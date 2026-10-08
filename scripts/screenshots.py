"""Regenerate the README screenshots from a running server.

Every other artefact in this repository is generated rather than committed by
hand, for the reason the README gives about the offline snapshot: a picture
written once and never rebuilt starts describing a version of the program that
no longer exists. The screenshots are the same kind of claim, so they are built
the same way.

Playwright is deliberately *not* in requirements.txt — nothing the simulator
does needs a browser engine, and `start.sh` installs that file in full on first
run. Install it separately when you want to rebuild the images:

    pip install playwright && playwright install chromium
    ./start.sh                       # in another shell, and let it warm up
    python scripts/screenshots.py

The town needs its warm-up finished before it is worth photographing: the
validation panel says nothing until a hundred trading days exist, so this waits
for `warming` in /api/state to go false rather than trusting a sleep.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VIEWS = [("", "town"), ("/sectors", "sectors"), ("/indices", "indices"), ("/traders", "traders")]
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def wait_until_warm(base: str, timeout: float) -> None:
    import json

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/state", timeout=5) as r:
                if not json.load(r).get("warming", True):
                    return
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass
        time.sleep(3)
    raise SystemExit(
        f"{base} was still warming after {timeout:.0f}s. Start it with ./start.sh and try again."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for the warm-up")
    ap.add_argument("--settle", type=float, default=6.0, help="seconds of live frames before each shot")
    # The town is WebGL. Playwright's own headless Chromium draws it in software, which
    # works; a local Chrome draws it on the GPU and is faster. Either is fine.
    ap.add_argument("--chromium", default=None,
                    help="path to a Chromium/Chrome executable instead of Playwright's own")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("playwright is not installed — see the note at the top of this file.", file=sys.stderr)
        return 1

    wait_until_warm(args.base, args.timeout)
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chromium) if args.chromium \
            else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)

        for path, name in VIEWS:
            page.goto(args.base + path, wait_until="networkidle")
            time.sleep(args.settle)
            page.keyboard.press("Escape")  # the town opens its explanation on a first visit
            # Give the 3D town a few frames to grow its buildings to their heights.
            time.sleep(3.0 if name == "town" else 1.5)
            page.screenshot(path=str(OUT / f"{name}.png"))
            print(f"{name:<10} {(OUT / f'{name}.png').stat().st_size // 1024:>5} KB")

        # The validation panel is the scientific claim and sits below the fold.
        page.goto(args.base + "/sectors", wait_until="networkidle")
        time.sleep(args.settle)
        page.locator("h2", has_text="Validation").first.scroll_into_view_if_needed()
        time.sleep(1.5)
        page.screenshot(path=str(OUT / "validation.png"))
        print(f"{'validation':<10} {(OUT / 'validation.png').stat().st_size // 1024:>5} KB")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
