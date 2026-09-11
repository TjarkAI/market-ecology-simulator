"""The two read endpoints the index board and the roster are built on.

The modules behind them are tested next door; what is tested here is the HTTP
layer's own arithmetic, which is where the interesting mistake was. `/api/indices`
takes two numbers that are easy to conflate — how far back to look and how many
points to send — and conflating them returns the whole run thinned to the
requested count under a label that says five days. It looks entirely plausible.

The endpoint functions are called directly rather than through
`fastapi.testclient`, which needs `httpx`; the project does not depend on it and
one test module is not a reason to start.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from mes import api
from mes.config import Config
from mes.indices import BASE
from mes.simulation import Simulation


@pytest.fixture(scope="module", autouse=True)
def live() -> Simulation:
    """A small market in place of the module-level one.

    Importing `mes.api` builds and warms a full run; these tests do not need it and
    a fixture that swaps in a cheap simulation keeps them from paying for it twice.
    """
    saved = api.runner.sim
    sim = Simulation(Config(n_adaptive=40, n_noise=30, n_passive=4, n_leveraged=4,
                            n_makers=3, seed=5, steps_per_day=20))
    for _ in range(600):  # 30 trading days
        sim.step()
    api.runner.sim = sim
    yield sim
    api.runner.sim = saved


# ------------------------------------------------------------------- indices
def test_the_window_and_the_point_count_are_separate(live):
    """`n` is how far back, `points` is how many samples. One number for both is
    the bug this endpoint was born with."""
    narrow = api.index_book(n=100, scale="step", points=1000)
    wide = api.index_book(n=600, scale="step", points=1000)

    assert narrow["covers"] == 100
    assert wide["covers"] == 600
    assert len(narrow["indices"][0]["series"]) == 100
    # The narrow window is a suffix of the wide one, which is what "the last 100
    # steps" has to mean.
    assert narrow["indices"][0]["series"] == wide["indices"][0]["series"][-100:]


def test_the_point_count_is_a_cap_and_the_last_point_is_kept(live):
    data = api.index_book(n=600, scale="step", points=50)
    for index in data["indices"]:
        assert len(index["series"]) <= 50
        assert index["series"][-1] == pytest.approx(index["level"], abs=0.01)
        assert len(index["fairSeries"]) == len(index["series"])


def test_a_window_longer_than_the_run_reports_what_it_covers(live):
    data = api.index_book(n=10_000_000, scale="step", points=100)
    assert data["covers"] <= live.t + 1
    assert str(data["covers"]) in data["window"]


def test_the_day_scale_serves_daily_closes(live):
    data = api.index_book(n=4000, scale="day", points=1000)
    assert data["scale"] == "day"
    assert data["covers"] == len(live.indices.by_key["MKT"].closes)
    assert data["indices"][0]["series"] == [
        round(v, 3) for v in live.indices.by_key["MKT"].closes]


def test_the_market_index_reports_no_beta_against_itself(live):
    data = api.index_book()
    market = next(i for i in data["indices"] if i["kind"] == "market")
    assert market["beta"] is None, "Regression auf sich selbst ist keine Messung"
    assert market["corr"] is None
    # The configured beta is still meaningful: it is the weighted average loading.
    assert market["betaSpec"] > 0


def test_every_index_carries_its_weights_and_its_breadth(live):
    for index in api.index_book()["indices"]:
        assert set(index["weights"]) == set(index["members"])
        assert sum(index["weights"].values()) == pytest.approx(1.0, abs=1e-3)
        assert 0 <= index["breadth"] <= index["width"] == len(index["members"])


def test_the_payload_survives_a_run_with_no_history(live):
    """A page opened in the first second must not meet a 500."""
    saved = api.runner.sim
    api.runner.sim = Simulation(Config(n_adaptive=10, n_noise=10, n_passive=1,
                                       n_leveraged=1, n_makers=1, steps_per_day=20))
    try:
        data = api.index_book(n=500, points=100)
        assert data["day"] == 0
        for index in data["indices"]:
            assert index["level"] == BASE
            assert index["vol"] is None and index["drawdown"] is None
            assert index["series"] == [BASE]
    finally:
        api.runner.sim = saved


# ------------------------------------------------------------------- traders
def test_the_roster_pages_and_filters(live):
    page = api.trader_list(limit=10)
    assert len(page["traders"]) == 10
    assert page["summary"]["count"] == len(live.agents)

    funds = api.trader_list(kind="leveraged", limit=500)
    assert funds["summary"]["matched"] == sum(
        1 for a in live.agents if a.kind == "leveraged")


def test_an_unknown_sort_is_a_400_naming_the_valid_ones(live):
    with pytest.raises(HTTPException) as raised:
        api.trader_list(sort="reichtum")
    assert raised.value.status_code == 400
    assert "equity" in raised.value.detail


def test_a_missing_trader_is_a_404(live):
    with pytest.raises(HTTPException) as raised:
        api.trader_detail(999_999)
    assert raised.value.status_code == 404


def test_reading_a_trader_does_not_select_one(live):
    """`/api/agents/{aid}` selects as a side effect of being read, which is right
    for the town and wrong for a table the pointer runs over."""
    api.runner.selected = None
    api.trader_detail(live.agents[3].aid)
    api.trader_list()
    assert api.runner.selected is None


# --------------------------------------------------------------------- routes
def test_both_pages_are_served(live):
    for route, name in ((api.index_view, "indices.html"),
                        (api.trader_view, "traders.html")):
        response = route()
        assert response.path.name == name
        assert response.path.is_file()
