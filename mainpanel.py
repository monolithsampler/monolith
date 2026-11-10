"""mainpanel.py - MAIN's machine front panel, its tracks panel and the machine picker (artboards MachinePanels,
Main<MACHINE>, MachinePicker). The panel and picker are laid out in screen pixels of the 1280 x 800 panel, as the
artboards are; r.P() converts the rest of the layout units.

Panel (652 x 204): the facia (140 tall: the machine's display in a recessed window, its badge at its own pixel size, never
scaled up) over the rail (the MONOLITH pixel logo at exactly 2x, the CHANGE MACHINE key)."""
import math
from PIL import Image, ImageDraw, ImageFilter
import skin
from uicore import clamp, mix, font, RED

MACHS = ["MODERN", "MPC60", "MPC3000", "MPC2000XL", "SP-1200", "ASR-10"]
ACCENT = {"MODERN": (255, 138, 61), "MPC60": (224, 53, 43), "MPC3000": (232, 223, 200), "MPC2000XL": (159, 183, 201),
          "SP-1200": (79, 134, 208), "ASR-10": (70, 224, 208)}
FACIA = {"MPC60": (16, 16, 18), "MPC3000": (16, 16, 18), "MPC2000XL": (22, 22, 24), "SP-1200": (80, 84, 92), "ASR-10": (20, 21, 26)}
SP_LIGHT = (212, 212, 206)
# the badge area, screen px (from the artboard crops) and where it sits: MPCs right-aligned 22 px in, the others centred
BADGE = {"MPC60": (134, 84, "right"), "MPC3000": (134, 80, "right"), "MPC2000XL": (122, 84, "right"),
         "SP-1200": (182, 84, "centre"), "ASR-10": (134, 86, "centre")}
CROP = {"MPC60": (494, 158), "MPC3000": (494, 158), "MPC2000XL": (506, 126), "SP-1200": (394, 82), "ASR-10": (494, 96)}
INFO = {"MODERN": ("Monolith engine", "32-bit 44.1 kHz"), "MPC60": ("1988", "12-bit 40 kHz"), "MPC3000": ("1994", "16-bit 44.1 kHz"),
        "MPC2000XL": ("1999", "16-bit 44.1 kHz"), "SP-1200": ("1987", "12-bit 26.04 kHz"), "ASR-10": ("1992", "16-bit 44.1 kHz")}
LOGO = [(0, 2, 1, 1), (4, 2, 1, 1), (0, 3, 2, 1), (3, 3, 2, 1), (0, 4, 1, 1), (2, 4, 1, 1), (4, 4, 1, 1), (0, 5, 1, 1), (4, 5, 1, 1),
        (0, 6, 1, 1), (4, 6, 1, 1), (0, 7, 1, 1), (4, 7, 1, 1), (0, 8, 1, 1), (4, 8, 1, 1), (7, 2, 3, 1), (6, 3, 1, 1), (10, 3, 1, 1),
        (6, 4, 1, 1), (10, 4, 1, 1), (6, 5, 1, 1), (10, 5, 1, 1), (6, 6, 1, 1), (10, 6, 1, 1), (6, 7, 1, 1), (10, 7, 1, 1), (7, 8, 3, 1),
        (12, 2, 1, 1), (16, 2, 1, 1), (12, 3, 2, 1), (16, 3, 1, 1), (12, 4, 1, 1), (14, 4, 1, 1), (16, 4, 1, 1), (12, 5, 1, 1),
        (15, 5, 2, 1), (12, 6, 1, 1), (16, 6, 1, 1), (12, 7, 1, 1), (16, 7, 1, 1), (12, 8, 1, 1), (16, 8, 1, 1), (19, 2, 3, 1),
        (18, 3, 1, 1), (22, 3, 1, 1), (18, 4, 1, 1), (22, 4, 1, 1), (18, 5, 1, 1), (22, 5, 1, 1), (18, 6, 1, 1), (22, 6, 1, 1),
        (18, 7, 1, 1), (22, 7, 1, 1), (19, 8, 3, 1), (24, 2, 1, 7), (24, 8, 5, 1), (33, 2, 5, 1), (35, 3, 1, 6), (39, 2, 1, 7),
        (43, 2, 1, 7), (39, 5, 5, 1)]
