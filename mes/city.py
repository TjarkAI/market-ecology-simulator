"""The city view of a simulation state.

The frontend in `web/` draws a small isometric town. Nothing in that town is
decorative: block height is the capital standing in a district, street width is
the order flow on that road, and a runner is ten agents carrying an order to
the exchange. This module is the only place where simulation state is turned
into those numbers, so the drawing code never has to interpret anything.

Heights are reported as plain euro amounts. Turning euro into floors is the
view's job: it starts at €30,000 per floor and steps the scale down only when
the tallest block would grow out of the plate, then prints the scale it used.
`SCALE` states the starting point so the API can be read without the frontend.
"""

from __future__ import annotations

from .simulation import Simulation

SCALE = {"base_floor_eur": 30_000, "floor_px": 5, "agents_per_figure": 10}

# Which agent group walks which road into the exchange.
_ROADS = {
    "mom": "momentum", "val": "value", "noise": "noise",
    "etf": "passive", "lev": "leveraged",
    # The market makers sit beside the exchange and the issuer supplies it with
    # new stock. Both trade every single step, so both need a road: without one,
    # the steadiest order flow in the market would be invisible.
    "mkr": "maker", "cmp": "company",
}

ORANGE, TEAL, GOLD, GREY, RED, GREEN, BLUE = (
    "#e07434", "#2f9e86", "#b7891f", "#65728a", "#d43f3f", "#1c9a52", "#5872c9",
)
# Text colour for a read-out with nothing to flag, on the light panels.
INK = "#172033"

# The display name of the district an agent belongs to. `Simulation.group_of`
# returns the internal key; the panel should say what the reader sees on the map.
_GROUP_NAMES = {
    "momentum": "Adaptive Quarter",
    "value": "Adaptive Quarter",
    "noise": "Noise Suburb",
    "passive": "ETF Depot",
    "leveraged": "Leverage Tower",
    "maker": "Market Makers",
    "company": "Issuer",
}

# What kind of agent it is, which is not the same as what it is currently doing:
# an adaptive trader is ADAPTIVE and may be running the value rule this minute. The
# unit card used to print "Lv 12" here — a level from no game, tied to nothing.
_KIND_LABELS = {
    "adaptive": "ADAPTIVE", "noise": "NOISE", "passive": "ETF",
    "leveraged": "LEVERAGED", "maker": "MAKER", "company": "ISSUER",
}


# --------------------------------------------------------------- formatting
def num(value: float, digits: int = 2) -> str:
    """A number with comma thousands and a point decimal: 1,234.50."""
    return f"{value:,.{digits}f}"


def num_int(value: float) -> str:
    """A whole number with comma thousands: 49,296."""
    return f"{int(round(value)):,}"


def millions(value: float) -> str:
    """An amount in millions, one decimal: 240.2M."""
    return num(value / 1e6, 1) + "M"


def eur(value: float, sign: bool = False) -> str:
    """A whole euro amount: €171,727, or +€900 with `sign`. The minus goes
    before the symbol, as in -€5."""
    prefix = "-" if value < 0 else ("+" if sign else "")
    return f"{prefix}€{num_int(abs(value))}"


def pct(part: float, whole: float) -> str:
    return f"{0.0 if whole <= 0 else part / whole * 100:.0f}%"


# ------------------------------------------------------------------ helpers
def _equity_by_group(sim: Simulation) -> dict[str, float]:
    out: dict[str, float] = {}
    for agent in sim.agents:
        group = sim.group_of(agent)
        out[group] = out.get(group, 0.0) + max(agent.equity(sim.price), 0.0)
    return out


def _count_by_group(sim: Simulation) -> dict[str, int]:
    out: dict[str, int] = {}
    for agent in sim.agents:
        group = sim.group_of(agent)
        out[group] = out.get(group, 0) + 1
    return out


def _street_width(orders: int, busiest: int) -> float:
    """Order count → street width in px, relative to the busiest road of the
    step. Absolute counts would saturate; the comparison is what reads."""
    if orders <= 0:
        return 2.0
    return round(3.0 + 15.0 * orders / max(busiest, 1), 1)


def _runner_count(orders: int, busiest: int) -> int:
    """One figure per ten agents, scaled so the widest road is fullest."""
    if orders <= 0:
        return 0
    return max(1, min(6, round(1 + 5 * orders / max(busiest, 1))))


