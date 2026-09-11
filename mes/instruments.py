"""Tradable instruments and the factor model behind their fair values.

Five sector instruments. Their fair values are not drawn independently: each is
driven by a common market factor, a sector shock and its own idiosyncratic noise.
That structure is the point — correlation between sectors then *emerges* from a
shared driver instead of being imposed as a correlation matrix, and it changes
over time because the relative size of the three components does.

    d log F_i = drift_i
              + beta_i * market_shock
              + sector_shock_i
              + idio_vol_i * eps_i

A stock is an `Instrument` whose `sector` is not its own symbol: it inherits that
sector's shock and adds its own idiosyncratic term. `stocks_per_sector` switches
between the two worlds — at 0 the sectors themselves trade, above 0 the individual
stocks do and the sector becomes a factor rather than an instrument.

The hierarchy is the point. One shock per *sector*, shared by every stock in it, is
what makes two technology stocks correlate more strongly with each other than with
an energy stock — without any pairwise correlation being written down anywhere.
Drawing a separate "sector" shock per instrument, which an earlier version did, would
have made that impossible: the sector label would have been decoration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Instrument:
    symbol: str
    name: str
    sector: str  # a sector instrument is its own sector
    beta: float  # sensitivity to the common market factor
    idio_vol: float  # own volatility, as a share of the market factor's
    rate_sensitivity: float  # duration, for the central bank's valuation channel
    fundamental: float = 100.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "beta": self.beta,
            "fundamental": round(self.fundamental, 2),
        }


# Deliberately different characters, so the sectors are not five copies of each
# other: a high-beta growth sector prone to bubbles, a volatile commodity sector,
# a rate-sensitive financial sector, and two defensives.
SECTOR_SPEC: list[dict] = [
    {"symbol": "TECH", "name": "Technologie", "beta": 1.40, "idio_vol": 1.20, "rate_sensitivity": 1.80},
    {"symbol": "ENRG", "name": "Energie",     "beta": 0.90, "idio_vol": 1.40, "rate_sensitivity": 0.40},
    {"symbol": "FINL", "name": "Finanzen",    "beta": 1.20, "idio_vol": 0.90, "rate_sensitivity": 2.20},
    {"symbol": "HLTH", "name": "Gesundheit",  "beta": 0.70, "idio_vol": 0.60, "rate_sensitivity": 0.90},
    {"symbol": "CONS", "name": "Konsum",      "beta": 0.80, "idio_vol": 0.55, "rate_sensitivity": 1.00},
]


SECTOR_NAMES: dict[str, str] = {spec["symbol"]: spec["name"] for spec in SECTOR_SPEC}


def sector_name(symbol: str) -> str:
    """The German name of a sector, by its symbol.

    A sector keeps a name even when it stops being tradable: with
    `stocks_per_sector` above zero no instrument is called TECH, but the group of
    stocks is still Technologie and the index over them has to say so.
    """
    return SECTOR_NAMES.get(symbol, symbol)


def build(
    initial_price: float,
    symbols: list[str] | None = None,
    stocks_per_sector: int = 0,
    stock_idio_multiple: float = 1.8,
    rng: np.random.Generator | None = None,
) -> list[Instrument]:
    """Create the instrument list.

    `symbols` restricts which sectors take part — one symbol gives back the
    single-asset market the model was calibrated on.

    `stocks_per_sector` at 0 makes the sectors themselves tradable. Above 0, each
    sector is represented by that many individual stocks (`TECH-1`, `TECH-2`, …)
    and the sector is no longer an instrument, only a shared shock. A single stock
    is noisier than the index it belongs to, which is what `stock_idio_multiple`
    says: the index averages the idiosyncratic parts away, an individual name does
    not.
    """
    wanted = set(symbols) if symbols else None
    chosen = [spec for spec in SECTOR_SPEC if wanted is None or spec["symbol"] in wanted]
    if not chosen:
        raise ValueError(f"Keine bekannten Symbole in {symbols}")

    out = []
    for spec in chosen:
        if stocks_per_sector <= 0:
            out.append(Instrument(
                symbol=spec["symbol"], name=spec["name"], sector=spec["symbol"],
                beta=spec["beta"], idio_vol=spec["idio_vol"],
                rate_sensitivity=spec["rate_sensitivity"], fundamental=initial_price,
            ))
            continue

        for i in range(1, stocks_per_sector + 1):
            # Stocks in a sector are alike but not identical: their loadings vary
            # a little around the sector's, which is what makes the correlation
            # within a sector high rather than exactly one.
            jitter = (1.0, 1.0) if rng is None else (
                float(rng.uniform(0.8, 1.25)), float(rng.uniform(0.8, 1.25))
            )
            out.append(Instrument(
                symbol=f"{spec['symbol']}-{i}",
                name=f"{spec['name']} {i}",
                sector=spec["symbol"],
                beta=spec["beta"] * jitter[0],
                idio_vol=spec["idio_vol"] * stock_idio_multiple * jitter[1],
                rate_sensitivity=spec["rate_sensitivity"] * jitter[0],
                fundamental=initial_price,
            ))
    return out


@dataclass
class FactorWorld:
    """Advances every instrument's fair value one step.

    One common shock is drawn per step and shared, which is what couples the
    instruments. `sector_vol` scales the per-sector component; set it to zero and
    the sectors differ only through their betas, which makes them almost
    perfectly correlated — a useful check that the factor structure is doing the
    work rather than the labels.
    """

    instruments: list[Instrument]
    rng: np.random.Generator
    drift: float
    vol: float  # volatility of the common market factor, per step
    sector_vol: float = 0.6  # sector component, relative to the market factor
    market_factor: float = 0.0  # last common shock, for inspection
    # Per-symbol drift adjustment, set by the central bank each step. Kept
    # separate from `drift` so the policy channel is visible rather than folded
    # into a single number nobody can attribute.
    drift_adjust: dict = field(default_factory=dict)
    sector_shocks: dict = field(default_factory=dict)

    def sectors(self) -> list[str]:
        return list(dict.fromkeys(i.sector for i in self.instruments))

    def step(self) -> None:
        self.market_factor = float(self.rng.standard_normal()) * self.vol

        # One shock per sector, drawn once and shared by every instrument in it.
        # This is the whole hierarchy: two stocks in the same sector move together
        # because they are hit by the same number, not because a correlation was
        # configured between them.
        self.sector_shocks = {
            sector: float(self.rng.standard_normal()) * self.vol * self.sector_vol
            for sector in self.sectors()
        }

        for instrument in self.instruments:
            sector_shock = self.sector_shocks[instrument.sector]
            idio_shock = float(self.rng.standard_normal()) * self.vol * instrument.idio_vol
            change = (
                self.drift
                + self.drift_adjust.get(instrument.symbol, 0.0)
                + instrument.beta * self.market_factor
                + sector_shock
                + idio_shock
            )
            instrument.fundamental *= float(np.exp(change))
            # No second copy of the series is kept here. `Market.fundamentals`
            # already appends the identical value every step, and this one grew for
            # ever without a single reader — five lists of floats nobody could ask
            # for, at 240 entries a day per instrument.

    def apply_shock(self, symbol: str | None, magnitude: float) -> None:
        """A shock to one instrument, to a whole sector, or to everything.

        `symbol` may name an instrument (`TECH-1`), a sector (`TECH`, which hits
        every stock in it), or be None for market-wide news scaled by each
        instrument's beta.

        None of these spread the shock beyond what they name. When stress does
        cross from one market to another it goes through the agents' portfolios,
        not through this function.
        """
        for instrument in self.instruments:
            if symbol is None:
                instrument.fundamental *= float(np.exp(magnitude * instrument.beta))
            elif symbol in (instrument.symbol, instrument.sector):
                instrument.fundamental *= float(np.exp(magnitude))


def correlation_matrix(returns: dict[str, np.ndarray], window: int = 250) -> dict:
    """Rolling correlation of sector returns — the heatmap's input.

    Average correlation rising in a crisis is itself a stylized fact, so this is
    a measurement and not only a picture.
    """
    symbols = sorted(returns)
    series = [np.asarray(returns[s], dtype=float)[-window:] for s in symbols]
    length = min((len(s) for s in series), default=0)
    if length < 20:
        return {"symbols": symbols, "matrix": None, "average": None}

    trimmed = np.vstack([s[-length:] for s in series])
    if np.any(trimmed.std(axis=1) < 1e-12):
        return {"symbols": symbols, "matrix": None, "average": None}

    matrix = np.corrcoef(trimmed)
    off_diagonal = matrix[~np.eye(len(symbols), dtype=bool)]
    return {
        "symbols": symbols,
        "matrix": [[round(float(v), 3) for v in row] for row in matrix],
        "average": round(float(off_diagonal.mean()), 3),
    }


def correlation_within_and_across(returns: dict, sectors: dict, window: int = 250) -> dict:
    """Average correlation of pairs inside a sector against pairs across sectors.

    The falsifiable claim of the hierarchy: two stocks in the same sector should
    move together more than two stocks in different sectors, and nothing in the
    model says so directly. If these two numbers came out equal, the sector label
    would be decoration.
    """
    symbols = sorted(returns)
    series = {s: np.asarray(returns[s], dtype=float)[-window:] for s in symbols}
    length = min((len(v) for v in series.values()), default=0)
    if length < 20 or len(symbols) < 2:
        return {"within": None, "across": None, "pairs_within": 0, "pairs_across": 0}

    within, across = [], []
    for i, a in enumerate(symbols):
        for b in symbols[i + 1:]:
            x, y = series[a][-length:], series[b][-length:]
            if x.std() < 1e-12 or y.std() < 1e-12:
                continue
            rho = float(np.corrcoef(x, y)[0, 1])
            (within if sectors.get(a) == sectors.get(b) else across).append(rho)

    return {
        "within": round(float(np.mean(within)), 3) if within else None,
        "across": round(float(np.mean(across)), 3) if across else None,
        "pairs_within": len(within),
        "pairs_across": len(across),
    }
