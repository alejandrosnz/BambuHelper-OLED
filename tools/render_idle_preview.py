#!/usr/bin/env python3
"""Pixel preview of the SH1106 idle/clock screen (128x64).

Replays the draw calls of renderIdle() in src/mono_display.cpp using the real
Adafruit glcdfont, the real 30x30 bitmaps from include/mono_weather_icons.h and
a captioned contact sheet, so one look tells you which state is broken.

Why this exists: the panel has no antialiasing and hard 128x64 limits, so a
1-px mistake is obvious on hardware but invisible in a diff. Run this before
flashing any layout change and show the PNG to the user for approval. The
drawing layer (fonts, string bounds, PNG sheet) lives in tools/oled_preview.py
and is shared with tools/render_status_preview.py.

The constants in the LAYOUT block below MIRROR renderIdle(). If you move a
block there, move it here too, or the preview will lie. The script prints the
computed coordinates, the ink bbox of every panel and exits non-zero if
anything leaves the panel.

Usage:
    python tools/render_idle_preview.py                  # full tour -> preview/idle.png
    python tools/render_idle_preview.py --date-format 7  # long format (size-1 fallback)
    python tools/render_idle_preview.py --all-formats    # one panel per date format
    python tools/render_idle_preview.py --hide-date      # time-only anchors
    python tools/render_idle_preview.py --no-weather --12h --ampm AM
    python tools/render_idle_preview.py --status offline --scale 8

Requires the Adafruit GFX library to be installed: run `pio run` once (or
`pio pkg install`) so .pio/libdeps/<env>/.../glcdfont.c exists.

Default sheet (clock on, unless the label says otherwise):
    1. date + clock + weather   2. date + clock
    3. clock + weather          4. clock only
    5. clock off - big temps    6. clock off - HOT + status X
    7. weather missing ("--")   8. no NTP ("--:--", no date)
    9. 12h + AM/PM
--hide-date keeps only the two date-hidden states; --no-weather drops every
weather row; --all-formats draws one panel per date format; --unit F redraws
the weather block with the °F unit letter and adds the 3-digit worst case.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path

from oled_preview import (Canvas, H, ROOT, W, auto_cols, load_font,
                          load_gfx_font, load_xbm, write_sheet)

# --- LAYOUT: mirrors renderIdle() -------------------------------------------
CLOCK_SIZE = 3
CLOCK_INK_H = 6 * CLOCK_SIZE     # 18 px of ink at size 3 (glyph row 6 is blank)
CLK_PAIR_TOP = 7                 # date top edge on the date+clock screen
CLK_INK_GAP = 10                 # ink gap between the date and the clock
WX_ICON_W = WX_ICON_H = 30       # mono_weather.h
WX_ICON_TOP = 36                 # cell rows 36..65; the last 2 rows are blank
WX_ICON_X = 23
WX_TEMP_X = 60
WX_TEMP_X_3D = 56                # 3-digit reading: shifts left of the corner icon
WX_TEMP_SIZE = 2
WX_TEMP_DY = 8                   # temp baseline offset below the icon
DATE_MAX_SIZE = 2                # same scale as the weather temperature
DATE_TOP = 0
# Anchors kept for the date-hidden screen (regression guard).
CLK_Y_WX_OLD, CLK_Y_OLD = 5, 20
WX_TOP_OLD, WX_TEMP_Y_OLD = 32, 40
# Temp icons (8x9 XBM) and the fallback screen, shared with printing/done.
TEMP_ICON_W, TEMP_ICON_H = 8, 9
TEMP_ROW_Y = 32                  # icons top; values are drawn at 42 (baseline)
TEMP_VAL_Y = 42
BOTTOM_Y = 56                    # HOT warning row / status icon row
HOT_THRESHOLD_C = 50
STATUS_X, STATUS_Y = 116, 56     # 8x8 corner icon

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def ordinal_suffix(day: int) -> str:
    """English ordinal for format 7: 1st, 2nd, 3rd, 11th..13th, 21st..."""
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


ICON_BY_CODE = {
    "01d": "wi_day_clear", "01n": "wi_night_clear",
    "02d": "wi_day_cloud", "02n": "wi_night_cloud",
    "03d": "wi_cloud", "03n": "wi_cloud",
    "04d": "wi_very_cloudy", "04n": "wi_very_cloudy",
    "09d": "wi_showers", "09n": "wi_showers",
    "10d": "wi_rain", "10n": "wi_rain",
    "11d": "wi_storm", "11n": "wi_storm",
    "13d": "wi_snow", "13n": "wi_snow",
    "50d": "wi_fog", "50n": "wi_fog",
}


# --- Assets ------------------------------------------------------------------
def load_icons() -> dict[str, bytes]:
    src = (ROOT / "include" / "mono_weather_icons.h").read_text(
        encoding="utf-8", errors="ignore")
    icons: dict[str, bytes] = {}
    for m in re.finditer(
            r"const unsigned char\s+(?:PROGMEM\s+)?(\w+)\s*\[\][^=]*=\s*\{(.*?)\}",
            src, re.S):
        out = bytearray()
        for tok in re.findall(r"0[xX][0-9a-fA-F]{2}|B[01]{8}", m.group(2)):
            out.append(int(tok, 16) if tok.lower().startswith("0x")
                       else int(tok[1:], 2))
        icons[m.group(1)] = bytes(out)
    if "degree_bmp" not in icons:
        sys.exit("degree_bmp not found in include/mono_weather_icons.h")
    return icons


# --- Layout (mirrors renderIdle) ---------------------------------------------
def text_width(t: str, size: int) -> int:
    """Adafruit getTextBounds width for the default font: 6*size per char."""
    return 6 * size * len(t)


def format_date(fmt: int, d: Date) -> str:
    day, mon, year = d.day, d.month, d.year
    return (
        f"{day:02d}.{mon:02d}.{year:04d}",
        f"{day:02d}-{mon:02d}-{year:04d}",
        f"{mon:02d}/{day:02d}/{year:04d}",
        f"{year:04d}-{mon:02d}-{day:02d}",
        f"{day:02d} {MONTHS[mon - 1]} {year:04d}",
        f"{MONTHS[mon - 1]} {day:02d}, {year:04d}",
        f"{day:02d} {MONTHS[mon - 1]}",
        f"{MONTHS[mon - 1]} {day}{ordinal_suffix(day)}",
    )[fmt]


def date_scale(text: str) -> int:
    """Same rule as renderIdle: size 2, drop to size 1 only if it won't fit."""
    for size in (DATE_MAX_SIZE, 1):
        if text_width(text, size) <= W:
            return size
    return 1


