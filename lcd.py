"""
lcd.py - draws the classic machines' displays: dot-matrix character LCDs (MPC60, MPC3000, SP-1200) and a small graphic
LCD (MPC2000XL), with their backlight colours, faint unlit dots, inverted fields and a blinking cursor.

The 6 x 9 dot font is the public-domain X11 "misc" 6x9 bitmap font (ASCII 32-126), baked in below as hex so nothing has
to be installed. Two extra glyphs: chr(1) = a quarter note, chr(2) = a solid block.
"""
import time
import numpy as np
from PIL import Image

CW, CH = 6, 9                                    # character cell, in dots
BLINK_PERIOD, BLINK_ON = 1.0, 0.5                # cursor blink: one on/off cycle a second, half of it lit (by ear and eye
                                                 # from the real machines, not a measured spec: change here if it feels off)
CLOCK = time.monotonic                           # what the blink follows; a video render sets this to its own timeline
_FONT_HEX = (
    "0000000000000000000008080808000800000014141400000000000014143e143e141400081c2a281c0a2a1c08102a12040812150200"
    "001824241826241a00000808080000000000000408080808080400000804040404040800000022143e14220000000008083e08080000"
    "00000000000c040408000000003e0000000000000000000c0c0000000202040810100000000c121212120c00000008180808081c0000"
    "000c120204081e0000001e040c02021c000000040c14243e040000001e101c02021c0000000c101c12120c0000001e02020408080000"
    "000c120c12120c0000000c12120e020c000000000c0c000c0c000000000c0c000c0404080000061820180600000000003e003e000000"
    "0000300c020c3000000c12020c0800080000001c242a2c201c0000000814223e22220000003c223c22223c0000000c121010120c0000"
    "001c121212121c0000001e101c10101e0000001e101c1010100000000c121016120c00000012121e1212120000001c080808081c0000"
    "000e040404241800000012141814121200000010101010101e00000022362a2a2222000000121a161212120000001c222222221c0000"
    "001c12121c10100000000c12121a160c0200001c12121c12120000000c120804120c0000003e080808080800000012121212120c0000"
    "001212121e0c0c00000022222a2a36220000002214080814220000002222140808080000001e020408101e0000001c101010101c0000"
    "001010080402020000001c040404041c000000081422000000000000000000000000003e0008040000000000000000000e12120e0000"
    "0010101c12121c00000000000e10100e00000002020e12120e00000000000c16180e000000040a081c080800000000000c12120e020c"
    "0010101c12121200000008001808081c00000004000c04040414080010101418141200000018080808081c0000000000342a2a220000"
    "0000001c12121200000000000c12120c00000000001c12121c10100000000e12120e0202000000141a101000000000000e18061c0000"
    "0008081c080a0400000000001212120e000000000012120c0c0000000000222a2a140000000000120c0c1200000000001212120e120c"
    "0000001e04081e000004080810080804000000080808080808080010080804080810000000000a140000000000"
)
_EXTRA = {1: [0x04, 0x04, 0x04, 0x04, 0x1c, 0x3c, 0x18, 0x00, 0x00],     # quarter note
          2: [0x3e] * 8 + [0x00]}                                      # block
_GLYPHS = {}


def glyph(ch):
    """9 x 6 boolean array for one character (unknown characters print as a space)"""
    c = ord(ch) if ch else 32
    g = _GLYPHS.get(c)
    if g is not None: return g
    if c in _EXTRA: rows = _EXTRA[c]
    elif 32 <= c <= 126:
        h = _FONT_HEX[(c - 32) * 18:(c - 32) * 18 + 18]
        rows = [int(h[i:i + 2], 16) for i in range(0, 18, 2)]
    else: rows = [0] * 9
    g = np.array([[(r >> (5 - x)) & 1 for x in range(CW)] for r in rows], bool)
    _GLYPHS[c] = g
    return g


class Style:
    """how a display looks: backlight, lit and unlit dots, whether each character sits in its own visible cell, and
    glow = a vacuum fluorescent display's halo around lit dots"""
    def __init__(self, bg, on, ghost, cells=False, row_h=CH, gap=True, glow=False):
        self.bg, self.on, self.ghost, self.cells, self.row_h, self.gap, self.glow = bg, on, ghost, cells, row_h, gap, glow


MPC_BLUE = Style((26, 64, 214), (226, 234, 255), (36, 76, 226))            # MPC60 / MPC3000: blue, light dots
XL_GREY = Style((156, 182, 196), (22, 30, 58), (146, 172, 188), row_h=8)    # MPC2000XL: pale, dark dots, 8-dot rows
SP_GREEN = Style((176, 196, 52), (34, 44, 12), (160, 182, 46), cells=True)  # SP-1200: yellow-green, cells visible
VFD_CYAN = Style((4, 8, 16), (128, 238, 240), (12, 24, 32), cells=True, glow=True)   # ASR-10: blue-green fluorescent


def render(lines, cols, style, k, inverse=(), cursor=None, blink=None):
    """the display as an RGB image k times its dot size.
    lines: list of strings; inverse: [(row, col, length)] drawn light-on-dark; cursor: (row, col, length), blinking"""
    rows, rh = len(lines), style.row_h
    on = np.zeros((rows * rh, cols * CW), bool)
    for r, text in enumerate(lines):
        for c, ch in enumerate(text[:cols]):
            if ch != " ": on[r * rh:(r + 1) * rh, c * CW:(c + 1) * CW] = glyph(ch)[:rh]
    blink_on = (CLOCK() / BLINK_PERIOD) % 1.0 < BLINK_ON if blink is None else blink
    spans = list(inverse) + ([cursor] if cursor and blink_on else [])
    for r, c, n in spans:
        on[r * rh:(r + 1) * rh, c * CW:(c + n) * CW] ^= True
    cellmask = None
    if style.cells:                                         # a character LCD: dots only inside each 5 x 8 cell
        cellmask = np.zeros_like(on)
        for r in range(rows):
            for c in range(cols): cellmask[r * rh:r * rh + 8, c * CW:c * CW + 5] = True
        on &= cellmask
    h, w = on.shape
    big = np.repeat(np.repeat(on, k, 0), k, 1)
    out = np.empty((h * k, w * k, 3), np.uint8)
    out[:] = style.ghost if not style.cells else style.bg
    if style.cells: out[np.repeat(np.repeat(cellmask, k, 0), k, 1)] = style.ghost
    out[big] = style.on
    if k >= 3 and style.gap:                                # a thin gap between dots, like a real LCD
        out[k - 1::k, :] = style.bg; out[:, k - 1::k] = style.bg
    img = Image.fromarray(out)
    if style.glow:                                          # fluorescent: lit dots bloom into the glass around them
        from PIL import ImageChops, ImageFilter
        halo = Image.fromarray(np.where(big[..., None], np.array(style.on, np.uint8), np.uint8(0)).astype(np.uint8))
        halo = halo.filter(ImageFilter.GaussianBlur(max(1.0, k * 0.9))).point(lambda v: int(v * 0.55))
        img = ImageChops.add(img, halo)
    return img
