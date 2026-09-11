"""The population as a list: every trader, what it holds and how it has done.

The town shows one agent at a time and steps through them with two arrows. That is
the right way to read *a* trader and a hopeless way to read six hundred: there was
no way to ask which fund is closest to a margin call, whether the value camp is
actually poorer than the momentum camp, or who is carrying the losses — questions
the model answers on every step and nothing ever displayed.

This module is to the roster what `mes/city.py` is to the town: the only place
simulation state is turned into the numbers the table shows, so the page never has
to interpret anything. Reading only — nothing here changes the simulation.

Sorting, filtering and paging happen here rather than in the browser because six
hundred rows with a position per instrument is a payload nobody needs in full to
answer "who is the largest leveraged fund".
"""

from __future__ import annotations

import numpy as np

from .simulation import Simulation

# What an agent *is*, which is not what it is currently doing: an adaptive trader is
# ADAPTIV and may be running the value rule this minute. Same labels as the town's
# unit card, deliberately — the two views name the same thing the same way.
KIND_LABELS = {
    "adaptive": "Adaptiv", "noise": "Rausch", "passive": "ETF",
    "leveraged": "Hebel", "maker": "Market Maker", "company": "Emittent",
}

STRATEGY_LABELS = {
    "momentum": "Momentum", "value": "Value", "noise": "Rausch",
    "passive": "Sparplan", "leveraged": "Hebel", "maker": "Quotierung",
    "company": "Emission",
}

GROUP_NAMES = {
    "momentum": "Adaptiv · Momentum", "value": "Adaptiv · Value",
    "noise": "Rausch-Vorstadt", "passive": "ETF-Lager", "leveraged": "Hebel-Fonds",
    "maker": "Market Maker", "company": "Emittent",
}

# One line saying what the group is for, so the roster explains itself the way the
# district list in the town does.
GROUP_NOTES = {
    "momentum": "Extrapoliert die letzte Bewegung und ignoriert die Bewertung.",
    "value": "Kauft unter der eigenen Schätzung des fairen Werts, verkauft darüber.",
    "noise": "Handelt ohne Meinung — die Gegenseite, damit gehandelt werden kann.",
    "passive": "Bekommt nach Plan Geld und kauft zu jedem Preis.",
    "leveraged": "Handelt auf Kredit. Fällt das Eigenkapital zu weit, wird verkauft.",
    "maker": "Stellt dauerhaft beide Seiten — die einzige stehende Liquidität.",
    "company": "Gibt Aktien aus, wenn sie teuer sind, und kauft zurück, wenn sie billig sind.",
}

# The columns the table may be sorted by, and how each is read off a row. A
# whitelist rather than `getattr`: an unknown key is a 400 with the list of valid
# ones, not a silent fall-back to some default order that looks like a broken sort.
SORTS: dict[str, callable] = {
    "aid": lambda row: row["aid"],
    "equity": lambda row: row["equity"],
    "cash": lambda row: row["cash"],
    "shares": lambda row: row["shares"],
    "exposure": lambda row: row["exposure"],
    "leverage": lambda row: row["leverage"] if row["leverage"] is not None else -1.0,
    "pnl": lambda row: row["pnl"],
    "pnlPct": lambda row: row["pnlPct"] if row["pnlPct"] is not None else -1e18,
    "perf": lambda row: row["perf"],
    "liquidations": lambda row: row["liquidations"],
    "kind": lambda row: (row["kind"], -row["equity"]),
    "strategy": lambda row: (row["strategy"], -row["equity"]),
}


def _row(sim: Simulation, agent) -> dict:
    """One trader. Every figure is marked at the prices of the current step."""
    equity = agent.equity()
    exposure = agent.exposure()
    leverage = agent.leverage()
    order = sim.last_orders.get(agent.aid)
    group = sim.group_of(agent)
    start = agent.start_equity

    return {
        "aid": agent.aid,
        "kind": agent.kind,
        "kindLabel": KIND_LABELS.get(agent.kind, agent.kind),
        "strategy": agent.strategy,
        "strategyLabel": STRATEGY_LABELS.get(agent.strategy, agent.strategy),
        "group": group,
        "groupName": GROUP_NAMES.get(group, group),
        # Set for the agents tied to one instrument — makers and issuers. None for
        # everyone else, who hold a portfolio across all of them.
        "symbol": agent.symbol,
        "cash": round(agent.cash, 2),
        "shares": agent.shares,
        "equity": round(equity, 2),
        "exposure": round(exposure, 2),
        # Infinity is not JSON. A wiped-out fund has no meaningful leverage, and
        # null says that better than a number the client has to special-case.
        "leverage": None if leverage == float("inf") else round(leverage, 2),
        "pnl": round(equity - start, 2),
        "pnlPct": None if start <= 1e-9 else round((equity / start - 1.0) * 100, 2),
        # The EMA the strategy review actually uses when this agent decides whether
        # to switch, so the table shows the number the model reads, not a proxy.
        "perf": round(agent.perf, 5),
        "liquidations": agent.liquidations,
        "positions": {sym: qty for sym, qty in sorted(agent.positions.items()) if qty},
        "order": None if order is None else {
            "step": order["ts"], "symbol": order["symbol"],
            "side": order["side"], "qty": order["qty"], "price": order["price"],
            # Only while it is this step's order. `last_orders` keeps the last one
            # for ever, and a table that says "kauft 300" for an agent that has not
            # traded in twenty thousand steps is a lie with a timestamp beside it.
            "open": order["ts"] >= sim.t - 1,
        },
    }


