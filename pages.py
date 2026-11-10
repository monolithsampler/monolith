"""pages.py - PROG (front panel), STEP, MUTE, SAMPLE, CHOP, SONG and BROWSE (+ the IMPORT window), drawn to the design
artboards (design/prev/*.png). Every function takes the Renderer (screens.py) as r and draws in 800 x 500 layout units."""
import math, os, time
import numpy as np
import skin
from PIL import Image
from uicore import clamp, mix, font, GREEN, YEL, RED, CYAN
from engine import OUT_SR, BANKS, NSEQ, NOTE_KINDS, KIND_NAMES

INK, INK2, LAB = (232, 234, 240), (150, 156, 168), skin.LAB


def acc(r): return skin.ACCENTS.get(r.e.machine, skin.ACCENTS["MODERN"])


def lab(r, x, y, txt, size=5.6, col=LAB, anchor="lm", w="s", sp=0.16):
    r.lab(x, y, txt, size, col, anchor, w, sp, floor=size)


def gpad(r, rect, on, col=None, rr=None):
    x0, y0, x1, y1 = rect
    sp, ox, oy = skin.glow_pad(r.P(x1 - x0), r.P(y1 - y0), on, col or acc(r), rr)
    r.put(sp, x0, y0, ox, oy)


def seg(r, rect, names, cur, pick, size=5.4):
    """a row of keys in a sunk well, one lit (with its LED)"""
    x0, y0, x1, y1 = rect
    r.well(rect, 5, (18, 19, 22), 5)
    n = len(names); w = (x1 - x0 - 4 - 2 * (n - 1)) / float(n)
    for k, nm in enumerate(names):
        bx = x0 + 2 + k * (w + 2)
        on = k == cur
        r.keycap((bx, y0 + 2, bx + w, y1 - 2), "down" if on else "up", 4)
        tw = r.d.textlength(nm, font=font(9, True)) * 0.62
        if on: r.ledp(bx + w / 2 - tw / 2 - 5, (y0 + y1) / 2, 3.0, True, acc(r))
        lab(r, bx + w / 2 + (3 if on else 0), (y0 + y1) / 2, nm, size, (244, 246, 249) if on else (140, 147, 160), "mm", "b", 0.08)
        r.hit((bx, y0, bx + w, y1), down=lambda *_, k=k: pick(k))


def toggle_box(r, rect, name, on, tap, sel=False):
    """a toggle switch in its own little well, ON label and LED at the top, its name under it (PROG VOICE, SAMPLE, CHOP)"""
    x0, y0, x1, y1 = rect
    r.d.rounded_rectangle([x0, y0, x1, y1], 4, fill=(18, 19, 22), outline=acc(r) if sel else (40, 42, 47), width=1)
    lab(r, x0 + 6, y0 + 6.5, "ON", 3.8, (110, 114, 124), "lm", "s", 0.06)
    r.ledp(x1 - 6.5, y0 + 6.5, 3.0, on, acc(r))
    cx = (x0 + x1) / 2
    tg = skin.toggle(r.P(13), r.P(24), on)
    r.img.paste(tg, (r.P(cx - 6.5), r.P(y0 + 13)), tg)
    lab(r, cx, y1 - 8, name, 4.6, (200, 204, 212), "mm", "s", 0.08)
    r.hit(rect, down=lambda *_: tap())


def vfader(r, rect, frac, setter, name, value, sel=False, centre=False):
    """a small fader in its own well: value on top, name below (PROG envelope / filter)"""
    x0, y0, x1, y1 = rect
    a = acc(r)
    r.d.rounded_rectangle([x0, y0, x1, y1], 4, fill=(18, 19, 22), outline=a if sel else (40, 42, 47), width=1)
    cx = (x0 + x1) / 2
    lab(r, cx, y0 + 9.5, value, 5.6, INK, "mm", "b", 0.02)
    ty0, ty1 = y0 + 22, y1 - 19
    for k in range(11):
        yy = ty0 + (ty1 - ty0) * k / 10
        r.d.line([cx - 11.5, yy, cx - 8, yy], fill=(80, 82, 88))
    r.d.rounded_rectangle([cx - 1.6, ty0, cx + 1.6, ty1], 1.6, fill=(6, 6, 7))
    f = clamp(frac, 0, 1)
    fy = ty1 - (ty1 - ty0) * f
    if centre:
        my = (ty0 + ty1) / 2
        r.d.rectangle([cx - 1.1, min(my, fy), cx + 1.1, max(my, fy)], fill=a)
    else: r.d.rounded_rectangle([cx - 1.1, fy, cx + 1.1, ty1], 1.1, fill=a)
    cap = skin.body(r.P(21), r.P(11), r.P(2), (226, 228, 232), (160, 164, 170), 0.3, 0.3, (3, 0.5))
    r.put(cap[0], cx - 10.5, fy - 5.5, cap[1], cap[2])
    r.d.line([cx - 7, fy, cx + 7, fy], fill=(70, 72, 78))
    lab(r, cx, y1 - 8.5, name, 4.6, (170, 174, 184), "mm", "s", 0.1)
    st = {}
    def down(px, py): st["y"], st["f"] = py, f
    def drag(px, py): setter(clamp(st["f"] + (st["y"] - py) / float(ty1 - ty0), 0.0, 1.0))
    r.hit(rect, down=down, drag=drag)


