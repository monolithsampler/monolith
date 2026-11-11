import math
"""skin.py - the look of Monolith's screens ("graphite": neo-skeuomorphic hardware - raised keys, recessed wells, machined
knobs, glass displays). Everything here is a sprite: drawn once, supersampled (so edges are smooth, unlike Pillow's own
shapes), cached, then pasted every frame - cheap enough for the Pi. Sizes are in screen pixels.

The accent colour follows the machine (the "chameleon" chassis): MODERN orange, the MPCs blue, the SP-1200 green-yellow,
the ASR-10 teal. Fonts: Inter (bundled in fonts/, SIL Open Font Licence), and the X11 6x9 dot font (lcd.py) for the
glass displays and the counter."""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 3                                                    # supersampling factor for the sprites

# each machine's accent, taken from its real front panel
ACCENTS = {"MODERN": (255, 138, 61),     # Monolith's own orange
           "MPC60": (230, 62, 62),       # Akai red (the logo and the REC keys)
           "MPC3000": (226, 212, 186),   # its cream-grey pads and keys
           "MPC2000XL": (159, 183, 201), # silver blue-grey
           "SP-1200": (96, 152, 224),    # the blue of the SP-1200's facia
           "ASR-10": (70, 224, 208)}     # Ensoniq teal

# the palette (from the design mock-ups)
PAGE_TOP, PAGE_MID, PAGE_BOT = (56, 60, 70), (38, 41, 48), (28, 30, 35)
KEY_TOP, KEY_BOT = (54, 58, 66), (42, 45, 51)
KEYD_TOP, KEYD_BOT = (34, 37, 43), (42, 45, 52)
PLATE_TOP, PLATE_BOT = (49, 52, 59), (39, 42, 48)
WELL_C = (21, 23, 27)
GLASS_TOP, GLASS_BOT = (15, 18, 22), (11, 13, 16)
TXT, TXT2, LAB, LAB2 = (230, 233, 239), (201, 206, 216), (124, 132, 148), (95, 102, 114)
LED_OFF = (58, 62, 70)

# ------------------------------------------------------------------ fonts
_FONT_FILES = {"r": "Inter-Regular.otf", "m": "Inter-Medium.otf", "s": "Inter-SemiBold.otf", "b": "Inter-Bold.otf"}
_fonts = {}


def inter(px, weight="s"):
    """Inter at a pixel size (weights: r regular, m medium, s semibold, b bold); DejaVu if Inter is missing"""
    key = (int(px), weight)
    if key not in _fonts:
        for base in (os.path.join(HERE, "fonts"), "/usr/share/fonts/opentype/inter"):
            try:
                _fonts[key] = ImageFont.truetype(os.path.join(base, _FONT_FILES[weight]), int(px)); break
            except OSError:
                continue
        else:
            _fonts[key] = ImageFont.truetype("DejaVuSans-Bold.ttf" if weight in "sb" else "DejaVuSans.ttf", int(px))
    return _fonts[key]


def face(name, px):
    """Michroma (labels, keys, captions) or Departure Mono (readouts; VT323 kept for reference), bundled in fonts/ (SIL OFL);
    Inter if one is missing"""
    key = (name, int(px))
    if key not in _fonts:
        try: _fonts[key] = ImageFont.truetype(os.path.join(HERE, "fonts", {"michroma": "Michroma-Regular.ttf", "vt323": "VT323-Regular.ttf", "departure": "DepartureMono-Regular.otf"}[name]), int(px))
        except OSError: _fonts[key] = inter(px, "s")
    return _fonts[key]


def have_inter():
    return any(os.path.exists(os.path.join(b, "Inter-Regular.otf")) for b in (os.path.join(HERE, "fonts"), "/usr/share/fonts/opentype/inter"))


# ------------------------------------------------------------------ helpers
_cache = {}


def cached(key, make):
    hit = _cache.get(key)
    if hit is None:
        if len(_cache) > 40000: _cache.clear()          # (every page on every machine is well under this)
        hit = _cache[key] = make()
    return hit


def _cache_tag(scale):
    """what a saved cache is valid for: this version of the look, at this scale"""
    import hashlib, os
    h = hashlib.sha1(str(scale).encode())
    here = os.path.dirname(os.path.abspath(__file__))
    for f in ("skin.py", "screens.py", "uicore.py", "pages.py", "fxpage.py", "mainpanel.py"):
        try: h.update(open(os.path.join(here, f), "rb").read())
        except OSError: pass
    return h.hexdigest()[:16]


def cache_path(scale):
    import os
    d = os.path.join(os.path.expanduser("~"), ".cache", "monolith")
    return os.path.join(d, f"skin_{_cache_tag(scale)}.bin")


def load_cache(scale):
    """the parts drawn last time (same look, same scale): True if loaded. A stale or broken file is just ignored."""
    import os, pickle, zlib
    p = cache_path(scale)
    try:
        _cache.update(pickle.loads(zlib.decompress(open(p, "rb").read())))
        return True
    except Exception:
        return False


def save_cache(scale):
    import os, pickle, zlib, glob
    p = cache_path(scale)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        for old in glob.glob(os.path.join(os.path.dirname(p), "skin_*.bin")):        # older looks / scales: not needed
            if old != p: os.remove(old)
        keep = {k: v for k, v in _cache.items() if not (isinstance(k, tuple) and k and k[0] == "stack")}   # (keyed by object ids)
        tmp = p + ".tmp"
        open(tmp, "wb").write(zlib.compress(pickle.dumps(keep, protocol=5), 1)); os.replace(tmp, p)
    except Exception as ex:
        print("skin cache not saved:", ex)


def _vgrad(w, h, top, bot):
    t = np.linspace(0, 1, h)[:, None, None]
    a = np.array(top, float)[None, None, :]; b = np.array(bot, float)[None, None, :]
    return Image.fromarray(np.repeat((a * (1 - t) + b * t).astype(np.uint8), w, axis=1), "RGB")


