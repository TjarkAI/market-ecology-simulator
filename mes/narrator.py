"""Turning simulation state into an explanation.

This module exists because of a fair complaint: watching figures walk and buildings
change height shows *state*, and state is not insight. You had to already know the
model to read the town.

Everything here answers three questions, in plain German, from measured numbers:

    Was passiert gerade?   the regime, the valuation, the risk
    Warum?                 the causal chain behind it
    Woran erkenne ich es?  what to watch next, and what would falsify it

Two rules kept this from becoming decoration. Every statement is derived from a
number the simulation actually holds — nothing is canned, and a quiet market is
described as quiet rather than dressed up. And "high" or "unusual" is measured
against the run's own history via a percentile, because a volatility of 0.8 means
nothing without knowing what this market normally does.
"""

from __future__ import annotations

import numpy as np

CALM, BUILDING, STRETCHED, FALLING, CASCADE = (
    "ruhig", "aufbauend", "überdehnt", "fallend", "kaskade")


def _percentile(series, value: float) -> float:
    """Where `value` sits in its own history, 0 to 1."""
    data = np.asarray([v for v in series if np.isfinite(v)], dtype=float)
    if len(data) < 30:
        return 0.5
    return float((data < value).mean())


def _de(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def _pct(value: float, digits: int = 0) -> str:
    return f"{'+' if value >= 0 else ''}{_de(value, digits)} %"


# ------------------------------------------------------------------ readings
def regime(sim) -> dict:
    """Which camp the adaptive traders are in, and what that implies."""
    share = sim.chartist_share()
    history = sim.chartist_share_hist[-4000:]
    swing = float(np.std(history)) if len(history) > 30 else 0.0

    if share >= 0.65:
        name, meaning = "Trendfolge-Regime", (
            "Die Mehrheit kauft, weil der Kurs steigt, nicht weil er billig ist. "
            "Das verstärkt sich selbst — und trägt den Kurs vom fairen Wert weg.")
    elif share <= 0.35:
        name, meaning = "Value-Regime", (
            "Die Mehrheit richtet sich am fairen Wert aus. Der Kurs bewegt sich "
            "ruhiger und wird zurückgeholt, wenn er zu weit läuft.")
    else:
        name, meaning = "gemischtes Regime", (
            "Beide Lager sind ähnlich groß. Keine Seite dominiert den Kurs, "
            "und genau aus diesem Gleichgewicht kippt es früher oder später.")

    return {
        "name": name,
        "share": round(share, 3),
        "meaning": meaning,
        "swing": round(swing, 3),
        "switched": sim.switched_last_review,
        "note": ("Die Population kippt regelmäßig zwischen den Lagern — das ist die "
                 "Quelle der Volatilitätscluster."
                 if swing > 0.15 else
                 "Die Population sitzt derzeit fest. Ohne Regimewechsel bleibt die "
                 "Volatilität gleichmäßig."),
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
        verdict = "Die Kurse liegen nahe an ihren fairen Werten."
    elif worst_gap > 0:
        verdict = (f"{worst_symbol} steht {_pct(worst_gap)} über dem fairen Wert. "
                   "Niemand hat das beschlossen — es ist das Ergebnis von mehr "
                   "Kaufdruck als Angebot.")
    else:
        verdict = (f"{worst_symbol} steht {_pct(worst_gap)} unter dem fairen Wert. "
                   "Für Value-Investoren wird der Titel damit interessant, was "
                   "Gegendruck aufbaut.")

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
    most of them almost always: the rank rarely fell below 0.6 and the "niedrig"
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
        label = "hoch"
        meaning = ("Deutlich unruhiger als dieser Markt sonst ist. In solchen Phasen "
                   "kommen Margin Calls, weil ein Kursrutsch die Fonds unter ihre "
                   "Schwelle drückt.")
    elif rank < 0.25:
        label = "niedrig"
        meaning = ("Ruhiger als üblich. Hebel baut sich in solchen Phasen auf, weil "
                   "Risiko billig aussieht — das ist die Vorstufe zur Kaskade.")
    else:
        label = "normal"
        meaning = "Im gewohnten Bereich dieses Marktes."

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
        state = ("Es laufen gerade Zwangsverkäufe. Jeder davon drückt den Kurs "
                 "weiter und kann den nächsten Fonds unter seine Schwelle bringen — "
                 "das ist die Kaskade.")
    elif np.isfinite(headroom) and headroom < 8:
        state = (f"Die Fonds sind {_de(headroom)} % von einem Margin Call entfernt. "
                 "Ein normaler Kursrückgang genügt jetzt.")
    elif median < 0.6:
        state = ("Die Fonds sind kaum gehebelt. Sie halten sich zurück, weil sie "
                 "die Kurse für zu teuer halten — ohne Hebel keine Kaskade.")
    else:
        state = (f"Die Fonds stehen bei {_de(median, 2)}× Hebel und haben "
                 f"{_de(headroom)} % Luft bis zum Margin Call.")

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
    CALM: "Ruhiger Markt",
    BUILDING: "Eine Aufwärtsbewegung baut sich auf",
    STRETCHED: "Der Markt ist überdehnt",
    FALLING: "Der Markt gibt nach",
    CASCADE: "Zwangsverkäufe laufen",
}

WATCH = {
    CALM: ["Ob der Chartisten-Anteil zu kippen beginnt — das kommt vor der Bewegung.",
           "Ob der Hebel der Fonds steigt, während es ruhig ist."],
    BUILDING: ["Ob der Abstand zum fairen Wert weiter wächst.",
               "Ob mehr Trader ins Trendfolge-Lager wechseln — das verstärkt sich selbst."],
    STRETCHED: ["Der Emittent gibt bei dieser Bewertung neue Aktien aus. Das ist die "
                "Gegenkraft — beobachten Sie, ob der Abstand aufhört zu wachsen.",
                "Ob das Value-Lager wieder wächst. Der Rückschlag beginnt dort."],
    FALLING: ["Ob die Fonds ihre Margin-Schwelle erreichen. Ab dort verkaufen sie, "
              "weil sie müssen.",
              "Ob die Buchtiefe einbricht — ohne Liquidität fallen Kurse weiter."],
    CASCADE: ["Wie viele Fonds nachziehen. Jeder Verkauf senkt den Kurs für den nächsten.",
              "Ob die Korrelation zwischen den Sektoren springt — ein Fonds in Not "
              "verkauft alle seine Positionen, nicht nur die problematische."],
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
        "reminder": ("Nichts davon ist einprogrammiert. Es gibt keine Formel für den "
                     "Kurs — jede Bewegung ist eine Order, die auf eine andere trifft."),
    }


EVENT_WHY = {
    "margin_call": ("Ein gehebelter Fonds ist unter seine Margin-Schwelle gefallen und "
                    "musste verkaufen. Er hat es nicht entschieden."),
    "wipeout": ("Ein Fonds hat sein Eigenkapital verloren. Seine Position wird "
                "vollständig aufgelöst."),
    "switch_wave": ("Viele Trader haben gleichzeitig die Strategie gewechselt. Solche "
                    "Wellen gehen Volatilitätsschüben voraus."),
    "news": ("Eine Nachricht hat den fairen Wert verschoben — nicht den Kurs. Ob der "
             "Kurs folgt, entscheiden die Agenten."),
    "scenario": "Ein Szenario hat die Rahmenbedingungen gesetzt.",
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
