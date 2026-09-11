"""One instrument's market: its book, its price history, its daily bars.

Splitting this out of `Simulation` is what makes several instruments possible
without duplicating the loop. Everything here is per-instrument; anything that
spans instruments — portfolios, margin, strategy switching — stays in
`Simulation`, because that is exactly where the interesting couplings live.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .instruments import Instrument
from .orderbook import BUY, SELL, OrderBook


@dataclass
class Market:
    instrument: Instrument
    tick: float = 0.01

    def __post_init__(self):
        price = self.instrument.fundamental
        self.book = OrderBook(tick=self.tick)
        self.price = price  # mark price = mid of the book
        self.last_trade = price  # last actual execution, for the tape
        self.prices: list[float] = [price]
        self.fundamentals: list[float] = [price]
        self.volumes: list[int] = [0]
        self.returns: list[float] = [0.0]
        self.trend = 0.0
        self.realized_vol = 0.0
        # What a valuation-driven agent believes the asset is worth: a lagged view
        # of the fair value, not the fair value itself. Nobody learns a fundamental
        # the instant it changes — estimates arrive with reports and get revised.
        # Modelling it as instantaneous made every correction land inside a day,
        # which is where the negative daily autocorrelation came from.
        self.perceived_fair = price

        # Daily bars. One step is a market period, not a day: the stylized facts
        # are properties of *daily* returns, and at the single-step level
        # microstructure dominates.
        self.bars: list[dict] = []
        self.daily_returns: list[float] = []
        self._day = {"o": price, "h": price, "l": price, "v": 0}

        self.step_volume = 0
        self.step_trades = 0
        # Orders accepted into *this* book this step. `Simulation.step_orders`
        # counts them across every market, which is the right number for the town's
        # activity read-out and the wrong one next to a per-market trade count.
        self.step_orders = 0
        self.step_fills: list[dict] = []
        self.recent_trades: list[dict] = []

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    # ------------------------------------------------------------ per step
    def begin_step(self, t: int) -> None:
        self.book.expire(t)
        self.step_volume = 0
        self.step_trades = 0
        self.step_orders = 0
        self.step_fills = []

    def record_fill(self, trade) -> None:
        self.last_trade = trade.price
        self.step_trades += 1
        self.step_volume += trade.qty
        fill = {
            "ts": trade.ts,
            "symbol": self.symbol,
            "price": round(trade.price, 2),
            "qty": trade.qty,
            "side": trade.aggressor_side,
        }
        self.step_fills.append(fill)
        self.recent_trades.append(fill)
        del self.recent_trades[:-60]

    def update_perception(self, cfg) -> None:
        """Advance the lagged view of fair value one step.

        At a lag of zero the estimate *is* the fair value, which is the default.
        The lag was added on the hypothesis that instantaneous knowledge was what
        made every correction land inside a day, and therefore the source of the
        negative daily autocorrelation. It was not: with a lag the price trends
        instead of reverting, it drifts further from fair value, the sector
        correlation falls and the margin cascade stops firing. Measured at half-lives
        of 0.5, 12 and 30 days, all worse than no lag on five of the six criteria.

        Kept as a knob because the mechanism is real — nobody learns a fundamental
        the instant it changes — and because a failed hypothesis is easier to trust
        when you can re-run it.
        """
        if cfg.perception_lag_days <= 0:
            self.perceived_fair = self.instrument.fundamental
            return
        half_life = max(1.0, cfg.perception_lag_days * max(1, cfg.steps_per_day))
        decay = 0.5 ** (1.0 / half_life)
        self.perceived_fair = (decay * self.perceived_fair
                               + (1 - decay) * self.instrument.fundamental)

    def end_step(self, cfg) -> float:
        """Mark to the mid, update the trend, append the series. Returns the
        step's log return.

        The official price is the mid of the book, not the last trade. Marking to
        the last trade makes the series bounce between bid and ask, which injects
        a strong negative autocorrelation that has nothing to do with how the
        agents behave.
        """
        previous = self.prices[-1]
        self.price = self.book.mid(self.price)

        ret = math.log(max(self.price, 1e-9) / max(previous, 1e-9))
        alpha = 2.0 / (cfg.chartist_window + 1.0)
        self.trend = (1 - alpha) * self.trend + alpha * ret
        self.realized_vol = 0.97 * self.realized_vol + 0.03 * abs(ret)

        self.prices.append(self.price)
        self.fundamentals.append(self.instrument.fundamental)
        self.volumes.append(self.step_volume)
        self.returns.append(ret)
        return ret

    def update_bar(self, t: int, cfg) -> None:
        day = self._day
        day["h"] = max(day["h"], self.price)
        day["l"] = min(day["l"], self.price)
        day["v"] += self.step_volume

        if t % max(1, cfg.steps_per_day) != 0:
            return

        # The close is averaged over the last few steps rather than sampled at the
        # final instant. The mid flickers as quotes arrive, expire and are
        # re-priced, so a single-instant close carries an independent measurement
        # error in every bar — real closing prices come out of an auction, which
        # aggregates in just this way.
        window = max(1, cfg.steps_per_day // 20)
        close = float(np.mean(self.prices[-window:]))

        self.bars.append({
            "t": len(self.bars),
            "step": t,
            "symbol": self.symbol,
            "o": round(day["o"], 2),
            "h": round(day["h"], 2),
            "l": round(day["l"], 2),
            "c": round(close, 2),
            "v": day["v"],
        })
        if len(self.bars) > 1:
            previous_close = self.bars[-2]["c"]
            self.daily_returns.append(math.log(max(close, 1e-9) / max(previous_close, 1e-9)))
        self._day = {"o": close, "h": close, "l": close, "v": 0}

    # -------------------------------------------------------------- helpers
    def seed_book(self, rng) -> None:
        """Starting liquidity. These orders belong to no agent, so trades against
        them create shares out of nothing; they expire well before any
        measurement."""
        price = self.instrument.fundamental
        for i in range(1, 16):
            self.book.submit(0, -1, BUY, int(rng.integers(5, 40)), price * (1 - 0.002 * i), lifetime=200)
            self.book.submit(0, -1, SELL, int(rng.integers(5, 40)), price * (1 + 0.002 * i), lifetime=200)

    def depth(self) -> tuple[int, int]:
        return self.book.resting_qty(SELL), self.book.resting_qty(BUY)

    def stretch(self) -> float:
        """How far the price sits from fair value, in log terms."""
        return math.log(max(self.price, 1e-9) / max(self.instrument.fundamental, 1e-9))