LOGO_I = (30, 0, 2, 9)                                          # the accent-coloured I


def logo(r, x, y, accent, k=2):
    """the MONOLITH pixel logo at exactly k x its 44 x 9 grid, in screen pixels (crisp: no scaling, no smoothing)"""
    d = ImageDraw.Draw(r.img)
    for gx, gy, w, h in LOGO: d.rectangle([x + gx * k, y + gy * k, x + (gx + w) * k - 1, y + (gy + h) * k - 1], fill=(233, 236, 242))
    gx, gy, w, h = LOGO_I
    d.rectangle([x + gx * k, y + gy * k, x + (gx + w) * k - 1, y + (gy + h) * k - 1], fill=accent)


_badges = {}


def badge(r, machine, bw, bh, align):
    """the maker's badge over the model's (badges/<M>_top.png, badges/<M>.png) fitted into bw x bh screen px - only ever made
    smaller, never larger. Returns an RGBA image (cached) or None when there are no badge files."""
    hits = [h for h in (r.badge_image(machine + "_top"), r.badge_image(machine)) if h is not None and h[1] is not None]
    key = (machine, bw, bh, align, tuple(h[0] for h in hits))               # (the files' paths and dates: a new file shows)
    if key in _badges: return _badges[key]
    if len(_badges) > 64: _badges.clear()
    parts = [h[1] for h in hits]
    out = None
    if parts:
        gap = 6
        share = [0.46, 0.54] if len(parts) == 2 else [1.0]
        ims = []
        for im, f in zip(parts, share):
            avail = (bh - gap * (len(parts) - 1)) * f
            k = min(1.0, bw / im.width, avail / im.height)
            ims.append(im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS))
        out = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        tot = sum(i.height for i in ims) + gap * (len(ims) - 1)
        y = (bh - tot) // 2
        for i in ims:
            x = bw - i.width if align == "right" else (bw - i.width) // 2
            out.paste(i, (x, y), i); y += i.height + gap
    _badges[key] = out
    return out


def _lcd_image(machine, scr, st, bw, bh, cur):
    """the machine's display, as big as fits bw x bh: whole dots when they are 2 x or more, else drawn at 2 x and made
    smaller (sharp edges, no blur when it grows)"""
    import lcd
    nw, nh = scr.cols * lcd.CW, scr.rows * st.row_h
    k = int(min(bw / nw, bh / nh))
    if k >= 2:
        return lcd.render(scr.text(), scr.cols, st, k, inverse=scr.inverse, cursor=cur)
    img = lcd.render(scr.text(), scr.cols, st, 2, inverse=scr.inverse, cursor=cur)
    f = min(bw / float(img.width), bh / float(img.height))
    return img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))), Image.LANCZOS)


