"""Guided experiments: a question, a setting, and a measured answer.

The seven experiments in the handbook were written on paper, which is the wrong place
for them. An experiment you have to read about and then reproduce by hand is a
document; an experiment the tool sets up, narrates and then *checks* is a lesson.

Each lesson has three parts and the third is what makes it more than a demo:

    question  what is being asked
    setup     the parameters, applied on start
    check     a predicate over the simulation state — measured, so the lesson can
              report "that worked" or "that did not work this time"

That last part matters more than it looks. A guided tour that always says "there you
go, exactly as expected" teaches nothing, because it would say the same thing if the model
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
        Check("Price detaches from fair value", gap > 20,
              f"largest gap {gap:.0f}% (needed: above 20%)"),
        Check("Trend followers dominate", share > 0.55,
              f"{share * 100:.0f}% in the Trend Camp"),
    ]


def check_cascade(sim) -> list[Check]:
    return [
        Check("Forced sales occurred", sim.margin_calls > 0,
              f"{sim.margin_calls:,} margin calls"),
        Check("They came in clusters, not one at a time", sim.margin_calls > 10,
              f"{sim.margin_calls:,} in total. A cascade is more than a single case"),
    ]


def check_etf(sim) -> list[Check]:
    gap = _gap(sim)
    return [
        Check("Price detaches from value", gap > 15,
              f"largest gap {gap:.0f}%"),
        Check("Money is actually flowing in", sim.cfg.passive_inflow > 100,
              f"inflow €{sim.cfg.passive_inflow:,.0f} per savings plan"),
    ]


def check_correlation(sim) -> list[Check]:
    corr = _avg_correlation(sim)
    return [
        Check("Sectors move together", corr > 0.15,
              f"average correlation {corr:.2f}, configured nowhere"),
    ]


def check_rates(sim) -> list[Check]:
    bank = sim.bank
    return [
        Check("The Central Bank has reacted", bank.rate > sim.cfg.neutral_rate + 0.01,
              f"rate {bank.rate * 100:.2f}% against neutral {sim.cfg.neutral_rate * 100:.2f}%"),
        Check("It has overshot", bank.output_gap < -0.3,
              f"output gap {bank.output_gap:+.2f}. The effect arrived with a lag"),
    ]


def check_regimes(sim) -> list[Check]:
    swing = _swing(sim)
    return [
        Check("The population tips between the camps", swing > 0.10,
              f"spread of the chartist share {swing:.2f}"),
        Check("No strategy wins for good", swing > 0.10,
              "Whoever wins attracts imitators and makes itself unprofitable"),
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
        return [Check("Enough trading days for the measurement", False,
                      "too few days so far. Let it run longer")]
    acf = float(np.mean(rows))
    return [
        Check("Returns are NOT predictable", abs(acf) < 0.1,
              f"ACF(1) {acf:+.3f}, required is within ±0.1. "
              "This test usually fails, and that is the model's open flaw, "
              "not a mistake in how you used it."),
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
        title="Does a bubble form on its own?",
        question="Can a price rise far above fair value without anyone deciding "
                 "that it should?",
        idea="Trend following is a feedback loop: buying because the price is rising "
             "makes it rise further. Nobody makes a recommendation, nobody "
             "coordinates. The bubble is a result of the rules, not an input.",
        scenario="bubble",
        days=70,
        watch=["The gap to fair value in the sector panel grows.",
               "The chartist share rises while the gap grows. That is the feedback "
               "loop, not its consequence.",
               "The Issuer starts to push back once the valuation is high enough."],
        honest="Whether the bubble reaches 20% or 60% is the model's answer and "
               "depends on the random start. Some runs produce none.",
    ),
    Lesson(
        key="cascade",
        title="Does a crash need bad news?",
        question="Can a price slide reinforce itself without any further bad news "
                 "arriving?",
        idea="A leveraged fund below its margin threshold sells because it has to. "
             "That pushes the price down, which takes the next fund below its "
             "threshold. A single trigger is enough. The mechanism does the rest.",
        scenario="leverage_crash",
        days=45,
        watch=["The alarm on the Leverage Tower in the town view.",
               "The number of margin calls in the log. They come in series.",
               "Only ONE trigger is scripted. Everything after it is a consequence."],
        honest="Whether the cascade ignites depends on whether the funds have built up "
               "enough leverage beforehand. After a calm run-up, nothing happens.",
    ),
    Lesson(
        key="etf",
        title="Do ETFs make the market less stable?",
        question="What happens when a large share of the capital is invested without "
                 "regard to price?",
        idea="A savings plan buys on a fixed beat, at any price. It does not check "
             "what something is worth. With enough of them, the price loses its "
             "connection to fair value. Not because anyone is wrong, but because "
             "nobody checks any more.",
        setup={"n_passive": 200, "passive_inflow": 240.0, "n_adaptive": 150},
        days=70,
        watch=["The gap to fair value.",
               "Volatility clustering in the validation panel. It collapses because "
               "the regime switches have less effect.",
               "For a robust answer: an A/B comparison with ETF 0 against 200."],
        honest="The A/B comparison across several seeds says more here than a "
               "single run.",
    ),
    Lesson(
        key="correlation",
        title="Where does the correlation between sectors come from?",
        question="Why do five different markets fall together when no correlation "
                 "is entered anywhere?",
        idea="Two couplings, neither of them configured. A common market factor in "
             "the fundamental values, and shared balance sheets: a fund in distress "
             "sells ALL of its positions, not only the problematic one.",
        setup={"n_leveraged": 50, "max_leverage": 5.0, "maintenance_margin": 0.40},
        days=70,
        watch=["The correlation heatmap on the analysis page.",
               "Then set \"Sector idiosyncrasy\" to 0: the sectors become almost "
               "identical, because only the common factor is left.",
               "Then set leveraged funds to 0: the correlation falls further. That "
               "was the contagion through portfolios."],
        honest="",
    ),
    Lesson(
        key="rates",
        title="How does a rate hike work?",
        question="Through valuation, through financing costs or through inflows?",
        idea="Through all three, at different speeds. And the Central Bank overshoots: "
             "it keeps tightening while inflation is already falling, because the "
             "effect arrives with a lag. That is not an input but a consequence of "
             "the lag.",
        scenario="rates2022",
        days=200,
        watch=["The Central Bank panel: the rate follows inflation up.",
               "The rate peak comes AFTER the inflation peak.",
               "Duration per sector. Financials and Technology are hit harder than "
               "Energy.",
               "Only the inflation shock is scripted, the rate path is not."],
        honest="This scenario runs long. At 16× it takes a few minutes.",
    ),
    Lesson(
        key="regimes",
        title="Which strategy wins in the long run?",
        question="Value or trend following?",
        idea="Neither, for good. Whoever is winning attracts imitators, and the more "
             "agents follow a strategy, the less it pays. So the population tips "
             "over again and again, and it is exactly this persistence-with-switching "
             "that makes volatility cluster.",
        setup={"herd_strength": 3.0, "switch_rate": 0.3},
        days=120,
        watch=["The strategy mix over time.",
               "The \"Strategy performance\" panel: the lead changes hands.",
               "Volatility clustering in the validation panel. It depends on these "
               "switches."],
        honest="",
    ),
    Lesson(
        key="predictable",
        title="Is this market predictable?",
        question="Can yesterday's return predict today's?",
        idea="In a real market: practically not. In this one: unfortunately yes. "
             "The autocorrelation is around −0.2 instead of zero. That is the "
             "model's documented open flaw, and this experiment shows it on purpose "
             "instead of hiding it.",
        days=120,
        watch=["The line \"No Return Autocorrelation\" in the validation panel.",
               "The anchor that holds the price at fair value is the same thing that "
               "makes its returns predictable. Exactly this trade-off is unsolved."],
        honest="This test usually fails. That is the right answer. A tool that does "
               "not show its own flaw would be worthless.",
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
        return {"key": key, "checks": [], "verdict": "unknown"}

    checks = CHECKS[key](sim)
    passed = sum(c.passed for c in checks)
    if passed == len(checks):
        verdict = "shown"
    elif passed:
        verdict = "partly"
    else:
        verdict = "not this time"

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
