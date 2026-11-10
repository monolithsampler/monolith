import sys, math, itertools
sys.path.insert(0, ".")
import make_stl as M
L, Rr = (0, M.SPLIT_X), (M.SPLIT_X, M.W)
for nm, fn in (("base", M.base), ("lid", M.lid)):
    full = fn(joins=False).volume(); parts = fn(L, joins=False).volume() + fn(Rr, joins=False).volume()
    print(nm, "split volume diff %.4f%%" % (100 * abs(full - parts) / full), "full vol", round(full))
for nm, m in [("cap_tr", M.keycap(M.CAP_TR)), ("cap18", M.keycap(18)), ("arrow", M.keycap(18, True))] + [(n, c) for n, c, _ in M.keycap_set()]:
    print(nm, "volume mm3", round(m.volume()), "(positive = valid orientation)")
sx = M.SPLIT_X
cells = [("pad%d" % i, cx, cy, M.HOLE / 2) for i, (cx, cy) in enumerate(M.PAD_CENTERS)]
cells += [("key", x, y, M.cap_wh(sz)[0] / 2, M.cap_wh(sz)[1] / 2) for x, y, sz in M.KEY_POS] + [("arrow", x, y, sz / 2) for x, y, sz in M.ARROW_POS] + [("ok", M.OK_POS[0], M.OK_POS[1], M.OK_POS[2] / 2), ("song", M.SONG_POS[0], M.SONG_POS[1], M.SONG_POS[2] / 2)]
cells += [("pot", x, y, 8.0) for x, y in M.POT_POS] + [("screw", x, y, 3.5) for x, y in M.SCREWS]
cells += [("join", sx + dx, y, 3.5) for y in M.JOIN_Y for dx in (-M.JOIN_DX, M.JOIN_DX)]
cells += [("jog", M.JOG_POS[0], M.JOG_POS[1], M.JOG_WHEEL_D / 2)]
def aabb(c):
    rx, ry = c[3], (c[4] if len(c) > 4 else c[3])
    return (c[1] - rx, c[2] - ry, c[1] + rx, c[2] + ry)
def overlaps(a, b, gap=0.0):
    A, B = aabb(a), aabb(b)
    return A[0] < B[2] + gap and B[0] < A[2] + gap and A[1] < B[3] + gap and B[1] < A[3] + gap
print("keys:", len(M.KEY_POS), "(23 expected: BANK has no key) + 4 arrows + OK + SONG =", len(M.KEY_POS) + 6, "MX switches")
print("cut by split:", [c[0] for c in cells if abs(c[1] - sx) < c[3] + 0.5 and c[0] not in ("join",)])
print("outside walls:", [(c[0], round(c[1]), round(c[2])) for c in cells if c[0] != "screw" and (c[1] - c[3] < 2.4 or c[1] + c[3] > M.W - 2.4 or c[2] - c[3] < 2.4 or c[2] + c[3] > M.SD + 0.01)])   # (front lid screws at y 4.5 merge their posts into the front wall on purpose)
ov = []
for a, b in itertools.combinations(cells, 2):
    if a[0].startswith("pad") and b[0].startswith("pad"): continue
    if overlaps(a, b, -0.01): ov.append((a[0], round(a[1]), round(a[2]), b[0], round(b[1]), round(b[2])))
print("overlaps (cap/hole squares, screws, jog circle as box):", ov)
# smallest gap between neighbouring caps
mg = 99
for a, b in itertools.combinations([c for c in cells if c[0] in ("key", "arrow", "ok", "song")], 2):
    if abs(a[2] - M.TR_Y) < 1e-6 and abs(b[2] - M.TR_Y) < 1e-6: continue
    A, B = aabb(a), aabb(b)
    gx, gy = max(B[0] - A[2], A[0] - B[2]), max(B[1] - A[3], A[1] - B[3])
    mg = min(mg, max(gx, gy))
print("smallest gap between neighbouring caps: %.1f mm (the transport bar's own 1 mm joints excluded)" % mg)
ux, uy = M.UNO_ORIGIN
boxes = [("uno", ux, uy, ux + 68.6, uy + 53.4), ("sr", M.SR_BOARD[0], M.SR_BOARD[1], M.SR_BOARD[0] + M.SR_BOARD[2], M.SR_BOARD[1] + M.SR_BOARD[3])]
for c in cells:
    if c[0] in ("screw", "join"):
        x, y = c[1], c[2] * M.C_
        for bx in boxes:
            if bx[1] - 3.5 < x < bx[3] + 3.5 and bx[2] - 3.5 < y < bx[4] + 3.5: print("POST INSIDE", c[0], bx[0], round(x), round(y))
print("uno vs pad posts:", [i for i, (cx, cs) in enumerate(M.PAD_CENTERS) if ux < cx + 11 and cx - 11 < ux + 68.6 and uy < cs * M.C_ + 11 and cs * M.C_ - 11 < uy + 53.4])
print("SR board vs uno overlap:", boxes[0][1] < boxes[1][3] and boxes[1][1] < boxes[0][3] and boxes[0][2] < boxes[1][4] and boxes[1][2] < boxes[0][4], "; SR board right edge", boxes[1][3], "< wall", M.W - M.WALL)
for (x, y) in [(ux, uy), (ux, uy + 53.4), (ux + 68.6, uy), (ux + 68.6, uy + 53.4)]:
    print("  height under lid at (%d,%d): %.1f" % (x, y, M.plane(x, y) - M.FLOOR))
