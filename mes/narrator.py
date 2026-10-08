"""Turning simulation state into an explanation.

This module exists because of a fair complaint: watching figures walk and buildings
change height shows *state*, and state is not insight. You had to already know the
model to read the town.

Everything here answers three questions, in plain English, from measured numbers:

    What is happening?     the regime, the valuation, the risk
    Why?                   the causal chain behind it
    How do I recognise it? what to watch next, and what would falsify it

Two rules kept this from becoming decoration. Every statement is derived from a
number the simulation actually holds — nothing is canned, and a quiet market is
described as quiet rather than dressed up. And "high" or "unusual" is measured
against the run's own history via a percentile, because a volatility of 0.8 means
nothing without knowing what this market normally does.
"""

from __future__ import annotations

import numpy as np

CALM, BUILDING, STRETCHED, FALLING, CASCADE = (
    "calm", "building", "stretched", "falling", "cascade")


def _percentile(series, value: float) -> float:
    """Where `value` sits in its own history, 0 to 1."""
    data = np.asarray([v for v in series if np.isfinite(v)], dtype=float)
    if len(data) < 30:
        return 0.5
    return float((data < value).mean())


def _num(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def _pct(value: float, digits: int = 0) -> str:
    """A size in percent, without a sign: the sentence says above or below."""
    return f"{_num(abs(value), digits)}%"


# ------------------------------------------------------------------ readings
def regime(sim) -> dict:
    """Which camp the adaptive traders are in, and what that implies."""
    share = sim.chartist_share()
    history = sim.chartist_share_hist[-4000:]
    swing = float(np.std(history)) if len(history) > 30 else 0.0

    if share >= 0.65:
        name, meaning = "Trend regime", (
            "The majority buys because the price is rising, not because it is cheap. "
            "That reinforces itself and carries the price away from fair value.")
    elif share <= 0.35:
        name, meaning = "Value regime", (
            "The majority trades on fair value. The price moves more calmly and is "
            "pulled back when it runs too far.")
    else:
        name, meaning = "Mixed regime", (
            "Both camps are about the same size. Neither side dominates the price, "
            "and it is exactly this balance that tips over sooner or later.")

    return {
        "name": name,
        "share": round(share, 3),
        "meaning": meaning,
        "swing": round(swing, 3),
        "switched": sim.switched_last_review,
        "note": ("The population tips between the camps regularly. That is the "
                 "source of the volatility clusters."
                 if swing > 0.15 else
                 "The population is currently stuck. Without regime switches, "
                 "volatility stays even."),
    }


def valuation(sim) -> dict:
    """How far each market sits from fair value, and whether that is remarkable."""
    rows = []
    for symbol, market in sim.markets.items():
        gap = (market.price / max(market.instrument.fundamental, 1e-9) - 1.0) * 100
        rows.append((symbol, gap))
    rows.sort(key=lambda r: -abs(r[1]))
    worst_symbol, worst_gap = rows[0]
    average = float(np.mean([abs(g) for _, g in rows]))

    if abs(worst_gap) < 10:
        verdict = "Prices are close to their fair values."
    elif worst_gap > 0:
        verdict = (f"{worst_symbol} is {_pct(worst_gap)} above fair value. "
                   "Nobody decided that. It is the result of more buying pressure "
                   "than supply.")
    else:
        verdict = (f"{worst_symbol} is {_pct(worst_gap)} below fair value. "
                   "That makes it interesting to value investors, which builds "
                   "counter-pressure.")

    return {
        "worst": worst_symbol,
        "worst_gap": round(worst_gap, 1),
        "average_gap": round(average, 1),
        "verdict": verdict,
        "rows": [{"sym": s, "gap": round(g, 1)} for s, g in rows],
    }


# The smoothing in `Market.end_step`: realized_vol = 0.97 * prev + 0.03 * |ret|.
# Its effective window is 1/0.03 steps, which is what the history has to be
# smoothed over for the comparison below to compare like with like.
_VOL_ALPHA = 0.03
# How much history the ranking looks at. Unbounded, this walked the whole return
# series on every poll of /api/explain — a list that grows by 240 entries a day.
_VOL_HISTORY = 20_000


def turbulence(sim) -> dict:
    """Volatility, measured against this run's own history rather than a constant.

    Both sides of the comparison are smoothed the same way, and that took a fix.
    `realized_vol` is an EMA of |return|; ranking it against the distribution of
    *raw* |return| compares an average with the individual draws it averages. Raw
    step returns are mostly near zero with a long right tail, so the EMA sits above
    most of them almost always: the rank rarely fell below 0.6 and the "low"
    verdict — the one that says leverage is building because risk looks cheap —
    was unreachable in any market state.
    """
    market = sim.market
    window = [abs(r) for r in market.returns[-2000:]]
    now = market.realized_vol

    history = np.abs(np.asarray(market.returns[-_VOL_HISTORY:-1], dtype=float))
    span = max(5, int(round(1.0 / _VOL_ALPHA)))
    if len(history) > span * 3:
        history = np.convolve(history, np.ones(span) / span, mode="valid")
    rank = _percentile(history, now)

    if rank > 0.85:
        label = "high"
        meaning = ("Much more turbulent than this market usually is. Phases like this "
                   "bring margin calls, because a price drop pushes the funds below "
                   "their threshold.")
    elif rank < 0.25:
        label = "low"
        meaning = ("Calmer than usual. Leverage builds up in phases like this, because "
                   "risk looks cheap. This is the precursor to the cascade.")
    else:
        label = "normal"
        meaning = "Within this market's usual range."

    return {
        "label": label,
        "rank": round(rank, 2),
        "step_vol": round(now, 6),
        "average_step": round(float(np.mean(window)), 6) if window else 0.0,
        "meaning": meaning,
    }


def risk(sim) -> dict:
    """Leverage, liquidity and forced selling — the cascade's preconditions."""
    funds = [a for a in sim.agents if a.kind == "leveraged"]
    levs = [a.leverage() for a in funds]
    levs = [l for l in levs if np.isfinite(l)]
    median = float(np.median(levs)) if levs else 0.0
    threshold = sim.cfg.maintenance_margin
    # A fund at leverage L breaches after a fall of (1/L - m)/(1 - m).
    headroom = ((1 / median - threshold) / (1 - threshold) * 100
                if median > 0 and threshold < 1 else float("nan"))

    depth = sum(sum(m.depth()) for m in sim.markets.values())
    volume = sum(m.step_volume for m in sim.markets.values())

    if sim.step_margin_calls:
        state = ("Forced sales are under way. Each one pushes the price further down "
                 "and can take the next fund below its threshold. That is the "
                 "cascade.")
    elif np.isfinite(headroom) and headroom < 8:
        state = (f"The funds are {_num(headroom)}% away from a margin call. "
                 "An ordinary price decline is now enough.")
    elif median < 0.6:
        state = ("The funds are barely leveraged. They are holding back because "
                 "they consider prices too expensive. Without leverage there is no "
                 "cascade.")
    else:
        state = (f"The funds are at {_num(median, 2)}× leverage and have "
                 f"{_num(headroom)}% of room before a margin call.")

    return {
        "leverage": round(median, 2),
        "headroom_pct": None if not np.isfinite(headroom) else round(headroom, 1),
        "calls_total": sim.margin_calls,
        "calls_now": sim.step_margin_calls,
        "wipeouts": sim.wipeouts,
        "depth": depth,
        "volume": volume,
        "state": state,
    }


# ------------------------------------------------------------------ the story
def phase(sim, val: dict, turb: dict, rsk: dict, reg: dict) -> str:
    if rsk["calls_now"]:
        return CASCADE
    recent = sim.market.returns[-sim.cfg.steps_per_day:]
    drift = float(np.sum(recent)) if recent else 0.0
    if drift < -0.02 and turb["rank"] > 0.6:
        return FALLING
    if abs(val["worst_gap"]) > 25 and reg["share"] > 0.55:
        return STRETCHED
    if reg["share"] > 0.55 and drift > 0.01:
        return BUILDING
    return CALM


HEADLINES = {
    CALM: "Calm market",
    BUILDING: "An upward move is building",
    STRETCHED: "The market is stretched",
    FALLING: "The market is giving way",
    CASCADE: "Forced sales under way",
}

WATCH = {
    CALM: ["Whether the chartist share starts to tip. That comes before the move.",
           "Whether the funds' leverage rises while things are calm."],
    BUILDING: ["Whether the gap to fair value keeps growing.",
               "Whether more traders switch to the Trend Camp. That reinforces itself."],
    STRETCHED: ["At this valuation the Issuer issues new shares. That is the "
                "counterforce. Watch whether the gap stops growing.",
                "Whether the Value Camp grows again. The reversal starts there."],
    FALLING: ["Whether the funds reach their margin threshold. From there on they "
              "sell because they have to.",
              "Whether book depth collapses. Without liquidity, prices keep falling."],
    CASCADE: ["How many funds follow. Each sale lowers the price for the next one.",
              "Whether the correlation between sectors jumps. A fund in distress "
              "sells all of its positions, not only the problematic one."],
}


def explain(sim) -> dict:
    """The whole reading: what is happening, why, and what to watch."""
    reg = regime(sim)
    val = valuation(sim)
    turb = turbulence(sim)
    rsk = risk(sim)
    current = phase(sim, val, turb, rsk, reg)

    because = [reg["meaning"], val["verdict"], turb["meaning"], rsk["state"]]

    return {
        "phase": current,
        "headline": HEADLINES[current],
        "because": because,
        "watch": WATCH[current],
        "regime": reg,
        "valuation": val,
        "turbulence": turb,
        "risk": rsk,
        "events": recent_events(sim),
        "reminder": ("None of this is programmed in. There is no formula for the "
                     "price. Every move is one order meeting another."),
    }


EVENT_WHY = {
    "margin_call": ("A leveraged fund fell below its margin threshold and had to "
                    "sell. It did not decide to."),
    "wipeout": ("A fund has lost its equity. Its position is liquidated in full."),
    "switch_wave": ("Many traders switched strategy at the same time. Waves like this "
                    "precede bursts of volatility."),
    "news": ("A headline moved fair value, not the price. Whether the price follows "
             "is up to the agents."),
    "scenario": "A scenario has set the conditions.",
}


def recent_events(sim, limit: int = 6) -> list[dict]:
    """The event log, each line with the mechanism behind it."""
    out = []
    for event in reversed(sim.events[-limit:]):
        out.append({
            "step": event.ts,
            "text": event.text,
            "kind": event.kind,
            "why": EVENT_WHY.get(event.kind, ""),
            "severity": event.severity,
        })
    return out