def _rr_mask(w, h, r, inset=0):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([inset, inset, w - 1 - inset, h - 1 - inset], max(0, r - inset), fill=255)
    return m


def _down(im, w, h):
    return im.resize((w, h), Image.LANCZOS)


def _rgba(rgb, a=255): return tuple(rgb[:3]) + (a,)


# ------------------------------------------------------------------ the parts
def body(w, h, r, top, bot, highlight=0.08, edge_dark=0.35, shadow=(10, 0.45), outline=None, glow=None):
    """a raised, rounded body: vertical gradient, a light top edge, a dark bottom lip, a soft drop shadow.
    Returns (sprite, ox, oy): paste at (x - ox, y - oy) - the sprite is padded for the shadow."""
    key = ("body", w, h, r, top, bot, highlight, edge_dark, shadow, outline, glow)

    def make():
        pad = int(shadow[0] * 1.6) + 4 if shadow else 2
        if glow: pad = max(pad, int(glow[1] * 1.8) + 4)
        W2, H2 = (w + 2 * pad) * SS, (h + 2 * pad) * SS
        out = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        if shadow:                                            # drop shadow: a blurred dark copy, nudged down
            sh = Image.new("L", (W2, H2), 0)
            ImageDraw.Draw(sh).rounded_rectangle([pad * SS, (pad + shadow[0] * 0.45) * SS, (pad + w) * SS, (pad + h + shadow[0] * 0.45) * SS],
                                                 r * SS, fill=int(255 * shadow[1]))
            sh = sh.filter(ImageFilter.GaussianBlur(shadow[0] * SS * 0.6))
            out.paste(Image.new("RGBA", (W2, H2), (0, 0, 0, 255)), (0, 0), sh)
        if glow:                                              # an accent glow around it (a lit key)
            gl = Image.new("L", (W2, H2), 0)
            ImageDraw.Draw(gl).rounded_rectangle([pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS], r * SS, fill=int(255 * glow[2]))
            gl = gl.filter(ImageFilter.GaussianBlur(glow[1] * SS * 0.6))
            out = Image.alpha_composite(out, Image.merge("RGBA", (*Image.new("RGB", (W2, H2), glow[0]).split(), gl)))
        m = _rr_mask(w * SS, h * SS, r * SS)
        g = _vgrad(w * SS, h * SS, top, bot).convert("RGBA")
        d = ImageDraw.Draw(g)
        if highlight:                                         # light top edge (inset 1px highlight)
            d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], r * SS, outline=_rgba((255, 255, 255), int(255 * highlight)), width=SS)
            g2 = Image.new("RGBA", g.size, (0, 0, 0, 0))
            ImageDraw.Draw(g2).rectangle([0, int(h * SS * 0.5), w * SS, h * SS], fill=(0, 0, 0, 0))
        if edge_dark:                                         # dark bottom lip
            lip = Image.new("L", (w * SS, h * SS), 0)
            ImageDraw.Draw(lip).rounded_rectangle([0, h * SS - 2 * SS - r * SS, w * SS - 1, h * SS - 1], r * SS, fill=int(255 * edge_dark))
            inner = _rr_mask(w * SS, h * SS - 2 * SS, r * SS)
            lip.paste(0, (0, 0), inner)
            g = Image.alpha_composite(g, Image.merge("RGBA", (*Image.new("RGB", g.size, (0, 0, 0)).split(), lip)))
        if outline:
            ImageDraw.Draw(g).rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], r * SS, outline=_rgba(outline[0], outline[1]), width=int(outline[2] * SS))
        out.paste(g, (pad * SS, pad * SS), m)
        return _down(out, w + 2 * pad, h + 2 * pad), pad, pad
    return cached(key, make)


def well(w, h, r, fill=WELL_C, depth=9, strength=0.8, rim=0.05):
    """a recessed area: flat dark fill with an inner shadow from the top, a faint light lip at the bottom"""
    key = ("well", w, h, r, fill, depth, strength, rim)

    def make():
        W2, H2 = w * SS, h * SS
        base = Image.new("RGBA", (W2, H2), _rgba(fill))
        m = _rr_mask(W2, H2, r * SS)
        # inner shadow: the inverse of a shape pushed down, blurred, kept inside
        sh = Image.new("L", (W2 + 40 * SS, H2 + 40 * SS), 255)
        ImageDraw.Draw(sh).rounded_rectangle([20 * SS, (20 + depth * 0.35) * SS, 20 * SS + W2, (20 + depth * 0.35) * SS + H2], r * SS, fill=0)
        sh = sh.filter(ImageFilter.GaussianBlur(depth * SS * 0.45)).crop((20 * SS, 20 * SS, 20 * SS + W2, 20 * SS + H2))
        sh = sh.point(lambda v: int(v * strength))
        base = Image.alpha_composite(base, Image.merge("RGBA", (*Image.new("RGB", (W2, H2), (0, 0, 0)).split(), sh)))
        if rim:
            ImageDraw.Draw(base).rounded_rectangle([0, 0, W2 - 1, H2 - 1], r * SS, outline=(255, 255, 255, int(255 * rim)), width=SS)
        out = Image.new("RGBA", (W2, H2), (0, 0, 0, 0)); out.paste(base, (0, 0), m)
        return _down(out, w, h)
    return cached(key, make)


def plate(w, h, r=16):
    """a module plate (the panels the screen is built from)"""
    return body(w, h, r, PLATE_TOP, PLATE_BOT, highlight=0.08, edge_dark=0.0, shadow=(14, 0.45))


