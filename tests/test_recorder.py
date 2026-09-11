"""A recording is only worth keeping if it can be reproduced from it.

The point of storing the config — and with it the seed — is that a run can be
re-created rather than merely looked at. If `reproduce()` gave a different price
series, the recording would be a screenshot, not a record.
"""

from mes import Config, Simulation
from mes.recorder import Recorder, catalogue, load, reproduce


def tiny() -> Config:
    return Config(n_adaptive=40, n_noise=30, n_passive=4, n_leveraged=4,
                  n_makers=3, steps_per_day=10, seed=23)


def test_record_save_and_load_round_trip(tmp_path):
    sim = Simulation(tiny())
    recorder = Recorder()
    for _ in range(120):
        sim.step()
        recorder.capture(sim)

    target = recorder.save(sim, "test", "20260101-000000", root=tmp_path)
    assert (target / "series.parquet").is_file()
    assert (target / "bars.parquet").is_file()
    assert (target / "run.json").is_file()

    record = load(target)
    assert len(record["series"]) == 120
    assert len(record["bars"]) == len(sim.bars)
    assert record["meta"]["steps"] == 120
    assert record["config"].seed == 23


def test_a_recording_reproduces_the_run_exactly(tmp_path):
    sim = Simulation(tiny())
    recorder = Recorder()
    for _ in range(200):
        sim.step()
        recorder.capture(sim)
    target = recorder.save(sim, "repro", "20260101-000001", root=tmp_path)

    again = reproduce(target)
    assert again.t == sim.t
    assert again.prices == sim.prices
    assert again.margin_calls == sim.margin_calls


def test_catalogue_lists_saved_runs(tmp_path):
    assert catalogue(root=tmp_path) == []

    sim = Simulation(tiny())
    recorder = Recorder()
    for _ in range(30):
        sim.step()
        recorder.capture(sim)
    recorder.save(sim, "eins", "20260101-000002", root=tmp_path)
    recorder.save(sim, "zwei", "20260101-000003", root=tmp_path)

    entries = catalogue(root=tmp_path)
    assert [e["name"] for e in entries] == ["zwei", "eins"]  # newest first
    assert all(e["seed"] == 23 for e in entries)


def test_scenario_key_is_recorded(tmp_path):
    from mes import scenarios

    sim = Simulation(tiny())
    sim.load_scenario(scenarios.get("calm"))
    recorder = Recorder()
    for _ in range(50):
        sim.step()
        recorder.capture(sim)
    target = recorder.save(sim, "szenario", "20260101-000004", root=tmp_path)
    assert load(target)["meta"]["scenario"] == "calm"


def test_an_unreadable_run_does_not_hide_the_others(tmp_path):
    """One half-written run.json used to take the whole catalogue with it: a 500
    from /api/runs and every other recording on disk invisible behind it."""
    sim = Simulation(tiny())
    recorder = Recorder()
    for _ in range(30):
        sim.step()
        recorder.capture(sim)
    recorder.save(sim, "gut", "20260101-000005", root=tmp_path)

    broken = tmp_path / "20260101-000006_kaputt"
    broken.mkdir()
    (broken / "run.json").write_text("{ this is not json")

    entries = catalogue(root=tmp_path)
    assert {e["name"] for e in entries} >= {"gut"}
    bad = [e for e in entries if e.get("error")]
    assert len(bad) == 1
    assert bad[0]["seed"] is None


def test_the_stored_config_is_the_one_the_run_started_with(tmp_path):
    """`Config.update_live` mutates in place, so saving the live object saved an end
    state — and a replay then applied the scripted change a second time from the
    timeline on top of a config that already had it."""
    sim = Simulation(tiny())
    started_with = sim.cfg.chartist_aggression
    recorder = Recorder()
    for _ in range(30):
        sim.step()
        recorder.capture(sim)
    sim.cfg.update_live({"chartist_aggression": started_with + 40.0})
    for _ in range(10):
        sim.step()
        recorder.capture(sim)

    target = recorder.save(sim, "getunt", "20260101-000007", root=tmp_path)
    assert load(target)["config"].chartist_aggression == started_with
