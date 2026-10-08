"""Every scenario has to run. A preset that raises, or that quietly stops
producing prices, is worse than no preset at all.

These tests deliberately do not assert that "bubble" produces a bubble. Whether
it does is a result of the model and depends on the seed; asserting it would turn
a research question into a fixture.
"""

import math

import pytest

from mes import Config, Simulation, scenarios


# A short trading day compresses the timelines. "Dotcom" spans 500 trading days,
# which is 120 000 steps at the real setting — minutes per test. The scripts and
# the invariants are what is under test here, not the statistics, so four steps
# per day is enough and keeps the suite quick.
FAST_DAY = 4


@pytest.mark.parametrize("key", sorted(scenarios.ALL))
def test_scenario_runs_to_the_end_of_its_script(key):
    scenario = scenarios.get(key)
    sim = Simulation(Config(seed=11, steps_per_day=FAST_DAY))
    sim.load_scenario(scenario)

    last_day = max((offset for offset, _ in scenario.timeline), default=0)
    steps = (last_day + 20) * FAST_DAY

    for _ in range(steps):
        sim.step()

    assert not sim.script, f"{key}: script not worked through"
    assert sim.price > 0 and math.isfinite(sim.price)
    assert all(math.isfinite(p) for p in sim.prices)
    assert sim.bars, f"{key}: no daily bars"


@pytest.mark.parametrize("key", sorted(scenarios.ALL))
def test_scenario_overrides_reach_the_config(key):
    scenario = scenarios.get(key)
    sim = Simulation(Config(seed=11, steps_per_day=FAST_DAY))
    sim.load_scenario(scenario)
    for name, value in scenario.overrides.items():
        assert getattr(sim.cfg, name) == pytest.approx(value), f"{key}: {name} not set"


def test_catalogue_is_complete_and_grouped():
    groups = scenarios.catalogue()
    listed = {item["key"] for group in groups for item in group["items"]}
    assert listed == set(scenarios.ALL)
    for group in groups:
        assert group["items"], f"empty group: {group['group']}"
        for item in group["items"]:
            assert item["name"] and item["description"] and item["question"]


def test_loading_a_scenario_restarts_the_run():
    sim = Simulation(Config(seed=11, steps_per_day=FAST_DAY))
    for _ in range(500):
        sim.step()
    assert sim.t == 500
    sim.load_scenario(scenarios.get("calm"))
    assert sim.t == 0
    assert sim.scenario_key == "calm"


def test_timeline_events_fire_on_their_day():
    """The scripted headline in `news_shock` lands on its day, not before.

    Random news is switched off for the duration. The scenario turns it on, and
    an unrelated headline arriving early made this test fail roughly one run in
    thirty for reasons that had nothing to do with the timeline. Worse, the
    generator draws from a list that contains the scripted headline itself, so
    even matching on the text is not enough. With the noise off, the only thing
    that can produce this headline is the script.
    """
    scenario = scenarios.get("news_shock")
    day, action = next((d, a) for d, a in scenario.timeline if "news" in a)
    headline = action["news"][0]

    sim = Simulation(Config(seed=11, steps_per_day=FAST_DAY))
    sim.load_scenario(scenario)
    sim.cfg.update_live({"news_intensity": 0.0})

    for _ in range(day * sim.cfg.steps_per_day - 1):
        sim.step()
    assert not any(e.text == headline for e in sim.events), "the headline came too early"

    for _ in range(2):
        sim.step()
    assert any(e.text == headline for e in sim.events), "the headline never arrived"


def test_leverage_crash_actually_produces_margin_calls():
    """This one is a mechanism check, not a price check: the scenario exists to
    show forced selling, so forced selling has to happen."""
    sim = Simulation(Config(seed=11, steps_per_day=FAST_DAY))
    sim.load_scenario(scenarios.get("leverage_crash"))
    for _ in range(3000):
        sim.step()
    assert sim.margin_calls > 0


def test_every_lesson_has_exactly_one_check_and_vice_versa():
    """`lessons.evaluate` indexes CHECKS by lesson key.

    A lesson without a check raises KeyError on the check endpoint; a check without a
    lesson is unreachable code that reads like a feature — there was one, keyed
    "decoupled", and it could only ever 404.
    """
    from mes import lessons

    assert set(lessons.CHECKS) == set(lessons.ALL), (
        "CHECKS and LESSONS do not match: "
        f"only in CHECKS {sorted(set(lessons.CHECKS) - set(lessons.ALL))}, "
        f"only in LESSONS {sorted(set(lessons.ALL) - set(lessons.CHECKS))}"
    )


def test_every_lesson_can_be_evaluated():
    """Each check runs against a real simulation without raising."""
    from mes import lessons

    sim = Simulation(Config(seed=5, steps_per_day=FAST_DAY))
    for _ in range(400):
        sim.step()
    for key in lessons.ALL:
        result = lessons.evaluate(key, sim)
        assert result["checks"], f"{key} returns no checks"
        assert result["verdict"] in ("shown", "partly", "not this time")


def test_every_scenario_a_lesson_names_exists():
    """A lesson may set itself up from a scenario; a typo there is a 404 at run time."""
    from mes import lessons, scenarios as scen

    for lesson in lessons.ALL.values():
        if lesson.scenario:
            assert scen.get(lesson.scenario) is not None, (
                f"{lesson.key} refers to an unknown scenario {lesson.scenario!r}")
