"""uicore.py - shared constants, colours and helpers for the UI: 800 x 500 layout units, drawn 1.6x (1280 x 800) on the 10.1 inch panel."""
from PIL import Image, ImageDraw, ImageFont

W, H = 800, 500                  # 16:10, the 1280 x 800 panel's shape (1 unit = 1.6 pixels = 0.27 mm on it)
TOP_H = 36                       # tab bar
CONTENT = (0, 40, 800, 376)      # x0, y0, x1, y1 of the working area
SOFT_Y = (376, 413)              # soft key row (F1-F4): 37 high = 10 mm on the panel, 5 clear of the Q-link strip
Q_Y = 418                        # Q-link strip starts here: 82 high (22 mm), its slider bars are drag targets

BG, PANEL, PANEL2, LINE = (13, 14, 19), (28, 30, 42), (38, 41, 56), (62, 66, 84)
TEXT, DIM = (228, 231, 238), (125, 130, 146)
ORANGE, CYAN, GREEN = (255, 150, 30), (60, 200, 230), (80, 210, 110)
RED, YEL, BLUE = (235, 70, 70), (240, 210, 60), (70, 110, 230)
ROW_COLORS = [(70, 110, 230), (60, 190, 170), (230, 170, 50), (200, 90, 200)]   # pad rows, front to back
TRACK_COLORS = [(70, 110, 230), (60, 190, 170), (230, 170, 50), (200, 90, 200),
                (235, 100, 90), (120, 200, 90), (90, 160, 240), (240, 140, 180)]

TABS = ["MAIN", "GRID", "STEP", "MUTE", "PROG", "SAMPLE", "CHOP", "MIXER", "FX", "SONG", "MENU"]
# GRID is one page with two views: the current track's grid (mode "GRID", the default) and every track at once (mode "SEQ").
TAB_OF = {"SEQ": "GRID", "PROJECTS": "MENU", "BROWSE": "MENU", "EDIT": "MENU", "PADS": "MENU", "MIDI": "MENU",
          "EXPORT": "MENU", "SETTINGS": "MENU"}                   # the pages MENU leads to light its tab

# hardware button numbers, as sent by the Arduino ("B,<n>,<1|0>")
BTN = dict(REC=0, OVERDUB=1, STOP=2, PLAY=3, PLAYSTART=4,
           MAIN=5, GRID=6, MUTE=7, LOAD=8, PROG=9, SAMPLE=10, CHOP=11, MIXER=12, FX=13,
           SHIFT=14, ERASE=15, UNDO=16, TAP=17, BANK=18, REPEAT=19, F1=20, F2=21, F3=22, F4=23)
MODE_KEYS = {5: "MAIN", 6: "GRID", 7: "MUTE", 9: "PROG", 10: "SAMPLE", 11: "CHOP", 12: "MIXER", 13: "FX"}

