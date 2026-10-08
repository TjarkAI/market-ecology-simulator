"""Invariants, not numbers.

These tests say nothing about whether the model is a good model — that is what
scripts/calibrate.py and metrics.py are for. They check that it is a *consistent*
one: that shares are not created out of nothing, that nobody spends money they do
not have, and that the same seed produces the same run. A model that violates
these is wrong no matter how plausible its output looks.
"""

import math

import pytest

from mes import Config, Simulation

# The seeded starting book belongs to no agent, so trades against it do create
# and destroy shares. It expires at step 200; measurements start after that.
SEED_BOOK_GONE = 250


def small(**kwargs) -> Config:
    """A small, fast population — these tests check logic, not statistics."""
    base = dict(n_adaptive=60, n_noise=40, n_passive=6, n_leveraged=6, n_makers=4, seed=7)
    base.update(kwargs)
    return Config(**base)


@pytest.fixture
def sim() -> Simulation:
    s = Simulation(small())
    for _ in range(SEED_BOOK_GONE):
        s.step()
    return s


def total_shares(sim: Simulation) -> int:
    return sum(a.shares for a in sim.agents)


def test_same_seed_same_run():
    a, b = Simulation(small()), Simulation(small())
    for _ in range(400):
        a.step()
        b.step()
    assert a.prices == b.prices
    assert a.chartist_share() == b.chartist_share()


def test_different_seed_different_run():
    a, b = Simulation(small(seed=1)), Simulation(small(seed=2))
    for _ in range(400):
        a.step()
        b.step()
    assert a.prices != b.prices


def test_shares_are_conserved_between_agents(sim):
    """Every trade moves shares from one agent to another. The only legitimate
    change in the total is the issuer creating or retiring float, so measuring
    with issuance switched off must give an exactly constant total.

    This was hollow twice over. `n_companies` was declared and never read, so the
    "switched off" arm ran with five issuers; and `total_shares` sums every agent
    *including* the issuer, whose negative position is the float — issuing 130
    shares moves the company to −130 and the buyer to +130 and leaves the total
    untouched. It could not fail for the reason it names. Both are fixed, and the
    control below is what makes this arm mean something.
    """
    quiet = Simulation(small(n_companies=0))
    assert not [a for a in quiet.agents if a.kind == "company"], \
        "n_companies=0 must really remove the issuer"
    for _ in range(SEED_BOOK_GONE):
        quiet.step()
    before = total_shares(quiet)
    for _ in range(500):
        quiet.step()
    assert total_shares(quiet) == before


def test_the_issuer_is_the_only_source_of_new_float():
    """The control: with an issuer present the stock held by everyone else grows,
    and by exactly what the issuer went short. Measured on non-issuers, because a
    total that includes the counterparty of every share cannot see issuance."""
    loud = Simulation(small(n_companies=1, issue_threshold=0.02))
    for _ in range(SEED_BOOK_GONE):
        loud.step()

    others = lambda s: sum(a.shares for a in s.agents if a.kind != "company")
    issued = lambda s: -sum(a.shares for a in s.agents if a.kind == "company")

    before, before_issued = others(loud), issued(loud)
    for _ in range(2000):
        loud.step()

    assert others(loud) - before == issued(loud) - before_issued, "shares out of nowhere"
    assert others(loud) != before, "the issuer moved nothing in 2,000 steps"


def test_only_makers_and_issuer_may_go_short(sim):
    for _ in range(500):
        sim.step()
    for agent in sim.agents:
        if agent.kind in ("maker", "company"):
            continue
        assert agent.shares >= 0, f"{agent.kind} #{agent.aid} holds {agent.shares} shares"


def test_only_leveraged_funds_may_borrow(sim):
    """Everyone else is capped at their cash when buying, so cash cannot go
    negative for them."""
    for _ in range(500):
        sim.step()
    for agent in sim.agents:
        if agent.kind == "leveraged":
            continue
        assert agent.cash > -1e-6, f"{agent.kind} #{agent.aid} has €{agent.cash:,.2f} in cash"


def test_market_makers_respect_their_inventory_limit(sim):
    for _ in range(800):
        sim.step()
    limit = sim.cfg.mm_inventory_limit
    for maker in sim.makers:
        assert maker.shares >= -limit


def test_prices_stay_finite_and_positive(sim):
    for _ in range(800):
        sim.step()
    assert all(p > 0 and math.isfinite(p) for p in sim.prices)
    assert all(math.isfinite(r) for r in sim.returns)
    assert all(math.isfinite(r) for r in sim.daily_returns)


def test_bars_are_well_formed(sim):
    for _ in range(sim.cfg.steps_per_day * 4):
        sim.step()
    assert sim.bars, "no daily bars produced"
    for bar in sim.bars:
        assert bar["l"] <= bar["o"] <= bar["h"]
        assert bar["l"] <= bar["c"] <= bar["h"]
        assert bar["v"] >= 0
    # One return per bar after the first.
    assert len(sim.daily_returns) == len(sim.bars) - 1


def test_margin_call_reduces_the_position():
    """A fund below its maintenance margin must end up smaller, not merely be
    logged. This is the cascade mechanism, so it has to actually sell."""
    sim = Simulation(small(max_leverage=5.0, maintenance_margin=0.5))
    for _ in range(300):
        sim.step()
    fund = next(a for a in sim.agents if a.kind == "leveraged")
    # `shares` is the total across instruments and read-only; a position is set
    # per instrument now.
    fund.positions = {sim.primary: 4000}
    fund.cash = -4000 * sim.price * 0.9  # deeply underwater
    before = fund.shares
    for _ in range(30):
        sim.step()
    assert fund.shares < before
    assert sim.margin_calls > 0


def test_live_parameters_apply_without_reset(sim):
    applied = sim.cfg.update_live({"chartist_aggression": 42.0})
    assert "chartist_aggression" in applied
    assert sim.cfg.chartist_aggression == 42.0


def test_structural_parameters_are_rejected_as_live(sim):
    """`n_adaptive` cannot change mid-run: the population is built at reset."""
    before = sim.cfg.n_adaptive
    applied = sim.cfg.update_live({"n_adaptive": 999})
    assert applied == []
    assert sim.cfg.n_adaptive == before


def test_empty_population_does_not_crash():
    sim = Simulation(small(n_adaptive=0, n_noise=0, n_passive=0, n_leveraged=0, n_makers=1))
    for _ in range(200):
        sim.step()
    assert sim.price > 0


def test_news_moves_the_world_but_not_the_price_directly(sim):
    """A headline changes fair value and mood. The price may only move because
    agents traded on it — that separation is the point of the model."""
    price_before = sim.price
    fair_before = sim.fair
    sim.inject_news("Test headline", -0.20)
    assert sim.fair < fair_before
    assert sim.price == price_before
