# AGENTS.md

Working notes for AI agents (and humans) touching **BambuHelper-OLED**. Read this
before editing code, and follow the approval loop at the end for anything that
changes what the OLED draws.

## What this repo is

Firmware for an **ESP32-C3 SuperMini + SH1106 128x64 monochrome OLED over I2C**.
It reads a Bambu Lab printer over LAN MQTT or Bambu Cloud, renders the state on
the panel, serves a configuration portal and supports OTA updates.

- Single PlatformIO environment: `sh1106_esp32c3` (`pio run` is enough).
- The colour-display layer (LovyanGFX gauges, cards, edge glow) is **not
  compiled** into this build. `src/display_mono.cpp` implements the small slice
  of that API the core still calls. Do not "fix" mono behaviour there.
- The real renderer is `src/mono_display.cpp` (Adafruit_SH1106G + Adafruit GFX).

## Non-negotiable rules

1. **Never break NVS compatibility.** Settings live in NVS with explicit keys
   (`dsp_*`, `mno_*`, `net_*`, `dp_*`). Do not rename keys, reorder/repurpose
   fields, or delete persisted fields just because the mono UI does not use them.
   `DisplaySettings` still carries colour/round-display fields on purpose.
2. **No C++ exceptions.** The build uses `-fno-exceptions`. Never add
   `try`/`catch`/`throw`; use `new (std::nothrow)` and check the pointer.
3. **Flash is tight** (~80% of the 1.75 MB OTA slot). Prefer `F("...")` for log
   strings, `PROGMEM` for tables, and avoid duplicating literals. `pio run`
   prints the real numbers; a PR fails if the image stops fitting.
4. **Match the surrounding style**: 2-space indent, `static` for file-local
   helpers, comments that explain *why* (not what), English identifiers and web
   strings. Keep the existing naming (`dispSettings`, `monoSettings`,
   `netSettings`, `dpSettings`).
5. **Respect user work.** Never revert uncommitted files you did not create;
   inspect `git status`/`git diff` first.
