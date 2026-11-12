"""fxpage.py - the FX page: the insert chain bar and a hardware faceplate for each effect (the Fx* design artboards).

  chain bar   PAD -> INSERT 1-4 -> MASTER (or, for the console's returns: RTN A1 A2 B1 B2 -> MASTER 1 2)
  faceplates  TAPE ECHO (Delay), VALVE DRIVE (Drive, with the valve case), FILTER, CRUSH, BUS COMP; a plain faceplate with
              knobs for every other effect (ASR-10, VST3); the effect library when the slot is empty or BROWSE is pressed.

Every function takes the Renderer (screens.py) as r and draws in its 800 x 500 layout units."""
import math, time
import numpy as np
import skin
from uicore import clamp, mix, font, GREEN, YEL, RED

FACE = (10, 103, 793, 366)
INK, INK2, AMBER = (232, 230, 224), (138, 136, 130), (255, 150, 60)
TITLES = {"Delay": ("TAPE ECHO", "TAPE LOOP, RECORD HEAD, THREE PLAYBACK HEADS"),
          "Drive": ("VALVE DRIVE", "TWO-STAGE VALVE PREAMP"),
          "Filter": ("FILTER", "CUTOFF, MODE, MIX, RESONANCE"),
          "Crush": ("CRUSH", "RATE, BITS, MIX"),
          "Comp": ("BUS COMP", "THRESHOLD, RATIO, ATTACK, RELEASE, MAKEUP")}


def accent(r): return skin.ACCENTS.get(r.e.machine, skin.ACCENTS["MODERN"])


# ---------------------------------------------------------------- shared parts
def lab(r, x, y, txt, size=5.2, col=INK2, anchor="lm", w="s", sp=0.14):
    r.lab(x, y, txt, size, col, anchor, w, sp, floor=size)


def screw_title(r, eff, style):
    x0, y0, x1, y1 = FACE
    sp = skin.faceplate(r.P(x1 - x0), r.P(y1 - y0), style)
    r.img.paste(sp, (r.P(x0), r.P(y0)), sp)
    title, sub = TITLES.get(eff.name, (eff.name.upper(), ""))
    if eff.kind == "asr10": sub = "ENSONIQ ASR-10 EFFECT (FROM YOUR ROM)"
    elif eff.kind == "vst3": sub = "VST3 PLUG-IN  -  PLUG-IN WINDOW ON F3"
    ink = (30, 30, 34) if style == "alu" else INK
    lab(r, 32.5, 116, title, 8.2, ink, "lm", "b", 0.24)
    where = r.c.fx_target_name(short=True).upper()
    kind = "BUILT-IN " + eff.name.upper() if eff.kind == "builtin" else ""
    lab(r, 32.5, 127.5, "   ".join(t for t in (kind, where, sub) if t), 4.6, (90, 92, 98) if style == "alu" else (120, 120, 116), "lm", "s", 0.12)
    if r.e.get_bypass(r.c.fx_tgt()):
        r.d.rounded_rectangle([700, 110, 770, 122], 2, outline=YEL, width=1)
        lab(r, 735, 116, "BYPASSED", 5.0, YEL, "mm", "b", 0.12)


def knob(r, cx, cy, dia, get, setter, kind="b"):
    """a faceplate knob: drag up / down"""
    if kind == "c": sp, pad = skin.chrome_knob(r.P(dia), get())
    else: sp, pad = skin.bknob(r.P(dia), get(), kind == "b")
    kd = r.P(dia)
    r.img.paste(sp, (r.P(cx) - kd // 2 - pad, r.P(cy) - kd // 2 - pad), sp)
    st = {}
    def down(px, py): st["y"], st["v"] = py, get()
    def drag(px, py): setter(clamp(st["v"] + (st["y"] - py) / 80.0, 0.0, 1.0))
    r.hit((cx - dia / 2 - 6, cy - dia / 2 - 6, cx + dia / 2 + 6, cy + dia / 2 + 6), down=down, drag=drag)


def pknob(r, eff, i, cx, cy, dia, name, lo="", hi="", ink=INK, valcol=None):
    """a knob for parameter i, its name and value to the right, its range under it"""
    knob(r, cx, cy, dia, lambda: eff.get(i), lambda v: eff.set(i, v))
    if lo: lab(r, cx - dia * 0.55, cy + dia * 0.78, lo, 3.9, (120, 120, 118), "mm", "s", 0.06)
    if hi: lab(r, cx + dia * 0.55, cy + dia * 0.78, hi, 3.9, (120, 120, 118), "mm", "s", 0.06)
    if name:
        lab(r, cx + dia / 2 + 12, cy - 6, name, 5.6, ink, "lm", "s", 0.16)
        r.t(cx + dia / 2 + 12, cy + 7, eff.fmt(i), 11, True, valcol or accent(r), "lm")


def bottom_bar(r, y0, y1):
    r.d.rounded_rectangle([20, y0, 782.5, y1], 3, fill=(17, 17, 19), outline=(52, 52, 56), width=1)


def amber_box(r, rect, lines, sizes):
    """an amber gas-discharge display"""
    x0, y0, x1, y1 = rect
    r.d.rounded_rectangle([x0, y0, x1, y1], 3, fill=(26, 15, 7), outline=(60, 40, 22), width=1)
    r.d.rectangle([x0 + 2, y0 + 2, x1 - 2, y0 + (y1 - y0) * 0.45], fill=(30, 18, 9))
    y = y0 + 6
    for txt, sz in zip(lines, sizes):
        y += sz * 0.62
        r.mono(x0 + 9, y, txt, sz, (255, 168, 80) if sz > 12 else (238, 140, 60), "lm")
        y += sz * 0.62 + 2


VU_NUMS = None


def vu_frac(db): return clamp((10 ** (db / 20.0) - 0.1) / (10 ** (3 / 20.0) - 0.1), 0.0, 1.0)


def vu(r, rect, level, key, label="VU", gr=None, cream=True):
    """a big VU meter: level = linear peak (or gr = dB of gain reduction for the comp's GR meter)"""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if gr is None:
        nums = [(vu_frac(-db), str(db), db <= 0 and False) for db in (20, 10, 7, 5, 3)] + \
               [(vu_frac(d), str(abs(d)), d > 0) for d in (-1, 0, 1, 2, 3)]
        frac = vu_frac(20 * math.log10(max(level, 1e-6)) + 3.0) if level > 1e-5 else 0.0
    else:
        law = lambda g: 1.0 - (g / 20.0) ** 0.55
        nums = [(law(g), str(g), False) for g in (20, 10, 7, 5, 3, 1, 0)]
        frac = law(clamp(gr, 0.0, 20.0))
    sq = lambda f: 0.08 + 0.84 * f                                     # keep the scale clear of the face's edges
    nums = [(sq(f), t, red) for f, t, red in nums]; frac = sq(frac)
    r.d.rounded_rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], 4, fill=(26, 26, 28), outline=(70, 70, 74), width=1)
    face = skin.vu_face(r.P(w), r.P(h), label, nums, cream)
    r.img.paste(face, (r.P(x0), r.P(y0)), face)
    if not hasattr(r, "_vu"): r._vu, r._eqc = {}, {}
    sm = r._vu.get(key, frac); sm += (frac - sm) * (0.35 if (frac > sm) != (gr is not None) else 0.12); r._vu[key] = sm
    (ax, ay), (bx, by) = skin.vu_needle(w, h, sm)
    r.d.line([x0 + ax, y0 + ay, x0 + bx, y0 + by], fill=(28, 22, 16), width=1.3)


