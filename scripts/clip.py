"""Record the short clip at the top of the README: a calm market, then a crash.

Built for the same reason as `scripts/screenshots.py`: a recording made once by
hand starts describing a program that no longer exists. Twenty seconds is what a
visitor actually watches, so the clip stays under that and shows the one thing a
still cannot — a shock to the fundamental value, and the cascade the agents make
of it. The crash is the `Crash` button (`POST /api/scenario/crash`), nothing more:
how far the price falls is the simulation's answer.

Neither Playwright nor ffmpeg is in requirements.txt, for the reason given in
`scripts/screenshots.py`. Install them separately when you want to rebuild:

    pip install playwright imageio-ffmpeg && playwright install chromium
    ./start.sh                       # in another shell, and let it warm up
    python scripts/clip.py

Writes docs/media/market-town-crash.mp4 (H.264, 1600×900, for LinkedIn and the
like) and docs/media/market-town-crash.gif (800 px, for the README).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from screenshots import wait_until_warm

OUT = Path(__file__).resolve().parent.parent / "docs" / "media"
W, H = 1600, 900
SETTLE = 5.0   # the town grows its buildings; cut away
CALM = 5.0     # the market as it runs, before the shock
CASCADE = 14.0


def post(base: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(base + path, method="POST",
                                 data=json.dumps(body or {}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for the warm-up")
    ap.add_argument("--chromium", default=None,
                    help="path to a Chromium/Chrome executable instead of Playwright's own")
    args = ap.parse_args()

    try:
        import imageio_ffmpeg
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("playwright or imageio-ffmpeg is not installed — see the note at the top of this file.",
              file=sys.stderr)
        return 1
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    wait_until_warm(args.base, args.timeout)
    OUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chromium) if args.chromium \
            else p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                  record_video_dir=tmp, record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        t0 = time.time()
        page.goto(args.base + "/", wait_until="networkidle")
        time.sleep(2.0)
        page.keyboard.press("Escape")  # the town opens its explanation on a first visit
        post(args.base, "/api/control", {"action": "speed", "speed": "4x"})
        time.sleep(SETTLE)
        start = time.time() - t0
        time.sleep(CALM)
        post(args.base, "/api/scenario/crash")
        time.sleep(CASCADE)
        ctx.close()
        browser.close()
        raw = next(Path(tmp).glob("*.webm"))

        mp4, gif = OUT / "market-town-crash.mp4", OUT / "market-town-crash.gif"
        subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", f"{start:.1f}", "-i", str(raw),
                        "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", "-an", str(mp4)], check=True)
        # The GIF starts a little later and is smaller: it sits in a README, where
        # every megabyte is a visitor waiting.
        palette = ("fps=8,scale=800:-1:flags=lanczos,split[a][b];"
                   "[a]palettegen=max_colors=96:stats_mode=diff[p];"
                   "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
        subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", f"{start + 1.3:.1f}", "-i", str(raw),
                        "-vf", palette, str(gif)], check=True)

    for f in (mp4, gif):
        print(f"{f.name:<26} {f.stat().st_size // 1024:>6} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
