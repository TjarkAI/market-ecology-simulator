"""The contract between the simulation and the city view.

`web/index.html` binds fields by name (`data-f="px"`). If a field disappears
from `mes/city.py`, the page silently shows a stale value — so the binding list
is read straight out of the HTML and checked against a real snapshot.
"""

import re
from pathlib import Path

import pytest

from mes.city import _ROADS, eur, millions, num, num_int, snapshot
from mes.config import Config
from mes.simulation import Simulation

WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"


@pytest.fixture(scope="module")
def sim() -> Simulation:
    s = Simulation(Config(seed=7, news_intensity=0.5))
    for _ in range(120):
        s.step()
    return s


def test_snapshot_covers_every_binding_in_the_page(sim):
    html = WEB.read_text()
    bound = set(re.findall(r'data-f(?:c|p2)?="([A-Za-z0-9_]+)"', html))
    # data-fp holds a CSS property name, not a field — exclude that attribute.
    snap = snapshot(sim)
    missing = sorted(name for name in bound if name not in snap)
    assert not missing, f"fields missing from the snapshot: {missing}"


DISTRICTS = ("mom", "val", "noi", "etf", "lev", "mkr", "cmp")


def test_capital_is_reported_in_euro_for_every_district(sim):
    capital = snapshot(sim)["capital"]
    assert set(capital) == {*DISTRICTS, "exp", "exch"}
    assert all(value >= 0 for value in capital.values())
    # The whole town is worth what the agents are worth. Clamped per agent, the
    # way _equity_by_group does it — a leveraged fund can have negative equity,
    # and a district cannot have negative height.
    total = sum(max(a.equity(sim.price), 0.0) for a in sim.agents)
    town = sum(capital[key] for key in DISTRICTS)
    assert town == pytest.approx(total, rel=0.02)


def test_flow_and_runners_exist_for_every_road(sim):
    snap = snapshot(sim)
    roads = {"mom", "val", "noise", "etf", "lev"}
    assert roads <= set(snap["flow"])
    assert roads <= set(snap["runners"])
    assert all(2.0 <= w <= 18.0 for w in snap["flow"].values())
    assert all(0 <= n <= 6 for n in snap["runners"].values())


def test_margin_call_alarm_follows_the_simulation(sim):
    assert snapshot(sim)["alarm"] in (0, 1)
    sim.step_margin_calls = 3
    assert snapshot(sim)["alarm"] == 1
    sim.step_margin_calls = 0


def test_quiet_market_still_fills_the_log(sim):
    sim.events.clear()
    rows = snapshot(sim)["log"]
    assert rows, "the town log must never be empty"
    assert all(len(row) == 3 for row in rows)


def test_number_format():
    assert num(1234.5) == "1,234.50"
    assert num(63.19, 1) == "63.2"
    assert num_int(9380) == "9,380"
    assert num_int(49_296.4) == "49,296"
    assert millions(11_000_000) == "11.0M"
    assert millions(240_150_000) == "240.2M"
    assert eur(171_727) == "€171,727"
    assert eur(900, sign=True) == "+€900"
    assert eur(-5) == "-€5"


def test_percentages_carry_no_space(sim):
    snap = snapshot(sim)
    assert snap["bankRate"].endswith("%") and " %" not in snap["bankRate"]
    for row in snap["markets"]:
        assert " %" not in row["chg"] and " %" not in row["gap"]


# ------------------------------------------------------------ crate colours
def test_buy_share_is_a_fraction_or_null_for_every_road(sim):
    """The crates the figures carry are coloured from this, so it has to be the
    real side of the orders: a share in [0, 1], and null for a road with no order,
    which is not the same as a road that only sold."""
    snap = snapshot(sim)
    assert set(snap["buyShare"]) == set(_ROADS)
    for key, group in _ROADS.items():
        share = snap["buyShare"][key]
        if sim.step_orders_by_group.get(group, 0) == 0:
            assert share is None, f"{key}: no orders this step, so no share"
        else:
            assert share is not None and 0.0 <= share <= 1.0, f"{key}: {share}"