def _groups(sim: Simulation, rows: list[dict], total_equity: float) -> list[dict]:
    """Per district: how many, how much, and who the largest member is.

    Built over *all* rows, never over the filtered page — the rollup answers "how is
    the population divided", and a rollup that changes when you type in a search box
    is answering a different question than the one it is labelled with.
    """
    out: dict[str, dict] = {}
    for row in rows:
        group = out.setdefault(row["group"], {
            "group": row["group"], "name": row["groupName"],
            "note": GROUP_NOTES.get(row["group"], ""),
            "count": 0, "equity": 0.0, "cash": 0.0, "shares": 0,
            "best": None, "bestEquity": float("-inf"), "wins": 0,
        })
        group["count"] += 1
        group["equity"] += row["equity"]
        group["cash"] += row["cash"]
        group["shares"] += row["shares"]
        group["wins"] += 1 if row["pnl"] > 0 else 0
        if row["equity"] > group["bestEquity"]:
            group["best"], group["bestEquity"] = row["aid"], row["equity"]

    result = []
    for group in out.values():
        group.pop("bestEquity")
        group["equity"] = round(group["equity"], 2)
        group["cash"] = round(group["cash"], 2)
        group["mean"] = round(group["equity"] / max(group["count"], 1), 2)
        group["share"] = round(group["equity"] / total_equity * 100, 2) if total_equity > 0 else 0.0
        result.append(group)
    result.sort(key=lambda g: -g["equity"])
    return result


def overview(
    sim: Simulation,
    *,
    sort: str = "equity",
    order: str = "desc",
    kind: str | None = None,
    strategy: str | None = None,
    symbol: str | None = None,
    query: str | None = None,
    limit: int = 150,
    offset: int = 0,
) -> dict:
    """The roster: a summary, the districts, and one page of traders.

    `symbol` filters to agents that hold — or are tied to — that instrument, which
    is how the question "who is long technology" gets asked.

    Raises `KeyError` for an unknown sort column; the HTTP layer turns that into a
    400 naming the valid ones.
    """
    if sort not in SORTS:
        raise KeyError(sort)

    rows = [_row(sim, agent) for agent in sim.agents]
    total_equity = sum(row["equity"] for row in rows)
    groups = _groups(sim, rows, total_equity)

    selected = rows
    if kind:
        selected = [r for r in selected if r["kind"] == kind]
    if strategy:
        selected = [r for r in selected if r["strategy"] == strategy]
    if symbol:
        selected = [r for r in selected
                    if r["symbol"] == symbol or symbol in r["positions"]]
    if query:
        needle = query.strip().lower().lstrip("#")
        if needle:
            selected = [r for r in selected
                        if needle in str(r["aid"])
                        or needle in r["kindLabel"].lower()
                        or needle in r["strategyLabel"].lower()]

    selected.sort(key=SORTS[sort], reverse=(order != "asc"))

    limit = max(1, min(limit, 2000))
    offset = max(0, min(offset, max(0, len(selected) - 1)))
    page = selected[offset:offset + limit]

    equities = np.array([row["equity"] for row in rows], dtype=float)
    pnls = np.array([row["pnl"] for row in rows], dtype=float)
    wealth = sim.wealth_stats()

    return {
        "step": sim.t,
        "day": sim.t // max(1, sim.cfg.steps_per_day),
        "symbols": list(sim.markets),
        "sorts": sorted(SORTS),
        "kinds": [{"key": key, "label": label} for key, label in KIND_LABELS.items()],
        "summary": {
            "count": len(rows),
            "shown": len(page),
            "matched": len(selected),
            "equity": round(total_equity, 2),
            "cash": round(sum(row["cash"] for row in rows), 2),
            "shares": sum(row["shares"] for row in rows),
            "mean": round(float(equities.mean()), 2) if len(equities) else 0.0,
            "median": round(float(np.median(equities)), 2) if len(equities) else 0.0,
            "winners": int((pnls > 0).sum()),
            "losers": int((pnls < 0).sum()),
            # The distribution figures the metrics panel already reports, repeated
            # here so the roster does not need a second request to say whether the
            # spread it is showing is the whole story.
            "gini": round(wealth["gini"], 4),
            "top10": round(wealth["top10"], 4),
            "deciles": [round(v, 4) for v in wealth["deciles"]],
            "margin_calls": sim.margin_calls,
            "wipeouts": sim.wipeouts,
            "chartist_share": round(sim.chartist_share(), 3),
        },
        "groups": groups,
        "sort": sort,
        "order": "asc" if order == "asc" else "desc",
        "offset": offset,
        "limit": limit,
        "traders": page,
    }


def detail(sim: Simulation, aid: int) -> dict:
    """One trader in full: its row, plus the position marked per instrument.

    Read-only, deliberately. `/api/agents/{aid}` selects the agent in the town as a
    side effect of being read, which is right for the town and wrong for a table
    where the pointer passes over three hundred rows.
    """
    agent = sim.by_id[aid]
    row = _row(sim, agent)
    # The value is the *printed* price times the quantity, not the unrounded one.
    # The panel shows all three side by side, and a reader who multiplies the two
    # visible numbers has to arrive at the third — at a few thousand shares an
    # unrounded mark puts the answer a euro out for no reason anyone can see.
    row["book"] = [
        {
            "symbol": symbol,
            "qty": agent.position(symbol),
            "price": round(market.price, 2),
            "value": round(agent.position(symbol) * round(market.price, 2), 2),
            "fair": round(market.instrument.fundamental, 2),
        }
        for symbol, market in sim.markets.items()
        if agent.position(symbol)
    ]
    row["note"] = GROUP_NOTES.get(row["group"], "")
    return row
