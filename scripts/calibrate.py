"""Run the model over several seeds and check it against the stylized facts.

A result that only holds for one seed is not a result. This script is the only
thing that decides whether a change to the model was an improvement.

    python scripts/calibrate.py --runs 5 --steps 8000
    python scripts/calibrate.py --set herd_strength=4.0 --set switch_rate=0.3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mes import Config, Simulation  # noqa: E402
from mes.instruments import correlation_matrix  # noqa: E402
from mes.metrics import analyse  # noqa: E402

WARMUP_DAYS = 50  # days discarded before measuring: the seeded book is still around


def parse_overrides(pairs: list[str]) -> dict:
    out: dict = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        out[key.strip()] = float(value)
    return out


def run_once(cfg: Config, steps: int) -> list[dict]:
    """One run, measured separately for every instrument.

    Per instrument, not averaged: the stylized facts are a claim about each
    market. A model where two sectors look right and three do not has not
    reproduced them, and an average would hide that.
    """
    sim = Simulation(cfg)
    for _ in range(steps):
        sim.step()

    out = []
    for symbol, market in sim.markets.items():
        returns = np.array(market.daily_returns[WARMUP_DAYS:])
        volumes = np.array([bar["v"] for bar in market.bars[WARMUP_DAYS + 1:]])
        report = analyse(returns, volumes)
        if report.get("insufficient"):
            raise SystemExit(f"Nur {len(returns)} Tage — mehr Schritte nötig.")
        report["_symbol"] = symbol
        report["_days"] = len(returns)
        report["_price"] = market.price
        report["_fair"] = market.instrument.fundamental
        report["_stretch"] = abs(market.stretch())
        out.append(report)

    warm = WARMUP_DAYS * cfg.steps_per_day
    correlation = correlation_matrix(sim.sector_returns())
    for report in out:
        report["_margin_calls"] = sim.margin_calls
        report["_chartist_share_std"] = float(np.std(sim.chartist_share_hist[warm:]))
        report["_avg_correlation"] = correlation["average"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--steps", type=int, default=8000)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    args = ap.parse_args()

    overrides = parse_overrides(args.set)
    if overrides:
        print("Overrides:", ", ".join(f"{k}={v}" for k, v in overrides.items()))

    reports = []
    for i in range(args.runs):
        cfg = Config(**{**overrides, "seed": 1000 + i * 137})
        reports.extend(run_once(cfg, args.steps))
        print(f"  Lauf {i + 1}/{args.runs} fertig (Seed {cfg.seed})", flush=True)

    symbols = sorted({r["_symbol"] for r in reports})
    names = [c["name"] for c in reports[0]["stylized_facts"]]
    total = len(reports)

    print(f"\n{len(symbols)} Instrument(e) x {args.runs} Läufe = {total} Messungen\n")
    print(f"{'Kriterium':<34} {'Mittel':>10} {'Streuung':>10}  bestanden")
    print("-" * 74)

    passed_total = 0
    for idx, name in enumerate(names):
        values = np.array([r["stylized_facts"][idx]["value"] for r in reports
                           if r["stylized_facts"][idx]["value"] is not None])
        passes = sum(r["stylized_facts"][idx]["passed"] for r in reports)
        ok = passes > total / 2
        passed_total += ok
        mark = "JA " if ok else "NEIN"
        mean = np.nanmean(values) if len(values) else float("nan")
        spread = np.nanstd(values) if len(values) else float("nan")
        print(f"{name:<34} {mean:>10.4f} {spread:>10.4f}  {mark} ({passes}/{total})")

    print("-" * 74)
    print(f"{passed_total}/{len(names)} Kriterien bestanden (Ziel: mindestens {len(names) - 1})")

    if len(symbols) > 1:
        print(f"\n{'Instrument':<12}{'bestanden':>11}{'Vola':>8}{'|Abw|':>8}{'ACF1':>8}")
        for symbol in symbols:
            rows = [r for r in reports if r["_symbol"] == symbol]
            per = np.mean([sum(c["passed"] for c in r["stylized_facts"]) for r in rows])
            print(f"{symbol:<12}{per:>8.1f}/{len(names)}"
                  f"{np.mean([r['annualised_vol'] for r in rows]):>8.2f}"
                  f"{np.mean([r['_stretch'] for r in rows]) * 100:>7.0f}%"
                  f"{np.mean([r['acf_returns'][0] for r in rows]):>+8.3f}")

    def avg(key: str) -> float:
        return float(np.nanmean([r[key] for r in reports if r.get(key) is not None]))

    print(
        f"\nVola (annualisiert) {avg('annualised_vol'):.3f} · "
        f"max. Drawdown {avg('max_drawdown'):.3f} · "
        f"Margin Calls {avg('_margin_calls'):.0f} · "
        f"Streuung Chartistenanteil {avg('_chartist_share_std'):.3f}"
    )
    if len(symbols) > 1:
        print(f"Durchschnittliche Sektor-Korrelation {avg('_avg_correlation'):.3f}")
    return 0 if passed_total >= len(names) - 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