def key(w, h, r=10, state="up", accent=(255, 138, 61)):
    """a mechanical key: up (raised), down (pressed in, accent rim) or lit (accent glow under the cap)"""
    if state == "down":
        sp, ox, oy = body(w, h, r, KEYD_TOP, KEYD_BOT, highlight=0.0, edge_dark=0.0, shadow=None, outline=(accent, 90, 1.0))
        inner = well(w, h, r, fill=(36, 39, 45), depth=6, strength=0.75, rim=0.0)
        return _stack(sp, ox, oy, inner), ox, oy
    if state == "lit":
        top = tuple(int(a * 0.32 + b * 0.68) for a, b in zip(accent, (47, 50, 57)))
        return body(w, h, r, top, (44, 47, 54), highlight=0.10, edge_dark=0.35, shadow=(8, 0.5), glow=(accent, 10, 0.28))
    return body(w, h, r, KEY_TOP, KEY_BOT, highlight=0.08, edge_dark=0.35, shadow=(8, 0.5))


def _stack(sp, ox, oy, top):
    key_ = ("stack", id(sp), id(top))

    def make():
        out = sp.copy(); out.alpha_composite(top, (ox, oy)); return out
    return cached(key_, make)


def led(size, on, col):
    """a small LED: lit with a glow, or dark"""
    key = ("led", size, on, col)

    def make():
        pad = size * 2 if on else 2
        W2 = (size + 2 * pad) * SS
        out = Image.new("RGBA", (W2, W2), (0, 0, 0, 0))
        if on:
            g = Image.new("L", (W2, W2), 0)
            ImageDraw.Draw(g).ellipse([pad * SS - size * SS * 0.4, pad * SS - size * SS * 0.4, (pad + size) * SS + size * SS * 0.4,
                                       (pad + size) * SS + size * SS * 0.4], fill=150)
            g = g.filter(ImageFilter.GaussianBlur(size * SS * 0.7))
            out = Image.merge("RGBA", (*Image.new("RGB", (W2, W2), col).split(), g))
        ImageDraw.Draw(out).ellipse([pad * SS, pad * SS, (pad + size) * SS, (pad + size) * SS], fill=_rgba(col if on else LED_OFF))
        if on:
            ImageDraw.Draw(out).ellipse([(pad + size * 0.25) * SS, (pad + size * 0.2) * SS, (pad + size * 0.55) * SS, (pad + size * 0.5) * SS],
                                        fill=(255, 255, 255, 110))
        return _down(out, size + 2 * pad, size + 2 * pad), pad
    return cached(key, make)


def bar_led(w, h, on, col):
    """the little LED bar on a tab key"""
    key = ("barled", w, h, on, col)

    def make():
        pad = 8 if on else 1
        W2, H2 = (w + 2 * pad) * SS, (h + 2 * pad) * SS
        out = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        if on:
            g = Image.new("L", (W2, H2), 0)
            ImageDraw.Draw(g).rounded_rectangle([pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS], h * SS / 2, fill=170)
            g = g.filter(ImageFilter.GaussianBlur(4 * SS))
            out = Image.merge("RGBA", (*Image.new("RGB", (W2, H2), col).split(), g))
        ImageDraw.Draw(out).rounded_rectangle([pad * SS, pad * SS, (pad + w) * SS, (pad + h) * SS], h * SS / 2, fill=_rgba(col if on else LED_OFF))
        return _down(out, w + 2 * pad, h + 2 * pad), pad
    return cached(key, make)


def knob(d, frac, accent, centre=False, steps=96):
    """a machined knob with an accent ring over 270 degrees; frac 0..1 (quantised to `steps` so it caches)"""
    q = int(round(max(0.0, min(1.0, frac)) * steps))
    key = ("knob", d, q, accent, centre)

    def make():
        f = q / steps
        ring = d + 14
        pad = 12
        W2 = (ring + 2 * pad) * SS
        out = Image.new("RGBA", (W2, W2), (0, 0, 0, 0))
        dr = ImageDraw.Draw(out)
        c0 = pad * SS; c1 = (pad + ring) * SS
        # ring track and the lit arc (PIL angles: 0 = 3 o'clock, clockwise); the arc runs from 135 to 405 degrees
        dr.arc([c0, c0, c1, c1], 135, 405, fill=(44, 47, 54, 255), width=int(5 * SS))
        a0, a1 = (135, 135 + 270 * f) if not centre else tuple(sorted((270, 135 + 270 * f)))
        if a1 - a0 > 0.8:
            g = Image.new("RGBA", (W2, W2), (0, 0, 0, 0))
            ImageDraw.Draw(g).arc([c0, c0, c1, c1], a0, a1, fill=_rgba(accent), width=int(5 * SS))
            glow = g.filter(ImageFilter.GaussianBlur(4 * SS))
            out = Image.alpha_composite(out, glow); out = Image.alpha_composite(out, g)
            dr = ImageDraw.Draw(out)
        # the knob: shadow, a dark skirt, a bright machined bevel, the cap
        cx = cy = W2 / 2
        rr = (d / 2) * SS
        sh = Image.new("L", (W2, W2), 0)
        ImageDraw.Draw(sh).ellipse([cx - rr, cy - rr + 4 * SS, cx + rr, cy + rr + 4 * SS], fill=160)
        sh = sh.filter(ImageFilter.GaussianBlur(5 * SS))
        out.paste(Image.new("RGBA", (W2, W2), (0, 0, 0, 255)), (0, 0), sh)
        dr = ImageDraw.Draw(out)
        for frac_r, col in ((1.0, (42, 45, 51)), (0.92, (61, 65, 74)), (0.86, (154, 160, 171)), (0.80, (86, 91, 102)), (0.76, (38, 41, 47))):
            dr.ellipse([cx - rr * frac_r, cy - rr * frac_r, cx + rr * frac_r, cy + rr * frac_r], fill=_rgba(col))
        # cap: a soft radial highlight from the top left
        cap = Image.new("L", (W2, W2), 0)
        ImageDraw.Draw(cap).ellipse([cx - rr * 0.6, cy - rr * 0.75, cx + rr * 0.2, cy - rr * 0.05], fill=40)
        cap = cap.filter(ImageFilter.GaussianBlur(rr * 0.25))
        out = Image.alpha_composite(out, Image.merge("RGBA", (*Image.new("RGB", (W2, W2), (255, 255, 255)).split(), cap)))
        dr = ImageDraw.Draw(out)
        ang = np.radians(135 + 270 * f)                      # the pointer
        x0, y0 = cx + np.cos(ang) * rr * 0.28, cy + np.sin(ang) * rr * 0.28
        x1, y1 = cx + np.cos(ang) * rr * 0.68, cy + np.sin(ang) * rr * 0.68
        dr.line([x0, y0, x1, y1], fill=(242, 244, 248, 255), width=int(3 * SS))
        return _down(out, ring + 2 * pad, ring + 2 * pad), pad + 7
    return cached(key, make)


