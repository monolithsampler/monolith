#!/usr/bin/env python3
"""Renders pictures of the finished device (case, MPC-style parts, hinged display with the real UI on it) with no 3D software.
    python3 make_render.py"""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import make_stl as M

SS = 2
TOP = M.LID                              # top face of the lid, panel coordinates (h)
HERE = os.path.dirname(os.path.abspath(__file__))

PR = lambda tl: [tuple(M.R(*p) for p in t) for t in tl]       # panel coordinates -> world (tilted)

DISP_PX, DISP_ACTIVE = (1280, 800), (216.566, 135.36)   # the 10.1 inch module: pixels and active area (mm)


def window_image(screen):
    """what shows through the bezel window: the glass border, and the UI placed on the panel the way sampler_os.py --fit auto does"""
    import sampler_os
    k = DISP_PX[0] / DISP_ACTIVE[0]                            # pixels per mm
    ww, wh = int(round(M.DISP_WINDOW[0] * k)), int(round(M.DISP_WINDOW[1] * k))
    img = Image.new("RGB", (ww, wh), (6, 6, 8))
    ax = int(round((M.DISP_WINDOW[0] - DISP_ACTIVE[0]) / 2 * k - M.DISP_WIN_OFF[0] * k))
    ay = int(round((M.DISP_WINDOW[1] - DISP_ACTIVE[1]) / 2 * k + M.DISP_WIN_OFF[1] * k))
    x, y, w, h = sampler_os.fit_box(*DISP_PX)
    img.paste(Image.open(screen).convert("RGB").resize((w, h), Image.LANCZOS), (ax + x, ay + y))
    return img


def boxm(x0, y0, z0, x1, y1, z1):
    m = M.Mesh(); m.box(x0, y0, z0, x1, y1, z1); return m.t
def cylm(cx, cy, r, z0, z1, n=28):
    m = M.Mesh(); m.cyl(cx, cy, r, z0, z1, n); return m.t
def ycyl(x, z, r, y0, y1, n=20):          # cylinder lying along y (LEDs and switch housings on the console front)
    m = M.Mesh(); m.cyl(x, z, r, y0, y1, n); return M.remap(m.t, lambda p: (p[0], p[2], p[1]), flip=True)
def xcyl(y, z, r, x0, x1, n=28):          # cylinder lying along x (rod, nuts, screw heads)
    m = M.Mesh(); m.cyl(y, z, r, x0, x1, n); return M.remap(m.t, lambda p: (p[2], p[0], p[1]))
def xtube(y, z, ro, ri, x0, x1):
    m = M.Mesh(); M.tube(m, y, z, ro, ri, x0, x1); return M.remap(m.t, lambda p: (p[2], p[0], p[1]))