def test_a_group_that_only_buys_reports_one():
    """The ETF depot only ever buys — `PassiveInvestor.act` returns BUY orders and
    nothing else — so every step it trades its share must be exactly 1.0."""
    sim = Simulation(Config(seed=11, passive_interval=5))
    seen = 0
    for _ in range(200):
        sim.step()
        snap = snapshot(sim)
        if sim.step_orders_by_group.get("passive", 0):
            seen += 1
            assert snap["buyShare"]["etf"] == 1.0
        else:
            assert snap["buyShare"]["etf"] is None
        # Market makers quote both sides, so whenever they trade the share is a
        # proper fraction of their orders and never claims more buys than orders.
        buys = sim.step_buys_by_group.get("maker", 0)
        assert buys <= sim.step_orders_by_group.get("maker", 0)
    assert seen, "the ETF depot never traded, so the test proved nothing"


def test_selected_agent_can_be_pinned(sim):
    target = sim.agents[42]
    assert snapshot(sim, selected_id=target.aid)["unit"].startswith(f"#{target.aid}")


# --------------------------------------------------- one exchange per market
def test_every_market_gets_an_exchange(sim):
    """The town had one exchange because the model had one market."""
    snap = snapshot(sim)
    assert [m["sym"] for m in snap["markets"]] == list(sim.markets)
    for row in snap["markets"]:
        assert row["eur"] >= 0
        assert row["px"] and row["chg"] and row["gap"]


def test_exactly_one_market_is_selected(sim):
    snap = snapshot(sim)
    assert sum(1 for m in snap["markets"] if m["sel"]) == 1
    assert snap["focus"] == sim.primary


def test_the_read_outs_follow_the_selected_market(sim):
    """Price, ticker and book line all have to agree on which market they are
    about. They did not at first: the book line followed the selection and the
    ticker kept reporting the first instrument, which reads as a bug because it
    is one."""
    for symbol in sim.markets:
        snap = snapshot(sim, symbol=symbol)
        assert snap["focus"] == symbol
        assert snap["tick"].startswith(symbol)
        assert snap["book"].startswith(symbol)
        assert snap["px"] == num(sim.markets[symbol].price)
        assert [m["sym"] for m in snap["markets"] if m["sel"]] == [symbol]


def test_an_unknown_symbol_falls_back_to_the_primary_market(sim):
    snap = snapshot(sim, symbol="GOLD")
    assert snap["focus"] == sim.primary


# ------------------------------------------------------------- the order book
# The book is where a price in this model comes from — every trade is one order
# crossing another — and no page drew it until it was asked for. It rides along
# with the snapshot because the town already polls this payload.

def test_the_snapshot_carries_the_order_book(sim):
    ladder = snapshot(sim)["ladder"]
    assert set(ladder) == {"bids", "asks", "bid", "ask", "spread", "spreadBp",
                           "restingBid", "restingAsk"}
    assert len(ladder["bids"]) <= 8 and len(ladder["asks"]) <= 8
    for level in ladder["bids"] + ladder["asks"]:
        price, qty = level
        assert price > 0 and qty > 0


def test_the_book_is_sorted_outwards_from_the_touch(sim):
    """Best first on both sides — the view reverses the asks to meet in the middle,
    and it can only do that if they arrive in a known order."""
    ladder = snapshot(sim)["ladder"]
    bids = [price for price, _ in ladder["bids"]]
    asks = [price for price, _ in ladder["asks"]]
    assert bids == sorted(bids, reverse=True), "the bid side must descend"
    assert asks == sorted(asks), "the ask side must ascend"
    if bids and asks:
        assert bids[0] < asks[0], "the best bid must not sit above the best ask"


def test_the_book_follows_the_selected_market(sim):
    """Same rule as the ticker and the book line: the read-outs agree on which
    market they are about."""
    for symbol, market in sim.markets.items():
        ladder = snapshot(sim, symbol=symbol)["ladder"]
        expected = market.book.depth(1, 8)
        assert [p for p, _ in ladder["bids"]] == [round(p, 2) for p, _ in expected]


def test_an_empty_book_still_answers(sim):
    """A market can be one-sided, and the panel has to say so rather than throw."""
    market = sim.markets[sim.primary]
    saved = market.book

    class Empty:
        """Everything the snapshot asks a book for, answering with nothing."""

        def depth(self, side, levels):
            return []

        def resting_qty(self, side):
            return 0

    market.book = Empty()
    try:
        ladder = snapshot(sim)["ladder"]
        assert ladder["bids"] == [] and ladder["asks"] == []
        assert ladder["spread"] == "—" and ladder["spreadBp"] == "—"
    finally:
        market.book = saved
