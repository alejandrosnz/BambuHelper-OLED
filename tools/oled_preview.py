#!/usr/bin/env python3
"""Shared layer for the SH1106 pixel previews (standard library only).

`render_idle_preview.py` (idle clock) and `render_status_preview.py`
(printing/pause/done) both replay firmware draw calls against a 128x64 canvas
and then write a captioned contact sheet. This module holds the parts they have
in common so there is exactly one copy:

  * the classic glcdfont and the GFX font loader (real glyph metrics from
    .pio/libdeps),
  * an Adafruit_GFX subset (default + GFX font, bitmaps, lines/rects, and
    getTextBounds with wrap disabled, which is what the firmware runs),
  * the XBM table reader used for the hand-drawn icons in the sources,
  * the grayscale PNG sheet writer with per-panel captions and the 1 px gray
    panel frame drawn outside the 128x64 area.

No Pillow: the PNG is built with zlib/struct so the tools run anywhere the
repo does.
"""

from __future__ import annotations

import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 128, 64


# --- Classic font -------------------------------------------------------------
def find_font() -> Path:
    candidates = sorted(ROOT.glob(".pio/libdeps/*/*/glcdfont.c"))
    if not candidates:
        sys.exit("glcdfont.c not found: run `pio run` (or `pio pkg install`) "
                 "once so PlatformIO downloads Adafruit GFX.")
    return candidates[0]


def load_font() -> bytes:
    src = find_font().read_text(encoding="utf-8", errors="ignore")
    body = src[src.index("{") + 1:src.rindex("}")]
    data = bytes(int(x, 16) for x in re.findall(r"0[xX]([0-9a-fA-F]{2})", body))
    if len(data) < 256 * 5:
        sys.exit(f"unexpected glcdfont.c size: {len(data)} bytes")
    return data


# --- GFX font -----------------------------------------------------------------
class GfxFont:
    """Just enough of the GFXfont struct: bitmaps + per-glyph metrics."""

    def __init__(self, bitmaps: bytes, glyphs: list[tuple], first: int,
                 last: int, y_advance: int):
        self.bitmaps = bitmaps
        self.glyphs = glyphs
        self.first = first
        self.last = last
        self.y_advance = y_advance

    def glyph(self, ch: int):
        if not (self.first <= ch <= self.last):
            return None
        return self.glyphs[ch - self.first]


def load_gfx_font(name: str = "FreeMonoBold9pt7b") -> GfxFont:
    hits = sorted(ROOT.glob(f".pio/libdeps/*/*/Fonts/{name}.h"))
    if not hits:
        sys.exit(f"{name}.h not found: run `pio run` so PlatformIO downloads "
                 "Adafruit GFX.")
    src = hits[0].read_text(encoding="utf-8", errors="ignore")

    bm = re.search(rf"{name}Bitmaps\[\][^=]*=\s*\{{(.*?)\}};", src, re.S)
    gl = re.search(rf"{name}Glyphs\[\][^=]*=\s*\{{(.*?)\}};", src, re.S)
    fn = re.search(rf"GFXfont\s+{name}\s+PROGMEM\s*=\s*\{{.*?,.*?,\s*"
                   rf"(0[xX][0-9a-fA-F]+|\d+)\s*,\s*"
                   rf"(0[xX][0-9a-fA-F]+|\d+)\s*,\s*(\d+)\s*\}}", src, re.S)
    if not (bm and gl and fn):
        sys.exit(f"could not parse {hits[0]}")
    bitmaps = bytes(int(x, 16) for x in re.findall(r"0[xX]([0-9a-fA-F]{2})",
                                                   bm.group(1)))
    glyphs = [tuple(int(v) for v in m) for m in re.findall(
        r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,"
        r"\s*(-?\d+)\s*,\s*(-?\d+)\s*\}", gl.group(1))]
    first, last, y_adv = (int(fn.group(1), 0), int(fn.group(2), 0),
                          int(fn.group(3)))
    if len(glyphs) != last - first + 1:
        sys.exit(f"glyph table mismatch in {hits[0]}: "
                 f"{len(glyphs)} glyphs for 0x{first:02x}..0x{last:02x}")
    return GfxFont(bitmaps, glyphs, first, last, y_adv)


def load_xbm(path: Path, symbol: str) -> bytes:
    """Read an XBM table out of a C/C++ source file (NZL_BMP, ...)."""
    src = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(rf"{symbol}\s*\[\][^=]*=\s*\{{(.*?)\}};", src, re.S)
    if not m:
        sys.exit(f"{symbol} not found in {path}")
    return bytes(int(t, 16) for t in re.findall(r"0[xX]([0-9a-fA-F]{2})",
                                                m.group(1)))