def vfader(r, rect, get, setter, label="MIX", top=None):
    """the tall MIX fader in its own well (filter / crush) - or the comp's MAKEUP"""
    x0, y0, x1, y1 = rect
    acc = accent(r)
    r.d.rounded_rectangle([x0, y0, x1, y1], 4, fill=(18, 18, 20), outline=(46, 46, 50), width=1)
    cx = (x0 + x1) / 2
    lab(r, cx, y0 + 12, top if top is not None else f"{get() * 100:.0f}%", 6.0, INK, "mm", "b", 0.04)
    ty0, ty1 = y0 + 28, y1 - 26
    for k in range(11):
        yy = ty0 + (ty1 - ty0) * k / 10
        r.d.line([cx - 11, yy, cx - 7, yy], fill=(110, 110, 112))
    r.d.rounded_rectangle([cx - 2, ty0, cx + 2, ty1], 2, fill=(8, 8, 9))
    fy = ty1 - (ty1 - ty0) * get()
    r.d.rounded_rectangle([cx - 1.4, fy, cx + 1.4, ty1], 1.4, fill=acc)
    cap = skin.fader_cap(r.P(20), r.P(11))
    r.put(cap[0], cx - 10, fy - 5.5, cap[1], cap[2])
    lab(r, cx, y1 - 14, label, 5.0, INK2, "mm", "s", 0.14)
    f = lambda py: setter(clamp((ty1 - py) / float(ty1 - ty0), 0.0, 1.0))
    r.hit((x0, y0, x1, y1), down=lambda px, py: f(py), drag=lambda px, py: f(py))


# ---------------------------------------------------------------- the chain bar
def chain_bar(r):
    c, e, d = r.c, r.e, r.d
    acc = accent(r)
    r.well((10, 49, 796, 92), 7, (20, 22, 26), 6)
    chain = c.fx_chain()
    for k, (t, label) in enumerate(chain):
        x0 = 16 + k * 121.5; x1 = x0 + 105.5
        if k:                                                            # the patch link between slots
            d.line([x0 - 16, 71, x0, 71], fill=(70, 72, 78), width=2)
            d.rounded_rectangle([x0 - 10.5, 67.5, x0 - 6.5, 74.5], 1, fill=(150, 152, 158))
        sel = t == c.fx_target
        r.keycap((x0, 55, x1, 87), "up", 5)
        if sel: d.rounded_rectangle([x0, 55, x1, 87], 5, outline=acc, width=1)
        tg = _target(c, t)
        eff, byp = e.get_fx(tg), e.get_bypass(tg)
        lab(r, x0 + 7, 62.5, label, 4.4, acc if sel else (128, 132, 142), "lm", "s", 0.12)
        if t < 64:
            pad = e.prog.pads[t]
            nm = eff.name if eff is not None else (f"{pad.src.name[:10]} (pad)" if pad.src is not None else "empty pad")
        else: nm = eff.name if eff is not None else "empty"
        r.t(x0 + 7, 75, nm[:16], 10.5, True, (240, 242, 246) if eff is not None or t < 64 else (110, 114, 124), "lm")
        if eff is not None or t >= 64: r.ledp(x1 - 10, 63, 3.2, eff is not None, YEL if byp else GREEN)
        r.hit((x0, 52, x1, 90), down=lambda *_, t=t: c.fx_set_target(t) if c.fx_target != t else setattr(c, "fx_browse", not c.fx_browse))
    # the audio load, in its own little window at the end of the chain
    r.glassbox((744, 56, 791, 86), 5)
    lab(r, 767.5, 64, "CPU", 4.0, (120, 124, 134), "mm", "s", 0.14)
    cpu = min(e.cpu, 9.99) * 100
    r.vt(767.5, 76, f"{cpu:.0f}%", 11.5, (255, 170, 60) if cpu > 70 else (233, 245, 236), "mm")


