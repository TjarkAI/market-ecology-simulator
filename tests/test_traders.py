"""The population as a list.

A roster is easy to get subtly wrong in ways that look right: a filter that also
narrows the rollup, a page that drops or repeats a row, a total that counts the
page instead of the population. Each of those produces a plausible screen, so each
gets a test.

The endpoint coroutines are called directly rather than through
`fastapi.testclient`, which needs `httpx`; the project does not depend on it and
one test module is not a reason to start — the same choice `test_api_robustness`
makes and for the same reason.
"""

from __future__ import annotations

import pytest

from mes import Config, Simulation, traders


def small(**kwargs) -> Config:
    base = dict(n_adaptive=60, n_noise=40, n_passive=6, n_leveraged=6,
                n_makers=3, seed=5, steps_per_day=40)
    base.update(kwargs)
    return Config(**base)


@pytest.fixture(scope="module")
def sim() -> Simulation:
    s = Simulation(small())
    for _ in range(800):
        s.step()
    return s


# ------------------------------------------------------------------ coverage
def test_every_agent_appears_exactly_once(sim):
    everyone = traders.overview(sim, limit=2000)
    ids = [row["aid"] for row in everyone["traders"]]
    assert sorted(ids) == sorted(a.aid for a in sim.agents)
    assert everyone["summary"]["count"] == len(sim.agents)


def test_the_totals_are_the_simulation_totals(sim):
    everyone = traders.overview(sim, limit=2000)
    assert everyone["summary"]["equity"] == pytest.approx(
        sum(a.equity() for a in sim.agents), rel=1e-6)
    assert everyone["summary"]["shares"] == sum(a.shares for a in sim.agents)
    assert everyone["summary"]["margin_calls"] == sim.margin_calls


def test_the_summary_counts_the_population_not_the_page(sim):
    page = traders.overview(sim, limit=5)
    assert page["summary"]["shown"] == 5
    assert page["summary"]["count"] == len(sim.agents)
    assert page["summary"]["equity"] == pytest.approx(
        sum(a.equity() for a in sim.agents), rel=1e-6)


def test_the_group_rollup_ignores_the_filter(sim):
    """A rollup that shrinks when a search box is typed into is answering a
    different question from the one its label promises."""
    everyone = traders.overview(sim, limit=2000)
    filtered = traders.overview(sim, kind="leveraged", limit=2000)
    assert {g["group"]: g["count"] for g in everyone["groups"]} == \
           {g["group"]: g["count"] for g in filtered["groups"]}


def test_the_group_counts_add_up_to_the_population(sim):
    everyone = traders.overview(sim, limit=2000)
    assert sum(g["count"] for g in everyone["groups"]) == len(sim.agents)
    assert sum(g["equity"] for g in everyone["groups"]) == pytest.approx(
        everyone["summary"]["equity"], rel=1e-6)


# ------------------------------------------------------------------- sorting
def test_sorting_runs_both_ways(sim):
    down = [r["equity"] for r in traders.overview(sim, sort="equity", limit=2000)["traders"]]
    up = [r["equity"] for r in
          traders.overview(sim, sort="equity", order="asc", limit=2000)["traders"]]
    assert down == sorted(down, reverse=True)
    assert up == sorted(up)
    assert down[0] == up[-1]


def test_every_advertised_sort_actually_works(sim):
    """The endpoint hands the frontend a list of sortable columns. Each one has to
    be usable, or the table grows a header that silently does nothing."""
    for column in traders.SORTS:
        result = traders.overview(sim, sort=column, limit=20)
        assert result["sort"] == column
        assert len(result["traders"]) == 20


def test_an_unknown_sort_is_refused(sim):
    """Falling back to a default order would look like a broken sort rather than a
    rejected one."""
    with pytest.raises(KeyError):
        traders.overview(sim, sort="vermoegen")


def test_a_missing_leverage_sorts_last_rather_than_crashing(sim):
    """A wiped-out fund has no meaningful leverage and comes back as null. Sorting
    a column containing null is exactly where a table falls over."""
    rows = traders.overview(sim, sort="leverage", limit=2000)["traders"]
    values = [r["leverage"] for r in rows]
    seen_null = False
    for value in values:
        if value is None:
            seen_null = True
        else:
            assert not seen_null, "null sorts before a number in descending order"


# ------------------------------------------------------------------ filtering
def test_filtering_by_kind(sim):
    rows = traders.overview(sim, kind="leveraged", limit=2000)["traders"]
    assert rows
    assert all(r["kind"] == "leveraged" for r in rows)
    assert len(rows) == sum(1 for a in sim.agents if a.kind == "leveraged")


def test_filtering_by_strategy_splits_the_adaptive_camp(sim):
    momentum = traders.overview(sim, strategy="momentum", limit=2000)["traders"]
    value = traders.overview(sim, strategy="value", limit=2000)["traders"]
    assert all(r["strategy"] == "momentum" for r in momentum)
    assert len(momentum) + len(value) == sum(1 for a in sim.agents if a.kind == "adaptive")


