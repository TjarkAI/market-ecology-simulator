#!/usr/bin/env python3
"""Build `Marktstadt.app` — a Dock launcher that starts the bridge and the town.

There is nothing to compile: the bundle is a folder with a plist, a bash script and
an icon. Generating it from a script rather than checking a binary blob into the
project means the icon can be changed by editing a few coordinates, and a broken
bundle is one command away from being correct again.

    python scripts/build_app.py            # bundle + icon
    python scripts/build_app.py --icon-only

What the launcher does, in order: find the project folder, free port 8000 so a
double-click always runs the current code, then hand `start.sh` to Terminal.app in a
visible window. Visible on purpose — the first start installs dependencies and the
market then fast-forwards 110 trading days, and both of those should be watchable
rather than a spinning Dock icon. Ctrl-C in that window stops the run.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "Marktstadt.app"
NAME = "Marktstadt"

# The town's palette, so the icon and the thing it opens are recognisably the same
# project. From the `:root` block in web/index.html.
BG_OUTER = (13, 11, 10)
BG_INNER = (44, 35, 27)
PLATE = (30, 25, 20)
PLATE_EDGE = (58, 46, 36)
MOM = (232, 129, 76)     # the momentum quarter
VAL = (79, 184, 160)     # the value quarter
EXCH = (255, 176, 110)   # an exchange
LAMP = (74, 208, 122)    # the live lamp


# --------------------------------------------------------------------- the icon
def squircle(size: int, radius_ratio: float = 0.225) -> Image.Image:
    """The macOS app-icon shape: a rounded square with a little air around it."""
    pad = round(size * 0.055)
    box = size - 2 * pad
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [pad, pad, pad + box, pad + box], radius=round(box * radius_ratio), fill=255)
    return mask


def backdrop(size: int) -> Image.Image:
    """The stage the town stands on: dark, lit from above like the real one."""
    plate = Image.new("RGB", (size, size), BG_OUTER)
    draw = ImageDraw.Draw(plate)
    # A cheap radial glow — concentric ellipses, then blurred. Good enough at any
    # icon size and it needs no numpy.
    cx, cy = size / 2, size * 0.30
    steps = 40
    for i in range(steps, 0, -1):
        t = i / steps
        r = size * 0.95 * t
        colour = tuple(round(BG_OUTER[c] + (BG_INNER[c] - BG_OUTER[c]) * (1 - t) ** 1.6)
                       for c in range(3))
        draw.ellipse([cx - r, cy - r * 0.85, cx + r, cy + r * 0.85], fill=colour)
    return plate.filter(ImageFilter.GaussianBlur(size / 60))


def iso_tile(cx: float, cy: float, a: float) -> list[tuple[float, float]]:
    """A 2:1 isometric tile's top face, centred on (cx, cy)."""
    return [(cx, cy - a / 2), (cx + a, cy), (cx, cy + a / 2), (cx - a, cy)]


def shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in colour)


def draw_block(draw: ImageDraw.ImageDraw, gx: float, gy: float,
               a: float, height: float, colour: tuple[int, int, int]) -> None:
    """One building: a lit top face and two walls, the right one darker.

    Same geometry the town uses — a tile plus two parallelograms — which is why the
    icon reads as a small piece of the map rather than as a generic bar chart.
    """
    top_y = gy - height
    top = iso_tile(gx, top_y, a)
    n, e, s, w = top
    # left wall: W → S → S+h → W+h
    draw.polygon([w, s, (s[0], s[1] + height), (w[0], w[1] + height)],
                 fill=shade(colour, 0.52))
    # right wall, in shadow
    draw.polygon([s, e, (e[0], e[1] + height), (s[0], s[1] + height)],
                 fill=shade(colour, 0.34))
    draw.polygon(top, fill=colour)


def render_icon(size: int = 1024) -> Image.Image:
    """Three towers on a plate. Deliberately only three.

    An icon is read at 32 pixels in the Dock, and the town's actual skyline turns to
    mud at that size. Three blocks of clearly different heights in three clearly
    different colours survive the downscale, and they are the three things the town
    is about: the trend followers, an exchange, the value camp.
    """
    scale = 4                                     # supersample, then shrink
    s = size * scale
    canvas = backdrop(s).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    unit = s / 1024.0
    cx, base = s / 2, s * 0.640

    # the ground plate, a wide flat diamond
    plate = iso_tile(cx, base, 424 * unit)
    draw.polygon(plate, fill=PLATE, outline=PLATE_EDGE, width=round(5 * unit))

    # Painted back to front so the near buildings overlap the far ones, which is the
    # only thing giving the group depth.
    a = 100 * unit
    for gx, gy, height, colour in [
        (cx - 172 * unit, base - 40 * unit, 172 * unit, VAL),    # value, low, west
        (cx + 175 * unit, base - 35 * unit, 272 * unit, EXCH),   # exchange, east
        (cx + 2 * unit,   base + 50 * unit, 380 * unit, MOM),    # momentum, tall, front
    ]:
        draw_block(draw, gx, gy, a, height, colour)

    # The live lamp: a status pip, not a moon. It was four times this size and read
    # as the subject of the icon rather than a note on it — but it is the one mark
    # that still says "running" at sixteen pixels, so it stays, small.
    r = 15 * unit
    lx, ly = s * 0.815, s * 0.180
    draw.ellipse([lx - r * 2.4, ly - r * 2.4, lx + r * 2.4, ly + r * 2.4],
                 fill=(*LAMP, 46))
    draw.ellipse([lx - r, ly - r, lx + r, ly + r], fill=(*LAMP, 255))

    icon = canvas.resize((size, size), Image.LANCZOS)
    icon.putalpha(squircle(size))
    return icon


