"""Running two configurations side by side.

The question this exists for is the one the whole project is about: *what does this
parameter do to the market?* A slider answers it impressionistically. Two runs from
the same seed with one parameter changed answer it with numbers.

That only works because every agent draws from its own random stream, seeded from
the run's seed and the agent's id. With one stream shared across the market, how
many numbers an agent consumed depended on what it decided, so the first
behavioural difference desynchronised everybody and the two arms became different
worlds rather than the same world under two policies. A channel worth 0.4 % in fair
value used to produce a 39 % difference after 20 000 steps, almost all of it path
divergence.

With per-agent streams the effect scales with its cause. Measured over 20 000 steps:

    borrow spread 1.00 % vs 1.05 %       0.4 % apart
    savings-plan inflow 30 vs 33         0.0 % apart
    trend following 55 vs 140            3.5 % apart

And a parameter that cannot do anything does nothing: `max_leverage` changed with no
leveraged funds in the population gives bit-identical runs, which is the control the
test suite asserts.

`sweep_pair` still exists and is still the better tool for a small effect — one seed
pair says nothing about whether a difference is bigger than the variation between
seeds, however clean the mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import Config
from .instruments import correlation_matrix
from .metrics import analyse
from .simulation import Simulation

# Only the seeded starting book needs skipping, and that expires at step 200 —
# five days is well past it. The 20 used elsewhere was needlessly greedy here: at
# 240 steps a day it threw away 4 800 steps of a comparison that has to be short
# enough to run from a button.
WARMUP_DAYS = 5


@dataclass
class Arm:
    """One side of a comparison."""

    label: str
    overrides: dict
    cfg: Config
    sim: Simulation

    @classmethod
    def build(cls, label: str, base: Config, overrides: dict) -> "Arm":
        cfg = Config.from_dict({**base.to_dict(), **overrides})
        return cls(label=label, overrides=dict(overrides), cfg=cfg, sim=Simulation(cfg))

    def report(self) -> dict:
        """Validation figures averaged over this arm's instruments."""
        rows = []
        for market in self.sim.markets.values():
            returns = np.array(market.daily_returns[WARMUP_DAYS:])
            volumes = np.array([bar["v"] for bar in market.bars[WARMUP_DAYS + 1:]])
            report = analyse(returns, volumes)
            if report.get("insufficient"):
                continue
            rows.append(report)

        if not rows:
            return {"insufficient": True, "days": len(self.sim.market.bars)}

        def mean(key):
            values = [r[key] for r in rows if r.get(key) is not None]
            return float(np.nanmean(values)) if values else None

        stretch = [abs(m.stretch()) for m in self.sim.markets.values()]
        return {
            "days": len(self.sim.market.bars),
            "criteria_met": float(np.mean([sum(c["passed"] for c in r["stylized_facts"]) for r in rows])),
            "criteria_total": len(rows[0]["stylized_facts"]),
            "annualised_vol": mean("annualised_vol"),
            "max_drawdown": mean("max_drawdown"),
            "excess_kurtosis": mean("excess_kurtosis"),
            "acf1": float(np.mean([r["acf_returns"][0] for r in rows])),
            "clustering": mean("acf_abs_mean_1_10"),
            "hill": mean("hill_tail_index"),
            "volume_corr": mean("volume_volatility_corr"),
            "stretch": float(np.mean(stretch)),
            "margin_calls": self.sim.margin_calls,
            "wipeouts": self.sim.wipeouts,
            "chartist_share": self.sim.chartist_share(),
            "rate": self.sim.bank.rate,
            "correlation": correlation_matrix(self.sim.sector_returns())["average"],
        }

    def series(self, n: int = 400) -> dict:
        market = self.sim.market
        return {
            "label": self.label,
            "price": [round(p, 2) for p in market.prices[-n:]],
            "fair": [round(f, 2) for f in market.fundamentals[-n:]],
            "bars": market.bars[-160:],
        }


@dataclass
class Comparison:
    """Two arms stepped in lockstep."""

    a: Arm
    b: Arm
    steps: int = 0

    @classmethod
    def build(cls, base: Config, a: dict, b: dict,
              label_a: str = "A", label_b: str = "B") -> "Comparison":
        return cls(a=Arm.build(label_a, base, a), b=Arm.build(label_b, base, b))

    def advance(self, n: int) -> None:
        for _ in range(max(0, n)):
            self.a.sim.step()
            self.b.sim.step()
        self.steps += max(0, n)

    def to_dict(self) -> dict:
        report_a, report_b = self.a.report(), self.b.report()
        difference = {}
        for key, value in report_a.items():
            other = report_b.get(key)
            if isinstance(value, (int, float)) and isinstance(other, (int, float)):
                difference[key] = round(other - value, 6)

        return {
            "steps": self.steps,
            "a": {"label": self.a.label, "overrides": self.a.overrides, "metrics": report_a},
            "b": {"label": self.b.label, "overrides": self.b.overrides, "metrics": report_b},
            "difference": difference,
            "series": [self.a.series(), self.b.series()],
            "caveat": (
                "Jeder Agent zieht aus seinem eigenen Zufallsstrom, deshalb bleiben beide "
                "Läufe auf demselben Pfad, solange der Parameter nichts bewirkt — ein "
                "Unterschied ist also seine Wirkung, nicht Zufall. Was ein einzelnes "
                "Seed-Paar trotzdem nicht sagen kann: ob der Unterschied größer ist als "
                "die Variation zwischen Seeds. Dafür der Vergleich über mehrere Seeds."
            ),
        }


def sweep_pair(base: Config, a: dict, b: dict, steps: int,
               seeds: list[int]) -> dict:
    """Run the same comparison over several seeds and report the distributions.

    This is the honest version of an A/B in this model. One pair tells you almost
    nothing about a small effect; the spread across pairs tells you whether the
    difference is bigger than the noise it sits in.
    """
    keys = ("criteria_met", "annualised_vol", "acf1", "clustering", "hill",
            "volume_corr", "stretch", "margin_calls")
    collected: dict[str, dict[str, list]] = {"a": {k: [] for k in keys},
                                             "b": {k: [] for k in keys}}

    for seed in seeds:
        seeded = Config.from_dict({**base.to_dict(), "seed": seed})
        comparison = Comparison.build(seeded, a, b)
        comparison.advance(steps)
        for side, arm in (("a", comparison.a), ("b", comparison.b)):
            report = arm.report()
            for key in keys:
                value = report.get(key)
                if value is not None:
                    collected[side][key].append(value)

    summary = {}
    for key in keys:
        values_a = np.array(collected["a"][key], dtype=float)
        values_b = np.array(collected["b"][key], dtype=float)
        if not len(values_a) or not len(values_b):
            continue
        gap = float(values_b.mean() - values_a.mean())
        spread = float(np.sqrt(values_a.var() + values_b.var()) + 1e-12)
        summary[key] = {
            "a": round(float(values_a.mean()), 4),
            "b": round(float(values_b.mean()), 4),
            "difference": round(gap, 4),
            "spread": round(spread, 4),
            # Bigger than one means the gap stands out from the seed-to-seed noise.
            # Below one it does not, whatever the single-pair chart looks like.
            "signal_to_noise": round(abs(gap) / spread, 2),
        }

    return {"seeds": seeds, "steps": steps, "a": a, "b": b, "summary": summary}