# =========================================================== PROG: the front panel
def prog_front(r):
    c, e, d = r.c, r.e, r.d
    p = e.pad
    a = acc(r)
    # the sample
    r.plate((10, 49, 484.5, 192), 8)
    r.glassbox((19, 56, 477.5, 185), 6)
    name = (p.src.name if p.src else "empty").upper()
    r.btn((24, 59, 38, 73), "<", lambda: c.select(e.sel - 1), 9, grow=3)
    lab(r, 43, 66, f"{BANKS[e.bank]}{e.sel + 1:02d}  {name[:22]}", 5.6, (210, 214, 222), "lm", "s", 0.14)
    tw = r.d.textlength(f"{BANKS[e.bank]}{e.sel + 1:02d}  {name[:22]}", font=font(9, False)) * 0.85
    r.btn((48 + tw + 6, 59, 62 + tw + 6, 73), ">", lambda: c.select(e.sel + 1), 9, grow=3)
    r.hit((40, 58, 46 + tw, 75), down=lambda *_: (setattr(c, "picking", True), setattr(c, "pick_cur", p.src.id if p.src else 0)))
    info = f"{p.length / OUT_SR:.2f} S  44.1K  MONO" if p.src else "TAP THE NAME TO PICK A SAMPLE"
    lab(r, 330, 66, info, 4.6, (120, 126, 138), "lm", "s", 0.12)
    # program: PRG - / name / PRG +
    r.btn((402, 59, 414, 73), "<", lambda: setattr(e.track, "prog", (e.track.prog - 1) % len(e.programs)), 9, grow=3)
    lab(r, 440, 66, e.prog.name.upper()[:8], 4.8, a, "mm", "b", 0.08)
    r.hit((418, 58, 462, 75), down=lambda *_: c.rename_program())
    r.btn((466, 59, 478, 73), ">", lambda: setattr(e.track, "prog", (e.track.prog + 1) % len(e.programs)), 9, grow=3)
    rect = (27, 78, 470, 172)
    src = p.src
    A, B = (0, src.length) if src else (0, 1)
    if src and not getattr(c, "pw_whole", False):                      # the region, a little either side (WHOLE: all of the file)
        m_ = max(int(0.12 * p.length), int(0.02 * OUT_SR)); A, B = max(0, p.start - m_), min(src.length, p.end + m_)
    if src:
        mins, maxs = src.envelope(int(rect[2] - rect[0]), A, B)
        cy, hh = (rect[1] + rect[3]) / 2, (rect[3] - rect[1]) / 2 - 2
        X = lambda pos: rect[0] + (pos - A) / float(max(1, B - A)) * (rect[2] - rect[0])
        top, bot = [], []
        for i in range(len(mins)):
            pos = A + (B - A) * i / float(len(mins))
            top.append((rect[0] + i, cy - maxs[i] * hh)); bot.append((rect[0] + i, cy - mins[i] * hh))
        xs, xe = X(p.start), X(p.end)
        poly = top + bot[::-1]
        d.polygon(poly, fill=mix((12, 13, 16), a, 0.22))
        d.line(top, fill=a, width=1); d.line(bot, fill=a, width=1)
        if xe < rect[2]: d.rectangle([xe, rect[1], rect[2], rect[3]], fill=(10, 11, 13))
        if xs > rect[0]: d.rectangle([rect[0], rect[1], xs, rect[3]], fill=(10, 11, 13))
        d.line([rect[0], cy, rect[2], cy], fill=mix((12, 13, 16), a, 0.5))
        for xx in (xs, xe): d.line([xx, rect[1], xx, rect[3]], fill=(240, 240, 242), width=1.4)
        ph = e.playhead(p)
        if ph is not None and A <= ph <= B: d.line([X(ph), rect[1], X(ph), rect[3]], fill=(255, 255, 255))
        lab(r, max(rect[0], xs) + 2, 179, f"START {p.start / OUT_SR:.3f}", 4.4, (140, 144, 152), "lm", "s", 0.1)
        lab(r, min(rect[2] - 50, xe) - 2, 179, f"END {p.end / OUT_SR:.3f}", 4.4, (140, 144, 152), "rm" if xe < rect[2] - 50 else "lm", "s", 0.1)
        def wdown(px, py):
            f = A + (px - rect[0]) / float(rect[2] - rect[0]) * (B - A)
            c.prog_row = 1 if abs(f - p.start) <= abs(f - p.end) else 2
        def wdrag(px, py):
            f = int(A + clamp((px - rect[0]) / float(rect[2] - rect[0]), 0, 1) * (B - A))
            msg = e.set_region(p, start=f) if c.prog_row == 1 else e.set_region(p, end=f)
            if msg and getattr(c, "_pw_msg", None) != msg: c._pw_msg = msg; c.say(msg)
        r.hit(rect, down=wdown, drag=wdrag)
        r.con_key((432, 160, 468, 171), "WHOLE", getattr(c, "pw_whole", False), a, lambda: setattr(c, "pw_whole", not getattr(c, "pw_whole", False)), 4.4)
    else:
        r.t(248, 125, "no sample on this pad - tap the name above", 12, False, (120, 126, 138), "mm")
    # VOICE
    r.plate((495, 49, 792, 192), 8)
    lab(r, 506, 61, "VOICE", 5.2)
    sp1200 = e.sound_of(p) == "SP-1200"
    tg = [("LO-FI" if not sp1200 else f"{p.rpm} RPM", p.lofi_on if not sp1200 else p.rpm != 33, 12),
          ("REVERSE", p.reverse, 8), ("WARP", p.warp, 14), ("NORMALIZE", p.norm, 9), ("MUTE", p.mute, None)]
    for k, (nm, on, row) in enumerate(tg):
        x0 = 506 + k * 56.25
        def tap(row=row):
            if row is None: p.mute = not p.mute
            else: c.prog_row = row; c.prog_adjust(row, 1)
        toggle_box(r, (x0, 72.5, x0 + 44, 125.6), nm, on, tap)
    lab(r, 506, 141.9, "PLAY MODE", 5.0)
    modes = ["ONE SHOT", "NOTE ON", f"CHOKE {p.choke or '-'}"]
    def pick(k):
        if k == 0: p.mode = "ONE"
        elif k == 1: p.mode = "HOLD"
        else: c.prog_row = 7; p.choke = (p.choke + 1) % 9
    seg(r, (506, 150, 781, 172), modes, 0 if p.mode == "ONE" else 1, pick, 5.0)
    if p.choke: r.d.rounded_rectangle([506 + 2 + 2 * ((275 - 8) / 3.0 + 2), 152, 779, 170], 4, outline=a, width=1)
    lab(r, 506, 182, f"CHOKE GROUP {p.choke or 'OFF'}   OUT {('ST 1-2', 'ST 3-4', 'ST 5-6', 'ST 7-8')[min(3, p.out)] if p.out < 4 else p.out}"
        f"   FX {e.get_fx(p).name.upper() if e.get_fx(p) else 'NONE'}", 4.4, (120, 126, 138), "lm", "s", 0.12)
    # AMP ENVELOPE
    r.plate((10, 201, 391, 366), 8)
    lab(r, 21, 213, "AMP ENVELOPE", 5.2)
    root = lambda v, top: (v / float(top)) ** 0.5
    unroot = lambda f, top: int(round(f * f * top))
    env = [("ATTACK", root(p.attack, 2000), lambda f: setattr(p, "attack", unroot(f, 2000)), f"{p.attack} ms", 16),
           ("DECAY", root(p.decay, 5000), lambda f: setattr(p, "decay", unroot(f, 5000)), f"{p.decay} ms" if p.decay else "OFF", 17),
           ("FADE IN", root(p.fade_in, 500), lambda f: (setattr(p, "fade_in", unroot(f, 500)), e.pad_changed(p)), f"{p.fade_in} ms", 10),
           ("FADE OUT", root(p.fade_out, 500), lambda f: (setattr(p, "fade_out", unroot(f, 500)), e.pad_changed(p)), f"{p.fade_out} ms", 11)]
    for k, (nm, f, st, val, row) in enumerate(env):
        x0 = 19 + k * 46.25
        def setter(v, st=st, row=row): c.prog_row = row; st(v)
        vfader(r, (x0, 226, x0 + 41, 358.75), f, setter, nm, val, c.prog_row == row)
    # its shape
    gx0, gy0, gx1, gy1 = 209, 225, 382.5, 358.75
    d.rounded_rectangle([gx0, gy0, gx1, gy1], 4, fill=(13, 14, 17), outline=(40, 42, 47), width=1)
    lab(r, gx0 + 9, gy0 + 10, "SHAPE", 4.4, (110, 114, 124), "lm", "s", 0.14)
    px0, px1, py0, py1 = gx0 + 10, gx1 - 10, gy0 + 22, gy1 - 10
    atk, dec = p.attack, p.decay
    T = max(250.0, (atk + (dec * 1.6 if dec else 400)) * 1.1)
    pts = []
    for k in range(120):
        t = T * k / 119.0
        if t < atk: g = t / max(1.0, atk)
        elif dec: g = math.exp(-(t - atk) / (dec / 4.0))
        else: g = 1.0
        fi = min(1.0, t / max(1e-3, p.fade_in)) if p.fade_in else 1.0
        pts.append((px0 + (px1 - px0) * k / 119.0, py1 - (py1 - py0) * g * fi))
    d.polygon([(px0, py1)] + pts + [(px1, py1)], fill=mix((13, 14, 17), a, 0.18))
    d.line(pts, fill=a, width=1.6)
    pk = max(pts, key=lambda q: -q[1])
    d.ellipse([pk[0] - 2.5, pk[1] - 2.5, pk[0] + 2.5, pk[1] + 2.5], fill=(255, 255, 255))
    if dec:
        q = next((q for q in pts if q[1] > py1 - 2), pts[-1])
        d.ellipse([q[0] - 2.5, q[1] - 2.5, q[0] + 2.5, q[1] + 2.5], fill=(255, 255, 255))
    # FILTER
    r.plate((401, 201, 792, 366), 8)
    lab(r, 412.5, 213, "FILTER", 5.2)
    mpc60 = e.sound_of(p) == "MPC60"
    order = ["LP", "BP", "HP"]
    def fpick(k):
        c.prog_row = 18
        p.flt = "OFF" if p.flt == order[k] else order[k]
        if p.flt == "LP" and p.cutoff >= 0.99: p.cutoff = 0.7
    seg(r, (650, 206, 784, 224), order, order.index(p.flt) if p.flt in order else -1, fpick, 4.8)
    hz = e.cut_hz(p.cutoff)
    flt = [("CUTOFF", p.cutoff, lambda f: setattr(p, "cutoff", round(f, 3)), f"{hz:.0f} Hz" if hz < 1000 else f"{hz / 1000:.1f} kHz", 19, False),
           ("RESO", p.res, lambda f: setattr(p, "res", round(f, 2)), f"{p.res * 100:.0f}%", 20, False),
           ("ENV AMT", (p.f_env + 1) / 2, lambda f: setattr(p, "f_env", round(f * 2 - 1, 2)), f"{p.f_env * 100:+.0f}", 21, True),
           ("VEL", p.f_vel, lambda f: setattr(p, "f_vel", round(f, 2)), f"{p.f_vel * 100:.0f}%", 23, False)]
    for k, (nm, f, st, val, row, cen) in enumerate(flt):
        x0 = 410 + k * 46.25
        def setter(v, st=st, row=row): c.prog_row = row; st(v)
        vfader(r, (x0, 232.5, x0 + 41, 358.75), f, setter, nm, val, c.prog_row == row, cen)
    # its response
    gx0, gy0, gx1, gy1 = 600, 232.5, 784, 358.75
    d.rounded_rectangle([gx0, gy0, gx1, gy1], 4, fill=(13, 14, 17), outline=(40, 42, 47), width=1)
    lab(r, gx0 + 9, gy0 + 10, "RESPONSE" if not mpc60 else "RESPONSE  (THE MPC60 HAS NO FILTER)", 4.4, (110, 114, 124), "lm", "s", 0.14)
    px0, px1, py0, py1 = gx0 + 4, gx1 - 4, gy0 + 22, gy1 - 6
    for k in range(1, 6): d.line([px0 + (px1 - px0) * k / 6, py0, px0 + (px1 - px0) * k / 6, py1], fill=(28, 30, 35))
    fr = 20.0 * 1000.0 ** (np.arange(90) / 89.0)
    if p.flt in order and not mpc60:
        q = 0.5 + p.res * 6.0
        s_ = 1j * fr / hz
        num = {"LP": 1.0, "HP": s_ * s_, "BP": s_ / q}[p.flt]
        db = 20 * np.log10(np.maximum(np.abs(num / (s_ * s_ + s_ / q + 1)), 1e-6))
    else: db = np.zeros(len(fr))
    pts = [(px0 + (px1 - px0) * k / 89.0, clamp(py0 + (py1 - py0) * (0.25 + (-float(v)) / 48.0), py0, py1)) for k, v in enumerate(db)]
    d.polygon([(px0, py1)] + pts + [(px1, py1)], fill=mix((13, 14, 17), a, 0.18))
    d.line(pts, fill=a if p.flt in order else (90, 94, 102), width=1.6)
    if p.flt not in order: lab(r, (px0 + px1) / 2, py1 - 12, "FILTER OFF", 4.6, (110, 114, 124), "mm", "s", 0.14)


