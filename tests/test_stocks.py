"""Individual stocks inside sectors.

A stock is only something other than a sixth sector if it *shares* its sector's
shock. So the tests here are about the hierarchy, not about the naming: one shock
per sector, shared by its members, and a measurable consequence — two stocks in the
same sector move together more than two stocks in different ones, with no pairwise
correlation configured anywhere.

The control matters as much as the claim. `sector_vol = 0` removes the shared shock,
and the effect has to shrink; otherwise something else is producing it and the sector
label is decoration.
"""

import numpy as np
import pytest

from mes import Config, Simulation
from mes.instruments import build, correlation_within_and_across


def small(**kwargs) -> Config:
    base = dict(n_adaptive=60, n_noise=40, n_passive=6, n_leveraged=8,
                n_makers=3, seed=6, steps_per_day=40, stocks_per_sector=2)
    base.update(kwargs)
    return Config(**base)


def daily_fair(sim: Simulation) -> dict:
    """Fair values sampled once a day, as log returns."""
    spd = sim.cfg.steps_per_day
    return {
        symbol: np.diff(np.log(np.array(market.fundamentals[::spd])))
        for symbol, market in sim.markets.items()
    }


# --------------------------------------------------------------- construction
def test_stocks_are_named_and_grouped_by_sector():
    instruments = build(100.0, stocks_per_sector=3)
    assert len(instruments) == 15
    assert instruments[0].symbol == "TECH-1"
    assert instruments[0].sector == "TECH"
    by_sector = {}
    for instrument in instruments:
        by_sector.setdefault(instrument.sector, []).append(instrument.symbol)
    assert set(by_sector) == {"TECH", "ENRG", "FINL", "HLTH", "CONS"}
    assert all(len(v) == 3 for v in by_sector.values())


def test_the_default_still_trades_the_sectors_themselves():
    """The calibrated configuration must not change under this feature."""
    sim = Simulation(Config(seed=1))
    assert sim.symbols == ["TECH", "ENRG", "FINL", "HLTH", "CONS"]
    assert all(sim.sector_of[s] == s for s in sim.symbols)


def test_a_single_stock_is_noisier_than_its_index():
    """An index averages the idiosyncratic parts away; a single name does not."""
    stocks = build(100.0, stocks_per_sector=2, stock_idio_multiple=1.8)
    sectors = build(100.0, stocks_per_sector=0)
    tech_stock = next(i for i in stocks if i.sector == "TECH")
    tech_sector = next(i for i in sectors if i.symbol == "TECH")
    assert tech_stock.idio_vol > tech_sector.idio_vol


def test_stocks_in_a_sector_are_alike_but_not_identical():
    instruments = build(100.0, stocks_per_sector=3, rng=np.random.default_rng(2))
    tech = [i for i in instruments if i.sector == "TECH"]
    betas = [i.beta for i in tech]
    assert len(set(betas)) == len(betas), "the stocks are exact copies"
    assert max(betas) / min(betas) < 2.0, "the stocks of one sector differ too much"


# ------------------------------------------------------------ the shared shock
def test_one_shock_per_sector_shared_by_its_members():
    sim = Simulation(small(stocks_per_sector=3))
    sim.step()
    shocks = sim.factors.sector_shocks
    assert set(shocks) == set(sim.sectors), "one shock per sector expected"
    # Every member of a sector is hit by that sector's number, so there are five
    # distinct values for fifteen instruments.
    assert len(set(shocks.values())) == 5


def test_a_sector_headline_hits_every_stock_in_it():
    sim = Simulation(small())
    for _ in range(200):
        sim.step()
    before = {s: m.instrument.fundamental for s, m in sim.markets.items()}
    sim.inject_news("Regulator opens proceedings", -0.25, symbol="FINL")
    after = {s: m.instrument.fundamental for s, m in sim.markets.items()}

    for symbol in sim.sectors["FINL"]:
        assert after[symbol] < before[symbol] * 0.85, f"{symbol} not hit"
    for symbol in sim.symbols:
        if sim.sector_of[symbol] != "FINL":
            assert after[symbol] == before[symbol]