def test_filtering_by_instrument_finds_holders_and_the_makers_of_it(sim):
    rows = traders.overview(sim, symbol="TECH", limit=2000)["traders"]
    assert rows
    for row in rows:
        assert row["symbol"] == "TECH" or "TECH" in row["positions"]
    # The market makers and the issuer of that instrument are in there.
    assert any(r["kind"] == "maker" and r["symbol"] == "TECH" for r in rows)


def test_the_search_matches_a_number_or_a_type(sim):
    by_id = traders.overview(sim, query="#3", limit=2000)["traders"]
    assert all("3" in str(r["aid"]) for r in by_id)
    by_kind = traders.overview(sim, query="leveraged", limit=2000)["traders"]
    assert by_kind and all(r["kind"] == "leveraged" for r in by_kind)


def test_an_empty_search_is_not_a_filter(sim):
    assert (traders.overview(sim, query="   ", limit=2000)["summary"]["matched"]
            == len(sim.agents))


# --------------------------------------------------------------------- paging
def test_paging_covers_everyone_without_gaps_or_repeats(sim):
    seen, offset = [], 0
    while True:
        page = traders.overview(sim, limit=40, offset=offset)
        seen.extend(r["aid"] for r in page["traders"])
        offset += 40
        if offset >= page["summary"]["matched"]:
            break
    assert sorted(seen) == sorted(a.aid for a in sim.agents)
    assert len(seen) == len(set(seen))


def test_an_offset_past_the_end_still_answers(sim):
    page = traders.overview(sim, limit=10, offset=10_000)
    assert page["traders"], "a page past the end must not come back empty"


# --------------------------------------------------------------------- fields
def test_profit_is_measured_against_the_start_of_the_run():
    fresh = Simulation(small())
    rows = traders.overview(fresh, limit=2000)["traders"]
    assert all(abs(r["pnl"]) < 1e-6 for r in rows), "a fresh run has no result"
    assert all(r["pnlPct"] == pytest.approx(0.0, abs=1e-6) for r in rows
               if r["pnlPct"] is not None)


def test_only_non_zero_positions_are_reported(sim):
    for row in traders.overview(sim, limit=2000)["traders"]:
        assert all(qty != 0 for qty in row["positions"].values())


def test_an_order_is_open_only_while_it_is_this_step(sim):
    """`last_orders` keeps the last order for ever. A row reading "kauft 300" for
    an agent that has not traded in twenty thousand steps is a lie with a
    timestamp next to it."""
    for row in traders.overview(sim, limit=2000)["traders"]:
        if row["order"] is None:
            continue
        assert row["order"]["open"] == (row["order"]["step"] >= sim.t - 1)


def test_an_infinite_leverage_comes_back_as_null(sim):
    """Infinity is not JSON, and a client that formats it gets "Infinity" or a
    parse error depending on the parser."""
    fund = next(a for a in sim.agents if a.kind == "leveraged")
    saved = dict(fund.positions), fund.cash
    fund.positions = {sim.primary: 100}
    fund.cash = -100 * sim.markets[sim.primary].price
    try:
        row = next(r for r in traders.overview(sim, limit=2000)["traders"]
                   if r["aid"] == fund.aid)
        assert row["leverage"] is None
    finally:
        fund.positions, fund.cash = saved[0], saved[1]


# --------------------------------------------------------------------- detail
def test_the_detail_lists_the_held_instruments_marked_to_the_current_price(sim):
    holder = next(a for a in sim.agents if a.kind == "adaptive" and a.shares > 0)
    row = traders.detail(sim, holder.aid)
    assert row["aid"] == holder.aid
    assert row["book"], "a holder without book rows"
    for line in row["book"]:
        assert line["qty"] == holder.position(line["symbol"])
        assert line["price"] == pytest.approx(
            round(sim.markets[line["symbol"]].price, 2))
        assert line["value"] == pytest.approx(line["qty"] * line["price"], abs=0.02)


def test_the_detail_changes_nothing(sim):
    """`/api/agents/{aid}` selects an agent as a side effect of being read, which
    is right for the town and wrong for a table the pointer runs over."""
    before = sim.rng.bit_generator.state
    traders.detail(sim, sim.agents[0].aid)
    traders.overview(sim, limit=2000)
    assert sim.rng.bit_generator.state == before


# ------------------------------------------------------- empty configurations
def test_a_population_without_a_group_does_not_break_the_roster():
    """`n_leveraged = 0` is a legal configuration and one of the guided
    experiments uses it."""
    sim = Simulation(small(n_leveraged=0, n_passive=0))
    for _ in range(60):
        sim.step()
    result = traders.overview(sim, limit=2000)
    assert "leveraged" not in {g["group"] for g in result["groups"]}
    assert traders.overview(sim, kind="leveraged")["traders"] == []
    assert result["summary"]["count"] == len(sim.agents)