def write_icns(target: Path) -> None:
    """Every size iconutil wants, rendered once and downsampled."""
    master = render_icon(1024)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / f"{NAME}.iconset"
        iconset.mkdir()
        for point in (16, 32, 128, 256, 512):
            for suffix, factor in (("", 1), ("@2x", 2)):
                px = point * factor
                master.resize((px, px), Image.LANCZOS).save(
                    iconset / f"icon_{point}x{point}{suffix}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)],
                       check=True)


# ------------------------------------------------------------------ the launcher
LAUNCHER = r'''#!/bin/bash
# Marktstadt-Starter: startet die Brücke (uvicorn, mes/api.py) in einem sichtbaren
# Terminal-Fenster und öffnet die Stadt im Browser. Fenster offen lassen — dort
# stehen die Logs, Strg-C beendet den Lauf.
#
# Das Fenster ist Absicht: der erste Start richtet die virtuelle Umgebung ein und
# installiert die Abhängigkeiten, danach spult der Markt 110 Handelstage vor. Beides
# will man sehen können und nicht hinter einem hüpfenden Dock-Symbol raten.

PORT="${MES_PORT:-8000}"

# Der Projektordner ist normalerweise der, in dem diese .app liegt. $MES_HOME
# überschreibt das, falls die App woanders liegen soll.
SELF_PARENT="$(cd "$(dirname "$0")/../../.." 2>/dev/null && pwd)"
PROJ=""
for P in "$MES_HOME" "$SELF_PARENT"; do
  if [ -n "$P" ] && [ -f "$P/mes/api.py" ] && [ -x "$P/start.sh" ]; then PROJ="$P"; break; fi
done

if [ -z "$PROJ" ]; then
  osascript -e 'display alert "Marktstadt" message "Projektordner nicht gefunden.\n\nMarktstadt.app muss IM Projektordner liegen — neben mes/, web/ und start.sh. Nicht nach ~/Downloads, ~/Desktop oder ~/Documents verschieben: dort sperrt macOS (TCC) die Helferprozesse.\n\nFürs Dock: die App im Projektordner lassen und von dort ins Dock ziehen — das Dock legt nur eine Verknüpfung an.\n\nAlternativ MES_HOME auf den Projektpfad setzen."'
  exit 1
fi

# Läuft schon eine Brücke auf dem Port? Hier beenden, bevor das Terminal eine neue
# startet — sonst zeigt ein Doppelklick den alten Code weiter an.
#
# -sTCP:LISTEN ist nicht optional: ohne den Filter listet lsof auch jeden *Client*
# mit offener Verbindung auf diesen Port, und der zweite Doppelklick erschlägt dann
# den Netzwerkprozess des Browsers, der gerade die Stadt anzeigt. Genau das ist beim
# Testen passiert.
OLD=$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null)
if [ -n "$OLD" ]; then kill $OLD 2>/dev/null; sleep 1; fi

# start.sh richtet die Umgebung ein, startet uvicorn und öffnet den Browser, sobald
# der Server antwortet. Deshalb genügt hier ein Aufruf.
osascript <<OSA
tell application "Terminal"
  activate
  do script "cd " & quoted form of "$PROJ" & " && clear && echo '▶ Marktstadt startet — Fenster offen lassen, Strg-C beendet.' && PORT=$PORT ./start.sh"
end tell
OSA
'''


def write_bundle() -> None:
    contents = APP / "Contents"
    macos, resources = contents / "MacOS", contents / "Resources"
    for folder in (macos, resources):
        folder.mkdir(parents=True, exist_ok=True)

    plist = {
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleIdentifier": "de.rtc.marktstadt.launcher",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": NAME,
        "CFBundleIconFile": NAME,
        "LSMinimumSystemVersion": "10.13",
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(plist, handle)

    launcher = macos / NAME
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--icon-only", action="store_true")
    args = parser.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("Nur auf macOS: das Bundle und iconutil sind macOS-spezifisch.")
    if shutil.which("iconutil") is None:
        raise SystemExit("iconutil fehlt — gehört zu den Xcode Command Line Tools.")

    icns = APP / "Contents" / "Resources" / f"{NAME}.icns"
    if not args.icon_only:
        write_bundle()
    write_icns(icns)

    # Finder caches icons per bundle; touching it makes the new one appear without
    # a logout.
    subprocess.run(["touch", str(APP)], check=False)
    print(f"{APP} gebaut.")
    print("Ins Dock: App aus dem Projektordner ins Dock ziehen (das Dock legt nur "
          "eine Verknüpfung an, die App bleibt hier liegen).")


if __name__ == "__main__":
    main()
