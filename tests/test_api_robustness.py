"""What happens when the frontend sends something the model cannot use.

Every one of these was a live 500 that left the simulation broken. They were found
by driving the actual buttons: the parameter panel posts `reset: true` for every
parameter marked `live: False`, a JSON body sends numbers as floats, and
`n_noise = 200.0` was enough to freeze the market permanently.

The chain was: `Config.from_dict` did not cast → `range(200.0)` raised inside
`_spawn_agents` → `Simulation.reset` had already appended 300 adaptive agents but
never reached the line that gives them a strategy → every following `step()` raised
`KeyError: 'base'` → the clock task died → `/api/state` kept answering, the page kept
showing "LÄUFT", and the step counter never moved again.

Three separate defects, so three groups of tests. The endpoint coroutines are called
directly rather than through `fastapi.testclient`, which needs `httpx`; the project
does not depend on it and one test module is not a reason to start.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from mes.config import PARAM_SPEC, Config
from mes.simulation import Simulation


# --------------------------------------------------------- 1. the cast
def test_from_dict_casts_integer_parameters():
    """A JSON body has no integers. The config has to make them again."""
    cfg = Config.from_dict({"n_noise": 200.0, "n_makers": 12.0, "seed": 7.0,
                            "switch_interval": 20.0})
    assert isinstance(cfg.n_noise, int)
    assert isinstance(cfg.n_makers, int)
    assert isinstance(cfg.seed, int)
    assert isinstance(cfg.switch_interval, int)


def test_from_dict_casts_every_parameter_in_the_spec():
    """The panel can post any parameter in PARAM_SPEC, so all of them are covered."""
    floats = {name: float(spec["min"]) for name, spec in PARAM_SPEC.items()}
    cfg = Config.from_dict(floats)
    for name, spec in PARAM_SPEC.items():
        value = getattr(cfg, name)
        expected = int if spec["kind"] == "int" else float
        assert isinstance(value, expected), \
            f"{name} ist {type(value).__name__}, erwartet {expected.__name__}"


def test_from_dict_leaves_symbols_alone():
    """`symbols` is a tuple or None; there is nothing to cast."""
    assert Config.from_dict({"symbols": None}).symbols is None
    assert Config.from_dict({"symbols": ("TECH",)}).symbols == ("TECH",)


def test_a_round_trip_through_to_dict_changes_nothing():
    assert Config.from_dict(Config().to_dict()).to_dict() == Config().to_dict()


def test_a_float_population_builds_and_steps():
    """The precise failure: floats from the slider, then a strategy review."""
    sim = Simulation(Config.from_dict({**Config().to_dict(),
                                       "n_adaptive": 20.0, "n_noise": 20.0,
                                       "n_passive": 2.0, "n_leveraged": 2.0,
                                       "n_makers": 2.0, "switch_interval": 5.0}))
    for _ in range(12):     # far enough to pass a strategy review
        sim.step()
    assert all(agent.strategy != "base" for agent in sim.agents), \
        "ein Agent ohne Strategie bringt jedes Review zum Absturz"


# --------------------------------------------- 2. and 3. through the endpoints
@pytest.fixture(scope="module")
def api():
    """The API module with a small, quick simulation in place of the real runner."""
    from mes import api as module

    small = Config(n_adaptive=20, n_noise=20, n_passive=4, n_leveraged=4, n_makers=2)
    module.runner.sim = Simulation(small)
    module.runner.warm_target = 0
    module.runner.failure = None
    module.runner.running = True
    return module


def call(coroutine):
    return asyncio.run(coroutine)


def test_posting_a_float_population_no_longer_raises(api):
    patch = api.ParamPatch(values={"n_noise": 15.0}, reset=True)
    result = call(api.set_params(patch))
    assert result["reset"] is True
    assert api.runner.sim.cfg.n_noise == 15


def test_the_market_still_steps_after_a_population_change(api):
    call(api.set_params(api.ParamPatch(values={"n_noise": 12.0}, reset=True)))
    before = api.runner.sim.t
    call(api.control(api.Control(action="step", n=5)))
    assert api.runner.sim.t == before + 5
    assert api.runner.failure is None


def test_an_unbuildable_configuration_is_a_400_and_the_market_survives(api, monkeypatch):
    """The atomicity guarantee, stated as a test.

    The model turns out to accept every value the panel can send — negative
    populations, a zero price, an empty symbol list all build and step, which is why
    the float/int cast above was the only crash path in practice. So the guarantee
    that matters is tested directly: whatever makes construction fail, the running
    market has to outlive it. Injected rather than provoked, because provoking it
    would mean relying on a configuration that happens to be rejected today.
    """
    live = api.runner.sim
    agents_before = len(live.agents)
    step_before = live.t

    def refuse(_cfg):
        raise ValueError("erfundene Ablehnung")

    monkeypatch.setattr(api, "Simulation", refuse)
    with pytest.raises(HTTPException) as raised:
        call(api.set_params(api.ParamPatch(values={"n_adaptive": 30.0}, reset=True)))
    assert raised.value.status_code == 400
    assert "nicht baubar" in raised.value.detail

    # Built-before-swapped: the same object is still there, and it still steps.
    monkeypatch.undo()
    assert api.runner.sim is live
    assert len(api.runner.sim.agents) == agents_before
    call(api.control(api.Control(action="step", n=1)))
    assert api.runner.sim.t == step_before + 1
    assert api.runner.failure is None


def test_state_reports_whether_the_clock_is_alive(api):
    """`failure` is the field the page needs in order to stop claiming "LÄUFT"."""
    snapshot = api.runner.snapshot()
    assert "failure" in snapshot
    assert snapshot["failure"] is None


def test_reset_clears_a_recorded_failure(api):
    api.runner.failure = "TypeError: erfunden"
    api.runner.running = False
    call(api.control(api.Control(action="reset")))
    assert api.runner.failure is None
    assert api.runner.snapshot()["failure"] is None


def test_the_whole_default_configuration_can_be_posted_back(api):
    """"Standardwerte wiederherstellen" sends a configuration, not a slider.

    `values` used to be declared `dict[str, float]`, so a body carrying
    `symbols: null` — present in every complete configuration — came back as a 422
    naming a field the caller never meant to set, and the restore button silently
    did nothing.
    """
    defaults = Config().to_dict()
    result = call(api.set_params(api.ParamPatch(values=defaults, reset=True)))
    assert result["reset"] is True
    restored = api.runner.sim.cfg.to_dict()
    assert restored["herd_strength"] == defaults["herd_strength"]
    assert restored["symbols"] == defaults["symbols"]


def test_posting_only_the_spec_keys_restores_them(api):
    """What the panel actually sends."""
    call(api.set_params(api.ParamPatch(values={"herd_strength": 8.0}, reset=False)))
    assert api.runner.sim.cfg.herd_strength == 8.0
    wanted = {name: Config().to_dict()[name] for name in PARAM_SPEC}
    call(api.set_params(api.ParamPatch(values=wanted, reset=True)))
    assert api.runner.sim.cfg.herd_strength == Config().herd_strength


def test_a_reset_ends_the_running_lesson(api):
    """The lesson belongs to the run that was set up for it.

    `runner.lesson` was never cleared, so after a reset — or after loading a
    scenario — the experiment panel went on marking one experiment as running and
    checking it against a market it had never arranged.
    """
    api.runner.lesson = "bubble"
    call(api.control(api.Control(action="reset")))
    assert api.runner.lesson is None
    assert api.runner.snapshot()["lesson"] is None


def test_loading_a_scenario_ends_the_running_lesson(api):
    api.runner.lesson = "bubble"
    call(api.load_scenario("calm"))
    assert api.runner.lesson is None


def test_the_clock_records_a_failing_step_instead_of_dying(api):
    """A step that raises has to stop the clock and name itself.

    Before, the task simply ended: the state endpoint went on answering, the page
    went on saying the market was running, and the only symptom was a step counter
    that never moved.
    """
    broken = Simulation(Config(n_adaptive=4, n_noise=4, n_passive=1,
                               n_leveraged=1, n_makers=1))

    def explode():
        raise RuntimeError("kaputt")

    broken.step = explode
    api.runner.sim = broken
    api.runner.warm_target = 0
    api.runner.failure = None
    api.runner.running = True

    async def run_briefly():
        task = asyncio.create_task(api.runner.loop())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if api.runner.failure:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_briefly())
    assert api.runner.failure == "RuntimeError: kaputt"
    assert api.runner.running is False


# ------------------------------------------------- candles follow the selection
def test_bars_can_be_asked_for_one_instrument(api):
    """A chart labelled TECH drawn from ENRG is a bug, not a detail.

    `/api/bars` had no symbol parameter and always answered with the primary market,
    which is why the candle view could not be given to a reader who had selected a
    different one.
    """
    for symbol in api.runner.sim.markets:
        answer = api.bars(n=5, symbol=symbol)
        assert answer["symbol"] == symbol
        assert all(bar["symbol"] == symbol for bar in answer["bars"])


def test_bars_falls_back_to_the_primary_market(api):
    """What it did before it took an argument, unchanged."""
    assert api.bars(n=5)["symbol"] == api.runner.sim.primary
    assert api.bars(n=5, symbol="GIBTSNICHT")["symbol"] == api.runner.sim.primary


def test_series_and_bars_agree_on_the_instrument(api):
    """Two views of the same market must not silently be two markets."""
    for symbol in api.runner.sim.markets:
        assert api.series(n=10, symbol=symbol)["symbol"] == symbol
        assert api.bars(n=10, symbol=symbol)["symbol"] == symbol


# ------------------------------------------- how long an experiment actually takes
def test_the_lesson_catalogue_prices_its_own_recommendation(api):
    """"empfohlen: 70 Handelstage" is two hours and twenty minutes at 1×.

    The panel said the days and nothing about the clock, which makes the
    recommendation unusable — so the arithmetic ships from the endpoint, where SPEEDS
    lives, instead of being duplicated into two pages.
    """
    catalogue = api.lesson_catalogue()
    clock = catalogue["clock"]
    assert clock["steps_per_day"] == api.runner.sim.cfg.steps_per_day
    assert set(clock["seconds_per_step"]) == set(api.SPEEDS)
    assert clock["fastest"] in api.SPEEDS
    # The fastest setting has to be the fastest one, or the panel sends people the
    # long way round.
    assert clock["seconds_per_step"][clock["fastest"]] == min(
        clock["seconds_per_step"].values())
    for lesson in catalogue["lessons"]:
        assert lesson["steps"] == lesson["days"] * clock["steps_per_day"]


def test_the_check_says_how_much_longer(api):
    """"Tag 12 von 70" carries no cost. These fields do."""
    api.runner.speed = "1x"
    result = api.check_lesson("bubble")
    assert result["speed"] == "1x"
    assert result["steps_left"] >= 0
    assert result["seconds_left"] >= 0
    slow = result["seconds_left"]

    api.runner.speed = "16x"
    fast = api.check_lesson("bubble")["seconds_left"]
    assert fast < slow, "16× muss schneller geschätzt werden als 1×"


def test_the_estimate_reaches_zero_once_the_recommendation_is_met(api):
    from mes import lessons as lesson_module

    needed = lesson_module.get("cascade").days
    api.runner.sim.t = (needed + 5) * api.runner.sim.cfg.steps_per_day
    result = api.check_lesson("cascade")
    assert result["steps_left"] == 0
    assert result["seconds_left"] == 0


# ------------------------------------------- a replay position the town can draw
@pytest.fixture()
def opened_replay(api, tmp_path):
    """A tiny recording, written by the real recorder and opened.

    Recorded here rather than relying on `runs/` so the test does not depend on
    somebody having run scripts/run.py first, and written through `Recorder.save` so
    it is the same on-disk shape a real run produces.
    """
    from mes import recorder

    cfg = Config(seed=5, n_adaptive=10, n_noise=10, n_passive=2,
                 n_leveraged=2, n_makers=1, steps_per_day=20)
    sim = Simulation(cfg)
    tape = recorder.Recorder()
    for _ in range(200):
        sim.step()
        tape.capture(sim)
    folder = tape.save(sim, "klein", "20260101-000000", root=tmp_path)

    api.replay = recorder.Replay.open(folder)
    yield api
    api.replay = None


def test_a_replay_position_is_shaped_like_the_live_state(opened_replay):
    """The town draws a recording with the code it draws the market with.

    The payload used to be a bare `city.snapshot`, missing every field the HTTP layer
    adds, so no page could render it without special-casing each read-out — which is
    why a recorded run was only ever readable as a single price.
    """
    api = opened_replay
    answer = api.seek_replay(api.Seek(day=4))
    frame = answer["snapshot"]
    live = api.runner.snapshot()
    missing = sorted(set(live) - set(frame))
    assert not missing, f"Replay-Rahmen fehlen Felder aus /api/state: {missing}"
    assert frame["replay"]["day"] == 4
    assert frame["running"] is False, "eine Aufzeichnung läuft nicht"
    assert frame["warming"] is False and frame["failure"] is None


def test_a_replay_position_brings_its_own_curves(opened_replay):
    """Fetching /api/series while a recording is open would answer from the *live*
    market and put a live chart beside a recorded town."""
    api = opened_replay
    frame = api.seek_replay(api.Seek(day=6))["snapshot"]
    assert frame["series"]["symbol"] == frame["focus"]
    assert frame["bars"]["symbol"] == frame["focus"]
    assert len(frame["series"]["price"]) == len(frame["series"]["fair"]) > 0
    assert frame["ladder"]["bids"] is not None


def test_the_replay_follows_the_towns_market_selection(opened_replay):
    """"Which market am I looking at" is a question about the view, not about which
    simulation is behind it."""
    api = opened_replay
    for symbol in api.runner.sim.markets:
        api.runner.symbol = symbol
        frame = api.get_replay()["snapshot"]
        assert frame["focus"] == symbol
        assert frame["series"]["symbol"] == symbol
    api.runner.symbol = None


def test_seeking_is_reproducible_in_both_directions(opened_replay):
    """Forwards is incremental, backwards restarts from step 0, and the point of the
    whole design is that both land on bit-identical state."""
    api = opened_replay
    forward = api.seek_replay(api.Seek(day=7))["snapshot"]
    api.seek_replay(api.Seek(day=9))
    backward = api.seek_replay(api.Seek(day=7))["snapshot"]
    assert forward["px"] == backward["px"]
    assert forward["step"] == backward["step"]
    assert forward["cap"] == backward["cap"]


def test_the_live_market_is_untouched_by_a_replay(opened_replay):
    """The replay is its own simulation. Scrubbing it must not move the market the
    town returns to."""
    api = opened_replay
    before = api.runner.sim.t
    api.seek_replay(api.Seek(day=8))
    api.seek_replay(api.Seek(day=2))
    assert api.runner.sim.t == before


# ------------------------------------------------- 4. what the audit turned up
def test_a_bad_live_value_is_a_400_and_changes_nothing(api):
    """`update_live` casts as it goes. A patch of three parameters whose second
    value is unparseable used to set the first, raise a 500 on the second and never
    reach the third — a configuration nobody asked for, behind an error naming none
    of it. Cast first, assign second."""
    before = api.runner.sim.cfg.to_dict()
    with pytest.raises(HTTPException) as raised:
        call(api.set_params(api.ParamPatch(values={
            "chartist_aggression": 90.0,
            "herd_strength": "sehr stark",
            "switch_rate": 0.5,
        })))
    assert raised.value.status_code == 400
    assert api.runner.sim.cfg.to_dict() == before


def test_a_reset_lets_go_of_a_selected_agent_that_no_longer_exists(api):
    """The population is rebuilt, so the id names a different agent or none at all
    — and `_selected` falls back to the first adaptive trader for an unknown id, so
    the panel showed *an* agent under the number of one that had gone."""
    small = Config(n_adaptive=4, n_noise=4, n_passive=1, n_leveraged=1, n_makers=1)

    api.runner.selected = max(api.runner.sim.by_id) + 500
    call(api.runner.reset(small))
    assert api.runner.selected is None

    # An id the new population *does* contain is left alone: clearing every
    # selection on every reset would lose the reader's place for no reason.
    api.runner.selected = min(api.runner.sim.by_id)
    call(api.runner.reset(small))
    assert api.runner.selected == min(api.runner.sim.by_id)


def test_starting_a_lesson_restarts_a_stopped_clock(api):
    """A lesson rebuilds the market, and a rebuilt market is not the one that broke.
    The failure used to survive it, so the clock stayed parked for ever with an
    error message from a simulation that no longer existed."""
    api.runner.failure = "RuntimeError: irgendwas"
    api.runner.running = False
    from mes import lessons

    call(api.start_lesson(sorted(lessons.ALL)[0]))
    assert api.runner.failure is None


def test_one_lesson_does_not_inherit_the_previous_one(api):
    """Building each lesson on the *live* config made them accumulate: start "no
    market makers", then start "no issuer", and the second experiment quietly ran
    without makers too, with its own panel reporting on a market it had not set up."""
    from mes import lessons

    setups = {key: lessons.get(key).setup for key in lessons.ALL}
    first = next(k for k, s in setups.items() if s and not lessons.get(k).scenario)
    second = next(k for k, s in setups.items()
                  if s and not lessons.get(k).scenario and k != first
                  and set(s) != set(setups[first]))

    call(api.start_lesson(first))
    call(api.start_lesson(second))
    defaults = Config().to_dict()
    live = api.runner.sim.cfg.to_dict()
    for name in setups[first]:
        if name in setups[second]:
            continue
        assert live[name] == defaults[name], \
            f"{second} läuft noch unter {first}s {name}"
