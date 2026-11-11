"""
progpanel.py - PROG's edit pages (GLOBAL / SAMPLES / ENVELOPES / LFO / MOD / EFFECTS) drawn as a panel, in the language of
the PROG front-panel artboard: every setting is the control it is, so what can be turned, switched, picked or read is
clear at a glance.

  knob     a continuous value (level, tune, cutoff, times): a machined knob with its arc, the value under it
  key      on / off (REVERSE, WARP, LO-FI ...): a key with its LED
  switch   a few choices (MODE, FILTER): a row of keys, the one in use pressed and lit
  window   a number or a name read off a display (START, END, BPM, SLICE, SAMPLE): a recessed amber window, like MAIN's
  action   a key that goes somewhere (EFFECT, MAKE TRANSWAVE)

SAMPLES is a wave view, as on an MPC: the waveform large, a ruler over it (bars and beats with WARP on, seconds without),
START / END flags to drag, and the warp controls together (WARP, SAMPLE BPM with x2 / /2 / AUTO, STRETCH).
The four Q-link knobs' settings carry a Q1-Q4 tag. Arrows, the wheel and taps work as before: the rows (prog_row) underneath
did not change, only how they are drawn.
"""
import math
from uicore import ORANGE, CYAN, GREEN, RED, YEL, TEXT, DIM, clamp
from engine import BANKS
import skin
from engine import OUT_SR, MODES

AMB, AMB_DIM, WIN_BG = (255, 176, 102), (150, 96, 50), (19, 11, 5)
LED_KEYS = {8, 9, 14, 45}                                 # + 12 (LO-FI) unless the pad is an SP-1200 sound
ACTIONS = {44: "OPEN FX", 55: "MAKE"}
SWITCH = {6: ("MODE", MODES), 18: ("FILTER", ["OFF", "LP", "HP", "BP"])}
SHORT = {0: "SAMPLE", 1: "START", 2: "END", 3: "SEMI", 4: "LEVEL", 5: "PAN", 7: "CHOKE", 8: "REVERSE", 9: "NORMALIZE",
         10: "FADE IN", 11: "FADE OUT", 13: "OUTPUT", 14: "WARP", 15: "SAMPLE BPM", 16: "ATTACK", 17: "DECAY", 19: "CUTOFF",
         20: "RESONANCE", 21: "FILTER ENV", 22: "FILTER DEC", 23: "VEL > CUT", 40: "SLICE", 41: "FINE", 42: "STRETCH",
         43: "GAIN", 44: "EFFECT", 45: "BYPASS", 52: "SOUND", 55: "TRANSWAVE", 82: "FILTER ATK"}


def _sq(v, hi): return math.sqrt(max(0.0, v) / float(hi))


def frac(e, row):
    """where a knob row sits, 0..1 (None: not a knob; shown in a window)"""
    p = e.pad
    f = {3: lambda: (p.tune + 24) / 48.0, 4: lambda: p.vol, 5: lambda: (p.pan + 1) / 2.0,
         10: lambda: p.fade_in / 500.0, 11: lambda: p.fade_out / 500.0, 16: lambda: _sq(p.attack, 2000),
         17: lambda: _sq(p.decay, 5000), 19: lambda: p.cutoff, 20: lambda: p.res, 21: lambda: (p.f_env + 1) / 2.0,
         22: lambda: _sq(p.f_dec - 10, 4990), 23: lambda: p.f_vel, 41: lambda: (p.fine + 99) / 198.0,
         42: lambda: math.log(p.stretch / 25.0) / math.log(16.0), 43: lambda: (p.gain_db + 12) / 24.0,
         53: lambda: e.sp_ring, 60: lambda: p.a_f1 / 150.0, 61: lambda: p.a_f2 / 150.0,
         62: lambda: (p.a_kbd1 + 127) / 254.0, 63: lambda: (p.a_kbd2 + 127) / 254.0, 74: lambda: p.a_softvel / 100.0,
         78: lambda: _sq(p.m_vatk, 2000), 79: lambda: p.m_vstart / 500.0, 80: lambda: (p.m_vpitch + 1200) / 2400.0,
         82: lambda: _sq(p.f_atk, 5000), 33: lambda: p.a_lfo_rate / 99.0, 34: lambda: p.a_lfo_depth / 127.0,
         35: lambda: p.a_lfo_delay / 99.0}.get(row)
    if f is None and 64 <= row <= 68: f = lambda: _sq(p.a_amp_t[row - 64], 20000)
    if f is None and 69 <= row <= 73: f = lambda: p.a_amp_l[row - 69] / 99.0
    if f is None and 46 <= row <= 51:
        fxp = e.get_fx(p)
        if fxp is None or row - 46 >= fxp.n(): return None
        f = lambda: fxp.get(row - 46)
    if f is None: return None
    try: return clamp(float(f()), 0.0, 1.0)
    except Exception: return None


