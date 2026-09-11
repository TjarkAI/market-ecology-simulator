"""Indices: the aggregate of a market that has no aggregate.

Every price in this project comes out of one order book. An index does not — it is
a measurement across several of them, and this module is the only place that
measurement is made, so nothing else has to decide what "the market" did.

**The weights are the ETF's.** `PassiveInvestor` buys `index_weight`, which is
`fundamental / sum(fundamentals)`, and that is the weighting used here. It is the
only index weighting the model already contains: a capitalisation weighting would
need a share count per instrument, and the number of shares in issue here is a
consequence of what the issuer sold, not a property of the instrument. Using the
ETF's own weights means the market index is the thing a passive investor in this
market actually holds, rather than a number invented for the chart.

**The index is chained, not a ratio of sums:**

    I_t = I_{t-1} · Σ_i w_{i,t-1} · (P_{i,t} / P_{i,t-1})

with `w_{i,t-1} = F_{i,t-1} / Σ_j F_{j,t-1}`. Real indices are chained for a reason
that applies here too: the weights move — fair values diffuse apart, and with
`stocks_per_sector` above zero instruments can differ by an order of magnitude in
level. A plain Σ P / Σ P₀ would then quietly turn into a price-weighted index, and
the sector with the largest number would dominate for no economic reason.

The same construction runs on the fair values, giving a fair-value index next to the
price index. The gap between the two is the aggregate version of the single
instrument's `stretch()`, and it is the one number that says whether the whole
market is above or below what it is worth.

Nothing here feeds back into the simulation. Indices are read out of prices that
already happened, draw no random numbers and change no state, so switching the
whole module off would produce a bit-identical run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .instruments import sector_name

BASE = 100.0

# How much per-step history to keep, in steps. The live chart needs a fine-grained
# recent window and nothing else does — the long view is served by the daily closes,
# which cost one float a day. Without a cap this would grow exactly like
# `Market.prices`: at 240 steps a day and a run left open for an afternoon at 16×,
# six indices × two series would reach tens of megabytes of floats nobody looks at.
MAX_STEPS = 14_400  # 60 trading days


@dataclass
class Index:
    """One index: its members, its level, and the fair-value index beside it."""

    key: str
    name: str
    kind: str  # "market" for the whole market, "sector" for one sector
    members: list[str]

    level: float = BASE
    fair: float = BASE
    levels: list[float] = field(default_factory=lambda: [BASE])
    fairs: list[float] = field(default_factory=lambda: [BASE])
    # One close a day, averaged over the end of the day the way `Market.update_bar`
    # averages an instrument's close, so index and instrument returns are measured
    # the same way and can be compared.
    closes: list[float] = field(default_factory=list)
    fair_closes: list[float] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    # Fair-value weight per member at the last step, for the read-out. These move,
    # which is the whole reason the index is chained.
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def gap(self) -> float:
        """How far the index sits above its fair-value index, as a fraction."""
        return self.level / max(self.fair, 1e-9) - 1.0

    def change(self, steps: int) -> float:
        """Return over the last `steps` steps, as a fraction. 0 if too short."""
        if len(self.levels) <= steps or steps <= 0:
            return 0.0
        past = self.levels[-1 - steps]
        return self.level / max(past, 1e-9) - 1.0

    @property
    def total_change(self) -> float:
        return self.level / BASE - 1.0

    def annualised_vol(self) -> float | None:
        """From daily returns, which is the frequency the stylized facts live at."""
        if len(self.daily_returns) < 20:
            return None
        return float(np.std(self.daily_returns) * math.sqrt(252))

    def max_drawdown(self) -> float | None:
        if len(self.closes) < 20:
            return None
        series = np.asarray(self.closes, dtype=float)
        peak = np.maximum.accumulate(series)
        return float((series / peak - 1.0).min())


class IndexBook:
    """Every index of one simulation, advanced once per step.

    Built from the simulation's own sector map, so the set of indices follows
    `stocks_per_sector` without anything here knowing about it: with sector
    instruments a sector index has one member and is that instrument rebased, with
    individual stocks it is the aggregate the sector no longer trades as.
    """

    def __init__(self, markets: dict, sectors: dict[str, list[str]]) -> None:
        self.symbols = list(markets)
        self.indices: list[Index] = [
            Index(key="MKT", name="Gesamtmarkt", kind="market", members=list(markets))
        ]
        for sector, members in sectors.items():
            self.indices.append(
                Index(key=sector, name=sector_name(sector), kind="sector",
                      members=list(members))
            )
        self.by_key = {index.key: index for index in self.indices}

        self._prev_price = {s: m.price for s, m in markets.items()}
        self._prev_fair = {s: m.instrument.fundamental for s, m in markets.items()}
        self._prev_close: dict[str, float] = {}
        self._set_weights()

    def _set_weights(self) -> None:
        for index in self.indices:
            total = sum(max(self._prev_fair[s], 0.0) for s in index.members) or 1.0
            index.weights = {s: max(self._prev_fair[s], 0.0) / total for s in index.members}

    # ---------------------------------------------------------------- per step
    def step(self, markets: dict, t: int, steps_per_day: int) -> None:
        price = {s: m.price for s, m in markets.items()}
        fair = {s: m.instrument.fundamental for s, m in markets.items()}

        for index in self.indices:
            weighted_price = weighted_fair = total = 0.0
            for symbol in index.members:
                weight = max(self._prev_fair.get(symbol, 0.0), 0.0)
                if weight <= 0.0:
                    continue
                total += weight
                weighted_price += weight * price[symbol] / max(self._prev_price[symbol], 1e-9)
                weighted_fair += weight * fair[symbol] / max(self._prev_fair[symbol], 1e-9)
            if total > 0.0:
                index.level *= weighted_price / total
                index.fair *= weighted_fair / total
            index.levels.append(index.level)
            index.fairs.append(index.fair)
            # Trimmed in blocks rather than every step: `del list[:-n]` moves every
            # remaining element, so trimming at each append would cost more than the
            # whole index calculation.
            if len(index.levels) > 2 * MAX_STEPS:
                del index.levels[:-MAX_STEPS]
                del index.fairs[:-MAX_STEPS]

        self._prev_price = price
        self._prev_fair = fair
        self._set_weights()

        if steps_per_day > 0 and t % steps_per_day == 0:
            self._close_day(steps_per_day)

    def _close_day(self, steps_per_day: int) -> None:
        window = max(1, steps_per_day // 20)
        for index in self.indices:
            close = float(np.mean(index.levels[-window:]))
            index.closes.append(close)
            index.fair_closes.append(float(np.mean(index.fairs[-window:])))
            previous = self._prev_close.get(index.key)
            if previous is not None:
                index.daily_returns.append(
                    math.log(max(close, 1e-9) / max(previous, 1e-9))
                )
            self._prev_close[index.key] = close


# ----------------------------------------------------------------- statistics
def beta(index_returns: list[float], market_returns: list[float]) -> float | None:
    """Realised beta of an index against the market index, from daily returns.

    Worth reading against the beta the factor model was *given*: the sector betas in
    `SECTOR_SPEC` act on the fair values, and whether they survive the journey into
    the prices is a question about the model, not a setting. They largely do not —
    the same attenuation the README reports for the correlations — and a number that
    says so is more use than one that hides it.
    """
    n = min(len(index_returns), len(market_returns))
    if n < 20:
        return None
    x = np.asarray(market_returns[-n:], dtype=float)
    y = np.asarray(index_returns[-n:], dtype=float)
    var = float(x.var())
    if var < 1e-18:
        return None
    return float(((x - x.mean()) * (y - y.mean())).mean() / var)


def correlation(index_returns: list[float], market_returns: list[float]) -> float | None:
    n = min(len(index_returns), len(market_returns))
    if n < 20:
        return None
    x = np.asarray(market_returns[-n:], dtype=float)
    y = np.asarray(index_returns[-n:], dtype=float)
    if x.std() < 1e-12 or y.std() < 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def sample(series: list[float], n: int) -> list[float]:
    """At most `n` points out of `series`, evenly spaced, last point always kept.

    A chart 700 px wide cannot show 14 400 points, and sending them costs more than
    drawing them. Striding from the end keeps the newest value exactly rather than
    letting it fall between two samples, which is what makes a live chart's last
    point disagree with the number printed beside it.
    """
    if n <= 0 or not series:
        return []
    if len(series) <= n:
        return list(series)
    stride = -(-len(series) // n)  # ceil
    # Offset so that the final element lands on the grid: (len-1) ≡ start (mod stride).
    return series[(len(series) - 1) % stride::stride]
