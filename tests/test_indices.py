"""The aggregate view of a market that has no aggregate.

An index here is a measurement, so the tests are about the measurement being
right rather than about the number being pleasant: a chained fair-value-weighted
index has to reduce to a plain price ratio when a sector holds one instrument, it
has to stay between its best and worst member, and it must not touch the
simulation it is reading. The last one is the important one — an index that
consumed a random number would make every run with this module differ from every
run without it, and the whole project rests on a seed reproducing a world.
"""

from __future__ import annotations

import numpy as np
import pytest

from mes import Config, Simulation
from mes import indices as ix


def small(**kwargs) -> Config:
    base = dict(n_adaptive=60, n_noise=40, n_passive=6, n_leveraged=6,
                n_makers=4, seed=5, steps_per_day=40)
    base.update(kwargs)
    return Config(**base)


@pytest.fixture(scope="module")
def sim() -> Simulation:
    s = Simulation(small())
    for _ in range(1200):  # 30 trading days at steps_per_day=40
        s.step()
    return s


# ------------------------------------------------------------------ the shape
def test_a_fresh_run_starts_every_index_at_the_base():
    fresh = Simulation(small())
    assert [i.level for i in fresh.indices.indices] == [ix.BASE] * 6
    assert [i.fair for i in fresh.indices.indices] == [ix.BASE] * 6


def test_there_is_one_market_index_and_one_per_sector(sim):
    keys = [i.key for i in sim.indices.indices]
    assert keys[0] == "MKT"
    assert sorted(keys[1:]) == sorted(sim.sectors)
    assert sim.indices.by_key["MKT"].members == sim.symbols
    assert sim.indices.by_key["MKT"].kind == "market"


def test_a_sector_index_carries_the_sector_name(sim):
    assert sim.indices.by_key["TECH"].name == "Technologie"


def test_the_level_series_grows_one_point_per_step(sim):
    assert len(sim.indices.by_key["MKT"].levels) == sim.t + 1


def test_daily_closes_appear_once_a_day(sim):
    market = sim.indices.by_key["MKT"]
    assert len(market.closes) == sim.t // sim.cfg.steps_per_day
    # One return between consecutive closes, so one fewer than the closes.
    assert len(market.daily_returns) == len(market.closes) - 1
    assert len(market.fair_closes) == len(market.closes)


# ------------------------------------------------------------- the arithmetic
def test_a_one_member_index_is_that_price_rebased(sim):
    """With sector instruments a sector holds exactly one member, and then the
    chained product of price ratios must telescope to the plain ratio. If it does
    not, the chaining is wrong somewhere and the multi-member case cannot be
    trusted either — that case has no independent reference to check against."""
    for symbol in sim.symbols:
        market = sim.markets[symbol]
        index = sim.indices.by_key[symbol]
        expected = market.price / market.prices[0] * ix.BASE
        assert index.level == pytest.approx(expected, rel=1e-9)
        fair = market.instrument.fundamental / market.fundamentals[0] * ix.BASE
        assert index.fair == pytest.approx(fair, rel=1e-9)


def test_the_market_index_lies_between_its_best_and_worst_member(sim):
    """A weighted average of member relatives cannot leave their range. It is the
    cheapest check that the weights are weights: a bug that lets one of them go
    negative or lets the normalisation drift shows up here immediately."""
    members = [sim.indices.by_key[s].total_change for s in sim.symbols]
    total = sim.indices.by_key["MKT"].total_change
    assert min(members) - 1e-9 <= total <= max(members) + 1e-9


def test_the_weights_are_the_etf_weights(sim):
    """`PassiveInvestor` buys `fundamental / sum(fundamentals)`. The index is
    weighted by the same number, and that is a claim worth pinning down rather
    than leaving in a docstring."""
    total = sum(m.instrument.fundamental for m in sim.markets.values())
    weights = sim.indices.by_key["MKT"].weights
    for symbol, market in sim.markets.items():
        assert weights[symbol] == pytest.approx(
            market.instrument.fundamental / total, rel=1e-9)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_the_gap_is_the_price_index_against_the_fair_index(sim):
    market = sim.indices.by_key["MKT"]
    assert market.gap == pytest.approx(market.level / market.fair - 1.0)


def test_change_over_a_horizon_longer_than_the_history_is_zero():
    fresh = Simulation(small())
    for _ in range(10):
        fresh.step()
    assert fresh.indices.by_key["MKT"].change(10_000) == 0.0