_fonts = {}
def font(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        import os
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
        tries = [(here + "/", "Inter-SemiBold.otf" if bold else "Inter-Medium.otf"),          # Inter (bundled, SIL OFL)
                 ("/usr/share/fonts/opentype/inter/", "Inter-SemiBold.otf" if bold else "Inter-Medium.otf")]
        tries += [(b_, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf") for b_ in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/")]
        for base, name in tries:
            try:
                _fonts[key] = ImageFont.truetype(base + name, size); break
            except OSError:
                continue
        else:
            _fonts[key] = ImageFont.load_default()
        try: _fonts[key].ui_key = key                      # so ScaledDraw can load the same face at the screen's real size
        except AttributeError: pass
    return _fonts[key]


class ScaledDraw:
    """Stands in for ImageDraw.Draw: the screens keep drawing in 800 x 500 coordinates, this draws them s times bigger with
    fonts loaded at the real pixel size, so a 1280 x 800 panel gets sharp text instead of an upscaled, blurred picture.
    Boxes cover exactly the screen pixels their layout pixels cover, so neighbouring cells still tile without gaps."""
    def __init__(self, draw, s):
        self.dr, self.s = draw, float(s)

    def _box(self, xy):
        if len(xy) == 2: (x0, y0), (x1, y1) = xy
        else: x0, y0, x1, y1 = xy
        s = self.s
        return [round(x0 * s), round(y0 * s), max(round(x0 * s), round((x1 + 1) * s) - 1), max(round(y0 * s), round((y1 + 1) * s) - 1)]

    def _pts(self, xy, centre=False):
        o = (self.s - 1) / 2.0 if centre else 0.0
        if xy and isinstance(xy[0], (tuple, list)): return [(x * self.s + o, y * self.s + o) for x, y in xy]
        return [v * self.s + o for v in xy]

    def _w(self, kw):
        if "width" in kw: kw["width"] = max(1, int(round(kw["width"] * self.s)))
        return kw

    def _font(self, kw):
        f = kw.get("font")
        k = getattr(f, "ui_key", None)
        if k: kw["font"] = font(max(1, int(round(k[0] * self.s))), k[1])
        return kw

    def rectangle(self, xy, **kw): self.dr.rectangle(self._box(xy), **self._w(kw))
    def ellipse(self, xy, **kw): self.dr.ellipse(self._box(xy), **self._w(kw))

    def rounded_rectangle(self, xy, radius=0, **kw):
        self.dr.rounded_rectangle(self._box(xy), radius * self.s, **self._w(kw))

    def line(self, xy, **kw): self.dr.line(self._pts(list(xy), True), **self._w(kw))
    def polygon(self, xy, **kw): self.dr.polygon(self._pts(list(xy)), **self._w(kw))
    _tcache = {}                                            # (text, font, anchor) -> (mask, x offset, y offset)

    def text(self, xy, txt, **kw):
        """text is the slowest thing to draw (FreeType renders every glyph), so each label is rendered once and then
        stamped: on a Pi this roughly halves the time a frame takes"""
        kw = self._font(kw)
        f, fill, anchor = kw.get("font"), kw.get("fill"), kw.get("anchor") or "la"
        img = getattr(self.dr, "_image", None)
        if img is None or f is None or not isinstance(fill, tuple) or set(kw) - {"font", "fill", "anchor"} or "\n" in txt:
            self.dr.text((xy[0] * self.s, xy[1] * self.s), txt, **kw); return
        key = (txt, id(f), anchor)
        hit = self._tcache.get(key)
        if hit is None:
            x0, y0, x1, y1 = f.getbbox(txt, anchor=anchor)
            m = Image.new("L", (max(1, x1 - x0), max(1, y1 - y0)), 0)
            ImageDraw.Draw(m).text((-x0, -y0), txt, font=f, fill=255, anchor=anchor)
            if len(self._tcache) > 6000: self._tcache.clear()
            hit = self._tcache[key] = (m, x0, y0)
        m, ox, oy = hit
        img.paste(fill[:3], (int(round(xy[0] * self.s)) + ox, int(round(xy[1] * self.s)) + oy), m)
    def textlength(self, txt, **kw): return self.dr.textlength(txt, **self._font(kw)) / self.s


def mix(c1, c2, f):
    f = max(0.0, min(1.0, f))
    return tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))


def ink(fill):
    """readable text colour on a given background: dark on light fills, light on dark ones"""
    lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return (18, 19, 24) if lum > 150 else TEXT


def ink_dim(fill):
    lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return (60, 62, 72) if lum > 150 else (190, 194, 206)


MIN_TOUCH = 32                    # smallest touch target in layout units (8.7 mm on the 10.1 inch panel)


def level_color(v):
    return GREEN if v < 0.6 else (YEL if v < 0.9 else RED)


def clamp(v, a, b):
    return max(a, min(b, v))


# ---------------- soft-key (F1-F4) grammar: what a label looks like tells you what the key does ----------------
#   a plain string            an ACTION: a verb ("SAVE", "DELETE NOTE")
#   T(noun, on)               a TOGGLE: a light that is lit when on ("METRONOME")
#   C(name, value)            a SETTING that steps through values: its name small, the value below ("SNAP / 1/16")
#   P(name)                   goes to a PAGE: name and an arrow ("CHOP >")
#   HOT(verb)                 the page's main action, drawn lit ("DO IT", "OK")
#   BACK                      back to the page you came from: always F4
def T(noun, on): return ("T", noun, bool(on))
def C(name, value): return ("C", name, str(value))
def P(name): return ("P", name)
def HOT(verb): return ("H", verb)
BACK = ("B", "BACK")


def soft_text(lab):
    """a soft-key label as plain text (for tests and the MIDI page)"""
    if isinstance(lab, str): return lab
    k = lab[0]
    if k == "T": return lab[1]
    if k == "C": return f"{lab[1]} {lab[2]}"
    if k == "P": return lab[1] + " >"
    if k == "H": return lab[1]
    if k == "B": return "< BACK"
    return str(lab[0])                                       # old style (text, on)
