"""The central bank and its three channels.

Each channel is tested in isolation, with the fair values' own volatility switched
off where it would otherwise drown the effect. That matters: at the calibrated
setting the fundamentals move 60 % a year on their own, and a rate channel worth a
few per cent is invisible against it — an early version of this module looked like
it worked when measured that way and did not.
"""

import numpy as np
import pytest

from mes import Config, Simulation
from mes.centralbank import CentralBank, per_step_decay


def quiet(**kwargs) -> Config:
    """A population small enough to be quick, with a still fair value so that a
    channel's effect is the only thing moving."""
    base = dict(
        n_adaptive=40, n_noise=30, n_passive=6, n_leveraged=6, n_makers=3,
        seed=9, steps_per_day=20,
        fundamental_vol=0.0, fundamental_vol_of_vol=0.0, fundamental_drift=0.0,
        macro_shock=0.0,
    )
    base.update(kwargs)
    return Config(**base)


# ---------------------------------------------------------------- the rule
def test_half_life_conversion_is_right():
    """Two half-lives of decay must leave a quarter."""
    decay = per_step_decay(half_life_days=10, steps_per_day=20)
    assert decay ** 200 == pytest.approx(0.5, rel=1e-6)
    assert decay ** 400 == pytest.approx(0.25, rel=1e-6)


def test_rate_starts_at_neutral():
    sim = Simulation(quiet(neutral_rate=0.03))
    assert sim.bank.rate == pytest.approx(0.03)


def test_taylor_rule_raises_the_rate_when_inflation_is_above_target():
    sim = Simulation(quiet())
    sim.bank.inflation = 0.06  # far above the 2 % target
    before = sim.bank.rate
    for _ in range(2000):
        sim.bank._set_rate()
    assert sim.bank.rate > before + 0.01


def test_taylor_rule_cuts_when_the_economy_is_cold():
    sim = Simulation(quiet())
    sim.bank.inflation = 0.0
    sim.bank.output_gap = -4.0
    for _ in range(2000):
        sim.bank._set_rate()
    assert sim.bank.rate < sim.cfg.neutral_rate


def test_rate_stays_within_bounds():
    sim = Simulation(quiet(max_rate=0.10))
    sim.bank.inflation = 0.50  # absurd, to push the rule past its ceiling
    for _ in range(5000):
        sim.bank._set_rate()
    assert 0.0 <= sim.bank.rate <= 0.10


def test_manual_mode_overrides_the_rule():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.07))
    sim.bank.inflation = 0.0  # the rule would cut hard
    for _ in range(500):
        sim.step()
    assert sim.bank.rate == pytest.approx(0.07)


def test_switching_the_bank_off_freezes_the_rate():
    sim = Simulation(quiet(cb_active=0))
    sim.bank.inflation = 0.09
    for _ in range(500):
        sim.step()
    assert sim.bank.rate == pytest.approx(sim.cfg.neutral_rate)


def test_the_economy_reacts_to_policy_with_a_lag():
    """A restrictive stance has to cool output — and not instantly, or the
    overshoot the model is meant to show could not happen."""
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.09, policy_lag_days=20))
    short = []
    for i in range(4000):
        sim.step()
        if i == 40:
            short.append(sim.bank.output_gap)
    assert abs(short[0]) < 0.5, "the effect arrived at once, without a lag"
    assert sim.bank.output_gap < -0.5, f"output gap {sim.bank.output_gap}"


# ------------------------------------------------------- channel: valuation
def test_a_rate_rise_lowers_fair_values_by_duration():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.02))
    for _ in range(50):
        sim.step()
    before = {s: m.instrument.fundamental for s, m in sim.markets.items()}

    sim.cfg.update_live({"cb_manual_rate": 0.04})  # +2 points
    for _ in range(50):
        sim.step()
    after = {s: m.instrument.fundamental for s, m in sim.markets.items()}

    for symbol, market in sim.markets.items():
        duration = sim.bank.duration(market.instrument.rate_sensitivity)
        expected = np.exp(-duration * 0.02)
        assert after[symbol] / before[symbol] == pytest.approx(expected, rel=1e-6)


def test_long_duration_sectors_fall_furthest():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.02))
    for _ in range(50):
        sim.step()
    before = {s: m.instrument.fundamental for s, m in sim.markets.items()}
    sim.cfg.update_live({"cb_manual_rate": 0.06})
    for _ in range(50):
        sim.step()
    drop = {s: 1 - m.instrument.fundamental / before[s] for s, m in sim.markets.items()}
    # FINL 2.2, TECH 1.8, CONS 1.0, HLTH 0.9, ENRG 0.4
    assert drop["FINL"] > drop["TECH"] > drop["CONS"] > drop["HLTH"] > drop["ENRG"]