6. **Layout changes need explicit approval** from the user, with a preview. See
   [The approval loop](#the-approval-loop-ui-changes).

## Build, flash, test

```bash
pio run                         # build the default env
pio run -t upload               # USB flash
pio run -t monitor              # serial console, 115200 baud
python tools/release.py         # package the OTA asset for the current version
python tools/release.py --skip-build   # reuse .pio/build/sh1106_esp32c3
```

If `pio` is not on `PATH` (common on this Windows machine):

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run
```

The build must end in `SUCCESS` and show RAM/flash usage. On the C3, hold
**BOOT** while plugging in if the upload cannot connect.

There is no unit-test suite. The gates are:

1. `pio run` compiles and the image still fits.
2. `tools/render_idle_preview.py` for idle-screen layout work and
   `tools/render_status_preview.py` for printing/pause/done.
3. On-device check through the serial `mock` commands (below).

### Mock mode (no printer needed)

`MONO_MOCK` is enabled by default (`src/mono_display.h`). Over the serial monitor:

```
mock            help
mock 0..8       pin a screen (0 print 0%, 1 print 50%, 2 long title/marquee,
                3 pause, 4 done, 5 error, 6 cold idle, 7 hot idle, 8 offline)
mock cycle      rotate all screens every 3 s
mock off        back to the real printer
mock w10d       force a demo weather icon (empty "mock w" clears it)
```

Use `mock 6`/`mock 7` for the idle clock and `mock w<code>` for the weather row.
This is the only way to see the real panel without a printer.

## Repo map

| Path | What lives there |
|---|---|
| `src/main.cpp` | Setup/loop, WiFi, MQTT, web server, splash/state transitions |
| `src/mono_display.cpp` | **All SH1106 rendering**, screen selection, change detection, mock mode |
| `src/mono_display.h` | Renderer API + tunable `MONO_*` constants |
| `src/display_mono.cpp` | No-op shim for the colour-display API on mono builds |
| `src/mono_weather.cpp` / `.h` | OpenWeatherMap fetch/cache, demo icon |
| `include/mono_weather_icons.h` | Twelve 30x30 icons + 8x10 degree bitmap |
| `src/settings.h` / `.cpp` | Setting structs, NVS load/save, defaults |
| `include/web_pages.h` | Portal HTML in raw literals with `%TOKEN%` placeholders |
| `src/web_template.cpp` | Streams the page and resolves `%TOKEN%` |
| `src/web_server.cpp` | Form/toggle handlers, JSON backup/restore, OTA, APIs |
| `web/app.js` / `web/app.css` | Portal assets, gzipped at build time |
| `tools/gen_web_assets.py` | Pre-build step: gzip assets into PROGMEM |
| `tools/oled_preview.py` | Shared preview layer: fonts, GFX canvas, PNG sheets |
| `tools/render_idle_preview.py` | Pixel preview of the idle screen |
| `tools/render_status_preview.py` | Pixel preview of the printing/pause/done screens |
| `tools/release.py` | OTA packaging + slot-size check |
| `img/preview/` | Committed preview snapshots (regenerate after layout changes) |
| `include/config.h` | `FW_VERSION`, board/feature defaults |

## How a setting is wired (end to end)

Example used throughout: the idle-screen **date format / hide date**. Copy this
path for any new setting.

1. **Struct field** — `src/settings.h`
   - `netSettings.dateFormat` (0..5), `dispSettings.hideClockDate`.
   - Pick the struct by ownership: network/clock → `NetworkSettings`; panel
     behaviour → `DisplaySettings`; mono-only row toggles → `MonoDisplaySettings`.
2. **Default** — `src/settings.cpp`
   - `DisplaySettings`: `defaultDisplaySettings()`.
   - `NetworkSettings` / `MonoDisplaySettings`: the default is the second
     argument of the `prefs.getX("key", default)` call in `loadSettings()`.
   - `resetSettings()` only wipes NVS and reboots, so defaults live in the
     loaders.
3. **NVS load/save** — `loadSettings()` / `saveSettings()` in `src/settings.cpp`
   with a new key (follow the `dsp_*` / `net_*` / `mno_*` prefix).
4. **HTML control** — `include/web_pages.h`: add the input/select and put a
   `%TOKEN%` where the state goes (`checked`, `selected`, `value`). Keep the
   comment block at the top of the file in sync; it lists every posted field.
5. **Token resolver** — `src/web_template.cpp`, `resolvePlaceholder()`:
   return the current state for the token (see `DATEFMT0..5`,
   `CLK_HIDEDATE`).
6. **Form reader** — `src/web_server.cpp`, `readDisplayFromForm()` for values
   posted with the Save/Apply form (use `server.hasArg`), or
   `handleToggleSetting()` for checkboxes that save instantly (add a short key
   such as `clkhd`).
7. **JS** — `web/app.js`: read/write the control in `applyDisplay()` (and
   `applyTheme()` if it is a colour). `tools/gen_web_assets.py` re-gzips it on
   the next build, so no manual step.
8. **Consume it** in `src/mono_display.cpp`.
9. **Repaint**: if the value changes pixels but is not part of `BambuState`,
   either add it to `monoFlagsNow()` or add a field to `MonoSig` + `makeSig()` +
   `sigSame()`. Otherwise the screen keeps the old frame until something else
   changes.
10. **Backup/restore** — `handleSettingsExport()` and the import path in
    `src/web_server.cpp` (`disp[...]`, `net[...]`). Skip only if the setting is
    explicitly device-local.
11. **Docs** — README tables/cards and the hint under the control.

### Portal gotchas

- `include/web_pages.h` is one big raw string: `%TOKEN%` is substituted by the
  device. Do not use `%` freely inside inline CSS/JS unless it is a real token.
- `web/app.js` and `web/app.css` are separate files; the page references them
  with cache-busting hashes generated from their bytes.
- Every OLED control saves immediately. A toggle handler must call
  `saveSettings()` (or the existing helper) and trigger a repaint when needed.

## The renderer

`src/mono_display.cpp`:

- `monoDisplayTick()` picks the screen, applies the 1 s static / ~10 fps
  marquee-blink cadence, and runs mock mode.
- One function per screen: `renderPrinting`, `renderFinish`, `renderIdle`,
  `renderFailed`, `renderOffline`, `renderPrepare`, `renderBootScreen`. Each
  starts with `oled.clearDisplay()` and **must end with `oled.display()`**.
- `renderNow()` is the only dispatcher; add a new screen there.
- `MonoSig` is the change detector. Add every field that can change pixels
  without changing `BambuState` (time, weather, toggles, date format...).
- Text goes through `monoCleanJobName()` / `wrapJobName2Lines()`; the GFX fonts
  have no accents, so transliteration is deliberate.

### OLED metrics (SH1106 128x64)

- Origin top-left. `oled.setCursor(x, y)` puts **y at the top of the text cell**,
  not the baseline.
- Default font: 5x7 glyph in a 6x8 cell. `setTextSize(s)` scales both; advance is
  `6*s` px per char, visible glyph height `7*s`, cell height `8*s` (last row
  blank).
- `FreeMonoBold9pt7b` (titles) is a real GFX font: cursor y is the baseline.
- Useful sizes: size 1 = 7 px glyph, size 2 = 14 px, size 3 = 21 px (the big
  clock). At size 2 only **10 characters** fit (120 px); at size 1, 21.
- Weather icons are 30x30 but the bitmaps include blank padding rows top/bottom;
  "touching" the edge visually still leaves 1-2 px of internal padding.
- The status icon is an 8x8 box at `(116, 56)`; keep new content out of it.
- `ntpOk()` gates the clock: without NTP the panel shows `--:--` and no date.
- Tunables (`MONO_REFRESH_MS`, `MONO_MAX_CHAR_TITLE_PER_LINE`,
  `MONO_HOT_THRESHOLD_C`, ...) are documented in `src/mono_display.h`.

Current idle layout (date visible, weather on):

```
date    row 0        size 2 (falls back to 1 for formats 4/5)
clock   y = 18       size 3, 18 px of ink  -> 18..35
weather icon y = 36  30x30 cell (ink inside 64; bottom 2 rows are blank)
weather temp y = 44  size 2
```

The weather temperature uses the unit letter from **Weather in °F** (default
`C`). A 3-digit reading (`100` in °F) would run the unit letter into the corner
status icon, so the temp block starts at `x = 56` instead of `60`.

With the date visible but the weather off, the date sits near the top edge
(`dateY = 7`) with a 10 px ink gap to the clock (`y = 29` for a size-2 date,
`y = 23` for the size-1 fallback).

With the date hidden the original anchors are frozen: clock `y=5` (weather on) or
`y=20` (weather off), icon `y=32`, temp `y=40`. Do not move them.

## Previewing the layout

Both preview tools share `tools/oled_preview.py`: the **real** `glcdfont.c` and
`FreeMonoBold9pt7b` loaders from `.pio/libdeps`, an Adafruit_GFX subset
(default + GFX fonts, bitmaps, lines, circles, `getTextBounds`), the XBM reader
and the captioned PNG sheet writer (standard library only, no Pillow). They
replay the firmware draw calls, print a per-panel table (coordinates, ink bbox,
`OK`/`FAIL`) and exit non-zero if a pixel leaves the panel.

`tools/render_idle_preview.py` covers the clock and the clock-off big-temps
fallback:

```bash
python tools/render_idle_preview.py                  # full tour -> preview/idle.png
python tools/render_idle_preview.py --all-formats    # one panel per date format
python tools/render_idle_preview.py --hide-date      # time-only anchors
python tools/render_idle_preview.py --status wifi    # corner icon: off|ok|offline|wifi
python tools/render_idle_preview.py --no-weather --12h --ampm AM
python tools/render_idle_preview.py --icon 10n --temp -3 --time 09:05
python tools/render_idle_preview.py --unit F            # °F unit + 3-digit case
python tools/render_idle_preview.py --scale 8 --cols 2 --out /tmp/idle.png
```

- Default sheet: date+clock+weather, date+clock, clock+weather, clock only,
  clock off (big temps), clock off + HOT + status X, weather missing, no NTP,
  12h + AM/PM.
- `--hide-date` / `--no-weather` narrow the sheet to the matching states.
- `--gap` is in output pixels (default 24), same as the status tool; `--scale`
  is output pixels per OLED pixel (default 5).
- The 1 px gray frame is drawn **outside** the 128x64 area: it marks the panel
  bounds without covering pixels.
- The script mirrors `renderIdle()` constants. It warns when the firmware
  constants drift; if you move a block, update both.
- It models the idle screen only; `tools/render_status_preview.py` does the
  printing, pause and done screens. For another screen, add a scene to one of
  the scripts instead of eyeballing the code.

`tools/render_status_preview.py` replays `renderPrinting()` (both pause blink
frames) and `renderFinish()` with the real `FreeMonoBold9pt7b` glyphs, the real
`NZL_BMP`/`BED_BMP` icons and a curated set of states. It writes a captioned
contact sheet, prints a per-panel table (wrapped title lines, stage/ETA, ink
bbox) and exits non-zero if a pixel leaves the panel.

```bash
python tools/render_status_preview.py                  # both -> preview/printing.png + done.png
python tools/render_status_preview.py --screen printing
python tools/render_status_preview.py --matrix         # every OLED toggle combo
python tools/render_status_preview.py --scale 6 --cols 2
```

- Curated printing sheet: 0/50/73/87/100 %, 1-line / 2-line / hard-cut titles,
  pause with the bar fill drawn and blinking empty, no data, no NTP, remaining
  vs ETA, midnight `+1`, a truncated stage, and each of `showLayer`, `showBar`,
  `showTimePrinting` and `showTimeAlt` off.
- Curated done sheet: temps off/on, targets 0 vs set, 3-digit values, 1-line /
  2-line / overflow titles and a non-Latin (empty) title.

### Committed snapshots (`img/preview/`)

The approved sheets are kept in `img/preview/` so a layout can be checked
without rebuilding. After a layout change is approved, regenerate and commit
them in the same commit:

```bash
python tools/render_idle_preview.py --out img/preview/idle.png
python tools/render_status_preview.py --out-dir img/preview   # printing.png + done.png
```

- `preview/` is git-ignored scratch space; `img/preview/` is the committed set.
- `--matrix` writes `preview/<screen>-matrix.png`: toggle cross-products for
  debugging, not documentation. Do not commit those.

## The approval loop (UI changes)

The panel is tiny and the user has a clear mental picture of it. Do not guess.

1. Read the renderer and list every state the change affects (date hidden/shown,
   weather on/off, 12/24 h, long/short date, NTP down...).
2. Make the change. Build (`pio run`).
3. Render a preview for **each affected state** and open it in the Review pane
   (`browser.preview` with the absolute PNG path). Do not just describe it.
4. In the reply, state the exact coordinates you used and what stayed untouched
   (especially any anchor the user said was already fine).
5. Ask for explicit approval ("¿te vale así?"). **Do not flash, commit or push
   until the user says yes.**
6. After approval, flash or let the user flash, then verify with `mock` on the
   real panel and report back. If the hardware differs from the preview, fix the
   preview too.
7. Never silently nudge "one pixel" after approval: that is a new change and
   needs a new preview.

## Versioning and releases

- `FW_VERSION` lives in `include/config.h`. Normal PRs do **not** bump it; CI
  only builds and packages (`pio run` + `tools/release.py --skip-build`).
- Releases run through `.github/workflows/release.yml` (or the local flow in the
  README): bump `FW_VERSION`, build, package, tag `vX.Y.Z`, upload
  `BambuHelper-OLED-sh1106_esp32c3-vX.Y.Z-ota.bin`.
- Asset naming is load-bearing: the portal's online updater only accepts
  `BambuHelper-OLED-<board>-<version>-ota.bin`.

## Definition of done

- [ ] `pio run` succeeds and the image still fits.
- [ ] New setting wired through NVS, portal, backup and renderer.
- [ ] Repaint trigger added (`MonoSig`/`monoFlagsNow`) if pixels change.
- [ ] Preview rendered for every affected state and approved by the user.
- [ ] `img/preview/` snapshots regenerated and committed with the change.
- [ ] Checked on hardware with `mock` (or explicitly left to the user).
- [ ] README / portal hint updated if user-visible behaviour changed.
- [ ] No NVS key renamed, no exceptions introduced, no user work reverted.
