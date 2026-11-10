#!/usr/bin/env python3
"""brand/make_logo.py - draws the Monolith logo (an original design made for this project) from rectangles only, so it
stays crisp and cuts cleanly for the printed badge.

  python3 brand/make_logo.py            -> brand/logo.png (concept B, white on transparent; then brand/make_brand.py)
  python3 brand/make_logo.py --sheet    -> brand/logo_concepts.png (the three concepts side by side)

The mark: a tall slab, 1 : 2.4, its left edge catching the light, with one thin line across it at the golden section -
the playhead, or the line a sample is cut on. The wordmark: MONOLITH in Inter Display Bold, widely tracked; concept B
draws its I as an orange slab standing taller than the rest."""
import os, sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
WHITE, ORANGE, DARK = (238, 240, 246, 255), (255, 150, 30, 255), (14, 15, 19, 255)

from PIL import ImageFont
FONT = "/usr/share/fonts/opentype/inter/InterDisplay-Bold.otf"     # Inter (SIL Open Font Licence): only drawn into the PNG


def wordmark(d, x, y, cap, word="MONOLITH", track=0.32, fill=WHITE, i_slab=None):
    """MONOLITH set letter by letter with wide tracking; cap = cap height in px, y = the top of the capitals. i_slab: draw
    the I as a slab of that colour, standing taller than the rest. Returns the x after the last letter."""
    f = ImageFont.truetype(FONT, int(cap / 0.727))
    top = f.getbbox("H")[1]
    for k, ch in enumerate(word):
        bb = f.getbbox(ch)
        if ch == "I" and i_slab:
            w = bb[2] - bb[0]
            d.rectangle([x, y - cap * 0.55, x + w * 1.05, y + cap - 1], fill=i_slab)
        else:
            d.text((x - bb[0], y - top), ch, font=f, fill=fill)
        x += (bb[2] - bb[0]) + (track * cap if k < len(word) - 1 else 0)
    return x


def word_width(cap, word="MONOLITH", track=0.32):
    f = ImageFont.truetype(FONT, int(cap / 0.727))
    return sum(f.getbbox(c)[2] - f.getbbox(c)[0] for c in word) + track * cap * (len(word) - 1)


def slab(d, x, y, w, h, fill=WHITE, line=ORANGE, edge=True):
    d.rectangle([x, y, x + w - 1, y + h - 1], fill=fill)
    if edge: d.rectangle([x, y, x + max(2, int(w * 0.14)) - 1, y + h - 1], fill=tuple(int(v * 0.78) for v in fill[:3]) + (255,))
    ly = y + int(h * 0.382)
    d.rectangle([x - int(w * 0.22), ly, x + w - 1 + int(w * 0.22), ly + max(2, int(h * 0.035)) - 1], fill=line)


# the 8-bit wordmark: 5 x 7 pixel letters, hard square pixels, one pixel between letters; the I is an orange slab two
# pixels wide standing two pixels taller than the rest
PIX = {
    "M": ["10001", "11011", "10101", "10001", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
}
I_W, I_UP, GAP = 2, 2, 1


def pixel_width(word="MONOLITH"):
    return sum((I_W if c == "I" else 5) for c in word) + GAP * (len(word) - 1)


def pixel_word(d, x, y, p, word="MONOLITH", fill=WHITE, i_fill=ORANGE):
    """the wordmark with pixels of p px; (x, y) = the top-left of the 7-pixel capitals"""
    for ch in word:
        if ch == "I":
            d.rectangle([x, y - I_UP * p, x + I_W * p - 1, y + 7 * p - 1], fill=i_fill)
            x += (I_W + GAP) * p; continue
        for r, row in enumerate(PIX[ch]):
            for cidx, on in enumerate(row):
                if on == "1": d.rectangle([x + cidx * p, y + r * p, x + (cidx + 1) * p - 1, y + (r + 1) * p - 1], fill=fill)
        x += (5 + GAP) * p
    return x


def concept_pixel(W=1600, H=600, bg=None, fg=WHITE):
    im = Image.new("RGBA", (W, H), bg or (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    p = int(min(W * 0.86 / pixel_width(), H * 0.6 / (7 + I_UP)))
    x = (W - pixel_width() * p) // 2; y = (H - (7 + I_UP) * p) // 2 + I_UP * p
    pixel_word(d, x, y, p, fill=fg)
    return im


def concept_a(W=1600, H=600, bg=None, fg=WHITE):
    im = Image.new("RGBA", (W, H), bg or (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    cap = H * 0.22; sh = int(cap * 2.1); sw = int(sh / 2.4)
    ww = word_width(cap); gap = cap * 0.75
    x = (W - (sw + gap + ww)) / 2; y = (H - sh) / 2
    slab(d, int(x), int(y), sw, sh, fill=fg)
    wordmark(d, x + sw + gap, y + sh - cap, cap, fill=fg)
    return im


def concept_b(W=1600, H=600, bg=None, fg=WHITE):
    im = Image.new("RGBA", (W, H), bg or (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    cap = H * 0.24
    x = (W - word_width(cap)) / 2
    wordmark(d, x, (H - cap) / 2 + cap * 0.25, cap, fill=fg, i_slab=ORANGE)
    return im


def concept_c(W=1600, H=600, bg=None, fg=WHITE):
    im = Image.new("RGBA", (W, H), bg or (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    sh = int(H * 0.78); sw = int(sh / 2.4)
    slab(d, int((W - sw) / 2), int((H - sh) / 2), sw, sh, fill=fg)
    return im


if __name__ == "__main__":
    if "--sheet" in sys.argv:
        tiles = []
        for name, fn in (("8-BIT  pixel wordmark, the I as an orange slab", concept_pixel), ("B  wordmark, the I as a slab", concept_b), ("A  mark + wordmark", concept_a)):
            dark = Image.new("RGBA", (1600, 600), DARK); dark.alpha_composite(fn(fg=WHITE))
            light = Image.new("RGBA", (1600, 600), (236, 236, 232, 255)); light.alpha_composite(fn(fg=DARK))
            tiles.append((name, dark, light))
        sheet = Image.new("RGB", (1600 * 2 + 60, 3 * 660 + 20), (30, 31, 36)); d = ImageDraw.Draw(sheet)
        for k, (name, dk, lt) in enumerate(tiles):
            y = 20 + k * 660
            sheet.paste(dk.convert("RGB"), (20, y + 40)); sheet.paste(lt.convert("RGB"), (1640, y + 40))
            from PIL import ImageFont
            d.text((24, y + 4), name, font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26), fill=(220, 222, 230))
        sheet.save(os.path.join(HERE, "logo_concepts.png")); print("wrote brand/logo_concepts.png")
    else:
        im = concept_pixel(2400, 900); im.crop(im.getbbox()).save(os.path.join(HERE, "logo.png")); print("wrote brand/logo.png")