CENTRED = {3, 5, 21, 41, 43, 62, 63, 80}


def kind(r, row):
    e = r.e
    if row in SWITCH: return "switch"
    if row in ACTIONS: return "action"
    if row in LED_KEYS or (row == 12 and e.sound_of(e.pad) != "SP-1200"): return "key"
    if frac(e, row) is not None: return "knob"
    return "window"


def qtags(r):
    """which rows the four Q-links turn on this page: row -> 1..4 (matched by name)"""
    c = r.c
    alias = {"PAD TUNE": 3, "TUNE": 3, "SEMI": 3, "START": 1, "END": 2, "FINE": 41, "STRETCH": 42, "SAMPLE BPM": 15,
             "LEVEL": 4, "PAN": 5, "GAIN": 43, "ATTACK": 16, "DECAY": 17, "CUTOFF": 19, "RESONANCE": 20}
    rows = c.PROG_TABS[c.prog_tab][1]
    out = {}
    try: q = c.qlinks()
    except Exception: return out
    for i, (label, *_rest) in enumerate(q[:4]):
        L = label.upper()
        row = alias.get(L)
        if row not in rows:
            row = next((rw for rw in rows if r.prog_label(rw).upper().startswith(L)), None)
        if row is not None and row in rows: out[row] = i + 1
    return out


# ------------------------------------------------------------------------------------------------------------- controls
def _label(r, x, y, txt, sel, w):
    r.lab(x, y, txt, 4.6, (255, 255, 255) if sel else (150, 156, 168), "mm", "s", 0.12, floor=4.2, maxw=w - 4)


def _qtag(r, x1, y0, n):
    r.d.rounded_rectangle([x1 - 15, y0 + 1, x1 - 2, y0 + 9], 2, fill=ORANGE)
    r.lab(x1 - 8.5, y0 + 5, f"Q{n}", 3.8, (20, 14, 8), "mm", "b", 0.0, floor=3.6)


def _hits(r, rect, row, tap=None):
    """the same touch behaviour the tiles had: tap selects (toggles flip, SAMPLE opens the picker), drag left / right turns"""
    c = r.c
    state = {}

    def down(px, py):
        c.prog_row = row; state["x"] = px
        if tap is not None: tap(); return
        if row == 0: c.ok()
        elif row in c.PROG_TOGGLES: c.prog_adjust(row, 1)

    def drag(px, py):
        if tap is not None or row == 0 or row in c.PROG_TOGGLES: return
        step = int((px - state["x"]) / 6)
        if step: c.prog_adjust(row, step); state["x"] = px
    r.hit(rect, down=down, drag=drag)