def glass(w, h, r=10, warm=False):
    """a display window: deep, with an inner shadow and a faint rim; warm = the amber MODERN display's glow"""
    key = ("glass", w, h, r, warm)

    def make():
        W2, H2 = w * SS, h * SS
        if warm:                                              # radial amber glow from the top left
            yy, xx = np.mgrid[0:H2, 0:W2]
            dist = np.sqrt(((xx - W2 * 0.3) / (W2 * 1.1)) ** 2 + ((yy - 0) / (H2 * 1.4)) ** 2)
            t = np.clip(dist / 0.7, 0, 1)[..., None]
            a, b = np.array((58, 36, 16), float), np.array((19, 11, 5), float)
            base = Image.fromarray((a * (1 - t) + b * t).astype(np.uint8), "RGB").convert("RGBA")
        else:
            base = _vgrad(W2, H2, GLASS_TOP, GLASS_BOT).convert("RGBA")
        sh = Image.new("L", (W2 + 40 * SS, H2 + 40 * SS), 255)
        ImageDraw.Draw(sh).rounded_rectangle([20 * SS, 23 * SS, 20 * SS + W2, 23 * SS + H2], r * SS, fill=0)
        sh = sh.filter(ImageFilter.GaussianBlur(5 * SS)).crop((20 * SS, 20 * SS, 20 * SS + W2, 20 * SS + H2)).point(lambda v: int(v * 0.85))
        base = Image.alpha_composite(base, Image.merge("RGBA", (*Image.new("RGB", (W2, H2), (0, 0, 0)).split(), sh)))
        ImageDraw.Draw(base).rounded_rectangle([0, 0, W2 - 1, H2 - 1], r * SS, outline=(255, 255, 255, 20), width=SS)
        out = Image.new("RGBA", (W2, H2), (0, 0, 0, 0)); out.paste(base, (0, 0), _rr_mask(W2, H2, r * SS))
        return _down(out, w, h)
    return cached(key, make)


def page_bg(w, h):
    """the chassis behind everything: a soft radial light from the top left"""
    def make():
        yy, xx = np.mgrid[0:h, 0:w].astype(float)
        dist = np.sqrt(((xx - w * 0.3) / (w * 1.2)) ** 2 + (yy / (h * 0.9)) ** 2)
        t = np.clip(dist, 0, 1)
        a, m, b = np.array(PAGE_TOP, float), np.array(PAGE_MID, float), np.array(PAGE_BOT, float)
        t1 = np.clip(t / 0.55, 0, 1)[..., None]; t2 = np.clip((t - 0.55) / 0.45, 0, 1)[..., None]
        col = np.where(t[..., None] < 0.55, a * (1 - t1) + m * t1, m * (1 - t2) + b * t2)
        noise = np.random.default_rng(7).normal(0, 1.2, (h, w, 1))          # a hint of grain, so gradients do not band
        return Image.fromarray(np.clip(col + noise, 0, 255).astype(np.uint8), "RGB")
    return cached(("page", w, h), make)


def strip_bg(w, h):
    return cached(("strip", w, h), lambda: _vgrad(w, h, (29, 31, 36), (23, 25, 29)))


