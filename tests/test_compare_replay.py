"""Comparing two configurations, and replaying a recorded run.

The replay tests are the strict ones: a replay is only worth having if it
reconstructs the run exactly, so they check identity against the recording rather
than similarity.

The comparison tests are deliberately modest, and the reason is in `mes/compare.py`:
two arms from the same seed do not stay on the same random path, so there is no
assertion here that a parameter change produces a particular difference. What is
checked is that the machinery reports honestly — including the signal-to-noise
figure that says when a difference is smaller than the seed spread.
"""

import numpy as np
import pytest

from mes import Config, Simulation
from mes.compare import Arm, Comparison, sweep_pair
from mes.recorder import Recorder, Replay, load


def tiny(**kwargs) -> Config:
    base = dict(n_adaptive=40, n_noise=30, n_passive=4, n_leveraged=4,
                n_makers=3, seed=21, steps_per_day=20)
    base.update(kwargs)
    return Config(**base)


def recorded(tmp_path, steps: int = 600, **kwargs):
    cfg = tiny(**kwargs)
    sim = Simulation(cfg)
    rec = Recorder()
    for _ in range(steps):
        sim.step()
        rec.capture(sim)
    return rec.save(sim, "demo", "20260101-000000", root=tmp_path), rec


# ------------------------------------------------------------------- replay
def test_a_replay_reconstructs_the_run_exactly(tmp_path):
    """Not "close to" — the same. The recording stores the seed, so the replay is
    the run rather than a summary of it."""
    path, rec = recorded(tmp_path)
    replay = Replay.open(path)

    for step in (1, 200, 599, 600):
        replay.seek(step)
        assert replay.sim.price == pytest.approx(rec.price[step - 1], abs=1e-12)


def test_seeking_backwards_is_exact_too(tmp_path):
    """Forwards is incremental, backwards restarts from zero — and has to land on
    the same number as if it had never gone past."""
    path, rec = recorded(tmp_path)
    replay = Replay.open(path)
    replay.seek(600)
    replay.seek(150)
    assert replay.position == 150
    assert replay.sim.price == pytest.approx(rec.price[149], abs=1e-12)


def test_seeking_is_clamped_to_the_recording(tmp_path):
    path, _ = recorded(tmp_path)
    replay = Replay.open(path)
    assert replay.seek(10_000) == replay.total
    assert replay.seek(-5) == 0


def test_replay_reports_its_position_in_days(tmp_path):
    path, _ = recorded(tmp_path, steps=600)
    replay = Replay.open(path)
    replay.seek(300)
    state = replay.to_dict()
    assert state["position"] == 300
    assert state["total"] == 600
    assert state["day"] == 300 // 20
    assert state["days_total"] == 30
    assert state["progress"] == pytest.approx(0.5)
    assert state["seed"] == 21


def test_advance_moves_forward(tmp_path):
    path, _ = recorded(tmp_path)
    replay = Replay.open(path)
    replay.advance(50)
    replay.advance(50)
    assert replay.position == 100


def test_a_replay_carries_the_whole_state_not_only_curves(tmp_path):
    """The reason for recomputing instead of reading a series back: the book and
    the agents exist at every position."""
    path, _ = recorded(tmp_path)
    replay = Replay.open(path)
    replay.seek(400)
    assert replay.sim.agents
    assert replay.sim.book.resting_qty(1) >= 0
    # `A == B or B` is true whenever B is non-empty, so this asserted only that the
    # dictionary had something in it. The count is the claim.
    expected = len(replay.cfg.symbols) if replay.cfg.symbols else 5
    assert len(replay.sim.markets) == expected


def test_a_scenario_recording_replays_as_that_scenario(tmp_path):
    from mes import scenarios

    cfg = tiny()
    sim = Simulation(cfg)
    sim.load_scenario(scenarios.get("calm"))
    rec = Recorder()
    for _ in range(300):
        sim.step()
        rec.capture(sim)
    path = rec.save(sim, "szenario", "20260101-000001", root=tmp_path)
    assert load(path)["meta"]["scenario"] == "calm"
    # The config stored is the scenario's, so replaying it reproduces those
    # conditions without needing the scenario definition again.
    replay = Replay.open(path)
    assert replay.cfg.chartist_aggression == scenarios.get("calm").overrides["chartist_aggression"]


def test_a_recording_keeps_the_scenarios_timeline(tmp_path):
    """A scenario is conditions *and* scheduled headlines, and only the conditions
    were written down. `script` is consumed as the run passes each entry, so by the
    time the recorder saved it there was nothing left to save — and the recording
    replayed as a quiet market under the same seed, with nothing in the file to say
    a single headline had gone missing."""
    from mes import scenarios

    scenario = scenarios.get("news_shock")
    assert scenario.timeline, "dieses Szenario braucht eine Zeitleiste"

    sim = Simulation(tiny())
    sim.load_scenario(scenario)
    for _ in range(300):
        sim.step()
    assert not sim.script, "die Zeitleiste ist im Lauf abgearbeitet worden"

    path = rec_and_save(sim, tmp_path)
    stored = load(path)["meta"]["script"]
    assert len(stored) == len(scenario.timeline)

    replay = Replay.open(path)
    assert len(replay.sim.script) == len(scenario.timeline)
    assert replay.sim.scenario_key == "news_shock"

    # And it survives a backward seek, which rebuilds the simulation from scratch.
    replay.seek(200)
    replay.seek(20)
    assert len(replay.sim.script) + sum(1 for step, _ in replay.sim.script_source
                                        if step <= 20) >= len(scenario.timeline)