def control(r, rect, row, qn=None, value=None):
    """one setting, drawn as what it is, in rect (layout units)"""
    c, e, d = r.c, r.e, r.d
    x0, y0, x1, y1 = rect
    w, cx = x1 - x0, (x0 + x1) / 2.0
    sel = row == c.prog_row
    k = kind(r, row)
    name = SHORT.get(row, r.prog_label(row)).upper()
    if row == 12: name = r.prog_label(row).upper().replace(" (SP FLAVOR)", "")
    if sel: d.rounded_rectangle([x0 + 1, y0 + 1, x1 - 1, y1 - 1], 6, fill=(40, 34, 30), outline=ORANGE, width=1)
    if qn and k != "knob": _qtag(r, x1, y0, qn)
    val = value if value is not None else (f"{e.pad.stretch}%" if row == 42 else r.prog_value(row))
    if k == "key":                                                    # on / off: a key with its LED
        on = {8: lambda: e.pad.reverse, 9: lambda: e.pad.norm, 14: lambda: e.pad.warp, 12: lambda: e.pad.lofi_on,
              45: lambda: e.get_fx(e.pad) is not None and e.get_bypass(e.pad)}[row]()
        kh = min(26, (y1 - y0) - 18)
        ky = (y0 + y1) / 2.0 - kh / 2 + 4
        r.keycap((x0 + 6, ky, x1 - 6, ky + kh), "lit" if on else "up", 5, CYAN if row == 14 else None)
        r.ledp(x0 + 14, ky + kh / 2, 3.6, on, CYAN if row == 14 else None)
        r.lab(cx + 5, ky + kh / 2, name, 4.8, (244, 246, 249) if on else (170, 176, 188), "mm", "s", 0.1, floor=4.2, maxw=w - 26)
        _hits(r, rect, row)
        return
    _label(r, cx, y0 + 7, name, sel, w if (not qn or k == "knob") else w - 26)
    if k == "knob":
        f = frac(e, row)
        kd = r.P(min(34, (y1 - y0) - 30, w - 16))
        sp, off = skin.knob(kd, f, ORANGE if sel else (210, 130, 50), row in CENTRED)
        ky = y0 + 13 + (y1 - y0 - 30) / 2.0
        r.img.paste(sp, (r.P(cx) - kd // 2 - off, r.P(ky) - kd // 2 - off), sp)
        if qn: _qtag(r, min(x1, cx + kd / r.scale / 2 + 15), ky - kd / r.scale / 2 - 2, qn)
        _fit_text(r, cx, y1 - 8, val, w - 6, sel)
        _hits(r, rect, row)
    elif k == "switch":
        title, opts = SWITCH[row]
        cur = e.pad.mode if row == 6 else e.pad.flt
        n = len(opts)
        bw = (w - 10) / n
        by0, by1 = y0 + 16, min(y1 - 6, y0 + 40)
        for i, o in enumerate(opts):
            bx = x0 + 5 + i * bw
            on = o == cur
            r.keycap((bx + 1, by0, bx + bw - 1, by1), "down" if on else "up", 4)
            lbl = o
            r.lab(bx + bw / 2, (by0 + by1) / 2, lbl, 4.4, ORANGE if on else (165, 171, 183), "mm", "s", 0.06, floor=3.8, maxw=bw - 4)

            def pick(o=o, row=row):
                c.prog_row = row
                if row == 6: e.pad.mode = o
                else:
                    e.pad.flt = o
                    if o == "LP" and e.pad.cutoff >= 0.99: e.pad.cutoff = 0.7
                e.pad_changed(e.pad)
            r.hit((bx, by0 - 2, bx + bw, by1 + 2), down=lambda *_, pick=pick: pick())
    elif k == "action":
        kh = 22
        ky = y0 + 16
        r.keycap((x0 + 8, ky, x1 - 8, ky + kh), "up", 5, CYAN)
        r.lab(cx, ky + kh / 2, ACTIONS[row], 4.6, CYAN, "mm", "s", 0.1, floor=4.0, maxw=w - 20)
        if row == 44 and e.get_fx(e.pad) is not None and y1 - (ky + kh) > 12: _fit_text(r, cx, y1 - 8, val, w - 6, sel)
        _hits(r, rect, row)
    else:                                                             # a display window
        window(r, (x0 + 5, y0 + 14, x1 - 5, min(y1 - 4, y0 + 14 + 26)), val, sel)
        _hits(r, rect, row)


def window(r, rect, txt, sel=False, col=None):
    """a recessed amber display window (the MAIN display's look) with a value in it"""
    x0, y0, x1, y1 = rect
    r.d.rounded_rectangle([x0, y0, x1, y1], 4, fill=(8, 8, 9))
    r.d.rounded_rectangle([x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5], 3, fill=WIN_BG, outline=ORANGE if sel else (60, 40, 22))
    r.vt((x0 + x1) / 2.0, (y0 + y1) / 2.0, str(txt).upper(), 11.5, col or AMB, "mm", maxw=(x1 - x0) - 8)


def _fit_text(r, cx, y, txt, w, sel):
    txt = str(txt)
    size = 10
    while size > 9 and r.d.textlength(txt, font=_font(size)) > w: size -= 1
    while len(txt) > 3 and r.d.textlength(txt, font=_font(size)) > w: txt = txt[:-2] + "…"
    r.t(cx, y, txt, size, True, (246, 247, 250) if sel else (205, 210, 220), "mm")


def _font(size):
    from screens import font
    return font(size, True)


def section(r, rect, title):
    """a panel section: an engraved heading over a sunken plate"""
    x0, y0, x1, y1 = rect
    if title: r.lab(x0 + 4, y0 + 3, title, 4.4, (200, 120, 50), "lm", "s", 0.16, floor=4.0)
    r.well((x0, y0 + 8, x1, y1), 6, (21, 22, 26), 5)


def grid(r, rect, rows, ncol=None, qt=None):
    """rows laid out in a grid of cells inside rect"""
    x0, y0, x1, y1 = rect
    n = len(rows)
    if not n: return
    ncol = ncol or (4 if n <= 8 else (4 if n <= 12 else 5))
    nr = (n + ncol - 1) // ncol
    cw, ch = (x1 - x0) / float(ncol), min(74.0, (y1 - y0) / float(nr))   # cells keep a knob's proportions
    for i, row in enumerate(rows):
        cx0, cy0 = x0 + (i % ncol) * cw, y0 + (i // ncol) * ch
        control(r, (cx0 + 1, cy0 + 1, cx0 + cw - 1, cy0 + ch - 1), row, (qt or {}).get(row))


# ------------------------------------------------------------------------------------------------------------- pages
def wave_view(r, rect, big):
    """the pad's sample: the region lit, START / END flags, chop marks, and a ruler (beats with WARP, else seconds)"""
    c, e, d = r.c, r.e, r.d
    p = e.pad
    src = p.src
    x0, y0, x1, y1 = rect
    ruler = 11 if big else 0
    wrect = (x0, y0 + ruler, x1, y1)
    a, b = c.prog_view()
    r.waveform(wrect, src, a, b, region=(p.start, p.end) if src else None, play=e.playhead(p))
    W = wrect[2] - wrect[0] - 2
    X = lambda pos: wrect[0] + 1 + (pos - a) / float(max(1, b - a)) * W
    if src is None:
        r.lab((x0 + x1) / 2, (y0 + y1) / 2, "NO SAMPLE - TAP SAMPLE BELOW TO PICK ONE", 5.2, (130, 136, 148), "mm", "s", 0.12)
        return
    if big:                                                           # the ruler
        d.rectangle([x0, y0, x1, y0 + ruler - 1], fill=(28, 30, 35))
        if p.warp and p.warp_bpm:
            beat = 60.0 / p.warp_bpm * OUT_SR
            k0 = int(math.floor((a - p.start) / beat)); k1 = int(math.ceil((b - p.start) / beat))
            step = max(1, int((k1 - k0) / 24) or 1)
            for k in range(k0, k1 + 1):
                pos = p.start + k * beat
                if not (a <= pos <= b) or k < 0: continue
                bar_ = k % 4 == 0
                xx = X(pos)
                d.line([xx, y0 + (2 if bar_ else 6), xx, y0 + ruler - 1], fill=CYAN if bar_ else (90, 120, 140))
                if bar_ or step == 1:
                    if bar_ or (k1 - k0) <= 16:
                        r.lab(xx + 2, y0 + 4.5, f"{k // 4 + 1}.{k % 4 + 1}", 3.6, CYAN if bar_ else (110, 140, 160), "lm", "s", 0.0, floor=3.4)
                d.line([xx, wrect[1], xx, wrect[3]], fill=(46, 70, 84) if bar_ else (34, 46, 56))
        else:
            span = (b - a) / float(OUT_SR)
            st = next(s for s in (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30) if span / s <= 10)
            t = math.ceil(a / OUT_SR / st) * st
            while t * OUT_SR <= b:
                xx = X(t * OUT_SR)
                d.line([xx, y0 + 5, xx, y0 + ruler - 1], fill=(110, 116, 128))
                r.lab(xx + 2, y0 + 4.5, f"{t:.2f}".rstrip("0").rstrip(".") + "s", 3.6, (120, 126, 138), "lm", "s", 0.0, floor=3.4)
                t += st
    for cpos in src.chops:
        if a <= cpos <= b: d.line([X(cpos), wrect[1] + 1, X(cpos), wrect[1] + 8], fill=DIM, width=1)
    if e.sound_of(p) == "ASR-10" and e.asr_loops(p):
        le_ = p.start + (p.a_le if p.a_le > 0 else p.length / OUT_SR) * OUT_SR
        for xs in (p.start + p.a_ls * OUT_SR, le_):
            if a <= xs <= b: d.line([X(xs), wrect[1] + 1, X(xs), wrect[3] - 1], fill=YEL, width=2)
    for xs, col, lb in ((p.start, GREEN, "S"), (p.end, RED, "E")):     # START / END flags (drag them)
        if a <= xs <= b:
            xx = X(xs)
            d.line([xx, wrect[1], xx, wrect[3] - 1], fill=col, width=2)
            fx = xx if lb == "S" else xx - 10
            d.rectangle([fx, wrect[1], fx + 10, wrect[1] + 9], fill=col)
            r.lab(fx + 5, wrect[1] + 4.5, lb, 3.8, (12, 12, 14), "mm", "b", 0.0, floor=3.6)
    linked = p.link is not None and p.link[0] == src.id
    info = f"{p.length / OUT_SR:.3f} s" + (f"   SLICE {p.link[1] + 1}/{e.slice_count(p)}" if linked else "")
    if p.warp and p.warp_bpm: info += f"   {p.length / OUT_SR * p.warp_bpm / 60.0:.2f} BEATS"
    r.lab(wrect[2] - 4, wrect[3] - 6, info, 4.2, (170, 176, 188), "rm", "s", 0.08, floor=3.8)

    def snap(f):
        if not c.pw_snap: return f
        import numpy as np
        w_ = src.raw[max(0, f - 256):f + 256]
        if w_.ndim > 1: w_ = w_[:, 0]
        zc = np.flatnonzero((w_[:-1] <= 0) & (w_[1:] > 0)) + max(0, f - 256)
        return int(zc[np.argmin(np.abs(zc - f))]) if len(zc) else f

    def wdown(px, py):
        f = a + (px - wrect[0]) / float(W) * (b - a)
        c.prog_row = 1 if abs(f - p.start) <= abs(f - p.end) else 2
        c._pw_msg = None

    def wdrag(px, py):
        f = snap(int(a + clamp((px - wrect[0]) / float(W), 0, 1) * (b - a)))
        r_ = e.set_region(p, start=f) if c.prog_row == 1 else e.set_region(p, end=f)
        if r_ and getattr(c, "_pw_msg", None) != r_: c._pw_msg = r_; c.say(r_)
    r.hit(wrect, down=wdown, drag=wdrag)


def env_view(r, rect):
    """ENVELOPES: the amp envelope (attack, decay) and the filter's (attack, decay, amount) as curves"""
    c, e, d = r.c, r.e, r.d
    p = e.pad
    x0, y0, x1, y1 = rect
    r.glassbox(rect, 6)
    tot = max(0.4, (p.attack + p.decay) / 1000.0 * 1.15, (p.f_atk + p.f_dec) / 1000.0 * 1.15)
    w, h = x1 - x0 - 20, y1 - y0 - 22
    X = lambda t: x0 + 10 + t / tot * w
    Y = lambda v: y1 - 8 - v * h

    def curve(att, dec, lvl, col):
        pts, n = [], 60
        a_ = att / 1000.0; dd = max(0.005, dec / 1000.0) if dec else tot
        for k in range(n + 1):
            t = k / n * tot
            v = (t / a_ if a_ > 0 and t < a_ else math.exp(-(t - a_) / (dd / 4.0)) if dec else 1.0)
            pts.append((X(t), Y(clamp(v, 0, 1) * lvl)))
        d.line(pts, fill=col, width=2)
    if p.flt != "OFF" and abs(p.f_env) > 0.01: curve(p.f_atk, p.f_dec, abs(p.f_env), CYAN)
    curve(p.attack, p.decay, 1.0, ORANGE)
    r.lab(x0 + 10, y0 + 8, "AMP", 4.4, ORANGE, "lm", "s", 0.14)
    if p.flt != "OFF": r.lab(x0 + 34, y0 + 8, f"FILTER {p.flt}", 4.4, CYAN, "lm", "s", 0.14)
    r.lab(x1 - 8, y0 + 8, f"{tot:.2f} S", 4.0, (140, 146, 158), "rm", "s", 0.1)


def warp_block(r, rect, qt):
    """WARP, SAMPLE BPM (x2 / /2 / AUTO) and STRETCH together"""
    c, e = r.c, r.e
    p = e.pad
    x0, y0, x1, y1 = rect
    w = x1 - x0
    control(r, (x0, y0, x0 + w * 0.27, y1), 14, qt.get(14))
    bx0, bx1 = x0 + w * 0.27, x0 + w * 0.70
    sel = c.prog_row == 15
    if sel: r.d.rounded_rectangle([bx0 + 1, y0 + 1, bx1 - 1, y1 - 1], 6, fill=(40, 34, 30), outline=ORANGE, width=1)
    if qt.get(15): _qtag(r, bx1, y0, qt[15])
    _label(r, (bx0 + bx1) / 2, y0 + 7, "SAMPLE BPM", sel, bx1 - bx0 - 26)
    bpm = p.warp_bpm or (e.guess_bpm(p) if p.src else 0)
    window(r, (bx0 + 5, y0 + 14, bx1 - 5, y0 + 38), f"{bpm:.1f}" if p.src else "-", sel, AMB if p.warp else AMB_DIM)
    _hits(r, (bx0, y0, bx1, y0 + 40), 15)
    kw = (bx1 - bx0 - 10) / 3.0

    def setb(fn):
        if p.src is None: return
        c.prog_row = 15
        p.warp_bpm = clamp(round(fn(p.warp_bpm or e.guess_bpm(p)), 2), 30.0, 300.0)
        if p.warp: e.set_warp(p, True)
        e.pad_changed(p); c.say(f"sample BPM {p.warp_bpm:.1f}")
    for i, (lb, fn) in enumerate((("x2", lambda v: v * 2), ("/2", lambda v: v / 2), ("AUTO", lambda v: e.guess_bpm(p)))):
        kx = bx0 + 5 + i * kw
        ky0, ky1 = y0 + 41, min(y1 - 3, y0 + 57)
        r.keycap((kx + 1, ky0, kx + kw - 1, ky1), "up", 4)
        r.lab(kx + kw / 2, (ky0 + ky1) / 2, lb, 4.2, (200, 205, 215), "mm", "s", 0.06, floor=3.8)
        r.hit((kx, ky0 - 2, kx + kw, ky1 + 2), down=lambda *_, fn=fn: setb(fn))
    control(r, (bx1, y0, x1, y1), 42, qt.get(42))


def samples_page(r, x0, y_top, x1, y_bot):
    """PROG > SAMPLES as a wave view"""
    qt = qtags(r)
    wave_view(r, (x0, y_top, x1, y_top + 120), True)
    r.btn((x1 - 78, y_top + 13, x1 - 42, y_top + 29), "ZOOM", lambda: setattr(r.c, "pw_zoom", not r.c.pw_zoom), 8, on=r.c.pw_zoom)
    r.btn((x1 - 39, y_top + 13, x1 - 3, y_top + 29), "SNAP", lambda: setattr(r.c, "pw_snap", not r.c.pw_snap), 8, on=r.c.pw_snap)
    ya, yb, yc = y_top + 127, y_top + 127 + (y_bot - y_top - 127) / 2.0, y_bot
    w = x1 - x0
    # line 1: what plays - the sample, its slice, the region, and REVERSE
    control(r, (x0, ya, x0 + w * 0.34, yb), 0, qt.get(0), (r.e.pad.src.name if r.e.pad.src else "- empty -"))
    for i, row in enumerate((40, 1, 2)):
        xa = x0 + w * 0.34 + i * w * 0.17
        control(r, (xa, ya, xa + w * 0.17, yb), row, qt.get(row))
    control(r, (x0 + w * 0.85, ya, x1, yb), 8, qt.get(8))
    # line 2: pitch and fades | the warp block
    for i, row in enumerate((3, 41, 10, 11)):
        xa = x0 + i * w * 0.11
        control(r, (xa, yb, xa + w * 0.11, yc), row, qt.get(row))
    warp_block(r, (x0 + w * 0.44, yb, x1, yc), qt)


def page(r, x0, y0, x1, y1):
    """the edit page under the tabs"""
    c, e = r.c, r.e
    name = c.prog_tab_name()
    rows = c.PROG_TABS[c.prog_tab][1]
    qt = qtags(r)
    if name == "SAMPLES": return samples_page(r, x0, y0, x1, y1)
    if name == "ENVELOPES" and e.sound_of(e.prog) != "ASR-10":
        env_view(r, (x0, y0, x1, y0 + 74))
        xm = x0 + (x1 - x0) * 0.27
        section(r, (x0, y0 + 80, xm - 3, y1), "AMP")
        section(r, (xm + 3, y0 + 80, x1, y1), "FILTER")
        amp = [rw for rw in rows if rw in (16, 17)]
        flt = [rw for rw in rows if rw not in (16, 17)]
        grid(r, (x0 + 2, y0 + 90, xm - 5, y1 - 2), amp, 1 if len(amp) > 1 and False else 2, qt)
        grid(r, (xm + 5, y0 + 90, x1 - 2, y1 - 2), flt, 4, qt)
        return
    if name == "ENVELOPES":                                           # ASR-10: its own five-stage envelope, drawn
        r.asr_env_graph(x0, y0, x1, y0 + 66, e.pad)
        grid(r, (x0, y0 + 70, x1, y1), rows, 5, qt)
        return
    if name == "GLOBAL":
        pad_rows, mrows = rows[:6], rows[6:]
        ya = y0 + 2
        yb = ya + 8 + 74 + 4
        section(r, (x0, ya, x1, yb), f"PAD {BANKS[e.bank]}{e.sel + 1:02d}")
        grid(r, (x0 + 2, ya + 10, x1 - 2, yb - 2), pad_rows, 6, qt)
        if mrows:
            snd = e.sound_of(e.prog)
            head = f"{snd} SOUND - " + ("THIS PROGRAM ONLY" if e.prog.sound else "FROM THE MACHINE")
            ncol = 6 if len(mrows) > 4 else 4
            nr = (len(mrows) + ncol - 1) // ncol
            yc = min(y1, yb + 6 + 8 + nr * 74 + 4)
            section(r, (x0, yb + 6, x1, yc), head)
            npg = len(c.machine_pages())
            if npg > 1:
                def nextpg():
                    c.mach_page = (c.mach_page + 1) % npg
                    if c.prog_row not in c.machine_rows() and c.prog_row not in (4, 5, 43, 6, 7, 13): c.prog_row = c.machine_rows()[0]
                r.btn((x1 - 52, yb + 4, x1 - 2, yb + 16), f"{c.mach_page + 1}/{npg}  >", nextpg, 8)
            grid(r, (x0 + 2, yb + 16, x1 - 2, yc - 2), mrows, ncol, qt)
        return
    if name == "EFFECTS":
        fxp = e.get_fx(e.pad)
        if fxp is None:
            grid(r, (x0, y0 + 4, x1, y0 + 78), [rw for rw in rows if rw == 44], 4, qt)
            r.lab((x0 + x1) / 2, y0 + 120, "NO EFFECT ON THIS PAD", 5.6, (150, 156, 168), "mm", "s", 0.14)
            r.lab((x0 + x1) / 2, y0 + 134, "OPEN FX TO INSERT ONE (TAPE ECHO, DRIVE, FILTER, CRUSH, COMP)", 4.4, (110, 116, 128), "mm", "s", 0.1)
            return
        rows = [rw for rw in rows if not (46 <= rw <= 51) or rw - 46 < fxp.n()]
    grid(r, (x0, y0 + 4, x1, y1), rows, None, qt)