# =========================================================== STEP
def step(r):
    c, e, d = r.c, r.e, r.d
    a = acc(r)
    sq, p = e.seq, e.pad
    # TRACK
    r.plate((10, 49, 792, 123), 8)
    lab(r, 21, 61, "TRACK", 5.2)
    n0 = max(0, min(e.cur_track - 2, 16 - 6))
    for k in range(6):
        t = n0 + k
        tr = sq.tracks[t]
        x0 = 21 + k * 93.75
        sel = t == e.cur_track
        r.keycap((x0, 70, x0 + 87.5, 113), "up", 5)
        if sel: d.rounded_rectangle([x0, 70, x0 + 87.5, 113], 5, outline=a, width=1)
        nm_col = a if sel else ((236, 238, 242) if tr.events else (130, 136, 148))
        r.t(x0 + 43.75, 87.5, tr.name[:12], 10, True, nm_col, "mm")
        lab(r, x0 + 43.75, 98, f"TRK {t + 1:02d}" + ("" if tr.kind not in NOTE_KINDS else f"  {KIND_NAMES[tr.kind]}"), 4.4,
            (130, 136, 148), "mm", "s", 0.08)
        r.hit((x0, 68, x0 + 87.5, 115), down=lambda *_, t=t: setattr(e, "cur_track", t))
    res = {48: 0, 24: 1, 12: 2}.get(c.step_res, 1)
    seg(r, (594, 77.5, 781, 105), ["1/8", "1/16", "1/32"], res,
        lambda k: (setattr(c, "step_res", (48, 24, 12)[k]), setattr(c, "step_page", 0)), 5.0)
    if e.track.kind in NOTE_KINDS:
        r.plate((10, 133, 792, 366), 8)
        r.t(400, 230, f"track {e.track.n + 1} is a {KIND_NAMES[e.track.kind]} track: edit its notes in GRID", 13, True, CYAN, "mm")
        r.t(400, 254, "STEP edits pad (drum) tracks", 11, False, INK2, "mm"); return
    pages = c.step_pages()
    c.step_page = clamp(c.step_page, 0, pages - 1)
    X = lambda i: 45.6 + i * 47.45
    # VELOCITY
    r.well((10, 133, 792, 226), 8, (16, 17, 20), 7)
    lab(r, 21, 143, f"VELOCITY   PAD {BANKS[e.bank]}{e.sel + 1:02d}  {(p.src.name if p.src else 'EMPTY').upper()[:24]}", 5.0)
    for i in range(16):
        x = X(i)
        evs = c.step_events(i)
        d.rounded_rectangle([x - 3, 154, x + 3, 216], 3, fill=(8, 8, 10))
        if evs:
            v = max(ev[2] for ev in evs) / 127.0
            y = 216 - 62 * v
            d.rounded_rectangle([x - 4.5, y - 1, x + 4.5, 216 + 1], 3, fill=mix((16, 17, 20), a, 0.25))
            d.rounded_rectangle([x - 2, y, x + 2, 216], 2, fill=a)
        def vdrag(px, py, i=i):
            if c.step_events(i): c.step_cursor = i; c.step_set_vel(i, 1 + clamp((216 - py) / 62.0, 0, 1) * 126)
        r.hit((x - 20, 148, x + 20, 222), down=vdrag, drag=vdrag)
    # the 16 steps
    r.plate((10, 235, 792, 366), 8)
    play_i = None
    span = 16 * c.step_res
    if e.playing and c.step_page * span <= e.pos < (c.step_page + 1) * span: play_i = int((e.pos - c.step_page * span) // c.step_res)
    for i in range(16):
        x0 = 20 + i * 47.7
        tick = c.step_tick(i)
        valid = tick < sq.length
        evs = c.step_events(i) if valid else []
        lab(r, x0 + 20.5, 248, f"{i + 1:02d}", 4.4, (220, 222, 228) if i % 4 == 0 else (110, 114, 124), "mm", "s", 0.04)
        if not valid: r.well((x0, 260, x0 + 41, 327.5), 5, (22, 23, 26), 4)
        else:
            col = a if not evs or max(ev[2] for ev in evs) < 120 else skin.mix_rgb(a, (255, 230, 200), 0.3)
            gpad(r, (x0, 260, x0 + 41, 327.5), bool(evs), col, 5)
            if len(evs) > 1: lab(r, x0 + 20.5, 318, f"x{len(evs)}", 4.6, (255, 255, 255), "mm", "b", 0.04)
        if i == c.step_cursor: d.rounded_rectangle([x0 - 1.5, 258.5, x0 + 42.5, 329], 6, outline=(236, 238, 242), width=1.2)
        on_ = play_i == i
        d.ellipse([x0 + 18.5, 337, x0 + 22.5, 341], fill=(255, 255, 255) if on_ else ((150, 154, 160) if i == c.step_cursor else (70, 74, 82)))
        if i and i % 4 == 0: d.line([x0 - 3.5, 252, x0 - 3.5, 342], fill=(26, 27, 31), width=1)
        r.hit((x0 - 2, 255, x0 + 43, 332), down=lambda *_, i=i: c.step_toggle(i))
    bar = c.step_tick(c.step_cursor) // max(1, sq.bar_ticks) + 1
    lab(r, 21, 354, f"PAGE {c.step_page + 1} OF {pages}   BAR {bar}   STEP {c.step_cursor + 1} / 16   {('1/8', '1/16', '1/32')[res]}"
        + ("   ACCENT ON" if c.step_accent else ""), 4.8, (140, 146, 158), "lm", "s", 0.14)


# =========================================================== MUTE
def mute(r):
    c, e, d = r.c, r.e, r.d
    a = acc(r)
    sq = e.seq
    any_solo = any(t.solo for t in sq.tracks)
    for k in range(8):
        n = c.mute_page * 8 + k
        tr = sq.tracks[n]
        x0 = 10 + k * 98.75; x1 = x0 + 90
        sel = n == e.cur_track
        r.plate((x0, 49, x1, 366), 8)
        if sel: d.rounded_rectangle([x0, 49, x1, 366], 8, outline=(120, 124, 134), width=1)
        used = bool(tr.events) or tr.kind not in ("drum",)
        lab(r, x0 + 9, 60, f"TRK {n + 1:02d}", 4.4, (120, 126, 138), "lm", "s", 0.1)
        r.t(x0 + 9, 75, tr.name[:11], 10.5, True, (236, 238, 242) if tr.events else (100, 104, 114), "lm")
        lvl = min(1.0, e.track_meter[n] * 1.4)
        for s_ in range(24):                                        # the meter
            y = 153 - s_ * 3.9
            on = s_ < lvl * 24
            col = GREEN if s_ < 18 else (YEL if s_ < 22 else RED)
            d.rectangle([x0 + 76, y - 2.6, x0 + 81, y], fill=col if on else (32, 36, 34))
        pend = tr.n in e.pending_mute
        muted = e.pending_mute.get(tr.n, tr.mute)
        on = not tr.mute and (not any_solo or tr.solo)
        gpad(r, (x0 + 9, 169, x0 + 81.5, 274), on and bool(tr.events), a, 6)
        word = ("MUTE NEXT BAR" if muted else "ON NEXT BAR") if pend else ("MUTED" if tr.mute else ("ON" if not any_solo or tr.solo else "SOLOED OUT"))
        if pend and int(time.time() * 4) % 2: d.rounded_rectangle([x0 + 8, 168, x0 + 82.5, 275], 6, outline=a, width=1.5)
        lab(r, x0 + 45.25, 265, word, 4.8, (40, 26, 16) if on and tr.events else (120, 124, 134), "mm", "b", 0.12)
        r.hit((x0 + 9, 169, x0 + 81.5, 274), down=lambda *_, tr=tr: (setattr(e, "cur_track", tr.n), c.mute_toggle(tr)))
        r.con_key((x0 + 9, 285, x0 + 81.5, 317), "SOLO", tr.solo, (240, 200, 60),
                  lambda tr=tr: (setattr(tr, "solo", not tr.solo), setattr(e, "cur_track", tr.n)), 5.2)
        lab(r, x0 + 9, 334, "GROUP", 4.0, (110, 114, 124), "lm", "s", 0.1)
        g = "-ABCD"[tr.mgroup]
        if c.mute_groups:
            d.rounded_rectangle([x0 + 6, 340, x0 + 40, 357], 3, outline=a, width=1)
            r.hit((x0 + 4, 330, x1 - 4, 362), down=lambda *_, tr=tr: setattr(tr, "mgroup", (tr.mgroup + 1) % 5))
        else: r.hit((x0 + 4, 52, x1 - 4, 160), down=lambda *_, n=n: setattr(e, "cur_track", n))
        r.t(x0 + 9, 348.5, g, 12, True, a if tr.mgroup and c.mute_groups else INK, "lm")


# =========================================================== SAMPLE
def sample(r):
    c, e, d = r.c, r.e, r.d
    a = acc(r)
    p = e.pad
    # INPUT meter + ARM key
    r.plate((10, 49, 792, 148), 8)
    lab(r, 21, 61, "INPUT" if e.rec_src == "INPUT" else "RESAMPLE: THE MAIN OUTPUT  -  PRESS PLAY", 5.2, LAB if e.rec_src == "INPUT" else CYAN)
    if e.rec_src == "INPUT" and not e.has_input: lab(r, 650, 61, "NO INPUT DEVICE", 5.0, RED, "rm", "s", 0.14)
    r.glassbox((21, 70, 652, 138), 5)
    mx0, mx1 = 47.5, 635
    dbx = lambda db: mx0 + (mx1 - mx0) * (db + 48) / 48.0
    lv = e.in_meter_lr if e.rec_src == "INPUT" else [e.in_meter, e.in_meter]
    for row, (yy, nm) in enumerate(((89, "L"), (113.5, "R"))):
        lab(r, 30, yy, nm, 4.4, (120, 126, 138), "mm", "s", 0.0)
        val = 20 * math.log10(max(1e-5, lv[row]))
        for k in range(86):
            db = -48 + 48 * k / 85.0
            x = mx0 + (mx1 - mx0) * k / 86.0
            on = db <= val
            col = GREEN if db < -18 else (YEL if db < -3 else RED)
            d.rectangle([x, yy - 6.5, x + 4.6, yy + 6.5], fill=col if on else (26, 30, 30))
    for db in (-48, -36, -24, -12, -6, 0): lab(r, dbx(db), 129, str(db), 3.8, (100, 104, 112), "mm", "s", 0.0)
    th_db = 20 * math.log10(max(1e-4, e.rec_thresh))
    tx = dbx(clamp(th_db, -48, 0))
    d.line([tx, 80, tx, 123], fill=a, width=1.5)
    lab(r, tx, 76, f"THRESHOLD {th_db:.0f} dB", 4.2, a, "mm", "b", 0.08)
    def thr(px, py): e.rec_thresh = round(10 ** (clamp(-48 + 48 * (px - mx0) / (mx1 - mx0), -48, 0) / 20.0), 4)
    r.hit((mx0, 72, mx1, 136), down=thr, drag=thr)
    st = e.rec_state
    lit = st in ("rec", "armed")
    col = RED if st == "rec" else a
    gpad(r, (667.5, 65, 780, 137.5), lit, col, 6)
    if not lit: r.d.rounded_rectangle([667.5, 65, 780, 137.5], 6, outline=(60, 62, 68), width=1)
    d.ellipse([718, 87, 729, 98], fill=(30, 18, 12) if lit else (90, 30, 30))
    word = {"rec": f"REC {e.rec_len / OUT_SR:.1f} S", "armed": "ARMED"}.get(st, "ARM")
    lab(r, 723.75, 112, word, 5.6, (40, 22, 12) if lit else (200, 204, 212), "mm", "b", 0.16)
    r.hit((667.5, 65, 780, 137.5), down=lambda *_: e.rec_toggle())
    # SOURCE / options
    r.plate((10, 157.5, 272.5, 366), 8)
    lab(r, 21, 169.4, "SOURCE", 5.0)
    srcs = ["IN 1+2", "IN 1", "IN 2", "RESAMPLE"]
    cur = 3 if e.rec_src == "RESAMPLE" else {"1-2": 0, "1": 1, "2": 2}.get(e.rec_in, 0)
    def spick(k):
        if k == 3: c.set_rec_src("RESAMPLE")
        else: c.set_rec_src("INPUT"); e.rec_in = ("1-2", "1", "2")[k]
    seg(r, (21, 180, 261, 205), srcs, cur, spick, 4.6)
    lab(r, 21, 219.4, "TAKES", 5.0)
    lab(r, 21, 230, "MONO, 44.1 KHZ, 32-BIT FLOAT", 4.4, (110, 114, 124), "lm", "s", 0.12)
    for k, (nm, on, fn) in enumerate((("MONITOR", e.in_monitor, lambda: setattr(e, "in_monitor", not e.in_monitor)),
                                       ("TRIM", e.rec_trim, lambda: setattr(e, "rec_trim", not e.rec_trim)),
                                       ("NORMALIZE", e.rec_norm, lambda: setattr(e, "rec_norm", not e.rec_norm)))):
        x0 = 21 + k * 65
        toggle_box(r, (x0, 265, x0 + 44, 318.75), nm, on, fn)
    lab(r, 21, 334, "TO PAD", 4.6)
    r.t(21, 348.5, f"{BANKS[e.bank]}{e.sel + 1:02d} ({p.src.name[:16] if p.src else 'empty'})", 11, True, INK, "lm")
    # the take
    r.plate((282.5, 157.5, 792, 366), 8)
    x0, y0, x1, y1 = 291.25, 166, 783.75, 357.5
    d.rounded_rectangle([x0, y0, x1, y1], 4, fill=(26, 15, 7), outline=(60, 40, 22), width=1)
    takes = sum(1 for s in e.sources if s.name.startswith(("rec_", "resample_")))
    nm = e.last_take.name.upper() if (st == "idle" and e.last_take) else f"TAKE {takes + 1:02d}"
    r.mono(x0 + 12, y0 + 18, nm, 19, (255, 168, 80), "lm")
    secs = e.rec_len / OUT_SR if st == "rec" else (e.last_take.length / OUT_SR if e.last_take else 0.0)
    r.mono(x1 - 12, y0 + 18, f"{int(secs // 60):02d}:{secs % 60:05.2f}", 19, (255, 168, 80), "rm")
    cy, hh = (y0 + y1) / 2 + 4, 52
    if st == "rec" and e.rec_peaks:
        pk = e.rec_peaks[-240:]
        pts = [(x0 + 12 + k * (x1 - x0 - 24) / 240.0, v) for k, v in enumerate(pk)]
    elif e.last_take:
        s = e.last_take
        mn, mxv = s.envelope(200, 0, s.length)
        pts = [(x0 + 12 + k * (x1 - x0 - 24) / 200.0, max(-mn[k], mxv[k])) for k in range(len(mn))]
    else: pts = []
    if pts:
        top = [(x, cy - min(1, v) * hh) for x, v in pts]; bot = [(x, cy + min(1, v) * hh) for x, v in pts]
        d.polygon(top + bot[::-1], fill=(120, 66, 28) if st != "rec" else (140, 40, 30))
        d.line(top, fill=(255, 168, 80)); d.line(bot, fill=(255, 168, 80))
    else:
        r.mono((x0 + x1) / 2, cy, "ARM, THEN PLAY SOMETHING" if st == "idle" else "WAITING FOR THE THRESHOLD", 11, (160, 96, 44), "mm")
    pk_db = 20 * math.log10(max(1e-5, max([v for _, v in pts] or [0]))) if pts else None
    r.mono(x0 + 12, y1 - 18, "44.1K MONO" + (f"  PEAK {pk_db:.1f} dB" if pk_db is not None else "")
           + ("   KEEP OR DISCARD (F3 / F4)" if e.last_take and st == "idle" else ""), 10, (220, 130, 56), "lm")
    if e.last_take and st == "idle": r.hit((x0, y0, x1, y1), down=lambda *_: e.trigger(e.pad, 110))


# =========================================================== CHOP
def chop(r):
    c, e, d = r.c, r.e, r.d
    a = acc(r)
    p, s = e.pad, c.src                                                    # CHOP's own sample (not the pad's)
    r.plate((10, 49, 792, 255), 8)
    gx0, gy0, gx1, gy1 = 18, 56, 784.5, 247
    d.rounded_rectangle([gx0, gy0, gx1, gy1], 5, fill=(11, 12, 15))
    if s is None:
        lab(r, 27.5, 66.5, "NO SAMPLE IN THE PROJECT YET", 5.0)
        r.t(400, 150, "record one (SAMPLE) or load one (BROWSE)", 12, False, INK2, "mm"); return
    regs = s.regions()
    A, B = int(c.chop_v0 * s.length), max(int(c.chop_v1 * s.length), int(c.chop_v0 * s.length) + 64)
    secs = s.length / OUT_SR
    beats = secs * e.seq.bpm / 60.0
    # the sample being chopped: < NAME > steps through the project's samples (newest first: SHIFT + < > too)
    r.keycap((18, 59, 34, 74), "up", 3); r.t(26, 66.5, "<", 9, True, (226, 230, 236), "mm")
    r.hit((14, 57, 38, 76), down=lambda *_: c.chop_pick(-1))
    nm = s.name.upper()[:22]
    lab(r, 42, 66.5, nm, 5.4, (240, 242, 246), "lm", "s", 0.1)
    nx = 42 + max(60, len(nm) * 7.2)
    r.keycap((nx, 59, nx + 16, 74), "up", 3); r.t(nx + 8, 66.5, ">", 9, True, (226, 230, 236), "mm")
    r.hit((nx - 4, 57, nx + 20, 76), down=lambda *_: c.chop_pick(1))
    lab(r, nx + 26, 66.5, f"{secs:.2f} S   ~{beats / e.seq.num:.1f} BARS AT {e.seq.bpm:.0f} BPM", 4.6, (150, 154, 162))
    lab(r, 700, 66.5, f"{len(regs)} SLICES   {('EQUAL', 'TRANSIENT', 'BEATS', 'MANUAL')[c.chop_mode]}", 4.6, (120, 124, 132), "rm", "s", 0.12)
    px0, px1, py0, py1 = 30, 772.5, 82.5, 226
    W = int(px1 - px0)
    X = lambda pos: px0 + (pos - A) / float(B - A) * W
    cur_k = c.chop_k()
    ra, rb = regs[cur_k]
    if X(rb) > px0 and X(ra) < px1: d.rectangle([max(px0, X(ra)), py0, min(px1, X(rb)), py1], fill=mix((11, 12, 15), a, 0.14))
    # parts of the sample no slice plays (trimmed off): hatched darker
    cov = sorted(regs); gaps, edge = [], 0
    for ga, gb in cov:
        if ga > edge: gaps.append((edge, ga))
        edge = max(edge, gb)
    if edge < s.length: gaps.append((edge, s.length))
    mn, mxv = s.envelope(W, A, B)
    cy, hh = (py0 + py1) / 2, (py1 - py0) / 2 - 2
    top = [(px0 + i, cy - mxv[i] * hh) for i in range(len(mn))]; bot = [(px0 + i, cy - mn[i] * hh) for i in range(len(mn))]
    d.polygon(top + bot[::-1], fill=mix((11, 12, 15), a, 0.28))
    d.line(top, fill=a); d.line(bot, fill=a)
    for ga, gb in gaps:
        if gb < A or ga > B: continue
        gx_a, gx_b = max(px0, X(ga)), min(px1, X(gb))
        if gx_b - gx_a < 1: continue
        ov = skin.cached(("chopgap", r.P(gx_b - gx_a), r.P(py1 - py0)), lambda: Image.new("RGBA", (max(1, r.P(gx_b - gx_a)), r.P(py1 - py0)), (6, 7, 9, 170)))
        r.img.paste(ov, (r.P(gx_a), r.P(py0)), ov)
    # the selected slice: START and END handles (drag them; Q2 / Q3 turn them)
    for edge_, lbl in ((ra, "S"), (rb, "E")):
        if A <= edge_ <= B:
            hx = X(edge_)
            d.line([hx, py0, hx, py1], fill=YEL, width=2)
            fx0 = hx if lbl == "S" else hx - 11
            d.rounded_rectangle([fx0, py0, fx0 + 11, py0 + 10], 2, fill=YEL)
            lab(r, fx0 + 5.5, py0 + 5, lbl, 4.4, (20, 20, 22), "mm", "b", 0.0)
    for k, (ra_, rb_) in enumerate(regs):
        if rb_ < A or ra_ > B: continue
        x = X(ra_)
        if px0 <= x <= px1 and k != cur_k: d.line([x, py0, x, py1], fill=(150, 152, 158), width=1)
        xl = max(px0, x)
        if X(rb_) - xl >= 14:
            on = k == cur_k
            r.d.rounded_rectangle([xl, 229, xl + 15, 240], 2, fill=a if on else (50, 52, 58))
            lab(r, xl + 7.5, 234.5, str(k + 1), 4.6, (255, 255, 255) if on else (200, 204, 212), "mm", "b", 0.0)
    if A <= c.chop_cursor <= B:                                           # the cursor: where SPLIT cuts
        cx_ = X(c.chop_cursor)
        for yy in range(int(py0), int(py1), 6): d.line([cx_, yy, cx_, min(py1, yy + 3)], fill=(240, 240, 242), width=1)
    ph = e.playhead(p)
    if ph is not None and A <= ph <= B: d.line([X(ph), py0, X(ph), py1], fill=(255, 255, 255))
    def cdown(px, py):
        pos = int(clamp(A + (px - px0) / float(W) * (B - A), 0, s.length - 1))
        c._chop_edge_drag = None
        grab = (B - A) * 9 / float(W)                                     # within 9 units of a handle: drag that edge
        sa, sb = s.regions()[c.chop_k()]
        if abs(pos - sa) <= grab and abs(pos - sa) <= abs(pos - sb): c._chop_edge_drag = 0
        elif abs(pos - sb) <= grab: c._chop_edge_drag = 1
        c.chop_cursor = pos
        if c._chop_edge_drag is None:                                     # a tap: select the slice there and hear it
            c.chop_sel = e.slice_at(s, pos, c.chop_k()); c.chop_audition()
    def cdrag(px, py):
        pos = int(clamp(A + (px - px0) / float(W) * (B - A), 0, s.length))
        k = c.chop_k()
        if getattr(c, "_chop_edge_drag", None) == 0: e.set_slice_edge(s, k, start=pos)
        elif getattr(c, "_chop_edge_drag", None) == 1: e.set_slice_edge(s, k, end=pos)
        c.chop_cursor = min(pos, s.length - 1)
    r.hit((px0, py0 - 10, px1, py1), down=cdown, drag=cdrag)
    # SLICES TO PADS
    r.plate((10, 264, 485, 366), 8)
    lab(r, 21, 276, "SLICES  (PADS OR < > PLAY THEM, F4 CONVERT)" + (f"   {cur_k + 1} OF {len(regs)}" if len(regs) > 8 else ""), 5.0)
    k0 = max(0, min(cur_k - 3, len(regs) - 8))
    for j in range(8):
        k = k0 + j
        x0 = 21.25 + j * 57.5
        if k >= len(regs): r.well((x0, 287.5, x0 + 51, 354), 5, (22, 23, 26), 4); continue
        on = k == cur_k
        gpad(r, (x0, 287.5, x0 + 51, 354), on, a, 5)
        if not on: d.rounded_rectangle([x0, 287.5, x0 + 51, 354], 5, outline=(60, 62, 68), width=1)
        linked = [q for q in e.prog.pads if q.link and q.link[0] == s.id and q.link[1] == k]
        tag = f"{BANKS[linked[0].idx // 16]}{linked[0].idx % 16 + 1:02d}" if linked else "-"
        r.t(x0 + 25.5, 316, str(k + 1), 14, True, (255, 255, 255) if on else (220, 224, 232), "mm")
        lab(r, x0 + 25.5, 330, tag, 4.4, (255, 236, 220) if on else (130, 136, 148), "mm", "s", 0.06)
        def tap(*_, k=k): c.chop_select(k)
        r.hit((x0, 287.5, x0 + 51, 354), down=tap)
    # DETECT
    r.plate((495, 264, 792, 366), 8)
    lab(r, 506, 276, "DETECT", 5.0)
    names = ["TRANSIENT", "EQUAL", "BEATS", "MANUAL"]
    order = [1, 0, 2, 3]
    seg(r, (506, 284, 781, 305), names, order.index(c.chop_mode), lambda k: c.chop_set_mode(order[k]), 4.4)
    toggle_box(r, (506, 309, 550, 362), "SNAP", c.chop_snap, lambda: setattr(c, "chop_snap", not c.chop_snap))
    toggle_box(r, (562.5, 309, 606.5, 362), "FADE", c.chop_fade, lambda: setattr(c, "chop_fade", not c.chop_fade))
    lab(r, 625, 323, f"SLICE {cur_k + 1}   Q2 START  Q3 END", 4.6, (130, 136, 148), "lm", "s", 0.12)
    r.t(625, 339, f"{ra / OUT_SR:.2f} - {rb / OUT_SR:.2f}", 14, True, INK, "lm")
    lab(r, 625, 354, f"{rb - ra} SMP", 4.2, (110, 114, 124), "lm", "s", 0.12)
    if c.chop_mode == 2:
        r.btn((735, 312, 781, 328), f"1/{c.chop_div}", lambda: (setattr(c, "chop_div", {4: 8, 8: 16, 16: 4}.get(c.chop_div, 8)), c.chop_run(True)), 9)
    armed = c.clear_armed()
    r.con_key((737, 338, 781, 354), "SURE?" if armed else "CLEAR", armed, RED, c.chop_clear, 4.6)


# =========================================================== SONG
def song(r):
    c, e, d = r.c, r.e, r.d
    a = acc(r)
    rows = e.song
    r.well((10, 49, 522.5, 366), 8, (20, 21, 25), 7)
    for x, t in ((38.75, "STEP"), (70, "SEQUENCE"), (262.5, "BARS"), (478.75, "REPEATS")): lab(r, x, 62.5, t, 4.4, (110, 114, 124), "lm", "s", 0.12)
    live_ = e.playing and e.song_mode
    top = clamp(c.song_cur - 3, 0, max(0, len(rows) + 1 - 8))
    for k in range(8):
        i = top + k
        y0 = 72.5 + k * 36.25
        if i > len(rows): break
        if i == len(rows):
            r.keycap((19, y0, 513.75, y0 + 30), "up", 5)
            r.ledp(30.5, y0 + 15, 3.0, False)
            lab(r, 47, y0 + 15, f"{i + 1:02d}", 6.6, (100, 104, 114), "mm", "b", 0.0)
            r.t(70, y0 + 15, "END", 11, True, (110, 114, 124), "lm")
            r.hit((19, y0, 513.75, y0 + 30), down=lambda *_: c.soft(0))
            continue
        si, reps = rows[i]
        sq = e.seqs[si]
        sel = i == c.song_cur
        live = live_ and e.song_pos == i
        r.keycap((19, y0, 513.75, y0 + 30), "up", 5)
        if sel: d.rounded_rectangle([19, y0, 513.75, y0 + 30], 5, outline=mix(a, (0, 0, 0), 0.3), width=1)
        r.ledp(30.5, y0 + 15, 3.0, live or sel, GREEN if live else a)
        lab(r, 47, y0 + 15, f"{i + 1:02d}", 6.6, a if sel else (130, 136, 148), "mm", "b", 0.0)
        r.t(70, y0 + 15, f"{si + 1:02d} {sq.name}"[:22], 11, True, INK if sel else (214, 218, 226), "lm")
        nb = min(sq.bars, 6)
        for b in range(nb):
            bx = 262.5 + b * 28.75
            played = live and b < (e.pos / max(1, sq.bar_ticks)) and e.song_rep >= 0
            col = a if (sel and b == 0) or played else ((120, 74, 46) if sel else (88, 92, 102))
            d.rounded_rectangle([bx, y0 + 11, bx + 25, y0 + 19], 1.5, fill=col)
        if sq.bars > 6: lab(r, 262.5 + 6 * 28.75 - 2, y0 + 15, f"+{sq.bars - 6}", 4.4, (130, 136, 148), "lm", "s", 0.0)
        r.btn((440, y0 + 6, 458, y0 + 24), "-", lambda i=i: rows[i].__setitem__(1, max(1, rows[i][1] - 1)), 10, grow=2)
        r.t(478, y0 + 15, f"x{reps}", 12, True, INK, "mm")
        r.btn((495, y0 + 6, 511, y0 + 24), "+", lambda i=i: rows[i].__setitem__(1, min(16, rows[i][1] + 1)), 10, grow=2)
        r.hit((19, y0, 436, y0 + 30), down=lambda *_, i=i: setattr(c, "song_cur", i))
    # SEQUENCES: tap = this step plays it
    r.plate((532.5, 49, 792, 255), 8)
    cur_si = rows[c.song_cur][0] if rows else e.cur_seq
    base = (cur_si // 8) * 8
    lab(r, 543.75, 61, f"SEQUENCES {base + 1}-{base + 8}", 5.0)
    r.btn((742, 54, 760, 68), "<", lambda: rows[c.song_cur].__setitem__(0, max(0, ((rows[c.song_cur][0] // 8) - 1) * 8)) if rows else None, 8, grow=2)
    r.btn((764, 54, 782, 68), ">", lambda: rows[c.song_cur].__setitem__(0, min(NSEQ - 1, ((rows[c.song_cur][0] // 8) + 1) * 8)) if rows else None, 8, grow=2)
    for k in range(8):
        si = base + k
        if si >= NSEQ: break
        x0 = 544 + (k % 4) * 61.25; y0 = 72.5 + (k // 4) * 82.5
        sq = e.seqs[si]
        used = any(t.events for t in sq.tracks)
        on = si == cur_si
        gpad(r, (x0, y0, x0 + 55, y0 + 74), on, a, 6)
        r.t(x0 + 27.5, y0 + 33, f"{si + 1:02d}", 15, True, (255, 255, 255) if on else (226, 230, 236) if used else (120, 126, 138), "mm")
        lab(r, x0 + 27.5, y0 + 49, sq.name[:9] if used else "empty", 4.4, (255, 236, 220) if on else (130, 136, 148), "mm", "s", 0.02)
        r.hit((x0, y0, x0 + 55, y0 + 74), down=lambda *_, si=si: rows[c.song_cur].__setitem__(0, si) if rows else None)
    # the amber display
    r.plate((532.5, 264, 792, 366), 8)
    x0, y0, x1, y1 = 541.25, 272.5, 783.75, 357.5
    d.rounded_rectangle([x0, y0, x1, y1], 4, fill=(26, 15, 7), outline=(60, 40, 22), width=1)
    tot = sum(e.seqs[si].bars * reps * e.seqs[si].num * 60.0 / max(1.0, e.seqs[si].bpm) for si, reps in rows)
    if rows:
        si, reps = rows[c.song_cur if not live_ else e.song_pos]
        n_ = (e.song_pos if live_ else c.song_cur) + 1
        done = 0.0
        if live_:
            done = sum(e.seqs[s_].bars * rp * e.seqs[s_].num * 60.0 / max(1.0, e.seqs[s_].bpm) for s_, rp in rows[:e.song_pos])
            done += (e.song_rep * e.seq.bars * e.seq.num + max(0.0, e.pos) / max(1, e.seq.beat_ticks)) * 60.0 / max(1.0, e.seq.bpm)
        rep = (e.song_rep + 1) if live_ else 1
        r.mono(x0 + 12, y0 + 18, f"STEP {n_:02d} {e.seqs[si].name.upper()}"[:20], 17, (255, 168, 80), "lm")
        r.mono(x0 + 12, y0 + 41, f"REPEAT {rep} OF {reps}", 13, (255, 168, 80), "lm")
        f = lambda t: f"{int(t // 60):02d}:{int(t % 60):02d}"
        r.mono(x0 + 12, y0 + 64, f"SONG {f(done)} / {f(tot)}", 13, (220, 130, 56), "lm")


# =========================================================== BROWSE (+ IMPORT)
def browse(r):
    c, e, d = r.c, r.e, r.d
    a = acc(r)
    # DRIVES / PLACES
    r.plate((10, 49, 188.75, 366), 8)
    lab(r, 21, 61, "DRIVES", 5.0)
    drives = getattr(c, "_drives", None)
    if drives is None:
        try: c.br_places()
        except Exception: c._drives = []
        drives = getattr(c, "_drives", [])
    for k in range(2):
        y0 = 69 + k * 64
        d.rounded_rectangle([19, y0, 180, y0 + 57], 5, fill=(20, 21, 24), outline=(44, 46, 52), width=1)
        lab(r, 27, y0 + 8, "USB", 4.0, (110, 114, 124), "lm", "s", 0.1)
        if k < len(drives):
            label, dev, mp, fs = drives[k]
            r.ledp(169, y0 + 8, 3.4, bool(mp), GREEN)
            d.rounded_rectangle([27, y0 + 18, 172, y0 + 27], 1.5, fill=(8, 8, 9))
            d.rounded_rectangle([38, y0 + 15.5, 161, y0 + 29.5], 1.5, fill=(230, 226, 214))
            lab(r, 99.5, y0 + 22.5, label.upper()[:16], 4.2, (40, 40, 44), "mm", "b", 0.08)
            r.t(27, y0 + 44, ("mounted" if mp else "tap to mount") + f"  {fs}", 9, False, (160, 166, 178), "lm")
            path = mp if mp else ("mount", dev, label, fs)
            def open_drive(*_, path=path):
                if isinstance(path, tuple):
                    mp_ = c.usb_mount(path[1], path[2], path[3])
                    if mp_: c.br_dir, c.br_cur = mp_, 0; c.br_refresh()
                else: c.br_dir, c.br_cur = path, 0; c.br_refresh()
            r.hit((19, y0, 180, y0 + 57), down=open_drive)
        else:
            r.ledp(169, y0 + 8, 3.4, False)
            d.rounded_rectangle([27, y0 + 18, 172, y0 + 27], 1.5, fill=(8, 8, 9))
            r.t(27, y0 + 44, "empty", 9, False, (110, 114, 124), "lm")
    lab(r, 21, 202, "PLACES", 5.0)
    places = [("PROJECT", "samples", e.sample_dir), ("TRACK OUTS", "this project", os.path.join(e.dir, "exports")),
              ("HOME", "folder", os.path.expanduser("~"))]
    for k, (nm, sub, path) in enumerate(places):
        y0 = 211 + k * 32.5
        here = c.br_dir is not None and (c.br_dir == path or c.br_dir.startswith(path + "/"))
        r.keycap((19, y0, 180, y0 + 27), "lit" if here else "up", 4)
        lab(r, 99.5, y0 + 9.5, nm, 5.0, (255, 255, 255) if here else (226, 230, 236), "mm", "b", 0.1)
        lab(r, 99.5, y0 + 19, sub, 4.0, (255, 236, 220) if here else (130, 136, 148), "mm", "s", 0.04)
        def go(*_, path=path):
            if os.path.isdir(path): c.br_dir, c.br_cur = path, 0; c.br_refresh()
            else: c.say("not there yet (nothing exported)")
        r.hit((19, y0, 180, y0 + 27), down=go)
    drv = c._br_drive()
    r.keycap((19, 315, 180, 354), "up", 5)
    lab(r, 99.5, 329, "EJECT USB", 5.2, (226, 230, 236) if drv else (100, 104, 114), "mm", "b", 0.1)
    lab(r, 99.5, 341, "safe to pull when the LED is off", 3.8, (130, 136, 148), "mm", "s", 0.02)
    r.hit((19, 315, 180, 354), down=lambda *_: c.soft(2))
    # the amber list
    r.plate((198.75, 49, 547.5, 328), 8)
    x0, y0, x1, y1 = 205, 56, 541, 321
    d.rounded_rectangle([x0, y0, x1, y1], 5, fill=(26, 15, 7), outline=(60, 40, 22), width=1)
    where = "PLACES" if c.br_dir is None else c.br_dir
    pretty = where.replace(os.path.expanduser("~"), "~").strip("/").upper().replace("/", " / ")
    r.mono(x0 + 10, y0 + 13, pretty[-26:], 13, (255, 168, 80), "lm")
    r.mono(x1 - 10, y0 + 13, f"{len(c.br_items)} ITEMS", 10, (200, 120, 52), "rm")
    d.line([x0 + 8, y0 + 24, x1 - 8, y0 + 24], fill=(90, 56, 26))
    RH, rows = 21.2, 11
    top = clamp(c.br_cur - 5, 0, max(0, len(c.br_items) - rows))
    if not c.br_items: r.mono((x0 + x1) / 2, 180, "NO AUDIO FILES HERE", 11, (160, 96, 44), "mm")
    for k in range(rows):
        i = top + k
        if i >= len(c.br_items): break
        name, path, isdir = c.br_items[i]
        y = y0 + 37 + k * RH
        sel = i == c.br_cur
        if sel: d.rectangle([x0 + 6, y - 9.5, x1 - 6, y + 9.5], fill=(255, 168, 80))
        ink = (40, 20, 6) if sel else (255, 168, 80)
        mpc = bool(path) and not isdir and path.lower().endswith(c.MPC_EXT)
        icon = "▸" if isdir else ("■" if mpc else "∿")
        r.mono(x0 + 12, y, icon, 11, ink, "lm")
        nm = name if len(name) <= 24 else name[:23] + "…"
        r.mono(x0 + 26, y, nm, 11, ink, "lm")
        if mpc:
            tag = {".xpj": "MPC 2.X", ".all": "MPC2000XL", ".aps": "MPC2000XL", ".pgm": "MPC2000XL"}.get(os.path.splitext(path)[1].lower(), "MPC")
            d.rounded_rectangle([x1 - 92, y - 5, x1 - 46, y + 5], 2, fill=(255, 168, 80) if not sel else (40, 20, 6))
            lab(r, x1 - 69, y, tag, 3.6, (40, 20, 6) if not sel else (255, 168, 80), "mm", "b", 0.04)
        elif not isdir and path:
            inf = c.br_info(path)
            if inf: r.mono(x1 - 10, y, f"{inf[0]:.2f} s {inf[1] / 1000:g}k {inf[2] or ''}"[:18], 10, ink, "rm")
        elif isdir and path and not isinstance(path, tuple) and c.br_dir is not None:
            try: n_ = len([f for f in os.listdir(path) if not f.startswith(".")]); r.mono(x1 - 10, y, f"{n_} items", 10, ink, "rm")
            except OSError: pass
        r.hit((x0, y - 10, x1, y + 10), down=lambda *_, i=i: c.br_open(i))
    if len(c.br_items) > rows:
        h = max(12, (y1 - y0 - 40) * rows / len(c.br_items)); yy = y0 + 30 + (y1 - y0 - 40 - h) * top / max(1, len(c.br_items) - rows)
        d.rounded_rectangle([x1 - 4, yy, x1 - 2, yy + h], 1, fill=(160, 96, 44))
    seg(r, (198.75, 336, 368, 362), ["ALL", "AUDIO", "PROJECTS"], ["ALL", "AUDIO", "PROJECTS"].index(c.br_filter),
        lambda k: (setattr(c, "br_filter", ("ALL", "AUDIO", "PROJECTS")[k]), c.br_refresh()), 4.6)
    seg(r, (378.75, 336, 547.5, 362), ["NAME", "DATE", "SIZE"], ["NAME", "DATE", "SIZE"].index(c.br_sort),
        lambda k: (setattr(c, "br_sort", ("NAME", "DATE", "SIZE")[k]), c.br_refresh()), 4.6)
    # PREVIEW
    r.plate((556.25, 49, 792, 366), 8)
    lab(r, 567.5, 61, "PREVIEW", 5.0)
    it = c.br_items[c.br_cur] if c.br_items else None
    path = it[1] if it and not it[2] and isinstance(it[1], str) else None
    wx0, wy0, wx1, wy1 = 565, 70, 783.75, 151
    r.glassbox((wx0, wy0, wx1, wy1), 5)
    audio = path and path.lower().endswith(c.AUDIO_EXT)
    if audio:
        pk = c.br_peaks(path)
        if pk:
            mn, mxv = pk; n = len(mn); cy, hh = (wy0 + wy1) / 2, (wy1 - wy0) / 2 - 5
            top_ = [(wx0 + 8 + k * (wx1 - wx0 - 16) / n, cy - mxv[k] * hh) for k in range(n)]
            bot_ = [(wx0 + 8 + k * (wx1 - wx0 - 16) / n, cy - mn[k] * hh) for k in range(n)]
            d.polygon(top_ + bot_[::-1], fill=mix((12, 13, 16), a, 0.28)); d.line(top_, fill=a); d.line(bot_, fill=a)
    r.t(567.5, 163, (it[0] if it else "")[:26], 10.5, True, INK, "lm")
    if audio:
        inf = c.br_info(path)
        if inf:
            secs, sr, bits, ch = inf
            bpm = None
            for bars in (1, 2, 4, 8):                                 # a loop length that makes a likely tempo
                b_ = bars * 4 * 60.0 / max(0.01, secs)
                if 70 <= b_ <= 180: bpm = b_; break
            for k, (nm, val) in enumerate((("LENGTH", f"{secs:.2f} s"), ("RATE", f"{sr / 1000:g} kHz"), ("BITS", str(bits or "-")),
                                           ("TEMPO", f"≈ {bpm:.0f} bpm" if bpm else "-"))):
                xx = 567.5 + (k % 2) * 110; yy = 178 + (k // 2) * 26
                lab(r, xx, yy, nm, 4.0, (110, 114, 124), "lm", "s", 0.12)
                r.t(xx, yy + 11, val, 10.5, True, INK, "lm")
        lab(r, 567.5, 234, "LOAD TO", 4.6)
        seg(r, (565, 242, 783.75, 266), [f"PAD {BANKS[e.bank]}{e.sel + 1:02d}", "CHOP"], 0 if c.br_to == "PAD" else 1,
            lambda k: setattr(c, "br_to", ("PAD", "CHOP")[k]), 4.4)
        lab(r, 567.5, 276, "converted to 44.1 kHz when loaded", 3.8, (110, 114, 124), "lm", "s", 0.04)
    elif path and path.lower().endswith(c.MPC_EXT):
        import textwrap
        for k, line in enumerate(textwrap.wrap(c.br_msg or "an MPC project", 34)[:6]): r.t(567.5, 184 + k * 15, line, 9.5, False, (200, 204, 212), "lm")
    else:
        for k, line in enumerate(("tap a folder to open it", "tap a file to hear it,", "tap it again to load it",
                                  "files are copied into the", "project when it is saved")):
            r.t(567.5, 184 + k * 15, line, 9.5, False, (150, 156, 168), "lm")
    r.keycap((565, 294, 670, 357.5), "up", 6)
    r.ledp(660, 302, 3.4, c.br_audition, GREEN)
    lab(r, 617.5, 318, "AUDITION", 5.4, (226, 230, 236), "mm", "b", 0.12)
    lab(r, 617.5, 331, "plays as you tap", 3.8, (130, 136, 148), "mm", "s", 0.02)
    r.hit((565, 294, 670, 357.5), down=lambda *_: setattr(c, "br_audition", not c.br_audition))
    can = bool(path)
    gpad(r, (677.5, 294, 783.75, 357.5), can, a, 6)
    if not can: d.rounded_rectangle([677.5, 294, 783.75, 357.5], 6, outline=(60, 62, 68), width=1)
    mpc = can and path.lower().endswith(c.MPC_EXT)
    lab(r, 730.6, 318, "IMPORT" if mpc else "LOAD", 6.0, (40, 22, 12) if can else (110, 114, 124), "mm", "b", 0.16)
    lab(r, 730.6, 331, "into this project" if mpc else (f"to pad {BANKS[e.bank]}{e.sel + 1:02d}" if c.br_to == "PAD" else "then chop it"), 3.8,
        (60, 36, 20) if can else (110, 114, 124), "mm", "s", 0.02)
    if can: r.hit((677.5, 294, 783.75, 357.5), down=lambda *_: c.br_load())
    if c.br_import: import_window(r)


def import_window(r):
    """IMPORT: what is in the MPC project, where it goes, CANCEL / IMPORT"""
    c, e, d = r.c, r.e, r.d
    a = acc(r)
    from PIL import Image
    shade = skin.cached(("shade", r.img.width, r.P(372)), lambda: Image.new("RGBA", (r.img.width, r.P(372)), (6, 7, 9, 150)))
    r.img.paste(shade, (0, 0), shade)
    r.hit((0, 0, 800, 372), down=lambda *_: None)
    x0, y0, x1, y1 = 44, 57.5, 756, 366
    sp = skin.body(r.P(x1 - x0), r.P(y1 - y0), r.P(8), (44, 46, 52), (34, 36, 41), 0.08, 0.2, (24, 0.7))
    r.put(sp[0], x0, y0, sp[1], sp[2])
    path = c.br_import
    ext = os.path.splitext(path)[1].lower()
    kind = {".xpj": "MPC 2.X", ".sp12": "SP-1200"}.get(ext, "MPC2000XL")
    lab(r, 61, 75, "IMPORT", 6.6, INK, "lm", "b", 0.24)
    tw = r.d.textlength(kind, font=font(8, True)) * 0.8 + 14
    d.rounded_rectangle([131, 69, 131 + tw, 81], 2, fill=a)
    lab(r, 131 + tw / 2, 75, kind, 4.6, (40, 22, 12), "mm", "b", 0.06)
    r.t(131 + tw + 8, 75, os.path.basename(path)[:28], 11, True, INK, "lm")
    lab(r, 306, 75, os.path.dirname(path).replace(os.path.expanduser("~"), "~").upper()[-34:], 4.6, (130, 136, 148), "lm", "s", 0.06)
    # what is in it
    d.rounded_rectangle([61, 92.5, 528, 280], 5, fill=(22, 23, 27), outline=(48, 50, 56), width=1)
    lab(r, 71, 104, "WHAT IS IN IT", 4.6, (130, 136, 148), "lm", "s", 0.14)
    import textwrap
    desc = (c.br_msg or "").split(". Tap again")[0]
    for k, line in enumerate(textwrap.wrap(desc or "an MPC project", 62)[:9]): r.t(71, 122 + k * 16, line, 10.5, k == 0, INK if k == 0 else (200, 204, 212), "lm")
    # where it goes
    d.rounded_rectangle([537.5, 92.5, 739, 280], 5, fill=(22, 23, 27), outline=(48, 50, 56), width=1)
    lab(r, 547.5, 104, "INTO THIS PROJECT", 4.6, (130, 136, 148), "lm", "s", 0.14)
    seg(r, (545, 113, 731, 133), ["REPLACE"], 0, lambda k: None, 4.6)
    for k, (h, v, col) in enumerate((("PROGRAMS, SEQUENCES, SONG", "replace the ones here", INK),
                                     ("THIS PROJECT", "kept in backups/ first", INK),
                                     ("ADD (KEEP WHAT IS HERE)", "not built yet", YEL),
                                     ("REPORT", "mpc_import_report.txt", INK))):
        yy = 148 + k * 31
        lab(r, 547.5, yy, h, 3.8, (110, 114, 124), "lm", "s", 0.1)
        r.t(547.5, yy + 11, v, 9.5, False, col, "lm")
    r.t(61, 298, "REPLACE keeps the current project in backups/ - copy it back to undo.", 9.5, False, (176, 182, 194), "lm")
    r.t(61, 312, "Anything that could not come across is listed in mpc_import_report.txt.", 9.5, False, (130, 136, 148), "lm")
    r.con_key((537.5, 315, 625, 350), "CANCEL", False, None, lambda: setattr(c, "br_import", None), 6.0)
    def go():
        p_, c.br_import = c.br_import, None; c.import_mpc(p_)
    gpad(r, (634, 315, 739, 350), True, a, 6)
    lab(r, 686.5, 327, "IMPORT", 6.0, (40, 22, 12), "mm", "b", 0.16)
    lab(r, 686.5, 340, "replace this project", 3.8, (60, 36, 20), "mm", "s", 0.02)
    r.hit((634, 315, 739, 350), down=lambda *_: go())