def panel(r):
    """the front panel, top right of MAIN"""
    import machines
    e, c = r.e, r.c
    m = e.machine
    acc = ACCENT[m]
    sc = r.scale
    X0, Y0 = int(616 * sc / 1.6), int(78 * sc / 1.6)
    q = lambda v: int(round(v * sc / 1.6))                      # artboard px -> this screen's px
    r.plate((X0 / sc, Y0 / sc, (X0 + q(652)) / sc, (Y0 + q(204)) / sc), 10)
    fx0, fy0, fx1, fy1 = X0 + q(10), Y0 + q(10), X0 + q(642), Y0 + q(150)
    D = ImageDraw.Draw(r.img)
    # the facia
    if m == "MODERN":
        g = skin._vgrad(fx1 - fx0, fy1 - fy0, (27, 29, 34), (18, 20, 24)).convert("RGBA")
        r.img.paste(g, (fx0, fy0), skin._rr_mask(fx1 - fx0, fy1 - fy0, q(10)))
    else:
        D.rounded_rectangle([fx0, fy0, fx1 - 1, fy1 - 1], q(10), fill=FACIA[m])
    D.line([fx0 + q(10), fy1, fx1 - q(10), fy1], fill=(70, 72, 78))
    inner_x0, inner_x1, cy = fx0 + q(16), fx1 - q(16), (fy0 + fy1) // 2
    hits = []
    if m == "MODERN":
        lw, lh = q(430), q(104)
        wx = inner_x0
        D.rounded_rectangle([wx, cy - lh // 2 - q(4), wx + lw + q(8), cy + lh // 2 + q(4)], q(6), fill=(6, 7, 8))
        lx, ly = wx + q(4), cy - lh // 2
        gl = Image.new("RGB", (lw, lh), (19, 11, 5))
        gm = Image.new("L", (lw, lh), 0); ImageDraw.Draw(gm).ellipse([-lw * 0.3, -lh * 1.2, lw * 0.9, lh * 0.9], fill=255)
        gl.paste((58, 36, 16), (0, 0), gm.filter(ImageFilter.GaussianBlur(lw * 0.15)))
        r.img.paste(gl, (lx, ly))
        sq, tr = e.seq, e.track
        amb, dim = (255, 176, 102), (230, 150, 86)
        r.vt((lx + q(14)) / sc, (ly + q(22)) / sc, f"SEQUENCE {e.cur_seq + 1:02d}" if not sq.name.startswith("Seq") else f"SEQUENCE {e.cur_seq + 1:02d}", 19, amb)
        r.vt((lx + lw - q(14)) / sc, (ly + q(22)) / sc, f"{sq.num}/{sq.den}  {sq.bars} BARS", 11.5, dim, "rm")
        prog = e.programs[tr.prog].name if hasattr(e, "programs") else ""
        r.vt((lx + q(14)) / sc, (ly + q(54)) / sc, f"TRK {tr.n + 1:02d} {tr.name.upper()[:12]}   PGM {prog.upper()[:8]}  BANK {'ABCD'[e.bank]}", 12.5, amb,
             maxw=(lw - q(28)) / sc)
        qn = __import__("engine").QUANT[e.qgrid][0]
        r.vt((lx + q(14)) / sc, (ly + q(84)) / sc, f"SWING {sq.swing * 100:.0f}%   Q {qn}", 11.5, dim)
        r.vt((lx + lw - q(14)) / sc, (ly + q(84)) / sc, f"{sq.bpm:.1f} BPM", 11.5, dim, "rm")
        # name where a badge would be
        mid = (wx + lw + q(8) + inner_x1) / 2.0
        room = (inner_x1 - (wx + lw + q(8)) - q(20)) / sc               # between the display and the facia's edge
        r.lab(mid / sc, (cy - q(10)) / sc, "MODERN", 13.75, (241, 243, 247), "mm", "s", 0.06, floor=8, maxw=room)
        r.lab(mid / sc, (cy + q(16)) / sc, "MONOLITH ENGINE", 5.6, acc, "mm", "s", 0.2, floor=4, maxw=room)
    else:
        scr = machines.screen(e, m, c.lcd_cur)
        st = machines.STYLE[m]
        bw, bh, align = BADGE[m]
        bw, bh = q(bw), q(bh)
        plate_w = bw + q(24)
        maxw = (inner_x1 - inner_x0) - plate_w - q(8)
        cw_, ch_ = CROP[m]
        s_ = min(maxw / float(cw_), q(104) / float(ch_))
        ww, wh = int(cw_ * s_), int(ch_ * s_)                   # the display window (as the artboard's crop of the screen)
        if m in ("MPC60", "MPC3000"): ml = int(((inner_x1 - inner_x0) - q(22) - bw - (ww + q(8))) / 2)
        else: ml = 0
        wx = inner_x0 + ml
        if m == "SP-1200":                                      # two-tone: the light plate from the middle of the gap rightwards
            split = fx0 + q(16) + ww + q(8) + q(8)
            D.rounded_rectangle([split, fy0, fx1 - 1, fy1 - 1], q(10), fill=SP_LIGHT)
            D.rectangle([split, fy0, split + q(12), fy1 - 1], fill=SP_LIGHT)
        D.rounded_rectangle([wx, cy - wh // 2 - q(4), wx + ww + q(8), cy + wh // 2 + q(4)], q(6), fill=(6, 7, 8))
        D.line([wx + q(4), cy + wh // 2 + q(4), wx + ww + q(4), cy + wh // 2 + q(4)], fill=(60, 62, 66))
        gx, gy = wx + q(4), cy - wh // 2
        D.rounded_rectangle([gx, gy, gx + ww - 1, gy + wh - 1], q(4) if m == "SP-1200" else q(2), fill=st.bg)    # the glass
        if m == "ASR-10" and c.asr_on():                         # ASR keys: its display as the manual draws it
            r.img.paste(asr_vfd(c, ww, wh, sc), (gx, gy))
            scr = None
        keys = [f[0] for f in scr.fields] if scr is not None else []
        if scr is not None and c.lcd_cur not in keys: c.lcd_cur = next((k_ for k_ in keys if not k_.startswith("soft")), keys[0] if keys else None)
        cur = next(((rr, col, n) for key, rr, col, n in scr.fields if key == c.lcd_cur), None) if scr is not None else None
        leg = q(30) if scr is not None and scr.legends else 0
        img = _lcd_image(m, scr, st, ww - q(10), wh - q(10) - leg, None if scr.legends else cur) if scr is not None else None
        if img is not None:
            ix, iy = gx + (ww - img.width) // 2, gy + leg + (wh - leg - img.height) // 2
            r.img.paste(img, (ix, iy))
        if scr is not None and scr.legends:                                         # the fluorescent display's printed words, lit or dark
            half = (len(scr.legends) + 1) // 2
            for row, words in enumerate((scr.legends[:half], scr.legends[half:])):
                for i, (w, lit) in enumerate(words):
                    x = ix + img.width * (i + 0.5) / len(words)
                    r.t(x / sc, (gy + q(9) + row * q(14)) / sc, w, 8, True, st.on if lit else mix(st.ghost, st.on, 0.12), "mm")
        import lcd as L
        kx = img.width / float(scr.cols * L.CW) if img is not None else 1; ky = img.height / float(scr.rows * st.row_h) if img is not None else 1
        for key, rr, col, n in (scr.fields if scr is not None else []):   # tap a field: the cursor goes there
            rx0, ry0 = ix + col * L.CW * kx, iy + rr * st.row_h * ky
            r.hit((rx0 / sc, ry0 / sc, (rx0 + n * L.CW * kx) / sc, (ry0 + st.row_h * ky) / sc), (lambda key_: lambda x, y: c.lcd_tap(key_))(key))
        b = badge(r, m, bw, bh, align)
        if b is not None:
            area_x0, area_x1 = wx + ww + q(8) + q(16), inner_x1
            if align == "right": bx = area_x1 - q(22) - b.width
            else: bx = (area_x0 + area_x1) // 2 - b.width // 2
            r.img.paste(b, (bx, cy - b.height // 2), b)
        else:                                                   # no badge files: the printed name instead
            small, big, _ = machines.BEZEL[m]
            light = (34, 36, 40) if m == "SP-1200" else (196, 198, 204)
            ax0 = wx + ww + q(8) + q(16)                                # only the room right of the display
            sz = 20
            while sz > 9 and r.d.textlength(big, font=font(sz, True)) > (inner_x1 - q(22) - ax0) / sc: sz -= 1   # (layout units)
            r.t((inner_x1 - q(22)) / sc, (cy - q(10)) / sc, big, sz, True, light, "rm")
    # the soft shadow across the top of the facia, over everything on it
    sh = skin.cached(("faciash", fx1 - fx0, fy1 - fy0), lambda: _facia_shadow(fx1 - fx0, fy1 - fy0, q(10)))
    r.img.paste(sh, (fx0, fy0), sh)
    # the rail: logo, CHANGE MACHINE
    ry0, ry1 = fy1 + q(8), Y0 + q(194)
    logo(r, X0 + q(18), (ry0 + ry1) // 2 - 9, acc, 2)
    kx1 = X0 + q(642) - q(6); kw = q(170); kx0 = kx1 - kw; ky0 = (ry0 + ry1) // 2 - q(17)
    r.keycap((kx0 / sc, ky0 / sc, kx1 / sc, (ky0 + q(34)) / sc), "up", 5)
    r.ledp((kx0 + q(18)) / sc, (ky0 + q(17)) / sc, 3.4, True, acc)
    r.lab((kx0 + q(30)) / sc, (ky0 + q(17)) / sc, "CHANGE MACHINE", 5.0, (231, 234, 240), "lm", "s", 0.14, floor=4,
          maxw=(kx1 - q(12) - (kx0 + q(30))) / sc)
    r.hit((kx0 / sc, (ky0 - 4) / sc, kx1 / sc, (ky0 + q(38)) / sc), down=lambda *_: c.open_picker())
    if m == "ASR-10":                                           # the ASR-10's own keys and pages, or its classic screen
        ax1 = kx0 - q(10); ax0 = ax1 - q(130)
        r.keycap((ax0 / sc, ky0 / sc, ax1 / sc, (ky0 + q(34)) / sc), "up", 5)
        r.ledp((ax0 + q(18)) / sc, (ky0 + q(17)) / sc, 3.4, c.asr_keys, acc)
        r.lab((ax0 + q(30)) / sc, (ky0 + q(17)) / sc, "ASR KEYS", 5.0, (231, 234, 240), "lm", "s", 0.14, floor=4,
              maxw=(ax1 - q(10) - (ax0 + q(30))) / sc)
        r.hit((ax0 / sc, (ky0 - 4) / sc, ax1 / sc, (ky0 + q(38)) / sc), down=lambda *_: c.toggle_asr_keys())


ASR_GHOST, ASR_BG = (16, 42, 46), (4, 9, 14)


def asr_vfd(c, w, h, sc):
    """the ASR-10's display (Musician's Manual, section 1): the mode word boxed top left, the page word(s) beside it, the
    sequencer status top right (flashing for count-in / standby), and the 22-character line in fluorescent dots"""
    import time
    pn = c.asr
    cy_ = ACCENT["ASR-10"]
    im = Image.new("RGB", (w, h), ASR_BG); d = ImageDraw.Draw(im)
    f = skin.face("michroma", max(7, int(h * 0.11)))
    mx, my, bh = int(w * 0.03), int(h * 0.1), int(h * 0.17)
    mw = int(f.getlength(pn.mode)) + 10
    d.rectangle([mx, my, mx + mw, my + bh], fill=cy_)
    d.text((mx + 5, my + bh // 2), pn.mode, font=f, fill=ASR_BG, anchor="lm")
    x = mx + mw + 14
    for wd in pn.words():
        d.text((x, my + bh // 2), wd, font=f, fill=cy_, anchor="lm"); x += int(f.getlength(wd)) + 10
    st_, fl = pn.status()
    if not fl or int(time.time() * 3) % 2 == 0:
        d.text((w - mx, my + bh // 2), st_, font=f, fill=cy_, anchor="rm")
    import lcd as L
    k = max(1, int((w - 2 * mx) / float(22 * L.CW)))                      # whole dots: as big as 22 characters fit
    sp, pad = skin.dot_text(pn.line().ljust(22)[:22], k, cy_, True, ASR_GHOST)
    im.paste(sp, ((w - (sp.width - 2 * pad)) // 2 - pad, int(h * 0.62) - (sp.height - 2 * pad) // 2 - pad), sp)
    return im


def asr_keys(r, x0=386, y0=182, x1=792, y1=371):
    """the ASR-10's fourteen page keys as printed on its panel, and Cancel-No / Enter-Yes (in place of the track list
    and the OUT meter, which moves to the Studio's own screen). One tap = that page; tapped again = its next screen."""
    c = r.c; pn = c.asr
    cy_ = ACCENT["ASR-10"]
    r.plate((x0, y0, x1, y1), 10)
    r.lab(x0 + 12, y0 + 11, "ENSONIQ PAGES", 5.2, skin.LAB, "lm", "s", 0.16)
    kw, kh, gapx, rowh = 60, 30, 8, 42
    top = y0 + 26
    def key(x, y, page, label, num=None, w=kw):
        lit = pn.page == page
        r.lab(x + w / 2, y + 3, label.upper(), 4.6, cy_ if lit else (220, 224, 232), "mm", "s", 0.06, maxw=w + 4)
        r.keycap((x, y + 9, x + w, y + 9 + kh - 6), "lit" if lit else "up", 4, cy_ if lit else None)
        if num is not None: r.t(x + w / 2, y + 9 + (kh - 6) / 2, str(num), 9, True, (255, 255, 255) if lit else (150, 156, 168), "mm")
        r.hit((x - 2, y, x + w + 2, y + kh + 4), down=lambda *_, pg=page: pn.press_page(pg))
    lx = x0 + 14
    for i, (pg, lab) in enumerate((("Instrument", "Instrument"), ("Seq Song", "Seq Song"), ("Sys MIDI", "Sys MIDI"), ("Effects", "Effects"))):
        key(lx, top + i * rowh, pg, lab, w=76)
    gx0 = lx + 76 + 16
    grid = [["Env 1", "Env 2", "Env 3"], ["Pitch", "Filters", "Amp"], ["LFO", "Wave", "Layer"]]
    for rr, row in enumerate(grid):
        for cc, pg in enumerate(row): key(gx0 + cc * (kw + gapx), top + rr * rowh, pg, pg, rr * 3 + cc + 1)
    key(gx0 + 1 * (kw + gapx), top + 3 * rowh, "Track", "Track", 0)
    dx = gx0 + 3 * (kw + gapx) + 10; bw = x1 - 14 - dx
    def big(y, h, word, sub, tag, lit, fn):
        r.keycap((dx, y, dx + bw, y + h), "lit" if lit else "up", 6, cy_ if lit else None)
        r.t(dx + bw / 2, y + h / 2 - 7, word, 11, True, (255, 255, 255) if lit else (226, 230, 236), "mm")
        r.t(dx + bw / 2, y + h / 2 + 8, sub, 8.5, False, (200, 230, 226) if lit else (150, 156, 168), "mm")
        if tag: r.lab(dx + 6, y + 6, tag, 4.2, (200, 230, 226) if lit else skin.LAB, "la", "s", 0.08)
        r.hit((dx, y, dx + bw, y + h), down=lambda *_: fn())
    ask = pn.ask is not None
    big(top + 9, 2 * rowh - 14, "CANCEL", "NO", "F1" if ask else "", False, pn.cancel)
    big(top + 9 + 2 * rowh, 2 * rowh - 14, "ENTER", "YES", "F4 / OK" if pn.waiting() else "", pn.waiting(), pn.enter)


def _facia_shadow(w, h, rad):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rectangle([0, 0, w, 6], fill=180)
    m = m.filter(ImageFilter.GaussianBlur(5))
    im.paste((0, 0, 0, 255), (0, 0), Image.composite(m, Image.new("L", (w, h), 0), skin._rr_mask(w, h, rad)))
    return im


# ------------------------------------------------------------------ the tracks panel under it
def tracks(r, x0, sq):
    d, e, c = r.d, r.e, r.c
    acc = ACCENT[e.machine]
    r.plate((x0, 183.75, 792, 330), 10)
    r.well((x0 + 6, 189.5, 786, 324), 7, (22, 24, 28), 8)
    page = e.cur_track // 8
    r.lab(x0 + 14, 197, f"TRACKS {page * 8 + 1}-{page * 8 + 8}", 5.6, skin.LAB, "lm", "s", 0.16)
    r.hit((x0 + 6, 189, x0 + 120, 203), down=lambda *_: setattr(e, "cur_track", (e.cur_track + 8) % 16))
    bar, _ = r.bar_beat()
    r.lab(778, 197, f"BAR {bar} / {sq.bars}", 5.6, skin.LAB, "rm", "s", 0.16)
    ct = sq.tracks[e.cur_track]
    r.lab(x0 + 140, 197, f"TRACK {ct.n + 1:02d} PLAYS P{ct.prog + 1:02d} {e.programs[ct.prog].name.upper()[:16]}  (TAP PGM TO CHANGE)",
          4.6, (150, 156, 166), "lm", "s", 0.1, maxw=780 - 70 - (x0 + 140))
    tx0, tx1 = x0 + 112, 778
    for k in range(page * 8, page * 8 + 8):
        t = sq.tracks[k]; y = 203.75 + (k % 8) * 15
        on = t.n == e.cur_track
        if on: d.rounded_rectangle([x0 + 10, y + 0.5, 782, y + 14.25], 3, fill=(36, 39, 45))
        r.t(x0 + 16, y + 7.5, f"{t.n + 1:02d}", 9, True, acc if on else (95, 101, 113), "lm")
        r.t(x0 + 36, y + 7.5, t.name[:8], 10, on, (235, 238, 243) if t.events else (95, 101, 113), "lm")
        # PGM: which program this track plays; tap it for the next one (each track can play its own program)
        cx0, cx1 = x0 + 82, x0 + 107
        d.rounded_rectangle([cx0, y + 2, cx1, y + 13], 2, fill=(52, 56, 64) if on else (34, 37, 42),
                            outline=acc if on else None)
        r.lab((cx0 + cx1) / 2, y + 7.5, f"P{t.prog + 1:02d}", 4.6, (240, 242, 246) if on else (150, 156, 166), "mm", "b", 0.04)
        n = sq.length
        col = acc if on else (150, 156, 166)
        for ev in t.events:
            px = tx0 + int(ev[0] / n * (tx1 - tx0))
            d.rounded_rectangle([px, y + 3.5, px + 2.2, y + 11.5], 0.6, fill=col)
        if t.mute: r.t(782, y + 7.5, "M", 9, True, RED, "rm")
        r.hit((x0 + 6, y, 786, y + 15), down=lambda *_, k=k: setattr(e, "cur_track", k))
        r.hit((cx0 - 2, y, cx1 + 2, y + 15), down=lambda *_, k=k: c.track_prog_step(k))
    if e.playing:
        px = tx0 + int(clamp(e.pos, 0, sq.length) / sq.length * (tx1 - tx0))
        d.rectangle([px - 1.2, 203.75, px + 1.2, 323.75], fill=mix((20, 22, 26), acc, 0.25))
        d.rectangle([px - 0.4, 203.75, px + 0.4, 323.75], fill=acc)


# ------------------------------------------------------------------ the machine picker
def picker(r):
    """SELECT MACHINE: six cards, one tap switches straight to that machine (no cycling); F1 CLOSE, F4 SELECT"""
    import machines
    e, c = r.e, r.c
    sc = r.scale
    q = lambda v: v / 1.6                                        # artboard px -> layout units
    shade = skin.cached(("shade", r.img.width, r.P(372)), lambda: Image.new("RGBA", (r.img.width, r.P(372)), (6, 7, 9, 160)))
    r.img.paste(shade, (0, 0), shade)
    r.hit((0, 44, 800, 372), down=lambda *_: None)
    x0, y0, x1, y1 = q(60), q(90), q(1220), q(585)
    sp = skin.body(r.P(x1 - x0), r.P(y1 - y0), r.P(9), (52, 55, 62), (40, 43, 49), 0.08, 0.2, (24, 0.7))
    r.put(sp[0], x0, y0, sp[1], sp[2])
    r.lab(q(84), q(120), "SELECT MACHINE", 7.5, (241, 243, 247), "lm", "s", 0.2, floor=5)
    r.t(q(84), q(141), "Tap one to switch straight to it. The project stays loaded.", 9, False, (160, 166, 178), "lm")
    r.keycap((q(1098), q(110), q(1196), q(150)), "up", 5)
    r.lab(q(1147), q(130), "CLOSE", 5.2, (231, 234, 240), "mm", "s", 0.14, floor=4)
    r.hit((q(1098), q(106), q(1196), q(154)), down=lambda *_: c.close_picker())
    for i, m in enumerate(MACHS):
        cx0 = q(84 + (i % 3) * 376); cy0 = q(166 + (i // 3) * 206)
        cx1, cy1 = cx0 + q(360), cy0 + q(190)
        on = e.machine == m
        hl = c.mpick == i
        acc = ACCENT[m]
        r.keycap((cx0, cy0, cx1, cy1), "up", 7)
        if on or hl: r.d.rounded_rectangle([cx0, cy0, cx1, cy1], 7, outline=acc if on else (200, 204, 212), width=1.4 if on else 1)
        # thumbnail
        tx0, ty0, tx1, ty1 = cx0 + q(12), cy0 + q(12), cx0 + q(182), cy0 + q(178)
        r.d.rounded_rectangle([tx0, ty0, tx1, ty1], 4, fill=(10, 10, 12))
        thumb(r, m, int(tx0 * sc), int(ty0 * sc), int((tx1 - tx0) * sc), int((ty1 - ty0) * sc))
        r.ledp(cx0 + q(201), cy0 + q(18), 3.6, True, acc)
        if on: r.lab(cx1 - q(12), cy0 + q(18), "ACTIVE", 4.4, acc, "rm", "s", 0.14, floor=4)
        r.lab(cx0 + q(196), cy0 + q(68), m.replace("MPC2000XL", "2000XL"), 13.75, (241, 243, 247), "lm", "s", 0.04, floor=8)
        a, b = INFO[m]
        r.t(cx0 + q(196), cy0 + q(118), a, 8.5, False, (160, 166, 178), "lm")
        r.t(cx0 + q(196), cy0 + q(136), b, 8.5, False, (226, 230, 236), "lm")
        r.d.rounded_rectangle([cx0 + q(196), cy0 + q(174), cx1 - q(12), cy0 + q(176)], 1, fill=acc if on else mix((44, 47, 54), acc, 0.4))
        r.hit((cx0, cy0, cx1, cy1), down=lambda *_, m=m: c.pick_machine(m))


_thumbs = {}


def thumb(r, m, X, Y, W, H):
    """a small picture of the machine's display (and badge) in a card's dark window, screen px"""
    import machines
    e = r.e
    if m == "MODERN":
        w, h = int(W * 0.86), int(H * 0.9)
        gl = Image.new("RGB", (w, h), (19, 11, 5))
        gm = Image.new("L", (w, h), 0); ImageDraw.Draw(gm).ellipse([-w * 0.3, -h * 0.4, w * 0.9, h * 0.8], fill=255)
        gl.paste((58, 36, 16), (0, 0), gm.filter(ImageFilter.GaussianBlur(w * 0.2)))
        r.img.paste(gl, (X + (W - w) // 2, Y + (H - h) // 2))
        r.vt((X + W * 0.12) / r.scale, (Y + H * 0.45) / r.scale, f"SEQUENCE {e.cur_seq + 1:02d}", 10, (255, 176, 102), maxw=W * 0.8 / r.scale)
        r.vt((X + W * 0.12) / r.scale, (Y + H * 0.58) / r.scale, f"TRK {e.track.n + 1:02d} {e.track.name.upper()[:8]}", 7.5, (230, 150, 86), maxw=W * 0.8 / r.scale)
        return
    scr = machines.screen(e, m, None)
    st = machines.STYLE[m]
    import lcd
    img = lcd.render(scr.text(), scr.cols, st, 2, inverse=scr.inverse)
    bw = int(W * 0.2)
    f = min((W - bw - 14) / float(img.width), H * 0.5 / float(img.height))
    img = img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))), Image.LANCZOS)
    gw, gh = img.width + 6, img.height + 6 + (8 if scr.legends else 0)
    lx, ly = X + 5, Y + (H - gh) // 2
    bg = FACIA[m]
    D = ImageDraw.Draw(r.img)
    D.rectangle([X + 2, ly - 6, X + W - 3, ly + gh + 6], fill=bg)
    if m == "SP-1200": D.rectangle([lx + gw + 3, ly - 6, X + W - 3, ly + gh + 6], fill=SP_LIGHT)
    D.rectangle([lx, ly, lx + gw - 1, ly + gh - 1], fill=st.bg)
    r.img.paste(img, (lx + 3, ly + 3 + (8 if scr.legends else 0)))
    b = badge(r, m, bw, gh + 4, "centre")
    if b is not None: r.img.paste(b, (X + W - bw - 4, ly - 2), b)