def _mood_colour(mood: float) -> str:
    if mood >= 62:
        return ORANGE
    if mood <= 38:
        return RED
    return TEAL


def _change(sim: Simulation, lookback: int = 20, market=None) -> tuple[str, str]:
    prices = (market or sim.market).prices
    price = (market or sim.market).price
    past = prices[max(0, len(prices) - 1 - lookback)]
    change = (price / max(past, 1e-9) - 1.0) * 100
    arrow = "▲" if change >= 0 else "▼"
    colour = TEAL if change >= 0 else RED
    return f"{arrow} {abs(change):.1f}%", colour


def _issued(sim: Simulation) -> int:
    """Shares the issuer has sold into the market.

    Its position is negative because a negative position *is* the float it has
    issued — the company is the counterparty of everyone who owns the stock.
    """
    return sum(agent.shares for agent in sim.agents if agent.kind == "company")


def _book_value(sim: Simulation, symbol: str | None = None) -> float:
    """Resting size on both sides at the current price — an exchange's height."""
    market = sim.markets[symbol or sim.primary]
    return sum(market.depth()) * market.price


def _ladder(sim: Simulation, symbol: str, levels: int = 8) -> dict:
    """The resting orders on both sides of the focused market.

    The book is where a price comes from — every trade in this model is one order
    crossing another — and it was the one part of the mechanism no page ever drew.
    It rides along with the snapshot rather than getting an endpoint of its own
    because the town already polls this payload; sixteen levels of two numbers is
    cheaper than a second request.

    Prices come back as plain floats. The bars are drawn from the sizes and the view
    needs to compare them, which is arithmetic, not formatting.
    """
    market = sim.markets[symbol]
    bids = market.book.depth(1, levels)
    asks = market.book.depth(-1, levels)
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    spread = (best_ask - best_bid) if best_bid is not None and best_ask is not None else None
    return {
        # Best first on both sides, the way the book is read outwards from the touch.
        "bids": [[round(price, 2), qty] for price, qty in bids],
        "asks": [[round(price, 2), qty] for price, qty in asks],
        "bid": num(best_bid) if best_bid is not None else "—",
        "ask": num(best_ask) if best_ask is not None else "—",
        "spread": num(spread) if spread is not None else "—",
        # In basis points, which is how a spread is usually compared across prices.
        "spreadBp": (f"{spread / market.price * 10_000:.0f} bp"
                     if spread is not None and market.price > 0 else "—"),
        "restingBid": num_int(sum(qty for _, qty in bids)),
        "restingAsk": num_int(sum(qty for _, qty in asks)),
    }


def _markets(sim: Simulation, selected: str) -> list[dict]:
    """One exchange per instrument.

    The town used to have a single exchange because the model had a single market.
    Now each one gets its own building, as tall as its own book is deep, and the
    read-outs follow whichever is selected. The districts stay as they were: the
    agents are one population holding a portfolio across all of them, which is
    exactly why the capital does not divide by market.
    """
    out = []
    for symbol, market in sim.markets.items():
        past_index = max(0, len(market.prices) - 1 - 2 * sim.cfg.steps_per_day)
        past = market.prices[past_index]
        change = (market.price / max(past, 1e-9) - 1.0) * 100
        out.append({
            "sym": symbol,
            "px": num(market.price),
            "chg": f"{'▲' if change >= 0 else '▼'} {abs(change):.1f}%",
            "chgFg": TEAL if change >= 0 else RED,
            "eur": _book_value(sim, symbol),
            "depth": num_int(sum(market.depth())),
            "sel": symbol == selected,
            # How far this market sits from its own fair value, which is the thing
            # the districts cannot show.
            "gap": f"{(market.price / max(market.instrument.fundamental, 1e-9) - 1) * 100:+.0f}%",
        })
    return out


