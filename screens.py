"""screens.py - draws every screen of Monolith (800 x 500 layout, drawn 1.6x on the 1280 x 800 panel) with Pillow and registers touch regions."""
import math, os, time
import numpy as np
from PIL import Image, ImageDraw
from engine import OUT_SR, OUT_NAMES, QUANT, BANKS, PPQ, NPROG, NSEQ, NOTE_KINDS, KIND_NAMES, SCALES, CHORDS, note_name
from uicore import *
import skin


def splash(status="", progress=None, scale=1.0):
    """start-up screen: the logo from brand/logo_mask.png if there is one (brand/make_brand.py), else the software's name"""
    import os
    img = Image.new("RGB", (int(round(W * scale)), int(round(H * scale))), (10, 10, 13))
    d = ScaledDraw(ImageDraw.Draw(img), scale)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand", "logo_mask.png")
    col = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand", "logo.png")
    if os.path.exists(col):                                       # the logo in its own colours (brand/make_logo.py)
        lg = Image.open(col).convert("RGBA"); bb = lg.getbbox(); lg = lg.crop(bb) if bb else lg
        k = min(150 / lg.height, 560 / lg.width) * scale; w, h = int(lg.width * k), int(lg.height * k)
        lg = lg.resize((w, h), Image.LANCZOS)
        img.paste(lg, ((img.width - w) // 2, int(205 * scale) - h // 2), lg)
        d.text((W // 2, 300), "v 7", font=font(14, True), fill=(125, 130, 146), anchor="mm")
    elif os.path.exists(path):
        m = Image.open(path).convert("L")
        k = min(300 / m.height, 560 / m.width) * scale; w, h = int(m.width * k), int(m.height * k)
        m = m.resize((w, h), Image.LANCZOS)
        top, bot = np.array((236, 238, 246), float), np.array((140, 146, 162), float)    # light to dark silver, top to bottom
        f = np.linspace(0, 1, h)[:, None]
        grad = (top[None, :] * (1 - f) + bot[None, :] * f).astype(np.uint8)
        img.paste(Image.fromarray(np.repeat(grad[:, None, :], w, axis=1)), ((img.width - w) // 2, int((40 + 150) * scale) - h // 2), m)
        d.text((W // 2, 372), "M O N O L I T H   v 7", font=font(13, True), fill=(140, 144, 156), anchor="mm")
    else:
        d.text((W // 2, 200), "MONOLITH", font=font(44, True), fill=(228, 231, 238), anchor="mm")
        d.text((W // 2, 250), "v 7", font=font(16, True), fill=(125, 130, 146), anchor="mm")
    if progress is not None:
        d.rounded_rectangle([300, 400, 500, 406], 3, outline=(62, 66, 84))
        d.rounded_rectangle([300, 400, 300 + int(200 * max(0.0, min(1.0, progress))), 406], 3, fill=(255, 150, 30))
    if status: d.text((W // 2, 430), status, font=font(11), fill=(120, 122, 132), anchor="mm")
    return img


class Renderer:
    def __init__(self, ctl, scale=1.0):
        """scale: draw the 800 x 500 layout this many times bigger (1.6 on a 1280 x 800 panel), sharp, not upscaled.
        Touch regions stay in 800 x 500 coordinates either way."""
        self.c, self.e = ctl, ctl.e
        self.scale = scale
        self.img = Image.new("RGB", (int(round(W * scale)), int(round(H * scale))), BG)
        self.d = ScaledDraw(ImageDraw.Draw(self.img), scale)
        self._hits = []

    # ------------------------------------------------------------ the skin (skin.py): sprites placed in layout units
    def P(self, v): return int(round(v * self.scale))

    def put(self, sprite, x, y, off=0, offy=None):
        """paste a skin sprite whose top-left (ignoring its shadow padding `off`) goes at layout (x, y)"""
        self.img.paste(sprite, (self.P(x) - off, self.P(y) - (off if offy is None else offy)), sprite)

    def keycap(self, rect, state="up", r=6, accent=None):
        x0, y0, x1, y1 = rect
        sp, ox, oy = skin.key(max(4, self.P(x1) - self.P(x0)), max(4, self.P(y1) - self.P(y0)), self.P(r), state, accent or ORANGE)
        self.put(sp, x0, y0, ox, oy)

    def plate(self, rect, r=10):
        x0, y0, x1, y1 = rect
        sp, ox, oy = skin.plate(self.P(x1) - self.P(x0), self.P(y1) - self.P(y0), self.P(r))
        self.put(sp, x0, y0, ox, oy)

    def well(self, rect, r=7, fill=skin.WELL_C, depth=9):
        x0, y0, x1, y1 = rect
        self.put(skin.well(self.P(x1) - self.P(x0), self.P(y1) - self.P(y0), self.P(r), fill, depth), x0, y0)

    def glassbox(self, rect, r=6, warm=False):
        x0, y0, x1, y1 = rect
        self.put(skin.glass(self.P(x1) - self.P(x0), self.P(y1) - self.P(y0), self.P(r), warm), x0, y0)

    LAB_MIN = 6.4               # smallest tracked label (layout units): ~1.3 mm capitals on the 10.1 inch panel

    def lab(self, x, y, txt, size=7, color=skin.LAB, anchor="la", weight="s", spacing=0.14, floor=None, maxw=None):
        """a letter-spaced panel label; anchor l/m/r + a/m. Never smaller than LAB_MIN unless a tight spot passes floor.
        maxw (layout units): the room it has - on a small screen (where the font's 7 px minimum makes it run wide) it is
        tightened, then made smaller, so it never spills out of its key"""
        size = max(size, self.LAB_MIN if floor is None else floor)
        im = skin.tracked(txt, self.P(size), weight, color, spacing)
        if maxw is not None and im.width > self.P(maxw):
            im = skin.tracked(txt, self.P(size), weight, color, 0.0)
            if im.width > self.P(maxw):
                k = self.P(maxw) / float(im.width)
                im = skin.cached(("labfit", txt, self.P(size), weight, color, self.P(maxw)),
                                 lambda im=im, k=k: im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS))
        px, py = self.P(x), self.P(y)
        if anchor[0] == "m": px -= im.width // 2
        elif anchor[0] == "r": px -= im.width
        if anchor[1] == "m": py -= im.height // 2
        self.img.paste(im, (px, py), im)

    def note(self, x, y, txt, anchor="lm", col=(138, 144, 156)):
        """a line of help text: sentence case, readable size"""
        self.t(x, y, txt, 9, False, col, anchor)

    def title(self, txt, sub=None, x=10, y=52, size=15):
        """a page title: Inter, with an optional tracked accent label after it; returns where the line ends"""
        self.t(x, y, txt, size, True, (240, 242, 246), "lm")
        x += self.d.textlength(txt, font=font(size, True))
        if sub:
            im = skin.tracked(sub, self.P(6.6), "s", ORANGE, 0.14)
            self.lab(x + 10, y + 1, sub, 6.6, ORANGE, "lm", "s", 0.14); x += 10 + im.width / self.scale
        return x

    def row(self, rect, sel=False, live=False, alt=False, r=5):
        """a list row inside a well: the chosen one is a lit key, a playing one glows green, others alternate faintly"""
        x0, y0, x1, y1 = rect
        if sel: self.keycap(rect, "lit", r, GREEN if live else None)
        elif live: self.keycap(rect, "lit", r, GREEN)
        elif alt: self.d.rounded_rectangle([x0, y0, x1, y1], r, fill=(27, 29, 34))

    def tile(self, rect, base, strength, r=7):
        """a raised key tinted with a colour (pad-mode tiles, track tiles); returns the colour its face reads as"""
        x0, y0, x1, y1 = rect
        top = mix(skin.KEY_TOP, base, strength); bot = mix(skin.KEY_BOT, base, strength * 0.75)
        glow = (base, 9, 0.22) if strength >= 0.5 else None
        sp, ox, oy = skin.body(self.P(x1) - self.P(x0), self.P(y1) - self.P(y0), self.P(r), top, bot, 0.1, 0.35, (8, 0.5), None, glow)
        self.put(sp, x0, y0, ox, oy)
        return mix(top, bot, 0.5)

    def field(self, rect, label, value, sel=False, lab_w=None, vsize=13, vcol=None):
        """a settings row: label (tracked) on the left, value in Inter; the chosen row is a lit key"""
        x0, y0, x1, y1 = rect
        if sel: self.keycap(rect, "lit", 5)
        else: self.well(rect, 5, (23, 25, 29), 5)
        cy = (y0 + y1) / 2.0
        self.lab(x0 + 10, cy, label.upper(), 5.8, (255, 255, 255) if sel else skin.LAB, "lm", "s", 0.12)
        if value is not None:
            self.t(x0 + (lab_w or 140), cy, value, vsize, True, vcol or ((250, 251, 253) if sel else (214, 218, 226)), "lm")

    def scrollbar(self, x, y0, y1, top, rows, n):
        if n <= rows: return
        h = max(14, (y1 - y0) * rows / float(n)); yy = y0 + (y1 - y0 - h) * top / float(max(1, n - rows))
        self.d.rounded_rectangle([x, yy, x + 4, yy + h], 2, fill=ORANGE)

    def seg(self, x0, y0, x1, y1, labels, sel, pick, size=6.2):
        """a segmented switch: keys in a sunk strip, the chosen one pressed in with its LED lit"""
        self.well((x0, y0, x1, y1), 6, (22, 24, 28), 5)
        n = len(labels); w = (x1 - x0 - 6 - 3 * (n - 1)) / float(n)
        for k, lab_ in enumerate(labels):
            bx = x0 + 3 + k * (w + 3); on_ = k == sel
            self.keycap((bx, y0 + 3, bx + w, y1 - 3), "down" if on_ else "up", 4.5)
            if on_: self.ledp(bx + 9, (y0 + y1) / 2, 3.4, True)
            self.lab(bx + w / 2 + (4 if on_ else 0), (y0 + y1) / 2, lab_, size, (244, 246, 249) if on_ else (140, 147, 160), "mm", "s", 0.1)
            self.hit((bx, y0, bx + w, y1), down=lambda *_, k=k: pick(k))

    def hmeter(self, x0, y0, x1, y1, level, nseg=64):
        """a row of LED segments, green / yellow / red to the right, lit up to `level`"""
        d = self.d
        w = (x1 - x0) / float(nseg); lit = int(round(clamp(level, 0, 1) * nseg))
        for k in range(nseg):
            f = (k + 1) / float(nseg)
            col = GREEN if f <= 0.65 else (YEL if f <= 0.88 else RED)
            d.rectangle([x0 + k * w + 0.4, y0, x0 + (k + 1) * w - 0.6, y1], fill=col if k < lit else mix((20, 22, 26), col, 0.09))

    def vmeter(self, x0, y0, x1, y1, level, nseg=22):
        """a column of LED segments, green / yellow / red from the bottom, lit up to `level` (0..1)"""
        d = self.d
        h = (y1 - y0) / float(nseg)
        lit = int(round(clamp(level, 0, 1) * nseg))
        for k in range(nseg):
            f = (k + 1) / float(nseg)
            col = GREEN if f <= 0.65 else (YEL if f <= 0.88 else RED)
            yb = y1 - k * h
            d.rectangle([x0, yb - h + 0.7, x1, yb - 0.3], fill=col if k < lit else mix((20, 22, 26), col, 0.09))

    def ledp(self, cx, cy, size, on, col=None):
        sp, pad = skin.led(self.P(size), on, col or ORANGE)
        self.img.paste(sp, (self.P(cx) - self.P(size) // 2 - pad, self.P(cy) - self.P(size) // 2 - pad), sp)

    RO_GRID = 11                                                      # Departure Mono is drawn on an 11 px grid

    def ro_px(self, size, txt="", maxw=None):
        """the readout font's pixel size for `size` layout units: a whole multiple of its 11 px grid, so every pixel of every
        letter lands on a screen pixel (sharp edges, nothing in between); smaller multiples if `txt` must fit in maxw"""
        k = max(1, int(round(self.P(size) / 14.0)))
        if maxw is not None and txt:
            while k > 1 and skin.face("departure", self.RO_GRID * k).getlength(txt) > self.P(maxw): k -= 1
        return self.RO_GRID * k

    def vt(self, x, y, txt, size, col, anchor="lm", glow=True, maxw=None):
        """a readout (the transport counter, BPM, status, MODERN's display) in Departure Mono, pixel-exact: no smoothing, no
        glow. (The name is from VT323, the font it replaced.) maxw (layout units): steps down a size to fit; a tiny spot that
        cannot take even the smallest whole size gets it smoothed down instead."""
        px_ = self.ro_px(size, txt, maxw)
        f = skin.face("departure", px_)
        if maxw is not None and f.getlength(txt) > self.P(maxw):              # (thumbnails): below 11 px, smoothed is the only way
            f = skin.face("departure", max(6, int(px_ * self.P(maxw) / f.getlength(txt))))
            ImageDraw.Draw(self.img).text((self.P(x), self.P(y)), txt, font=f, fill=col, anchor=anchor); return
        d = ImageDraw.Draw(self.img); d.fontmode = "1"
        d.text((self.P(x), self.P(y)), txt, font=f, fill=col, anchor=anchor)

    def dots(self, x, y, txt, k, col, anchor="la", ghost=None):
        sp, pad = skin.dot_text(txt, k, col, True, ghost)
        px, py = self.P(x) - pad, self.P(y) - pad
        w, h = sp.width - 2 * pad, sp.height - 2 * pad
        if anchor[0] == "m": px -= w // 2
        elif anchor[0] == "r": px -= w
        if anchor[1] == "m": py -= h // 2
        self.img.paste(sp, (px, py), sp)

    # ------------------------------------------------------------ plumbing
    MIN_TEXT = 9                 # smallest text, in layout units: 1.8 mm capitals on the 10.1 inch panel (readable at arm's length)

    def t(self, x, y, s, size=12, bold=False, fill=TEXT, anchor="la"):
        self.d.text((x, y), s, font=font(max(size, self.MIN_TEXT), bold), fill=fill, anchor=anchor)

    def hit(self, rect, down=None, drag=None):
        self._hits.append((tuple(int(v) for v in rect), down, drag))

    ICONS = ("<", ">", "-", "+")

    def icon(self, kind, cx, cy, r, col, w=2):
        """small vector icons, the same everywhere: < > (chevrons), - +, play, stop, rec, folder, back"""
        d = self.d
        if kind == "<": d.line([(cx + r * 0.45, cy - r), (cx - r * 0.45, cy), (cx + r * 0.45, cy + r)], fill=col, width=w)
        elif kind == ">": d.line([(cx - r * 0.45, cy - r), (cx + r * 0.45, cy), (cx - r * 0.45, cy + r)], fill=col, width=w)
        elif kind == "-": d.line([(cx - r, cy), (cx + r, cy)], fill=col, width=w)
        elif kind == "+": d.line([(cx - r, cy), (cx + r, cy)], fill=col, width=w); d.line([(cx, cy - r), (cx, cy + r)], fill=col, width=w)
        elif kind == "play": d.polygon([(cx - r * 0.7, cy - r), (cx - r * 0.7, cy + r), (cx + r, cy)], fill=col)
        elif kind == "stop": d.rectangle([cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8], fill=col)
        elif kind == "rec": d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    def btn(self, rect, label, down, size=12, fill=PANEL2, color=TEXT, outline=LINE, on=False, grow=0):
        """button; `grow` enlarges the touch area beyond the drawn shape (for small buttons in tight layouts).
        A label that is just < > - or + is drawn as an icon, so arrows and steppers look the same on every page."""
        x0, y0, x1, y1 = rect
        rr = min(6, (y1 - y0) / 3.5)
        if fill == PANEL2 and outline == LINE:                         # the standard button: a key cap (lit when on)
            self.keycap(rect, "lit" if on else "up", rr)
        elif fill != PANEL2 or on:                                     # a coloured state (mute red, solo yellow...): a key lit in it
            self.keycap(rect, "lit", rr, outline if outline != LINE else ORANGE)
        else: self.keycap(rect, "up", rr)
        col = (255, 255, 255) if on else color
        if label in self.ICONS:
            self.icon(label, (x0 + x1) / 2.0, (y0 + y1) / 2.0, max(3.0, min(7.0, (y1 - y0) * 0.22, (x1 - x0) * 0.25)), col, 2)
        elif len(label) > 2 and (label.startswith("< ") or label.endswith(" >")):     # "< CHOP", "CHOP >": text with an arrow icon
            txt = label[2:] if label.startswith("< ") else label[:-2]
            w = self.d.textlength(txt, font=font(max(size, self.MIN_TEXT), True))
            mid, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            r = max(3.0, min(5.0, (y1 - y0) * 0.18))
            if label.startswith("< "): self.icon("<", mid - w / 2 - 4, cy, r, col); self.t(mid + 6, cy, txt, size, True, col, "mm")
            else: self.icon(">", mid + w / 2 + 4, cy, r, col); self.t(mid - 6, cy, txt, size, True, col, "mm")
        else:
            self.t((x0 + x1) // 2, (y0 + y1) // 2, label, size, True, col, "mm")
        self.hit((x0 - grow, y0 - grow, x1 + grow, y1 + grow), down=lambda *_: down())

    def frame(self):
        d, c = self.d, self.c
        self._hits = []
        try: c.tick()                                     # AUTOSAVE (settingspage)
        except Exception as ex: print("tick:", ex)
        global ORANGE
        ORANGE = skin.ACCENTS.get(self.e.machine, skin.ACCENTS["MODERN"])     # the chassis takes its light from the machine
        self.img.paste(skin.page_bg(self.img.width, self.img.height), (0, 0))
        getattr(self, "screen_" + c.mode.lower())()
        if c.kbd is not None: self.keyboard()
        if c.editor_fx is None: self.soft_row()          # with a plug-in window open, its title bar labels the F-keys instead
        self.qlink_strip()
        if c.confirm is not None: self.confirm_box()
        if c.show_legend(): self.legend()
        if c.editor_fx is not None: self.editor_backdrop()
        self.top_bar()
        c.hits = self._hits
        for p in self.e.all_pads_cache():
            p.meter *= 0.82
        for i in range(16): self.e.track_meter[i] *= 0.85
        return self.img

    # ------------------------------------------------------------ shared pieces
    def top_bar(self):
        d, e, c = self.d, self.e, self.c
        if c.editor_fx is not None: d.rectangle([0, 0, W, TOP_H], fill=PANEL); self.editor_title()
        else: self.tabs()
        self.transport()

    def editor_title(self):
        """while a plug-in window is open the tab row becomes its title bar, with a big CLOSE button"""
        d, c = self.d, self.c
        v = c.editor_view or {}
        where = c.editor_where or "?"
        self.t(10, 12, (v.get("name") or c.editor_fx.name)[:20], 13, True, CYAN, "lm")
        pw, ph = v.get("px", (0, 0))
        self.t(10, 27, f"on {where}   {pw} x {ph}" + ("   drag the bars" if (v.get("hbar") or v.get("vbar")) else ""), 9, False, DIM, "lm")
        z = v.get("zoom", 1.0)                                        # zoom: - 100% + FIT  (= F2 F3 F4, CLOSE = F1)
        zx = 290                                                      # each button wide enough that its F-key tag clears the symbol
        self.btn((zx, 4, zx + 44, 31), "-", lambda: c.editor_zoom("out"), 16, grow=3)
        self.t(zx + 72, 18, f"{z * 100:.0f}%", 13, True, TEXT if v.get("can_zoom", True) else DIM, "mm")
        self.hit((zx + 46, 0, zx + 98, TOP_H), down=lambda *_: c.editor_zoom(1.0))     # tap the % = back to 100 %
        self.btn((zx + 100, 4, zx + 144, 31), "+", lambda: c.editor_zoom("in"), 16, grow=3)
        self.btn((zx + 152, 4, zx + 222, 31), "FIT", lambda: c.editor_zoom("fit"), 11, grow=3)
        for fx_, lab in ((zx + 3, "F2"), (zx + 103, "F3"), (zx + 155, "F4")):
            self.t(fx_, 5, lab, 9, False, (150, 154, 170), "la")
        x0, x1 = 520, 608
        d.rounded_rectangle([x0, 4, x1, 31], 6, fill=(110, 30, 30), outline=RED)
        cx, cy = x0 + 16, 18
        d.line([cx - 6, cy - 6, cx + 6, cy + 6], fill=TEXT, width=3); d.line([cx - 6, cy + 6, cx + 6, cy - 6], fill=TEXT, width=3)
        self.t(x0 + 52, 19, "CLOSE", 11, True, TEXT, "mm")
        self.t(x1 - 4, 5, "F1", 9, False, (230, 190, 190), "ra")
        self.hit((x0 - 6, 0, x1 + 4, TOP_H), down=lambda *_: setattr(c, "editor_req", "close"))

    TAB_X0, TAB_W, TAB_GAP = 10, 51.0, 2.4                    # the tab keys, in their well (eleven, MENU last)

    def tabs(self):
        d, e, c = self.d, self.e, self.c
        self.well((7, 5, 600, 37), 8, (23, 25, 29), 6)
        for i, name in enumerate(TABS):
            x = self.TAB_X0 + i * (self.TAB_W + self.TAB_GAP)
            on = name == TAB_OF.get(c.mode, c.mode)
            self.keycap((x, 7.5, x + self.TAB_W, 34.5), "down" if on else "up", 5.5)
            sp, pad = skin.bar_led(self.P(11), max(2, self.P(1.9)), on, ORANGE)
            self.img.paste(sp, (self.P(x + self.TAB_W / 2) - self.P(5.5) - pad, self.P(11) - pad), sp)
            self.lab(x + self.TAB_W / 2, 23.5, name, 7.4, (244, 246, 249) if on else (154, 161, 174), "mm", "s", 0.08, maxw=self.TAB_W - 4)
            self.hit((x - 1, 0, x + self.TAB_W + 1, TOP_H + 2), down=lambda *_, n=name: c.set_mode(n))

    def transport(self):
        d, e, c = self.d, self.e, self.c
        # the counter: a dark glass box with the transport LED, its state, bar.beat.tick in dots, and the tempo
        state, col = self.transport_state()
        x0, y0, x1, y1 = 606, 5, 794, 37
        self.glassbox((x0, y0, x1, y1), 8)
        lit = e.playing or e.rec != "off"
        self.ledp(x0 + 11, (y0 + y1) / 2, 6.5, lit, (92, 240, 138) if state == "PLAY" else col)
        self.lab(x0 + 20, y0 + 5, state, 6.2, col if lit else (124, 132, 148), "la", "s", 0.14)
        bar, beat = self.bar_beat()
        tick = int(e.pos % e.seq.beat_ticks) if e.pos >= 0 else 0
        pos = f"{bar:03d}.{beat}.{tick * 100 // max(1, e.seq.beat_ticks):02d}" if isinstance(bar, int) else f"{bar}.{beat}"
        k = max(2, self.P(1.55))
        now = time.time()
        lvl = getattr(e, "msg_level", "info")
        hold = (2.2 if lvl == "warn" else 1.6) + max(0, len(e.msg) - 13) / 9.0 + 0.6   # long ones scroll, so they stay longer
        if e.msg and lvl in ("info", "warn") and now - e.msg_time < hold:      # status: a dot-matrix line in the glass, then back
            self.status_line(e.msg, x0 + 20, y0 + 22.5, x1 - 66, now - e.msg_time, (255, 190, 90) if lvl == "warn" else (233, 245, 236))
        else:
            self.vt(x0 + 20, y0 + 22, pos, 19, (233, 245, 236) if e.pos >= 0 else YEL, "lm", maxw=x1 - 66 - (x0 + 20))
        if lvl == "save" and now - e.msg_time < 1.6:                           # saved: a disk icon blinks twice
            if int((now - e.msg_time) * 5) % 2 == 0: self.disk_icon(x1 - 70, y0 + 20, (233, 245, 236))
        elif e.unsaved(): self.disk_icon(x1 - 70, y0 + 20, (255, 170, 60))   # unsaved changes: an amber disk until it is saved
        warn_on = now - getattr(e, "warn_time", 0.0) < 20.0
        self.ledp(x1 - 70, y0 + 7, 3.5, warn_on, (255, 170, 60))               # warning LED: stays lit for a while
        if c.midi_io is not None and c.midi_io.names:                       # MIDI keyboard connected: a dot, lit on activity
            self.ledp(x1 - 78, y0 + 7, 3.5, now - c.midi_seen < 0.25, CYAN)
        d.line([x1 - 62, y0 + 6, x1 - 62, y1 - 6], fill=(40, 44, 50))
        self.hit((600, 0, x1 - 63, TOP_H), down=lambda *_: e.stop() if e.playing else e.play())
        self.lab(x1 - 11, y0 + 5, "BPM", 6.2, (127, 135, 149), "ra", "s", 0.14)            # (the same margin as the counter)
        self.vt(x1 - 11, y0 + 22, f"{e.seq.bpm:5.1f}".strip(), 18, (233, 245, 236), "rm", maxw=48)
        self.hit((x1 - 62, 0, 800, TOP_H), down=lambda *_: self.c.tap())
        if e.playing or e.rec != "off": d.rectangle([x0 + 10, y1 + 1, x1 - 10, y1 + 2], fill=col)

    def status_line(self, text, x0, y, x1, age, col):
        """a status message as small dot-matrix text in the glass; longer ones scroll once, then hold the end"""
        size = 13
        cw = skin.face("departure", self.ro_px(size)).getlength("M") / self.scale    # one character, layout units (monospaced)
        room = int((x1 - x0) / cw)
        txt = text.upper()
        if len(txt) > room:
            extra = len(txt) - room
            start = min(extra, max(0, int((age - 0.6) * 9)))                 # pause, then about 9 characters a second
            txt = txt[start:start + room]
        self.vt(x0, y, txt, size, col, "lm")

    def disk_icon(self, cx, cy, col):
        d = self.d
        d.rounded_rectangle([cx - 4, cy - 4, cx + 4, cy + 4], 1, outline=col, width=1)
        d.rectangle([cx - 2, cy - 4, cx + 2, cy - 1.5], fill=col); d.rectangle([cx - 2.5, cy + 1, cx + 2.5, cy + 4], fill=col)

    def editor_backdrop(self):
        """behind the plug-in's own window (which the X server draws on top): a dark panel, plus scroll bars when it is too big"""
        d, c = self.d, self.c
        d.rectangle([0, TOP_H, W, Q_Y - 1], fill=(6, 6, 9))
        self.t(400, (TOP_H + Q_Y) // 2, "opening the plug-in window...", 12, False, DIM, "mm")
        self.hit((0, TOP_H, W, Q_Y), down=lambda *_: None)                # the FX page underneath must not react to taps
        d.rectangle([0, Q_Y - 1, W, Q_Y + 1], fill=CYAN)
        v = c.editor_view
        if not v: return
        T = 16
        x0, y0, w, h = v["x"], v["y"], v["w"], v["h"]
        if v["vbar"]:                                                  # vertical bar on the right of the viewport
            bx0, by0, by1 = x0 + w, y0, y0 + h
            d.rectangle([bx0, by0, bx0 + T, by1], fill=PANEL, outline=LINE)
            th = max(28, h * h / v["ch"]); span = max(1e-6, v["ch"] - h)
            ty = by0 + (h - th) * v["sy"] / span
            d.rounded_rectangle([bx0 + 2, ty + 2, bx0 + T - 2, ty + th - 2], 5, fill=CYAN)
            def vdrag(px, py, th=th, by0=by0, span=span): c.editor_scroll_to(sy=(py - by0 - th / 2) / max(1.0, h - th) * span)
            self.hit((bx0 - 8, by0, bx0 + T + 8, by1), down=vdrag, drag=vdrag)
        if v["hbar"]:                                                  # horizontal bar under the viewport
            bx0, bx1, by0 = x0, x0 + w, y0 + h
            d.rectangle([bx0, by0, bx1, by0 + T], fill=PANEL, outline=LINE)
            tw = max(28, w * w / v["cw"]); span = max(1e-6, v["cw"] - w)
            tx = bx0 + (w - tw) * v["sx"] / span
            d.rounded_rectangle([tx + 2, by0 + 2, tx + tw - 2, by0 + T - 2], 5, fill=CYAN)
            def hdrag(px, py, tw=tw, bx0=bx0, span=span): c.editor_scroll_to(sx=(px - bx0 - tw / 2) / max(1.0, w - tw) * span)
            self.hit((bx0, by0 - 8, bx1, by0 + T + 8), down=hdrag, drag=hdrag)

    def transport_state(self):
        e = self.e
        if e.playing and e.pos < 0: return "COUNT-IN", YEL
        if e.playing and e.rec == "rec": return "REC", RED
        if e.playing and e.rec == "over": return "OVERDUB", ORANGE
        if e.playing: return "PLAY", GREEN
        if e.rec != "off": return "REC ARMED", RED
        return "STOPPED", DIM

    def bar_beat(self):
        e, sq = self.e, self.e.seq
        if e.pos < 0: return "-" + str(int(-e.pos // sq.bar_ticks) + 1), 1
        return int(e.pos // sq.bar_ticks) + 1, int((e.pos % sq.bar_ticks) // sq.beat_ticks) + 1

    def soft_row(self):
        """the four soft keys, drawn by what they do (see the grammar in uicore.py): an action is a plain label, a toggle has
        a light, a setting shows its name over its value, a page jump ends in an arrow, BACK starts with one (always F4)"""
        c, d = self.c, self.d
        y0, y1 = SOFT_Y
        cy = (y0 + y1) / 2.0
        for i, lab in enumerate(c.soft_labels()):
            x0, x1 = 8 + i * 198, 8 + i * 198 + 190
            if not lab:
                self.well((x0, y0, x1, y1), 8, (30, 32, 37), 5); continue
            if isinstance(lab, tuple) and len(lab) == 2 and isinstance(lab[1], bool): lab = T(lab[0], lab[1])     # old (text, on)
            kind = "A" if isinstance(lab, str) else lab[0]
            hot = kind == "H" or (kind == "T" and lab[2])
            self.keycap((x0, y0, x1, y1), "up", 7.5)
            col = (231, 234, 240)
            mid = (x0 + x1) / 2.0
            if kind == "A":
                txt = lab
                if txt.startswith("< "):
                    txt = txt[2:]; w = d.textlength(txt, font=font(12, True)); self.icon("<", mid - w / 2 - 12, cy, 5, col)
                elif txt.endswith(" >"):
                    txt = txt[:-2]; w = d.textlength(txt, font=font(12, True)); self.icon(">", mid + w / 2 + 12, cy, 5, col)
                self.lab(mid, cy + 0.5, txt, 8.6, col, "mm", "s", 0.1)
            elif kind == "H": self.lab(mid, cy + 0.5, lab[1], 8.6, (255, 255, 255), "mm", "s", 0.1)
            elif kind == "T": self.lab(mid, cy + 0.5, lab[1], 8.6, col, "mm", "s", 0.1)
            elif kind == "C":
                self.lab(mid, y0 + 11, lab[1], 6, skin.LAB, "mm", "s", 0.14)
                self.lab(mid, y0 + 25, lab[2], 8.6, col, "mm", "s", 0.06)
            elif kind == "P":
                w = d.textlength(lab[1], font=font(12, True))
                self.lab(mid - 5, cy + 0.5, lab[1], 8.6, col, "mm", "s", 0.1); self.icon(">", mid + w / 2 + 8, cy, 5, col)
            elif kind == "B":
                w = d.textlength("BACK", font=font(12, True))
                self.icon("<", mid - w / 2 - 6, cy, 5, col); self.lab(mid + 6, cy + 0.5, "BACK", 8.6, col, "mm", "s", 0.1)
            if kind in ("T", "H"): self.ledp(x1 - 11, y0 + 7.5, 4.2, hot)
            self.hit((x0, y0, x1, y1), down=lambda *_, i=i: c.soft(i))
            self.lab(x0 + 8, y0 + 5, f"F{i + 1}", 5.6, skin.LAB, "la", "s", 0.1)

    def qlink_strip(self):
        d, c = self.d, self.c
        self.img.paste(skin.strip_bg(self.img.width, self.img.height - self.P(Q_Y + 1)), (0, self.P(Q_Y + 1)))
        d.line([0, Q_Y + 1, W, Q_Y + 1], fill=(44, 47, 54))
        kd = self.P(38.75)
        for i, (label, get, _, fmt) in enumerate(c.qlinks()):
            x = i * 200
            if i: d.line([x, Q_Y + 2, x, H], fill=(31, 33, 38))
            cx, cy = x + 41, Q_Y + 41
            if label == "-":                                              # this knob does nothing on this screen
                sp, off = skin.knob(kd, 0.0, (70, 74, 90))
                self.img.paste(sp, (self.P(cx) - kd // 2 - off, self.P(cy) - kd // 2 - off), sp)
                self.lab(x + 80, Q_Y + 24, f"Q{i + 1}", 6.2, (80, 84, 96), "la", "s", 0.14)
                self.t(x + 80, Q_Y + 34, "not used here", 12, False, (80, 84, 96))
                continue
            f = clamp(get(), 0.0, 1.0)
            sp, off = skin.knob(kd, f, ORANGE)
            self.img.paste(sp, (self.P(cx) - kd // 2 - off, self.P(cy) - kd // 2 - off), sp)
            self.lab(x + 80, Q_Y + 24, f"Q{i + 1}  {label.upper()}"[:26], 6.2, skin.LAB, "la", "s", 0.14)
            val = fmt()
            sz = 19 if d.textlength(val, font=font(19, True)) < 112 else (15 if d.textlength(val, font=font(15, True)) < 112 else 12)
            self.t(x + 80, Q_Y + 35, val, sz, True, (241, 243, 247))     # the value is always the real value: never greyed
            if c.pot_seen[i] and not c.armed[i]:                             # hardware knob not caught up yet: show where it is
                import math
                a = math.radians(135 + 270 * c.pot[i] / 127.0); r = 25
                px, py = cx + math.cos(a) * r, cy + math.sin(a) * r
                d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=YEL)
                self.t(x + 190, Q_Y + (62 if i == 3 else 8), "turn to pick up", 10, False, YEL, "ra")
            def qdrag(px, py, i=i, x=x):
                v = clamp((px - (x + 12)) / 176.0, 0.0, 1.0)
                c.qlinks()[i][2](v); c.armed[i] = True; c.pot[i] = int(v * 127)
            self.hit((x, Q_Y, x + 200, H), down=qdrag, drag=qdrag)
        # Q-link mode pill (tap = next mode; SHIFT + jog push does the same): SCREEN follows the screen, the others stay put
        qm = c.qlink_mode
        on = qm != "SCREEN"
        self.keycap((712, Q_Y + 7, 794, Q_Y + 23), "lit" if on else "up", 5)
        self.lab(753, Q_Y + 15.5, "Q: " + qm, 5.8, (255, 255, 255) if on else skin.LAB, "mm", "s", 0.1)
        self.hit((700, Q_Y, 800, Q_Y + 34), down=lambda *_: c.cycle_qlink())

    def confirm_box(self):
        """a question (ask() in ui.py): title, one line, answered on the soft keys below - F1 cancel, F4 the main answer"""
        d, c = self.d, self.c
        q = c.confirm
        x0, y0, x1, y1 = 150, 130, 650, 262
        self.hit((0, TOP_H, W, SOFT_Y[0] - 1), down=lambda *_: None)         # the page underneath does not react
        self.plate((x0, y0, x1, y1), 10)
        d.rounded_rectangle([x0, y0, x1, y1], 10, outline=mix((49, 52, 59), ORANGE, 0.6), width=1)
        self.lab(x0 + 18, y0 + 20, q["title"], 7.0, ORANGE, "lm", "s", 0.14)
        words, lines, cur = q["text"].split(), [], ""
        for w_ in words:                                                      # wrap to the box
            t_ = (cur + " " + w_).strip()
            if d.textlength(t_, font=font(13)) > x1 - x0 - 36 and cur: lines.append(cur); cur = w_
            else: cur = t_
        lines.append(cur)
        for k, ln in enumerate(lines[:3]):
            self.t(x0 + 18, y0 + 50 + k * 20, ln, 13, False, TEXT, "lm")
        self.note((x0 + x1) / 2, y1 - 16, "answer with the soft keys below", "mm")

    def legend(self):
        d, c = self.d, self.c
        d.rectangle([20, 44, 780, 372], fill=(8, 8, 12), outline=YEL, width=2)
        self.t(36, 52, "SHIFT +", 18, True, YEL)
        rows = c.legend()
        for k, (key, what) in enumerate(rows):
            col, r = k % 2, k // 2
            x, y = 36 + col * 370, 78 + r * 28
            d.rounded_rectangle([x, y, x + 120, y + 24], 5, fill=PANEL2, outline=LINE)
            self.t(x + 60, y + 12, key, 12, True, TEXT, "mm")
            self.t(x + 132, y + 12, what, 13, False, TEXT, "lm")
        self.t(400, 364, "release SHIFT to close", 11, False, DIM, "mm")

    def pad_tile(self, x, y, s, idx_in_bank, down=None, show_len=True):
        d, e = self.d, self.e
        n = e.bank * 16 + idx_in_bank
        p = e.prog.pads[n]
        S = self.P(s)
        if p.empty:                                                   # an empty pad: a darker, flatter cap
            sp, ox, oy = skin.body(S, S, self.P(6.5), (35, 38, 44), (31, 33, 38), 0.05, 0.25, (6, 0.4))
        else:
            sp, ox, oy = skin.key(S, S, self.P(6.5), "up", ORANGE)
        self.put(sp, x, y, ox, oy)
        hot = min(1.0, p.meter * 1.6) if not p.empty else 0.0
        if hot > 0.04:                                                # a hit lights the pad from inside
            q = min(8, int(hot * 8 + 0.5))
            gl = skin.cached(("padglow", S, q, ORANGE), lambda: self._pad_glow(S, q / 8.0))
            self.img.paste(gl, (self.P(x), self.P(y)), gl)
        if idx_in_bank == e.sel:
            d.rounded_rectangle([x - 0.5, y - 0.5, x + s + 0.5, y + s + 0.5], 7, outline=ORANGE, width=1.4)
        tc, td = ((246, 247, 250), (150, 156, 168)) if not p.empty else ((112, 118, 130), (86, 91, 102))
        if p.mute: tc = (120, 124, 134)
        self.t(x + 8, y + 7, f"{BANKS[e.bank]}{idx_in_bank + 1:02d}", 10, True, tc)
        if p.empty: self.lab(x + 8, y + s - 15, "EMPTY", 6.2, td, "la", "s", 0.14)
        else:
            name = (p.src.name if p.link is None else "chop %d" % (p.link[1] + 1)).replace("_", " ").strip()[:12].upper()
            self.lab(x + 8, y + s - (25 if show_len else 15), name, 6.2, (214, 218, 226), "la", "s", 0.1)
            if show_len: self.t(x + 8, y + s - 15, f"{p.length / OUT_SR:.2f} s", 9, False, td)
        if p.mute: self.t(x + s - 7, y + 6, "M", 10, True, RED, "ra")
        if p.solo: self.t(x + s - 7, y + 18, "S", 10, True, YEL, "ra")
        if p.link: self.ledp(x + s - 8, y + s - 8, 3, True, CYAN)
        if p.warp and not p.empty: self.t(x + s - 7, y + 30, "W", 9, True, CYAN, "ra")
        self.hit((x, y, x + s, y + s), down=down or (lambda *_, i=idx_in_bank: (self.c.select(i), e.pad_hit(i + 1, 100))))

    def _pad_glow(self, S, f):
        import numpy as np_
        yy, xx = np_.mgrid[0:S, 0:S].astype(float)
        r = np_.sqrt((xx - S * 0.5) ** 2 + (yy - S * 0.42) ** 2) / (S * 0.55)
        a = np_.clip(1 - r, 0, 1) ** 1.6 * 200 * f
        m = Image.fromarray(a.astype(np_.uint8), "L")
        out = Image.new("RGBA", (S, S), ORANGE + (0,)); out.putalpha(m)
        return out

    def mode_tile(self, x, y, s, i, pm=None, down=None):
        """a pad tile in one of the pad modes (16 LEVELS / PERFORM / TRACK MUTE / NEXT SEQ): shows what pad i+1 does"""
        d, e, c = self.d, self.e, self.c
        n, pm = i + 1, pm or e.pad_mode
        flash = time.time() - c.pad_flash.get(n, 0) < 0.15
        base, top, sub, lit, mark = ROW_COLORS[i // 4], f"{n:02d}", "", False, ""
        if pm == "16 LEVELS":
            if e.levels_param == "VELOCITY": top, sub = f"vel {max(1, round(n * 127 / 16))}", "velocity"
            else: top, sub = f"{n - 9:+d} st", "tune"
            base = mix((60, 60, 70), ORANGE, n / 16.0)
        elif pm == "PERFORM":
            notes = e.perform_notes(n)
            top = note_name(notes[0]); sub = "+".join(note_name(x)[:-1] for x in notes[1:]) if len(notes) > 1 else ""
            lit = (notes[0] - e.perf_root) % 12 == 0                    # the key's root notes stand out
            base = CYAN if lit else (60, 110, 140)
        elif pm == "TRACK MUTE":
            tr = e.seq.tracks[i]
            top, sub = tr.name[:9], ("MUTED" if tr.mute else ("SOLO" if tr.solo else ("empty" if not tr.events else KIND_NAMES[tr.kind])))
            base = (120, 36, 36) if tr.mute else ((170, 140, 30) if tr.solo else (TRACK_COLORS[i % 8] if tr.events else (40, 44, 56)))
            lit = not tr.mute and bool(tr.events)
        elif pm == "NEXT SEQ":
            sq = e.seqs[i]
            used = any(t.events for t in sq.tracks)
            top, sub = sq.name, ("PLAYING" if i == e.cur_seq else ("NEXT" if e.next_seq == i else ("" if used else "empty")))
            base = GREEN if i == e.cur_seq else (ORANGE if e.next_seq == i else ((70, 110, 230) if used else (40, 44, 56)))
        strong = lit or pm in ("16 LEVELS", "NEXT SEQ") or (pm == "TRACK MUTE" and (tr.mute or tr.solo or bool(tr.events)))
        st_ = 0.62 if strong else 0.22
        if flash: base, st_ = mix(base, (255, 255, 255), 0.5), 0.85
        fill = self.tile((x, y, x + s, y + s), base, st_)
        if pm == "NEXT SEQ" and e.next_seq == i and int(time.time() * 4) % 2:
            d.rounded_rectangle([x - 2, y - 2, x + s + 2, y + s + 2], 8, outline=ORANGE, width=3)
        if pm == "16 LEVELS" and n == 9 and e.levels_param == "TUNE":
            d.rounded_rectangle([x - 2, y - 2, x + s + 2, y + s + 2], 8, outline=ORANGE, width=2)
        self.t(x + s // 2, y + s // 2 - 6, top, 13 if len(top) < 8 else 10, True, ink(fill), "mm")
        if sub: self.lab(x + s / 2, y + s - 13, sub[:12].upper(), 5.0, ink_dim(fill), "mm", "s", 0.1)
        self.lab(x + 6, y + 8, f"{n}", 5.2, ink_dim(fill), "lm", "s", 0.05)
        self.hit((x, y, x + s, y + s), down=down or (lambda *_, n=n: c.pad_hit(n, 100)))

    def pad_grid(self, x0, y0, s=76, step=80):
        """the 16 pads as they lie on the hardware (pad 1 bottom left); in a pad mode they show what each pad does"""
        for r in range(4):
            for col in range(4):
                i = (3 - r) * 4 + col
                if self.e.pad_mode == "NORMAL": self.pad_tile(x0 + col * step, y0 + r * step, s, i)
                else: self.mode_tile(x0 + col * step, y0 + r * step, s, i)

    def bank_buttons(self, x, y, w=30, h=72, gap=6):
        e = self.e
        for b in range(4):
            yy = y + b * (h + gap)
            self.btn((x, yy, x + w, yy + h), BANKS[b], lambda b=b: setattr(e, "bank", b), 14, on=(b == e.bank))

    def waveform(self, rect, src, a, b, region=None, markers=(), cursor=None, play=None, colors=(CYAN, (40, 70, 90))):
        d = self.d
        x0, y0, x1, y1 = rect
        self.glassbox(rect, 5)
        if colors == (CYAN, (40, 70, 90)): colors = (ORANGE, mix((14, 16, 20), ORANGE, 0.28))   # the accent, dim outside the region
        cy, hh, width = (y0 + y1) // 2, (y1 - y0) // 2 - 4, x1 - x0 - 2
        for gx in range(int(x0) + 25, int(x1), 25): d.line([gx, y0 + 2, gx, y1 - 2], fill=(26, 31, 38))
        d.line([x0 + 1, cy, x1 - 1, cy], fill=(42, 49, 59))
        if src is None or src.length < 4:
            self.t((x0 + x1) // 2, cy, "no sample on this pad", 14, False, DIM, "mm"); return
        mins, maxs = src.envelope(width, a, b)
        for i in range(width):
            pos = a + (b - a) * i / width
            inside = region is None or region[0] <= pos <= region[1]
            d.line([x0 + 1 + i, cy - int(maxs[i] * hh) - 1, x0 + 1 + i, cy - int(mins[i] * hh) + 1], fill=colors[0] if inside else colors[1])
        tx = lambda s: x0 + 1 + (s - a) / float(b - a) * width
        for k, m in enumerate(markers):
            if a <= m <= b: d.line([tx(m), y0 + 1, tx(m), y1 - 1], fill=(232, 236, 242), width=1.4)
        if cursor is not None and a <= cursor <= b: d.line([tx(cursor), y0 + 1, tx(cursor), y1 - 1], fill=YEL, width=2)
        if play is not None and a <= play <= b: d.line([tx(play), y0 + 1, tx(play), y1 - 1], fill=(255, 255, 255))
        return tx

    # ------------------------------------------------------------ MAIN
    def screen_main(self):
        d, e, c = self.d, self.e, self.c
        self.pad_grid(10, 48)
        if e.pad_mode in ("NORMAL", "16 LEVELS"): self.bank_buttons(338, 48, 34, 72, 8)
        x0, sq, tr = 386, e.seq, e.track
        import mainpanel
        mainpanel.panel(self)                                       # the machine's own front panel (MachinePanels artboard)
        if c.asr_on(): mainpanel.asr_keys(self)                     # the ASR keys take the track list's and the meter's room
        else:
            mainpanel.tracks(self, x0, sq)
            self.out_meter(x0)
        if c.mpick is not None: mainpanel.picker(self)

    def machine_panel(self, x0, y0, x1, y1):
        """the chosen machine's display in its bezel (machines.py builds the text, lcd.py draws the dots); its fields can be
        tapped, the arrows move the cursor and the jog wheel changes the field; tap the machine name to change machine"""
        import machines, lcd
        e, c, d = self.e, self.c, self.d
        scr = machines.screen(e, e.machine, c.lcd_cur)
        if scr is None: return False
        leg_h = 28 if scr.legends else 0                      # a fluorescent display's lit words above its characters
        st = machines.STYLE[e.machine]
        small, big, bez = machines.BEZEL[e.machine]
        sc = self.scale
        self.plate((x0, y0, x1, y1), 10)
        d.rounded_rectangle([x0 + 4, y0 + 4, x1 - 4, y1 - 4], 7, fill=bez)
        nw, nh = scr.cols * lcd.CW, scr.rows * st.row_h
        side = 80                                             # the column right of the display: printed name + logo
        aw, ah = (x1 - x0 - side - 14) * sc, (y1 - y0 - 12 - leg_h) * sc
        k = max(1, int(min(aw / nw, ah / nh)))
        if e.machine == "SP-1200": k = min(k, max(1, int(4 * sc / 1.6)))
        lw, lh = nw * k, nh * k                               # display size in screen pixels
        lx = int(round((x0 + 8) * sc)); ly = int(round(((y0 + y1) / 2.0 + leg_h / 2.0) * sc - lh / 2.0))
        keys = [f[0] for f in scr.fields]
        if c.lcd_cur not in keys: c.lcd_cur = next((k_ for k_ in keys if not k_.startswith("soft")), keys[0] if keys else None)
        cur = next(((r, col, n) for key, r, col, n in scr.fields if key == c.lcd_cur), None)
        img = lcd.render(scr.text(), scr.cols, st, k, inverse=scr.inverse, cursor=None if scr.legends else cur)
        pad = max(2, int(3 * sc))
        d.rounded_rectangle([lx / sc - 3, ly / sc - 3 - leg_h, (lx + lw) / sc + 2, (ly + lh) / sc + 2], 3, fill=st.bg)   # the glass
        self.img.paste(img, (lx, ly))
        if scr.legends:                                       # two rows of words, lit or dark, spread over the glass width
            half = (len(scr.legends) + 1) // 2
            for row, words in enumerate((scr.legends[:half], scr.legends[half:])):
                span = lw / sc - 4
                for i, (w, lit) in enumerate(words):
                    x = lx / sc + 2 + span * (i + 0.5) / len(words)
                    self.t(x, ly / sc - leg_h + 4 + row * 12, w, 8, True, st.on if lit else mix(st.ghost, st.on, 0.12), "mt")
        for key, r, col, n in scr.fields:                     # tap a field to put the cursor on it
            rx0, ry0 = (lx + col * lcd.CW * k) / sc, (ly + r * st.row_h * k) / sc
            rect = (rx0, ry0, rx0 + n * lcd.CW * k / sc, ry0 + st.row_h * k / sc)
            self.hit(rect, (lambda key_: lambda x, y: c.lcd_tap(key_))(key))
        tx = (lx + lw) / sc + 8
        plate = machines.PLATE.get(e.machine)
        if plate is not None:                                  # the name / badges sit on a lighter strip
            tx = x1 - 0.95 * (x1 - tx + 2)                                         # 95% of the space beside the display
            d.rounded_rectangle([tx, y0, x1, y1], 8, fill=plate)                   # right edge to edge, top to bottom
            d.rectangle([tx, y0, tx + 12, y1], fill=plate); bez = plate             # square where it meets the dark panel
        light = (196, 198, 204) if sum(bez) < 200 else (34, 36, 40)
        rx = x1 - (14 if plate is not None else 8)
        if not self.machine_badges(e.machine, tx + (6 if plate is not None else 0), y0 + (14 if plate is not None else 8), rx, y1 - 38):      # your own badge images, if you added them
            for i, ln in enumerate(small.split("|")): self.t(rx, y0 + 10 + i * 11, ln, 9, False, mix(light, bez, 0.35), "ra")
            self.t(rx, y0 + 40, big, 20 if len(big) < 6 else (16 if len(big) < 8 else 11), True, light, "ra")
        self.lab(rx, y1 - 27, "TAP TO CHANGE", 5.0, mix(light, bez, 0.45), "rm", "s", 0.14)
        self.lab(rx, y1 - 15, "MACHINE  >", 6.6, ORANGE, "rm", "s", 0.16)
        self.hit((tx, y0, x1, y1), lambda x, y: c.cycle_machine())
        return True

    _badge_cache = {}

    def badge_image(self, name):
        """badges/<name>.png (or .jpg) from the software's folder, as RGBA; None if there is none. Cached until the file changes."""
        base = os.path.join(getattr(self.e, "app_dir", "") or ".", "badges")
        for ext in (".png", ".PNG", ".jpg", ".jpeg", ".JPG"):
            path = os.path.join(base, name + ext)
            if os.path.isfile(path): break
        else: return None
        key = (path, os.path.getmtime(path), os.path.getsize(path))
        hit = Renderer._badge_cache.get(name)
        if hit is None or hit[0] != key:
            try: im = Image.open(path).convert("RGBA")
            except Exception: im = None
            hit = Renderer._badge_cache[name] = (key, im, {})
        return hit

    def machine_badges(self, machine, x0, y0, x1, y1):
        """Your own badge artwork beside the machine's display: badges/<MACHINE>_top.png (e.g. the maker's) above
        badges/<MACHINE>.png (the model), or either alone in the whole space. Not part of Monolith: add your own files.
        Returns False when there are none (the printed name shows instead)."""
        hits = [(n, self.badge_image(n)) for n in (machine + "_top", machine)]
        hits = [(n, h) for n, h in hits if h is not None and h[1] is not None]
        if not hits: return False
        sc = self.scale
        gap = 6
        boxes = [(y0, y1)] if len(hits) == 1 else [(y0, y0 + (y1 - y0 - gap) * 0.4), (y0 + (y1 - y0 - gap) * 0.4 + gap, y1)]
        for (n, (_, im, sized)), (by0, by1) in zip(hits, boxes):
            bw, bh = max(1, int((x1 - x0) * sc)), max(1, int((by1 - by0) * sc))
            f = min(bw / im.width, bh / im.height)
            w, h = max(1, int(im.width * f)), max(1, int(im.height * f))
            if (w, h) not in sized: sized.clear(); sized[(w, h)] = im.resize((w, h), Image.LANCZOS)
            px, py = int(x1 * sc) - w, int((by0 + by1) / 2.0 * sc - h / 2.0)       # right-aligned, like the printed name
            self.img.paste(sized[(w, h)], (px, py), sized[(w, h)])
        return True

    _logo_cache = {}

    def brand_logo(self, w, h):
        """brand/logo.png (brand/make_logo.py) fitted into w x h layout pixels, cached; None if there is none"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand", "logo.png")
        if not os.path.exists(path): return None
        key = (path, os.path.getmtime(path), int(w * self.scale), int(h * self.scale))
        hit = Renderer._logo_cache.get("logo")
        if hit is None or hit[0] != key:
            lg = Image.open(path).convert("RGBA"); bb = lg.getbbox(); lg = lg.crop(bb) if bb else lg
            k = min(key[2] / lg.width, key[3] / lg.height)
            hit = Renderer._logo_cache["logo"] = (key, lg.resize((max(1, int(lg.width * k)), max(1, int(lg.height * k))), Image.LANCZOS))
        return hit[1]

    MACHINE_CHIPS = ["MODERN", "MPC60", "MPC3000", "MPC2000XL", "SP-1200", "ASR-10"]

    def machine_chips(self, x0, y0, x1, y1):
        """the six machine keys (tap one to switch): each with an LED in its own colour"""
        e, c = self.e, self.c
        self.well((x0, y0, x1, y1), 6, (23, 25, 29), 5)
        cw, ch = (x1 - x0 - 8) / 3.0, (y1 - y0 - 7) / 2.0
        for i, m in enumerate(self.MACHINE_CHIPS):
            cx0 = x0 + 3 + (i % 3) * (cw + 1); cy0 = y0 + 3 + (i // 3) * (ch + 1)
            on = e.machine == m
            self.keycap((cx0, cy0, cx0 + cw - 1, cy0 + ch - 1), "down" if on else "up", 4)
            self.ledp(cx0 + 6.5, cy0 + ch / 2 - 0.5, 3.2, on, skin.ACCENTS[m])
            self.lab(cx0 + 11, cy0 + ch / 2 - 0.5, m.replace("MPC2000XL", "2000XL"), 4.9, (244, 246, 249) if on else (140, 147, 160), "lm", "s", 0.04, floor=4.9)
            self.hit((cx0, cy0, cx0 + cw, cy0 + ch), down=lambda *_, m=m: c.set_machine(m))

    def sequence_card(self, x0, sq, tr):
        """MODERN's panel, laid out like the classic machines': its own amber display on the left; the logo and the six
        machine keys on the right"""
        d, e, c = self.d, self.e, self.c
        x1, y0, y1 = 792, 46, 150
        self.plate((x0, y0, x1, y1), 10)
        gx0, gy0, gx1, gy1 = x0 + 7, y0 + 7, 654, y1 - 7                 # the glass
        self.glassbox((gx0, gy0, gx1, gy1), 6, warm=True)
        amber, dim = (255, 176, 102), (176, 112, 58)
        k3 = max(2, self.P(1.9)); k4 = max(3, self.P(2.55))
        k2 = max(2, self.P(1.3))
        cpx = lambda k: 6 * k / self.scale                                 # layout width of one character at k
        room = gx1 - gx0 - 18
        right = f"{sq.num}/{sq.den} {sq.bars} BARS"
        nmax = max(4, int((room - len(right) * cpx(k2) - 8) / cpx(k4)))
        self.dots(gx0 + 9, gy0 + 9, sq.name.upper()[:nmax], k4, amber)
        self.dots(gx1 - 9, gy0 + 14, right, k2, dim, "ra")
        self.dots(gx0 + 9, gy0 + 37, f"TRK {tr.n + 1:02d} {tr.name.upper()}"[:int(room / cpx(k3))], k3, amber)
        bottom = f"PGM {e.prog.name.upper()[:8]}  BANK {BANKS[e.bank]}  SWING {sq.swing * 100:.0f}%  Q {QUANT[e.qgrid][0]}  {'LOOP' if sq.loop else '1-SHOT'}"
        pm = e.pad_mode                                                    # PADS, small, in the glass's corner
        bx0, by0, by1 = gx1 - 80, gy1 - 19, gy1 - 5                      # PADS and MENU, small, in the glass's corner
        fit_ = int((bx0 - gx0 - 14) / cpx(k2))
        parts_ = [f"PGM {e.prog.name.upper()[:12]}", f"SW {sq.swing * 100:.0f}%", f"Q {QUANT[e.qgrid][0]}", "LOOP" if sq.loop else "1-SHOT"]
        while len(parts_) > 1 and len("  ".join(parts_)) > fit_: parts_.pop(-2 if len(parts_) > 2 else -1)
        self.dots(gx0 + 9, gy0 + 63, "  ".join(parts_)[:fit_], k2, dim)
        for kx0, kx1, txt, on, go in ((bx0, bx0 + 36, "PADS" if pm == "NORMAL" else pm[:4], pm != "NORMAL", "PADS"),
                                      (bx0 + 40, gx1 - 7, "MENU", False, "MENU")):
            d.rounded_rectangle([kx0, by0, kx1, by1], 3, fill=(70, 40, 14) if on else None, outline=amber if on else dim, width=1)
            self.dots((kx0 + kx1) / 2, (by0 + by1) / 2, txt, k2, amber if on else dim, "mm")
            self.hit((kx0, by0 - 3, kx1, by1 + 3), (lambda go_: lambda x, y: c.set_mode(go_))(go))
        rate = {48: "1/8", 24: "1/16", 12: "1/32"}.get(e.rep_div, "")     # status chips (no soft key for these here)
        flags = [(f"NOTE REPEAT {rate}", e.rep_on), ("SONG MODE", e.song_mode), ("ERASE HELD", c.erase_down),
                 (f"NEXT: SEQ {(e.next_seq or 0) + 1:02d}", e.next_seq is not None), ("PADS: " + pm, pm != "NORMAL")]
        xx = gx0 + 9
        for lab, on in flags:
            if not on: continue
            w = int(d.textlength(lab, font=font(8, True))) + 12
            if xx + w > gx1 - 8: break
            d.rounded_rectangle([xx, gy0 + 50, xx + w, gy0 + 60], 3, fill=(70, 40, 14), outline=amber)
            self.t(xx + w // 2, gy0 + 55, lab, 8, True, amber, "mm"); xx += w + 5
        rx0 = gx1 + 8
        lg = self.brand_logo(x1 - 8 - rx0, 20)                             # the logo, then the machine keys
        if lg is not None: self.img.paste(lg, (self.P((rx0 + x1 - 8) / 2) - lg.width // 2, self.P(y0 + 20) - lg.height // 2), lg)
        else: self.t((rx0 + x1 - 8) / 2, y0 + 20, "MONOLITH", 16, True, TEXT, "mm")
        self.machine_chips(rx0, y0 + 38, x1 - 7, y1 - 7)
        self.hit((rx0, y0, x1, y0 + 36), lambda x, y: c.cycle_machine())     # like the classic panels: tap the name plate

    def tracks_overview(self, x0, sq):
        d, e, c = self.d, self.e, self.c
        self.plate((x0, 158, 792, 330), 10)
        self.well((x0 + 6, 164, 786, 324), 7, (22, 24, 28), 8)
        page = e.cur_track // 8                                     # the 8 tracks around the selected one; tap the header for the others
        self.lab(x0 + 14, 171, f"TRACKS {page * 8 + 1}-{page * 8 + 8}", 6.2, skin.LAB, "la", "s", 0.16)
        bar, _ = self.bar_beat()
        self.lab(786 - 70, 171, f"BAR {bar} / {sq.bars}", 6.2, skin.LAB, "ra", "s", 0.16)
        self.btn((728, 168, 782, 182), f"{9 - page * 8}-{16 - page * 8}", lambda: setattr(e, "cur_track", (e.cur_track + 8) % 16), 9, grow=4)
        tx0, tx1 = x0 + 120, 778
        for k in range(page * 8, page * 8 + 8):
            t = sq.tracks[k]; y = 186 + (k % 8) * 17
            on = t.n == e.cur_track
            if on: d.rounded_rectangle([x0 + 10, y - 1, 782, y + 15], 4, fill=(36, 39, 45))
            self.t(x0 + 16, y + 7, f"{t.n + 1:02d}", 9, True, ORANGE if on else (95, 101, 113), "lm")
            self.t(x0 + 36, y + 7, t.name[:14], 10.5, on, (235, 238, 243) if t.events else (95, 101, 113), "lm")
            n = sq.length
            col = ORANGE if on else (150, 156, 166)
            for ev in t.events:
                px = tx0 + int(ev[0] / n * (tx1 - tx0))
                d.rounded_rectangle([px, y + 3, px + 2.2, y + 12], 0.6, fill=col if t.events else DIM)
            if t.mute: self.t(782, y + 7, "M", 9, True, RED, "rm")
            self.hit((x0 + 6, y - 1, 786, y + 16), down=lambda *_, k=k: setattr(e, "cur_track", k))
        if e.playing:
            px = tx0 + int(clamp(e.pos, 0, sq.length) / sq.length * (tx1 - tx0))
            d.rectangle([px - 1.2, 184, px + 1.2, 322], fill=mix((20, 22, 26), ORANGE, 0.25))
            d.rectangle([px - 0.4, 184, px + 0.4, 322], fill=ORANGE)
        self.out_meter(x0)

    def out_meter(self, x0):
        """output meter, left and right: segmented, like a hardware LED meter"""
        e, d = self.e, self.d
        self.plate((x0, 338, 792, 372), 10)
        self.well((x0 + 6, 343, 786, 367), 6, (20, 22, 26), 6)
        self.lab(x0 + 14, 355, "OUT", 6, skin.LAB, "lm", "s", 0.16)
        mx0, mx1 = x0 + 44, 780
        seg, gap = 5.0, 1.6
        nseg = int((mx1 - mx0) / (seg + gap))
        for k, v in enumerate((getattr(e, "meter_l", e.master_meter), getattr(e, "meter_r", e.master_meter))):
            yy = 347.5 + k * 9
            m = min(1.0, max(0.0, v)) ** 0.5
            lit = int(m * nseg + 0.5)
            for j in range(nseg):
                sx = mx0 + j * (seg + gap)
                f_ = j / nseg
                on_c = (75, 224, 131) if f_ < 0.75 else ((240, 210, 60) if f_ < 0.92 else (235, 80, 70))
                d.rectangle([sx, yy, sx + seg, yy + 5], fill=on_c if j < lit else (38, 48, 42))

    # ------------------------------------------------------------ GRID page: one header, two views    # ------------------------------------------------------------ GRID page: one header, two views
    def grid_header(self):
        """The GRID page's header, the same in both views: sequence < >, track < > and what it plays, bars, loop,
        the bottom-lane / view-length chip, and ALL TRACKS (lit in the all-tracks view; GRID key toggles it too)."""
        d, e, c = self.d, self.e, self.c
        sq, tr, allv = e.seq, e.track, c.mode == "SEQ"
        y0, y1 = 42, 66
        self.btn((6, y0, 34, y1), "<", lambda: e.select_seq(e.cur_seq - 1), 14, grow=3)
        self.t(40, 54, f"{e.cur_seq + 1:02d} {sq.name}"[:15], 12, True, TEXT, "lm")
        self.hit((36, y0 - 2, 158, y1 + 2), down=lambda *_: c.rename_seq())          # tap a name to rename it
        self.btn((160, y0, 188, y1), ">", lambda: e.select_seq(e.cur_seq + 1), 14, grow=3)
        self.btn((196, y0, 224, y1), "<", lambda: c.step_track(-1), 14, grow=3)
        self.t(230, 54, f"T{tr.n + 1:02d} {tr.name}"[:13], 12, True, TRACK_COLORS[tr.n % 8] if (tr.events or not allv) else DIM, "lm")
        self.hit((226, y0 - 2, 352, y1 + 2), down=lambda *_: c.rename_track())
        self.btn((354, y0, 382, y1), ">", lambda: c.step_track(1), 14, grow=3)
        # what the track plays, spelled out (the pads in the rows below are this program's): tap to change it
        plays = (f"PGM {e.programs[tr.prog].name}" if tr.kind == "drum" else self.track_type_label(tr)).upper()
        self.keycap((388, y0, 500, y1), "lit" if c.track_setup == tr.n else "up", 5)
        self.lab(394, 49, "PLAYS", 3.8, (130, 136, 148), "lm", "s", 0.12, floor=3.6)
        self.lab(394, 59, plays, 5.8, {"drum": TEXT, "keys": CYAN, "plugin": (200, 140, 255), "midi": YEL}[tr.kind], "lm", "s", 0.06,
                 floor=4.2, maxw=102)
        self.hit((388, y0 - 2, 500, y1 + 2), down=lambda *_: c.cycle_track_type(tr.n))
        self.btn((506, y0, 528, y1), "-", lambda: e.set_bars(sq.bars - 1), 14, grow=3)
        self.t(542, 49, str(sq.bars), 13, True, TEXT, "mm"); self.t(542, 62, "bars", 9, False, DIM, "mm")
        self.btn((556, y0, 578, y1), "+", lambda: e.set_bars(sq.bars + 1), 14, grow=3)
        self.btn((584, y0, 632, y1), "LOOP" if sq.loop else "1-SHOT", lambda: setattr(sq, "loop", not sq.loop), 10, on=sq.loop)
        if allv:
            self.btn((638, y0, 686, y1), f"{c.seq_bars} BAR" + ("S" if c.seq_bars > 1 else ""),
                     lambda: setattr(c, "seq_bars", {1: 2, 2: 4, 4: 8, 8: 1}.get(c.seq_bars, 4)), 10)
        self.btn((690, y0, 792, y1), "ALL TRACKS", lambda: c.set_mode("GRID" if allv else "SEQ"), 11, on=allv)

    def screen_seq(self):
        """GRID page, ALL TRACKS view: every track of the sequence; tap the selected track again (or OK) to edit it"""
        d, e, c = self.d, self.e, self.c
        sq = e.seq
        self.grid_header()
        page = e.cur_track // 8                                       # 8 tracks per page, the page follows the selected track
        vis = max(1, min(c.seq_bars, sq.bars))
        if e.playing and e.pos >= 0:                                  # follow the playhead
            bar = int(e.pos // sq.bar_ticks)
            if not (c.seq_off <= bar < c.seq_off + vis): c.seq_off = bar // vis * vis
        c.seq_off = clamp(c.seq_off, 0, max(0, sq.bars - 1))
        tx0, tx1 = 240, 792
        ppt = (tx1 - tx0) / float(vis * sq.bar_ticks)
        t0 = c.seq_off * sq.bar_ticks
        ry, RH = 74, 34
        y_end = 94 + 8 * RH
        self.plate((2, ry - 4, 798, y_end + 4), 9)
        self.well((tx0, ry, tx1 + 2, y_end + 1), 5, (19, 21, 25), 7)
        self.lab(8, ry + 8, f"TRACKS {page * 8 + 1}-{page * 8 + 8}", 5.6, skin.LAB, "lm", "s", 0.14); self.lab(124, ry + 8, "TYPE", 5.6, skin.LAB, "lm", "s", 0.14)
        self.lab(172, ry + 8, "MUTE  SOLO", 5.6, skin.LAB, "lm", "s", 0.14)
        for b in range(vis):
            bx = tx0 + b * sq.bar_ticks * ppt
            d.line([bx, ry + 2, bx, y_end], fill=(64, 68, 78))
            self.lab(bx + 5, ry + 8, str(c.seq_off + b + 1), 5.8, skin.LAB, "lm", "s", 0.1)
        def locate(px, py): e.locate(t0 + (px - tx0) / ppt)
        self.hit((tx0, ry, tx1, ry + 16), down=locate, drag=locate)
        for r in range(8):
            k = page * 8 + r
            tr = sq.tracks[k]; y = 94 + r * RH
            on = k == e.cur_track
            if on:
                d.rounded_rectangle([5, y, 236, y + RH - 2], 5, fill=(52, 56, 64))
                d.rectangle([tx0 + 1, y, tx1, y + RH - 2], fill=(31, 34, 40))
                d.rounded_rectangle([5, y + 4, 7.5, y + RH - 6], 1, fill=ORANGE)
            elif r % 2: d.rectangle([tx0 + 1, y, tx1, y + RH - 2], fill=(23, 25, 29))
            col = TRACK_COLORS[k % 8]
            self.t(13, y + RH // 2 - 1, f"{k + 1:02d}", 10, True, ORANGE if on else (95, 101, 113), "lm")
            self.t(36, y + RH // 2 - 1, tr.name[:10], 12, on, (244, 246, 249) if on else ((214, 218, 226) if tr.events else (95, 101, 113)), "lm")
            m = clamp(e.track_meter[k], 0, 1)                        # activity bar under the name
            if m > 0.02: d.rectangle([36, y + RH - 6, 36 + int(78 * m), y + RH - 4], fill=level_color(m))
            yb0, yb1 = y + 4, y + RH - 6
            plab = self.track_type_label(tr)
            self.btn((120, yb0, 164, yb1), plab, lambda k=k: c.cycle_track_type(k), 9 if tr.kind != "drum" else 10,
                     color={"drum": TEXT, "keys": CYAN, "plugin": (200, 140, 255), "midi": YEL}[tr.kind], on=c.track_setup == k)
            self.btn((170, yb0, 200, yb1), "M", lambda k=k: setattr(sq.tracks[k], "mute", not sq.tracks[k].mute), 11, color=TEXT if tr.mute else DIM,
                     fill=(120, 34, 34) if tr.mute else PANEL2, outline=RED if tr.mute else LINE)
            self.btn((204, yb0, 234, yb1), "S", lambda k=k: setattr(sq.tracks[k], "solo", not sq.tracks[k].solo), 11, color=TEXT if tr.solo else DIM,
                     fill=(120, 100, 20) if tr.solo else PANEL2, outline=YEL if tr.solo else LINE)
            def ndown(*_, k=k):                                       # tap = select; tap the selected track again = edit it
                if e.cur_track == k: c.set_mode("GRID")
                else: e.cur_track = k
            self.hit((4, y, 118, y + RH - 1), down=ndown)
            def tdown(px, py, k=k): e.cur_track = k; e.locate(t0 + (px - tx0) / ppt) if not e.playing else None
            self.hit((tx0, y, tx1, y + RH - 1), down=tdown)
            for ev in tr.events:
                if not (t0 <= ev[0] < t0 + vis * sq.bar_ticks): continue
                x = tx0 + (ev[0] - t0) * ppt
                yy = y + RH - 6 - int(ev[1] % 16 * (RH - 12) / 15.0)
                d.rounded_rectangle([x, yy - 2, min(tx1 - 1, x + max(2.2, ev[3] * ppt)), yy + 0.6], 1, fill=mix(col, (255, 255, 255), ev[2] / 400.0) if not tr.mute else (70, 74, 84))
            if not tr.events and on: self.t(tx0 + 8, y + RH // 2 - 1, "empty - tap its name again to edit it, or press REC / OVERDUB", 9, False, (70, 74, 90), "lm")
            elif on: self.t(116, y + RH // 2 - 1, ">", 11, True, ORANGE, "rm")
        for b in range(vis + 1):
            bx = tx0 + b * sq.bar_ticks * ppt
            for beat in range(1, sq.num):
                x = bx + beat * sq.beat_ticks * ppt
                if x < tx1: d.line([x, 94, x, y_end], fill=(33, 36, 42))
        if t0 <= e.pos < t0 + vis * sq.bar_ticks or e.pos < 0:
            px = tx0 + (e.pos - t0) * ppt
            if tx0 <= px <= tx1:
                d.line([px, ry, px, y_end], fill=mix((20, 22, 26), ORANGE, 0.4), width=4)
                d.line([px, ry, px, y_end], fill=ORANGE, width=1.5)
        if c.track_setup is not None: self.track_setup_panel()

    def track_setup_panel(self):
        """SEQ: what a track plays - DRUM (pads of a program), KEYGROUP (one pad, chromatic), PLUGIN (VST3 synth), MIDI (external)"""
        import fx as fxlib, os
        d, e, c = self.d, self.e, self.c
        k = c.track_setup
        tr = e.seq.tracks[k]
        x0, y0, x1, y1 = 236, 72, 792, 368
        self.hit((x0, y0, x1, y1), down=lambda *_: None)                 # nothing underneath reacts
        self.plate((x0, y0, x1, y1), 10)
        d.rounded_rectangle([x0, y0, x1, y1], 10, outline=mix((49, 52, 59), ORANGE, 0.6), width=1)
        self.lab(x0 + 14, y0 + 12, f"TRACK {k + 1:02d}", 6.0, ORANGE, "lm", "s", 0.16)
        self.t(x0 + 14, y0 + 26, f"{tr.name}  -  what does it play?", 13, True, (240, 242, 246), "lm")
        self.btn((x1 - 86, y0 + 6, x1 - 8, y0 + 32), "CLOSE", lambda: setattr(c, "track_setup", None), 11, grow=4)
        tab = getattr(c, "ts_tab", None) or tr.kind
        info = {"drum": "the 16 pads x 4 banks of a drum program", "keys": "one pad, played up and down the keyboard",
                "plugin": "a VST3 instrument (synth / sampler plug-in)", "midi": "notes to external gear on MIDI out"}
        for i, kind in enumerate(("drum", "keys", "plugin", "midi")):
            bx = x0 + 14 + i * 132
            self.btn((bx, y0 + 40, bx + 124, y0 + 76), KIND_NAMES[kind], lambda kind=kind: setattr(c, "ts_tab", kind), 12,
                     on=(tab == kind), color={"drum": TEXT, "keys": CYAN, "plugin": (200, 140, 255), "midi": YEL}[kind])
        self.t(x0 + 14, y0 + 92, info[tab] + ("   (current)" if tab == tr.kind else ""), 11, False, DIM, "lm")
        by = y0 + 110
        def setk(kind, plugin=None):
            if e.set_track_kind(tr, kind, plugin): c.ts_tab = None; e.say(f"track {k + 1}: {KIND_NAMES[kind]}")
        if tab == "drum":
            self.t(x0 + 14, by + 16, "Program", 12, True, TEXT, "lm")
            for p in range(NPROG):
                bx = x0 + 100 + p * 54
                self.btn((bx, by, bx + 48, by + 34), f"P{p + 1}", lambda p=p: (setk("drum"), setattr(tr, "prog", p)) if tr.kind == "drum" or not tr.events else setk("drum"),
                         12, on=(tr.kind == "drum" and tr.prog == p))
        elif tab == "keys":
            kp = e.prog.pads[tr.key_pad]
            self.t(x0 + 14, by + 16, f"Plays pad {BANKS[tr.key_pad // 16]}{tr.key_pad % 16 + 1:02d}  {kp.src.name if kp.src else '(empty)'}", 12, True, TEXT, "lm")
            self.btn((x0 + 330, by, x0 + 540, by + 34), f"USE SELECTED PAD {BANKS[e.bank]}{e.sel + 1:02d}",
                     lambda: (setk("keys"), setattr(tr, "key_pad", e.pad_idx)), 11)
            self.t(x0 + 14, by + 62, f"Original pitch on key {self.note_name(tr.root)}", 12, False, TEXT, "lm")
            self.btn((x0 + 330, by + 46, x0 + 380, by + 78), "-", lambda: setattr(tr, "root", max(24, tr.root - 1)), 16)
            self.btn((x0 + 386, by + 46, x0 + 436, by + 78), "+", lambda: setattr(tr, "root", min(96, tr.root + 1)), 16)
            if tr.kind != "keys": self.btn((x0 + 14, by + 100, x0 + 214, by + 136), "MAKE IT KEYGROUP", lambda: setk("keys"), 12, color=CYAN)
        elif tab == "plugin":
            insts = fxlib.discover_instruments()
            if not insts:
                self.t(x0 + 14, by + 16, "no VST3 instruments found (put them in ~/.vst3 or plugins/; needs vst3host)", 11, False, YEL, "lm")
            for i, (path, name) in enumerate(insts[:5]):
                yy = by + i * 34
                cur = tr.kind == "plugin" and tr.plugin == path
                self.btn((x0 + 14, yy, x0 + 340, yy + 30), name, lambda path=path: setk("plugin", path), 12, on=cur)
            if tr.kind == "plugin" and tr.plugin:
                self.btn((x0 + 360, by, x0 + 540, by + 40), "PLUG-IN WINDOW",
                         lambda: c.toggle_editor(e.instrument(tr), f"TRACK {k + 1}"), 12, color=(200, 140, 255))
                inst = e.instruments.get(id(tr))
                self.t(x0 + 360, by + 58, f"{inst.n()} parameters" if inst else "", 10, False, DIM, "lm")
        else:
            ch = tr.midi_ch or 1
            self.t(x0 + 14, by + 16, f"MIDI out channel {ch}", 12, True, TEXT, "lm")
            self.btn((x0 + 220, by, x0 + 270, by + 34), "-", lambda: setattr(tr, "midi_ch", max(1, (tr.midi_ch or 1) - 1)), 16)
            self.btn((x0 + 276, by, x0 + 326, by + 34), "+", lambda: setattr(tr, "midi_ch", min(16, (tr.midi_ch or 1) + 1)), 16)
            if tr.kind != "midi": self.btn((x0 + 14, by + 50, x0 + 214, by + 86), "MAKE IT MIDI", lambda: setk("midi"), 12, color=YEL)
            self.t(x0 + 14, by + 110, "plays nothing inside the sampler: connect a synth to a USB MIDI port", 10, False, DIM, "lm")
        self.t(x0 + 14, y1 - 16, "notes from KEYGROUP / PLUGIN / MIDI tracks can be swapped between them; DRUM <-> notes needs an empty track", 9, False, DIM, "lm")

    # ------------------------------------------------------------ GRID (piano roll for the active track)
    # ------------------------------------------------------------ GRID bottom lane: OFF / VELOCITY / AUTOMATION
    LANE_H = {"OFF": 0, "VEL": 28, "AUTO": 100}

    GY0 = 94                                                          # GRID view: the ruler's top edge (the header sits above)

    def grid_h(self):
        """height of the note area: it takes the space the bottom lane does not use"""
        return 264 - self.LANE_H[self.c.g_view]

    def auto_lane(self, gx0, gx1, vy0, vy1, ppt, span, snap):
        """automation of the chosen parameter: a line through its points; drag to draw (snapped to the grid)"""
        d, e, c = self.d, self.e, self.c
        tr = e.track
        tg = c.auto_target()
        d.rectangle([gx0, vy0, gx1, vy1], fill=PANEL)
        d.rectangle([4, vy0, gx0 - 2, vy1], fill=PANEL2)
        key, label = (tg[0], tg[1]) if tg else (None, "-")
        words = label.split(" ")
        lines = [" ".join(words[:2]), words[2], " ".join(words[3:])] if len(words) > 3 else [label]
        for k, ln in enumerate(l for l in lines if l):
            self.t(8, vy0 + 6 + k * 13, ln[:12], 9, k == 0, ORANGE if k == 0 else TEXT)
        self.hit((4, vy0, gx0 - 2, vy0 + 58), down=lambda *_: c.next_auto_target())
        has = bool(key and tr.auto.get(key))
        self.btn((8, vy1 - 22, gx0 - 6, vy1 - 2), "CLEAR", lambda: c.auto_clear_lane(), 8, on=False)
        y_of = lambda v: vy1 - 3 - v * (vy1 - vy0 - 6)
        mid = y_of(0.5) if key == "pan" else None
        if mid is not None: d.line([gx0, mid, gx1, mid], fill=LINE)
        if tg is not None:
            pts = tr.auto.get(key) or []
            if pts:
                xs = [gx0 + (t - c.g_off) * ppt for t, _ in pts]
                line = [(gx0, y_of(pts[0][1]))] + [(x, y_of(v)) for x, (_, v) in zip(xs, pts)] + [(gx1, y_of(pts[-1][1]))]
                d.line(line, fill=ORANGE, width=2)
                for x, (_, v) in zip(xs, pts):
                    if gx0 <= x <= gx1: d.ellipse([x - 3, y_of(v) - 3, x + 3, y_of(v) + 3], fill=YEL)
            else:
                yv = y_of(tg[2]())
                d.line([gx0, yv, gx1, yv], fill=DIM)
                self.t((gx0 + gx1) // 2, vy0 + 12, "drag here to draw  -  or move the Q-link while recording", 9, False, DIM, "mm")
        if e.playing and c.g_off <= e.pos < c.g_off + span:
            x = gx0 + (e.pos - c.g_off) * ppt
            d.line([x, vy0, x, vy1], fill=(255, 255, 255))
        def draw(px, py):
            if tg is None: return
            tick = int(c.g_off + (px - gx0) / ppt) // snap * snap
            tick = clamp(tick, 0, e.seq.length - 1)
            v = clamp((vy1 - 3 - py) / float(vy1 - vy0 - 6), 0.0, 1.0)
            e.auto_set_point(tr, key, tick, v)
        self.hit((gx0, vy0, gx1, vy1), down=lambda px, py: (e.begin_edit(), draw(px, py)), drag=draw)   # one undo step per stroke

    def screen_grid(self):
        d, e, c = self.d, self.e, self.c
        sq, tr = e.seq, e.track
        if tr.kind in NOTE_KINDS: return self.screen_keyroll()
        gx0, gx1, gy0 = 92, 792, self.GY0
        nl = c.g_lanes                                                   # 8 lanes (big, touch friendly) or all 16
        lane_h = self.grid_h() // nl
        base = 0 if nl == 16 else (c.g_lane // 8) * 8                    # which 8 pads are visible: follows the cursor
        span = c.g_bars * sq.bar_ticks
        ppt = (gx1 - gx0) / float(span)
        self.grid_header()
        import gridtools
        gridtools.toolbar(self)
        gy_end = gy0 + 12 + nl * lane_h
        def ly(lane): return gy0 + 12 + (nl - 1 - (lane - base)) * lane_h
        self.plate((2, gy0 - 5, 798, gy_end + 4), 9)
        self.well((gx0, gy0 + 11, gx1 - 3, gy_end + 1), 5, (20, 22, 26), 7)
        # ruler
        bt = sq.beat_ticks
        k0 = c.g_off // bt
        for k in range(k0, (c.g_off + span) // bt + 1):
            x = gx0 + (k * bt - c.g_off) * ppt
            if x > gx1 - 12: break
            if k % sq.num == 0: self.lab(x + 2, gy0 + 4, f"{k // sq.num + 1}.1", 5.6, skin.LAB2, "lm", "s", 0.1)
        # lanes
        for lane in range(base, base + nl):
            y = ly(lane)
            pad = e.prog.pads[e.bank * 16 + lane]
            on = lane == c.g_lane
            if on or lane % 2: d.rectangle([gx0 + 1, y, gx1 - 4, y + lane_h - 1], fill=(33, 36, 42) if on else (24, 26, 30))
            # the row's pad: its number and what it plays (the sample, or which slice of which sample), M and S
            self.keycap((6, y + 1.5, 64, y + lane_h - 1.5), "down" if on else "up", 4)
            if pad.src is None: lab = "empty"
            elif pad.link is not None: lab = f"{pad.src.name[:5]} {pad.link[1] + 1}".replace("_", " ")
            else: lab = pad.src.name.replace("_", " ")
            tc = ORANGE if on else ((214, 218, 226) if pad.src else (100, 106, 118))
            if nl == 8:
                self.lab(11, y + lane_h // 2 - 6, f"{BANKS[e.bank]}{lane + 1:02d}", 5.4, ORANGE if on else skin.LAB, "lm", "s", 0.1)
                self.t(11, y + lane_h // 2 + 6, lab[:8], 9, True, tc, "lm")
            else:
                self.lab(10, y + lane_h // 2, f"{BANKS[e.bank]}{lane + 1:02d}", 4.8, ORANGE if on else skin.LAB, "lm", "s", 0.04)
                self.t(28, y + lane_h // 2, lab[:6], 7.5, True, tc, "lm")
            self.hit((4, y, 64, y + lane_h), down=lambda *_, lane=lane: (setattr(c, "g_lane", lane), setattr(e, "sel", lane),
                                                                     e.trigger(e.prog.pads[e.bank * 16 + lane], 100)))
            mh = min(lane_h - 4, 14)
            for k_, (flag, letter, col) in enumerate((("mute", "M", RED), ("solo", "S", YEL))):
                bx = 66 + k_ * 12
                st_ = getattr(pad, flag)
                self.keycap((bx, y + lane_h / 2 - mh / 2, bx + 11, y + lane_h / 2 + mh / 2), "lit" if st_ else "up", 3, col)
                self.lab(bx + 5.5, y + lane_h / 2, letter, 4.4, (20, 20, 22) if st_ else (160, 166, 178), "mm", "b", 0.0, floor=4.0)
                self.hit((bx, y, bx + 11.5, y + lane_h), down=lambda *_, lane=lane, flag=flag: c.g_pad_flag(lane, flag))
        # grid lines
        s = c.snap()
        t = (c.g_off // s) * s
        while t <= c.g_off + span:
            x = gx0 + (t - c.g_off) * ppt
            if gx0 < x < gx1 - 3:
                col = (64, 68, 78) if t % sq.bar_ticks == 0 else ((40, 43, 50) if t % bt == 0 else (29, 31, 36))
                d.line([x, gy0 + 12, x, gy_end], fill=col)
            t += s
        # notes: lit caps in the accent colour, brighter the harder they were played
        for ev in tr.events:
            if not (c.g_off <= ev[0] < c.g_off + span): continue
            lane = ev[1] - e.bank * 16
            if not (base <= lane < base + nl): continue
            y = ly(lane)
            x = gx0 + (ev[0] - c.g_off) * ppt
            w = max(3, min(ev[3] * ppt - 1.5, gx1 - 4 - x))
            v = 0.55 + 0.45 * ev[2] / 127.0
            top = tuple(int(min(255, ch * v * 1.08)) for ch in ORANGE); bot = tuple(int(ch * v * 0.78) for ch in ORANGE)
            sp, ox, oy = skin.body(max(3, self.P(w)), max(3, self.P(lane_h - 6)), self.P(2.5), top, bot, 0.25, 0.25, (4, 0.5))
            self.put(sp, x, y + 3, ox, oy)
            if gridtools.selected(c, ev):
                d.rounded_rectangle([x - 1.5, y + 1.5, x + w + 1.5, y + lane_h - 1.5], 3, outline=(255, 255, 255), width=1.6)
                if w > 8: d.rectangle([x + w - 3, y + 6, x + w - 1.5, y + lane_h - 6], fill=(255, 255, 255))     # the length handle
        # cursor + playhead
        if c.g_off <= c.g_tick < c.g_off + span and base <= c.g_lane < base + nl:
            x = gx0 + (c.g_tick - c.g_off) * ppt
            y = ly(c.g_lane)
            d.rounded_rectangle([x, y + 1, x + max(4, s * ppt), y + lane_h - 2], 3, outline=YEL, width=1.4)
        if c.g_off <= e.pos < c.g_off + span:
            x = gx0 + (e.pos - c.g_off) * ppt
            d.rectangle([x - 1.6, gy0 + 1, x + 1.6, gy_end], fill=mix((20, 22, 26), ORANGE, 0.3))
            d.rectangle([x - 0.5, gy0 + 1, x + 0.5, gy_end], fill=ORANGE)
        if e.playing and e.pos >= c.g_off + span: c._g_scroll_to(e.pos)
        if e.playing and e.pos < c.g_off: c._g_scroll_to(e.pos)
        # bottom lane: velocity, automation, or nothing (LANE chip in the header)
        vy0, vy1 = gy_end + 6, 370
        if c.g_view == "VEL":
            self.well((gx0, vy0, gx1 + 2, vy1), 4, (19, 21, 25), 5)
            self.lab(8, vy0 + 6, "VELOCITY", 6.4, skin.LAB, "la", "s", 0.14)
            for ev in tr.events:
                if not (c.g_off <= ev[0] < c.g_off + span): continue
                x = gx0 + (ev[0] - c.g_off) * ppt
                h = int((vy1 - vy0 - 4) * ev[2] / 127.0)
                lane = ev[1] - e.bank * 16
                d.rectangle([x, vy1 - h, x + 2, vy1 - 1], fill=ROW_COLORS[(lane // 4) % 4] if lane == c.g_lane else mix(ROW_COLORS[(lane // 4) % 4], BG, 0.5))
        elif c.g_view == "AUTO": self.auto_lane(gx0, gx1, vy0, vy1, ppt, span, s)
        if not tr.events:
            self.t((gx0 + gx1) // 2, (gy0 + gy_end) // 2, "DRAW: tap to add a note, drag right for its length", 12, False, DIM, "mm")
        # touch on the grid (the tool decides: draw / select / erase)
        lo, hi = e.bank * 16 + base, e.bank * 16 + base + nl - 1
        gridtools.install(self, (gx0, gy0 + 12, gx1, gy_end), ppt, s,
                          lambda py: e.bank * 16 + int(clamp(base + nl - 1 - int((py - (gy0 + 12)) // lane_h), base, base + nl - 1)),
                          lambda p_: ly(p_ - e.bank * 16), lane_h, lo, hi)
        gridtools.draw_box(self)
        self.hit((gx0, gy0 - 2, gx1, gy0 + 10), down=lambda px, py: e.locate(c.g_off + (px - gx0) / ppt),
                 drag=lambda px, py: e.locate(c.g_off + (px - gx0) / ppt))
        if c.track_setup is not None: self.track_setup_panel()

    def track_type_label(self, tr):
        e = self.e
        if tr.kind == "keys": return f"K {BANKS[tr.key_pad // 16]}{tr.key_pad % 16 + 1:02d}"
        if tr.kind == "plugin": return (__import__("os").path.basename(tr.plugin).replace(".vst3", "") or "PLUG")[:5]
        if tr.kind == "midi": return f"MIDI{tr.midi_ch or 1}"
        return e.programs[tr.prog].name.replace("DRUM ", "P")

    NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    def note_name(self, n): return f"{self.NOTE_NAMES[n % 12]}{n // 12 - 1}"

    def screen_keyroll(self):
        """GRID for a KEYS track: a piano roll (notes from an external keyboard or drawn here)"""
        d, e, c = self.d, self.e, self.c
        sq, tr = e.seq, e.track
        gx0, gx1, gy0 = 92, 792, self.GY0
        nl = 12 if c.g_lanes == 8 else 24                       # one octave of big lanes, or two octaves
        lane_h = self.grid_h() / float(nl)
        if not (0 <= c.g_lane <= 127) or c.g_lane < 12: c.g_lane = 60
        c.k_top = clamp(c.k_top, nl - 1, 127)
        if not (c.k_top - nl < c.g_lane <= c.k_top): c.k_follow(c.g_lane)
        top = c.k_top
        span = c.g_bars * sq.bar_ticks
        ppt = (gx1 - gx0) / float(span)
        kp = e.prog.pads[tr.key_pad]
        self.grid_header()
        import gridtools
        gridtools.toolbar(self)
        if tr.kind == "keys": what = f"KEYGROUP: {BANKS[tr.key_pad // 16]}{tr.key_pad % 16 + 1:02d} {kp.src.name if kp.src else '(empty pad)'}   {self.note_name(tr.root)} = original pitch"
        elif tr.kind == "plugin": what = f"PLUGIN: {__import__('os').path.basename(tr.plugin).replace('.vst3', '') or '(none chosen)'}"
        else: what = f"MIDI: out on channel {tr.midi_ch or 1}"
        what += f"   + MIDI out ch {tr.midi_ch}" if tr.midi_ch and tr.kind != "midi" else ""
        gy_end = gy0 + 12 + self.grid_h()
        def ly(note): return gy0 + 12 + (top - note) * lane_h
        self.plate((2, gy0 - 5, 798, gy_end + 4), 9)
        self.well((gx0, gy0 + 11, gx1 + 2, gy_end + 1), 4, (19, 21, 25), 7)
        bt = sq.beat_ticks
        for k in range(c.g_off // bt, (c.g_off + span) // bt + 1):
            x = gx0 + (k * bt - c.g_off) * ppt
            if x > gx1 - 12: break
            if k % sq.num == 0: self.lab(x + 4, gy0 + 4, str(k // sq.num + 1), 6.4, skin.LAB, "lm", "s", 0.1)
        held = set(e.held)
        for note in range(top, top - nl, -1):
            y = ly(note); black = (note % 12) in (1, 3, 6, 8, 10)
            on = note == c.g_lane
            d.rectangle([gx0 + 1, y, gx1, y + lane_h - 1], fill=(44, 48, 56) if on else ((18, 19, 23) if black else (25, 27, 32)))
            if note in held: kt, kb = mix((240, 240, 244), ORANGE, 0.7), mix((200, 200, 206), ORANGE, 0.8)   # the keyboard down the left side
            elif black: kt, kb = (52, 54, 60), (30, 32, 36)
            else: kt, kb = (232, 233, 236), (200, 202, 208)
            sp, ox, oy = skin.body(self.P(gx0 - 10), max(3, self.P(lane_h - 1.5)), self.P(2.5), kt, kb, 0.3, 0.3, (3, 0.45))
            self.put(sp, 6, y + 0.5, ox, oy)
            kf = mix(kt, kb, 0.5)
            if note % 12 == 0 or nl == 12 or on:
                self.t(gx0 - 9, y + lane_h / 2, self.note_name(note), 9 if nl == 12 else 8, note % 12 == 0, ink(kf), "rm")
            if on: d.rounded_rectangle([2, y + 2, 4.5, y + lane_h - 3], 1, fill=ORANGE)
            def kdown(px, py, note=note):
                c.g_lane = note; e.audition(note, 100)
            self.hit((4, y, gx0 - 2, y + lane_h), down=kdown)
        s_ = c.snap()
        t = (c.g_off // s_) * s_
        while t <= c.g_off + span:
            x = gx0 + (t - c.g_off) * ppt
            if x >= gx0:
                col = (64, 68, 78) if t % sq.bar_ticks == 0 else ((40, 43, 50) if t % bt == 0 else (29, 31, 36))
                d.line([x, gy0 + 12, x, gy_end], fill=col)
            t += s_
        for ev in tr.events:
            if not (c.g_off <= ev[0] < c.g_off + span) or not (top - nl < ev[1] <= top): continue
            y = ly(ev[1]); x = gx0 + (ev[0] - c.g_off) * ppt
            w = max(3, min(ev[3] * ppt - 1.5, gx1 - 2 - x))
            v = 0.55 + 0.45 * ev[2] / 127.0
            nt_ = tuple(int(min(255, ch * v * 1.08)) for ch in ORANGE); nb_ = tuple(int(ch * v * 0.78) for ch in ORANGE)
            sp, ox, oy = skin.body(max(3, self.P(w)), max(3, self.P(lane_h - 4)), self.P(2.5), nt_, nb_, 0.25, 0.25, (4, 0.5))
            self.put(sp, x, y + 2, ox, oy)
            if gridtools.selected(c, ev):
                d.rounded_rectangle([x - 1.5, y + 0.5, x + w + 1.5, y + lane_h - 1.5], 3, outline=(255, 255, 255), width=1.6)
        above = sum(1 for ev in tr.events if ev[1] > top); below = sum(1 for ev in tr.events if ev[1] <= top - nl)
        if above: self.t(gx1 - 4, gy0 + 16, f"{above} higher", 9, True, YEL, "ra")
        if below: self.t(gx1 - 4, gy_end - 14, f"{below} lower", 9, True, YEL, "ra")
        if c.g_off <= c.g_tick < c.g_off + span and top - nl < c.g_lane <= top:
            x = gx0 + (c.g_tick - c.g_off) * ppt
            d.rounded_rectangle([x, ly(c.g_lane) + 0.5, x + max(4, s_ * ppt), ly(c.g_lane) + lane_h - 1.5], 3, outline=YEL, width=1.4)
        if c.g_off <= e.pos < c.g_off + span:
            x = gx0 + (e.pos - c.g_off) * ppt
            d.line([x, gy0 - 2, x, gy_end], fill=mix((20, 22, 26), ORANGE, 0.4), width=4)
            d.line([x, gy0 - 2, x, gy_end], fill=ORANGE, width=1.5)
        if e.playing and e.pos >= c.g_off + span: c._g_scroll_to(e.pos)
        if e.playing and e.pos < c.g_off: c._g_scroll_to(e.pos)
        vy0, vy1 = gy_end + 6, 370
        if c.g_view == "VEL":
            self.well((gx0, vy0, gx1 + 2, vy1), 4, (19, 21, 25), 5)
            self.lab(8, vy0 + 6, "VELOCITY", 6.4, skin.LAB, "la", "s", 0.14)
            for ev in tr.events:
                if not (c.g_off <= ev[0] < c.g_off + span): continue
                x = gx0 + (ev[0] - c.g_off) * ppt
                h = int((vy1 - vy0 - 4) * ev[2] / 127.0)
                d.rectangle([x, vy1 - h, x + 2, vy1 - 1], fill=ORANGE if ev[1] == c.g_lane else mix(ORANGE, (20, 22, 26), 0.5))
        elif c.g_view == "AUTO": self.auto_lane(gx0, gx1, vy0, vy1, ppt, span, max(1, c.snap()))
        if not tr.events:
            self.t((gx0 + gx1) // 2, (gy0 + gy_end) // 2 - 10, "play the keyboard with REC or OVERDUB on - or tap here to draw notes", 12, False, DIM, "mm")
            self.t((gx0 + gx1) // 2, (gy0 + gy_end) // 2 + 12, what[:70], 11, False, CYAN, "mm")
        gridtools.install(self, (gx0, gy0 + 12, gx1, gy_end), ppt, s_,
                          lambda py: int(clamp(top - int((py - (gy0 + 12)) // lane_h), top - nl + 1, top)),
                          lambda n_: ly(n_), lane_h, 0, 127)
        gridtools.draw_box(self)
        self.hit((gx0, gy0 - 2, gx1, gy0 + 10), down=lambda px, py: e.locate(c.g_off + (px - gx0) / ppt),
                 drag=lambda px, py: e.locate(c.g_off + (px - gx0) / ppt))
        if c.track_setup is not None: self.track_setup_panel()

    # ------------------------------------------------------------ MENU: the pages without a key of their own
    def menu_icon(self, kind, cx, cy, col):
        d = self.d
        if kind == "projects":                                       # a stack of folders
            for k in (6, 0):
                d.rounded_rectangle([cx - 20 + k, cy - 12 - k, cx + 16 + k, cy + 14 - k], 3, outline=col, width=2)
            d.rectangle([cx - 20, cy - 16, cx - 6, cy - 12], fill=col)
        elif kind == "browse":                                       # a USB stick
            d.rounded_rectangle([cx - 10, cy - 8, cx + 10, cy + 20], 4, outline=col, width=2)
            d.rectangle([cx - 6, cy - 20, cx + 6, cy - 8], outline=col, width=2)
        elif kind == "edit":                                         # bars with a copy arrow
            for k in range(3): d.rectangle([cx - 22 + k * 15, cy - 4, cx - 10 + k * 15, cy + 14], outline=col, width=2)
            d.line([(cx - 16, cy - 12), (cx + 16, cy - 12)], fill=col, width=2); self.icon(">", cx + 14, cy - 12, 4, col)
        elif kind == "pads":
            for r in range(2):
                for q in range(2): d.rounded_rectangle([cx - 18 + q * 20, cy - 18 + r * 20, cx - 2 + q * 20, cy - 2 + r * 20], 3, fill=col)
        elif kind == "midi":                                         # a DIN socket
            d.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], outline=col, width=2)
            for a in (-60, -30, 0, 30, 60):
                import math
                x, y = cx + 10 * math.sin(math.radians(a)), cy + 8 - 10 * math.cos(math.radians(a))
                d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=col)
        elif kind == "export":                                       # stems: waveforms stacked
            for k in range(3):
                y = cy - 12 + k * 12
                d.line([(cx - 20 + j * 5, y + (3 if j % 2 else -3)) for j in range(9)], fill=col, width=2)
        elif kind == "song":                                         # chained blocks
            for k in range(3): d.rounded_rectangle([cx - 24 + k * 17, cy - 8, cx - 12 + k * 17, cy + 8], 3, outline=col, width=2)
            d.line([(cx - 12, cy), (cx - 7, cy)], fill=col, width=2); d.line([(cx + 5, cy), (cx + 10, cy)], fill=col, width=2)
        elif kind == "settings":                                     # a gear: eight teeth round a ring
            import math
            for k in range(8):
                an = k * math.pi / 4
                d.line([cx + 12 * math.cos(an), cy + 12 * math.sin(an), cx + 18 * math.cos(an), cy + 18 * math.sin(an)], fill=col, width=5)
            d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], outline=col, width=3); d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=col, width=2)
        elif kind == "save":                                         # a floppy disk
            d.rounded_rectangle([cx - 16, cy - 16, cx + 16, cy + 16], 3, outline=col, width=2)
            d.rectangle([cx - 9, cy - 16, cx + 9, cy - 5], outline=col, width=2); d.rectangle([cx - 10, cy + 3, cx + 10, cy + 16], fill=col)

    def screen_settings(self):
        """MENU > SETTINGS (settingspage.py): the sections in a column of keys, the rows in a well; < > / jog the value"""
        import settingspage as SP, pages
        d, e, c = self.d, self.e, self.c
        self.title("SETTINGS")
        sec = SP.SECTIONS[c.set_sec]
        top = {"AUDIO": lambda: "NOW: " + (c.audio_now or "-") + f"  -  {(c.xruns or {}).get('n', 0)} DROPOUTS",
               "CONTROLLERS": lambda: "MPC STUDIO: " + ("CONNECTED" if getattr(c, "studio_seen", False) else "NOT SEEN")
                                      + "  -  OTHER MIDI: " + (", ".join(sorted({n.split(' ')[0] for n in c.midi_io.names.values()})) if getattr(c, "midi_io", None) and c.midi_io.names else "NONE")}.get(sec)
        if top:
            self.ledp(130, 52, 5, True, GREEN); self.t(142, 52, top().upper()[:96], 9.5, False, (176, 182, 192), "lm")
        self.well((6, 66, 172, 368), 8, (22, 24, 28), 7)
        for i, s_ in enumerate(SP.SECTIONS):
            y = 74 + i * 56; on = i == c.set_sec
            self.keycap((14, y, 164, y + 46), "lit" if on else "up", 6, ORANGE if on else None)
            self.lab(89, y + 23, s_, 5.6, (255, 255, 255) if on else (205, 210, 218), "mm", "s", 0.1, maxw=140)
            self.hit((14, y, 164, y + 46), down=lambda *_, i=i: c.set_section(i))
        self.well((180, 66, 794, 368), 8, (22, 24, 28), 7)
        rs = c.set_rows(); rh = 41 if len(rs) <= 6 else 36
        c.set_row %= len(rs)
        for i, row in enumerate(rs):
            y = 74 + i * rh; sel = i == c.set_row and row.kind != "info"
            self.row((188, y, 786, y + rh - 5), sel, False, i % 2 == 1, 5)
            self.lab(200, y + (rh - 5) / 2 - (5 if row.new else 0), row.name, 5.6, (255, 255, 255) if sel else (196, 201, 210), "lm", "s", 0.1, maxw=150)
            if row.new: self.lab(200, y + (rh - 5) / 2 + 8, "NEW", 4.2, ORANGE, "lm", "s", 0.12)
            vx0, vx1 = 360, 780
            if row.kind == "seg":
                vals = [v for _, v in row.options]; cur = SP.get(c, row.key)
                def pick(k, row=row, i=i):
                    c.set_row = i; SP.put(c, row.key, row.options[k][1])
                pages.seg(self, (vx0, y + 4, vx1, y + rh - 9), [lab for lab, _ in row.options], vals.index(cur) if cur in vals else -1, pick, 5.0)
            elif row.kind == "list":
                cur = SP.get(c, row.key); lab = next((l_ for l_, v in row.options if v == cur), cur or "-")
                self.well((vx0, y + 4, vx1, y + rh - 9), 5, (12, 13, 15), 4)
                self.t(vx0 + 12, y + (rh - 5) / 2, str(lab)[:48], 11, True, (233, 236, 240), "lm")
                self.t(vx1 - 10, y + (rh - 5) / 2, "JOG / < > TO CHANGE", 8, False, (130, 136, 148), "rm")
                def lt(*_, row=row, i=i):
                    c.set_row = i; SP.step(c, row, 1)
                self.hit((vx0, y + 4, vx1, y + rh - 9), down=lt)
            elif row.kind == "info":
                try: txt = row.info()
                except Exception as ex: txt = f"- ({ex})"
                self.t(vx0, y + (rh - 5) / 2, txt, 11, False, (220, 224, 230), "lm")
            elif row.kind == "key":
                self.keycap((vx0, y + 4, vx0 + 190, y + rh - 9), "up", 5)
                self.lab(vx0 + 95, y + (rh - 5) / 2, row.options[0], 5.4, (230, 233, 238), "mm", "s", 0.1)
                self.hit((vx0, y + 4, vx0 + 190, y + rh - 9), down=lambda *_, row=row, i=i: (setattr(c, "set_row", i), row.action()))
            if row.kind in ("seg", "list", "key"):
                self.hit((188, y, vx0 - 4, y + rh - 5), down=lambda *_, i=i: setattr(c, "set_row", i))
        foot = {"AUDIO": "These restart the sound: they take effect on APPLY (F3).",
                "CONTROLLERS": "MPC STUDIO and OTHER USB MIDI take effect on APPLY. Learning a controller's knobs: MENU > MIDI.",
                "DISPLAY + TOUCH": "These take effect on APPLY (F3): Monolith restarts.",
                "GENERAL": "AUTOSAVE only saves while stopped, to the open project (as SHIFT + PLAY does).",
                "ABOUT": "SAVE LOG TO USB writes monolith-log.txt (version, settings, the last messages) for a bug report."}[sec]
        self.t(196, 356, foot, 9, False, (140, 146, 158), "lm")

    def screen_menu(self):
        d, e, c = self.d, self.e, self.c
        self.title("MENU", f"PROJECT: {e.project_name.upper()}")
        nc = c.MENU_COLS; tw_ = (784 - 8 * (nc - 1)) / nc                # five across: tiles 150 wide
        for i, (name, sub, ic) in enumerate(c.MENU_ITEMS):
            col, r = i % nc, i // nc
            x, y = 8 + col * (tw_ + 8), 70 + r * 152
            sel = i == c.menu_cur
            self.keycap((x, y, x + tw_, y + 144), "lit" if sel else "up", 10)
            self.menu_icon(ic, x + tw_ / 2, y + 48, (255, 255, 255) if sel else ORANGE)
            self.t(x + tw_ / 2, y + 100, name, 14, True, (250, 251, 253) if sel else (226, 230, 236), "mm")
            self.note(x + tw_ / 2, y + 122, sub, "mm", (226, 230, 236) if sel else (138, 144, 156))
            def mdown(*_, i=i):
                c.menu_cur = i; c.menu_go(i)
            self.hit((x, y, x + tw_, y + 144), down=mdown)

    # ------------------------------------------------------------ on-screen keyboard (naming things)
    def keyboard(self):
        d, c = self.d, self.c
        k = c.kbd
        x0, y0, x1, y1 = 4, 40, 796, 376
        self.hit((x0, y0, x1, y1), down=lambda *_: None)             # the page underneath does not react
        self.plate((x0, y0, x1, y1), 10)
        d.rounded_rectangle([x0, y0, x1, y1], 10, outline=mix((49, 52, 59), ORANGE, 0.6), width=1)
        self.lab(18, 53, k["title"].upper(), 6.0, ORANGE, "lm", "s", 0.16)
        self.glassbox((14, 63, 786, 99), 6)
        txt = k["text"]
        self.t(26, 81, txt, 18, True, (244, 246, 249), "lm")
        cx = 26 + d.textlength(txt, font=font(18, True)) + 2
        if int(time.time() * 2) % 2 == 0: d.rectangle([cx, 70, cx + 2, 92], fill=ORANGE)
        self.lab(778, 81, f"{len(txt)}/{k['max']}", 5.8, skin.LAB, "rm", "s", 0.1)
        rows = c.KBD_ROWS
        kh, gap, ytop = 48, 6, 106
        for r, row in enumerate(rows):
            y = ytop + r * (kh + gap)
            if r < 4:
                w = (772 - 9 * gap) / 10.0
                xs = [(14 + i * (w + gap), w) for i in range(len(row))]
            else:
                widths = {"CASE": 120, "SPACE": 300, "DEL": 110, "CLEAR": 110, "OK": 108}
                xs, xx = [], 14
                for key in row: xs.append((xx, widths[key])); xx += widths[key] + gap
            for i, key in enumerate(row):
                x, w = xs[i]
                sel = (r, i) == (k["row"], k["col"] % len(row))
                lab = key if (len(key) > 1 or k["caps"]) else key.lower()
                if key == "CASE": lab = "ABC" if not k["caps"] else "abc"
                on = key == "OK"
                self.btn((int(x), y, int(x + w), y + kh), lab, lambda key=key: c.kbd_press(key), 16 if len(key) == 1 else 12,
                         fill=mix(PANEL2, ORANGE, 0.3) if on else PANEL2, color=ORANGE if on else TEXT, outline=YEL if sel else LINE)

    # ------------------------------------------------------------ EDIT: sequence / track / pad operations
    def screen_edit(self):
        d, e, c = self.d, self.e, self.c
        xe = self.title("EDIT")
        self.note(xe + 14, 52, f"sequence {e.cur_seq + 1:02d} {e.seq.name}   {e.seq.bars} bars {e.seq.num}/{e.seq.den}   track {e.cur_track + 1:02d} {e.track.name}")
        self.well((4, 63, 230, 372), 8, (22, 24, 28), 7)
        for i, op in enumerate(c.ED_OPS):
            y = 66 + i * 34
            def pick(i=i): c.ed_op, c.ed_row = i, 0
            on_ = i == c.ed_op
            self.row((7, y, 227, y + 30), on_, False, False, 5)
            if on_: self.ledp(20, y + 15, 3.6, True)
            self.t(118, y + 15, op, 11, True, (255, 255, 255) if on_ else (186, 192, 204), "mm")
            self.hit((7, y, 227, y + 30), down=lambda *_, pick=pick: pick())
        x0 = 238
        op = c.ED_OPS[c.ed_op]
        self.plate((x0, 63, 796, 372), 9)
        self.t(x0 + 14, 84, op, 16, True, ORANGE, "lm")
        self.t(x0 + 14, 104, c.ED_HELP[op], 10, False, (160, 166, 178), "lm")
        rows = c.ed_rows()
        c.ed_row = clamp(c.ed_row, 0, max(0, len(rows) - 1))
        for k, (lab, val, adj) in enumerate(rows):
            y = 116 + k * 34
            sel = k == c.ed_row
            self.field((x0 + 8, y, 784, y + 30), lab, val, sel, 112)
            self.btn((694, y + 2, 732, y + 28), "-", lambda adj=adj, k=k: (setattr(c, "ed_row", k), adj(-1)), 16, grow=2)
            self.btn((740, y + 2, 778, y + 28), "+", lambda adj=adj, k=k: (setattr(c, "ed_row", k), adj(1)), 16, grow=2)
            self.hit((x0 + 8, y, 690, y + 30), down=lambda *_, k=k: setattr(c, "ed_row", k))
        self.btn((610, 328, 784, 364), "DO IT", c.ed_do, 14, on=True)
        self.lab(x0 + 14, 346, "UNDO TAKES IT BACK", 5.6, skin.LAB, "lm", "s", 0.14)

    # ------------------------------------------------------------ PROJECTS (MENU > PROJECTS)
    def screen_projects(self):
        d, e, c = self.d, self.e, self.c
        items = e.list_projects()
        c.pj_cur = clamp(c.pj_cur, 0, len(items) - 1)
        self.title("PROJECTS", f"OPEN: {e.project_name.upper()}")
        self.well((4, 66, 540, 372), 8, (22, 24, 28), 8)
        RH, top_y, rows = 32, 70, 9
        top = clamp(c.pj_cur - 4, 0, max(0, len(items) - rows))
        for r in range(rows):
            i = top + r
            if i >= len(items): break
            name, path = items[i]
            y = top_y + r * RH
            cur = os.path.abspath(path) == os.path.abspath(e.dir)
            sel = i == c.pj_cur
            self.row((8, y, 532, y + RH - 4), sel, False, r % 2 == 1, 4)
            self.t(20, y + RH // 2 - 2, name, 13, sel or cur, (255, 255, 255) if sel else (220, 224, 232), "lm")
            if cur: self.ledp(468, y + RH // 2 - 2, 3.6, True, GREEN); self.lab(520, y + RH // 2 - 2, "OPEN", 5.8, GREEN, "rm", "s", 0.16)
            elif name == "DEMO": self.lab(520, y + RH // 2 - 2, "THE DEMO", 5.6, skin.LAB, "rm", "s", 0.14)
            def pdown(*_, i=i):
                if c.pj_cur == i: c.pj_open(i)
                else: c.pj_cur = i
            self.hit((8, y, 532, y + RH - 4), down=pdown)
        self.plate((546, 66, 796, 372), 9)
        nseq = sum(1 for q in e.seqs if any(t.events for t in q.tracks))
        info = [("SAMPLES", str(len(e.sources))), ("SEQUENCES", str(nseq)), ("PROGRAMS", str(sum(1 for p in e.programs if any(not x.empty for x in p.pads))))]
        for k, (a, b) in enumerate(info):
            self.lab(558, 90 + k * 40, a, 5.6, skin.LAB, "lm", "s", 0.16); self.t(558, 108 + k * 40, b, 17, True, (240, 242, 246), "lm")
        nun = len(e.unused_sources())
        self.btn((556, 212, 780, 244), f"DELETE {nun} UNUSED SAMPLE" + ("S" if nun != 1 else ""), c.pj_purge, 10, color=RED if nun else DIM)
        for k, ln in enumerate(["tap a project, tap it again to open it", "(asks to save changes first)", "NEW: an empty project",
                                "SAVE AS: a copy you carry on in", "saved in projects/ next to the", "software; DEMO is its own folder"]):
            self.note(558, 262 + k * 16, ln)

    # ------------------------------------------------------------ MUTE: track mutes / solos and the next sequence, for playing live
    def screen_mute(self):
        import pages
        pages.mute(self)


    # ------------------------------------------------------------ BROWSE (SHIFT + PROG): audio files from USB / folders
    def screen_browse(self):
        import pages
        pages.browse(self)


    # ------------------------------------------------------------ PADS: pad modes (SHIFT + MUTE, or PADS > on MAIN)
    def screen_pads(self):
        d, e, c = self.d, self.e, self.c
        self.pad_grid(10, 48)
        if e.pad_mode in ("NORMAL", "16 LEVELS"): self.bank_buttons(338, 48, 34, 72, 8)
        x0 = 386
        self.lab(x0, 54, "PAD MODE", 6.2, skin.LAB, "lm", "s", 0.16)
        from engine import PAD_MODES
        self.seg(x0 - 2, 63, 794, 107, list(PAD_MODES), list(PAD_MODES).index(e.pad_mode) if e.pad_mode in PAD_MODES else -1,
                 lambda k: c.set_pad_mode(PAD_MODES[k]), 5.4)
        rows = c.pads_rows()
        c.pads_row = clamp(c.pads_row, 0, len(rows) - 1)
        if c.pads_row == 0: d.rounded_rectangle([x0 - 5, 60, 797, 110], 8, outline=YEL, width=1)
        for k, (lab, val, adj) in enumerate(rows[1:], start=1):          # this mode's settings: - value +
            y = 116 + (k - 1) * 37
            sel = k == c.pads_row
            self.field((x0, y, 700, y + 32), lab, None, sel)
            self.t(x0 + 250, y + 16, val, 14, True, (250, 251, 253) if sel else (214, 218, 226), "mm")
            self.hit((x0, y, 700, y + 32), down=lambda *_, k=k: setattr(c, "pads_row", k))
            self.btn((704, y + 2, 744, y + 30), "-", lambda adj=adj, k=k: (setattr(c, "pads_row", k), adj(-1)), 16)
            self.btn((748, y + 2, 788, y + 30), "+", lambda adj=adj, k=k: (setattr(c, "pads_row", k), adj(1)), 16)
        help_ = {"NORMAL": ["Pads play their samples (and record when REC / OVERDUB runs).",
                            "Pick a mode above. Pad modes also work from MAIN and the other screens,",
                            "and on the MIDI controller's pads."],
                 "16 LEVELS": ["One pad spread over all 16: pads 1-16 = soft to hard (VELOCITY)",
                               "or -8 to +7 semitones (TUNE, pad 9 = the pad's own pitch).",
                               "Velocity hits record on a DRUM track; tuned hits play live only."],
                 "PERFORM": ["Pads play the current track's instrument in a scale (pad 1 = the key,",
                             "upwards bottom-left to top-right); CHORD stacks thirds on each pad.",
                             "Works with KEYGROUP, PLUGIN and MIDI tracks; records while REC runs."],
                 "TRACK MUTE": ["Pad 1-16 = track 1-16 of this sequence: tap to mute / unmute.",
                                "Lit = playing, dark red = muted. F3 unmutes all."],
                 "NEXT SEQ": ["Pad 1-16 = sequence 1-16. Stopped: switches now.",
                              "Playing: switches when this sequence ends (tap again to cancel)."]}[e.pad_mode]
        tr = e.track
        if e.pad_mode == "PERFORM":
            help_ = help_ + [f"now: track {tr.n + 1:02d} {tr.name}  ({KIND_NAMES[tr.kind]}" + (", plays the selected pad pitched)" if tr.kind == "drum" else ")")]
        for k, line in enumerate(help_):
            self.t(x0, 306 + k * 16, line, 10, False, (150, 156, 168) if k < 3 else CYAN, "lm")

    # ------------------------------------------------------------ TRACK OUT (SHIFT + SAMPLE, or TRACK OUT > on MAIN)
    def screen_export(self):
        import os
        d, e, c = self.d, self.e, self.c
        what = "the whole SONG" if c.ex_song else f"sequence {e.seq.name}"
        xe = self.title("TRACK OUT")
        self.note(xe + 14, 52, f"every ticked track of {what} to its own WAV")
        self.well((4, 66, 532, 372), 8, (22, 24, 28), 7)
        sel = set(c.ex_tracks())
        seqs = e.song_seqs(c.ex_song)
        for k in range(16):                                          # the 16 tracks: tick = bounce it
            col, r = k // 8, k % 8
            x, y = 8 + col * 262, 70 + r * 37
            trs = [sq.tracks[k] for sq in seqs]
            has = any(t.events for t in trs); midi = all(t.kind == "midi" for t in trs if t.events) and has
            on = k in sel
            self.keycap((x, y, x + 254, y + 33), "lit" if on else "up", 5)
            self.ledp(x + 15, y + 16.5, 5.5, on)
            tr = trs[0]
            self.t(x + 30, y + 12, f"{k + 1:02d} {tr.name[:14]}", 12, on, (255, 255, 255) if on else ((214, 218, 226) if has else (110, 116, 128)), "lm")
            note = "MIDI OUT: NOT AUDIO" if midi else ("MUTED" if tr.mute and has else (KIND_NAMES[tr.kind].upper() if has else "EMPTY"))
            self.lab(x + 30, y + 25, note, 5.4, YEL if midi else ((220, 224, 232) if on else skin.LAB2), "lm", "s", 0.1, floor=5.4)
            self.hit((x, y, x + 254, y + 34), down=lambda *_, k=k: c.ex_toggle(k))
        x0 = 540
        self.plate((x0, 66, 796, 372), 9)
        self.seg(x0 + 8, 77, x0 + 248, 115, ["SEQUENCE", "SONG"], 1 if c.ex_song else 0,
                 lambda k: (setattr(c, "ex_song", bool(k)), setattr(c, "ex_sel", None)), 5.8)
        self.btn((x0 + 10, 120, x0 + 242, 150), ("STEREO MIX: " + ("YES" if c.ex_mix else "NO")), lambda: setattr(c, "ex_mix", not c.ex_mix), 11, on=c.ex_mix)
        self.lab(x0 + 12, 172, "TAIL", 5.8, skin.LAB, "lm", "s", 0.16)
        self.btn((x0 + 60, 158, x0 + 100, 186), "-", lambda: setattr(c, "ex_tail", max(0.0, c.ex_tail - 0.5)), 16)
        self.t(x0 + 140, 172, f"{c.ex_tail:.1f} s", 13, True, TEXT, "mm")
        self.btn((x0 + 180, 158, x0 + 220, 186), "+", lambda: setattr(c, "ex_tail", min(10.0, c.ex_tail + 0.5)), 16)
        dests = c.ex_dests(); dl, dp = dests[c.ex_dest % len(dests)]
        self.lab(x0 + 12, 204, "SAVE TO", 5.8, skin.LAB, "lm", "s", 0.16)
        self.btn((x0 + 10, 214, x0 + 242, 244), dl[:22] + ("  >" if len(dests) > 1 else ""), lambda: setattr(c, "ex_dest", (c.ex_dest + 1) % len(dests)), 11,
                 color=CYAN if dl != "PROJECT" else TEXT)
        secs = e.bounce_length(c.ex_song)
        n = len(sel) + (1 if c.ex_mix else 0)
        self.lab(x0 + 12, 258, f"{n} FILE{'S' if n != 1 else ''} X {secs + c.ex_tail:.1f} S, WAV 32-BIT FLOAT", 5.4, skin.LAB, "lm", "s", 0.1)
        if e.bouncing:
            self.t(x0 + 12, 282, "bouncing " + e.bounce_status, 11, True, ORANGE, "lm")
            self.t(x0 + 12, 300, "outputs are silent meanwhile", 9, False, DIM, "lm")
        elif c.ex_err: self.t(x0 + 12, 282, c.ex_err[:34], 10, True, RED, "lm")
        elif c.ex_files:
            self.t(x0 + 12, 282, f"done: {len(c.ex_files)} files in", 11, True, GREEN, "lm")
            self.t(x0 + 12, 300, os.path.basename(getattr(c, "ex_folder", ""))[:34], 9, False, TEXT, "lm")
        self.btn((x0 + 10, 318, x0 + 242, 358), "BOUNCING..." if e.bouncing else "START TRACK OUT", c.start_track_out, 13,
                 on=e.bouncing, color=ORANGE)

    # ------------------------------------------------------------ MIDI setup (SHIFT + MAIN)
    def screen_midi(self):
        import midi as M
        d, e, c = self.d, self.e, self.c
        mp = c.midi_map
        io = c.midi_io
        names = sorted(io.names.values()) if io else []
        self.title("MIDI")
        live = time.time() - c.midi_seen < 0.3
        self.ledp(68, 52, 6, live, GREEN)
        self.t(84, 52, ("connected: " + ", ".join(sorted({n.split(" ")[0] for n in names}))) if names else "no MIDI device found - plug in the keyboard (USB)", 11, False, TEXT if names else YEL, "lm")
        kc = "any channel" if mp.key_ch == 0 else f"channel {mp.key_ch}"
        self.lab(790, 52, f"KEYS: {kc.upper()}   PADS: CH {mp.pad_ch}, NOTES {mp.pad_base}-{mp.pad_base + 63}", 5.4, skin.LAB, "rm", "s", 0.1)
        self.well((4, 67, 544, 364), 8, (22, 24, 28), 7)
        rows = M.LEARN_TARGETS
        per_col, rh = M.PER_COL, 24
        for i, tname in enumerate(rows):
            col, r = i // per_col, i % per_col
            x, y = 8 + col * 270, 72 + r * rh
            sel = i == c.midi_row
            learning = c.midi_learn == tname
            if learning: self.keycap((x, y, x + 262, y + rh - 3), "lit", 4, YEL)
            else: self.row((x, y, x + 262, y + rh - 3), sel, False, r % 2 == 1, 4)
            self.t(x + 8, y + (rh - 3) / 2, tname, 10.5, True, (255, 255, 255) if (sel or learning) else (196, 201, 210), "lm")
            if tname == "PADS": val = f"ch {mp.pad_ch}, note {mp.pad_base}+"
            else:
                v = mp.learned.get(tname)
                val = "-" if not v else f"{'CC' if v[0] == 'cc' else 'note'} {v[2]}  ch {v[1]}"
            if learning: val = "move / press it now..."
            self.t(x + 254, y + (rh - 3) // 2, val, 10, learning, YEL if learning else (TEXT if val != "-" else DIM), "rm")
            def rdown(px, py, i=i, tname=tname):
                c.midi_row = i
                c.midi_learn = None if c.midi_learn == tname else tname
            self.hit((x, y, x + 262, y + rh - 2), down=rdown)
        # MIDI out per track (current sequence)
        x0 = 548
        self.lab(x0, 80, "MIDI OUT PER TRACK  (TAP = CHANNEL)", 5.4, skin.LAB, "lm", "s", 0.12)
        for k in range(16):
            tr = e.seq.tracks[k]
            col, r = k // 8, k % 8
            x, y = x0 + col * 122, 94 + r * 31
            self.keycap((x, y, x + 116, y + 27), "lit" if tr.midi_ch else "up", 4, CYAN)
            self.t(x + 6, y + 13, f"{k + 1:02d} {tr.name[:6]}", 10, False, TEXT, "lm")
            self.t(x + 110, y + 13, f"ch {tr.midi_ch}" if tr.midi_ch else "off", 10, True, CYAN if tr.midi_ch else DIM, "rm")
            self.hit((x, y, x + 116, y + 28), down=lambda *_, tr=tr: setattr(tr, "midi_ch", (tr.midi_ch + 1) % 17))
        self.note(8, 370, "tap a row, then move / press that control (tap again to cancel). Pads: hit pad 1 while PADS learns.")
        clk = mp.clock + (f"  {e.ext_bpm:.1f}" if mp.clock == "FOLLOW" and e.ext_bpm else "")
        self.btn((x0, 344, x0 + 140, 370), "CLOCK: " + clk, c.cycle_clock, 10, on=mp.clock != "OFF")
        self.btn((x0 + 146, 344, x0 + 244, 370), f"BEND: {mp.bend_range} st", c.cycle_bend, 10)

    STEP_X0, STEP_W = 48, 46.5                                         # step columns (shared by the 16 big steps and the overview below)

    def screen_step(self):
        import pages
        pages.step(self)


    # ------------------------------------------------------------ PROG (drum program / pad editor)
    PROG_ROWS = ["SAMPLE (tap to pick)", "START", "END", "SEMI", "LEVEL", "PAN", "MODE", "CHOKE", "REVERSE", "NORMALIZE", "FADE IN", "FADE OUT",
                 "LO-FI", "OUTPUT", "WARP", "WARP BPM", "ATTACK", "DECAY", "FILTER", "CUTOFF", "RESONANCE", "FILTER ENV", "FILTER DECAY",
                 "VELOCITY > CUTOFF",
                 "LOOP", "LOOP START", "LOOP END", "MOD", "MOD SRC", "MOD AMT", "RANGE", "LOOP POS",
                 "LFO WAVE", "LFO RATE", "LFO DEPTH", "LFO DELAY", "ENV1 ATTACK", "ENV1 DECAY", "ENV1 SUSTAIN", "ENV1 RELEASE",
                 "SLICE", "FINE", "STRETCH", "GAIN", "EFFECT (tap: FX page)", "BYPASS", "P1", "P2", "P3", "P4", "P5", "P6",
                 "SOUND (this program)", "RING (all SP sounds)", "RATE (system)", "TRANSWAVE", "CHANNEL (filter)", "DECAY (SP)",
                 "FX BUS", "FILTER", "CUTOFF F1", "CUTOFF F2", "KBD AMT F1", "KBD AMT F2",
                 "ATTACK", "DECAY 1", "DECAY 2", "DECAY 3", "RELEASE", "INITIAL", "PEAK", "BREAK 1", "BREAK 2", "SUSTAIN",
                 "SOFT VEL", "VEL CURVE", "ENV MODE", "DECAY MODE", "VEL > ATTACK", "VEL > START", "VEL > PITCH",
                 "VEL > LEVEL", "FILTER ATTACK"]

    def asr_value(self, row):
        import asrvoice as AV
        from engine import ASR_RATES
        p, e = self.e.pad, self.e
        rate = ASR_RATES[e.asr_rate]
        reg = p.length / OUT_SR
        le = p.a_le if p.a_le > 0 else reg
        if row == 24: return AV.LOOP_MODES[p.a_loop]
        if row == 25: return f"{p.a_ls * rate:.0f} smp"
        if row == 26: return f"{le * rate:.0f} smp"
        if row == 31: return f"len {max(0.0, le - p.a_ls) * rate:.0f} = {rate / max(1e-6, (le - p.a_ls) * rate) * 1.0:.1f} Hz" if le > p.a_ls else "-"
        if row == 27: return AV.MOD_TYPES[p.a_mod]
        if row == 28: return p.a_src
        if row == 29: return f"{p.a_amt:+d}" if p.a_amt else "0"
        if row == 30: return AV.RANGES[p.a_range].strip() + (" smp" if p.a_mod not in (6, 7) else " (n/a)")
        if row == 32: return AV.LFO_WAVES[p.a_lfo_wave]
        if row == 33: return f"{p.a_lfo_rate}  ({AV._lfo_step(p.a_lfo_rate) / AV.VOICE_TICK_S:.2f} Hz)"
        if row == 34: return str(p.a_lfo_depth)
        if row == 35: return str(p.a_lfo_delay)
        if row in (36, 37, 39): return f"{p.a_env1[{36: 0, 37: 1, 39: 3}[row]]} ms"
        return f"{p.a_env1[2] * 100:.0f}%"

    def prog_label(self, row):
        e = self.e
        if row == 12: return "SAMPLED AT" if e.sound_of(e.pad) == "SP-1200" else "LO-FI (SP flavor)"
        if 46 <= row <= 51:
            fxp = e.get_fx(e.pad)
            return fxp.labels[row - 46][:22] if fxp is not None and row - 46 < fxp.n() else "-"
        if row == 15: return "BPM (WARP)"
        if row == 17 and e.sound_of(e.pad) == "MPC60": return "FADEOUT"
        return self.PROG_ROWS[row]

    def prog_value(self, row):
        p, e = self.e.pad, self.e
        if row == 52: return e.prog.sound if e.prog.sound else "AS MACHINE"
        if row == 53: return "off" if not e.sp_ring else f"{e.sp_ring * 100:.0f}%"
        if row == 54: return "44.1 kHz / 23" if e.asr_rate else "29.76 kHz / 31"
        if row == 55: return "tap: MAKE"
        if row == 77: return ("END", "START")[p.m_dmode]
        if row == 78: return f"+{p.m_vatk} ms soft" if p.m_vatk else "0"
        if row == 79: return f"+{p.m_vstart} ms soft" if p.m_vstart else "0"
        if row == 80: return f"{p.m_vpitch:+d} ct hard" if p.m_vpitch else "0"
        if row == 81: return "curve" if p.vel_mpc is None else f"{p.vel_mpc}"
        if row == 82: return f"{p.f_atk} ms"
        snd_ = e.sound_of(p)
        if snd_ == "MPC60" and 18 <= row <= 23: return "- (no filter)"
        if snd_ in ("MPC3000", "MPC2000XL") and row == 18 and p.flt in ("HP", "BP"): return f"{p.flt} > LP (chip)"
        if 64 <= row <= 68: return f"{p.a_amp_t[row - 64]} ms"
        if 69 <= row <= 73: return str(p.a_amp_l[row - 69])
        if row == 74: return f"{p.a_softvel}% of hard"
        if row in (75, 76):
            import asrvoice as AV; return AV.VEL_CURVES[p.a_vcurve] if row == 75 else AV.ENV_MODES[p.a_emode]
        if row == 58:
            import asrvoice as AV; return AV.BUSES[p.a_bus]
        if row == 59:
            import asrvoice as AV; return AV.FILTER_MODES[p.a_fmode]
        if row in (60, 61): return str(p.a_f1 if row == 60 else p.a_f2) + (" (open)" if (p.a_f1 if row == 60 else p.a_f2) >= 150 else "")
        if row in (62, 63):
            v = p.a_kbd1 if row == 62 else p.a_kbd2; return f"{v:+d}" if v else "0"
        if row == 56:
            ch = e.sp_channel(p)
            return ("AUTO " if not p.sp_ch else "") + f"{ch} " + ("DYN" if ch <= 2 else "FIXED" if ch <= 6 else "NONE")
        if row == 57:
            from engine import sp_decay_of
            v = sp_decay_of(p.decay); return f"{v:02d}" + (" (plays out)" if v >= 31 else "")
        if row == 40:
            if p.src is None: return "-"
            if p.link and p.link[0] == p.src.id: return f"{p.link[1] + 1} of {e.slice_count(p)}"
            return "PAD"
        if row == 41: return f"{p.fine:+d} ct" if p.fine else "0"
        if row == 42: return f"{p.stretch}%" + ("" if p.warp else " (WARP off)")
        if row == 43: return f"{p.gain_db:+.1f} dB"
        if row in (44, 45) or 46 <= row <= 51:
            fxp = e.get_fx(p)
            if row == 44: return fxp.name[:16] if fxp is not None else "- none -"
            if row == 45: return ("BYPASSED" if p.fx_bypass else "on") if fxp is not None else "-"
            return fxp.fmt(row - 46)[:12] if fxp is not None and row - 46 < fxp.n() else ""
        if row >= 24: return self.asr_value(row)
        if row == 0: return (p.src.name if p.link is None else f"{p.src.name} / chop {p.link[1] + 1}") if p.src else "- empty -"
        if row == 1: return f"{p.start / OUT_SR:.3f} s"
        if row == 2: return f"{p.end / OUT_SR:.3f} s"
        if row == 3: from engine import fmt_st; return fmt_st(p.tune)
        if row == 4: return f"{p.vol * 100:.0f}%"
        if row == 5: return "C" if abs(p.pan) < 0.05 else f"{'L' if p.pan < 0 else 'R'}{abs(p.pan) * 100:.0f}"
        if row == 6: return "ONE SHOT" if p.mode == "ONE" else "HOLD (note length)"
        if row == 7: return "off" if not p.choke else f"group {p.choke}"
        if row == 8: return "ON" if p.reverse else "off"
        if row == 9: return "ON" if p.norm else "off"
        if row == 10: return f"{p.fade_in} ms"
        if row == 11: return f"{p.fade_out} ms"
        if row == 12:
            if e.sound_of(p) == "SP-1200":
                from engine import SP_RPMS
                return f"{p.rpm} rpm" + (f" (-{SP_RPMS[p.rpm]} st)" if SP_RPMS.get(p.rpm) else "")
            return "SP-1200" if p.lofi_on else "clean"
        if row == 14: return ("ON - follows tempo" if p.warp else "off")
        if row == 16: return f"{p.attack} ms" if p.attack else "off"
        if row == 17: return f"{p.decay} ms" if p.decay else "off (plays out)"
        if row == 18: return {"OFF": "off", "LP": "LOW-PASS", "HP": "HIGH-PASS", "BP": "BAND-PASS"}[p.flt]
        if row == 19: return f"{e.cut_hz(p.cutoff):.0f} Hz" if e.cut_hz(p.cutoff) < 1000 else f"{e.cut_hz(p.cutoff) / 1000:.1f} kHz"
        if row == 20: return f"{p.res * 100:.0f}%"
        if row == 21: return f"{p.f_env * 100:+.0f}%" if p.f_env else "off"
        if row == 22: return f"{p.f_dec} ms"
        if row == 23: return f"{p.f_vel * 100:.0f}%" if p.f_vel else "off"
        if row == 15:
            if not p.src: return "-"
            b = p.warp_bpm or e.guess_bpm(p)
            return f"{b:.1f}" + ("" if p.warp_bpm else " (guess)") + (f"  = {p.length / OUT_SR * b / 60.0:.2f} beats" if p.warp else "")
        return OUT_NAMES[p.out] + ("" if (p.out == 0 or e.out_ok(p.out)) else " (n/a)")

    def screen_prog(self):
        d, e, c = self.d, self.e, self.c
        p = e.pad
        if c.prog_front and not c.picking:
            import pages
            return pages.prog_front(self)
        for r in range(4):
            for col in range(4):
                i = (3 - r) * 4 + col
                self.pad_tile(10 + col * 80, 48 + r * 80, 76, i, show_len=False)
        self.bank_buttons(338, 48, 34, 72, 8)
        x0 = 386
        self.t(x0, 46, f"{e.prog.name[:12]}", 14, True, (240, 242, 246))
        self.lab(x0 + d.textlength(e.prog.name[:12], font=font(14, True)) + 8, 52, f"PAD {BANKS[e.bank]}{e.sel + 1:02d}", 6.6, ORANGE, "lm", "s", 0.14)
        self.hit((x0, 40, x0 + 150, 70), down=lambda *_: c.rename_program())               # tap the program name to rename it
        unflat = getattr(p, "_unflat", None) is not None
        if not c.picking:
            self.btn((556, 42, 654, 68), "UNFLATTEN" if unflat else "FLATTEN", c.flatten_toggle, 10, color=YEL if unflat else CYAN)
        self.btn((660, 42, 724, 68), "PRG -", lambda: setattr(e.track, "prog", (e.track.prog - 1) % NPROG), 11)
        self.btn((728, 42, 792, 68), "PRG +", lambda: setattr(e.track, "prog", (e.track.prog + 1) % NPROG), 11)
        if c.picking:
            self.t(x0, 78, "CHOOSE A SAMPLE", 11, True, DIM)
            self.btn((680, 70, 792, 92), "BROWSE FILES", lambda: c.set_mode("BROWSE"), 10, color=CYAN)
            self.btn((590, 70, 674, 92), "RENAME", c.rename_picked, 10)
            items = [("- empty pad -", 0)] + [(s.name, s.length) for s in e.sources]
            top = clamp(c.pick_cur - 5, 0, max(0, len(items) - 11))
            for r in range(11):
                i = top + r
                if i >= len(items): break
                y = 96 + r * 25
                cur = (i - 1) == c.pick_cur if False else i == c.pick_cur + 0
                sel = i == c.pick_cur
                d.rounded_rectangle([x0, y, 792, y + 23], 4, fill=PANEL2 if sel else PANEL, outline=ORANGE if sel else LINE)
                self.t(x0 + 10, y + 12, items[i][0], 12, sel, TEXT if sel else DIM, "lm")
                self.t(782, y + 12, f"{items[i][1] / OUT_SR:.2f} s" if i else "", 11, False, DIM, "rm")
                def pdown(px, py, i=i):
                    if c.pick_cur == i:
                        c.ok()
                    else: c.pick_cur = i
                self.hit((x0, y, 792, y + 24), down=pdown)
            return
        # the tabs, then the page drawn as a panel (progpanel): each setting the control it is; SAMPLES is a wave view
        if c.prog_row not in c.PROG_TABS[c.prog_tab][1]: c.prog_tab = c.prog_tab_of(c.prog_row)
        tabs_ = c.PROG_TABS
        SHORT = {"ENVELOPES": "ENVELOPE", "MODULATION": "MOD"}
        SHOWN = {"GLOBAL": "PAD", "SAMPLES": "SAMPLE", "ENVELOPES": "ENV / FILTER"}       # what each page holds
        self.well((x0, 73, 792, 99), 6, (22, 24, 28), 5)                # GLOBAL / SAMPLES / ENVELOPES / (LFO / MODULATION) / EFFECTS
        sw_ = (792 - x0 - 6 - 3 * (len(tabs_) - 1)) / float(len(tabs_))
        for k, (tname, rows_) in enumerate(tabs_):
            bx = x0 + 3 + k * (sw_ + 3)
            lab_ = SHORT.get(tname, SHOWN.get(tname, tname)) if len(tabs_) > 4 else SHOWN.get(tname, tname)
            if len(tabs_) > 4 and tname in ("GLOBAL", "SAMPLES"): lab_ = SHOWN[tname]
            on_ = k == c.prog_tab
            self.keycap((bx, 76, bx + sw_, 96), "down" if on_ else "up", 4.5)
            if on_: self.ledp(bx + 9, 86, 3.4, True)
            self.lab(bx + sw_ / 2 + (4 if on_ else 0), 86, lab_, 5.8, (244, 246, 249) if on_ else (140, 147, 160), "mm", "s", 0.08)
            self.hit((bx, 73, bx + sw_, 99), down=lambda *_, k=k: c.set_prog_tab(k))
        import progpanel
        progpanel.page(self, x0, 104, 792, 370)

    def asr_env_graph(self, x0, y0, x1, y1, p):
        """the ASR-10 amp envelope's shape: hard velocity (bright) and soft (dim), held a moment at SUSTAIN, then RELEASE"""
        import asrvoice as AV
        d = self.d
        d.rounded_rectangle([x0, y0, x1, y1], 5, fill=PANEL, outline=LINE)
        hold = sum(p.a_amp_t[:4]) / 1000.0
        off = hold + max(0.15, 0.25 * hold)
        tot = off + p.a_amp_t[4] / 1000.0 + 0.05
        w, h = x1 - x0 - 16, y1 - y0 - 30
        n = max(2, int(w))
        sr = n / tot
        for vel, col in ((1, DIM), (127, ORANGE)):
            g, _ = AV.amp_env(p, vel, 0.0, n, sr, off)
            pts = [(x0 + 8 + k, y1 - 10 - float(g[k]) * h) for k in range(n)]
            d.line(pts, fill=col, width=2)
        ox = x0 + 8 + off / tot * w
        d.line([ox, y0 + 18, ox, y1 - 8], fill=LINE)
        self.t(x0 + 8, y0 + 10, "AMP ENV", 9, True, DIM, "lm")
        self.t(x1 - 8, y0 + 10, "hard", 8, True, ORANGE, "rm")
        self.t(ox - 3, y0 + 26, "off", 8, False, DIM, "rm")

    # ------------------------------------------------------------ SAMPLE (record)
    def screen_sample(self):
        import pages
        pages.sample(self)


    # ------------------------------------------------------------ CHOP (non-destructive)
    def screen_chop(self):
        import pages
        pages.chop(self)


    # ------------------------------------------------------------ MIXER
    def screen_mixer_pads(self):
        """a console: 16 channel strips (pads of the bank, or tracks) and the master. Each strip: LED meter, fader in its
        slot, pan knob, number and name, mute / solo keys, where it goes"""
        d, e, c = self.d, self.e, self.c
        tracks = c.mix_page == 1
        top, bot = 82, 222
        self.t(10, 52, "TRACK MIXER" if tracks else "PAD MIXER", 15, True, (240, 242, 246), "lm")
        if not tracks:
            tx = 10 + d.textlength("PAD MIXER", font=font(15, True)) + 12
            self.lab(tx, 53, f"OF PGM {e.track.prog + 1:02d} {e.prog.name.upper()[:12]}   BANK {BANKS[e.bank]}", 6.6, ORANGE, "lm", "s", 0.14)
        else:
            tx = 10 + d.textlength("TRACK MIXER", font=font(15, True)) + 12
            self.lab(tx, 53, f"SEQUENCE {e.cur_seq + 1:02d} {e.seq.name.upper()[:14]}", 6.6, ORANGE, "lm", "s", 0.14)
        self.well((596, 38, 794, 68), 7, (22, 24, 28), 5)
        for k_, (lab_, on_) in enumerate((("PADS", not tracks), ("TRACKS", tracks))):
            bx = 599 + k_ * 98
            self.keycap((bx, 41, bx + 94, 65), "down" if on_ else "up", 5)
            if on_: self.ledp(bx + 12, 53, 3.6, True)
            self.lab(bx + 49, 53, lab_, 6.4, (244, 246, 249) if on_ else (140, 147, 160), "mm", "s", 0.14)
            self.hit((bx, 38, bx + 94, 68), down=lambda *_, p=k_: (setattr(c, "mix_page", p), setattr(c, "armed", [False] * 4)))
        self.plate((4, 72, 744, 336), 9)
        self.plate((748, 72, 796, 336), 9)
        for n in range(16):
            x = 8 + n * 46
            if tracks: o = e.seq.tracks[n]; selected = n == e.cur_track; meter = e.track_meter[n]
            else: o = e.prog.pads[e.bank * 16 + n]; selected = n == e.sel; meter = o.meter
            if selected: d.rounded_rectangle([x, 75, x + 44, 333], 6, fill=(46, 50, 58), outline=mix((46, 50, 58), ORANGE, 0.75), width=1.2)
            elif n: d.line([x - 1, 80, x - 1, 328], fill=(33, 36, 41))
            self.vmeter(x + 6, top, x + 11, bot, min(1.0, meter * 1.3), 24)
            self.well((x + 21, top - 2, x + 27, bot + 2), 3, (12, 13, 15), 4)
            for k in range(11):                                       # fader scale
                ty = bot - (bot - top) * k / 10.0
                d.line([x + 31, ty, x + (37 if k in (0, 5, 10) else 34), ty], fill=(78, 83, 94))
            fy = bot - (bot - top) * o.vol
            sp, ox, oy = skin.body(self.P(28), self.P(14), self.P(3), (88, 93, 104), (52, 56, 64), 0.18, 0.4, (6, 0.6))
            self.put(sp, x + 10, fy - 7, ox, oy)
            d.line([x + 12, fy, x + 36, fy], fill=(30, 32, 37), width=1.6)
            d.line([x + 12, fy - 0.8, x + 36, fy - 0.8], fill=DIM if o.mute else ORANGE, width=1)
            if selected and c.mix_row == 0: d.rounded_rectangle([x + 8, fy - 9, x + 40, fy + 9], 4, outline=YEL, width=1)
            kd = self.P(17)                                             # pan: a small knob, centre detent
            sp, off = skin.knob(kd, (o.pan + 1) / 2.0, mix((60, 64, 72), CYAN, 0.9), True)
            self.img.paste(sp, (self.P(x + 22) - kd // 2 - off, self.P(240) - kd // 2 - off), sp)
            if selected and c.mix_row == 1: d.rounded_rectangle([x + 6, 228, x + 38, 252], 5, outline=YEL, width=1)
            self.t(x + 22, 262, f"{n + 1}", 11, True, (244, 246, 249) if selected else (150, 156, 168), "mm")
            nm = o.name[:6] if tracks else (o.src.name[:6] if o.src else "-")
            self.lab(x + 22, 274, nm.upper().replace("_", " ").strip()[:5] or "-", 5.6, ORANGE if selected else skin.LAB2, "mm", "s", 0.02, floor=5.6)
            self.btn((x + 3, 283, x + 21, 305), "M", lambda o=o, n=n: (c._mx_sel(n), setattr(o, "mute", not o.mute)), 10,
                     fill=(120, 34, 34) if o.mute else PANEL2, color=TEXT if o.mute else DIM, outline=RED if o.mute else LINE)
            self.btn((x + 23, 283, x + 41, 305), "S", lambda o=o, n=n: (c._mx_sel(n), setattr(o, "solo", not o.solo)), 10,
                     fill=(120, 100, 20) if o.solo else PANEL2, color=TEXT if o.solo else DIM, outline=YEL if o.solo else LINE)
            if tracks: self.lab(x + 22, 316, f"P{o.prog + 1}", 5.2, skin.LAB, "mm", "s", 0.1)
            else:
                tag = "MIX" if not o.out else OUT_NAMES[o.out].upper()
                self.lab(x + 22, 315, tag, 5.0, (ORANGE if e.out_ok(o.out) else RED) if o.out else skin.LAB2, "mm", "s", 0.08)
                if o.fx is not None: self.lab(x + 22, 325, "FX", 5.0, DIM if o.fx_bypass else CYAN, "mm", "s", 0.1)
            def set_vol(py, o=o): o.vol = clamp((bot - py) / float(bot - top), 0.0, 1.0)
            def set_pan(px, o=o, x=x): o.pan = round(clamp((px - (x + 22)) / 14.0, -1.0, 1.0), 2)
            def vdown(px, py, n=n, set_vol=set_vol): c._mx_sel(n); c.mix_row = 0; set_vol(py)
            def pdown(px, py, n=n, set_pan=set_pan): c._mx_sel(n); c.mix_row = 1; set_pan(px)
            self.hit((x, top - 6, x + 44, bot + 4), down=vdown, drag=lambda px, py, set_vol=set_vol: set_vol(py))
            self.hit((x, 230, x + 44, 250), down=pdown, drag=lambda px, py, set_pan=set_pan: set_pan(px))
            self.hit((x, 252, x + 44, 282), down=lambda *_, n=n: c._mx_sel(n))
        mm = min(1.0, e.master_meter)                                  # the master: a stereo pair of LED columns
        self.vmeter(758, top, 768, bot, mm, 24); self.vmeter(772, top, 782, bot, mm, 24)
        self.lab(772, 262, "OUT", 6.4, (220, 224, 232), "mm", "s", 0.16)
        self.lab(772, 274, "MASTER", 4.6, skin.LAB2, "mm", "s", 0.1)
        has = e.master_fx is not None
        self.keycap((753, 283, 791, 305), "lit" if has and not e.master_fx_bypass else "up", 5, CYAN)
        self.lab(772, 294, "FX" if has else "+ FX", 5.6, (240, 250, 252) if has else (150, 156, 168), "mm", "s", 0.1)
        self.hit((750, top - 4, 794, 330), down=lambda *_: (setattr(c, "fx_target", 64), c.set_mode("FX")))
        if not tracks:
            sel = e.pad; okc = sel.out == 0 or e.out_ok(sel.out)
            self.btn((8, 342, 230, 368), f"PAD {e.sel + 1} OUTPUT:  {OUT_NAMES[sel.out]}" + ("" if okc else " (n/a)"), lambda: e.cycle_out(sel, 1), 11,
                     outline=YEL if c.mix_row == 2 else LINE)
            self.note(242, 355, f"tap to change - your sound card has {e.nout} outputs")
        else:
            self.note(10, 355, "tracks use their program's pad effects and outputs (change those on the PADS page)")

    # ------------------------------------------------------------ MIXER: the console (desk C, American; MixerAmerican artboard)
    CON_INK, CON_DIM, CON_PANEL = (233, 226, 207), (142, 138, 128), (24, 25, 28)

    def screen_mixer(self):
        c = self.c
        if c.mix_view == "PADS": return self.screen_mixer_pads()
        d, e = self.d, self.e
        y0, y1 = 46, 367
        sh = skin.body(self.P(788), self.P(y1 - y0), self.P(4), (36, 37, 40), (20, 21, 23), 0.06, 0.0, (12, 0.6))
        self.put(sh[0], 6, y0, sh[1], sh[2])
        d.rectangle([7, y1 - 3, 793, y1], fill=(58, 40, 28))                   # the wooden lip under the desk
        strips = c.mix_strips()
        xs = [8 + k * 66.25 for k in range(8)] + [542.5, 603.75] + [670.0]
        ws = [66.25] * 8 + [61.25, 61.25] + [122.5]
        for x in (538.8, 665.2):                                               # gaps between programs / returns / master
            d.rectangle([x, y0 + 1, x + 3.5, y1 - 4], fill=(6, 6, 8))
        for k, (kind, st, label) in enumerate(strips):
            self.con_strip(k, kind, st, label, xs[k], ws[k], y0, y1)
        if c.eq_open: self.eq_page()

    def con_vu(self, x, y, w, h, st, ch, key):
        face = skin.vu_face(self.P(w), self.P(h))
        self.img.paste(face, (self.P(x), self.P(y)), face)
        lvl = st.meter[ch] if ch < 2 else max(st.meter)
        import console as K
        vu = (K.db(lvl) + 20.0) / 23.0 if lvl > 1e-5 else 0.0                 # -20 .. +3 VU, 0 VU = -3 dBFS peaks
        sm = self._vu.get(key, 0.0); sm += (vu - sm) * (0.35 if vu > sm else 0.12); self._vu[key] = sm
        (ax, ay), (bx, by) = skin.vu_needle(w, h, sm)
        self.d.line([x + ax, y + ay, x + bx, y + by], fill=(28, 22, 16), width=1.3)
        self.d.rounded_rectangle([x - 0.5, y - 0.5, x + w + 0.5, y + h + 0.5], 3, outline=(8, 8, 10), width=1.2)

    def con_label(self, x, y, txt, col=None, anchor="lm", size=5.0):
        if anchor == "la": anchor = "lm"
        if anchor == "ra": anchor = "rm"
        self.lab(x, y, txt, size, col or self.CON_DIM, anchor, "s", 0.12, floor=size)

    _mono = {}

    def mono(self, x, y, txt, size, col, anchor="lm"):
        """monospaced text (the console's scribble / insert displays)"""
        px = self.P(size)
        f = Renderer._mono.get(px)
        if f is None:
            from PIL import ImageFont
            for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"):
                try: f = ImageFont.truetype(path, px); break
                except OSError: pass
            f = f or font(int(size), False)
            Renderer._mono[px] = f
        ImageDraw.Draw(self.img).text((self.P(x), self.P(y)), txt, font=f, fill=col, anchor=anchor)

    def con_knob(self, cx, cy, dia, frac, getter, setter, sel=False, centre=False):
        kd = self.P(dia)
        sp, pad = skin.cknob(kd, frac, centre)
        self.img.paste(sp, (self.P(cx) - kd // 2 - pad, self.P(cy) - kd // 2 - pad), sp)
        if sel: self.d.ellipse([cx - dia / 2 - 2.5, cy - dia / 2 - 2.5, cx + dia / 2 + 2.5, cy + dia / 2 + 2.5], outline=YEL, width=1)
        st = {}
        def down(px, py): st["y"], st["v"] = py, getter()
        def drag(px, py): setter(clamp(st["v"] + (st["y"] - py) / 60.0, 0.0, 1.0))
        self.hit((cx - dia / 2 - 4, cy - dia / 2 - 4, cx + dia / 2 + 4, cy + dia / 2 + 4), down=down, drag=drag)

    def con_key(self, rect, text, lit=False, col=None, down=None, size=5.2):
        x0, y0, x1, y1 = rect
        if lit:
            lc = col or (238, 232, 214)
            sp, ox, oy = skin.body(self.P(x1 - x0), self.P(y1 - y0), self.P(2.5), mix(lc, (255, 255, 255), 0.2), mix(lc, (0, 0, 0), 0.12),
                                   0.25, 0.25, (4, 0.5), None, (lc, 6, 0.35))
            tc = (24, 24, 26) if sum(lc) > 450 else (255, 255, 255)
        else:
            sp, ox, oy = skin.body(self.P(x1 - x0), self.P(y1 - y0), self.P(2.5), (50, 51, 55), (34, 35, 38), 0.1, 0.35, (4, 0.5))
            tc = (168, 164, 154)
        self.put(sp, x0, y0, ox, oy)
        self.lab((x0 + x1) / 2, (y0 + y1) / 2, text, size, tc, "mm", "s", 0.08, floor=size)
        if down: self.hit((x0 - 1, y0 - 2, x1 + 1, y1 + 2), down=lambda *_: down())

    def con_inserts(self, x, y, w, slots, names, target_of, header="INSERTS"):
        d, c = self.d, self.c
        self.con_label(x + 3, y + 1.5, header)
        bx0, by0, bx1, by1 = x + 2, y + 4, x + w - 2, y + 23
        d.rounded_rectangle([bx0, by0, bx1, by1], 2, fill=(14, 12, 11))
        room = max(3, int((bx1 - bx0 - 9) / 4.6))
        for i in range(2):
            ly = by0 + 1 + i * 9.0
            nm = names[i] if i < len(names) else None
            if nm: d.rectangle([bx0 + 1, ly, bx1 - 1, ly + 8.2], fill=(40, 22, 8))
            d.ellipse([bx0 + 3, ly + 3, bx0 + 5.2, ly + 5.2], fill=(255, 150, 60) if nm else (60, 60, 64))
            self.mono(bx0 + 7.5, ly + 4.3, (nm or f"INS {i + 1}")[:room], 7.6, (255, 160, 72) if nm else (70, 72, 76))
            t = target_of(i)
            if t is not None: self.hit((bx0, ly - 1, bx1, ly + 9), down=lambda *_, t=t: (setattr(c, "fx_target", t), c.set_mode("FX")))

    def con_eq_thumb(self, x, y, w, st, key, on_tap):
        import console as K
        d = self.d
        self.con_label(x + 3, y + 1.5, "EQ"); self.con_label(x + w - 3, y + 1.5, "TAP", anchor="ra")
        bx0, by0, bx1, by1 = x + 2, y + 4, x + w - 2, y + 27
        d.rounded_rectangle([bx0, by0, bx1, by1], 2, fill=(14, 12, 10))
        for gx in (0.25, 0.5, 0.75): d.line([bx0 + (bx1 - bx0) * gx, by0 + 2, bx0 + (bx1 - bx0) * gx, by1 - 2], fill=(34, 30, 26))
        d.line([bx0 + 2, (by0 + by1) / 2, bx1 - 2, (by0 + by1) / 2], fill=(38, 33, 28))
        act = st.eq_on and K.eq_active(st.eq)
        ck = ("eqthumb", repr(st.eq), st.eq_on, int(bx1 - bx0))
        pts = self._eqc.get(ck)
        if pts is None:
            n = 40; fr = 20.0 * 1000.0 ** (np.arange(n) / (n - 1.0))
            r = K.eq_response(st.eq, fr) if act else np.zeros(n)
            pts = [(i / (n - 1.0), float(np.clip(v, -18, 18))) for i, v in enumerate(r)]
            if len(self._eqc) > 200: self._eqc.clear()
            self._eqc[ck] = pts
        mid, sc = (by0 + by1) / 2, (by1 - by0 - 5) / 36.0
        line = [(bx0 + 2 + f * (bx1 - bx0 - 4), mid - v * sc) for f, v in pts]
        if act: d.line(line, fill=mix((14, 12, 10), ORANGE, 0.35), width=3)
        d.line(line, fill=ORANGE if act else (90, 80, 70), width=1.2)
        self.lab(bx1 - 2, by0 + 3, "EQ" if act else "OFF", 4.6, ORANGE if act else (86, 82, 76), "ra", "b", 0.05, floor=4.6)
        self.hit((bx0, by0, bx1, by1), down=lambda *_: on_tap())

    def con_fader(self, x, w, st, kind, sel, y0=250, y1=352):
        import console as K
        d, c, e = self.d, self.c, self.e
        cx = x + w / 2
        sends = c.mix_view == "SENDS" and kind == "prog"
        if kind == "master": f = K.gain_to_fader(e.volume / 0.8)
        elif sends: f = st.sends[c.mix_send]
        else: f = K.gain_to_fader(st.level)
        d.rounded_rectangle([cx - 2.2, y0, cx + 2.2, y1], 2, fill=(6, 6, 7))
        marks = (("+10", 1.0), ("5", 0.875), ("0", 0.75), ("5", 0.62), ("10", 0.5), ("20", 0.33), ("30", 0.18), ("\u221e", 0.0))
        for t, fv in marks:
            yy = y1 - (y1 - y0) * fv
            self.lab(cx - 9, yy, t, 4.4, (150, 146, 136), "rm", "s", 0.0, floor=4.4)
            d.line([cx + 7, yy, cx + 11, yy], fill=(140, 136, 126), width=1)
        fy = y1 - (y1 - y0) * f
        cap = skin.fader_cap(self.P(18), self.P(10))
        self.put(cap[0], cx - 9, fy - 5, cap[1], cap[2])
        if sends: d.line([cx - 7, fy + 3.6, cx + 7, fy + 3.6], fill=(80, 150, 255) if c.mix_send else (230, 70, 60), width=1.2)
        if sel and c.mix_param == 0: d.rounded_rectangle([cx - 11, fy - 7, cx + 11, fy + 7], 3, outline=YEL, width=1)
        def setf(py):
            v = clamp((y1 - py) / float(y1 - y0), 0.0, 1.0)
            if kind == "master": e.volume = clamp(K.fader_to_gain(v) * 0.8, 0.0, 1.25)
            elif sends: st.sends[c.mix_send] = v
            else: st.level = K.fader_to_gain(v)
        self.hit((x + 2, y0 - 6, x + w - 2, y1 + 6), down=lambda px, py, i=None: setf(py), drag=lambda px, py: setf(py))

    def con_screws(self, x, w, y):
        for sx in (x + 6, x + w - 6):
            self.d.ellipse([sx - 2.4, y - 2.4, sx + 2.4, y + 2.4], fill=(150, 152, 156)); self.d.line([sx - 1.6, y, sx + 1.6, y], fill=(60, 62, 66))

    def con_strip(self, k, kind, st, label, x, w, y0, y1):
        import console as K
        d, c, e = self.d, self.c, self.e
        sel = k == c.mix_strip
        if not hasattr(self, "_vu"): self._vu, self._eqc = {}, {}
        if sel: d.rectangle([x + 0.5, y0 + 1, x + w - 0.5, y1 - 4], fill=(32, 33, 37))
        elif k < 8: d.line([x + w - 0.3, y0 + 2, x + w - 0.3, y1 - 5], fill=(10, 10, 12))
        sel_fn = lambda k=k: c.mix_select(k)
        # meters
        if kind == "master":
            self.con_vu(x + 6, 51, w / 2 - 8, 31, st, 0, ("m", 0)); self.con_vu(x + w / 2 + 2, 51, w / 2 - 8, 31, st, 1, ("m", 1))
        else: self.con_vu(x + 4, 51, w - 8, 31, st, 2, (kind, k))
        for i in (0, 1): st.meter[i] *= 0.8
        # name plate
        ink = (240, 236, 224) if sel else (210, 206, 194)
        d.rounded_rectangle([x + 3, 85.5, x + w - 3, 95.5], 2, fill=(38, 39, 43) if not sel else mix((38, 39, 43), ORANGE, 0.25),
                            outline=ORANGE if sel else None, width=1)
        if kind == "prog" and k < len(e.programs):                     # a program's channel: its number, its name; unused ones dim
            pr_ = e.programs[k]
            used = any(not p_.empty for p_ in pr_.pads)
            if not used and not sel: ink = (110, 108, 102)
            self.lab(x + 5, 90.5, f"P{k + 1}", 4.8, ORANGE if used else (120, 96, 60), "lm", "b", 0.0, floor=4.4)
            self.lab(x + w / 2 + 6, 90.5, (label.upper() if used else "EMPTY")[:10], 5.0, ink, "mm", "b", 0.04, floor=4.2, maxw=w - 22)
        else: self.lab(x + w / 2, 90.5, label.upper()[:12], 5.6, ink, "mm", "b", 0.06, floor=5.6)
        self.hit((x, 84, x + w, 97), down=lambda *_: sel_fn())
        # inserts
        if kind == "prog":
            pr = e.programs[k]
            names = [f.name if f is not None else None for f in pr.fx]
            self.con_inserts(x, 100, w, 2, names, lambda i, pr=pr: (65 + i) if pr is e.prog else None)
        elif kind in ("rtn", "grp"):
            names = [f.name if f is not None else None for f in getattr(st, "fx", [])] if kind == "rtn" else []
            self.con_inserts(x, 100, w, 2, names, (lambda i, k=k: 69 + (k - 8) * 2 + i) if kind == "rtn" else (lambda i: None),
                             "INSERTS" if kind == "rtn" else "GROUP BUS")
        else:
            names = [e.master_fx.name if e.master_fx else None, st.fx[0].name if st.fx[0] else None]
            self.con_inserts(x, 100, w, 2, names, lambda i: 64 if i == 0 else 73, "STEREO BUS INSERTS")
        self.con_eq_thumb(x, 129, w, st, k, lambda k=k: (c.mix_select(k), c.eq_toggle(True)))
        # sends / return info / master section
        if kind == "prog":
            self.con_label(x + 3, 161, "SENDS")
            for j, cxk in enumerate((x + w * 0.3, x + w * 0.7)):
                self.con_knob(cxk, 174, 13, st.sends[j], lambda j=j, st=st: st.sends[j], lambda v, j=j, st=st: st.sends.__setitem__(j, v),
                              sel and c.mix_param == 2 + j)
                self.con_label(cxk, 185, "AB"[j], anchor="mm")
        elif kind in ("rtn", "grp"):
            fxn = next((f.name for f in getattr(st, "fx", []) if f is not None), None) if kind == "rtn" else None
            self.con_label(x + 3, 161, ((fxn or "EMPTY") + " RTN").upper()[:14] if kind == "rtn" else label.upper(), self.CON_INK)
            self.con_label(x + 3, 175.5, "TO", anchor="lm", size=4.6)
            self.con_key((x + w - 25, 171, x + w - 4, 180), st.out, True, None, lambda st=st, kind=kind: c.mix_cycle_out(st, kind), 5.0)
        else:
            self.con_label(x + 6, 161, "SEND MASTERS")
            for j, cxk in enumerate((x + 22, x + 44)):
                self.con_knob(cxk, 174, 13, e.send_master[j], lambda j=j: e.send_master[j], lambda v, j=j: e.send_master.__setitem__(j, v),
                              sel and c.mix_param == 2 + j)
                self.con_label(cxk, 185, "AB"[j], anchor="mm")
            self.con_label(x + 6, 191, "MONITOR")
            self.con_knob(x + 22, 202, 12, e.monitor, lambda: e.monitor, lambda v: setattr(e, "monitor", v), sel and c.mix_param == 1)
            self.con_label(x + 22, 212.5, "LEVEL", anchor="mm")
            self.con_key((x + 40, 197, x + w - 6, 206), "DIM", e.dim, (255, 196, 92), lambda: setattr(e, "dim", not e.dim), 5.4)
        # pan
        if kind != "master":
            self.con_label(x + 3, 191, "PAN")
            self.con_knob(x + w / 2, 201, 15, (st.pan + 1) / 2, lambda st=st: (st.pan + 1) / 2,
                          lambda v, st=st: setattr(st, "pan", round(v * 2 - 1, 2)), sel and c.mix_param == 1, True)
            self.con_label(x + 3, 209.5, "L"); self.con_label(x + w - 3, 209.5, "R", anchor="ra")
        # group buttons, mute / solo
        if kind == "prog":
            bw = (w - 8) / 3.0
            for j, g in enumerate(K.OUTS):
                bx = x + 3 + j * (bw + 1)
                self.con_key((bx, 218, bx + bw, 227), g, st.out == g, None, lambda st=st, g=g: setattr(st, "out", g), 4.8)
        if kind != "master":
            hw = (w - 7) / 2.0
            self.con_key((x + 3, 230, x + 3 + hw, 239.5), "MUTE", st.mute, (58, 208, 106), lambda st=st: setattr(st, "mute", not st.mute), 4.8)
            self.con_key((x + 4 + hw, 230, x + w - 3, 239.5), "SOLO", st.solo, (240, 200, 60), lambda st=st: setattr(st, "solo", not st.solo), 4.8)
        self.con_fader(x, w, st, kind, sel)
        self.con_screws(x, w, 361)

    def eq_page(self):
        """the full parametric EQ lifts out of the strip (MixerEQ artboard)"""
        import console as K
        d, c, e = self.d, self.c, self.e
        kind, st, label = c.mix_sel()
        x0, y0, x1, y1 = 37, 60, 762, 364
        self.hit((x0, y0, x1, y1), down=lambda *_: None)
        sp = skin.body(self.P(x1 - x0), self.P(y1 - y0), self.P(5), (34, 35, 38), (22, 23, 26), 0.08, 0.2, (20, 0.8))
        self.put(sp[0], x0, y0, sp[1], sp[2])
        for sx, sy in ((x0 + 6, y0 + 6), (x1 - 6, y0 + 6), (x0 + 6, y1 - 6), (x1 - 6, y1 - 6)):
            d.ellipse([sx - 2.4, sy - 2.4, sx + 2.4, sy + 2.4], fill=(150, 152, 156)); d.line([sx - 1.6, sy, sx + 1.6, sy], fill=(60, 62, 66))
        self.lab(x0 + 20, y0 + 10, "CHANNEL EQ", 6.6, self.CON_INK, "lm", "b", 0.24)
        d.rounded_rectangle([x0 + 145, y0 + 5, x0 + 205, y0 + 15], 2, fill=(46, 47, 52))
        self.lab(x0 + 175, y0 + 10, label.upper()[:12], 5.6, (230, 230, 232), "mm", "b", 0.04, floor=5.6)
        bx = x1 - 196
        for t, on, col, fn in (("IN", st.eq_on, (72, 200, 96), lambda: setattr(st, "eq_on", not st.eq_on)),
                               ("A / B", c.eq_is_b(), (200, 200, 205), c.eq_swap_ab),
                               ("ANALYZER", c.eq_analyser, (232, 168, 60), lambda: setattr(c, "eq_analyser", not c.eq_analyser)),
                               ("CLOSE", False, None, lambda: c.eq_toggle(False))):
            self.con_key((bx, y0 + 4, bx + 45, y0 + 16), t, on, col, fn, 4.6); bx += 48
        # the graph
        gx0, gy0, gx1, gy1 = x0 + 15, y0 + 23, x1 - 72, y0 + 198          # narrower: the OUTPUT column on its right
        self.glassbox((gx0, gy0, gx1, gy1), 5)
        px0, px1, py0, py1 = gx0 + 26, gx1 - 6, gy0 + 6, gy1 - 16
        fx_ = lambda f: px0 + (px1 - px0) * math.log(f / 20.0) / math.log(1000.0)
        fy_ = lambda g: py0 + (py1 - py0) * (18 - g) / 36.0
        for g in (12, 6, 0, -6, -12):
            d.line([px0, fy_(g), px1, fy_(g)], fill=(40, 36, 30) if g else (60, 52, 40))
            self.lab(px0 - 4, fy_(g), f"{g:+d}", 4.6, (120, 112, 100), "rm", "s", 0.0, floor=4.6)
        for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
            d.line([fx_(f), py0, fx_(f), py1], fill=(36, 33, 29))
            self.lab(fx_(f), py1 + 7, (f"{f // 1000}k" if f >= 1000 else str(f)), 4.6, (120, 112, 100), "mm", "s", 0.0, floor=4.6)
        if c.eq_analyser and len(e.an_buf):                                   # the signal after the EQ, as a soft green hill
            x = e.an_buf * np.hanning(len(e.an_buf))
            mag = np.abs(np.fft.rfft(x)) + 1e-9
            fr = np.fft.rfftfreq(len(x), 1 / 44100.0)
            cols = 120; edges = 20.0 * 1000.0 ** (np.arange(cols + 1) / float(cols))
            idx = np.searchsorted(fr, edges)
            band = np.array([mag[max(1, idx[i]):max(idx[i] + 1, idx[i + 1])].max() for i in range(cols)])
            dbv = 20 * np.log10(band / len(x) * 4)
            sm = getattr(self, "_an_sm", None)
            sm = dbv if sm is None or len(sm) != cols else np.maximum(dbv, sm - 3.0)
            self._an_sm = sm
            pts = [(px0 + (px1 - px0) * i / (cols - 1.0), clamp(fy_(-18 + (v + 72) / 72.0 * 30), py0, py1)) for i, v in enumerate(sm)]
            d.polygon([(px0, py1)] + pts + [(px1, py1)], fill=(28, 70, 52))
        fl = (np.arange(160) / 159.0)
        fr = 20.0 * 1000.0 ** fl
        resp = K.eq_response(st.eq, fr) if st.eq_on else np.zeros(len(fr))
        line = [(px0 + (px1 - px0) * a, clamp(fy_(float(v)), py0, py1)) for a, v in zip(fl, resp)]
        d.polygon([(px0, fy_(0))] + line + [(px1, fy_(0))], fill=mix((14, 12, 10), ORANGE, 0.14))
        d.line(line, fill=mix((14, 12, 10), ORANGE, 0.4), width=4); d.line(line, fill=ORANGE, width=1.6)
        BAND_COL = [(226, 64, 56), (236, 168, 60), (72, 200, 96), (70, 130, 230), (140, 140, 146)]
        for i, b in enumerate(st.eq):
            if not b.get("on") and i == 4: continue
            gx = fx_(b["freq"]); gy = fy_(0 if i == 0 else b["gain"]) if b.get("on") else fy_(0)
            if i == 0 and b.get("on"): gy = fy_(float(K.eq_response(st.eq, [b["freq"]])[0]))
            r_ = 5.5
            if i == c.eq_band: d.ellipse([gx - r_ - 3, gy - r_ - 3, gx + r_ + 3, gy + r_ + 3], outline=mix(BAND_COL[i], (20, 20, 20), 0.3), width=1)
            d.ellipse([gx - r_, gy - r_, gx + r_, gy + r_], fill=(24, 24, 26) if b.get("on") else (40, 40, 44), outline=BAND_COL[i], width=1.5)
            self.lab(gx, gy, str(i + 1), 4.8, (240, 240, 240), "mm", "b", 0.0, floor=4.8)
        drag_st = {}
        def gdown(px, py):
            near = min(range(5), key=lambda i: abs(fx_(st.eq[i]["freq"]) - px) + (0 if st.eq[i].get("on") or i < 4 else 999))
            c.eq_band = near; drag_st["b"] = near; gdrag(px, py)
        def gdrag(px, py):
            b = st.eq[drag_st.get("b", c.eq_band)]
            b["freq"] = clamp(20.0 * 1000.0 ** ((px - px0) / float(px1 - px0)), 20.0, 20000.0); b["on"] = True
            if drag_st.get("b", c.eq_band): b["gain"] = round(clamp(18 - (py - py0) / float(py1 - py0) * 36, -15, 15), 1)
        self.hit((px0, py0, px1, py1), down=gdown, drag=gdrag)
        # OUTPUT: gain after the EQ, its marks on the graph's dB grid, and the strip's level beside it
        ox0, ox1 = gx1 + 7, x1 - 15
        self.glassbox((ox0, gy0, ox1, gy1), 5)
        self.lab((ox0 + ox1) / 2, gy0 + 9, "OUTPUT", 4.8, (200, 204, 212), "mm", "s", 0.14, floor=4.8)
        fx_c = ox0 + 12
        for g in (12, 6, 0, -6, -12):
            yy = fy_(g)
            self.lab(fx_c + 7, yy, f"{g:+d}" if g else "0", 3.6, ORANGE if g == 0 else (130, 126, 118), "lm", "s", 0.0, floor=3.6)
            d.line([fx_c - 6, yy, fx_c - 3, yy], fill=(110, 106, 98))
        d.rounded_rectangle([fx_c - 1.6, fy_(15), fx_c + 1.6, fy_(-15)], 1.6, fill=(6, 6, 7))
        cy_ = fy_(clamp(st.eq_gain, -15, 15))
        cap = skin.fader_cap(self.P(18), self.P(10))
        self.put(cap[0], fx_c - 9, cy_ - 5, cap[1], cap[2])
        def odrag(px, py):
            st.eq_gain = round(clamp(18 - (py - py0) / float(py1 - py0) * 36, -12.0, 12.0) * 2) / 2.0
        self.hit((ox0, py0, ox0 + 30, py1), down=odrag, drag=odrag)
        for ch in (0, 1):                                                  # a stereo LED meter, after the EQ and fader
            mx = ox1 - 10 + ch * 4
            lv = st.meter[ch]
            dbv = 20 * math.log10(max(1e-5, lv))
            for k in range(26):
                db_ = 12 - k * (42 / 25.0)
                yy = fy_(clamp(db_ + 6, -18, 18)) if False else py0 + (py1 - py0) * k / 25.0
                lit = dbv >= (6 - k * 2.4)
                colr = (235, 80, 70) if k < 3 else ((240, 210, 60) if k < 7 else (75, 224, 131))
                d.rectangle([mx, yy - 1.4, mx + 2.6, yy + 0.8], fill=colr if lit else (32, 36, 34))
        self.t((ox0 + ox1) / 2, gy1 - 9, f"{st.eq_gain:+.1f} dB".replace("+0.0", "0.0"), 10, True, (236, 236, 238), "mm")
        # the five band panels
        TYPE_NAME = {"HP": "HIGH-PASS", "LOW SHELF": "LOW SHELF", "BELL": "BELL", "HIGH SHELF": "HIGH SHELF"}
        pw = (x1 - x0 - 30 - 4 * 6) / 5.0
        for i, b in enumerate(st.eq):
            bx0 = x0 + 15 + i * (pw + 6); by0, by1 = y0 + 205, y1 - 11
            sel = i == c.eq_band
            d.rounded_rectangle([bx0, by0, bx0 + pw, by1], 4, fill=(20, 21, 24), outline=(72, 200, 96) if sel else (30, 31, 35), width=1.4 if sel else 1)
            on = b.get("on")
            self.ledp(bx0 + 8, by0 + 8, 4.5, on, BAND_COL[i])
            if i == 4 and not on:
                self.lab(bx0 + 15, by0 + 8, "BAND 5 OFF", 5.0, self.CON_DIM, "lm", "b", 0.12, floor=5.0)
            else:
                self.lab(bx0 + 15, by0 + 8, f"BAND {i + 1}", 5.0, (226, 226, 228), "lm", "b", 0.12, floor=5.0)
                self.lab(bx0 + 15, by0 + 15, TYPE_NAME.get(b["type"], b["type"]), 4.4, self.CON_DIM, "lm", "s", 0.1, floor=4.4)
                hz = lambda v: f"{v:.0f}" if v < 1000 else f"{v / 1000:.1f}k"
                if i == 0:
                    ks = [("FREQ", math.log(b["freq"] / 20.0) / math.log(1000.0), hz(b["freq"]),
                           lambda v, b=b: b.update(freq=20.0 * 1000.0 ** v, on=True)),
                          ("SLOPE", 1.0 if b.get("slope", 12) >= 24 else 0.0, f"{b.get('slope', 12)} dB/oct",
                           lambda v, b=b: b.update(slope=24 if v > 0.5 else 12, on=True))]
                else:
                    ks = [("FREQ", math.log(b["freq"] / 20.0) / math.log(1000.0), hz(b["freq"]), lambda v, b=b: b.update(freq=20.0 * 1000.0 ** v, on=True)),
                          ("GAIN", (b["gain"] + 15) / 30.0, f"{b['gain']:+.0f} dB", lambda v, b=b: b.update(gain=round(-15 + 30 * v, 1), on=True)),
                          ("Q", (b["q"] - 0.3) / 5.7, f"{b['q']:.1f}", lambda v, b=b: b.update(q=round(0.3 + 5.7 * v, 2), on=True))]
                n = len(ks)
                for j, (nm, fv, val, setter) in enumerate(ks):
                    kx = bx0 + pw * (j + 0.5) / n
                    self.con_knob(kx, by0 + 39, 15, fv, lambda fv=fv: fv, setter)
                    self.lab(kx, by0 + 53, nm, 4.4, self.CON_DIM, "mm", "s", 0.12, floor=4.4)
                    self.t(kx, by0 + 62, val, 9, True, (236, 236, 238), "mm")
            self.hit((bx0, by0, bx0 + pw, by0 + 20), down=lambda *_, i=i, b=b: b.update(on=not b.get("on")) if c.eq_band == i else setattr(c, "eq_band", i))
            self.hit((bx0, by0 + 20, bx0 + pw, by0 + 28), down=lambda *_, i=i: setattr(c, "eq_band", i))

    # ------------------------------------------------------------ FX
    def screen_fx(self):
        import fxpage
        fxpage.draw(self)

    # ------------------------------------------------------------ SONG
    def screen_song(self):
        import pages
        pages.song(self)


WARM_MODES = ["MAIN", "GRID", "SEQ", "STEP", "MUTE", "PROG", "SAMPLE", "CHOP", "MIXER", "FX", "SONG",
              "MENU", "EDIT", "PROJECTS", "BROWSE", "PADS", "EXPORT", "MIDI"]


def prewarm(eng, scale, machines=None, progress=None):
    """draw every page once for each machine, off screen, so all the skin's parts (keys, knobs, glass, LEDs in each machine's
    colour) are made now, behind the logo, and not the first time a page opens while a beat plays (that was a stutter).
    Uses its own Controls and Renderer: the real ones, and the project, are not touched."""
    from ui import Controls
    import engine as E
    c = Controls(eng); r = Renderer(c, scale)
    ms = list(machines or E.MACHINES)
    keep = eng.machine
    n, total = 0, len(ms) * len(WARM_MODES)
    try:
        for m in ms:
            eng.machine = m
            for md in WARM_MODES:
                try:
                    if md == "PROJECTS": c.mode = md                 # (set_mode would re-read the project list: not needed here)
                    else: c.set_mode(md)
                    r.frame()
                    if md == "FX": _warm_faceplates(r)
                    if md == "MIXER": c.eq_open = True; r.frame(); c.eq_open = False
                    if md == "MAIN": c.open_picker(); r.frame(); c.close_picker()
                except Exception as ex: print("prewarm", m, md, ex)
                n += 1
                if progress: progress(n / float(total))
    finally:
        eng.machine = keep


def _warm_faceplates(r):
    """draw every built-in effect's faceplate (and the valve case) once, with throw-away effects: the project is not touched"""
    import fx as fxlib, fxpage
    for name, draw in (("Delay", fxpage.tape_echo), ("Drive", fxpage.valve_drive), ("Filter", fxpage.filt), ("Crush", fxpage.crush),
                       ("Comp", fxpage.comp)):
        eff = fxlib.create("builtin", name)
        draw(r, eff)
        if name == "Drive":
            for v in (1, 2):
                r.c.valve_case, r.c.valve_pick = v, 0
                fxpage.valve_case(r, eff)
            r.c.valve_case = None
    r._hits = []
