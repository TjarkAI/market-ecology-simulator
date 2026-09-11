"""The matching engine is the foundation — if it is wrong, every result is."""

import pytest

from mes.orderbook import BUY, SELL, OrderBook


def test_no_cross_no_trade():
    book = OrderBook()
    book.submit(0, 1, BUY, 10, 99.0)
    trades, order = book.submit(0, 2, SELL, 10, 101.0)
    assert trades == []
    assert order is not None
    assert book.best_bid() == 99.0
    assert book.best_ask() == 101.0


def test_crossing_trades_at_resting_price():
    book = OrderBook()
    book.submit(0, 1, SELL, 10, 100.0)
    trades, _ = book.submit(1, 2, BUY, 10, 105.0)
    assert len(trades) == 1
    assert trades[0].price == 100.0  # price-time priority: resting order sets the price
    assert trades[0].qty == 10
    assert trades[0].buyer_id == 2 and trades[0].seller_id == 1


def test_partial_fill_leaves_remainder_resting():
    book = OrderBook()
    book.submit(0, 1, SELL, 4, 100.0)
    trades, order = book.submit(1, 2, BUY, 10, 100.0)
    assert sum(t.qty for t in trades) == 4
    assert order is not None and order.qty == 6
    assert book.best_bid() == 100.0
    assert book.best_ask() is None


def test_market_order_walks_the_book_and_does_not_rest():
    book = OrderBook()
    book.submit(0, 1, SELL, 5, 100.0)
    book.submit(0, 1, SELL, 5, 101.0)
    trades, order = book.submit(1, 2, BUY, 20, None)
    assert [t.price for t in trades] == [100.0, 101.0]
    assert sum(t.qty for t in trades) == 10
    assert order is None  # unfilled remainder is discarded, not rested
    assert book.best_ask() is None


def test_price_priority_best_first():
    book = OrderBook()
    book.submit(0, 1, SELL, 5, 102.0)
    book.submit(0, 2, SELL, 5, 100.0)
    book.submit(0, 3, SELL, 5, 101.0)
    trades, _ = book.submit(1, 9, BUY, 15, 102.0)
    assert [t.price for t in trades] == [100.0, 101.0, 102.0]


def test_time_priority_within_a_price_level():
    book = OrderBook()
    book.submit(0, 1, SELL, 5, 100.0)
    book.submit(0, 2, SELL, 5, 100.0)
    trades, _ = book.submit(1, 9, BUY, 5, 100.0)
    assert trades[0].seller_id == 1  # first in, first filled


def test_cancel_removes_liquidity():
    book = OrderBook()
    _, order = book.submit(0, 1, BUY, 10, 99.0)
    book.cancel(order.order_id)
    assert book.best_bid() is None
    trades, _ = book.submit(1, 2, SELL, 10, 99.0)
    assert trades == []


def test_expiry_clears_stale_orders():
    book = OrderBook()
    book.submit(0, 1, BUY, 10, 99.0, lifetime=5)
    book.expire(4)
    assert book.best_bid() == 99.0
    book.expire(5)
    assert book.best_bid() is None


def test_quantity_is_conserved():
    """Nothing may be created or destroyed by matching."""
    book = OrderBook()
    book.submit(0, 1, SELL, 7, 100.0)
    book.submit(0, 2, SELL, 3, 100.5)
    trades, order = book.submit(1, 3, BUY, 12, 101.0)
    filled = sum(t.qty for t in trades)
    resting = order.qty if order else 0
    assert filled + resting == 12
    assert filled == 10


@pytest.mark.parametrize("side", [BUY, SELL])
def test_zero_and_negative_quantities_are_ignored(side):
    book = OrderBook()
    assert book.submit(0, 1, side, 0, 100.0) == ([], None)
    assert book.submit(0, 1, side, -5, 100.0) == ([], None)


def _true_resting(book, side):
    """Depth counted the slow, obvious way — the reference for the fast one."""
    heap = book._bids if side == BUY else book._asks
    return sum(o.qty for _, _, o in heap if o.qty > 0 and o.order_id in book._live)


def test_depth_counter_matches_a_full_recount():
    """`resting_qty` is maintained incrementally for speed, so it can drift from
    the truth. Every path that changes the book is exercised here: resting,
    partial and full fills, cancellation, per-agent cancellation, expiry and the
    heap compaction."""
    import random

    rng = random.Random(4)
    book = OrderBook()
    live_ids = []

    for step in range(1, 400):
        action = rng.random()
        if action < 0.55:
            side = BUY if rng.random() < 0.5 else SELL
            _, order = book.submit(step, rng.randint(1, 12), side,
                                   rng.randint(1, 50),
                                   100.0 + rng.uniform(-1.0, 1.0), lifetime=rng.randint(2, 40))
            if order is not None:
                live_ids.append(order.order_id)
        elif action < 0.75:
            side = BUY if rng.random() < 0.5 else SELL
            book.submit(step, 99, side, rng.randint(1, 60), None)
        elif action < 0.85 and live_ids:
            book.cancel(live_ids.pop(rng.randrange(len(live_ids))))
        elif action < 0.92:
            book.cancel_agent(rng.randint(1, 12))
        else:
            book.expire(step)

        for side in (BUY, SELL):
            assert book.resting_qty(side) == _true_resting(book, side), (
                f"Schritt {step}, Seite {side}: Zaehler {book.resting_qty(side)} "
                f"gegen Nachzaehlung {_true_resting(book, side)}"
            )


def test_heaps_do_not_grow_without_bound():
    """Cancelled entries are only dropped when they reach the top of a heap, so
    without compaction a run that re-quotes constantly grows for ever."""
    book = OrderBook()
    for step in range(1, 3000):
        book.submit(step, 1, BUY, 10, 99.0, lifetime=10_000)
        book.cancel_agent(1)
    assert len(book._bids) < 500, f"Heap wuchs auf {len(book._bids)} Eintraege"
    assert book.resting_qty(BUY) == 0
