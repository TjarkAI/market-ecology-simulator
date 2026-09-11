"""Scenarios: parameter presets plus a script of events.

A scenario never dictates what the price does. It sets the conditions — how
strongly agents chase trends, how much leverage is allowed, what the news says —
and then the model answers. Whether "Finanzkrise 2008" produces a 12 % or a 45 %
drawdown is a result, and a different seed gives a different number.

That distinction matters most for the historical episodes. They are not attempts
to reproduce a price path; fitting five parameters until a chart matches history
would prove nothing. What is being asked is narrower and answerable: does the
*mechanism* thought to drive that episode produce that kind of behaviour in a
model that was never built for it?
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Scenario:
    key: str
    name: str
    description: str
    question: str  # what this scenario is meant to show
    overrides: dict = field(default_factory=dict)  # applied on load, needs a reset
    # (day offset from load, action). Actions: news / params / note
    timeline: list[tuple[int, dict]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "question": self.question,
            "overrides": self.overrides,
            "events": len(self.timeline),
        }


# --------------------------------------------------------------- basic set
BASIC = [
    Scenario(
        key="calm",
        name="Ruhiger Markt",
        description="Wenig Trendfolge, viel Liquidität, kaum Hebel. Der Kurs "
                    "folgt dem Fundamentalwert ohne große Ausschläge.",
        question="Wie sieht der Markt aus, wenn keine Rückkopplung wirkt?",
        overrides={"chartist_aggression": 30.0, "herd_strength": 0.5,
                   "max_leverage": 1.5, "n_makers": 20, "news_intensity": 0.1},
    ),
    Scenario(
        key="bubble",
        name="Blasenbildung",
        description="Starke Trendfolge und hoher Herdentrieb. Niemand gibt eine "
                    "Kaufempfehlung — die Blase entsteht aus der Rückkopplung.",
        question="Kann aus reiner Trendfolge eine Preisblase entstehen?",
        overrides={"chartist_aggression": 140.0, "herd_strength": 4.0,
                   "switch_rate": 0.35, "fundamental_aggression": 0.15,
                   "issue_threshold": 0.5},
    ),
    Scenario(
        key="leverage_crash",
        name="Hebel-Crash",
        description="Hoher Hebel und knappe Margin-Schwelle. Ein normaler "
                    "Kursrückgang genügt, um Zwangsverkäufe auszulösen, die den "
                    "nächsten Rückgang erzeugen.",
        question="Wie viel eines Crashs stammt aus dem Auslöser und wie viel aus "
                 "der Zwangsliquidation?",
        # Three things have to line up for a cascade, and getting them wrong is
        # instructive. The trend followers are turned *down*, not up: with them
        # loud the price runs far above fair value, the funds read that as a
        # reason to be defensive, and they never borrow enough to be called. The
        # value anchor is turned up for the same reason. And the maintenance
        # margin is set against the leverage the funds actually reach — about 2×,
        # not the 5× they are allowed — because a threshold below that is never
        # touched. With `maintenance_margin` at the default 0.25 this scenario
        # produces no margin calls at all, which is exactly the trap.
        overrides={"max_leverage": 5.0, "maintenance_margin": 0.42,
                   "n_leveraged": 60, "chartist_aggression": 60.0,
                   "value_price_pull": 0.06, "fundamental_aggression": 0.30,
                   "activity_elasticity": 0.0},
        timeline=[
            (8, {"note": "Hebel ist aufgebaut. Noch ist alles ruhig."}),
            # A trigger, because the point of the scenario is the cascade and not
            # the wait for one. How far the price falls afterwards is still the
            # model's answer: the first forced sale pushes the price down, which
            # puts the next fund below its margin.
            (12, {"news": ["Großinvestor steigt aus", -0.12]}),
        ],
    ),
    Scenario(
        key="etf_dominance",
        name="ETF-Dominanz",
        description="Der größte Teil des Kapitals fließt preisunempfindlich in "
                    "den Markt. Niemand prüft mehr, was etwas wert ist.",
        question="Machen passive Zuflüsse den Markt stabiler oder instabiler?",
        overrides={"n_passive": 200, "passive_inflow": 220.0,
                   "n_adaptive": 150, "issue_threshold": 0.3},
    ),
    Scenario(
        key="news_shock",
        name="Nachrichtenschock",
        description="Ein großer negativer Schock auf den Fundamentalwert. Jede "
                    "Gruppe liest ihn anders — der ETF liest ihn gar nicht.",
        question="Wie verarbeitet ein heterogener Markt dieselbe Nachricht?",
        overrides={"news_intensity": 0.4},
        timeline=[
            (5, {"news": ["Geopolitische Spannungen eskalieren", -0.25]}),
            (6, {"note": "Der Schock traf nur den fairen Wert. Was der Kurs macht, "
                         "entscheiden die Agenten."}),
        ],
    ),
]


# ----------------------------------------------------------- history set
# Mechanisms, not price paths. Each entry names the mechanism it is testing.
HISTORY = [
    Scenario(
        key="dotcom",
        name="Dotcom-Blase 1998–2000",
        description="Eine Phase hoher Fundamentalerwartungen trifft auf starke "
                    "Trendfolge. Nach zwei Jahren dreht die Erwartung — der "
                    "Herdentrieb bleibt.",
        question="Genügt eine Erwartungsumkehr bei unverändertem Herdenverhalten, "
                 "um einen mehrjährigen Anstieg in einen Absturz zu drehen?",
        overrides={"fundamental_drift": 0.40 / (252 * 240), "chartist_aggression": 135.0,
                   "herd_strength": 3.5, "fundamental_aggression": 0.15,
                   "issue_threshold": 0.45, "n_leveraged": 35},
        timeline=[
            (10, {"note": "Wachstumsphase: die Erwartungen tragen den Kurs."}),
            (500, {"params": {"fundamental_drift": -0.25 / (252 * 240)}}),
            (500, {"news": ["Analysten senken Wachstumserwartungen deutlich", -0.06]}),
            (502, {"note": "Die Erwartung ist gedreht. Der Herdentrieb ist unverändert."}),
        ],
    ),
    Scenario(
        key="gfc2008",
        name="Finanzkrise 2008",
        description="Hoher Hebel im System, dann ein Schock. Die Zwangsverkäufe "
                    "der Fonds erzeugen den nächsten Margin Call.",
        question="Wie viel eines Crashs stammt aus der Nachricht und wie viel aus "
                 "der Zwangsliquidation?",
        overrides={"max_leverage": 7.0, "maintenance_margin": 0.32,
                   "n_leveraged": 70, "chartist_aggression": 110.0,
                   "issue_threshold": 0.35},
        timeline=[
            (200, {"note": "Hebel ist aufgebaut. Noch ist alles ruhig."}),
            (260, {"news": ["Großinvestor steigt aus", -0.10]}),
            (263, {"news": ["Regulierer eröffnet Verfahren", -0.08]}),
            (266, {"note": "Ab hier verkaufen die Fonds, weil sie müssen, nicht "
                           "weil sie wollen."}),
        ],
    ),
    Scenario(
        key="covid",
        name="COVID-Crash 2020",
        description="Ein sehr schneller, sehr großer Schock, gefolgt von "
                    "massiver Liquiditätszufuhr.",
        question="Kann eine Liquiditätsflut einen fundamentalen Schock "
                 "überkompensieren?",
        overrides={"chartist_aggression": 115.0, "n_leveraged": 45,
                   "maintenance_margin": 0.30},
        timeline=[
            (120, {"news": ["Weltweite Produktionsstopps angekündigt", -0.30]}),
            (122, {"news": ["Nachfrageeinbruch in allen Branchen", -0.12]}),
            (128, {"news": ["Zentralbank kündigt unbegrenzte Ankäufe an", 0.10]}),
            (130, {"params": {"passive_inflow": 260.0}}),
            (132, {"note": "Der faire Wert ist weiter unten als vor dem Schock. "
                           "Der Kurs muss dem nicht folgen."}),
        ],
    ),
    Scenario(
        key="memestock",
        name="Meme-Aktie 2021",
        description="Sehr viele kleine, unkoordinierte Händler, extremer "
                    "Herdentrieb, dünne Liquidität und wenig Angebot.",
        question="Wie weit kann sich ein Kurs vom Wert lösen, wenn Liquidität "
                 "und Angebot knapp sind?",
        overrides={"n_noise": 700, "n_adaptive": 400, "herd_strength": 5.0,
                   "switch_rate": 0.5, "chartist_aggression": 150.0,
                   "n_makers": 4, "mm_quote_size": 60,
                   "issue_threshold": 0.9, "fundamental_aggression": 0.1},
        timeline=[
            (30, {"note": "Enge Liquidität, kaum Angebot, maximaler Herdentrieb."}),
        ],
    ),
    Scenario(
        key="rates2022",
        name="Zinswende 2022",
        description="Die Zentralbank hebt die Zinsen, weil die Inflation läuft. "
                    "Bewertungen fallen, Hebelkosten steigen, Zuflüsse versiegen — "
                    "drei Kanäle, unterschiedlich schnell.",
        question="Wirkt eine Zinserhöhung über die Bewertung, über die "
                 "Finanzierungskosten oder über die Zuflüsse?",
        # Inflation is pushed up and the bank is left to react on its own. The rate
        # path is not scripted: it comes out of the Taylor rule meeting an economy
        # that reacts with a lag, which is what produces the overshoot.
        overrides={"chartist_aggression": 105.0, "n_leveraged": 50,
                   "max_leverage": 4.0, "maintenance_margin": 0.40,
                   "macro_shock": 0.05, "rate_adjust_days": 15.0},
        timeline=[
            (5, {"note": "Inflation zieht an. Die Zentralbank hat noch nicht reagiert."}),
            (6, {"inflation": 0.075}),
            (40, {"note": "Der Zins steigt der Inflation nach — mit Verzögerung."}),
            (120, {"note": "Bewertungen sind gefallen, Hebelkosten gestiegen, "
                           "Zuflüsse versiegt. Was davon den Kurs bewegt hat, "
                           "zeigt das Zentralbank-Panel."}),
        ],
    ),
]

ALL = {s.key: s for s in BASIC + HISTORY}


def catalogue() -> list[dict]:
    """What the UI shows in the scenario picker."""
    return [
        {"group": "Grundszenarien", "items": [s.to_dict() for s in BASIC]},
        {"group": "Historische Episoden", "items": [s.to_dict() for s in HISTORY]},
    ]


def get(key: str) -> Scenario | None:
    return ALL.get(key)
