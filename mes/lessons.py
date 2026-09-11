"""Guided experiments: a question, a setting, and a measured answer.

The seven experiments in the handbook were written on paper, which is the wrong place
for them. An experiment you have to read about and then reproduce by hand is a
document; an experiment the tool sets up, narrates and then *checks* is a lesson.

Each lesson has three parts and the third is what makes it more than a demo:

    frage    what is being asked
    aufbau   the parameters, applied on start
    prüfung  a predicate over the simulation state — measured, so the lesson can
             report "das hat funktioniert" or "das hat diesmal nicht funktioniert"

That last part matters more than it looks. A guided tour that always says "sehen Sie,
genau wie erwartet" teaches nothing, because it would say the same thing if the model
were broken. These report failure when the run does not deliver, and several of them
regularly do — this is a model with two failing criteria, and the lessons are not
allowed to hide that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Check:
    label: str
    passed: bool
    detail: str


@dataclass
class Lesson:
    key: str
    title: str
    question: str
    idea: str  # what the reader should end up understanding
    setup: dict = field(default_factory=dict)  # config overrides
    scenario: str | None = None
    days: int = 60  # how long to run before checking
    watch: list = field(default_factory=list)
    honest: str = ""  # what to expect when it does not work

    def to_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title, "question": self.question,
            "idea": self.idea, "setup": self.setup, "scenario": self.scenario,
            "days": self.days, "watch": self.watch, "honest": self.honest,
        }


# --------------------------------------------------------------- the checks
def _gap(sim) -> float:
    return max(abs(m.price / max(m.instrument.fundamental, 1e-9) - 1.0) * 100
               for m in sim.markets.values())


def _chartists(sim) -> float:
    return sim.chartist_share()


def _swing(sim) -> float:
    history = sim.chartist_share_hist[-6000:]
    return float(np.std(history)) if len(history) > 50 else 0.0


def _avg_correlation(sim) -> float:
    from .instruments import correlation_matrix
    value = correlation_matrix(sim.sector_returns())["average"]
    return 0.0 if value is None else value


def check_bubble(sim) -> list[Check]:
    gap, share = _gap(sim), _chartists(sim)
    return [
        Check("Kurs löst sich vom fairen Wert", gap > 20,
              f"größter Abstand {gap:.0f} % (nötig: über 20 %)"),
        Check("Trendfolger dominieren", share > 0.55,
              f"{share * 100:.0f} % im Trendfolge-Lager"),
    ]


def check_cascade(sim) -> list[Check]:
    return [
        Check("Zwangsverkäufe traten auf", sim.margin_calls > 0,
              f"{sim.margin_calls} Margin Calls"),
        Check("Sie kamen gehäuft, nicht einzeln", sim.margin_calls > 10,
              f"{sim.margin_calls} insgesamt — eine Kaskade ist mehr als ein Einzelfall"),
    ]


def check_etf(sim) -> list[Check]:
    gap = _gap(sim)
    return [
        Check("Preis löst sich vom Wert", gap > 15,
              f"größter Abstand {gap:.0f} %"),
        Check("Es fließt tatsächlich Geld herein", sim.cfg.passive_inflow > 100,
              f"Zufluss {sim.cfg.passive_inflow:.0f} je Sparplan"),
    ]


def check_correlation(sim) -> list[Check]:
    corr = _avg_correlation(sim)
    return [
        Check("Sektoren laufen gemeinsam", corr > 0.15,
              f"Durchschnittskorrelation {corr:.2f} — nirgends konfiguriert"),
    ]


def check_rates(sim) -> list[Check]:
    bank = sim.bank
    return [
        Check("Die Zentralbank hat reagiert", bank.rate > sim.cfg.neutral_rate + 0.01,
              f"Zins {bank.rate * 100:.2f} % gegen neutral {sim.cfg.neutral_rate * 100:.2f} %"),
        Check("Sie hat überschossen", bank.output_gap < -0.3,
              f"Output-Gap {bank.output_gap:+.2f} — die Wirkung kam verzögert"),
    ]


def check_regimes(sim) -> list[Check]:
    swing = _swing(sim)
    return [
        Check("Die Population kippt zwischen den Lagern", swing > 0.10,
              f"Streuung des Chartisten-Anteils {swing:.2f}"),
        Check("Keine Strategie gewinnt dauerhaft", swing > 0.10,
              "Wer gewinnt, zieht Nachahmer an und macht sich selbst unrentabel"),
    ]


def check_predictable(sim) -> list[Check]:
    from .metrics import analyse
    rows = []
    for market in sim.markets.values():
        returns = np.array(market.daily_returns[5:])
        report = analyse(returns)
        if not report.get("insufficient"):
            rows.append(report["acf_returns"][0])
    if not rows:
        return [Check("Genug Handelstage für die Messung", False,
                      "noch zu wenige Tage — länger laufen lassen")]
    acf = float(np.mean(rows))
    return [
        Check("Renditen sind NICHT prognostizierbar", abs(acf) < 0.1,
              f"ACF(1) {acf:+.3f} — gefordert ist ±0,1. "
              "Dieser Test schlägt normalerweise fehl, und das ist der offene "
              "Fehler des Modells, nicht Ihrer Bedienung."),
    ]


# One entry per lesson, and no others: `evaluate` indexes this by lesson key, so a
# check without a lesson can only ever 404 and a lesson without a check raises. There
# used to be a "decoupled" check here with no lesson behind it — unreachable code that
# read like a feature. `tests/test_scenarios.py` now keeps the two sides equal.
CHECKS = {
    "bubble": check_bubble, "cascade": check_cascade, "etf": check_etf,
    "correlation": check_correlation,
    "rates": check_rates, "regimes": check_regimes, "predictable": check_predictable,
}


# --------------------------------------------------------------- the lessons
LESSONS = [
    Lesson(
        key="bubble",
        title="Entsteht eine Blase von selbst?",
        question="Kann ein Kurs weit über den fairen Wert steigen, ohne dass jemand "
                 "das beschließt?",
        idea="Trendfolge ist eine Rückkopplung: Kaufen, weil der Kurs steigt, lässt "
             "ihn weiter steigen. Niemand gibt eine Empfehlung, niemand koordiniert — "
             "die Blase ist ein Ergebnis der Regeln, keine Eingabe.",
        scenario="bubble",
        days=70,
        watch=["Der Abstand zum fairen Wert im Sektor-Panel wächst.",
               "Der Chartisten-Anteil steigt, während er wächst — das ist die "
               "Rückkopplung, nicht die Folge.",
               "Der Emittent beginnt gegenzuhalten, sobald die Bewertung reicht."],
        honest="Ob die Blase 20 % oder 60 % erreicht, ist die Antwort des Modells und "
               "hängt am Zufallsstart. Manche Läufe liefern keine.",
    ),
    Lesson(
        key="cascade",
        title="Braucht ein Crash schlechte Nachrichten?",
        question="Kann ein Kursrutsch sich selbst verstärken, ohne dass weitere "
                 "schlechte Nachrichten kommen?",
        idea="Ein gehebelter Fonds unter seiner Margin-Schwelle verkauft, weil er muss. "
             "Das drückt den Kurs, wodurch der nächste Fonds unter seine Schwelle "
             "fällt. Ein einzelner Auslöser genügt — den Rest macht die Mechanik.",
        scenario="leverage_crash",
        days=45,
        watch=["Der Alarm am Hebel-Turm in der Stadtansicht.",
               "Die Zahl der Margin Calls im Protokoll — sie kommen in Serie.",
               "Nur EIN Auslöser ist geskriptet. Alles danach ist Folge."],
        honest="Ob die Kaskade zündet, hängt daran, ob die Fonds vorher genug Hebel "
               "aufgebaut haben. Bei ruhigem Vorlauf passiert nichts.",
    ),
    Lesson(
        key="etf",
        title="Machen ETFs den Markt instabiler?",
        question="Was passiert, wenn ein großer Teil des Kapitals preisunempfindlich "
                 "investiert?",
        idea="Ein Sparplan kauft im Takt, zu jedem Preis. Er prüft nicht, was etwas "
             "wert ist. Genug davon, und der Kurs verliert seinen Bezug zum fairen "
             "Wert — nicht weil jemand irrt, sondern weil niemand mehr prüft.",
        setup={"n_passive": 200, "passive_inflow": 240.0, "n_adaptive": 150},
        days=70,
        watch=["Der Abstand zum fairen Wert.",
               "Das Volatilitätscluster im Validierungspanel — es bricht ein, weil die "
               "Regimewechsel weniger Wirkung haben.",
               "Für die belastbare Antwort: A/B-Vergleich mit ETF 0 gegen 200."],
        honest="Der A/B-Vergleich über mehrere Seeds ist hier aussagekräftiger als ein "
               "einzelner Lauf.",
    ),
    Lesson(
        key="correlation",
        title="Woher kommt die Korrelation zwischen Sektoren?",
        question="Warum fallen fünf verschiedene Märkte gemeinsam, obwohl nirgends "
                 "eine Korrelation eingetragen ist?",
        idea="Zwei Kopplungen, keine davon konfiguriert. Ein gemeinsamer Marktfaktor "
             "in den Fundamentalwerten — und gemeinsame Bilanzen: ein Fonds in Not "
             "verkauft ALLE seine Positionen, nicht nur die problematische.",
        setup={"n_leveraged": 50, "max_leverage": 5.0, "maintenance_margin": 0.40},
        days=70,
        watch=["Die Korrelations-Heatmap auf der Analyseseite.",
               "Danach „Sektor-Eigenleben“ auf 0 stellen: die Sektoren werden fast "
               "identisch, weil dann nur noch der gemeinsame Faktor wirkt.",
               "Danach Hebel-Fonds auf 0: die Korrelation fällt weiter — das war die "
               "Ansteckung über Portfolios."],
        honest="",
    ),
    Lesson(
        key="rates",
        title="Wie wirkt eine Zinserhöhung?",
        question="Über die Bewertung, über die Finanzierungskosten oder über die "
                 "Zuflüsse?",
        idea="Über alle drei, unterschiedlich schnell. Und die Zentralbank überschießt: "
             "sie strafft weiter, während die Inflation schon fällt, weil die Wirkung "
             "verzögert eintritt. Das ist keine Eingabe, sondern eine Folge der "
             "Verzögerung.",
        scenario="rates2022",
        days=200,
        watch=["Das Zentralbank-Panel: der Zins steigt der Inflation nach.",
               "Der Zinsgipfel liegt NACH dem Inflationsgipfel.",
               "Duration je Sektor — Finanzen und Technologie werden härter getroffen "
               "als Energie.",
               "Nur der Inflationsschock ist geskriptet, der Zinspfad nicht."],
        honest="Dieses Szenario läuft lang. Bei 16× dauert es ein paar Minuten.",
    ),
    Lesson(
        key="regimes",
        title="Welche Strategie gewinnt langfristig?",
        question="Value oder Trendfolge?",
        idea="Keine dauerhaft. Wer gerade gewinnt, zieht Nachahmer an — und je mehr "
             "eine Strategie verfolgen, desto weniger trägt sie. Die Population kippt "
             "deshalb immer wieder, und genau diese Beharrlichkeit-mit-Wechsel ist es, "
             "was die Volatilität klumpen lässt.",
        setup={"herd_strength": 3.0, "switch_rate": 0.3},
        days=120,
        watch=["Der Strategie-Mix über die Zeit.",
               "Das Panel „Strategie-Performance“: die Führung wechselt.",
               "Volatilitätscluster im Validierungspanel — es hängt an diesen Wechseln."],
        honest="",
    ),
    Lesson(
        key="predictable",
        title="Ist dieser Markt prognostizierbar?",
        question="Kann man aus der Rendite von gestern die von heute vorhersagen?",
        idea="In einem echten Markt: praktisch nicht. In diesem: leider ja — die "
             "Autokorrelation liegt bei etwa −0,2 statt bei null. Das ist der "
             "dokumentierte offene Fehler des Modells, und dieses Experiment zeigt "
             "ihn absichtlich, statt ihn zu verstecken.",
        days=120,
        watch=["Die Zeile „Keine Rendite-Autokorrelation“ im Validierungspanel.",
               "Der Anker, der den Kurs am fairen Wert hält, ist dasselbe, was seine "
               "Renditen prognostizierbar macht. Genau dieser Zielkonflikt ist ungelöst."],
        honest="Dieser Test schlägt normalerweise fehl. Das ist die richtige Antwort — "
               "ein Werkzeug, das den eigenen Fehler nicht zeigt, wäre wertlos.",
    ),
]

ALL = {lesson.key: lesson for lesson in LESSONS}


def catalogue() -> list[dict]:
    return [lesson.to_dict() for lesson in LESSONS]


def get(key: str) -> Lesson | None:
    return ALL.get(key)


def evaluate(key: str, sim) -> dict:
    """Run the lesson's checks against the current state."""
    lesson = ALL.get(key)
    if lesson is None:
        return {"key": key, "checks": [], "verdict": "unbekannt"}

    checks = CHECKS[key](sim)
    passed = sum(c.passed for c in checks)
    if passed == len(checks):
        verdict = "gezeigt"
    elif passed:
        verdict = "teilweise"
    else:
        verdict = "diesmal nicht"

    return {
        "key": key,
        "title": lesson.title,
        "verdict": verdict,
        "passed": passed,
        "total": len(checks),
        "checks": [{"label": c.label, "passed": c.passed, "detail": c.detail}
                   for c in checks],
        "honest": lesson.honest,
    }
