#!/usr/bin/env python3
"""Pixel preview of the SH1106 splash + boot/setup card (128x64).

Replays the draw calls of the brand splash in monoDisplayInit() and of
renderBootScreen() in src/mono_display.cpp with the real Adafruit glcdfont and
FreeMonoBold9pt7b, then writes a captioned contact sheet.

Why this exists: the boot card carries five blocks (brand, network, IP, section
and the printer rows) in 64 px, and the row budget is unforgiving: a row is
8 px, so one extra line pushes the last printer off the panel. The script
prints the coordinates, the ink bbox of every panel and how many configured
printers actually fit, and exits non-zero if a pixel leaves the panel.

Brand sizing note: "BambuHelper-OLED" is 174 px in FreeMonoBold9pt7b and 192 px
in the default font at size 2, so the repo name never fits on one big row. The
big title font also carries descenders down to baseline+4 ("Helper"), so a
"big name + -OLED under it" stack eats 23 px and leaves room for a single
printer. The card therefore uses one centred size-1 row, a hairline rule for
hierarchy, and spends the freed rows on air; the splash is where the big
9 pt wordmark lives.

Usage:
    python tools/render_boot_preview.py                 # splash + boot card
    python tools/render_boot_preview.py --no-splash
    python tools/render_boot_preview.py --scale 6 --cols 2 --out /tmp/boot.png

Requires the Adafruit GFX library to be installed: run `pio run` once (or
`pio pkg install`) so .pio/libdeps/<env>/.../glcdfont.c exists.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from oled_preview import (Canvas, H, ROOT, W, auto_cols, load_font,
                          load_gfx_font, write_sheet)

# --- LAYOUT: mirrors renderBootScreen() / the splash -------------------------
COLS = 21                  # default font: 6 px advance in a 128 px row
BRAND = "BambuHelper-OLED"
BRAND_BIG = "BambuHelper"  # 119 px in FreeMonoBold9pt7b (the widest that fits)
BRAND_Y = 0                # brand row: ink 0..6
RULE_Y = 9                 # hairline under the brand, separates the header
NET_Y = 12                 # "WiFi:"/"AP:" row
IP_Y = 21                  # "IP:" row
LABEL_Y = 33               # "Printer(s):" row (air under the network block)
LIST_Y = 42                # first printer row
LIST_STEP = 9              # 8 px cell + 1 px of air
INK_MAX_Y = 63             # last visible glyph row (row 7 of the cell is blank)
# Splash: both halves of the name plus the version in the 9 pt wordmark font
# ("BambuHelper" 119 px, "-OLED" 53 px, "v3.9.4" 64 px). Baselines 18 px apart:
# the title font descends to baseline+4 ("Helper"), so equal baselines are the
# only even-looking rhythm.
SPLASH_TITLE_BASE = 19
SPLASH_SUB_BASE = 37
SPLASH_VER_BASE = 55


def fw_version() -> str:
    src = (ROOT / "include" / "config.h").read_text(encoding="utf-8",
                                                    errors="ignore")
    m = re.search(r'FW_VERSION\s+"([^"]+)"', src)
    if not m:
        sys.exit("FW_VERSION not found in include/config.h")
    return m.group(1)


def fit_tag(tag: str, value: str, cols: int = COLS) -> str:
    """tag + value clipped to one row, with a ".." tail when it is cut."""
    room = cols - len(tag)
    if len(value) > room:
        value = value[:room - 2] + ".." if room > 2 else value[:room]
    return tag + value


def name_state(name: str, live: bool) -> str:
    """One printer row: "<name> - on" / "<name> - off" (name clipped)."""
    suffix = " - on" if live else " - off"
    return name[:COLS - len(suffix)] + suffix


@dataclass
class Scene:
    label: str
    ssid: str = ""
    ip: str = ""
    ap: bool = False
    printers: list[tuple[str, bool]] = field(default_factory=list)
    splash: bool = False


def draw_splash(c: Canvas, gfx) -> None:
    c.setFont(gfx)
    c.setTextSize(1)
    c.setCursor(0, SPLASH_TITLE_BASE)
    c.print(BRAND_BIG)
    c.setCursor(0, SPLASH_SUB_BASE)
    c.print(BRAND[11:])  # "-OLED"
    c.setCursor(0, SPLASH_VER_BASE)
    c.print(fw_version())


def draw_boot(c: Canvas, sc: Scene) -> None:
    c.setFont()
    c.setTextSize(1)
    c.setCursor((W - len(BRAND) * 6) // 2, BRAND_Y)
    c.print(BRAND)
    c.drawFastHLine(0, RULE_Y, W)
    c.setCursor(0, NET_Y)
    c.print(fit_tag("AP: " if sc.ap else "WiFi: ", sc.ssid))
    c.setCursor(0, IP_Y)
    c.print(fit_tag("IP: ", sc.ip))
    c.setCursor(0, LABEL_Y)
    c.print("Printer:" if len(sc.printers) == 1 else "Printers:")
    if not sc.printers:
        c.setCursor(0, LIST_Y)
        c.print("none configured")
        return
    y = LIST_Y
    for name, live in sc.printers:
        if y > INK_MAX_Y - 6:
            break
        c.setCursor(0, y)
        c.print(name_state(name, live))
        y += LIST_STEP


def check_scene(c: Canvas, sc: Scene) -> list[str]:
    errs = []
    bbox = c.ink_bbox()
    if bbox and (bbox[0] < 0 or bbox[2] >= W or bbox[1] < 0 or bbox[3] >= H):
        errs.append(f"ink bbox {bbox} leaves the panel")
    if c.oob:
        errs.append(f"{c.oob} px outside the panel")
    return errs


def visible_printers() -> int:
    """How many printer rows fit under the label."""
    return (INK_MAX_Y - 6 - LIST_Y) // LIST_STEP + 1


def firmware_drift_warnings() -> list[str]:
    src = (ROOT / "src" / "mono_display.cpp").read_text(
        encoding="utf-8", errors="ignore")
    pairs = [
        (r"BOOT_BRAND_Y\s*=\s*(\d+)", BRAND_Y, "brand row"),
        (r"BOOT_RULE_Y\s*=\s*(\d+)", RULE_Y, "brand rule"),
        (r"BOOT_NET_Y\s*=\s*(\d+)", NET_Y, "network row"),
        (r"BOOT_IP_Y\s*=\s*(\d+)", IP_Y, "IP row"),
        (r"BOOT_LABEL_Y\s*=\s*(\d+)", LABEL_Y, "printer label row"),
        (r"BOOT_LIST_Y\s*=\s*(\d+)", LIST_Y, "first printer row"),
        (r"BOOT_LIST_STEP\s*=\s*(\d+)", LIST_STEP, "printer row step"),
        (r"SPLASH_TITLE_BASE\s*=\s*(\d+)", SPLASH_TITLE_BASE,
         "splash title baseline"),
        (r"SPLASH_SUB_BASE\s*=\s*(\d+)", SPLASH_SUB_BASE,
         "splash -OLED baseline"),
        (r"SPLASH_VER_BASE\s*=\s*(\d+)", SPLASH_VER_BASE,
         "splash version baseline"),
    ]
    warns = []
    for pattern, expected, name in pairs:
        m = re.search(pattern, src)
        if not m:
            warns.append(f"could not find {name} in src/mono_display.cpp")
        elif int(m.group(1)) != expected:
            warns.append(f"{name}: firmware {m.group(1)} vs preview {expected}")
    return warns


def default_scenes() -> list[Scene]:
    return [
        Scene("splash", splash=True),
        Scene("wifi + 2 printers", "MiFibra-5G", "192.168.1.23",
              printers=[("X1 Carbon", True), ("Bambu Lab P1S", False)]),
        Scene("wifi + 1 printer", "MiFibra-5G", "192.168.1.23",
              printers=[("X1C", True)]),
        Scene("printer name too long", "MiFibra-5G", "192.168.1.23",
              printers=[("Bambu Lab P1S Combo Works", True),
                        ("Printer 2", False)]),
        Scene("ssid too long", "MiFibra-5G-A6F2-EXT", "192.168.1.23",
              printers=[("X1C", True)]),
        Scene("no printer configured", "MiFibra-5G", "192.168.1.23"),
        Scene("3 printers (list is cut)", "MiFibra-5G", "192.168.1.23",
              printers=[("X1C", True), ("Bambu Lab P1S", True),
                        ("A1 mini", False)]),
        Scene("no IP yet", "MiFibra-5G", "connecting",
              printers=[("X1C", False)]),
        Scene("AP setup mode", "BambuHelper-9F3A", "192.168.4.1", ap=True,
              printers=[("X1C", False)]),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render the SH1106 splash + boot card to a PNG sheet.")
    ap.add_argument("--no-splash", action="store_true",
                    help="drop the splash panel")
    ap.add_argument("--scale", type=int, default=5, help="pixels per OLED px")
    ap.add_argument("--cols", type=int, default=0,
                    help="panels per row (default: auto from panel count)")
    ap.add_argument("--gap", type=int, default=24,
                    help="gap between panels in output px (default 24)")
    ap.add_argument("--out", type=Path, default=ROOT / "preview" / "boot.png",
                    help="output PNG (default preview/boot.png)")
    args = ap.parse_args()

    font = load_font()
    gfx = load_gfx_font()
    scenes = default_scenes()
    if args.no_splash:
        scenes = [s for s in scenes if not s.splash]

    panels: list[tuple[str, Canvas]] = []
    failed = False
    print(f"\nboot ({len(scenes)} panels) -> {args.out}")
    print(f"  {'#':>2}  {'scene':<26} {'ssid':<20} {'ip':<14} "
          f"{'printers':>8}  {'ink bbox':<14} result")
    for i, sc in enumerate(scenes):
        c = Canvas(font, gfx)
        if sc.splash:
            draw_splash(c, gfx)
            errs = []
            bbox = c.ink_bbox()
            if bbox and (bbox[0] < 0 or bbox[2] >= W or bbox[1] < 0 or
                         bbox[3] >= H):
                errs.append(f"ink bbox {bbox} leaves the panel")
        else:
            draw_boot(c, sc)
            errs = check_scene(c, sc)
        failed |= bool(errs)
        bbox = c.ink_bbox()
        bb = f"{bbox[0]}..{bbox[2]} {bbox[1]}..{bbox[3]}" if bbox else "-"
        shown = "-" if sc.splash else f"{len(sc.printers)}"
        cut = ("" if sc.splash or len(sc.printers) <= visible_printers()
               else f" ({visible_printers()} shown)")
        print(f"  {i + 1:>2}  {sc.label:<26} {sc.ssid or '-':<20} "
              f"{sc.ip or '-':<14} {shown:>8}  {bb:<14} "
              f"{'OK' if not errs else 'FAIL: ' + '; '.join(errs)}{cut}")
        panels.append((sc.label, c))

    for w in firmware_drift_warnings():
        print(f"warning: {w}", file=sys.stderr)

    cols = args.cols or auto_cols(len(panels))
    write_sheet(args.out, panels, font, max(1, args.scale), max(1, cols),
                args.gap)
    print(f"\nwrote {args.out}  ({len(panels)} panels, {args.scale}x, "
          f"{max(1, cols)} column(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
