#!/usr/bin/env python3
"""Regenerate the offline snapshot embedded in `web/index.html`.

The town is a single HTML file with no build step, and opening it straight from
the filesystem — no server, no Python — has to still draw something, otherwise
the design cannot be inspected as a file. That fallback used to be two snapshots
written by hand, and they drifted: they still claimed 550 agents and a single
exchange long after the model had 615 and five, and the page showed those numbers
for the first second of every real session. Fake figures that look live are worse
than no figures.

So the fallback is generated from a real run instead, and `tests/test_frontend.py`
compares its key set against a live snapshot, which fails the moment it drifts.

    python scripts/demo_state.py            # print the literal
    python scripts/demo_state.py --write    # splice it into web/index.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mes.city import snapshot  # noqa: E402
from mes.config import Config  # noqa: E402
from mes.simulation import Simulation  # noqa: E402

PAGE = ROOT / "web" / "index.html"
BEGIN = "/* demo-state:begin"
END = "/* demo-state:end */"
# Twenty trading days: long enough that the districts have separated and the log
# has something in it, short enough to stay a snapshot of a settling market.
DAYS = 20


def build(seed: int = 42, days: int = DAYS) -> dict:
    sim = Simulation(Config(seed=seed))
    for _ in range(days * sim.cfg.steps_per_day):
        sim.step()
    snap = snapshot(sim)
    # The fields the HTTP layer adds on top of the city snapshot. Offline there is no
    # clock, so the town says so rather than pretending to run.
    snap.update(running=False, speed="1x", warming=False, warmProgress=1.0,
                lesson=None, failure=None)
    return snap


def literal(snap: dict) -> str:
    body = json.dumps(snap, ensure_ascii=False, indent=1)
    return (f"{BEGIN} — erzeugt von scripts/demo_state.py, nicht von Hand ändern */\n"
            f"const DEMO =\n{body}\n;\n{END}")


def splice(text: str, block: str) -> str:
    start, stop = text.index(BEGIN), text.index(END) + len(END)
    return text[:start] + block + text[stop:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="splice into web/index.html")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args()

    block = literal(build(args.seed, args.days))
    if not args.write:
        print(block)
        return

    text = PAGE.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"Marker {BEGIN!r} / {END!r} fehlen in {PAGE}")
    PAGE.write_text(splice(text, block), encoding="utf-8")
    print(f"{PAGE}: Offline-Snapshot ersetzt ({len(block)} Zeichen)")


def extract(text: str) -> dict:
    """Read the literal back out of the page. Used by the test."""
    match = re.search(re.escape(BEGIN) + r".*?const DEMO\s*=\s*(\{.*?\})\s*;\s*"
                      + re.escape(END), text, re.S)
    if match is None:
        raise ValueError("kein Offline-Snapshot in der Seite gefunden")
    return json.loads(match.group(1))


if __name__ == "__main__":
    main()