def test_the_valuation_channel_is_reversible():
    """A hike followed by an equal cut has to leave fair value where it started.

    The first version of this channel applied a drag proportional to the *level*
    of the stance, which accumulated for as long as the rate stayed high and gave
    nothing back on the way down. Real valuations reprice once and stay there.
    """
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.02))
    for _ in range(50):
        sim.step()
    start = {s: m.instrument.fundamental for s, m in sim.markets.items()}

    sim.cfg.update_live({"cb_manual_rate": 0.08})
    for _ in range(2000):  # held high for a long time
        sim.step()
    high = {s: m.instrument.fundamental for s, m in sim.markets.items()}
    assert high["TECH"] < start["TECH"] * 0.7

    sim.cfg.update_live({"cb_manual_rate": 0.02})
    for _ in range(50):
        sim.step()
    for symbol in sim.symbols:
        assert sim.markets[symbol].instrument.fundamental == pytest.approx(start[symbol], rel=1e-6)


# --------------------------------------------------------- channel: funding
def test_borrowed_money_costs_interest():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.10, borrow_spread=0.02))
    for _ in range(50):
        sim.step()
    fund = next(a for a in sim.agents if a.kind == "leveraged")
    fund.cash = -100_000.0
    fund.positions = {sim.primary: 0}
    before = fund.cash
    for _ in range(200):
        sim.step()
    assert fund.cash < before, "credit costs nothing"


def test_a_higher_rate_costs_more():
    def erosion(rate: float) -> float:
        sim = Simulation(quiet(cb_manual=1, cb_manual_rate=rate, borrow_spread=0.0))
        for _ in range(20):
            sim.step()
        fund = next(a for a in sim.agents if a.kind == "leveraged")
        fund.cash, fund.positions = -100_000.0, {}
        for _ in range(400):
            sim.step()
        return -100_000.0 - fund.cash

    assert erosion(0.10) > erosion(0.02) * 3


def test_cash_savers_are_not_paid_interest():
    """One-sided on purpose: charging borrowers is the channel that matters for
    cascades, while paying every agent interest on idle cash would inject money
    into the market and change the calibration for a second-order effect.

    Checked on the charging step itself rather than over a run — an agent left to
    keep trading changes its own cash, which says nothing about interest.
    """
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.10))
    for _ in range(20):
        sim.step()
    for agent in sim.agents:
        agent.cash = 50_000.0
    sim._charge_funding()
    assert all(a.cash == pytest.approx(50_000.0) for a in sim.agents)

    for agent in sim.agents:
        agent.cash = -50_000.0
    sim._charge_funding()
    assert all(a.cash < -50_000.0 for a in sim.agents)


# ----------------------------------------------------------- channel: flows
def test_high_rates_dry_up_savings_plan_inflows():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.02))
    assert sim.bank.flow_multiplier() == pytest.approx(1.0)
    sim.cfg.update_live({"cb_manual_rate": 0.10})
    assert sim.bank.flow_multiplier() < 0.6


def test_the_flow_multiplier_never_goes_negative():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.15,
                           inflow_rate_sensitivity=30.0))
    assert sim.bank.flow_multiplier() == 0.0


def test_a_cut_below_neutral_increases_inflows():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.0, neutral_rate=0.03))
    assert sim.bank.flow_multiplier() > 1.0


# ------------------------------------------------------------------- report
def test_the_report_is_json_friendly_and_in_per_cent():
    sim = Simulation(quiet(cb_manual=1, cb_manual_rate=0.045))
    for _ in range(400):
        sim.step()
    report = sim.bank.to_dict()
    assert report["rate"] == pytest.approx(4.5)
    assert report["manual"] is True
    assert isinstance(report["history"], list)
    for key, value in report.items():
        assert not isinstance(value, (np.floating, np.integer)), f"{key} is not a Python type"


def test_a_reporting_cadence_of_zero_does_not_kill_the_clock():
    """`rate_report_days` is a real field, not in PARAM_SPEC, so `Config.from_dict`
    passes it straight through — and `t % (spd * 0)` raised ZeroDivisionError inside
    `step()`. The runner caught it, stopped the market and put "ZeroDivisionError"
    on screen. A reporting cadence is not something a run should die of."""
    sim = Simulation(Config.from_dict({**Config().to_dict(), "rate_report_days": 0,
                                       "n_adaptive": 10, "n_noise": 10, "n_passive": 2,
                                       "n_leveraged": 2, "n_makers": 2}))
    for _ in range(60):
        sim.step()
    assert sim.t == 60
    assert sim.bank.history, "without a cadence every step is reported"
