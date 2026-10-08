"""Scenarios: parameter presets plus a script of events.

A scenario never dictates what the price does. It sets the conditions — how
strongly agents chase trends, how much leverage is allowed, what the news says —
and then the model answers. Whether "Financial crisis 2008" produces a 12% or a 45%
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
        name="Calm market",
        description="Little trend following, plenty of liquidity, hardly any leverage. "
                    "The price follows the fundamental value without large swings.",
        question="What does the market look like when no feedback loop is at work?",
        overrides={"chartist_aggression": 30.0, "herd_strength": 0.5,
                   "max_leverage": 1.5, "n_makers": 20, "news_intensity": 0.1},
    ),
    Scenario(
        key="bubble",
        name="Bubble formation",
        description="Strong trend following and a strong herd instinct. Nobody issues "
                    "a buy recommendation. The bubble arises from the feedback loop.",
        question="Can a price bubble arise from trend following alone?",
        overrides={"chartist_aggression": 140.0, "herd_strength": 4.0,
                   "switch_rate": 0.35, "fundamental_aggression": 0.15,
                   "issue_threshold": 0.5},
    ),
    Scenario(
        key="leverage_crash",
        name="Leverage crash",
        description="High leverage and a tight margin threshold. An ordinary price "
                    "decline is enough to trigger forced sales, which produce the "
                    "next decline.",
        question="How much of a crash comes from the trigger and how much from the "
                 "forced liquidation?",
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
            (8, {"note": "Leverage has built up. Everything is still calm."}),
            # A trigger, because the point of the scenario is the cascade and not
            # the wait for one. How far the price falls afterwards is still the
            # model's answer: the first forced sale pushes the price down, which
            # puts the next fund below its margin.
            (12, {"news": ["Major investor pulls out", -0.12]}),
        ],
    ),
    Scenario(
        key="etf_dominance",
        name="ETF dominance",
        description="Most of the capital flows into the market without regard to "
                    "price. Nobody checks any more what something is worth.",
        question="Do passive inflows make the market more stable or less stable?",
        overrides={"n_passive": 200, "passive_inflow": 220.0,
                   "n_adaptive": 150, "issue_threshold": 0.3},
    ),
    Scenario(
        key="news_shock",
        name="News shock",
        description="A large negative shock to the fundamental value. Each group "
                    "reads it differently. The ETF does not read it at all.",
        question="How does a heterogeneous market process the same headline?",
        overrides={"news_intensity": 0.4},
        timeline=[
            (5, {"news": ["Geopolitical tensions escalate", -0.25]}),
            (6, {"note": "The shock hit only fair value. What the price does is up "
                         "to the agents."}),
        ],
    ),
]


# ----------------------------------------------------------- history set
# Mechanisms, not price paths. Each entry names the mechanism it is testing.
HISTORY = [
    Scenario(
        key="dotcom",
        name="Dotcom bubble 1998–2000",
        description="A phase of high fundamental expectations meets strong trend "
                    "following. After two years the expectations turn. The herd "
                    "instinct stays.",
        question="Is a reversal in expectations, with herd behaviour unchanged, enough "
                 "to turn a rise lasting several years into a crash?",
        overrides={"fundamental_drift": 0.40 / (252 * 240), "chartist_aggression": 135.0,
                   "herd_strength": 3.5, "fundamental_aggression": 0.15,
                   "issue_threshold": 0.45, "n_leveraged": 35},
        timeline=[
            (10, {"note": "Growth phase: expectations carry the price."}),
            (500, {"params": {"fundamental_drift": -0.25 / (252 * 240)}}),
            (500, {"news": ["Analysts sharply cut growth expectations", -0.06]}),
            (502, {"note": "Expectations have turned. The herd instinct is unchanged."}),
        ],
    ),
    Scenario(
        key="gfc2008",
        name="Financial crisis 2008",
        description="High leverage in the system, then a shock. The funds' forced "
                    "sales produce the next margin call.",
        question="How much of a crash comes from the news and how much from the "
                 "forced liquidation?",
        overrides={"max_leverage": 7.0, "maintenance_margin": 0.32,
                   "n_leveraged": 70, "chartist_aggression": 110.0,
                   "issue_threshold": 0.35},
        timeline=[
            (200, {"note": "Leverage has built up. Everything is still calm."}),
            (260, {"news": ["Major investor pulls out", -0.10]}),
            (263, {"news": ["Regulator opens proceedings", -0.08]}),
            (266, {"note": "From here on the funds sell because they have to, not "
                           "because they want to."}),
        ],
    ),
    Scenario(
        key="covid",
        name="COVID crash 2020",
        description="A very fast, very large shock, followed by a massive injection "
                    "of liquidity.",
        question="Can a flood of liquidity more than make up for a fundamental "
                 "shock?",
        overrides={"chartist_aggression": 115.0, "n_leveraged": 45,
                   "maintenance_margin": 0.30},
        timeline=[
            (120, {"news": ["Worldwide production halts announced", -0.30]}),
            (122, {"news": ["Demand collapses across all industries", -0.12]}),
            (128, {"news": ["Central Bank announces unlimited asset purchases", 0.10]}),
            (130, {"params": {"passive_inflow": 260.0}}),
            (132, {"note": "Fair value is still lower than before the shock. "
                           "The price does not have to follow it."}),
        ],
    ),
    Scenario(
        key="memestock",
        name="Meme stock 2021",
        description="A great many small, uncoordinated traders, an extreme herd "
                    "instinct, thin liquidity and little supply.",
        question="How far can a price detach from value when liquidity and supply "
                 "are scarce?",
        overrides={"n_noise": 700, "n_adaptive": 400, "herd_strength": 5.0,
                   "switch_rate": 0.5, "chartist_aggression": 150.0,
                   "n_makers": 4, "mm_quote_size": 60,
                   "issue_threshold": 0.9, "fundamental_aggression": 0.1},
        timeline=[
            (30, {"note": "Tight liquidity, hardly any supply, maximum herd instinct."}),
        ],
    ),
    Scenario(
        key="rates2022",
        name="Rate turn 2022",
        description="The Central Bank raises rates because inflation is running. "
                    "Valuations fall, leverage costs rise, inflows dry up: three "
                    "channels, at different speeds.",
        question="Does a rate hike work through valuation, through financing costs "
                 "or through inflows?",
        # Inflation is pushed up and the bank is left to react on its own. The rate
        # path is not scripted: it comes out of the Taylor rule meeting an economy
        # that reacts with a lag, which is what produces the overshoot.
        overrides={"chartist_aggression": 105.0, "n_leveraged": 50,
                   "max_leverage": 4.0, "maintenance_margin": 0.40,
                   "macro_shock": 0.05, "rate_adjust_days": 15.0},
        timeline=[
            (5, {"note": "Inflation is picking up. The Central Bank has not reacted yet."}),
            (6, {"inflation": 0.075}),
            (40, {"note": "The rate follows inflation up, with a lag."}),
            (120, {"note": "Valuations have fallen, leverage costs have risen, "
                           "inflows have dried up. Which of these moved the price "
                           "is shown in the Central Bank panel."}),
        ],
    ),
]

ALL = {s.key: s for s in BASIC + HISTORY}


def catalogue() -> list[dict]:
    """What the UI shows in the scenario picker."""
    return [
        {"group": "Basic scenarios", "items": [s.to_dict() for s in BASIC]},
        {"group": "Historical episodes", "items": [s.to_dict() for s in HISTORY]},
    ]


def get(key: str) -> Scenario | None:
    return ALL.get(key)