@dataclass
class Scene:
    label: str
    date: str | None
    dsize: int
    date_h: int
    date_y: int
    clk_y: int
    wx: bool
    wx_top: int
    wx_temp_y: int
    clock_on: bool = True       # monoSettings.showClockIdle
    status: str = "off"         # showStatusIdle: off|ok|offline|wifi
    hot: bool = False           # monoSettings.showHotIdle (clock-off screen only)
    weather_ok: bool = True     # monoWeatherGet() returned data
    ntp: bool = True            # ntpOk(): without it the clock shows "--:--"
    twelve: bool = False        # use24h == false: centered time + AM/PM
    nozzle: int = 24            # big-temp screen (clock off)
    bed: int = 24
    temp_text: str | None = None  # per-panel weather temp override


def build_scene(label: str, date_fmt: int, hide_date: bool, wx: bool,
                day: Date, ntp: bool = True, status: str = "off",
                clock_on: bool = True, hot: bool = False,
                weather_ok: bool = True, twelve: bool = False,
                nozzle: int = 24, bed: int = 24,
                temp_text: str | None = None) -> Scene:
    extra = dict(clock_on=clock_on, status=status, hot=hot,
                 weather_ok=weather_ok, ntp=ntp, twelve=twelve,
                 nozzle=nozzle, bed=bed, temp_text=temp_text)
    if not clock_on:
        return Scene(label, None, 0, 0, 0, 0, False,
                     WX_TOP_OLD, WX_TEMP_Y_OLD, **extra)
    if hide_date or not ntp:
        # Original anchors: the date is hidden when NTP has not synced yet.
        return Scene(label, None, 0, 0, 0,
                     CLK_Y_WX_OLD if wx else CLK_Y_OLD, wx,
                     WX_TOP_OLD, WX_TEMP_Y_OLD, **extra)
    text = format_date(date_fmt, day)
    dsize = date_scale(text)
    date_h = 7 * dsize
    if wx:
        date_y = DATE_TOP
        clk_y = date_h + (WX_ICON_TOP - date_h - CLOCK_INK_H) // 2 + 2
        return Scene(label, text, dsize, date_h, date_y, clk_y, True,
                     WX_ICON_TOP, WX_ICON_TOP + WX_TEMP_DY, **extra)
    # Date + clock only: date near the top and a roomy ink gap under it.
    date_y = CLK_PAIR_TOP
    return Scene(label, text, dsize, date_h, date_y,
                 date_y + 6 * dsize + CLK_INK_GAP, False,
                 WX_TOP_OLD, WX_TEMP_Y_OLD, **extra)


