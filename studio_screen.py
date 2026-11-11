"""studio_screen.py - what Monolith shows on the MPC Studio (mk1)'s own screen, and how it gets there.

The screen (from the Studio's v1.10 firmware): 360 x 96 dots, 4 grey levels, rows of 120 bytes - three dots a byte,
two bits each (bits 5-4, 3-2, 1-0; 3 = fully lit). One SysEx message draws one row, or part of one, on USB-MIDI port 0:

    F0 47 7F 13 04  len(2)  width(2)  x(2)  y(2)  <width/3 bytes>  F7        every 2-byte number = high 7 bits, low 7 bits
                    len = 6 + width/3 (the bytes between it and F7); x + width <= 360, y < 96

Only rows that changed are sent, so a still screen costs nothing.

What it shows: on MAIN with a classic machine chosen, that machine's own display, dot for dot (the Studio's blue screen
with white dots is close to the MPC60's); everywhere else a Monolith screen - the page, sequence, bar, tempo, any status
message, and the four Q-links' names and values."""
import time
import numpy as np
from PIL import Image

W, H = 360, 96
LEN_BYTES = W // 3


def row_msg(y, row, x=0):
    """one row (bytes of 3 dots) as the Studio's screen message"""
    n = len(row) * 3
    ln = 6 + len(row)
    hdr = [0xF0, 0x47, 0x7F, 0x13, 0x04, ln >> 7, ln & 0x7F, n >> 7, n & 0x7F, x >> 7, x & 0x7F, y >> 7, y & 0x7F]
    return bytes(hdr) + bytes(row) + b"\xF7"