def test_a_headline_can_name_one_stock():
    sim = Simulation(small())
    for _ in range(200):
        sim.step()
    target = sim.sectors["TECH"][0]
    before = {s: m.instrument.fundamental for s, m in sim.markets.items()}
    sim.inject_news("Profit warning issued", -0.30, symbol=target)
    after = {s: m.instrument.fundamental for s, m in sim.markets.items()}

    assert after[target] < before[target] * 0.8
    for symbol in sim.symbols:
        if symbol != target:
            assert after[symbol] == before[symbol], f"{symbol} should be untouched"


# --------------------------------------------------- the measurable consequence
# Two stocks a sector rather than three, and a shorter run: fifteen instruments
# over thirty thousand steps took two and a half minutes on its own, and the
# statements below are about an ordering, which does not need that much data.
@pytest.fixture(scope="module")
def run() -> Simulation:
    sim = Simulation(small(stocks_per_sector=2))
    for _ in range(16_000):
        sim.step()
    return sim


def test_stocks_in_a_sector_correlate_more_than_across_sectors(run):
    """The claim, measured on fair values where the hierarchy lives."""
    result = correlation_within_and_across(daily_fair(run), run.sector_of)
    assert result["pairs_within"] > 0 and result["pairs_across"] > 0
    assert result["within"] > result["across"], (
        f"within {result['within']} not above across sectors {result['across']}"
    )


def test_the_factor_structure_is_attenuated_in_prices(run):
    """Prices carry far less of the hierarchy than fair values do.

    Each market's price is dominated by its own order flow, so only part of the
    factor structure reaches it. Over a long run (three stocks a sector, 40 000
    steps) the ordering does survive but shrinks to about a third: fair values gave
    0.322 within against 0.187 across, prices 0.069 against 0.027.

    What is *not* asserted is that the ordering holds in prices at this sample size.
    It does not reliably: with five within-sector pairs over sixty-odd days the
    price correlations are noise around zero and the sign flips between runs.
    Asserting it here would have made a green test out of a coin toss. The robust
    statement is the attenuation itself, and real markets show within-sector price
    correlations far above what this model produces — a limitation, not a detail.
    """
    fair = correlation_within_and_across(daily_fair(run), run.sector_of)
    price = correlation_within_and_across(run.sector_returns(), run.sector_of)
    assert fair["within"] > fair["across"]
    fair_gap = fair["within"] - fair["across"]
    price_gap = price["within"] - price["across"]
    assert price_gap < fair_gap, f"price gap {price_gap} not smaller than {fair_gap}"


def test_removing_the_shared_shock_shrinks_the_effect():
    """The control. Without a sector shock the gap has to narrow — if it did not,
    something other than the hierarchy would be producing it.

    It does not fall to zero, and the reason is worth knowing: stocks in a sector
    also carry similar betas, so they load on the common market factor alike.
    """
    def gap(sector_vol: float) -> float:
        sim = Simulation(small(stocks_per_sector=2, sector_vol=sector_vol))
        for _ in range(16_000):
            sim.step()
        result = correlation_within_and_across(daily_fair(sim), sim.sector_of)
        return result["within"] - result["across"]

    assert gap(0.6) > gap(0.0) * 1.5


# ----------------------------------------------------------------- sector index
def test_the_sector_index_averages_its_members(run):
    for sector, members in run.sectors.items():
        expected = sum(run.markets[s].price for s in members) / len(members)
        assert run.sector_index(sector) == pytest.approx(expected)
        assert run.sector_index(sector) > 0


def test_an_unknown_sector_has_no_index(run):
    assert run.sector_index("GOLD") == 0.0


def test_prices_and_bars_stay_sane_with_stocks(run):
    import math

    for market in run.markets.values():
        assert market.price > 0 and math.isfinite(market.price)
        assert market.bars, f"{market.symbol} without daily bars"
        assert all(math.isfinite(r) for r in market.daily_returns)