# --- Canvas -------------------------------------------------------------------
class Canvas:
    """The slice of Adafruit_GFX the mono renderer uses, plus draw tracing."""

    def __init__(self, classic: bytes, gfx: GfxFont | None = None):
        self.font_bytes = classic
        self.gfx = gfx
        self.font: GfxFont | None = None
        self.size = 1
        self.cx = 0
        self.cy = 0
        self.oob = 0          # pixels written outside 0..127 / 0..63
        self.p = [[0] * W for _ in range(H)]

    # -- state, same names as the Arduino calls used by the renderer --
    def setFont(self, font: GfxFont | None = None) -> None:
        self.font = font

    def setTextSize(self, size: int) -> None:
        self.size = size

    def setCursor(self, x: int, y: int) -> None:
        self.cx, self.cy = x, y

    def clear(self) -> None:
        self.p = [[0] * W for _ in range(H)]
        self.oob = 0

    # -- primitives --
    def _put(self, x: int, y: int) -> None:
        if 0 <= x < W and 0 <= y < H:
            self.p[y][x] = 1
        else:
            self.oob += 1

    def drawPixel(self, x: int, y: int) -> None:
        self._put(x, y)

    def drawFastHLine(self, x: int, y: int, w: int) -> None:
        for i in range(w):
            self._put(x + i, y)

    def drawFastVLine(self, x: int, y: int, h: int) -> None:
        for i in range(h):
            self._put(x, y + i)

    def drawLine(self, x0: int, y0: int, x1: int, y1: int) -> None:
        # Adafruit_GFX::drawLine, verbatim (Bresenham, integer halving).
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0 = y0, x0
            x1, y1 = y1, x1
        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        dx, dy = x1 - x0, abs(y1 - y0)
        err = dx // 2
        ystep = 1 if y0 < y1 else -1
        while x0 <= x1:
            if steep:
                self._put(y0, x0)
            else:
                self._put(x0, y0)
            err -= dy
            if err < 0:
                y0 += ystep
                err += dx
            x0 += 1

    def drawTriangle(self, x0: int, y0: int, x1: int, y1: int, x2: int,
                     y2: int) -> None:
        self.drawLine(x0, y0, x1, y1)
        self.drawLine(x1, y1, x2, y2)
        self.drawLine(x2, y2, x0, y0)

    def drawCircle(self, x0: int, y0: int, r: int) -> None:
        # Adafruit_GFX::drawCircle, verbatim (midpoint circle, 8 octants).
        f = 1 - r
        ddF_x = 1
        ddF_y = -2 * r
        x = 0
        y = r
        self._put(x0, y0 + r)
        self._put(x0, y0 - r)
        self._put(x0 + r, y0)
        self._put(x0 - r, y0)
        while x < y:
            if f >= 0:
                y -= 1
                ddF_y += 2
                f += ddF_y
            x += 1
            ddF_x += 2
            f += ddF_x
            self._put(x0 + x, y0 + y)
            self._put(x0 - x, y0 + y)
            self._put(x0 + x, y0 - y)
            self._put(x0 - x, y0 - y)
            self._put(x0 + y, y0 + x)
            self._put(x0 - y, y0 + x)
            self._put(x0 + y, y0 - x)
            self._put(x0 - y, y0 - x)

    def drawRect(self, x: int, y: int, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            return
        self.drawFastHLine(x, y, w)
        self.drawFastHLine(x, y + h - 1, w)
        self.drawFastVLine(x, y, h)
        self.drawFastVLine(x + w - 1, y, h)

    def fillRect(self, x: int, y: int, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            return
        for j in range(h):
            for i in range(w):
                self._put(x + i, y + j)

    def drawBitmap(self, x: int, y: int, data: bytes, w: int, h: int) -> None:
        stride = (w + 7) // 8
        for j in range(h):
            for i in range(w):
                if data[j * stride + i // 8] & (0x80 >> (i % 8)):
                    self._put(x + i, y + j)

    # -- text --
    def print(self, text: str) -> None:
        if not text:
            return
        if self.font is None:
            # Classic font: 5 columns per glyph, bit 0 = top row, 6*size advance.
            x = self.cx
            for ch in text:
                base = (ord(ch) & 0xFF) * 5
                for i in range(5):
                    col = self.font_bytes[base + i]
                    for j in range(8):
                        if col & (1 << j):
                            for a in range(self.size):
                                for b in range(self.size):
                                    self._put(x + i * self.size + a,
                                              self.cy + j * self.size + b)
                x += 6 * self.size
            self.cx = x
            return
        size = self.size
        for ch in text:
            g = self.font.glyph(ord(ch) & 0xFF)
            if g is None:
                continue
            off, gw, gh, xa, xo, yo = g
            for yy in range(gh):
                for xx in range(gw):
                    bit = yy * gw + xx
                    if self.font.bitmaps[off + bit // 8] & (0x80 >> (bit % 8)):
                        self._put(self.cx + xo * size + xx * size,
                                  self.cy + yo * size + yy * size)
            self.cx += xa * size

    def getTextBounds(self, text: str, x: int = 0,
                      y: int = 0) -> tuple[int, int, int, int]:
        """Adafruit_GFX::getTextBounds/charBounds with wrap disabled."""
        if not text:
            return (x, y, 0, 0)
        minx, miny, maxx, maxy = 0x7FFF, 0x7FFF, -1, -1
        if self.font is None:
            for _ in text:
                x2, y2 = x + 6 * self.size - 1, y + 8 * self.size - 1
                maxx, maxy = max(maxx, x2), max(maxy, y2)
                minx, miny = min(minx, x), min(miny, y)
                x += 6 * self.size
        else:
            for ch in text:
                g = self.font.glyph(ord(ch) & 0xFF)
                if g is None:
                    continue
                _, gw, gh, xa, xo, yo = g
                x1 = x + xo * self.size
                y1 = y + yo * self.size
                x2 = x1 + gw * self.size - 1
                y2 = y1 + gh * self.size - 1
                minx, miny = min(minx, x1), min(miny, y1)
                maxx, maxy = max(maxx, x2), max(maxy, y2)
                x += xa * self.size
        if maxx >= minx:
            x1, w = minx, maxx - minx + 1
        else:
            x1, w = x, 0
        if maxy >= miny:
            y1, h = miny, maxy - miny + 1
        else:
            y1, h = y, 0
        return (x1, y1, w, h)

    def ink_bbox(self) -> tuple[int, int, int, int] | None:
        xs = [x for y in range(H) for x in range(W) if self.p[y][x]]
        ys = [y for y in range(H) if any(self.p[y])]
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))


# --- PNG sheet ------------------------------------------------------------------
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _draw_label(img: list[list[int]], x: int, y: int, text: str,
                font: bytes, px: int) -> None:
    for ch in text:
        base = (ord(ch) & 0xFF) * 5
        for i in range(5):
            col = font[base + i]
            for j in range(8):
                if col & (1 << j):
                    for a in range(px):
                        for b in range(px):
                            yy, xx = y + j * px + a, x + i * px + b
                            if 0 <= yy < len(img) and 0 <= xx < len(img[0]):
                                img[yy][xx] = 0
        x += 6 * px


def _wrap_caption(text: str, max_chars: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= max_chars:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def auto_cols(n: int) -> int:
    """Panels per row when the caller does not pick one."""
    return 4 if n > 9 else 3 if n > 4 else n


def write_sheet(path: Path, panels: list[tuple[str, Canvas]], font: bytes,
                scale: int, cols: int, gap: int) -> None:
    """Grayscale contact sheet, stdlib only, 1 px gray frame around each panel."""
    scale = max(1, scale)
    cap_px = max(2, scale // 2 + 1)
    cell_w = (W + 2) * scale
    max_chars = max(12, (cell_w - 2 * scale) // (6 * cap_px))
    captions = [_wrap_caption(f"{i + 1}. {label}", max_chars)
                for i, (label, _) in enumerate(panels)]
    max_lines = max(len(c) for c in captions)
    cap_line_h = 9 * cap_px
    cap_h = max_lines * cap_line_h + 2 * cap_px
    cell_h = (H + 2) * scale + cap_h
    rows = (len(panels) + cols - 1) // cols
    pad = 3 * scale
    width = 2 * pad + cols * cell_w + (cols - 1) * gap
    height = 2 * pad + rows * cell_h + (rows - 1) * gap
    img = [[255] * width for _ in range(height)]

    for k, (_, canvas) in enumerate(panels):
        col, row = k % cols, k // cols
        ox = pad + col * (cell_w + gap) + scale
        oy = pad + row * (cell_h + gap) + scale
        for y in range(H):
            for x in range(W):
                if canvas.p[y][x]:
                    for a in range(scale):
                        for b in range(scale):
                            img[oy + y * scale + a][ox + x * scale + b] = 0
        top, bottom = oy - 1, oy + H * scale
        left, right = ox - 1, ox + W * scale
        for x in range(left, right + 1):
            img[top][x] = 170
            img[bottom][x] = 170
        for y in range(top, bottom + 1):
            img[y][left] = 170
            img[y][right] = 170
        ty = oy + H * scale + scale + 2 * cap_px
        for line in captions[k]:
            _draw_label(img, ox, ty, line, font, cap_px)
            ty += cap_line_h

    raw = b"".join(b"\x00" + bytes(r) for r in img)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" +
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0,
                                        0, 0)) +
        _png_chunk(b"IDAT", zlib.compress(raw, 9)) +
        _png_chunk(b"IEND", b""))