def _target(c, t):
    from engine import FxSlot
    if t == 64: return "master"
    if t == 73: return FxSlot(c.e.master_strip, 0)
    if t >= 69: return FxSlot(c.e.returns[(t - 69) // 2], (t - 69) % 2)
    if t >= 65: return FxSlot(c.e.prog, t - 65)
    return c.e.prog.pads[t]


# ---------------------------------------------------------------- the page
def draw(r):
    c, e = r.c, r.e
    chain_bar(r)
    eff = e.get_fx(c.fx_tgt())
    if eff is None or c.fx_browse: return browse(r, eff)
    f = {"Delay": tape_echo, "Drive": valve_drive, "Filter": filt, "Crush": crush, "Comp": comp}.get(eff.name) if eff.kind == "builtin" else None
    (f or generic)(r, eff)
    if c.valve_case and eff.name == "Drive": valve_case(r, eff)


# ---------------------------------------------------------------- the library
def browse(r, eff):
    c, d, e = r.c, r.d, r.e
    acc = accent(r)
    x0, y0, x1, y1 = FACE
    r.well((x0, y0, 560, y1), 8, (20, 22, 26), 7)
    items, cur = c.fx_items, c.fx_cursor
    rows = 8
    top = max(0, min(cur - 3, len(items) - rows))
    loaded = None if eff is None else eff.ident
    for k in range(rows):
        i = top + k
        if i >= len(items): break
        kind, ident, name = items[i]
        y = y0 + 4 + k * 32
        on = (loaded is None and not kind) or (loaded == (kind, ident))
        if i == cur: r.keycap((x0 + 5, y + 1, 548, y + 29), "lit", 5)
        elif k % 2: d.rectangle([x0 + 5, y, 548, y + 30], fill=(25, 27, 31))
        r.ledp(x0 + 18, y + 15, 4.2, on, GREEN)
        if kind == "builtin": name = {"Delay": "Tape Echo", "Drive": "Valve Drive", "Comp": "Bus Comp"}.get(ident, name)
        r.t(x0 + 34, y + 15, name[:40], 13, i == cur, (250, 251, 253) if i == cur else ((214, 218, 226) if on else (150, 156, 168)), "lm")
        tag = {"builtin": "BUILT-IN", "vst3": "VST3", "asr10": "ASR-10"}.get(kind, "")
        if tag: lab(r, 540, y + 15, tag, 4.6, (255, 255, 255) if i == cur else (110, 116, 128), "rm", "s", 0.12)
        def rdown(px, py, i=i):
            if c.fx_cursor == i: c.fx_load()
            else: c.fx_cursor = i
        r.hit((x0 + 4, y, 550, y + 30), down=rdown)
    if len(items) > rows:
        h = max(14, int(250 * rows / len(items))); yy = y0 + 6 + int((250 - h) * top / max(1, len(items) - rows))
        d.rounded_rectangle([553, yy, 557, yy + h], 2, fill=acc)
    r.plate((570, y0, x1, y1), 8)
    kind, ident, name = items[cur]
    lab(r, 582, y0 + 14, "EFFECT LIBRARY", 5.6, skin.LAB, "lm", "s", 0.16)
    if kind == "builtin": name = {"Delay": "Tape Echo", "Drive": "Valve Drive", "Comp": "Bus Comp"}.get(ident, name)
    r.t(582, y0 + 34, name[:22] if kind else "no effect", 15, True, (244, 246, 249), "lm")
    title, sub = TITLES.get(ident, ("", "")) if kind == "builtin" else ("", "")
    info = {"builtin": f"{title or name.upper()}: {sub.lower()}" if sub else "built-in effect",
            "vst3": "a VST3 plug-in (Q-links follow its first parameters)",
            "asr10": "an ASR-10 effect algorithm (from your ROM)"}.get(kind, "takes the effect out of this slot")
    for k, line in enumerate(_wrap(r, info, 196, 11)[:5]):
        r.t(582, y0 + 56 + k * 15, line, 11, False, (176, 182, 194), "lm")
    lab(r, 582, y1 - 46, "GOES ON", 5.0, skin.LAB, "lm", "s", 0.16)
    r.t(582, y1 - 32, c.fx_target_name(short=True), 12, True, acc, "lm")
    lab(r, 582, y1 - 12, "TAP AGAIN OR PUSH THE JOG TO LOAD", 4.6, skin.LAB2, "lm", "s", 0.1)


def _wrap(r, text, w, size):
    out, line = [], ""
    for word in text.split():
        t = (line + " " + word).strip()
        if r.d.textlength(t, font=font(size, False)) > w and line: out.append(line); line = word
        else: line = t
    return out + ([line] if line else [])


# ---------------------------------------------------------------- TAPE ECHO
def tape_echo(r, eff):
    d, e = r.d, r.e
    acc = accent(r)
    screw_title(r, eff, "dark")
    # the transport: tape tank window, heads, capstan
    d.rounded_rectangle([25, 133, 386, 292.5], 5, fill=(16, 16, 17), outline=(54, 54, 58), width=1)
    d.rounded_rectangle([45, 147, 367.5, 214], 3, fill=(10, 9, 8), outline=(64, 60, 56), width=1)
    d.rectangle([46, 148, 366.5, 172], fill=(16, 14, 12))
    ms = eff.ms()
    speed = 0.0 if not e.playing else 140.0 / max(60.0, ms)
    ph = (time.time() * speed) % (2 * math.pi)
    n = 24; pts = []
    for k in range(n * 28 + 1):
        th = k / 28.0 * 2 * math.pi + ph
        x = 54 + (k / (n * 28.0)) * 304 + 5.5 * math.sin(th)
        y = 181 + 28 * math.cos(th) * (0.9 + 0.1 * math.cos(k * 0.37))
        pts.append((x, clamp(y, 150, 211)))
    d.line(pts, fill=(84, 46, 22), width=2.4); d.line(pts, fill=(156, 92, 46), width=1.0)
    lab(r, 51, 220.6, "TAPE TANK", 4.4, (120, 116, 108), "lm", "s", 0.16)
    path = [(50, 212), (54, 236), (64, 241)] + [(x, 241) for x in (90, 330)] + [(338, 236), (349, 214)]
    d.line(path, fill=(110, 64, 30), width=2)
    d.rounded_rectangle([64, 242, 336, 261], 2, fill=(28, 28, 30), outline=(60, 60, 64), width=1)
    heads = eff.heads()
    names = [("ERASE", 79, None), ("REC", 121, None), ("PB 1", 184, 0), ("PB 2", 234, 1), ("PB 3", 284, 2)]
    for nm, hx, h in names:
        sp = skin.body(r.P(20), r.P(15), r.P(2), (232, 234, 238), (150, 154, 160), 0.3, 0.3, (3, 0.5))
        r.put(sp[0], hx - 10, 238, sp[1], sp[2])
        d.line([hx - 7, 243, hx + 7, 243], fill=(120, 122, 128))
        on = h is not None and h in heads
        if h is not None:
            r.ledp(hx, 267.5, 4.2, on, acc)
            lab(r, hx, 276, nm, 4.6, acc if on else (110, 108, 104), "mm", "b", 0.1)
        else: lab(r, hx, 269, nm, 4.4, (130, 128, 122), "mm", "s", 0.12)
    d.ellipse([320, 223, 335, 238], fill=(20, 20, 22), outline=(140, 140, 146), width=1)
    d.ellipse([324.5, 227.5, 330.5, 233.5], fill=(220, 222, 226))
    lab(r, 327.5, 269, "CAPSTAN", 4.4, (130, 128, 122), "mm", "s", 0.12)
    pb = "  ".join(f"PB{h + 1} {ms * eff.HEADS[h]:.0f} ms" for h in heads) if heads else "REVERB ONLY"
    lab(r, 209, 231, pb, 5.2, acc, "mm", "b", 0.04)
    # meter, peak, mode selector
    vu(r, (400, 137.5, 544, 225), getattr(eff, "peak", 0.0), ("fx", "echo"), "VU")
    lab(r, 472, 232, "INPUT", 4.6, (150, 146, 138), "mm", "s", 0.14)
    peak = getattr(eff, "peak", 0.0) > 0.89
    sp, pad = skin.pilot(r.P(17), peak, (240, 50, 40))
    r.img.paste(sp, (r.P(565.6) - r.P(17) // 2 - pad, r.P(173) - r.P(17) // 2 - pad), sp)
    lab(r, 565.6, 192, "PEAK", 4.6, (150, 146, 138), "mm", "s", 0.14)
    cx, cy = 694, 200
    nm = len(eff.MODES)
    cur = min(nm - 1, int(round(eff.vals[3] * (nm - 1))))
    for k, md in enumerate(eff.MODES):
        a = math.radians(-150 + 300 * k / (nm - 1))
        rr = 50
        r.d.line([cx + 33 * math.sin(a), cy - 33 * math.cos(a), cx + 37 * math.sin(a), cy - 37 * math.cos(a)], fill=(170, 170, 172), width=1)
        lab(r, cx + rr * math.sin(a) * (1.18 if len(md) > 3 else 1.0), cy - rr * math.cos(a), md, 4.8 if md.startswith(("R", "REV")) else 5.4,
            acc if k == cur else ((140, 140, 138) if md.startswith(("R", "REV")) else (226, 226, 222)), "mm", "b", 0.02)
    knob(r, cx, cy, 52, lambda: eff.get(3), lambda v: eff.set(3, round(v * (nm - 1)) / (nm - 1.0)), "c")
    lab(r, 610, 255, "ECHO", 4.6, (200, 200, 196), "mm", "s", 0.12)
    lab(r, 771, 255, "+ REVERB", 4.6, (130, 130, 128), "mm", "s", 0.12)
    lab(r, cx, 275.6, "MODE SELECTOR", 4.8, (180, 178, 172), "mm", "s", 0.16)
    # the knobs and the amber display
    bottom_bar(r, 303, 361)
    pknob(r, eff, 0, 69, 330, 32, "REPEAT RATE", "SHORT", "LONG")
    pknob(r, eff, 1, 201, 330, 32, "INTENSITY", "0", "10")
    pknob(r, eff, 2, 334, 330, 32, "ECHO VOLUME", "0", "10")
    beat = 60000.0 / max(20.0, e.bpm)
    note = _note_value(ms, beat)
    amber_box(r, (450, 309, 772.5, 354), [f"{ms:.0f} MS", f"{note} @ {e.bpm:.0f} BPM"], (17, 11))
    x0, x1, base = 598, 760, 347
    span = max(ms * 1.5 * 4, 1200.0)
    for h in heads or []:
        for k in range(1, 6):
            t = ms * eff.HEADS[h] * k
            if t > span: break
            hh = 30 * eff.vals[2] * (eff.vals[1] ** (k - 1)) / max(1, len(heads)) ** 0.3
            if hh < 1: continue
            xx = x0 + (x1 - x0) * t / span
            d.line([xx, base, xx, base - hh], fill=(255, 160, 70), width=1.6)
    d.line([x0, base + 0.5, x1, base + 0.5], fill=(90, 54, 24))


def _note_value(ms, beat):
    best = None
    for name, beats in (("1/32", 0.125), ("1/16", 0.25), ("1/8", 0.5), ("1/4", 1.0), ("1/2", 2.0), ("1/1", 4.0)):
        for suf, f in (("", 1.0), (" DOT", 1.5), (" TRIP", 2 / 3.0)):
            err = abs(math.log(ms / (beat * beats * f)))
            if best is None or err < best[0]: best = (err, name + suf)
    return best[1] if best[0] < 0.06 else f"{ms / beat:.2f} BEAT"


# ---------------------------------------------------------------- VALVE DRIVE
def valve_drive(r, eff):
    c, d = r.c, r.d
    acc = accent(r)
    screw_title(r, eff, "dark")
    byp = r.e.get_bypass(c.fx_tgt())
    d.rounded_rectangle([26, 136, 429, 302.5], 4, fill=(8, 8, 9), outline=(60, 60, 64), width=1)
    for k in range(30):                                                 # the cage
        xx = 32 + k * 13.4
        d.line([xx, 141, xx, 272], fill=(52, 50, 48), width=1)
    d.line([28, 141, 427, 141], fill=(120, 118, 114), width=1.5)
    d.rectangle([30, 273, 425, 299], fill=(42, 42, 45)); d.line([30, 273, 425, 273], fill=(90, 90, 94))
    glow = 0.0 if byp else 0.35 + 0.65 * eff.vals[0]
    for which, cx, w, top, power in ((1, 131, 31, 182, False), (2, 294, 38, 145, True)):
        h = 278 - top
        d.ellipse([cx - w * 0.9, 268, cx + w * 0.9, 280], fill=(30, 30, 33), outline=(100, 100, 106))
        sp = skin.valve(r.P(w), r.P(h), power, glow, (255, 140, 50))
        r.img.paste(sp, (r.P(cx - w / 2), r.P(top)), sp)
        name = eff.v1()[0] if which == 1 else eff.v2()[0]
        px0 = cx - 35
        sp2 = skin.body(r.P(70), r.P(13.4), r.P(1.5), (226, 228, 232), (176, 180, 186), 0.3, 0.3, (3, 0.5))
        r.put(sp2[0], px0, 281, sp2[1], sp2[2])
        lab(r, px0 + 13, 287.7, f"V{which}", 4.0, (90, 92, 98), "mm", "s", 0.1)
        r.t(px0 + 40, 287.7, name, 9.5, True, (30, 30, 34), "mm")
        r.hit((cx - 40, top - 4, cx + 40, 296), down=lambda *_, which=which: c.valve_open(which))
    vu(r, (445, 137.5, 601, 231), getattr(eff, "peak", 0.0) * 0.7, ("fx", "drive"), "VU")
    lab(r, 523, 239, "OUTPUT", 4.6, (150, 146, 138), "mm", "s", 0.14)
    sp, pad = skin.pilot(r.P(30), not byp, (255, 120, 40))
    r.img.paste(sp, (r.P(644) - r.P(30) // 2 - pad, r.P(165.6) - r.P(30) // 2 - pad), sp)
    lab(r, 644, 194, "PILOT", 4.6, (160, 158, 152), "mm", "s", 0.14)
    for cx, top, bot, name in ((704, "ON", "OFF", "POWER"), (745, "PLAY", "STBY", "STANDBY")):
        tg = skin.toggle(r.P(14), r.P(26), not byp)
        r.img.paste(tg, (r.P(cx - 7), r.P(165.6 - 13)), tg)
        lab(r, cx, 143, top, 4.0, (140, 138, 132), "mm", "s", 0.1); lab(r, cx, 182, bot, 4.0, (140, 138, 132), "mm", "s", 0.1)
        lab(r, cx, 195, name, 4.6, (180, 178, 172), "mm", "s", 0.14)
        r.hit((cx - 14, 140, cx + 14, 190), down=lambda *_: r.e.toggle_bypass(c.fx_tgt()))
    d.rounded_rectangle([445, 256, 772.5, 301], 3, fill=(16, 16, 18), outline=(50, 50, 54), width=1)
    lab(r, 457.5, 266, "V1", 4.0, (120, 118, 112), "lm"); r.t(476, 267, eff.v1()[0], 11, True, INK, "lm")
    lab(r, 537.5, 266, "V2", 4.0, (120, 118, 112), "lm"); r.t(556, 267, eff.v2()[0], 11, True, INK, "lm")
    lab(r, 457.5, 285, "TAP A VALVE TO CHANGE IT", 4.2, mix(acc, (60, 60, 60), 0.35), "lm", "s", 0.12)
    lab(r, 631, 266, "CHARACTER", 4.0, (120, 118, 112), "lm")
    r.t(631, 281, eff.character(), 10.5, False, acc, "lm")
    bottom_bar(r, 309, 361)
    pknob(r, eff, 0, 69, 332.5, 32, "DRIVE", "0", "10")
    pknob(r, eff, 3, 201, 332.5, 32, "BIAS", "COLD", "HOT")
    pknob(r, eff, 1, 334, 332.5, 32, "MIX", "DRY", "WET")
    pknob(r, eff, 2, 466, 332.5, 32, "LEVEL", "0", "10")
    lab(r, 740, 334, "MONOLITH", 4.6, (170, 168, 162), "rm", "b", 0.2)
    d.line([746, 326, 746, 342], fill=acc, width=1.5)
    lab(r, 752, 334, "VD-2", 4.6, (170, 168, 162), "lm", "b", 0.2)


def valve_case(r, eff):
    from fx import VALVES_V1, VALVES_V2
    c, d = r.c, r.d
    acc = accent(r)
    from PIL import Image
    shade = skin.cached(("shade", r.img.width, r.P(372)), lambda: Image.new("RGBA", (r.img.width, r.P(372)), (6, 7, 9, 150)))
    r.img.paste(shade, (0, 0), shade)
    x0, y0, x1, y1 = 75, 110, 725, 369
    sp = skin.faceplate(r.P(x1 - x0), r.P(y1 - y0), "alu")
    r.img.paste(sp, (r.P(x0), r.P(y0)), sp)
    r.hit((0, 0, 800, 372), down=lambda *_: None)
    for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):              # chrome corners
        d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=(214, 216, 220), outline=(120, 122, 128), width=1)
        d.ellipse([cx - 6, cy - 7, cx + 2, cy - 1], fill=(250, 250, 252))
    v = c.valve_case
    lab(r, 102.5, 122.5, "VALVE CASE", 7.0, (30, 30, 34), "lm", "b", 0.24)
    lab(r, 206, 122.5, "CHOOSE A VALVE FOR " + ("V1 PREAMP" if v == 1 else "V2 POWER"), 5.0, (70, 72, 78), "lm", "s", 0.12)
    d.rounded_rectangle([90, 137.5, 710, 325], 4, fill=(16, 16, 18))
    vals = VALVES_V1 if v == 1 else VALVES_V2
    cur = eff.v1()[0] if v == 1 else eff.v2()[0]
    n = len(vals); step = 103.3
    xs = [400 + (k - (n - 1) / 2.0) * step for k in range(n)]
    for k, cx in enumerate(xs):
        nm = vals[k][0]
        sel = k == c.valve_pick
        d.rounded_rectangle([cx - 21, 149, cx + 21, 259], 21, fill=(6, 6, 7), outline=acc if sel else None, width=1.4)
        sp = skin.valve(r.P(28), r.P(84), v == 2, 0.6 if sel else 0.0)
        r.img.paste(sp, (r.P(cx - 14), r.P(160)), sp)
        if nm == cur: lab(r, cx, 142.5, f"IN V{v} NOW", 4.0, (160, 160, 162), "mm", "s", 0.12)
        d.rounded_rectangle([cx - 41.5, 264, cx + 41.5, 319], 2, fill=(238, 228, 204), outline=acc if sel else (190, 180, 160), width=1.4 if sel else 1)
        r.t(cx - 35, 275.6, nm, 11, True, (30, 28, 26), "lm")
        if v == 1:
            mu = vals[k][1]
            r.t(cx + 33, 275.6, f"µ {mu}" if mu else "pentode", 9, False, (60, 56, 50), "rm")
            desc, harm = vals[k][2], vals[k][3]
        else: desc, harm = vals[k][1], (0.6, 0.8, 0.3, 0.2)
        while desc and r.d.textlength(desc, font=font(9, False)) > 72: desc = desc[:-2].rstrip(" ,") + "…" if not desc.endswith("…") else desc[:-2] + "…"
        r.t(cx - 35, 288, desc, 9, False, (70, 64, 56), "lm")
        for j, hv in enumerate(harm):
            bx = cx - 35 + j * 8
            d.rectangle([bx, 312 - 9 * hv, bx + 5, 312], fill=(176, 84, 40) if j == 0 else (130, 100, 76))
        lab(r, cx + 4, 309, "H2-H5", 3.6, (140, 130, 116), "lm", "s", 0.04)
        def pick(*_, k=k):
            if c.valve_pick == k: c.valve_insert()
            else: c.valve_pick = k
        r.hit((cx - 45, 145, cx + 45, 322), down=pick)
    lab(r, 102.5, 343.75, "TAP A VALVE, THEN INSERT  -  JOG OR Q1 TO BROWSE", 4.6, (70, 72, 78), "lm", "s", 0.12)
    r.con_key((519, 331, 594, 359), "CLOSE", False, None, lambda: setattr(c, "valve_case", None), 6.0)
    r.con_key((601, 331, 682.5, 359), "INSERT", True, acc, c.valve_insert, 6.0)


# ---------------------------------------------------------------- FILTER
def filt(r, eff):
    d = r.d
    acc = accent(r)
    screw_title(r, eff, "slate")
    d.rounded_rectangle([27.5, 141, 590, 351], 4, fill=(13, 15, 18), outline=(40, 42, 48), width=1)
    lab(r, 37.5, 152.5, "RESPONSE   DRAG THE NODE (UP = RESONANCE), OR TURN Q1", 4.4, (100, 104, 112), "lm", "s", 0.12)
    px0, px1, py0, py1 = 40, 577.5, 166, 335
    fx_ = lambda f: px0 + (px1 - px0) * math.log(f / 20.0) / math.log(1000.0)
    fy_ = lambda g: py0 + (py1 - py0) * (12 - g) / 54.0
    for g in (6, -6, -18, -30): d.line([px0, fy_(g), px1, fy_(g)], fill=(30, 33, 38))
    for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000):
        d.line([fx_(f), py0, fx_(f), py1], fill=(30, 33, 38))
        lab(r, fx_(f) + 3, py1 - 6, f"{f // 1000}k" if f >= 1000 else str(f), 4.2, (100, 104, 112), "lm", "s", 0.0)
    fl = np.arange(200) / 199.0
    fr = 20.0 * 1000.0 ** fl
    resp = eff.response(fr)
    line = [(px0 + (px1 - px0) * a, clamp(fy_(float(v)), py0, py1)) for a, v in zip(fl, resp)]
    d.polygon([(px0, py1)] + line + [(px1, py1)], fill=mix((13, 15, 18), acc, 0.12))
    d.line(line, fill=mix((13, 15, 18), acc, 0.4), width=4); d.line(line, fill=acc, width=1.6)
    fc = eff.cutoff(); nx = fx_(fc); ny = clamp(fy_(float(eff.response([fc])[0])), py0, py1)
    for yy in range(int(py0), int(py1), 6): d.line([nx, yy, nx, yy + 2], fill=mix((13, 15, 18), acc, 0.5))
    d.ellipse([nx - 9, ny - 9, nx + 9, ny + 9], outline=acc, width=1.4)
    d.ellipse([nx - 3, ny - 3, nx + 3, ny + 3], fill=(255, 255, 255))
    r.t(nx + 14, ny - 9, eff.fmt(0), 10, True, acc, "lm")
    def drag(px, py):
        eff.set(0, clamp(math.log(max(80.0, 20.0 * 1000.0 ** ((px - px0) / (px1 - px0))) / 80.0) / math.log(200.0), 0, 1))
        eff.set(3, clamp((fy_(0) - py) / 70.0 + 0.0, 0, 1) if py < fy_(0) else 0.0)
    r.hit((px0, py0, px1, py1), down=drag, drag=drag)
    # mode knob
    cx, cy = 650, 206
    mode = eff.mode()
    for nm, (lx, ly), (ledx, ledy), v in (("LP", (611, 183), (611, 193), 0.0), ("BP", (650, 160.6), (650, 169), 0.5), ("HP", (689, 183), (689, 193), 1.0)):
        lab(r, lx, ly, nm, 5.6, acc if mode == nm else (140, 144, 150), "mm", "b", 0.04)
        r.ledp(ledx, ledy, 3.2, mode == nm, acc)
        r.hit((lx - 12, ly - 8, lx + 12, ly + 14), down=lambda *_, v=v: eff.set(1, v))
    knob(r, cx, cy, 44, lambda: {"LP": 0.1, "BP": 0.5, "HP": 0.9}[eff.mode()], lambda v: eff.set(1, v), "n")
    lab(r, cx, 249, "MODE", 4.8, (150, 154, 160), "mm", "s", 0.14)
    amber_box(r, (602.5, 290, 696, 351), [f"{mode} {_khz(fc)}", f"CUTOFF {eff.vals[0] * 100:.0f}%", f"MIX {eff.vals[2] * 100:.0f}%"], (14, 9.5, 9.5))
    vfader(r, (706, 141, 775, 351), lambda: eff.get(2), lambda v: eff.set(2, v))


def _khz(f): return f"{f:.0f}" if f < 1000 else f"{f / 1000:.1f}K"


# ---------------------------------------------------------------- CRUSH
def crush(r, eff):
    d = r.d
    acc = accent(r)
    screw_title(r, eff, "slate")
    d.rounded_rectangle([27.5, 141, 427.5, 351], 4, fill=(13, 15, 18), outline=(40, 42, 48), width=1)
    lab(r, 37.5, 152.5, "WHAT IT DOES TO A WAVE", 4.4, (100, 104, 112), "lm", "s", 0.12)
    rate, bits = eff.rate(), eff.bits()
    lab(r, 349, 153, f"{2 ** bits if bits < 13 else '%dk' % (2 ** bits // 1000)} LEVELS   {eff.fmt(0).upper()}", 5.0, acc, "mm", "b", 0.06)
    px0, px1, py0, py1 = 40, 415, 175, 325
    for k in range(7): d.line([px0, py0 + (py1 - py0) * k / 6, px1, py0 + (py1 - py0) * k / 6], fill=(28, 31, 36))
    n = 300; t = np.arange(n) / (n - 1.0)
    cyc = 2.0
    clean = np.sin(2 * np.pi * cyc * t - 0.4)
    spc = rate / 2000.0                                                 # samples per cycle of a 2 kHz tone
    held = np.sin(2 * np.pi * np.floor(t * cyc * spc) / spc - 0.4)
    lv = 2.0 ** (bits - 1)
    q = np.round(held * lv) / lv
    mid, amp = (py0 + py1) / 2, (py1 - py0) / 2 * 0.9
    d.line([(px0 + (px1 - px0) * a, mid - amp * v) for a, v in zip(t, clean)], fill=(120, 124, 132), width=1)
    pts = []
    for a, v in zip(t, q):
        x, y = px0 + (px1 - px0) * a, mid - amp * v
        if pts and abs(pts[-1][1] - y) > 1e-3: pts.append((x, pts[-1][1]))
        pts.append((x, y))
    d.line(pts, fill=mix((13, 15, 18), acc, 0.4), width=4); d.line(pts, fill=acc, width=1.6)
    # bits knob
    cx, cy = 512.5, 234
    for b in (16, 12, 10, 8, 6, 4, 2):
        fr = 1 - (b - 2) / 14.0
        a = math.radians(-135 + 270 * fr)
        lab(r, cx + 46 * math.sin(a), cy - 46 * math.cos(a), str(b), 5.6, acc if b == bits else (150, 154, 160), "mm", "b", 0.0)
    knob(r, cx, cy, 52, lambda: 1 - eff.get(1), lambda v: eff.set(1, 1 - v), "n")
    lab(r, cx, 301, "BITS", 4.8, (150, 154, 160), "mm", "s", 0.14)
    r.t(cx, 314, f"{bits} bit", 11, True, acc, "mm")
    # the rate ladder
    lab(r, 590, 144.4, "RATE", 4.8, (150, 154, 160), "lm", "s", 0.14)
    for k, (hz, txt, who) in enumerate(eff.RATES):
        y0 = 154 + k * 32.5
        sel = k == eff.rate_i()
        r.con_key((590, y0, 684, y0 + 27.5), "", sel, acc, lambda k=k: eff.set(0, k / (len(eff.RATES) - 1.0)))
        tc = (255, 255, 255) if sel else (210, 212, 218)
        r.t(637, y0 + (10 if who else 13.75), txt, 10.5, True, tc, "mm")
        if who: lab(r, 637, y0 + 21, who, 3.6, tc, "mm", "b", 0.06)
    vfader(r, (697.5, 141, 772.5, 351), lambda: eff.get(2), lambda v: eff.set(2, v))


# ---------------------------------------------------------------- BUS COMP
def comp(r, eff):
    d = r.d
    acc = accent(r)
    screw_title(r, eff, "alu")
    dark = (30, 30, 34)
    vu(r, (30, 141, 217.5, 251), 0, ("fx", "gr"), "GR", gr=eff.gr)
    lab(r, 123.75, 258.75, "GAIN REDUCTION", 4.6, (60, 62, 68), "mm", "s", 0.14)
    # the transfer curve
    d.rounded_rectangle([231, 140, 431, 252.5], 5, fill=(12, 12, 14), outline=(90, 92, 98), width=1.5)
    lab(r, 241, 150, "CURVE", 4.2, (100, 102, 108), "lm", "s", 0.14)
    cx0, cx1, cy0, cy1 = 244, 420, 158, 242
    tx = lambda db: cx0 + (cx1 - cx0) * (db + 60) / 60.0
    ty = lambda db: cy1 - (cy1 - cy0) * (db + 60) / 72.0
    for k in range(12):
        a, b = -60 + k * 5, -60 + k * 5 + 2.5
        d.line([tx(a), ty(a), tx(b), ty(b)], fill=(80, 82, 88))
    xs = np.linspace(-60, 0, 80); ys = eff.curve(xs)
    d.line([(tx(a), clamp(ty(b), cy0, cy1)) for a, b in zip(xs, ys)], fill=acc, width=1.8)
    th = eff.thr(); dy = float(eff.curve([th])[0])
    d.ellipse([tx(th) - 3, ty(dy) - 3, tx(th) + 3, ty(dy) + 3], fill=(255, 255, 255))
    # gain-reduction history
    d.rounded_rectangle([29, 269, 431, 352.5], 5, fill=(12, 12, 14), outline=(90, 92, 98), width=1.5)
    lab(r, 39, 279, "GAIN REDUCTION, LATEST", 4.2, (100, 102, 108), "lm", "s", 0.14)
    hx0, hx1, hy0, hy1 = 42, 418, 287, 345
    hist = eff.hist[-300:]
    if hist:
        pts = [(hx0 + (hx1 - hx0) * k / 299.0, hy0 + (hy1 - hy0) * min(1.0, g / 12.0)) for k, g in enumerate([0.0] * (300 - len(hist)) + hist)]
        d.polygon([(hx0, hy0)] + pts + [(hx1, hy0)], fill=mix((12, 12, 14), acc, 0.25))
        d.line(pts, fill=acc, width=1.4)
    d.line([hx0, hy0, hx1, hy0], fill=(80, 82, 88))
    # ratio
    lab(r, 447.5, 144.4, "RATIO", 4.8, (60, 62, 68), "lm", "s", 0.14)
    ri = min(5, int(round(eff.vals[1] * 5)))
    for k, rt in enumerate(eff.RATIOS):
        x0 = 447.5 + (k % 3) * 43.75; y0 = 154 + (k // 3) * 33.5
        r.con_key((x0, y0, x0 + 39, y0 + 29), "ALL" if rt == 100 else str(rt), k == ri, acc, lambda k=k: eff.set(1, k / 5.0), 6.6)
    # threshold, attack, release
    def bk(i, cx, cy, dia, name, lo, hi):
        knob(r, cx, cy, dia, lambda: eff.get(i), lambda v: eff.set(i, v))
        lab(r, cx - dia * 0.55, cy + dia * 0.62, lo, 4.0, dark, "mm", "s", 0.0)
        lab(r, cx + dia * 0.55, cy + dia * 0.62, hi, 4.0, dark, "mm", "s", 0.0)
        lab(r, cx, cy + dia * 0.98, name, 4.6, (60, 62, 68), "mm", "s", 0.14)
        r.t(cx, cy + dia * 0.98 + 13, eff.fmt(i), 11, True, dark, "mm")
    bk(0, 712.5, 172.5, 46, "THRESHOLD", "-40", "0")
    bk(2, 500, 279, 38, "ATTACK", ".1", "100")
    bk(3, 600, 279, 38, "RELEASE", "50", "A")
    # SC HPF and makeup
    d.rounded_rectangle([660, 279, 704, 331], 3, fill=(22, 22, 25), outline=(80, 82, 88), width=1)
    on = eff.vals[5] > 0.5
    lab(r, 668, 284.5, "ON", 3.8, (140, 140, 146), "mm", "s", 0.06)
    r.ledp(695.6, 284.5, 3.2, on, acc)
    tg = skin.toggle(r.P(12), r.P(22), on)
    r.img.paste(tg, (r.P(682 - 6), r.P(301 - 11)), tg)
    lab(r, 682, 323, "SC HPF", 4.4, (200, 200, 204), "mm", "s", 0.1)
    r.hit((660, 279, 704, 331), down=lambda *_: eff.set(5, 0.0 if on else 1.0))
    vfader(r, (712.5, 256, 769, 354), lambda: eff.get(4), lambda v: eff.set(4, v), "MAKEUP", eff.fmt(4))


# ---------------------------------------------------------------- any other effect (ASR-10, VST3)
def generic(r, eff):
    c, d = r.c, r.d
    acc = accent(r)
    screw_title(r, eff, "slate")
    order = c.fx_order(eff)
    page = c.fx_page
    s0 = (page * 4 // 8) * 8
    shown = order[s0:s0 + 8]
    d.rounded_rectangle([20, 140, 782.5, 356], 4, fill=(22, 24, 28), outline=(44, 46, 52), width=1)
    on_q = set(order[c.fx_page * 4:c.fx_page * 4 + 4])
    for k, i in enumerate(shown):
        cx = 70 + (k % 4) * 185; cy = 190 + (k // 4) * 95
        knob(r, cx, cy, 40, lambda i=i: eff.get(i), lambda v, i=i: eff.set(i, v), "b")
        q = (order.index(i) - c.fx_page * 4 + 1) if i in on_q else None
        lab(r, cx + 34, cy - 10, (f"Q{q}  " if q else "") + eff.labels[i].upper()[:18], 5.0, acc if q else (150, 154, 160), "lm", "s", 0.12)
        r.t(cx + 34, cy + 6, eff.fmt(i)[:14], 12, True, INK, "lm")
    if eff.n() > 8:
        lab(r, 772, 346, f"{eff.n()} PARAMETERS  -  F4 / CURSOR DOWN FOR THE NEXT FOUR", 4.4, (120, 124, 132), "rm", "s", 0.1)