class Scene:
    def __init__(self, az, el, dist, size, focal, target):
        az, el = math.radians(az), math.radians(el)
        t = np.array(target, float)
        self.cam = t + dist * np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])
        f = t - self.cam; f /= np.linalg.norm(f)
        r = np.cross(f, [0, 0, 1]); r /= np.linalg.norm(r)
        self.f, self.r, self.u = f, r, np.cross(r, f)
        self.w, self.h = size[0] * SS, size[1] * SS
        self.focal = focal * SS
        a = np.linspace(0, 1, self.h)[:, None, None]
        arr = (np.array([44, 48, 60]) * (1 - a) + np.array([14, 15, 19]) * a) * np.ones((1, self.w, 1))
        self.img = Image.fromarray(arr.astype(np.uint8)); self.d = ImageDraw.Draw(self.img)
        self.light = np.array([-0.35, -0.5, 0.8]); self.light /= np.linalg.norm(self.light)
    def proj(self, P):
        P = np.asarray(P, float) - self.cam
        z = P @ self.f
        return np.stack([self.w / 2 + self.focal * (P @ self.r) / z, self.h / 2 - self.focal * (P @ self.u) / z], -1), z
    def tris(self, tl, color, horiz="none", shade=1.0):
        """draw triangles back to front (painter's algorithm), flat-shaded; vectorised with numpy"""
        if not len(tl): return
        T = np.asarray(tl, float).reshape(-1, 3, 3)
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); L = np.linalg.norm(n, axis=1)
        keep = L > 1e-9
        T, n = T[keep], n[keep] / L[keep, None]
        cen = T.mean(1)
        front = np.einsum("ij,ij->i", n, self.cam - cen) > 0
        T, n, cen = T[front], n[front], cen[front]
        if not len(T): return
        lit = (0.38 + 0.62 * np.maximum(0.0, n @ self.light)) ** 0.9 * shade
        key = np.linalg.norm(cen - self.cam, axis=1)
        if horiz != "none": key = key + np.where(np.abs(n[:, 2]) > 0.7, -1e6 if horiz == "last" else 1e6, 0.0)
        order = np.argsort(-key, kind="stable")
        P = T[order].reshape(-1, 3) - self.cam
        z = (P @ self.f).reshape(-1, 3)
        xy = np.stack([self.w / 2 + self.focal * (P @ self.r) / z.reshape(-1), self.h / 2 - self.focal * (P @ self.u) / z.reshape(-1)], -1).reshape(-1, 3, 2)
        cols = np.minimum(255, np.outer(lit[order], color)).astype(int)
        ok = (z > 0.1).all(1)
        for k in np.nonzero(ok)[0]:
            col = tuple(cols[k]); q = xy[k]
            self.d.polygon([(q[0, 0], q[0, 1]), (q[1, 0], q[1, 1]), (q[2, 0], q[2, 1])], fill=col, outline=col)
    def tris_textured(self, tl, along=(0.0, 1.0, 0.0)):
        """triangles filled with the stained-wood texture, shaded like tris(); the grain follows world direction `along`"""
        if not len(tl): return
        T = np.asarray(tl, float).reshape(-1, 3, 3)
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]); L = np.linalg.norm(n, axis=1)
        keep = L > 1e-9
        T, n = T[keep], n[keep] / L[keep, None]
        cen = T.mean(1)
        front = np.einsum("ij,ij->i", n, self.cam - cen) > 0
        T, n, cen = T[front], n[front], cen[front]
        if not len(T): return
        lit = (0.38 + 0.62 * np.maximum(0.0, n @ self.light)) ** 0.9
        c0 = cen.mean(0)
        p, z = self.proj([c0, c0 + 40.0 * np.asarray(along, float), c0 + np.array([0, 0, 40.0])])
        ang = math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0])
        ppm = float(np.hypot(*(p[2] - p[0]))) / 40.0                 # screen pixels per mm there (from a vertical 40 mm)
        key = (ang, round(ppm, 1), self.w, self.h)
        if getattr(self, "_tex_key", None) != key:
            self._tex, self._tex_key = stain_texture(self.w, self.h, ang, max(0.5, ppm)), key
        mask = Image.new("L", (self.w, self.h), 0); md = ImageDraw.Draw(mask)
        shade = Image.new("L", (self.w, self.h), 0); sd = ImageDraw.Draw(shade)
        order = np.argsort(-np.linalg.norm(cen - self.cam, axis=1), kind="stable")
        for k in order:
            q, zz = self.proj(T[k])
            if (zz <= 0.1).any(): continue
            pts = [tuple(x) for x in q]
            md.polygon(pts, fill=255, outline=255)
            v = int(min(255, 255 * lit[k] * 1.25)); sd.polygon(pts, fill=v, outline=v)
        from PIL import ImageChops
        layer = ImageChops.multiply(self._tex, Image.merge("RGB", [shade] * 3))
        self.img.paste(layer, (0, 0), mask); self.d = ImageDraw.Draw(self.img)

    def quad_image(self, corners3d, im):
        p, _ = self.proj(corners3d)
        w, h = im.size
        A = []; B = []
        for (x, y), (u, v) in zip(p, [(0, 0), (w, 0), (w, h), (0, h)]):
            A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B += [u, v]
        coef = np.linalg.solve(np.array(A, float), np.array(B, float))
        layer = im.transform((self.w, self.h), Image.PERSPECTIVE, tuple(coef), Image.BICUBIC)
        mask = Image.new("L", (self.w, self.h), 0)
        ImageDraw.Draw(mask).polygon([tuple(q) for q in p], fill=255)
        self.img.paste(layer, (0, 0), mask); self.d = ImageDraw.Draw(self.img)
    def shadow(self, pts):
        sh = Image.new("L", (self.w, self.h), 0)
        p, _ = self.proj(pts); ImageDraw.Draw(sh).polygon([tuple(q) for q in p], fill=170)
        sh = sh.filter(ImageFilter.GaussianBlur(24 * SS))
        self.img.paste(Image.new("RGB", (self.w, self.h), (0, 0, 0)), (0, 0), sh); self.d = ImageDraw.Draw(self.img)
    def label(self, xyz, text, size=11, fill=(235, 235, 240), anchor="mm"):
        p, z = self.proj([xyz])
        try: font = ImageFont.truetype("DejaVuSans-Bold.ttf", size * SS)
        except Exception: font = ImageFont.load_default()
        self.d.text(tuple(p[0]), text, fill=fill, font=font, anchor=anchor)
    def out(self, path, size):
        self.img.resize(size, Image.LANCZOS).save(path)

