"""Parameter sweeps and ablations.

Two modes, one purpose: attribute a property of the market to a mechanism.

    # turn each mechanism off in turn and see what changes
    python scripts/sweep.py ablate --steps 80000

    # vary one parameter across a range
    python scripts/sweep.py param --name n_passive --values 0,50,100,200 --seeds 3

An ablation answers "which mechanism is responsible", a sweep answers "how much".
Both write a CSV so the result can be read again without re-running.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mes import Config, Simulation  # noqa: E402
from mes.metrics import analyse  # noqa: E402

WARMUP_DAYS = 20
OUT = Path(__file__).resolve().parent.parent / "runs"

# Each entry switches off exactly one mechanism. Anything that changes the
# result identifies a cause; anything that does not, rules one out.
ABLATIONS: dict[str, dict] = {
    "baseline":              {},
    "no market makers":      {"n_makers": 0},
    "no MM inventory skew":  {"mm_skew": 0.0},
    "no issuer":             {"n_companies": 0},
    "no value price anchor": {"value_price_pull": 0.0},
    "no value sizing":       {"fundamental_aggression": 0.0},
    "no trend following":    {"chartist_aggression": 0.0},
    "no herding":            {"herd_strength": 0.0},
    "no strategy switching": {"switch_rate": 0.0},
    "no ETF inflow":         {"passive_inflow": 0.0},
    "no leverage":           {"n_leveraged": 0},
    "no noise traders":      {"n_noise": 0},
}

FIELDS = ["variant", "seed", "days", "acf1", "acf2", "acf3", "kurtosis",
          "clustering", "hill", "vol_corr", "ann_vol", "passed",
          "chartist_mean", "chartist_std", "stretch_med", "margin_calls"]


def measure(cfg: Config, steps: int) -> dict:
    sim = Simulation(cfg)
    for _ in range(steps):
        sim.step()

    returns = np.array(sim.daily_returns[WARMUP_DAYS:])
    volumes = np.array([bar["v"] for bar in sim.bars[WARMUP_DAYS + 1:]])
    report = analyse(returns, volumes)
    if report.get("insufficient"):
        raise SystemExit(f"Too few days ({len(returns)}). More steps needed.")

    warm = WARMUP_DAYS * cfg.steps_per_day
    share = np.array(sim.chartist_share_hist[warm:])
    stretch = np.abs(np.log(np.array(sim.prices[warm:]) / np.array(sim.fundamentals[warm:])))

    return {
        "days": len(returns),
        "acf1": report["acf_returns"][0],
        "acf2": report["acf_returns"][1],
        "acf3": report["acf_returns"][2],
        "kurtosis": report["excess_kurtosis"],
        "clustering": report["acf_abs_mean_1_10"],
        "hill": report["hill_tail_index"],
        "vol_corr": report.get("volume_volatility_corr", float("nan")),
        "ann_vol": report["annualised_vol"],
        "passed": sum(c["passed"] for c in report["stylized_facts"]),
        "chartist_mean": float(share.mean()) if len(share) else float("nan"),
        "chartist_std": float(share.std()) if len(share) else float("nan"),
        "stretch_med": float(np.median(stretch)) if len(stretch) else float("nan"),
        "margin_calls": sim.margin_calls,
    }


def header() -> None:
    print(f"{'Variant':<24}{'ACF1':>8}{'ACF2':>7}{'Kurt':>7}{'Clu':>7}"
          f"{'Hill':>7}{'VolC':>7}{'Vol':>7}{'Chart':>13}{'Gap':>7}{'MC':>5}{'ok':>5}")
    print("-" * 105)


def show(label: str, row: dict) -> None:
    print(f"{label:<24}{row['acf1']:>+8.3f}{row['acf2']:>+7.3f}{row['kurtosis']:>7.2f}"
          f"{row['clustering']:>+7.3f}{row['hill']:>7.2f}{row['vol_corr']:>+7.2f}"
          f"{row['ann_vol']:>7.3f}"
          f"{row['chartist_mean']:>8.2f}±{row['chartist_std']:<4.2f}"
          f"{row['stretch_med'] * 100:>6.0f}%{row['margin_calls']:>5}{row['passed']:>4}/6",
          flush=True)


def write_csv(rows: list[dict], name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_ablation(steps: int, seeds: list[int]) -> list[dict]:
    header()
    rows = []
    for label, overrides in ABLATIONS.items():
        per_seed = []
        for seed in seeds:
            row = measure(Config(seed=seed, **overrides), steps)
            row.update(variant=label, seed=seed)
            rows.append(row)
            per_seed.append(row)
        mean = {k: float(np.nanmean([r[k] for r in per_seed])) for k in FIELDS
                if k not in ("variant", "seed")}
        show(label, mean)
    return rows


def run_param(name: str, values: list[float], steps: int, seeds: list[int]) -> list[dict]:
    if name not in Config().to_dict():
        raise SystemExit(f"Unknown parameter: {name}")
    caster = type(getattr(Config(), name))
    header()
    rows = []
    for value in values:
        per_seed = []
        for seed in seeds:
            row = measure(Config(seed=seed, **{name: caster(value)}), steps)
            row.update(variant=f"{name}={value}", seed=seed)
            rows.append(row)
            per_seed.append(row)
        mean = {k: float(np.nanmean([r[k] for r in per_seed])) for k in FIELDS
                if k not in ("variant", "seed")}
        show(f"{name}={value}", mean)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ablate", "param"])
    ap.add_argument("--steps", type=int, default=80_000)
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--name", help="parameter name for param mode")
    ap.add_argument("--values", help="comma-separated values for param mode")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    seeds = [1000 + i * 137 for i in range(args.seeds)]
    print(f"{args.steps:,} steps, {len(seeds)} seed(s)\n")

    if args.mode == "ablate":
        rows = run_ablation(args.steps, seeds)
        name = args.out or "ablation.csv"
    else:
        if not args.name or not args.values:
            raise SystemExit("param mode needs --name and --values")
        values = [float(v) for v in args.values.split(",")]
        rows = run_param(args.name, values, args.steps, seeds)
        name = args.out or f"sweep_{args.name}.csv"

    print(f"\nWritten: {write_csv(rows, name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