# ------------------------------------------------------------------ text
def tracked(txt, px, weight, color, spacing=0.12):
    """letter-spaced capitals (the panel labels): an RGBA image, cached"""
    key = ("trk", txt, px, weight, color, spacing)

    def make():
        # drawn 4x and scaled down: at label sizes FreeType's hinting snaps each letter on its own, so round letters
        # (S, O, C) came out taller than the rest on some systems (the Pi). Drawn large, every letter keeps its true size.
        K = 4
        size = max(7, round(px * 0.9))                                    # Michroma, as on the artboards (it runs wide: a touch smaller,
        f = face("michroma", size * K)                                    # and less extra tracking - it is spaced out already)
        sp_ = spacing * 0.5
        adv = [f.getlength(ch) + sp_ * px * K for ch in txt]
        wd = int(sum(adv) - sp_ * px * K) + 4 * K
        asc, desc = f.getmetrics()
        hh = asc + desc + 2 * K
        m = Image.new("L", (max(K, wd), hh), 0)
        d = ImageDraw.Draw(m); x = 0.0
        for ch, a in zip(txt, adv):
            d.text((x, 0), ch, font=f, fill=255); x += a
        w1, h1 = max(1, -(-m.width // K)), max(1, -(-hh // K))
        m = m.resize((w1, h1), Image.LANCZOS)
        im = Image.new("RGBA", (w1, h1), _rgba(color))
        a_ = m.point(lambda v: v * _rgba(color)[3] // 255) if len(_rgba(color)) == 4 else m
        im.putalpha(a_)
        return im
    return cached(key, make)


def dot_text(txt, k, col, glow=True, ghost=None):
    """the 6 x 9 dot font (lcd.py) at k screen pixels a dot, round-ish dots, with a phosphor glow: the glass displays"""
    key = ("dots", txt, k, col, glow, ghost)

    def make():
        import lcd
        cols = len(txt)
        wd, ht = cols * lcd.CW * k, lcd.CH * k
        m = Image.new("L", (wd * SS, ht * SS), 0)
        d = ImageDraw.Draw(m)
        gm = Image.new("L", (wd * SS, ht * SS), 0) if ghost else None
        gd = ImageDraw.Draw(gm) if ghost else None
        rad = k * SS * 0.46
        for i, ch in enumerate(txt):
            g = lcd.glyph(ch)
            for r in range(lcd.CH):
                for c_ in range(lcd.CW):
                    cx, cy = (i * lcd.CW + c_ + 0.5) * k * SS, (r + 0.5) * k * SS
                    if g[r][c_]: d.rounded_rectangle([cx - rad, cy - rad, cx + rad, cy + rad], rad * 0.45, fill=255)
                    elif gd is not None: gd.rounded_rectangle([cx - rad, cy - rad, cx + rad, cy + rad], rad * 0.45, fill=255)
        m = _down(m, wd, ht)
        pad = k * 3 if glow else 0
        out = Image.new("RGBA", (wd + 2 * pad, ht + 2 * pad), (0, 0, 0, 0))
        if ghost:
            gm = _down(gm, wd, ht)
            out.paste(Image.new("RGBA", (wd, ht), _rgba(ghost)), (pad, pad), gm)
        if glow:
            gl = Image.new("L", out.size, 0); gl.paste(m, (pad, pad)); gl = gl.filter(ImageFilter.GaussianBlur(k * 1.4)).point(lambda v: int(v * 0.55))
            out = Image.alpha_composite(out, Image.merge("RGBA", (*Image.new("RGB", out.size, col).split(), gl)))
        out.paste(Image.new("RGBA", (wd, ht), _rgba(col)), (pad, pad), m)
        return out, pad
    return cached(key, make)


# ------------------------------------------------------------------ console parts (the MIXER, desk C: American)
def vu_face(w, h, label="VU", nums=None, cream=False):
    """an amber VU meter face: arc with ticks, red end, 'VU'. The needle is drawn per frame (vu_needle_geom).
    nums: [(frac, text, red)] numerals round the arc (the faceplates' big meters); cream: the paler face of the faceplates."""
    key = ("vu", w, h, label, repr(nums), cream)

    def make():
        W2, H2 = w * SS, h * SS
        im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        if cream:
            g = Image.new("RGB", (W2, H2), (240, 228, 196))
            gl = Image.new("L", (W2, H2), 0); ImageDraw.Draw(gl).ellipse([W2 * 0.2, H2 * 0.45, W2 * 0.9, H2 * 1.4], fill=150)
            g.paste((252, 244, 222), (0, 0), gl.filter(ImageFilter.GaussianBlur(W2 * 0.12)))
            g = g.convert("RGBA")
        else:
            g = _vgrad(W2, H2, (250, 206, 128), (236, 168, 78)).convert("RGBA")
            ImageDraw.Draw(g).rectangle([0, int(H2 * 0.82), W2, H2], fill=(226, 156, 70, 255))
        m = _rr_mask(W2, H2, int(3 * SS))
        im.paste(g, (0, 0), m)
        d = ImageDraw.Draw(im)
        cx, cy, R = W2 / 2, H2 * 1.55, H2 * 1.25
        if nums:
            f2 = inter(max(6, int(h * SS * 0.1)), "m")
            for fr, txt, red in nums:
                a = math.radians(-42 + 84 * fr)
                for r0, r1 in ((R * 0.88, R * 0.95),):
                    d.line([cx + r0 * math.sin(a), cy - r0 * math.cos(a), cx + r1 * math.sin(a), cy - r1 * math.cos(a)],
                           fill=(196, 40, 30, 255) if red else (40, 30, 20, 255), width=max(1, SS))
                r2 = R * 1.02
                d.text((cx + r2 * math.sin(a), cy - r2 * math.cos(a)), txt, font=f2, fill=(196, 40, 30, 255) if red else (48, 34, 20, 255), anchor="mm")
        for k in range(11 if not nums else 0):
            a = math.radians(-38 + k * 7.6)
            r0, r1 = R * (0.86 if k % 2 else 0.83), R * 0.93
            col = (196, 40, 30, 255) if k >= 8 else (40, 30, 20, 255)
            d.line([cx + r0 * math.sin(a), cy - r0 * math.cos(a), cx + r1 * math.sin(a), cy - r1 * math.cos(a)], fill=col, width=max(1, SS))
        d.arc([cx - R * 0.93, cy - R * 0.93, cx + R * 0.93, cy + R * 0.93], -90 - 38, -90 + 38, fill=(60, 44, 26, 255), width=max(1, SS // 2))
        d.arc([cx - R * 0.93, cy - R * 0.93, cx + R * 0.93, cy + R * 0.93], -90 + 23, -90 + 38, fill=(196, 40, 30, 255), width=SS)
        f = inter(max(6, int(h * SS * (0.13 if nums else 0.2))), "b")
        d.text((cx, H2 * (0.6 if nums else 0.68)), label, font=f, fill=(48, 34, 20, 255), anchor="mm")
        sh = Image.new("L", (W2, H2), 0); ImageDraw.Draw(sh).rectangle([0, 0, W2, int(5 * SS)], fill=70)
        sh = sh.filter(ImageFilter.GaussianBlur(3 * SS))
        im.paste((0, 0, 0, 255), (0, 0), Image.composite(sh, Image.new("L", (W2, H2), 0), m))
        return _down(im, w, h)
    return cached(key, make)


def vu_needle(w, h, frac):
    """needle end points (relative to the face's top-left) for a VU reading 0..1 (0 = -20 VU, ~0.77 = 0 VU, 1 = +3)"""
    cx, cy, R = w / 2.0, h * 1.55, h * 1.25
    a = math.radians(-42 + 84 * max(0.0, min(1.0, frac)))
    return (cx + R * 0.42 * math.sin(a), cy - R * 0.42 * math.cos(a)), (cx + R * 0.97 * math.sin(a), cy - R * 0.97 * math.cos(a))


def cknob(d, frac, centre=False, steps=64):
    """a console knob: silver skirt, black cap, white pointer over 300 degrees; frac 0..1"""
    q = int(round(max(0.0, min(1.0, frac)) * steps))
    key = ("cknob", d, q, centre)

    def make():
        pad = max(4, d // 4)
        W2 = (d + 2 * pad) * SS
        im = Image.new("RGBA", (W2, W2), (0, 0, 0, 0))
        sh = Image.new("L", (W2, W2), 0)
        o = pad * SS
        ImageDraw.Draw(sh).ellipse([o, o + d * SS * 0.08, o + d * SS, o + d * SS * 1.08], fill=200)
        im.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(d * SS * 0.07)))
        dr = ImageDraw.Draw(im)
        dr.ellipse([o, o, o + d * SS, o + d * SS], fill=(214, 216, 220, 255))
        g = _vgrad(d * SS, d * SS, (236, 238, 242), (150, 154, 160)).convert("RGBA")
        im.paste(g, (o, o), _rr_mask(d * SS, d * SS, d * SS // 2))
        i = d * SS * 0.16
        dr.ellipse([o + i, o + i, o + d * SS - i, o + d * SS - i], fill=(26, 27, 30, 255))
        dr.ellipse([o + i, o + i, o + d * SS - i, o + d * SS - i], outline=(70, 72, 78, 255), width=max(1, SS // 2))
        a = math.radians(-150 + 300 * (q / float(steps)))
        c = o + d * SS / 2.0; r0, r1 = d * SS * 0.05, d * SS * 0.36
        dr.line([c + r0 * math.sin(a), c - r0 * math.cos(a), c + r1 * math.sin(a), c - r1 * math.cos(a)], fill=(245, 245, 245, 255),
                width=max(2, int(d * SS * 0.07)))
        return _down(im, d + 2 * pad, d + 2 * pad), pad
    return cached(key, make)


def fader_cap(w, h):
    """the American desk's fader cap: black, a white line across"""
    key = ("fcap", w, h)

    def make():
        sp, ox, oy = body(w, h, max(1, h // 6), (44, 45, 48), (12, 12, 14), 0.12, 0.4, (max(3, h // 3), 0.7))
        im = sp.copy(); d = ImageDraw.Draw(im)
        y = oy + h // 2
        d.line([ox + w * 0.18, y, ox + w * 0.82, y], fill=(250, 250, 250, 255), width=max(1, h // 7))
        return im, ox, oy
    return cached(key, make)


# ------------------------------------------------------------------ effect faceplates (the FX page)
def faceplate(w, h, style="dark"):
    """an effect's front panel: 'dark' (black crackle, the tape echo and valve drive), 'slate' (filter / crush), 'alu' (brushed
    aluminium, the bus comp)"""
    key = ("face", w, h, style)

    def make():
        W2, H2 = w * SS, h * SS
        rng = np.random.default_rng(7)
        if style == "alu":
            base = np.linspace(196, 168, H2)[:, None] + np.zeros((1, W2))
            streak = rng.normal(0, 1, (H2, 1)) * 5 + rng.normal(0, 1, (H2, W2)) * 2
            a = np.clip(base + streak, 0, 255)
            rgb = np.stack([a, a + 2, a + 6], -1)
        elif style == "dark":
            n = rng.normal(0, 1, (H2 // 3 + 1, W2 // 3 + 1)).repeat(3, 0).repeat(3, 1)[:H2, :W2]
            a = 34 + n * 3.2
            rgb = np.stack([a + 1, a + 1, a], -1)
        else:
            a = np.linspace(48, 40, H2)[:, None] + np.zeros((1, W2)) + rng.normal(0, 1, (H2, W2)) * 0.8
            rgb = np.stack([a, a + 2, a + 6], -1)
        g = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
        im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        im.paste(g, (0, 0), _rr_mask(W2, H2, 6 * SS))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, W2 - 1, H2 - 1], 6 * SS, outline=(255, 255, 255, 40 if style != "alu" else 110), width=SS)
        d.rounded_rectangle([SS, SS, W2 - 1 - SS, H2 - 1 - SS], 5 * SS, outline=(0, 0, 0, 120), width=SS)
        for sx, sy in ((7, 7), (w - 7, 7), (7, h - 7), (w - 7, h - 7)):
            X, Y, r = sx * SS, sy * SS, 3 * SS
            d.ellipse([X - r, Y - r, X + r, Y + r], fill=(150, 152, 156, 255), outline=(40, 40, 44, 255), width=SS // 2 or 1)
            d.line([X - r * 0.6, Y - r * 0.6, X + r * 0.6, Y + r * 0.6], fill=(60, 62, 66, 255), width=SS)
        return _down(im, w, h)
    return cached(key, make)


def bknob(d, frac, ring=True):
    """a black faceplate knob (pointer, tick ring round it): the tape echo / valve drive / comp knobs; frac 0..1"""
    q = int(round(max(0.0, min(1.0, frac)) * 48))
    key = ("bknob", d, q, ring)

    def make():
        pad = max(5, int(d * 0.32))
        W2 = (d + 2 * pad) * SS; o = pad * SS; D = d * SS; c = W2 / 2.0
        im = Image.new("RGBA", (W2, W2), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        if ring:
            for k in range(11):
                a = math.radians(-135 + 27 * k)
                r0, r1 = D * 0.6, D * 0.68
                dr.line([c + r0 * math.sin(a), c - r0 * math.cos(a), c + r1 * math.sin(a), c - r1 * math.cos(a)], fill=(200, 200, 204, 255), width=SS)
        sh = Image.new("L", (W2, W2), 0)
        ImageDraw.Draw(sh).ellipse([o, o + D * 0.1, o + D, o + D * 1.1], fill=210)
        im.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(D * 0.08)))
        dr.ellipse([o, o, o + D, o + D], fill=(14, 14, 16, 255))
        g = _vgrad(int(D * 0.86), int(D * 0.86), (70, 70, 76), (22, 22, 25)).convert("RGBA")
        im.paste(g, (int(o + D * 0.07), int(o + D * 0.07)), _rr_mask(int(D * 0.86), int(D * 0.86), int(D * 0.43)))
        a = math.radians(-135 + 270 * q / 48.0)
        r0, r1 = D * 0.1, D * 0.4
        dr.line([c + r0 * math.sin(a), c - r0 * math.cos(a), c + r1 * math.sin(a), c - r1 * math.cos(a)], fill=(245, 245, 245, 255),
                width=max(2, int(D * 0.07)))
        return _down(im, d + 2 * pad, d + 2 * pad), pad
    return cached(key, make)


def chrome_knob(d, frac):
    """the big knurled chrome knob (the tape echo's MODE SELECTOR, the crush BITS knob)"""
    q = int(round(max(0.0, min(1.0, frac)) * 66))
    key = ("chknob", d, q)

    def make():
        pad = max(5, int(d * 0.18))
        W2 = (d + 2 * pad) * SS; o = pad * SS; D = d * SS; c = W2 / 2.0
        im = Image.new("RGBA", (W2, W2), (0, 0, 0, 0))
        sh = Image.new("L", (W2, W2), 0)
        ImageDraw.Draw(sh).ellipse([o, o + D * 0.08, o + D, o + D * 1.08], fill=220)
        im.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(D * 0.06)))
        dr = ImageDraw.Draw(im)
        dr.ellipse([o, o, o + D, o + D], fill=(36, 36, 40, 255))
        for k in range(60):                                              # the knurled skirt
            a = 2 * math.pi * k / 60
            dr.line([c + D * 0.4 * math.sin(a), c - D * 0.4 * math.cos(a), c + D * 0.5 * math.sin(a), c - D * 0.5 * math.cos(a)],
                    fill=(70, 70, 76, 255) if k % 2 else (20, 20, 22, 255), width=SS)
        cap = int(D * 0.74); co = int(c - cap / 2)
        g = Image.new("RGB", (cap, cap), (200, 202, 206)); gl = Image.new("L", (cap, cap), 0)
        ImageDraw.Draw(gl).ellipse([cap * 0.1, cap * 0.05, cap * 0.75, cap * 0.6], fill=255)
        g.paste((250, 251, 253), (0, 0), gl.filter(ImageFilter.GaussianBlur(cap * 0.12)))
        g2 = _vgrad(cap, cap, (230, 232, 236), (130, 134, 140))
        g = Image.blend(g, g2, 0.45).convert("RGBA")
        im.paste(g, (co, co), _rr_mask(cap, cap, cap // 2))
        a = math.radians(-150 + 300 * q / 66.0)
        r0, r1 = D * 0.12, D * 0.33
        dr.line([c + r0 * math.sin(a), c - r0 * math.cos(a), c + r1 * math.sin(a), c - r1 * math.cos(a)], fill=(24, 24, 26, 255),
                width=max(2, int(D * 0.06)))
        return _down(im, d + 2 * pad, d + 2 * pad), pad
    return cached(key, make)


def valve(w, h, power=False, glow=0.0, warm=(255, 140, 50)):
    """a vacuum tube: glass envelope, plates, getter, pins; glow 0..1 warms the heater. power = the big octal output valve."""
    q = int(round(max(0.0, min(1.0, glow)) * 8))
    key = ("valve", w, h, power, q, warm)

    def make():
        W2, H2 = w * SS, h * SS
        im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
        g = q / 8.0
        if g > 0:                                                        # the warm halo behind the glass
            gl = Image.new("L", (W2, H2), 0)
            ImageDraw.Draw(gl).ellipse([W2 * 0.05, H2 * 0.25, W2 * 0.95, H2 * 0.9], fill=int(170 * g))
            im.paste(warm + (255,), (0, 0), gl.filter(ImageFilter.GaussianBlur(W2 * 0.18)))
        d = ImageDraw.Draw(im)
        gx0, gx1 = W2 * 0.2, W2 * 0.8
        top, bot = H2 * 0.03, H2 * (0.82 if power else 0.9)
        glass = Image.new("RGBA", (W2, H2), (0, 0, 0, 0)); gd = ImageDraw.Draw(glass)
        gd.rounded_rectangle([gx0, top, gx1, bot], int((gx1 - gx0) / 2), fill=(200, 210, 220, 46), outline=(220, 228, 236, 170), width=SS)
        im.alpha_composite(glass)
        # plates and the heater
        px0, px1 = W2 * 0.3, W2 * 0.7
        py0, py1 = H2 * (0.18 if power else 0.24), H2 * (0.62 if power else 0.74)
        d.rectangle([px0, py0, px1, py1], fill=(70, 72, 78, 255), outline=(150, 154, 160, 255), width=SS)
        for k in range(1, 4 if power else 2):
            xx = px0 + (px1 - px0) * k / (4 if power else 2)
            d.line([xx, py0, xx, py1], fill=(40, 40, 44, 255), width=SS)
        if power:
            for k in range(12):
                yy = py0 + (py1 - py0) * k / 11
                d.line([px0 + SS, yy, px1 - SS, yy], fill=(110, 112, 118, 255), width=1)
        if g > 0:
            hc = tuple(int(30 + (c - 30) * g) for c in warm)
            d.rectangle([W2 * 0.44, py0 + SS * 2, W2 * 0.56, py1 - SS * 2], fill=hc + (255,))
        d.line([px0 - SS, py0 - SS * 2, px1 + SS, py0 - SS * 2], fill=(200, 204, 210, 255), width=SS)
        d.line([px0 - SS, py1 + SS * 2, px1 + SS, py1 + SS * 2], fill=(200, 204, 210, 255), width=SS)
        # the getter (silver flash at the top)
        d.ellipse([W2 * 0.3, top + H2 * 0.01, W2 * 0.7, top + H2 * 0.08], fill=(150, 156, 166, 160))
        if power:                                                        # the octal base
            d.rounded_rectangle([W2 * 0.18, bot, W2 * 0.82, H2 * 0.97], SS * 2, fill=(70, 46, 30, 255), outline=(30, 20, 14, 255), width=SS)
        else:
            for k in range(9):
                xx = W2 * (0.32 + 0.36 * k / 8)
                d.line([xx, bot, xx, H2 * 0.99], fill=(190, 192, 196, 255), width=SS)
        # a highlight down the glass
        d.line([gx0 + (gx1 - gx0) * 0.18, top + (gx1 - gx0) * 0.5, gx0 + (gx1 - gx0) * 0.18, bot - SS * 6], fill=(255, 255, 255, 120), width=SS * 2)
        return _down(im, w, h)
    return cached(key, make)


def pilot(d, on, col=(255, 120, 40)):
    """a jewel pilot lamp in a chrome bezel"""
    key = ("pilot", d, on, col)

    def make():
        pad = max(4, d)
        W2 = (d + 2 * pad) * SS; o = pad * SS; D = d * SS; c = W2 / 2.0
        im = Image.new("RGBA", (W2, W2), (0, 0, 0, 0))
        if on:
            gl = Image.new("L", (W2, W2), 0); ImageDraw.Draw(gl).ellipse([o - D * 0.3, o - D * 0.3, o + D * 1.3, o + D * 1.3], fill=150)
            im.paste(col + (255,), (0, 0), gl.filter(ImageFilter.GaussianBlur(D * 0.25)))
        dr = ImageDraw.Draw(im)
        dr.ellipse([o, o, o + D, o + D], fill=(170, 172, 176, 255), outline=(60, 60, 64, 255), width=SS)
        i = D * 0.16; jc = col if on else tuple(int(v * 0.35) for v in col)
        dr.ellipse([o + i, o + i, o + D - i, o + D - i], fill=jc + (255,))
        for k in range(12):                                              # the jewel's facets
            a = 2 * math.pi * k / 12
            dr.line([c, c, c + (D / 2 - i) * math.sin(a), c - (D / 2 - i) * math.cos(a)],
                    fill=tuple(min(255, int(v * (1.25 if k % 2 else 0.8))) for v in jc) + (255,), width=SS)
        dr.ellipse([c - D * 0.18, c - D * 0.26, c - D * 0.02, c - D * 0.12], fill=(255, 255, 255, 180 if on else 90))
        return _down(im, d + 2 * pad, d + 2 * pad), pad
    return cached(key, make)


def toggle(w, h, up):
    """a chrome bat-handle toggle switch on a round nut"""
    key = ("toggle", w, h, up)

    def make():
        W2, H2 = w * SS, h * SS
        im = Image.new("RGBA", (W2, H2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        c, cy = W2 / 2, H2 / 2
        r = W2 * 0.42
        d.ellipse([c - r, cy - r, c + r, cy + r], fill=(40, 40, 44, 255), outline=(120, 122, 128, 255), width=SS)
        d.ellipse([c - r * 0.6, cy - r * 0.6, c + r * 0.6, cy + r * 0.6], fill=(150, 152, 158, 255))
        tip = cy - H2 * 0.4 if up else cy + H2 * 0.4
        d.line([c, cy, c, tip], fill=(210, 212, 218, 255), width=int(W2 * 0.2))
        d.ellipse([c - W2 * 0.16, tip - W2 * 0.16, c + W2 * 0.16, tip + W2 * 0.16], fill=(236, 238, 242, 255), outline=(120, 120, 126, 255), width=SS)
        return _down(im, w, h)
    return cached(key, make)


def glow_pad(w, h, on, col=(255, 138, 61), r=None):
    """a soft pad / big key: dark when off; lit, it glows from the middle in the accent (STEP steps, MUTE tracks, CHOP slices)"""
    key = ("gpad", w, h, on, col, r)

    def make():
        rr = r if r is not None else max(3, min(w, h) // 9)
        if not on:
            return body(w, h, rr, (52, 55, 62), (40, 43, 49), 0.1, 0.3, (max(4, h // 12), 0.5))
        sp, ox, oy = body(w, h, rr, mix_rgb(col, (0, 0, 0), 0.45), mix_rgb(col, (0, 0, 0), 0.62), 0.12, 0.25, (max(4, h // 12), 0.6), None,
                          (col, max(4, w // 6), 0.35))
        im = sp.copy()
        W2, H2 = w * SS, h * SS
        gl = Image.new("L", (W2, H2), 0)
        ImageDraw.Draw(gl).ellipse([W2 * 0.12, H2 * 0.12, W2 * 0.88, H2 * 0.7], fill=255)
        gl = gl.filter(ImageFilter.GaussianBlur(min(W2, H2) * 0.18))
        layer = Image.new("RGBA", (W2, H2), col + (255,))
        mask = Image.composite(gl, Image.new("L", (W2, H2), 0), _rr_mask(W2, H2, rr * SS))
        layer.putalpha(mask.point(lambda v: int(v * 0.85)))
        im.alpha_composite(_down(layer, w, h), (ox, oy))
        return im, ox, oy
    return cached(key, make)


def mix_rgb(a, b, f): return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))