# --- Rendering ---------------------------------------------------------------
def draw_status(c: Canvas, kind: str) -> None:
    """renderIdle(): the 8x8 corner icon (wifi warn / printer X / live circle)."""
    x, y = STATUS_X, STATUS_Y
    if kind == "wifi":
        c.drawTriangle(x + 3, y, x, y + 7, x + 7, y + 7)
        c.drawFastVLine(x + 3, y + 2, 3)
        c.drawPixel(x + 3, y + 6)
    elif kind == "offline":
        c.drawLine(x, y, x + 7, y + 7)
        c.drawLine(x + 7, y, x, y + 7)
    else:  # "ok": empty circle = idle and connected
        c.drawCircle(x + 4, y + 4, 3)


def draw_scene(c: Canvas, sc: Scene, gfx, time_s: str, ampm: str, temp: str,
               icon: bytes, degree: bytes,
               temp_icons: dict[str, bytes], unit: str = "C") -> None:
    c.clear()
    if sc.clock_on:
        c.setFont()
        c.setTextSize(1)
        if sc.date:
            c.setTextSize(sc.dsize)
            _, _, dw, _ = c.getTextBounds(sc.date)
            c.setCursor((W - dw) // 2, sc.date_y)
            c.print(sc.date)
            c.setTextSize(1)
        c.setTextSize(CLOCK_SIZE)
        if sc.ntp:
            clock = time_s
            if sc.twelve:
                # Centered time + AM/PM block (5-char times leave no room at x=20).
                _, _, w, _ = c.getTextBounds(clock, 20, sc.clk_y)
                x0 = max(0, (W - (w + 6 + 12)) // 2)
                c.setCursor(x0, sc.clk_y)
                c.print(clock)
                c.setTextSize(1)
                c.setCursor(x0 + w + 6, sc.clk_y + 8)
                c.print(ampm)
                c.setTextSize(CLOCK_SIZE)
            else:
                c.setCursor(20, sc.clk_y)
                c.print(clock)
        else:
            c.setCursor(20, sc.clk_y)
            c.print("--:--")
        if sc.wx:
            txt = (sc.temp_text or temp) if sc.weather_ok else "--"
            n = len(txt)
            c.drawBitmap(WX_ICON_X, sc.wx_top,
                         icon if sc.weather_ok else temp_icons["error"],
                         WX_ICON_W, WX_ICON_H)
            c.setTextSize(WX_TEMP_SIZE)
            tx = WX_TEMP_X_3D if n >= 3 else WX_TEMP_X
            c.setCursor(tx, sc.wx_temp_y)
            c.print(txt)
            deg_x = tx + 2 + n * 12
            c.drawBitmap(deg_x, sc.wx_temp_y, degree, 8, 10)
            c.setCursor(deg_x + 9, sc.wx_temp_y)
            c.print(unit)
        c.setFont()
        c.setTextSize(1)
    else:
        # Big actual temps with icons (targets rarely matter in idle).
        c.setFont(gfx)
        c.setTextSize(1)
        nb, bb = str(sc.nozzle), str(sc.bed)
        x = 0
        c.drawBitmap(x, TEMP_ROW_Y, temp_icons["nozzle"], TEMP_ICON_W,
                     TEMP_ICON_H)
        x += 11
        c.setCursor(x, TEMP_VAL_Y)
        c.print(nb)
        x += c.getTextBounds(nb)[2] + 8
        c.drawBitmap(x, TEMP_ROW_Y, temp_icons["bed"], TEMP_ICON_W,
                     TEMP_ICON_H)
        x += 12
        c.setCursor(x, TEMP_VAL_Y)
        c.print(bb)
        c.setFont()
        c.setTextSize(1)
        c.setCursor(0, BOTTOM_Y)
        if sc.hot and sc.nozzle > HOT_THRESHOLD_C:
            c.print("HOT ")
    if sc.status != "off":
        draw_status(c, sc.status)


# --- Checks ------------------------------------------------------------------
def ink_rows(data: bytes, w: int, h: int) -> tuple[int, int]:
    """First/last rows that contain a lit pixel (bitmaps carry blank padding)."""
    stride = (w + 7) // 8
    rows = [j for j in range(h)
            if any(data[j * stride + i // 8] & (0x80 >> (i % 8))
                   for i in range(w))]
    return (min(rows), max(rows)) if rows else (h, -1)


def check_scene(sc: Scene, icon: bytes, temp: str = "",
                unit: str = "C") -> list[str]:
    errs = []
    if sc.date:
        if text_width(sc.date, sc.dsize) > W:
            errs.append(f"date {sc.date!r} is {text_width(sc.date, sc.dsize)} px wide")
        if sc.date_y < 0 or sc.date_y + sc.date_h > H:
            errs.append(f"date ink rows {sc.date_y}..{sc.date_y + sc.date_h - 1} "
                        "leave the panel")
    if sc.clock_on:
        if sc.clk_y < 0 or sc.clk_y + CLOCK_INK_H > H:
            errs.append(f"clock ink rows {sc.clk_y}..{sc.clk_y + CLOCK_INK_H - 1} "
                        "leave the panel")
        if sc.date and sc.clk_y < sc.date_y + sc.date_h:
            errs.append("clock overlaps the date")
        if sc.wx:
            lo, hi = ink_rows(icon, WX_ICON_W, WX_ICON_H)
            if sc.wx_top + lo < 0 or sc.wx_top + hi > H - 1:
                errs.append(f"weather ink rows {sc.wx_top + lo}.."
                            f"{sc.wx_top + hi} leave the panel")
            if sc.status != "off":
                txt = (sc.temp_text or temp) if sc.weather_ok else "--"
                tx = WX_TEMP_X_3D if len(txt) >= 3 else WX_TEMP_X
                end = tx + 11 + len(txt) * 12 + 10  # unit glyph ink, exclusive
                if end > STATUS_X:
                    errs.append(f"weather unit ink ends at x={end}, under the "
                                "corner status icon")
    else:
        if TEMP_ROW_Y + TEMP_ICON_H > H:
            errs.append("temp icons leave the panel")
    if not sc.clock_on and sc.hot and sc.nozzle > HOT_THRESHOLD_C:
        if BOTTOM_Y + 7 > H:
            errs.append("HOT warning leaves the panel")
    return errs


def firmware_drift_warnings() -> list[str]:
    """Warn if the LAYOUT constants no longer match renderIdle()."""
    src = (ROOT / "src" / "mono_display.cpp").read_text(
        encoding="utf-8", errors="ignore")
    pairs = [
        (r"const int clkInkH\s*=\s*(\d+)", CLOCK_INK_H, "clkInkH"),
        (r"const int clkPairTop\s*=\s*(\d+)", CLK_PAIR_TOP, "clkPairTop"),
        (r"const int clkInkGap\s*=\s*(\d+)", CLK_INK_GAP, "clkInkGap"),
        (r"const int wxTop\s*=\s*(\d+)", WX_ICON_TOP, "wxTop"),
        (r"clkY = wxShown \? (\d+) : (\d+);", (CLK_Y_WX_OLD, CLK_Y_OLD),
         "date-hidden clock anchors"),
        (r"wxIconY = dateShown \? wxTop : (\d+);", WX_TOP_OLD, "old icon top"),
        (r"wxTempY = dateShown \? wxTop \+ (\d+) : (\d+);",
         (WX_TEMP_DY, WX_TEMP_Y_OLD), "weather temp offsets"),
        (r"int tx = \(n >= 3\) \? (\d+) : (\d+);",
         (WX_TEMP_X_3D, WX_TEMP_X), "weather temp x"),
        (r"const int iconX = (\d+);", STATUS_X, "idle status icon x"),
        (r"const int iconY = (\d+);", STATUS_Y, "idle status icon y"),
        (r"drawNozzleIcon\(x, 32\);\s*\n\s*x \+= (\d+);", 11,
         "clock-off nozzle icon gap"),
        (r"const int BOTTOM_Y = (\d+);", BOTTOM_Y, "BOTTOM_Y"),
    ]
    warns = []
    for pattern, expected, name in pairs:
        m = re.search(pattern, src)
        if not m:
            warns.append(f"could not find {name} in renderIdle()")
            continue
        found = tuple(int(g) for g in m.groups()) if len(m.groups()) > 1 \
            else int(m.group(1))
        if found != expected:
            warns.append(f"{name}: firmware {found} vs preview {expected}")
    return warns


# --- Scenes ------------------------------------------------------------------
def default_scenes(date_fmt: int, day: Date, status: str,
                   twelve: bool, unit: str = "C") -> list[Scene]:
    """The tour drawn by a plain run: every idle branch and OLED toggle."""
    wx_on = build_scene("date + clock + weather", date_fmt, False, True, day,
                        status=status, twelve=twelve)
    date_only = build_scene("date + clock", date_fmt, False, False, day,
                            status=status, twelve=twelve)
    clock_wx = build_scene("clock + weather", date_fmt, True, True, day,
                           status=status, twelve=twelve)
    clock_only = build_scene("clock only", date_fmt, True, False, day,
                             status=status, twelve=twelve)
    cold = build_scene("clock off - big temps", date_fmt, False, False, day,
                       clock_on=False, nozzle=24, bed=24)
    hot = build_scene("clock off - HOT + status X", date_fmt, False, False,
                      day, clock_on=False, status="offline", hot=True,
                      nozzle=62, bed=45)
    no_wx = build_scene("weather missing (--)", date_fmt, False, True, day,
                        weather_ok=False, status=status, twelve=twelve)
    no_ntp = build_scene("no NTP (--:--, no date)", date_fmt, True, True, day,
                         ntp=False, status=status)
    scenes = [wx_on, date_only, clock_wx, clock_only, cold, hot, no_wx,
              no_ntp]
    if unit == "F":
        # Worst case for the right edge: a 3-digit °F reading next to the
        # corner status icon (the block shifts 4 px left for it).
        scenes.append(build_scene("weather 3-digit (\u00b0F)", date_fmt, False,
                                  True, day, status="ok", twelve=twelve,
                                  temp_text="100"))
    if not twelve:
        # With --12h every clock panel already shows the AM/PM block.
        scenes.append(build_scene("12h + AM/PM", date_fmt, False, True, day,
                                  status=status, twelve=True))
    return scenes


# --- Main --------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render the SH1106 idle screen to a captioned PNG sheet.")
    ap.add_argument("--date-format", type=int, choices=range(8), default=0,
                    help="0=DD.MM.YYYY 1=DD-MM-YYYY 2=MM/DD/YYYY 3=YYYY-MM-DD "
                         "4=DD MMM YYYY 5=MMM DD, YYYY 6=DD MMM 7=MMM DDth "
                         "(default 0)")
    ap.add_argument("--date", type=Date.fromisoformat, default=Date(2025, 12, 31),
                    metavar="YYYY-MM-DD", help="date to render (default 2025-12-31)")
    ap.add_argument("--hide-date", action="store_true",
                    help="time-only screen: date hidden (original anchors)")
    ap.add_argument("--no-weather", action="store_true",
                    help="drop the weather row from every panel")
    ap.add_argument("--all-formats", action="store_true",
                    help="one panel per date format")
    ap.add_argument("--time", default="12:34", help="time text (default 12:34)")
    ap.add_argument("--12h", dest="twelve", action="store_true",
                    help="12-hour layout + AM/PM")
    ap.add_argument("--ampm", choices=("AM", "PM"), default="PM")
    ap.add_argument("--temp", default=None,
                    help="weather temp text (default 21 in °C, 70 in °F)")
    ap.add_argument("--unit", choices=("C", "F"), default="C",
                    help="weather unit letter (default C)")
    ap.add_argument("--icon", default="01d",
                    help="OpenWeatherMap icon code, e.g. 01d, 10n (default 01d)")
    ap.add_argument("--status", choices=("off", "ok", "offline", "wifi"),
                    default="off",
                    help="idle corner icon on the clock panels (default off)")
    ap.add_argument("--scale", type=int, default=5, help="pixels per OLED px")
    ap.add_argument("--cols", type=int, default=0,
                    help="panels per row (default: auto from panel count)")
    ap.add_argument("--gap", type=int, default=24,
                    help="gap between panels in output px (default 24)")
    ap.add_argument("--out", type=Path, default=ROOT / "preview" / "idle.png",
                    help="output PNG (default preview/idle.png)")
    args = ap.parse_args()
    if args.temp is None:
        args.temp = "70" if args.unit == "F" else "21"

    font = load_font()
    gfx = load_gfx_font()
    icons = load_icons()
    icon = icons.get(ICON_BY_CODE.get(args.icon, "wi_error"), icons["wi_error"])
    degree = icons["degree_bmp"]
    temp_icons = {
        "nozzle": load_xbm(ROOT / "src" / "mono_display.cpp", "NZL_BMP"),
        "bed": load_xbm(ROOT / "src" / "mono_display.cpp", "BED_BMP"),
        "error": icons["wi_error"],
    }

    scenes: list[Scene] = []
    if args.all_formats:
        for fmt in range(8):
            scenes.append(build_scene(f"format {fmt}", fmt, False,
                                      not args.no_weather, args.date,
                                      status=args.status, twelve=args.twelve))
    elif args.hide_date or args.no_weather:
        hides = (True,) if args.hide_date else (False, True)
        weathers = (False,) if args.no_weather else (True, False)
        for hide in hides:
            for wx in weathers:
                if hide:
                    label = "clock + weather" if wx else "clock only"
                else:
                    label = "date + clock + weather" if wx else "date + clock"
                scenes.append(build_scene(label, args.date_format, hide, wx,
                                          args.date, status=args.status,
                                          twelve=args.twelve))
    else:
        scenes = default_scenes(args.date_format, args.date, args.status,
                                args.twelve, args.unit)

    panels: list[tuple[str, Canvas]] = []
    failed = False
    print(f"\nidle ({len(scenes)} panels) -> {args.out}")
    print(f"  {'#':>2}  {'scene':<30} {'date':<13} {'sz':>2} {'d_y':>3} "
          f"{'clk_y':>5} {'wx ink':>7}  {'ink bbox':<14} result")
    for i, sc in enumerate(scenes):
        c = Canvas(font, gfx)
        draw_scene(c, sc, gfx, args.time, args.ampm, args.temp, icon, degree,
                   temp_icons, args.unit)
        errs = check_scene(sc, icon, args.temp, args.unit)
        failed |= bool(errs)
        if sc.wx:
            lo, hi = ink_rows(icon, WX_ICON_W, WX_ICON_H)
            wx_rows = f"{sc.wx_top + lo}..{sc.wx_top + hi}"
        elif not sc.clock_on:
            wx_rows = "temps"
        else:
            wx_rows = "-"
        bbox = c.ink_bbox()
        if bbox and (bbox[0] < 0 or bbox[2] >= W or bbox[1] < 0 or bbox[3] >= H):
            errs.append(f"ink bbox {bbox} leaves the panel")
        failed |= bool(errs)
        bb = f"{bbox[0]}..{bbox[2]} {bbox[1]}..{bbox[3]}" if bbox else "-"
        print(f"  {i + 1:>2}  {sc.label:<30} {sc.date or '-':<13} "
              f"{sc.dsize:>2} {sc.date_y:>3} {sc.clk_y:>5} {wx_rows:>7}  "
              f"{bb:<14} {'OK' if not errs else 'FAIL: ' + '; '.join(errs)}")
        panels.append((sc.label, c))

    warns = firmware_drift_warnings()
    for w in warns:
        print(f"warning: {w}", file=sys.stderr)

    cols = args.cols or auto_cols(len(panels))
    write_sheet(args.out, panels, font, max(1, args.scale), max(1, cols),
                args.gap)
    print(f"\nwrote {args.out}  ({len(panels)} panels, {args.scale}x, "
          f"{max(1, cols)} column(s), {args.time}"
          f"{' ' + args.ampm if any(s.twelve for s in scenes) else ''}"
          f"{', weather ' + args.icon if any(s.wx for s in scenes) else ''}"
          f"{', ' + args.unit if any(s.wx for s in scenes) else ''})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