def test_a_recorded_scenario_reproduces_its_prices(tmp_path):
    """The whole point of storing a seed: the replay is the run, not a summary of
    it. Without the timeline the headlines never arrive and the two diverge."""
    from mes import scenarios

    sim = Simulation(tiny())
    sim.load_scenario(scenarios.get("news_shock"))
    for _ in range(600):
        sim.step()
    recorded_price = sim.price
    path = rec_and_save(sim, tmp_path)

    replay = Replay.open(path)
    replay.seek(600)
    assert replay.sim.price == recorded_price


def rec_and_save(sim, tmp_path):
    rec = Recorder()
    rec.step = list(range(sim.t))  # the series content is not what is under test
    rec.price = [sim.price] * sim.t
    rec.fair = [sim.fair] * sim.t
    rec.volume = [0] * sim.t
    rec.chartist_share = [0.0] * sim.t
    rec.sentiment = [0.0] * sim.t
    rec.margin_calls = [0] * sim.t
    rec.orders = [0] * sim.t
    return rec.save(sim, "szenario", "20260101-000002", root=tmp_path)


# -------------------------------------------------------------- comparison
def test_an_arm_applies_its_overrides():
    arm = Arm.build("hoch", tiny(), {"chartist_aggression": 140.0})
    assert arm.cfg.chartist_aggression == 140.0
    assert arm.overrides == {"chartist_aggression": 140.0}


def test_both_arms_advance_together():
    comparison = Comparison.build(tiny(), {}, {"chartist_aggression": 140.0})
    comparison.advance(300)
    assert comparison.steps == 300
    assert comparison.a.sim.t == 300
    assert comparison.b.sim.t == 300


def test_identical_arms_stay_identical():
    """The control on the machinery itself: with nothing changed, both arms must
    produce the same run. If they diverged here, the comparison would be measuring
    its own bookkeeping."""
    comparison = Comparison.build(tiny(), {}, {})
    comparison.advance(400)
    assert comparison.a.sim.prices == comparison.b.sim.prices


def test_the_report_is_json_friendly():
    comparison = Comparison.build(tiny(), {}, {"chartist_aggression": 140.0})
    comparison.advance(20 * 25)  # enough days for the metrics to exist
    payload = comparison.to_dict()
    assert set(payload) >= {"steps", "a", "b", "difference", "series", "caveat"}
    for name, value in payload["difference"].items():
        # int or float — counts stay integers, which is fine for JSON. What must
        # not appear is a numpy scalar or a NaN.
        assert isinstance(value, (int, float)) and not isinstance(value, np.generic), name
        assert np.isfinite(value), name


def test_the_report_carries_the_caveat():
    """What a single seed pair cannot say is part of the output, next to the
    numbers rather than buried in a docstring."""
    comparison = Comparison.build(tiny(), {}, {})
    comparison.advance(50)
    assert "Seeds" in comparison.to_dict()["caveat"]


def test_a_parameter_that_cannot_act_changes_nothing():
    """The control that per-agent random streams make possible.

    `max_leverage` with no leveraged funds in the population has nothing to act on,
    so the two arms must come out bit-identical. Under a single shared stream they
    would not: any difference in how many numbers were drawn would have shifted
    every later draw for everybody.
    """
    comparison = Comparison.build(tiny(n_leveraged=0),
                                  {"max_leverage": 2.0}, {"max_leverage": 9.0})
    comparison.advance(1500)
    assert comparison.a.sim.market.prices == comparison.b.sim.market.prices


def test_an_agents_draws_depend_only_on_the_seed_and_its_id():
    """Structural check on the streams themselves, independent of the market."""
    a, b = Simulation(tiny()), Simulation(tiny(n_noise=99))
    first_a = {agent.aid: agent.rng.random() for agent in a.agents[:5]}
    first_b = {agent.aid: agent.rng.random() for agent in b.agents[:5]}
    assert first_a == first_b, "gleiche id und gleicher Seed müssen gleich ziehen"
    assert len(set(first_a.values())) == len(first_a), "verschiedene ids ziehen gleich"


def test_a_short_run_reports_insufficient_rather_than_guessing():
    comparison = Comparison.build(tiny(), {}, {})
    comparison.advance(30)
    assert comparison.to_dict()["a"]["metrics"].get("insufficient") is True


def test_the_seed_sweep_reports_signal_against_noise():
    """The honest form of an A/B here: several seed pairs, and a ratio saying
    whether the gap is bigger than the spread it sits in."""
    result = sweep_pair(tiny(), {}, {"chartist_aggression": 140.0},
                        steps=20 * 30, seeds=[11, 12])
    assert result["seeds"] == [11, 12]
    for figure in result["summary"].values():
        assert set(figure) == {"a", "b", "difference", "spread", "signal_to_noise"}
        assert figure["signal_to_noise"] >= 0


def test_the_sweep_finds_no_signal_between_identical_arms():
    """Two identical arms differ only through the seed, so nothing should stand
    out from the noise. This is the null case, and it has to come back empty."""
    result = sweep_pair(tiny(), {}, {}, steps=20 * 30, seeds=[11, 12, 13])
    for name, figure in result["summary"].items():
        assert figure["difference"] == pytest.approx(0.0, abs=1e-9), name
