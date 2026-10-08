"""Run the model without the UI and write the result to disk.

    python scripts/run.py --steps 120000 --name baseline
    python scripts/run.py --scenario gfc2008 --name crisis --seed 42

Produces `runs/<stamp>_<name>/` with the per-step series, the daily bars, the
config including the seed, and the event log — everything needed to reproduce the
run or to analyse it in a notebook.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mes import Config, Simulation, scenarios  # noqa: E402
from mes.metrics import analyse  # noqa: E402
from mes.recorder import Recorder  # noqa: E402

WARMUP_DAYS = 20  # bars discarded before measuring: the seeded book is still there


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=120_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scenario", default=None, help="preset from mes/scenarios.py")
    ap.add_argument("--name", default="run")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    sim = Simulation(Config(seed=args.seed))
    if args.scenario:
        scenario = scenarios.get(args.scenario)
        if scenario is None:
            print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
            print("Available:", ", ".join(sorted(scenarios.ALL)), file=sys.stderr)
            return 2
        sim.load_scenario(scenario)
        print(f"Scenario: {scenario.name}\n  Question: {scenario.question}")

    recorder = Recorder()
    for i in range(args.steps):
        sim.step()
        recorder.capture(sim)
        if (i + 1) % 20_000 == 0:
            print(f"  {i + 1:,}/{args.steps:,} steps, {len(sim.bars):,} trading days", flush=True)

    returns = np.array(sim.daily_returns[WARMUP_DAYS:])
    volumes = np.array([bar["v"] for bar in sim.bars[WARMUP_DAYS + 1:]])
    report = analyse(returns, volumes)

    print(f"\n{len(sim.bars):,} trading days · price {sim.price:,.2f} · fair value {sim.fair:,.2f}")
    # `analyse` reports "insufficient" below fifty daily returns and returns none of
    # the figures below. Reading them anyway made a short run die on
    # `KeyError: 'annualised_vol'` after doing all of its work — and the run was
    # still worth saving. calibrate.py and sweep.py both guard this case; this one
    # did not.
    if report.get("insufficient"):
        print(f"Too few trading days for the figures: {report['n']} daily returns "
              f"after {WARMUP_DAYS} days of warm-up, 50 are needed. "
              f"For the stylized facts, 100+ days are sensible. "
              f"That is {(100 + WARMUP_DAYS) * sim.cfg.steps_per_day:,} steps.")
    else:
        print(f"Volatility {report['annualised_vol']:.3f} p.a. · "
              f"max. drawdown {report['max_drawdown']:.3f} · "
              f"margin calls {sim.margin_calls:,} · wipeouts {sim.wipeouts:,}")
        print()
        for check in report["stylized_facts"]:
            mark = "YES" if check["passed"] else "NO "
            value = "n/a" if check["value"] is None else f"{check['value']:.4f}"
            print(f"  {mark} {check['name']:<34} {value:>10}   {check['detail']}")
        passed = sum(c["passed"] for c in report["stylized_facts"])
        print(f"\n{passed}/{len(report['stylized_facts'])} criteria passed")

    if not args.no_save:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = recorder.save(sim, args.name, stamp)
        print(f"\nSaved: {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