# --------------------------------------------------------------- the payload
def snapshot(sim: Simulation, selected_id: int | None = None,
             symbol: str | None = None) -> dict:
    cfg = sim.cfg
    focus = symbol if symbol in sim.markets else sim.primary
    market = sim.markets[focus]
    equity = _equity_by_group(sim)
    counts = _count_by_group(sim)
    orders = sim.step_orders_by_group

    adaptive_total = counts.get("momentum", 0) + counts.get("value", 0)
    total_wealth = sum(equity.values())
    mood = sim.fear_greed()
    change, change_colour = _change(sim, market=market)
    markets = _markets(sim, focus)

    lev_equity = equity.get("leveraged", 0.0)
    lev_exposure = sum(
        agent.exposure(sim.price) for agent in sim.agents if agent.kind == "leveraged"
    )
    lev_count = counts.get("leveraged", 0)
    lev_ratio = lev_exposure / lev_equity if lev_equity > 1e-6 else 0.0

    agent = _selected(sim, selected_id)
    review_step = sim.t % max(1, cfg.switch_interval)
    busiest = max(orders.values()) if orders else 0
    buys = sim.step_buys_by_group

    return {
        "seed": cfg.seed,
        "agents": len(sim.agents),
        "scale": SCALE,

        # --- header read-outs -------------------------------------------
        "step": num_int(sim.t),
        "cap": millions(total_wealth),
        "mood": f"{mood:.0f}",
        "moodFg": _mood_colour(mood),
        "vol": num_int(market.step_volume),
        "px": num(market.price),
        # Which market the read-outs are about, and all of them for the exchanges.
        "focus": focus,
        "markets": markets,
        "chg": change,
        "chgFg": change_colour,

        # --- ticker: the newest event, or the market state --------------
        **_ticker(sim, market=market),

        # --- what the landmarks on the plate say -------------------------
        # Every one of these was a fixed number in the HTML: the central bank
        # showed a fair value from a demo snapshot, the suburb always had 200
        # inhabitants and the depot always took in €27,000. A label that never
        # moves while the thing it labels does is worse than no label.
        "day": num_int(sim.t // max(1, cfg.steps_per_day)),
        "bankRate": num(sim.bank.rate * 100, 2) + "%",
        "bankSub": f"Inflation {num(sim.bank.inflation * 100, 2)}% · "
                   f"target {num(cfg.inflation_target * 100, 2)}%",
        "noiseN": num_int(counts.get("noise", 0)),
        "etfN": num_int(counts.get("passive", 0)),
        "etfFlow": eur(cfg.passive_inflow * counts.get("passive", 0), sign=True),
        "etfSub": f"every {cfg.passive_interval} steps · price-insensitive",
        "mkrN": num_int(counts.get("maker", 0)),
        "mkrSub": f"book depth {num_int(sum(market.depth()))} shares",
        "cmpN": num_int(-min(0, _issued(sim))),
        "cmpSub": f"issues from {num(cfg.issue_threshold * 100, 0)}% above fair value",

        # --- the adaptive quarter ---------------------------------------
        "mom": num_int(counts.get("momentum", 0)),
        "momW": pct(counts.get("momentum", 0), adaptive_total),
        "val": num_int(counts.get("value", 0)),
        "valW": pct(counts.get("value", 0), adaptive_total),
        "mov": num_int(sim.switched_last_review),
        "movW": pct(sim.switched_last_review, adaptive_total),
        "quarter": f"{counts.get('momentum', 0)} / {counts.get('value', 0)}",

        # --- this step ---------------------------------------------------
        "act": num_int(max(1, int(len(sim.agents) * cfg.activation_rate))),
        "ord": num_int(sim.step_orders),
        "trd": num_int(sim.step_trades),
        "mc": num_int(sim.step_margin_calls),
        "mcFg": RED if sim.step_margin_calls else INK,
        # Every figure on this line is the focused market's. It used to open with
        # the symbol and then quote `sim.step_orders`, which counts orders across
        # all five books, next to that market's own trade count — so the line read
        # "TECH · 300 orders · 12 trades" in a market that had seen sixty orders.
        "book": f"{focus} · {market.step_orders} orders · {market.step_trades} trades · "
                f"book {millions(_book_value(sim, focus))}",
        # The resting orders themselves, for the book view. See _ladder.
        "ladder": _ladder(sim, focus),

        # --- geometry inputs: capital per district, in € ------------------
        "capital": {
            "mom": equity.get("momentum", 0.0),
            "val": equity.get("value", 0.0),
            "noi": equity.get("noise", 0.0),
            "etf": equity.get("passive", 0.0),
            "lev": lev_equity,
            "mkr": equity.get("maker", 0.0),
            "cmp": equity.get("company", 0.0),
            "exp": lev_exposure,
            "exch": _book_value(sim, focus),
        },
        "flow": {
            key: _street_width(orders.get(group, 0), busiest)
            for key, group in _ROADS.items()
        },
        "runners": {
            **{key: _runner_count(orders.get(group, 0), busiest)
               for key, group in _ROADS.items()},
            "switch": min(4, sim.switched_last_review // 8),
        },
        # Per road, the share of this step's orders from that group that were buys,
        # 0 to 1. None for a group that sent no order, which is not the same as a
        # group that only sold. The figures' crates are coloured from this.
        "buyShare": {
            key: (round(buys.get(group, 0) / orders[group], 2)
                  if orders.get(group, 0) > 0 else None)
            for key, group in _ROADS.items()
        },
        "pips": _pips(sim, focus),

        # --- the leverage tower -----------------------------------------
        "lev": f"{lev_count} · {num(lev_ratio, 1)}×" if lev_count and lev_exposure > 0
               else f"{lev_count} · liquidated",
        "levSub": _lev_sub(sim, lev_ratio, lev_count),
        "alarm": 1 if sim.step_margin_calls else 0,

        # --- districts list ---------------------------------------------
        # Four fields per row: name, the figures, what the district is for, and a
        # member to show in the unit panel when it is clicked. The last two exist
        # because a list of sizes told the reader how big each district is and
        # never what any of them does.
        "rooms": _rooms(sim, markets, equity, counts, adaptive_total, lev_equity,
                        lev_count, focus),

        # --- review clock -------------------------------------------------
        "reviewStep": review_step,
        "reviewOf": cfg.switch_interval,

        # --- the selected unit -------------------------------------------
        **_unit(sim, agent),

        # --- city log -----------------------------------------------------
        "log": _log(sim, focus),
    }


def _rooms(sim: Simulation, markets: list[dict], equity: dict, counts: dict,
           adaptive_total: int, lev_equity: float, lev_count: int,
           focus: str) -> list[list]:
    notes = _district_notes(sim)
    # The focused market, like every other read-out on the plate. This row read
    # `sim.book`, which is the *primary* market, while the market-maker landmark two
    # lines away reported the selected one — two numbers for the same quantity,
    # differing, on the same screen.
    focused = sim.markets[focus]
    rows = [
        ["Exchanges", f"{len(markets)} markets · book {millions(sum(m['eur'] for m in markets))}"],
        ["Central Bank", f"Rate {num(sim.bank.rate * 100, 2)}% · "
                         f"inflation {num(sim.bank.inflation * 100, 2)}%"],
        ["Adaptive Quarter", f"{num_int(adaptive_total)} agents · "
                             f"{millions(equity.get('momentum', 0) + equity.get('value', 0))}"],
        ["Noise Suburb", f"{num_int(counts.get('noise', 0))} agents · "
                         f"{millions(equity.get('noise', 0))}"],
        ["ETF Depot", f"{num_int(counts.get('passive', 0))} agents · "
                      f"{millions(equity.get('passive', 0))}"],
        ["Leveraged funds", f"{num_int(lev_count)} agents · {millions(lev_equity)}"],
        ["Market Makers", f"{num_int(counts.get('maker', 0))} agents · book depth {focus} "
                          f"{num_int(sum(focused.depth()))} shares"],
        ["Issuer", f"{num_int(-min(0, _issued(sim)))} shares issued into circulation"],
    ]
    return [[name, meta, notes.get(name, ""), _representative(sim, name)]
            for name, meta in rows]


def _ticker(sim: Simulation, fresh_for: int = 15, market=None) -> dict:
    """The newest event, but only while it is still news."""
    if sim.events and sim.t - sim.events[-1].ts <= fresh_for:
        event = sim.events[-1]
        crash = event.kind in ("margin_call", "wipeout")
        return {
            "tickStep": f"STEP {num_int(event.ts)}",
            "tick": event.text,
            "tickFg": RED if crash else ORANGE,
            "tickBd": _alpha(RED, .55) if crash else _alpha(ORANGE, .4),
        }
    # The market the read-outs are about, not always the first one: the book line
    # followed the selection and the ticker did not, which read as a bug because
    # it was one.
    market = market or sim.markets[sim.primary]
    stretch = (market.price / max(market.instrument.fundamental, 1e-9) - 1.0) * 100
    return {
        "tickStep": f"STEP {num_int(sim.t)}",
        "tick": f"{market.symbol} {num(market.price)} · {num(stretch, 1)}% from fair value",
        "tickFg": ORANGE,
        "tickBd": _alpha(ORANGE, .4),
    }


def _pips(sim: Simulation, symbol: str) -> list[dict]:
    """The last fills, floating over the exchange. Green bought, red sold.

    Of the *focused* market. `sim.step_fills` concatenates every market's fills, so
    the numbers floating over the selected tower were four fifths other people's
    trades — and the tower is labelled with its symbol.
    """
    out = []
    for fill in sim.markets[symbol].step_fills[-5:]:
        buy = fill["side"] > 0
        out.append({
            "t": ("+" if buy else "−") + num_int(fill["qty"]),
            "c": GREEN if buy else RED,
        })
    return out


def _lev_sub(sim: Simulation, ratio: float, count: int) -> str:
    if count == 0 or ratio <= 0:
        return "Tower collapsed · all funds wiped out"
    if sim.step_margin_calls:
        calls = sim.step_margin_calls
        return f"{calls} margin call{'' if calls == 1 else 's'} this step"
    headroom = ratio / max(sim.cfg.max_leverage, 1e-6)
    if headroom > 0.8:
        return "one bad move away from a margin call"
    return f"{num(headroom * 100, 0)}% of the allowed leverage in use"


def _selected(sim: Simulation, selected_id: int | None):
    if selected_id is not None and selected_id in sim.by_id:
        return sim.by_id[selected_id]
    for agent in sim.agents:
        if agent.kind == "adaptive":
            return agent
    return sim.agents[0]


# What each district is for, in one sentence. The town could always show *how big*
# a district is and never *what it does*, which is the difference between a
# read-out and something a first-time reader can use. Sentences live here rather
# than in the HTML because several of them quote a parameter.
def _district_notes(sim: Simulation) -> dict[str, str]:
    cfg = sim.cfg
    return {
        "Exchanges": f"{len(sim.markets)} order books, one per sector. A price only forms "
                     "where one order meets another.",
        "Central Bank": "Sets the rate. It reaches the market through valuation, borrowing "
                        "costs and inflows. It never moves the price directly.",
        "Adaptive Quarter": f"Switches every {cfg.switch_interval} steps between trend "
                            "following and value, depending on what has worked recently.",
        "Noise Suburb": "Trades without an opinion. Provides the other side, so that "
                        "trading can happen at all.",
        "ETF Depot": f"Buys on a schedule every {cfg.passive_interval} steps, regardless "
                     "of price. Reads no news.",
        "Leveraged funds": f"Trades on credit, at most {num(cfg.max_leverage, 1)}×. If "
                           f"equity falls below {num(cfg.maintenance_margin * 100, 0)}% of "
                           "the position, it sells. No decision is involved.",
        "Market Makers": "Quotes prices on both sides at all times. The only source of "
                         "standing liquidity.",
        "Issuer": f"Issues new shares as soon as the price is more than "
                  f"{num(cfg.issue_threshold * 100, 0)}% above fair value. The only source "
                  "of new supply.",
    }


# Which agent kind stands for each district, so clicking one can show a real
# member of it in the unit panel. The two districts without agents map to None.
_DISTRICT_KIND = {
    "Exchanges": None, "Central Bank": None,
    "Adaptive Quarter": "adaptive", "Noise Suburb": "noise",
    "ETF Depot": "passive", "Leveraged funds": "leveraged",
    "Market Makers": "maker", "Issuer": "company",
}


def _representative(sim: Simulation, name: str) -> int | None:
    kind = _DISTRICT_KIND.get(name)
    if kind is None:
        return None
    for agent in sim.agents:
        if agent.kind == kind:
            return agent.aid
    return None


def _unit(sim: Simulation, agent) -> dict:
    """The panel on the right: one agent, its state and its last decision.

    The arithmetic is reported for the market the agent's last order was actually in,
    falling back to the primary. It used to divide by `sim.price` — the primary
    market — while the header showed whichever market the reader had selected, so the
    line "target = 0.84 · wealth / price" did not reconcile with the two numbers on
    either side of it. Naming the market is part of the fix: the reader can see which
    price the division used.
    """
    cfg = sim.cfg
    order = sim.last_orders.get(agent.aid)
    symbol = order["symbol"] if order and order["symbol"] in sim.markets else sim.primary
    price = sim.markets[symbol].price
    momentum = agent.strategy == "momentum"
    equity = agent.equity(price)
    leverage = agent.leverage(price)

    if momentum:
        strat, colour = "MOMENTUM", ORANGE
    elif agent.strategy == "value":
        strat, colour = "VALUE", TEAL
    else:
        strat, colour = agent.strategy.upper(), GOLD

    # The two terms the momentum rule in agents.py actually uses.
    z = sim.trend / (sim.realized_vol + 1e-6)
    signal = max(-1.0, min(1.0, z / 3.0)) * (cfg.chartist_aggression / 100.0)
    target = max(equity, 1.0) / max(price, 0.01) * (0.5 + signal + sim.world.sentiment * 0.25)

    if order:
        side = "BUYS" if order["side"] > 0 else "SELLS"
        colour_order = GREEN if order["side"] > 0 else RED
        text = f"{side} {num_int(order['qty'])} @ {num(order['price'])}"
    else:
        colour_order, text = GREY, "waiting"

    # Stepping through the population needs neighbours, and a panel that says
    # "3 of 615" tells the reader the arrows are not decoration.
    index = next((i for i, a in enumerate(sim.agents) if a.aid == agent.aid), 0)
    total = len(sim.agents)

    return {
        "unit": f"#{agent.aid} {type(agent).__name__}",
        # Names the district rather than repeating the strategy, so the card and the
        # map agree on where this agent is.
        "sub": f"{_GROUP_NAMES.get(sim.group_of(agent), sim.group_of(agent))} · "
               f"capital {eur(equity)} · "
               f"{'on the way to the exchange' if order else 'in the district'}",
        "unitGroup": _GROUP_NAMES.get(sim.group_of(agent), sim.group_of(agent)),
        "unitKind": _KIND_LABELS.get(agent.kind, agent.kind.upper()),
        "unitIdx": num_int(index + 1),
        "unitTotal": num_int(total),
        "unitOf": f"{index + 1} / {total}",
        "unitPrev": sim.agents[(index - 1) % total].aid,
        "unitNext": sim.agents[(index + 1) % total].aid,
        # The two rule parameters the panel prints. They were literals in the
        # markup — "45" and "0.96" — next to bars that did move, so the bars and
        # the numbers disagreed as soon as a slider was touched.
        "trend": num(cfg.chartist_aggression, 0),
        "mem": num(cfg.memory, 2),
        # The base weight the target position starts from, so the formula line is
        # the formula the agent actually used this step.
        "dBase": num(0.5 + signal, 2),
        "strat": strat,
        "stratFg": colour,
        "stratBg": _alpha(colour, 0.16),
        "stratBd": _alpha(colour, 0.4),
        "body": colour,
        "eq": num_int(equity),
        "eqW": pct(equity, max(a.equity(price) for a in sim.agents)),
        "trendW": pct(cfg.chartist_aggression, 150),
        "memW": pct(cfg.memory, 1.0),
        "levX": num(leverage, 1) + "×" if leverage != float("inf") else "∞",
        "levW": pct(min(leverage, cfg.max_leverage), cfg.max_leverage),
        "d1": "= " + num(z, 2),
        "d2": "= " + num(sim.world.sentiment * 0.25, 2),
        "d3": f"= {num_int(max(0, target))} shares",
        # Which market the division used, so the line can be checked against a price
        # the reader can see.
        "dSym": symbol,
        "dPx": num(price),
        "order": text,
        # "open" was a fixed word in the markup and it sat next to "waiting".
        "orderState": "open" if order else "no order",
        "orderFg": colour_order,
        "orderBg": _alpha(colour_order, 0.14),
        "orderBd": _alpha(colour_order, 0.5),
    }


def _log(sim: Simulation, symbol: str) -> list[list]:
    """Events first; when the market is quiet, the tape of the focused market.

    `sim.recent_trades` is the primary market's, so with any other market selected
    the log filled up with trades at prices that appear nowhere else on the screen.
    """
    colours = {"margin_call": RED, "wipeout": RED, "switch_wave": GOLD, "news": GREY}
    rows = [
        [num_int(event.ts), event.text, colours.get(event.kind, GREY)]
        for event in reversed(sim.events[-6:])
    ]
    for fill in reversed(sim.markets[symbol].recent_trades[-6:]):
        if len(rows) >= 6:
            break
        side = "buys" if fill["side"] > 0 else "sells"
        rows.append([num_int(fill["ts"]),
                     f"{side} {num_int(fill['qty'])} @ {num(fill['price'])}",
                     GREEN if fill["side"] > 0 else RED])
    return rows


def _alpha(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"