def pack(img):
    """an L image 360 x 96 (0..255) -> 96 rows of 120 bytes (2-bit dots, three a byte)"""
    a = np.asarray(img.convert("L"), np.uint16)
    lv = np.clip((a + 42) // 85, 0, 3).astype(np.uint8)                   # 0, 85, 170, 255 -> levels 0-3
    lv = lv.reshape(H, LEN_BYTES, 3)
    b = (lv[:, :, 0] << 4) | (lv[:, :, 1] << 2) | lv[:, :, 2]
    return [bytes(r) for r in b]


# ------------------------------------------------------------------ drawing in the LCD's own 6 x 9 dot font
def text(a, x, y, s, k=1, level=255, maxw=None):
    """draw s into the numpy image a at (x, y), each font dot k x k; returns the width drawn"""
    import lcd
    cx = x
    for ch in s:
        if maxw is not None and cx + lcd.CW * k > x + maxw: break
        g = lcd.glyph(ch)
        if k > 1: g = np.repeat(np.repeat(g, k, 0), k, 1)
        h, w = g.shape
        y0, y1, x0, x1 = max(0, y), min(H, y + h), max(0, cx), min(W, cx + w)
        if y1 > y0 and x1 > x0:
            sub = g[y0 - y:y1 - y, x0 - cx:x1 - cx]
            a[y0:y1, x0:x1][sub] = level
        cx += lcd.CW * k
    return cx - x


def tw(s, k=1):
    import lcd
    return len(s) * lcd.CW * k


def _lcd(scr, c, k, cells, ghost=85, row_h=None, gap=False):
    """a machine's characters as an L image k dots per dot; cells = each character's 5 x 8 box shows faintly (ghost)"""
    import lcd
    st = lcd.Style((0, 0, 0), (255, 255, 255), (ghost,) * 3 if cells else (0, 0, 0), cells=cells, row_h=row_h or lcd.CH, gap=gap)
    cur = next(((r, col, n) for key, r, col, n in scr.fields if key == c.lcd_cur), None) if not scr.legends else None
    return lcd.render(scr.text(), scr.cols, st, k, inverse=scr.inverse, cursor=cur).convert("L")


def box(a, x0, y0, x1, y1, level):
    a[y0, x0:x1 + 1] = level; a[y1, x0:x1 + 1] = level; a[y0:y1 + 1, x0] = level; a[y0:y1 + 1, x1] = level


def sp_frame(e, c, scr):
    """SP-1200: its 16 x 2 LCD with the character cells showing (as on the real one), the E-mu name plate beside it, and
    the eight sliders under it - each pad's tune as the slider's position, its hits lighting the strip beside it"""
    from engine import SP_TUNE
    a = np.zeros((H, W), np.uint8)
    img = np.asarray(_lcd(scr, c, 2, True))
    h, w = img.shape
    a[5:5 + h, 6:6 + w] = img
    box(a, 2, 1, 6 + w + 3, 5 + h + 3, 170)
    x0 = 6 + w + 14
    text(a, x0, 3, "E-mu Systems", 1, 170)
    text(a, x0, 15, "SP 1200", 2, 255)
    text(a, x0, 36, f"12 BIT  BANK {'ABCD'[e.bank]}", 1, 170)
    a[48, :] = 85
    text(a, 4, 52, "TUNE", 1, 170)
    text(a, 4, 62, "1-8", 1, 85)
    base = e.bank * 16 + (8 if e.sel >= 8 else 0)
    for i in range(8):
        pad = e.prog.pads[base + i]
        cx = 54 + i * 38
        sel = base + i == e.pad_idx
        a[53:91, cx] = 85; a[53:91, cx + 1] = 85                          # the slot
        for t in range(55, 91, 6): a[t, cx - 4:cx - 2] = 85                 # its scale
        f = (pad.tune - SP_TUNE[0]) / float(SP_TUNE[1] - SP_TUNE[0]) if not pad.empty else 0.5
        cy = int(89 - 34 * max(0.0, min(1.0, f)))
        a[cy - 2:cy + 3, cx - 6:cx + 8] = 255 if sel else 170              # the cap
        a[cy, cx - 6:cx + 8] = 0
        m = min(1.0, pad.meter * 1.6) if not pad.empty else 0.0
        n = int(m * 9)
        for k in range(9):                                                # the hit meter beside it
            yy = 89 - k * 4
            a[yy - 2:yy, cx + 12:cx + 16] = 255 if k < n else (85 if not pad.empty else 0)
        lbl = str(i + 1)
        if sel: a[91:96, cx - 3:cx + 5] = 255; text(a, cx - 2, 87, lbl, 1, 0)
        else: text(a, cx - 2, 87, lbl, 1, 170)
    return Image.fromarray(a)


_logos = {}


def badge_logo(name, h):
    """badges/<name>.png made h dots tall for this screen: its shape (alpha) in the screen's four greys, so the edges keep a
    step of grey and the curves stay smooth. None if the file is not there. Cached until the file changes."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "badges", name + ".png")
    try: key = (name, h, os.path.getmtime(path))
    except OSError: return None
    if key not in _logos:
        im = Image.open(path).convert("RGBA")
        im = im.crop(im.getbbox() or (0, 0, im.width, im.height))
        al = im.getchannel("A").resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)
        v = np.asarray(al, np.uint16)
        _logos[key] = (np.clip((v + 42) // 85, 0, 3) * 85).astype(np.uint8)
    return _logos[key]


def asr_keys_frame(e, c):
    """the ASR keys (asrpanel.py) on the Studio's screen: the display as on the ASR (the mode boxed, the page, the
    sequencer status, the 22-character line), then the ensoniq logo, this page's Q-links and the L / R output meters"""
    import lcd as L
    pn = c.asr
    a = np.zeros((H, W), np.uint8)
    w_ = tw(pn.mode) + 4
    a[0:10, 0:w_ + 2] = 255; text(a, 2, 1, pn.mode, 1, 0)                 # the mode word, lit as a block
    x = w_ + 8
    for wd in pn.words(): text(a, x, 1, wd, 1, 255); x += tw(wd) + 6
    st_, fl = pn.status()
    if not fl or int(time.time() * 3) % 2 == 0: text(a, W - tw(st_) - 2, 1, st_, 1, 255)
    arr = np.concatenate([L.glyph(ch) for ch in pn.line().ljust(22)[:22]], 1).astype(np.uint8)
    big = np.kron(arr, np.ones((2, 2), np.uint8))                          # 2 dots a dot: 22 characters fit
    ox = (W - big.shape[1]) // 2
    a[14:14 + big.shape[0], ox:ox + big.shape[1]] = np.where(big > 0, 255, 0)
    a[36, :] = 85
    logo = badge_logo("ASR-10_top", 18)
    if logo is not None: a[44:44 + logo.shape[0], 2:2 + logo.shape[1]] = np.maximum(a[44:44 + logo.shape[0], 2:2 + logo.shape[1]], logo)
    else: text(a, 2, 46, "ensoniq", 2, 255)
    text(a, 2, 70, "ADVANCED SAMPLING", 1, 170); text(a, 2, 81, "RECORDER", 1, 170)
    for i, (lab, get, _, fmt) in enumerate(c.qlinks()[:4]):
        if lab == "-": continue
        y = 41 + i * 13
        try: v = str(fmt())
        except Exception: v = ""
        l_ = f"Q{i + 1} {lab.upper()}"[:14]
        room = max(4, (332 - 136 - tw(l_) - 6) // 6)                        # the value gets what the label leaves
        v = v.replace(" ", "")[:room] if len(v) > room else v
        text(a, 136, y, l_, 1, 170); text(a, 332 - tw(v), y, v, 1, 255)
    for ch, lvl in enumerate((getattr(e, "meter_l", 0.0), getattr(e, "meter_r", 0.0))):   # L / R output, upright
        x_ = 340 + ch * 10
        n_ = int(min(1.0, max(0.0, lvl)) ** 0.5 * 11)
        for k_ in range(11):
            y_ = 84 - k_ * 4
            a[y_:y_ + 3, x_:x_ + 7] = 255 if k_ < n_ else 85
        text(a, x_ + 1, 88, "LR"[ch], 1, 170)
    return Image.fromarray(a)


def asr_frame(e, c, scr):
    """ASR-10: its panel words lit and dark, the fluorescent line big with its unlit dots showing, then the maker's
    name and a two-channel level meter in fluorescent segments"""
    a = np.zeros((H, W), np.uint8)
    half = (len(scr.legends) + 1) // 2
    for row, words in enumerate((scr.legends[:half], scr.legends[half:])):
        for i, (w_, lit) in enumerate(words):
            cx = int(W * (i + 0.5) / len(words)) - tw(w_) // 2
            text(a, cx, 1 + row * 10, w_, 1, 255 if lit else 85)
    img = np.asarray(_lcd(scr, c, 3, False, gap=True))                    # dots apart, like a fluorescent display
    h, w = img.shape
    y0 = 22
    a[y0:y0 + h, (W - w) // 2:(W - w) // 2 + w] = img
    a[y0 + h + 4, :] = 85
    logo = badge_logo("ASR-10_top", 18)                                    # the real ensoniq logo from badges/, in the 4 greys
    if logo is not None:
        lh, lw = logo.shape
        a[61:61 + lh, 4:4 + lw] = np.maximum(a[61:61 + lh, 4:4 + lw], logo)
    else: text(a, 4, 62, "ensoniq", 2, 255)
    text(a, 4, 83, "ADVANCED SAMPLING RECORDER", 1, 170)
    for ch, lvl in enumerate((getattr(e, "meter_l", 0.0), getattr(e, "meter_r", 0.0))):
        yy = 64 + ch * 9
        text(a, 196, yy - 1, "LR"[ch], 1, 170)
        n = int(min(1.0, max(0.0, lvl)) ** 0.5 * 24)
        for k in range(24):
            x = 206 + k * 6
            a[yy:yy + 6, x:x + 4] = 255 if k < n else 85
    return Image.fromarray(a)


def machine_frame(e, c):
    """MAIN on a classic machine: its display, as big as it fits in whole dots, centred (the SP-1200 and ASR-10, whose
    displays are small, get a fuller screen of their own)"""
    import machines, lcd
    scr = machines.screen(e, e.machine, c.lcd_cur)
    if scr is None: return None
    if e.machine == "SP-1200": return sp_frame(e, c, scr)
    if e.machine == "ASR-10" and getattr(c, "asr_on", lambda: False)(): return asr_keys_frame(e, c)
    if e.machine == "ASR-10": return asr_frame(e, c, scr)
    st0 = machines.STYLE[e.machine]
    st = lcd.Style((0, 0, 0), (255, 255, 255), (0, 0, 0), cells=False, row_h=st0.row_h, gap=False)
    leg = 22 if scr.legends else 0
    nw, nh = scr.cols * lcd.CW, scr.rows * st.row_h
    cur = next(((r, col, n) for key, r, col, n in scr.fields if key == c.lcd_cur), None) if not scr.legends else None
    k = max(1, min(W // nw, (H - leg) // nh))                          # whole dots only: pixel-perfect (the MPCs fit at 1 x)
    img = lcd.render(scr.text(), scr.cols, st, k, inverse=scr.inverse, cursor=cur).convert("L")
    out = Image.new("L", (W, H), 0)
    out.paste(img, ((W - img.width) // 2, leg + (H - leg - img.height) // 2))
    if scr.legends:                                                    # the ASR-10's lit and dark words above its characters
        a = np.array(out)
        half = (len(scr.legends) + 1) // 2
        for row, words in enumerate((scr.legends[:half], scr.legends[half:])):
            for i, (w, lit) in enumerate(words):
                cx = int(W * (i + 0.5) / len(words)) - tw(w) // 2
                text(a, cx, 1 + row * 10, w, 1, 255 if lit else 85)
        out = Image.fromarray(a)
    return out


def monolith_frame(e, c):
    """every other page: what page, where, how fast, the last status message, and the four Q-links"""
    a = np.zeros((H, W), np.uint8)
    page = c.mode if not (c.mode == "MAIN" and c.mpick is not None) else "MACHINE"
    page = {"EXPORT": "TRACK OUT", "PADS": "PAD MODES"}.get(page, page)     # the names the main screen uses
    text(a, 2, 1, page, 2, 255)
    sq = e.seq
    bar = int(max(0.0, e.pos) // max(1, sq.bar_ticks)) + 1
    beat = int(max(0.0, e.pos) % max(1, sq.bar_ticks) // max(1, sq.beat_ticks)) + 1
    right = f"{bar:03d}.{beat}  {sq.bpm:5.1f}"
    text(a, W - 2 - tw(right), 5, right, 1, 255)
    state = "REC" if e.rec != "off" else ("PLAY" if e.playing else "STOP")
    text(a, W - 2 - tw(right) - tw(state) - 8, 5, state, 1, 255 if e.playing or e.rec != "off" else 170)
    a[20, :] = 85
    now = time.time()
    msg = e.msg if (e.msg and now - e.msg_time < 2.5 and getattr(e, "msg_level", "info") in ("info", "warn")) else ""
    line = msg.upper() if msg else f"SEQ {e.cur_seq + 1:02d} {sq.name.upper()}  TRK {e.track.n + 1:02d} {e.track.name.upper()}"
    if c.mode == "MAIN" and c.mpick is not None:
        line = "PICK: " + c.PICK[c.mpick] + "   F4 SELECT"
    if getattr(c, "confirm", None) is not None:                          # a question on the main screen: F1 CANCEL, F4 answers
        line = c.confirm["title"] + "   F1 CANCEL  F4 " + str(c.confirm["keys"][3][0][-1])
    if c.mode == "MAIN" and e.machine == "MODERN" and c.mpick is None and not msg and getattr(c, "confirm", None) is None:
        # MAIN's fields as on the touch screen: the one under the cursor inverted (arrows move it, the wheel changes it)
        x = 2
        segs = [("seq", c.main_value("seq").replace("SEQUENCE", "SEQ")), ("bars", f"{sq.bars} BARS"),
                ("trk", c.main_value("trk")), ("pgm", c.main_value("pgm"))]
        if c.main_field in ("swing", "q", "bpm"): segs = segs[:1] + [(c.main_field, c.main_value(c.main_field))] + segs[2:]
        for key, t in segs:
            w = tw(t)
            if x + w > W - 2: break
            if key == c.main_field:
                a[23:34, max(0, x - 2):min(W, x + w + 2)] = 255; text(a, x, 25, t, 1, 0)
            else: text(a, x, 25, t, 1, 255)
            x += w + 9
    else: text(a, 2, 25, line[:59], 1, 255)
    a[37, :] = 85
    try: q = c.qlinks()
    except Exception: q = []
    for i, (label, get, _, fmt) in enumerate(q[:4]):
        x0 = i * 90
        if i: a[40:96, x0] = 85
        if label == "-": continue
        text(a, x0 + 4, 42, label.upper()[:14], 1, 170)
        try: val = str(fmt())
        except Exception: val = ""
        k = 2 if tw(val, 2) <= 84 else 1
        text(a, x0 + 4, 56 if k == 2 else 60, val[:14 if k == 1 else 7], k, 255)
        try: f = min(1.0, max(0.0, float(get())))
        except Exception: f = 0.0
        a[90:93, x0 + 4:x0 + 4 + int(80 * f)] = 255                  # how far the knob is turned
        a[92, x0 + 4:x0 + 84] = np.maximum(a[92, x0 + 4:x0 + 84], 85)
    return Image.fromarray(a)


def frame(c):
    e = c.e
    if c.mode == "MAIN" and e.machine != "MODERN" and c.mpick is None:
        try:
            img = machine_frame(e, c)
            if img is not None: return img
        except Exception:
            pass
    return monolith_frame(e, c)


class Screen:
    """keeps the Studio's screen in step: renders a frame, sends the rows that changed"""
    def __init__(self):
        self.rows = [None] * H

    def reset(self): self.rows = [None] * H

    def update(self, c, send):
        rows = pack(frame(c))
        n = 0
        for y, r in enumerate(rows):
            if r != self.rows[y]:
                send(row_msg(y, r)); self.rows[y] = r; n += 1
        return n
