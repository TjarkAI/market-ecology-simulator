"""Continuous double auction order book.

Price formation is not a formula here: every trade is the result of one order
crossing another. Bubbles, liquidity gaps and cascades can only emerge if the
matching engine is real, so this module is deliberately the most carefully
tested part of the simulator.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

BUY = 1
SELL = -1


@dataclass(slots=True)
class Order:
    order_id: int
    agent_id: int
    side: int  # BUY (+1) or SELL (-1)
    price: float  # limit price
    qty: int  # remaining quantity
    ts: int  # step the order was submitted
    expiry: int  # step after which the order is dropped


@dataclass(slots=True)
class Trade:
    ts: int
    price: float
    qty: int
    buyer_id: int
    seller_id: int
    aggressor_side: int  # side of the incoming order that caused the trade


@dataclass
class OrderBook:
    """Price-time priority book with lazy deletion.

    Resting orders live in two heaps. Cancelled or expired orders are not
    removed eagerly; they are skipped (and dropped) when they surface at the
    top of the book. That keeps submission O(log n) without a bookkeeping
    structure that would be easy to get subtly wrong.
    """

    tick: float = 0.01
    _bids: list = field(default_factory=list)  # (-price, seq, Order)
    _asks: list = field(default_factory=list)  # (price, seq, Order)
    _live: dict = field(default_factory=dict)  # order_id -> Order
    _by_agent: dict = field(default_factory=dict)  # agent_id -> set of order_id
    # Running resting quantity per side. Kept incrementally because the obvious
    # implementation — walk the heap and add up the live orders — is O(heap), and
    # the heaps only shed cancelled entries when those reach the top. With market
    # makers re-quoting every step the dead entries pile up unboundedly, so a
    # depth query that looked cheap became the dominant cost of the whole
    # simulation and got slower the longer a run went on.
    _resting: dict = field(default_factory=lambda: {BUY: 0, SELL: 0})
    _dead: int = 0  # heap entries known to be dead, for compaction
    _seq: int = 0
    _next_id: int = 1

    # ------------------------------------------------------------------ utils
    def round_price(self, price: float) -> float:
        return round(round(price / self.tick) * self.tick, 10)

    def _prune(self, heap: list) -> None:
        """Drop dead orders from the top of a heap."""
        while heap:
            order = heap[0][2]
            if order.qty <= 0 or order.order_id not in self._live:
                heapq.heappop(heap)
            else:
                break

    # ------------------------------------------------------------------ views
    def best_bid(self) -> float | None:
        self._prune(self._bids)
        return self._bids[0][2].price if self._bids else None

    def best_ask(self) -> float | None:
        self._prune(self._asks)
        return self._asks[0][2].price if self._asks else None

    def mid(self, fallback: float) -> float:
        bid, ask = self.best_bid(), self.best_ask()
        if bid is not None and ask is not None:
            return 0.5 * (bid + ask)
        if bid is not None:
            return bid
        if ask is not None:
            return ask
        return fallback

    def spread(self) -> float | None:
        bid, ask = self.best_bid(), self.best_ask()
        return None if bid is None or ask is None else ask - bid

    def depth(self, side: int, levels: int = 10) -> list[tuple[float, int]]:
        """Aggregated (price, quantity) ladder — used by the dashboard."""
        heap = self._bids if side == BUY else self._asks
        book: dict[float, int] = {}
        for _, _, order in heap:
            if order.qty > 0 and order.order_id in self._live:
                book[order.price] = book.get(order.price, 0) + order.qty
        ladder = sorted(book.items(), reverse=(side == BUY))
        return ladder[:levels]

    def resting_qty(self, side: int) -> int:
        return max(0, self._resting.get(side, 0))

    # ------------------------------------------------------------------ writes
    def _forget(self, order: Order) -> None:
        """Remove an order from the indexes and the depth totals. The heap entry
        is left for `_prune` to discard when it surfaces."""
        if self._live.pop(order.order_id, None) is not None:
            self._resting[order.side] -= order.qty
            self._dead += 1
        owned = self._by_agent.get(order.agent_id)
        if owned is not None:
            owned.discard(order.order_id)
            if not owned:
                del self._by_agent[order.agent_id]

    def cancel(self, order_id: int) -> None:
        order = self._live.get(order_id)
        if order is not None:
            self._forget(order)

    def cancel_agent(self, agent_id: int) -> None:
        """Pull all of one agent's quotes.

        Called for every agent that acts, so it must not scan the whole book —
        hence the `_by_agent` index. With a few hundred resting orders and
        dozens of agents acting per step, the naive scan dominated the runtime.
        """
        for oid in self._by_agent.pop(agent_id, ()):
            order = self._live.pop(oid, None)
            if order is not None:
                self._resting[order.side] -= order.qty
                self._dead += 1

    def _compact(self) -> None:
        """Rebuild the heaps once the dead entries outnumber the live ones.

        Lazy deletion is the right trade for speed, but nothing ever removes a
        cancelled entry that is not at the top of the heap, so without this the
        heaps grow for the lifetime of the run.
        """
        if self._dead < 64 or self._dead < len(self._live):
            return
        for heap in (self._bids, self._asks):
            kept = [entry for entry in heap
                    if entry[2].qty > 0 and entry[2].order_id in self._live]
            heap[:] = kept
            heapq.heapify(heap)
        self._dead = 0

    def expire(self, ts: int) -> None:
        for order in [o for o in self._live.values() if o.expiry <= ts]:
            self._forget(order)

    def submit(
        self,
        ts: int,
        agent_id: int,
        side: int,
        qty: int,
        price: float | None,
        lifetime: int = 20,
    ) -> tuple[list[Trade], Order | None]:
        """Submit an order and match it against the opposite side.

        `price=None` means a market order: it is modelled as a limit order at
        an unreachable price, so it walks the book and any unfilled remainder
        is discarded rather than resting.
        """
        if qty <= 0:
            return [], None

        is_market = price is None
        limit = float("inf") if side == BUY else 0.0
        if not is_market:
            limit = self.round_price(price)

        trades: list[Trade] = []
        opposite = self._asks if side == BUY else self._bids

        while qty > 0:
            self._prune(opposite)
            if not opposite:
                break
            resting = opposite[0][2]
            crosses = resting.price <= limit if side == BUY else resting.price >= limit
            if not crosses:
                break

            traded = min(qty, resting.qty)
            resting.qty -= traded
            self._resting[resting.side] -= traded
            qty -= traded
            trades.append(
                Trade(
                    ts=ts,
                    price=resting.price,  # price-time priority: resting order sets the price
                    qty=traded,
                    buyer_id=agent_id if side == BUY else resting.agent_id,
                    seller_id=resting.agent_id if side == BUY else agent_id,
                    aggressor_side=side,
                )
            )
            if resting.qty == 0:
                self._forget(resting)
                heapq.heappop(opposite)

        if qty > 0 and not is_market:
            order = Order(
                order_id=self._next_id,
                agent_id=agent_id,
                side=side,
                price=limit,
                qty=qty,
                ts=ts,
                expiry=ts + lifetime,
            )
            self._next_id += 1
            self._seq += 1
            self._live[order.order_id] = order
            self._by_agent.setdefault(agent_id, set()).add(order.order_id)
            self._resting[side] += qty
            self._compact()
            entry = (-order.price, self._seq, order) if side == BUY else (order.price, self._seq, order)
            heapq.heappush(self._bids if side == BUY else self._asks, entry)
            return trades, order

        return trades, None
