"""Recording a run to disk, and replaying it.

A run is a directory: one Parquet file of per-step series, one of daily bars, and
the config as JSON. The config includes the seed, which is what makes a recording
worth keeping — anyone with the directory can reproduce the run exactly rather
than merely look at its output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .simulation import Simulation

RUNS = Path(__file__).resolve().parent.parent / "runs"


@dataclass
class Recorder:
    """Collects the per-step series of a running simulation."""

    step: list[int] = field(default_factory=list)
    price: list[float] = field(default_factory=list)
    fair: list[float] = field(default_factory=list)
    volume: list[int] = field(default_factory=list)
    chartist_share: list[float] = field(default_factory=list)
    sentiment: list[float] = field(default_factory=list)
    margin_calls: list[int] = field(default_factory=list)
    orders: list[int] = field(default_factory=list)

    def capture(self, sim: Simulation) -> None:
        self.step.append(sim.t)
        self.price.append(sim.price)
        self.fair.append(sim.fair)
        self.volume.append(sim.step_volume)
        self.chartist_share.append(sim.chartist_share())
        self.sentiment.append(sim.world.sentiment)
        self.margin_calls.append(sim.step_margin_calls)
        self.orders.append(sim.step_orders)

    def __len__(self) -> int:
        return len(self.step)

    def frame(self):
        import pandas as pd

        return pd.DataFrame(
            {
                "step": self.step,
                "price": self.price,
                "fair": self.fair,
                "volume": self.volume,
                "chartist_share": self.chartist_share,
                "sentiment": self.sentiment,
                "margin_calls": self.margin_calls,
                "orders": self.orders,
            }
        )

    def save(self, sim: Simulation, name: str, stamp: str, root: Path | None = None) -> Path:
        """Write the run to `runs/<stamp>_<name>/`.

        `stamp` is passed in rather than read from the clock so that the caller
        decides how a run is named, and so this stays testable.
        """
        import pandas as pd

        target = (root or RUNS) / f"{stamp}_{name}"
        target.mkdir(parents=True, exist_ok=True)

        self.frame().to_parquet(target / "series.parquet", index=False)
        pd.DataFrame(sim.bars).to_parquet(target / "bars.parquet", index=False)

        meta = {
            "name": name,
            "stamp": stamp,
            "scenario": sim.scenario_key,
            "steps": sim.t,
            "days": len(sim.bars),
            "margin_calls": sim.margin_calls,
            "wipeouts": sim.wipeouts,
            # The configuration the run *began* with, seed included: this is the
            # reproducibility record. Deliberately not the live one — a scripted
            # `params` action mutates it, so saving it wrote down an end state and
            # the replay then re-applied the same change from the timeline on top.
            "config": sim.cfg_start,
            # The scenario's timeline, without which the config is not enough. A
            # scenario is parameters *and* scheduled headlines, and the headlines
            # were never written down — so a recorded crash replayed as a quiet
            # market with the same seed and nothing in the file to explain it.
            "script": [[int(step), action] for step, action in sim.script_source],
            "events": [event.to_dict() for event in sim.events],
        }
        (target / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        return target


def load(path: str | Path) -> dict:
    """Read a recorded run back. `config` reproduces it exactly."""
    import pandas as pd

    target = Path(path)
    meta = json.loads((target / "run.json").read_text())
    return {
        "meta": meta,
        "config": Config.from_dict(meta["config"]),
        "series": pd.read_parquet(target / "series.parquet"),
        "bars": pd.read_parquet(target / "bars.parquet"),
    }


def restore(sim: Simulation, meta: dict) -> Simulation:
    """Put a recording's scheduled events back on a fresh simulation.

    Recordings written before the timeline was saved have no `script` key; they
    reproduce as far as their config allows, which is exactly as well as they did
    before.
    """
    sim.install_script(meta.get("script") or [], key=meta.get("scenario"))
    return sim


def reproduce(path: str | Path) -> Simulation:
    """Re-run a recording from its config. The prices must come out identical —
    that is the point of storing the seed."""
    record = load(path)
    sim = restore(Simulation(record["config"]), record["meta"])
    for _ in range(record["meta"]["steps"]):
        sim.step()
    return sim


def catalogue(root: Path | None = None) -> list[dict]:
    """Everything under runs/, newest first."""
    base = root or RUNS
    if not base.exists():
        return []
    out = []
    for entry in sorted(base.iterdir(), reverse=True):
        meta_file = entry / "run.json"
        if not meta_file.is_file():
            continue
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, ValueError) as error:
            # One half-written run.json used to take the whole catalogue with it:
            # a 500 from `/api/runs`, and every other recording on disk invisible
            # behind it. A directory that cannot be read is one unreadable row.
            out.append({"path": str(entry), "name": entry.name, "stamp": None,
                        "scenario": None, "days": None, "seed": None,
                        "error": f"{type(error).__name__}: {error}"})
            continue
        out.append(
            {
                "path": str(entry),
                "name": meta.get("name"),
                "stamp": meta.get("stamp"),
                "scenario": meta.get("scenario"),
                "days": meta.get("days"),
                "seed": meta.get("config", {}).get("seed"),
            }
        )
    return out


@dataclass
class Replay:
    """Replaying a recorded run, by recomputing it rather than storing it.

    The simulation is deterministic in its seed, so a recording does not need a
    snapshot of every state: it needs the config. Seeking to step N means running N
    steps from a fresh start, and seeking forwards from where we already are means
    running only the difference. Nothing about the reconstruction is approximate —
    it is the same run, not a summary of it.

    That buys the whole state at every position, which a series export cannot give:
    the order book, the districts, the agents. The cost is time rather than disk,
    and it is paid only when seeking backwards.
    """

    meta: dict
    cfg: Config
    sim: Simulation
    position: int = 0

    @classmethod
    def open(cls, path: str | Path) -> "Replay":
        record = load(path)
        cfg = record["config"]
        return cls(meta=record["meta"], cfg=cfg,
                   sim=restore(Simulation(cfg), record["meta"]))

    @property
    def total(self) -> int:
        return int(self.meta.get("steps", 0))

    def seek(self, step: int) -> int:
        """Move to a step. Forwards is incremental, backwards restarts."""
        target = max(0, min(int(step), self.total))
        if target < self.position:
            self.sim.reset(self.cfg)
            # `reset` empties the queue, so the timeline has to go back on. Without
            # this, seeking backwards produced a market with no headlines while
            # seeking forwards produced one with them — the same recording, two
            # different runs, depending on which way the scrubber was dragged.
            restore(self.sim, self.meta)
            self.position = 0
        while self.position < target:
            self.sim.step()
            self.position += 1
        return self.position

    def advance(self, n: int = 1) -> int:
        return self.seek(self.position + n)

    def to_dict(self) -> dict:
        return {
            "name": self.meta.get("name"),
            "stamp": self.meta.get("stamp"),
            "scenario": self.meta.get("scenario"),
            "seed": self.cfg.seed,
            "position": self.position,
            "total": self.total,
            "progress": round(self.position / max(self.total, 1), 4),
            "day": self.position // max(1, self.cfg.steps_per_day),
            "days_total": self.total // max(1, self.cfg.steps_per_day),
        }