# ----------------------------------------------------- several stocks a sector
def test_a_sector_index_aggregates_several_stocks():
    """Above `stocks_per_sector` = 0 the sector is not tradable and the index is
    the only thing that can be quoted for it — so it has to be an aggregate rather
    than any single member."""
    sim = Simulation(small(stocks_per_sector=2))
    for _ in range(400):
        sim.step()

    tech = sim.indices.by_key["TECH"]
    assert tech.members == ["TECH-1", "TECH-2"]
    assert len(sim.indices.by_key["MKT"].members) == 10

    levels = [sim.markets[s].price / sim.markets[s].prices[0] * ix.BASE
              for s in tech.members]
    assert min(levels) - 1e-9 <= tech.level <= max(levels) + 1e-9
    # Not simply one of them: the aggregate has to be doing work.
    assert abs(levels[0] - levels[1]) > 1e-6


# ------------------------------------------------------------ non-interference
def test_the_index_book_draws_no_random_numbers():
    """The whole project rests on a seed reproducing a world. A module that reads
    prices must not consume from the stream that produces them."""
    sim = Simulation(small())
    for _ in range(50):
        sim.step()
    before = sim.rng.bit_generator.state
    sim.indices.step(sim.markets, sim.t, sim.cfg.steps_per_day)
    assert sim.rng.bit_generator.state == before


def test_two_runs_of_one_seed_give_the_same_index():
    a, b = Simulation(small()), Simulation(small())
    for _ in range(300):
        a.step()
        b.step()
    assert a.indices.by_key["MKT"].levels == b.indices.by_key["MKT"].levels


def test_a_reset_starts_the_index_over():
    """`Runner.reset` builds a fresh simulation; a stale index book would carry a
    level from the previous run into a new one and nothing on screen would say so."""
    sim = Simulation(small())
    for _ in range(200):
        sim.step()
    assert sim.indices.by_key["MKT"].level != ix.BASE
    sim.reset()
    assert sim.indices.by_key["MKT"].level == ix.BASE
    assert sim.indices.by_key["MKT"].closes == []


# -------------------------------------------------------------------- memory
def test_the_step_history_is_capped(monkeypatch):
    """`Market.prices` grows for ever, which is a known cost of the design. The
    index does not have to repeat it: the long view is served by the daily closes
    at one float a day, so the fine-grained series is a rolling window."""
    monkeypatch.setattr(ix, "MAX_STEPS", 30)
    sim = Simulation(small(steps_per_day=10))
    for _ in range(200):
        sim.step()
    market = sim.indices.by_key["MKT"]
    assert len(market.levels) <= 2 * 30 + 1
    assert len(market.fairs) == len(market.levels)
    # The daily series is not capped, because that is what the long chart reads.
    assert len(market.closes) == 20


# ------------------------------------------------------------------ sampling
def test_sample_never_exceeds_the_cap_and_keeps_the_last_point():
    for length in (1, 2, 7, 99, 100, 101, 1000, 14_400):
        series = list(range(length))
        for cap in (1, 10, 37, 400):
            out = ix.sample(series, cap)
            assert len(out) <= cap, (length, cap, len(out))
            assert out[-1] == series[-1], (length, cap)
            assert out == sorted(out), "die Reihenfolge muss erhalten bleiben"


def test_sample_returns_the_series_when_it_is_short_enough():
    assert ix.sample([1, 2, 3], 10) == [1, 2, 3]
    assert ix.sample([], 10) == []
    assert ix.sample([1, 2, 3], 0) == []


# --------------------------------------------------------------- the statistics
def test_beta_and_correlation_need_twenty_observations():
    short = list(np.random.default_rng(1).standard_normal(19))
    assert ix.beta(short, short) is None
    assert ix.correlation(short, short) is None


def test_beta_of_a_series_on_itself_is_one():
    series = list(np.random.default_rng(2).standard_normal(60))
    assert ix.beta(series, series) == pytest.approx(1.0)
    assert ix.correlation(series, series) == pytest.approx(1.0)


def test_beta_recovers_a_known_loading():
    rng = np.random.default_rng(3)
    market = rng.standard_normal(400)
    sector = 1.6 * market + 0.05 * rng.standard_normal(400)
    assert ix.beta(list(sector), list(market)) == pytest.approx(1.6, abs=0.05)


def test_a_flat_market_has_no_beta():
    """Dividing by a zero variance has to give "not measurable", not an exception
    and not an enormous number."""
    assert ix.beta([1.0] * 40, [0.0] * 40) is None
    assert ix.correlation([1.0] * 40, [0.0] * 40) is None


def test_the_volatility_and_drawdown_need_twenty_days():
    sim = Simulation(small(steps_per_day=40))
    for _ in range(10 * 40):
        sim.step()
    market = sim.indices.by_key["MKT"]
    assert market.annualised_vol() is None
    assert market.max_drawdown() is None

    for _ in range(20 * 40):
        sim.step()
    assert market.annualised_vol() > 0
    assert market.max_drawdown() <= 0