WOOD = (176, 122, 72)                                  # (only for flat-coloured wood; the cheeks use the dark stain below)
STAIN_BASE, STAIN_GRAIN = (22, 17, 14), (58, 44, 35)    # very dark stained hardwood: nearly black, the grain still shows


def stain_texture(w, h, angle, scale):
    """a full-frame dark-stained wood texture, grain running at `angle` (radians, screen space); scale = pixels per mm"""
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ca, sa = math.cos(angle), math.sin(angle)
    u = (xx * ca + yy * sa) / scale                          # mm along the grain
    v = (-xx * sa + yy * ca) / scale                         # mm across it
    def smooth(cells_u, cells_v, mag):
        n = rng.standard_normal((cells_v, cells_u)).astype(np.float32)
        im = Image.fromarray(((n - n.min()) / (np.ptp(n) + 1e-9) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        return (np.asarray(im, np.float32) / 255.0 - 0.5) * mag
    warp = smooth(3, 10, 16.0) + smooth(14, 5, 4.0)          # the growth rings wander and bunch up, as in real timber
    ring = 0.5 + 0.5 * np.sin(2 * np.pi * (v + warp) / 4.5)  # about 4.5 mm between rings on average
    lines = ring ** 3 * 0.30 + ring ** 18 * 0.55             # soft early wood, a darker-stained late-wood line
    lines *= 0.55 + 0.9 * (smooth(5, 12, 1.0) + 0.5)         # some stretches show more figure than others
    fib = rng.standard_normal(h + w).astype(np.float32)      # fine fibres: noise across the grain, stretched along it
    vi = np.clip(((v - v.min()) * 3.0).astype(int), 0, len(fib) - 1)
    lines = lines + 0.22 * fib[vi] * (0.5 + 0.5 * ring)
    lines = np.clip(lines + smooth(40, 30, 0.25), 0, 1.2)
    base, grain = np.array(STAIN_BASE, np.float32), np.array(STAIN_GRAIN, np.float32)
    col = base[None, None, :] + lines[..., None] * (grain - base)[None, None, :]
    return Image.fromarray(np.clip(col, 0, 255).astype(np.uint8))
BLACK = (40, 41, 46)                                  # one black filament for the body, lid, console and screen frame
KEY_COL = {0: (210, 50, 50), 1: (230, 120, 40), 2: (150, 154, 164), 3: (60, 190, 90), 4: (40, 140, 70), 14: (230, 200, 60)}

def accessories(lit):
    acc = []
    for i, (cx, cy) in enumerate(M.PAD_CENTERS):
        h = M.HOLE / 2 - 0.4
        acc.append((PR(boxm(cx - h, cy - h, TOP - 6, cx + h, cy + h, TOP + 3.0)), (34, 34, 40)))
        acc.append((PR(boxm(cx - h + 1.5, cy - h + 1.5, TOP + 3.0, cx + h - 1.5, cy + h - 1.5, TOP + 3.6)), (70, 120, 255) if i in lit else (22, 22, 26)))
    for x, y in M.POT_POS:
        acc.append((PR(cylm(x, y, 8.5, TOP, TOP + 15, 32)), (236, 236, 238))); acc.append((PR(cylm(x, y, 8.6, TOP + 15, TOP + 17, 32)), (205, 40, 40)))
    for k, (x, y, sz) in zip(M.KEY_BTN, M.KEY_POS):
        col = KEY_COL.get(k, (176, 180, 190) if 5 <= k <= 13 else ((112, 116, 130) if k < 20 else (70, 110, 190)))   # screen keys light, play keys dark, F keys blue
        acc.append((PR(boxm(x - 7.8, y - 7.8, TOP, x + 7.8, y + 7.8, TOP + 5.4)), (22, 22, 26)))      # MX switch housing
        cw, cd = M.cap_wh(sz)
        acc.append((PR(boxm(x - cw / 2, y - cd / 2, TOP + 5.6, x + cw / 2, y + cd / 2, TOP + 9.6)), col))  # printed cap (transport caps are wide)
    x, y, sz = M.SONG_POS
    acc.append((PR(boxm(x - 7.8, y - 7.8, TOP, x + 7.8, y + 7.8, TOP + 5.4)), (22, 22, 26)))
    acc.append((PR(boxm(x - sz / 2, y - sz / 2, TOP + 5.6, x + sz / 2, y + sz / 2, TOP + 9.6)), (176, 180, 190)))
    for (x, y, sz) in M.ARROW_POS + [M.OK_POS]:
        acc.append((PR(boxm(x - 7.8, y - 7.8, TOP, x + 7.8, y + 7.8, TOP + 5.4)), (22, 22, 26)))
        acc.append((PR(boxm(x - sz / 2, y - sz / 2, TOP + 5.6, x + sz / 2, y + sz / 2, TOP + 9.6)), (235, 150, 40) if (x, y) == (M.OK_POS[0], M.OK_POS[1]) else (88, 92, 104)))
    for x, z, d, lab in M.FRONT_HOLES:                         # headphone jack + level knob on the front edge
        f0 = -M.PR_D                                           # (now on the palm rest's front face)
        if lab == "PHONES": acc += [(ycyl(x, z, 6.3, f0 - 8, f0, 24), (200, 202, 210)), (ycyl(x, z, 3.3, f0 - 8.4, f0 - 8, 16), (18, 18, 22))]
        else: acc += [(ycyl(x, z, 6.0, f0 - 11, f0, 24), (60, 62, 70)), (ycyl(x, z, 1.0, f0 - 11.4, f0 - 11, 8), (230, 230, 235))]
    jx, jy = M.JOG_POS
    acc += [(PR(cylm(jx, jy, 25, TOP, TOP + 11, 56)), (60, 62, 70)), (PR(cylm(jx, jy, 24.5, TOP + 11, TOP + 12, 56)), (150, 152, 160)),
            (PR(cylm(jx, jy, 4, TOP + 12, TOP + 13, 20)), (30, 30, 34))]
    return acc

def world_frame(alpha):
    f = M.frame_pose(alpha)
    to_world = lambda tl: M.remap(tl, f, flip=True)          # local frame coordinates are mirrored relative to the world
    return to_world(M.frame_tray_local().t), to_world(M.frame_bezel().t), f

def back_panel():
    """chrome 1/4 inch jack bushings and the panel-mount ports on the console's back wall (world coordinates)"""
    yb = M.D + M.RISER_D
    chrome, dark = [], []
    for x in M.JACK_X_OUT:
        chrome += ycyl(x, M.JACK_Z_OUT, 6.3, yb, yb + 9, 24) + ycyl(x, M.JACK_Z_OUT, 7.5, yb, yb + 2.2, 6)
        dark += ycyl(x, M.JACK_Z_OUT, 3.3, yb + 9, yb + 9.4, 16)
    for x in M.JACK_X_IN:
        chrome += ycyl(x, M.JACK_Z_IN, 6.3, yb, yb + 9, 24) + ycyl(x, M.JACK_Z_IN, 7.5, yb, yb + 2.2, 6)
        dark += ycyl(x, M.JACK_Z_IN, 3.3, yb + 9, yb + 9.4, 16)
    for name, x, z, w, h in M.PORTS:
        chrome += boxm(x - w / 2 - 8, yb, z - h / 2 - 3, x + w / 2 + 8, yb + 1.2, z + h / 2 + 3)
        dark += boxm(x - w / 2, yb + 1.0, z - h / 2, x + w / 2, yb + 1.6, z + h / 2)
    bx, bz, bd = M.POWER_BTN
    chrome += ycyl(bx, bz, bd / 2 + 2, yb, yb + 1.5, 24); dark += ycyl(bx, bz, bd / 2 - 1, yb + 1.5, yb + 4, 24)
    for x in M.VENT_X:
        dark += boxm(x - 1.5, yb - 0.2, M.VENT_Z[0], x + 1.5, yb + 0.3, M.VENT_Z[1])
    return [(chrome, (200, 202, 210)), (dark, (18, 18, 22))]

def back_labels(sc):
    yb = M.D + M.RISER_D + 10
    for text, x, z, w in M.back_labels(): sc.label((x, yb, z), text, 8, (230, 232, 240))
    sc.label((sum(M.VENT_X) / len(M.VENT_X), yb, M.VENT_Z[1] + 6), "VENT (Pi 5 behind)", 8, (230, 232, 240))

CH_X = {0: (-M.CHEEK_T, 0.0), 1: (M.W, M.W + M.CHEEK_T)}
def cheek_tris(side):
    return M.cheek_world(side)
def cheek_extras(side):
    """the outer faces are plain flat wood: wood screws go in from the inside and the hinge rod sits in blind holes"""
    return [], []

def rear_accessories(vu=(9, 6)):
    """lights, VU meter windows, buttons and logo plate on the front of the rear console"""
    acc = []
    Y0 = M.D
    zr = lambda h: M.ZB + h
    for x, h, name in M.LEDS:
        col = {"PWR": (60, 235, 90), "PLAY": (60, 235, 90), "REC": (240, 60, 60)}[name]
        acc.append((ycyl(x, zr(h), M.LED_D / 2 + 0.4, Y0 - 1.2, Y0 + 0.5), col))
    for row, hrow in enumerate(M.VU_ROWS):
        for i in range(M.VU_N):
            cx = M.VU_X0 + i * M.VU_PITCH
            on = i < vu[row]
            col = ((60, 230, 90) if i < 8 else ((250, 200, 40) if i < 10 else (240, 60, 60))) if on else (30, 32, 38)
            acc.append((boxm(cx - M.VU_WIN[0] / 2, Y0 - 0.4, zr(hrow) - M.VU_WIN[1] / 2, cx + M.VU_WIN[0] / 2, Y0 + 1.4, zr(hrow) + M.VU_WIN[1] / 2), col))
    x0, x1, h0, h1 = M.LOGO
    acc.append((boxm(x0, Y0 - 0.2, zr(h0), x1, Y0 + 1.0, zr(h1)), (24, 26, 32)))
    return acc

_BADGE = None
def badge_image():
    """the badge as printed (once a logo is in brand/): light mark on a black plate; None while there is no logo"""
    global _BADGE
    if _BADGE is None:
        bw, bh = M.LOGO[1] - M.LOGO[0], M.LOGO[3] - M.LOGO[2]
        k = 12                                                    # px per mm
        img = Image.new("RGB", (int(bw * k), int(bh * k)), (18, 18, 22))
        if not os.path.exists(os.path.join(HERE, M.LOGO_ICON)): return None
        iw, ih = (bw - 2 * M.BADGE_MARGIN) * k, (bh - 2 * M.BADGE_MARGIN) * k
        col = os.path.join(HERE, "brand", "logo.png")
        if os.path.exists(col):                                   # the logo in its colours (brand/make_logo.py)
            lg = Image.open(col).convert("RGBA"); bb = lg.getbbox(); lg = lg.crop(bb) if bb else lg
            sc_ = min(iw / lg.width, ih / lg.height); lg = lg.resize((int(lg.width * sc_), int(lg.height * sc_)), Image.LANCZOS)
            img.paste(lg, ((img.width - lg.width) // 2, (img.height - lg.height) // 2), lg)
        else:
            m = Image.open(os.path.join(HERE, M.LOGO_ICON)).convert("L")
            sc_ = min(iw / m.width, ih / m.height); m = m.resize((int(m.width * sc_), int(m.height * sc_)), Image.LANCZOS)
            img.paste(Image.new("RGB", m.size, (226, 228, 236)), ((img.width - m.width) // 2, (img.height - m.height) // 2), m)
        _BADGE = img
    return _BADGE

def badge(sc):
    x0, x1, h0, h1 = M.LOGO
    zr = lambda h: M.ZB + h
    y = M.D - 0.15
    im = badge_image()
    if im is not None: sc.quad_image([(x0, y, zr(h1)), (x1, y, zr(h1)), (x1, y, zr(h0)), (x0, y, zr(h0))], im)

def draw(sc, screen, alpha, lit, labels=False, cheeks=True, cut_near=False, backlabels=False):
    sc.shadow([(x - 8, y + 8, -0.5) for x, y in [(-M.CHEEK_T - 6, -4), (M.W + M.CHEEK_T + 6, -4), (M.W + M.CHEEK_T + 6, M.D + 40), (-M.CHEEK_T - 6, M.D + 40)]])
    behind = sc.cam[1] > M.HINGE_Y                              # viewed from the back: the frame is in front of the body
    cx_ = sc.cam[0]
    outside = cx_ < 0 or cx_ > M.W
    near = (0 if cx_ < 0 else 1) if outside else None
    far = None if near is None else 1 - near
    def draw_cheek(side):
        sc.tris_textured(cheek_tris(side))                        # very dark stained hardwood
        scr, cap = cheek_extras(side)
        sc.tris_textured(cap)
    first_cheeks = [] if not cheeks else ([far] if near is not None else [0, 1])
    for s in first_cheeks:
        if s is not None: draw_cheek(s)
    sc.tris(M.base(joins=False).t, BLACK, horiz="first")
    sc.tris(M.palmrest().t, BLACK, horiz="first")                       # palm rest core
    pad = M.Mesh(); pad.prism(M.pad_outline(), 0.6, M.W - 0.6)                  # the vinyl pad: (y, z) profile along x
    sc.tris(M.remap(pad.t, lambda p: (p[2], p[0], p[1])), (34, 34, 38))
    sc.tris(M.lid_world(), BLACK, horiz="last")
    # one control = its parts in the order they are built (housing, then cap; knob, then its top), kept together and
    # drawn bottom-up; the controls far to near by their unrounded distance, so the order never flips between frames
    groups = []
    for tl, col in accessories(lit):
        c = np.mean([np.mean(t, 0) for t in tl], 0)
        if groups and np.hypot(*(groups[-1][0][:2] - c[:2])) < 3.0: groups[-1][1].append((tl, col))
        else: groups.append([c, [(tl, col)]])
    groups.sort(key=lambda g: -float(np.hypot(*(g[0][:2] - sc.cam[:2]))))
    objs = [(g[0], tl, col) for g in groups for tl, col in g[1]]
    def body_parts():
        if sc.cam[1] > M.D + M.RISER_D:                       # from behind: keys first (the console hides them), then the back panel
            for _, tl, col in objs: sc.tris(tl, col)
            sc.tris(M.riser().t, BLACK)
            for tl, col in back_panel(): sc.tris(tl, col)
        else:
            sc.tris(M.riser().t, BLACK)
            for tl, col in rear_accessories(): sc.tris(tl, col)
            badge(sc)
            for _, tl, col in objs: sc.tris(tl, col)
    def rod_parts():                                              # the rod sits in blind holes: it never shows outside the cheeks
        sp = xtube(M.HINGE_Y, M.HINGE_Z, M.SPACER[0] / 2, M.SPACER[1] / 2, 0, M.SPACER[2]) + \
             xtube(M.HINGE_Y, M.HINGE_Z, M.SPACER[0] / 2, M.SPACER[1] / 2, M.W - M.SPACER[2], M.W)
        sc.tris(sp, (90, 92, 100))
    def frame_parts(with_rod=True):
        tray, bezel, f = world_frame(alpha)
        if with_rod: rod_parts()
        sc.tris(tray, BLACK, horiz="last"); sc.tris(bezel, BLACK)
        if not behind and alpha > -60:
            u0, v0, u1, v1 = M.window_rect()
            sc.quad_image([f((u0, v1, 1.0)), f((u1, v1, 1.0)), f((u1, v0, 1.0)), f((u0, v0, 1.0))], window_image(screen))
    if alpha < -45: rod_parts(); body_parts(); frame_parts(False)    # folded down, the frame lies on top of everything
    elif behind: body_parts(); frame_parts()
    else: frame_parts(); body_parts()
    if labels:
        L = lambda x, s, h: M.R(x, s, h)
        short = {"PLAY START": "P.ST", "NOTE REPEAT": "RPT", "OVERDUB": "ODUB", "SAMPLE": "SMPL", "MIXER": "MIX"}
        for (x, y, sz), n in zip(M.KEY_POS, M.PANEL_KEYS): sc.label(L(x, y, TOP + 9.8), short.get(n, n), 9 if M.cap_wh(sz)[0] < 20 else 10, (20, 20, 24) if n in ("STOP", "SHIFT") or 5 <= M.KEY_NAMES.index(n) <= 13 else (245, 245, 245))
        for (x, y), n in zip(M.POT_POS, ["Q1", "Q2", "Q3", "Q4"]): sc.label(L(x, y + 13, TOP + 0.1), n, 9)
        sc.label(L(M.JOG_POS[0], M.JOG_POS[1], TOP + 13), "JOG", 10)
        for (x, y, _), n in zip(M.ARROW_POS, ["^", "v", "<", ">"]): sc.label(L(x, y, TOP + 9.8), n, 14, (235, 235, 240))
        sc.label(L(M.OK_POS[0], M.OK_POS[1], TOP + 9.8), "OK", 10, (30, 20, 10))
        sc.label(L(M.SONG_POS[0], M.SONG_POS[1], TOP + 9.8), "SONG", 9, (20, 20, 24))
        for x, z, d, lab in M.FRONT_HOLES: sc.label((x, -M.PR_D - 12, z + 11), lab, 8, (220, 222, 230))
        for i, (cx, cy) in enumerate(M.PAD_CENTERS): sc.label(L(cx, cy, TOP + 3.7), str(i + 1), 12, (140, 140, 150))
        zr = lambda h: M.ZB + h
        for x, h, name in M.LEDS: sc.label((x, M.D - 1.5, zr(h - 6)), name, 8, (200, 204, 214))
        sc.label((M.VU_X0 - 9, M.D - 1.5, zr(M.VU_ROWS[0])), "L", 9, (200, 204, 214)); sc.label((M.VU_X0 - 9, M.D - 1.5, zr(M.VU_ROWS[1])), "R", 9, (200, 204, 214))
    if backlabels: back_labels(sc)
    if cheeks and not cut_near:
        for s in ([near] if near is not None else []):
            draw_cheek(s)

def render(path, screen, alpha, az, el, dist, size=(1400, 900), focal=1500, target=(M.W / 2, M.D / 2 + 10, 70), labels=False, lit=(0, 1, 4, 9), **kw):
    sc = Scene(az, el, dist, size, focal, target)
    draw(sc, screen, alpha, lit, labels, **kw)
    sc.out(path, size); print("wrote", path)

def tilt_study(path, screen):
    tiles = []
    for alpha, name in ((-83, "closed (folded flat over the keys)"), (0, "upright"), (35, "leaning back")):
        sc = Scene(90, 4, 1000, (700, 520), 1500, (M.W / 2, M.D * 0.55, 85))
        draw(sc, screen, alpha, (), cut_near=True)
        sc.label((M.W / 2, M.D * 0.42, -4), name + "  (near cheek hidden)", 14, (255, 255, 255))
        tiles.append(sc.img.resize((700, 520), Image.LANCZOS))
    im = Image.new("RGB", (2100, 520)); [im.paste(t, (i * 700, 0)) for i, t in enumerate(tiles)]
    im.save(path); print("wrote", path)

if __name__ == "__main__":
    shots = os.path.join(HERE, "shots"); out = os.path.join(HERE, "renders"); os.makedirs(out, exist_ok=True)
    S = lambda n: os.path.join(shots, n)
    render(os.path.join(out, "render_hero.png"), S("02_seq.png"), 12, 32, 24, 790, size=(1500, 950), focal=1500, target=(M.W / 2, M.D / 2 + 10, 70))
    render(os.path.join(out, "render_front.png"), S("03_grid.png"), 8, 0, 20, 790, size=(1500, 900), focal=1500, labels=True)
    render(os.path.join(out, "render_low.png"), S("05_program.png"), 20, -40, 12, 760, size=(1400, 850), lit=(2, 3, 6, 13))
    render(os.path.join(out, "render_rear.png"), S("01_main.png"), 12, 205, 20, 760, size=(1500, 900))
    render(os.path.join(out, "render_bare.png"), S("07_chop.png"), 12, 32, 24, 790, size=(1500, 950), cheeks=False, lit=(3, 7, 11, 15))
    render(os.path.join(out, "render_top.png"), S("04_step.png"), 12, 0, 62, 800, size=(1500, 950), labels=True, cheeks=False)
    render(os.path.join(out, "render_rearview.png"), S("02_seq.png"), 12, 0, 10, 700, size=(1500, 800), focal=1700, labels=True, target=(M.W / 2, M.D, M.ZB + 10))
    render(os.path.join(out, "render_backpanel.png"), S("01_main.png"), 12, 180, 8, 700, size=(1500, 800), focal=1700, target=(M.W / 2, M.D + M.RISER_D, 50), backlabels=True)
    render(os.path.join(out, "render_closed.png"), S("01_main.png"), -83, 32, 24, 790, size=(1500, 950), focal=1500)
    tilt_study(os.path.join(out, "render_tilt.png"), S("09_fx.png"))
