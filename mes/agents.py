"""The market participants.

Every agent sees the same markets and reacts differently. None can see the true
fundamental value directly, none knows what the others are about to do, and none
has a model of the price. All market behaviour in this project comes out of these
few dozen lines of decision logic.

Agents hold a portfolio: cash plus a position in each instrument. On each turn an
agent trades **one** instrument — the one furthest from where it wants to be. That
keeps the work per step constant as instruments are added, and it matches how
order flow actually arrives: one order at a time, not a simultaneous rebalance of
everything.

Order intents are `(symbol, side, qty, limit_price | None)`. The simulation
applies budget and inventory constraints; agents do not police themselves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .orderbook import BUY, SELL


def clamp(value: float, low: float, high: float) -> float:
    """Plain-Python clamp, deliberately not `np.clip`.

    These agents are the hot path: a few hundred of them decide every step, each
    touching every instrument. numpy is fast on arrays and slow on single
    numbers — profiling showed `np.clip` alone called two thousand times per step
    and accounting for over a third of the whole simulation's runtime. Scalars
    belong in the standard library.
    """
    return low if value < low else high if value > high else value


@dataclass
class Quote:
    """What an agent may know about one instrument at decision time."""

    symbol: str
    mid: float
    best_bid: float | None
    best_ask: float | None
    trend: float  # EMA of log returns over chartist_window
    vol: float  # EMA of |log returns|, normalises the trend signal
    fundamental: float  # the true fair value, which nobody observes directly
    fair_slow: float  # the lagged estimate agents actually act on
    depth_ask: int  # shares resting on the offer — what a buyer can hit
    depth_bid: int  # shares resting on the bid — what a seller can hit
    index_weight: float  # share of total fair value, used by the ETF


@dataclass
class MarketCtx:
    """The whole market state an agent is allowed to see."""

    t: int
    quotes: dict[str, Quote]
    sentiment: float
    flow_multiplier: float  # central-bank scaling on savings-plan inflows
    intensity: float  # how fast information is arriving, 1 = average
    cfg: object

    @property
    def symbols(self) -> list[str]:
        return list(self.quotes)

    def marks(self) -> dict[str, float]:
        return {symbol: quote.mid for symbol, quote in self.quotes.items()}


@dataclass
class Agent:
    aid: int
    cash: float
    kind: str = "base"
    strategy: str = "base"  # adaptive agents flip this between value/momentum
    bias: float = 0.0  # persistent personal misperception of fair value
    perf: float = 0.0  # EMA of recent wealth growth
    last_wealth: float = 0.0
    # Equity at spawn. `last_wealth` is the strategy review's baseline and moves
    # every review, so it cannot answer "how has this trader done" — which is the
    # first question anyone asks of a list of traders.
    start_equity: float = 0.0
    liquidations: int = 0
    positions: dict = field(default_factory=dict)
    symbol: str | None = None  # set for agents tied to one instrument
    # Last prices the simulation marked this agent to. Kept so equity can be
    # asked for without passing every price around; the simulation refreshes it
    # once per step.
    marks: dict = field(default_factory=dict)
    # This agent's own random stream. Every draw an agent makes comes from here
    # rather than from a stream shared with the market, and that is what makes a
    # comparison of two configurations mean anything: with one shared stream, how
    # many numbers an agent consumed depended on what it decided, so the first
    # behavioural difference desynchronised everybody and the two runs became
    # different worlds rather than the same world under two policies.
    rng: np.random.Generator | None = None
    # Size multiplier for agents that serve one market. A market maker is tied to
    # its instrument, so its cash does not grow with the number of markets the way
    # a portfolio holder's does — but the flow it has to absorb in that market
    # does. Without this the book was thin by exactly the instrument count and the
    # volatility doubled.
    scale: float = 1.0

    # ------------------------------------------------------------ portfolio
    def position(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def add(self, symbol: str, quantity: int) -> None:
        self.positions[symbol] = self.positions.get(symbol, 0) + quantity

    @property
    def shares(self) -> int:
        """Total shares held across all instruments.

        Kept because plenty of code and several tests ask an agent how much stock
        it holds without caring which. Per-instrument work uses `position()`.
        """
        return sum(self.positions.values())

    def _prices(self, prices=None) -> dict:
        """Accept a price dict, or fall back to the last marks.

        A single float is accepted and ignored on purpose: the city view and the
        older tests call `equity(sim.price)` from the days of one instrument, and
        with a portfolio that number cannot answer the question. The marks the
        simulation set are used instead, which is the correct answer to what was
        being asked.
        """
        if isinstance(prices, dict):
            return prices
        return self.marks

    def equity(self, prices=None) -> float:
        marks = self._prices(prices)
        return self.cash + sum(qty * marks.get(sym, 0.0) for sym, qty in self.positions.items())

    def exposure(self, prices=None) -> float:
        marks = self._prices(prices)
        return sum(abs(qty) * marks.get(sym, 0.0) for sym, qty in self.positions.items())

    def leverage(self, prices=None) -> float:
        eq = self.equity(prices)
        return self.exposure(prices) / eq if eq > 1e-9 else float("inf")

    # ------------------------------------------------------------- decision
    def act(self, ctx: MarketCtx) -> list[tuple[str, int, int, float | None]]:
        return []

    # -------------------------------------------------------------- helpers
    def _pick(self, targets: dict[str, float], ctx: MarketCtx) -> str | None:
        """Choose the instrument to trade this turn: the biggest gap between the
        target position and the current one, measured in money.

        A little randomness is mixed in so the choice is not deterministic — a
        market where everyone always works the same name first is not a market.
        """
        best, best_score = None, 0.0
        for symbol, target in targets.items():
            quote = ctx.quotes.get(symbol)
            if quote is None:
                continue
            gap = abs(target - self.position(symbol)) * quote.mid
            score = gap * (0.5 + self.rng.random())
            if score > best_score:
                best, best_score = symbol, score
        return best

    def _order(
        self, symbol: str, target_shares: float, ctx: MarketCtx,
        patience: float, reference: float,
    ) -> list[tuple[str, int, int, float | None]]:
        """Turn a desired position into one limit order.

        Two separate decisions. The *quantity* comes from how far the current
        position is from the target. The *price* comes from `reference` — the
        price this agent considers justified, which need not be the current mid.

        That separation is what anchors the market. If everyone quoted around the
        mid, the mid would be free to drift anywhere and the price series would be
        a smooth ramp with no restoring force. A value investor instead quotes
        towards its own valuation, and that offer is what drags the price back.

        `patience` sets the scatter around the reference: a buyer in a hurry pays
        up, a seller in a hurry undercuts, so the aggression term follows the side.
        """
        quote = ctx.quotes[symbol]
        gap = target_shares - self.position(symbol)

        band = ctx.cfg.rebalance_band * max(abs(target_shares), 1.0)
        if abs(gap) < max(1.0, band):
            return []

        side = BUY if gap > 0 else SELL
        qty = int(min(abs(gap), max(1.0, abs(gap) * 0.35)))

        # Participation limit. A desired position change can be thousands of
        # shares while the book holds a few hundred; sending the whole thing
        # sweeps every level and moves the price by percent at a time. Real desks
        # work to a participation rate, and without one the model's volatility is
        # dominated by execution mechanics rather than by what agents think.
        depth = quote.depth_ask if side == BUY else quote.depth_bid
        qty = min(qty, max(3, int(depth * ctx.cfg.max_participation)))
        if qty < 1:
            return []

        offset = self.rng.uniform(-patience, patience) + side * patience * 0.35
        return [(symbol, side, qty, max(0.01, reference * (1.0 + offset)))]

    def _budget_shares(self, ctx: MarketCtx) -> float:
        """Wealth expressed in shares of an average instrument."""
        wealth = max(self.equity(ctx.marks()), 1.0)
        prices = [q.mid for q in ctx.quotes.values()]
        average = (sum(prices) / len(prices)) if prices else 1.0
        return wealth / max(average, 0.01)


class NoiseTrader(Agent):
    """Trades for reasons the model does not represent: rebalancing, taxes,
    boredom. Provides the background liquidity everyone else trades against."""

    def act(self, ctx):
        cfg = ctx.cfg
        symbols = ctx.symbols
        if not symbols:
            return []
        symbol = symbols[int(self.rng.integers(len(symbols)))]
        quote = ctx.quotes[symbol]
        side = BUY if self.rng.random() < 0.5 else SELL
        qty = int(self.rng.integers(1, 12))
        price = quote.mid * (1.0 + self.rng.normal(0.0, cfg.noise_spread))
        return [(symbol, side, qty, max(0.01, price))]


class AdaptiveTrader(Agent):
    """The heart of the model.

    Runs either a value or a momentum rule and periodically reconsiders which one
    to use, based on how the two rules have been doing. That switching is what
    makes volatility cluster.

    Across instruments the rule decides the *weights*: a value investor tilts
    towards whatever looks cheapest, a trend follower towards whatever is running.
    Neither diversifies on purpose, so sector concentration is a by-product of the
    strategy mix rather than a setting.
    """

    def _signals(self, ctx: MarketCtx) -> dict[str, float]:
        cfg = ctx.cfg
        out = {}
        for symbol, quote in ctx.quotes.items():
            if self.strategy == "value":
                perceived = quote.fair_slow * math.exp(self.bias * cfg.perception_noise)
                mispricing = (perceived - quote.mid) / max(quote.mid, 0.01)
                out[symbol] = clamp(mispricing * 8.0, -1.0, 1.0) * cfg.fundamental_aggression
            else:
                # The raw trend is tiny and its scale depends on the volatility
                # regime. Dividing by volatility turns it into a z-score, so the
                # aggression parameter means the same thing in a calm market and
                # in a crash.
                z = quote.trend / (quote.vol + 1e-6)
                signal = clamp(z / 3.0, -1.0, 1.0) * (cfg.chartist_aggression / 100.0)
                out[symbol] = signal + ctx.sentiment * 0.25
        return out

    def act(self, ctx):
        cfg = ctx.cfg
        signals = self._signals(ctx)
        if not signals:
            return []

        # Half the portfolio in stock at a neutral signal, shifted by the view,
        # then split evenly across the instruments.
        #
        # The division by `n` matters and getting it wrong is not obvious: a
        # weight of `1/n * (1 + n * signal / 2)` looks like the same rule spread
        # over n names, but at n = 1 it gives a base weight of 1.0 rather than
        # 0.5. Every agent then wanted to be fully invested, and the price settled
        # at nearly twice fair value. Written this way the rule reduces exactly to
        # the single-asset rule the model was calibrated on.
        n = len(signals)
        equity = max(self.equity(ctx.marks()), 1.0)
        weights = {
            symbol: clamp(0.5 + signal, 0.0, 1.0) / n
            for symbol, signal in signals.items()
        }
        targets = {
            symbol: equity * weight / max(ctx.quotes[symbol].mid, 0.01)
            for symbol, weight in weights.items()
        }

        symbol = self._pick(targets, ctx)
        if symbol is None:
            return []

        quote = ctx.quotes[symbol]
        signal = signals[symbol]
        if self.strategy == "value":
            perceived = quote.fair_slow * math.exp(self.bias * cfg.perception_noise)
            mispricing = (perceived - quote.mid) / max(quote.mid, 0.01)
            # Concedes only a fraction of the valuation gap per order. A limit at
            # the full valuation would sweep every bid down to that level and act
            # like a market order; a real value investor undercuts to get filled,
            # it does not give the position away.
            pull = clamp(mispricing, -0.6, 0.6) * cfg.value_price_pull
            reference, patience = quote.mid * (1.0 + pull), 0.006
        else:
            # Extrapolates: expects the move to continue a little further and is
            # willing to pay for that expectation. No valuation enters at all.
            reference, patience = quote.mid * (1.0 + signal * 0.02), 0.003

        return self._order(symbol, targets[symbol], ctx, patience, reference)


class PassiveInvestor(Agent):
    """The ETF. No opinion, no model, no reaction to news.

    Receives money on a schedule and buys at whatever price the book offers,
    spread across instruments by index weight. Its only market-relevant property
    is that it is price-insensitive.
    """

    def act(self, ctx):
        cfg = ctx.cfg
        if ctx.t % max(1, cfg.passive_interval) != 0:
            return []
        # Channel three: when cash pays, less of it goes into equities.
        self.cash += cfg.passive_inflow * ctx.flow_multiplier
        if not ctx.quotes:
            return []

        # Buy the index: one instrument per turn, chosen with probability equal
        # to its weight, so over time the holdings track the weights without
        # having to trade everything at once.
        symbols = ctx.symbols
        weights = np.array([max(ctx.quotes[s].index_weight, 1e-9) for s in symbols])
        weights = weights / weights.sum()
        symbol = symbols[int(self.rng.choice(len(symbols), p=weights))]

        quote = ctx.quotes[symbol]
        reference = quote.best_ask or quote.mid
        qty = int(self.cash // max(reference, 0.01))
        if qty < 1:
            return []
        return [(symbol, BUY, qty, None)]  # market order: takes any price


class LeveragedFund(Agent):
    """Borrows to amplify a blended value/momentum view, concentrated in whatever
    it is most convinced about.

    Forced deleveraging is handled by the simulation, not here — an agent in a
    margin call does not get to choose. Because the margin test is at portfolio
    level, a call triggered by one sector is met by selling all of them, which is
    how stress in one part of the market reaches the rest.
    """

    def act(self, ctx):
        cfg = ctx.cfg
        marks = ctx.marks()
        equity = self.equity(marks)
        if equity <= 0 or not ctx.quotes:
            return []

        convictions = {}
        for symbol, quote in ctx.quotes.items():
            perceived = quote.fair_slow * math.exp(self.bias * cfg.perception_noise * 0.5)
            value_signal = (perceived - quote.mid) / max(quote.mid, 0.01) * 6.0
            trend_signal = quote.trend / (quote.vol + 1e-6) / 3.0 * (cfg.chartist_aggression / 100.0)
            convictions[symbol] = math.tanh(value_signal + trend_signal + ctx.sentiment * 0.2)

        # A fund that is only invested when optimistic never borrows, and then
        # margin calls are dead code. A leveraged fund carries a book at all times
        # and sizes it with conviction; going flat entirely is what a margin call
        # is for.
        appetite = {s: clamp(0.7 + 0.5 * c, 0.1, 1.0) for s, c in convictions.items()}
        n = len(appetite)
        # Each name gets its share of the allowed leverage, sized by conviction.
        # Dividing by `n` keeps total leverage at `max_leverage * mean(appetite)`,
        # which is the single-asset rule when there is one instrument — allocating
        # the full allowance to every name instead would leave the fund
        # permanently at its limit and margin calls would fire constantly.
        targets = {
            s: equity * cfg.max_leverage * appetite[s] / n / max(ctx.quotes[s].mid, 0.01)
            for s in appetite
        }

        symbol = self._pick(targets, ctx)
        if symbol is None:
            return []
        quote = ctx.quotes[symbol]
        perceived = quote.fair_slow * math.exp(self.bias * cfg.perception_noise * 0.5)
        gap = (perceived - quote.mid) / max(quote.mid, 0.01)
        reference = quote.mid * (1.0 + clamp(gap, -0.6, 0.6) * cfg.value_price_pull * 0.5)
        return self._order(symbol, targets[symbol], ctx, 0.004, reference)


class MarketMaker(Agent):
    """Quotes both sides of one instrument continuously and takes no view.

    Without this agent the book has no depth of its own: everyone else cancels and
    re-quotes as their opinion changes, so resting liquidity is an accident. A few
    hundred shares against orders of several thousand means every order sweeps
    every level, and the resulting volatility says more about the matching engine
    than about what anyone believes.

    The inventory lean is applied to quoted *sizes*, not prices. Both control
    inventory, but skewing prices moves the mid — and the mid is the market price,
    so a price skew is a direct mean-reverting force on the market itself.
    """

    def act(self, ctx):
        cfg = ctx.cfg
        quote = ctx.quotes.get(self.symbol)
        if quote is None:
            return []

        # Wider quotes in a fast market — the classic inventory-risk response.
        # How strongly is a knob, because it pulls against the volume/volatility
        # relationship: most volume is market-maker volume, so a maker that backs
        # right off when things get busy suppresses trading exactly when a real
        # market trades most.
        half = quote.mid * cfg.mm_spread * (1.0 + cfg.mm_vol_sensitivity * quote.vol / 0.002)
        half = max(half, quote.mid * 0.0002)

        held = self.position(self.symbol)
        limit = max(1.0, cfg.mm_inventory_limit * self.scale)
        lean = clamp(held / limit, -1.0, 1.0)
        tilt = lean * clamp(cfg.mm_skew, 0.0, 1.0)

        # More size when information is arriving quickly, not less. A maker that
        # only widens its spread in a busy market withdraws exactly when the market
        # trades most — and since most volume is maker volume, that broke the
        # volume/volatility relationship at the source.
        busy = clamp(ctx.intensity ** cfg.mm_size_elasticity, 0.5, 3.0)
        size = max(1, int(cfg.mm_quote_size * self.scale * busy))
        return [
            (self.symbol, BUY, max(1, int(size * (1.0 - tilt))), max(0.01, quote.mid - half)),
            (self.symbol, SELL, max(1, int(size * (1.0 + tilt))), max(0.02, quote.mid + half)),
        ]


class Company(Agent):
    """The issuer of one instrument. Sells new shares when they are expensive and
    buys them back when they are cheap.

    Without an issuer the model has a one-way ratchet. Demand from trend followers
    and savings plans is persistent, but the supply of shares is fixed: value
    investors eventually sell out, market makers hit their inventory limit, and
    from then on nothing is offered at all. The price then rises to a multiple of
    fair value and simply stays there.

    Its position goes negative because a negative position *is* the float it has
    issued — the company is the counterparty of everyone who owns the stock.
    """

    def act(self, ctx):
        cfg = ctx.cfg
        if ctx.t % max(1, cfg.issue_interval) != 0:
            return []
        quote = ctx.quotes.get(self.symbol)
        if quote is None:
            return []

        # The issuer reads reports like everyone else.
        premium = (quote.mid - quote.fair_slow) / max(quote.fair_slow, 0.01)

        # Proportional, not on/off. Issuing a fixed slab the moment a threshold is
        # crossed and nothing below it is bang-bang control, and it makes the price
        # oscillate: the correction overshoots, the premium flips sign, issuance
        # stops dead. Sizing the response to how far the premium has run past the
        # threshold removes the limit cycle.
        excess = (abs(premium) - cfg.issue_threshold) / max(cfg.issue_threshold, 1e-6)
        intensity = clamp(excess, 0.0, 1.0)
        if intensity <= 0.0:
            return []

        if premium > 0:
            qty = int(max(1.0, quote.depth_bid * cfg.issue_rate * intensity))
            return [(self.symbol, SELL, qty, quote.mid * (1.0 - 0.0015))]

        if self.cash > quote.mid:
            budget = self.cash * cfg.buyback_share * intensity
            qty = int(min(budget / max(quote.mid, 0.01),
                          max(1.0, quote.depth_ask * cfg.issue_rate * intensity)))
            if qty >= 1:
                return [(self.symbol, BUY, qty, quote.mid * (1.0 + 0.0015))]
        return []


KIND_TO_CLASS = {
    "noise": NoiseTrader,
    "adaptive": AdaptiveTrader,
    "passive": PassiveInvestor,
    "leveraged": LeveragedFund,
    "maker": MarketMaker,
    "company": Company,
}