# split pieces must fit a 220 mm bed
print("lid halves along x:", M.SPLIT_X, M.W - M.SPLIT_X, "(<220 ok)")
# frame sweep in panel coords
pts = [(u, v, t) for u in list(range(0, int(M.FR_W) + 1, 8)) + [M.FR_W] for v in list(range(0, int(M.FR_H) + 1, 8)) + [M.FR_H] for t in range(0, int(M.FR_T) + 1, 6)]
pts += [(u, v, t) for u in (M.EAR_U, M.EAR_U + 4, M.EAR_U + 8, M.FR_W - M.EAR_U - 8, M.FR_W - M.EAR_U - 4, M.FR_W - M.EAR_U) for v in (-19, -10, 0) for t in (M.AX_T - 9, M.AX_T, M.AX_T + 9)]
obst = [("pad", cx - 15.5, cy - 15.5, cx + 15.5, cy + 15.5, 3.6) for cx, cy in M.PAD_CENTERS]
obst += [("knob", x - 7.5, y - 7.5, x + 7.5, y + 7.5, 17) for x, y in M.POT_POS]
obst += [("key", x - M.cap_wh(sz)[0] / 2, y - M.cap_wh(sz)[1] / 2, x + M.cap_wh(sz)[0] / 2, y + M.cap_wh(sz)[1] / 2, 10.0) for x, y, sz in M.KEY_POS + M.ARROW_POS + [M.OK_POS, M.SONG_POS]]
obst.append(("jog", M.JOG_POS[0] - 25, M.JOG_POS[1] - 25, M.JOG_POS[0] + 25, M.JOG_POS[1] + 25, 13))
obst.append(("lid", 0, 0, M.W, M.SD, 0))
def topanel(p):
    x, y, z = p; zz = z - M.FRONT_Z
    return x, y * M.C_ + zz * M.S_, -y * M.S_ + zz * M.C_
def riser_top(y): return M.RT if y <= M.RYK else M.RT + (M.RZB - M.RT) * (y - M.RYK) / (M.D + M.RISER_D - M.RYK)
ear_u = [(M.EAR_U, M.EAR_U + 10), (M.FR_W - M.EAR_U - 10, M.FR_W - M.EAR_U)]
def is_ear(p): return p[1] < 0 and any(a <= p[0] <= b for a, b in ear_u)
worst = {}
for al in range(-90, 71, 5):
    f = M.frame_pose(al); mn = 1e9; who = None
    for p in pts:
        x, s, h = topanel(f(p))
        for o in obst:
            if o[1] <= x <= o[3] and o[2] <= s <= o[4]:
                c_ = h - (M.LID + o[5])
                if c_ < mn: mn, who = c_, (o[0], tuple(round(q, 1) for q in p))
        if not is_ear(p):
            wx, wy, wz = f(p)
            if M.D <= wy <= M.D + M.RISER_D:                  # inside the console's footprint: must be above its top surface
                c_ = wz - riser_top(wy)
                if c_ < mn: mn, who = c_, ("console", tuple(round(q, 1) for q in p))
    worst[al] = (round(mn, 1), who)
for al in (-85, -60, -20, 0, 20, 30, 40, 45, 70): print("frame angle", al, "min clearance mm:", worst.get(al))
okk = sorted(a for a, (c_, _) in worst.items() if c_ > 1.0)
print("angles with >1 mm clearance:", okk)
blocked = [a for a in sorted(worst) if a not in okk]
print("blocked angles:", blocked)
f = M.frame_pose(0); xs = [f(p)[0] for p in pts]; print("frame x span", round(min(xs), 1), round(max(xs), 1), "between cheeks 0..", M.W)
print("spacer length", M.SPACER[2], "ear starts at", M.FR_X0 + M.EAR_U, "gap", round(M.FR_X0 + M.EAR_U - M.SPACER[2], 2), "rod", M.ROD_LEN)
print("cheek screw spacing ok; y range", M.CHEEK_SCREW_Y[0] - 6, M.CHEEK_SCREW_Y[-1] + 6, "< D", round(M.D, 1))
ex = M.ear_x()
print("ear slots", ex, "| badge pocket x", M.LOGO[:2], "| lights x", [l[0] for l in M.LEDS], "| VU x", M.VU_X0 - M.VU_WIN[0] / 2, M.VU_X0 + (M.VU_N - 1) * M.VU_PITCH + M.VU_WIN[0] / 2, "| cable slot", M.CABLE_X)
print("console face clear of the ear slots:", M.LOGO[1] + 5 <= ex[0][0] and all(not (a - 4 < l[0] < b + 4) for l in M.LEDS for a, b in ex)
      and ex[0][1] < M.VU_X0 - M.VU_WIN[0] / 2 and M.VU_X0 + (M.VU_N - 1) * M.VU_PITCH + M.VU_WIN[0] / 2 < ex[1][0])
