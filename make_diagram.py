#!/usr/bin/env python3
"""Writes wiring_diagram.svg"""
import make_stl as M

out = []
def add(s): out.append(s)
def text(x, y, s, size=15, anchor="start", weight="normal", fill="#1d1d1f"):
    add(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="{fill}">{s}</text>')
def rect(x, y, w, h, fill="#fff", stroke="#333", sw=2, rx=8, dash=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
def line(x1, y1, x2, y2, col="#333", sw=2, arrow=False, dash=""):
    m = ' marker-end="url(#ar)"' if arrow else ""
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="{sw}"{m}{d}/>')
def circle(x, y, r, fill="#fff", stroke="#333", sw=2):
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
def box(x, y, w, h, title, sub="", fill="#eef3ff"):
    rect(x, y, w, h, fill=fill)
    text(x + w / 2, y + (h / 2 - 2 if sub else h / 2 + 5), title, 16, "middle", "bold")
    if sub: text(x + w / 2, y + h / 2 + 18, sub, 13, "middle", fill="#555")

W_, H_ = 900, 3800
add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W_} {H_}" font-family="Helvetica, Arial, sans-serif">')
add('<defs><marker id="ar" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">'
    '<path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker></defs>')
add(f'<rect width="{W_}" height="{H_}" fill="#ffffff"/>')

# ---------------- 1. system ----------------
text(30, 40, "Sampler build - wiring and layout", 26, weight="bold")
text(30, 66, "Arduino Uno scans the panel; the Pi 5 runs Monolith. Pi 5 + DAC8x / ADC8x + jacks: rear console. Hinged frame: 10.1 in screen only.", 15, fill="#555")
text(30, 110, "1. System overview", 20, weight="bold")
box(30, 140, 170, 70, "16 piezo pads", "1M + 5.1V zener each")
box(250, 140, 150, 70, "CD4067 mux", "16 channels -> 1")
box(450, 140, 150, 70, "Arduino Uno", "scans, sends USB serial")
box(650, 140, 220, 70, "Raspberry Pi 5 (rear console)", "sampler_os.py + VST3 FX", "#e9f7ec")
box(450, 270, 150, 70, "4 knobs + 24 keys + lights", "A1-A4; 3 x 74HC165 D2-D4; LEDs D5", "#fff6e5")
box(650, 270, 220, 70, "HiFiBerry DAC8x + ADC8x", "8 outs, 8 ins (2 wired)", "#e9f7ec")
box(650, 390, 220, 60, "Speaker / headphones", "", "#f3f3f3")
box(250, 270, 150, 70, "micro:bit (optional)", "tilt = filter, drive", "#f6eefc")
box(450, 390, 150, 60, "Line-in source", "(optional, to sample)", "#f3f3f3")
box(30, 270, 170, 70, "10.1 in touch display", "HDMI video + USB touch", "#e9f7ec")
box(30, 390, 170, 60, "D-pad + OK + jog wheel", "ribbon to Pi GPIO (sect. 6)", "#fff6e5")
line(200, 175, 250, 175, arrow=True); text(225, 165, "16", 13, "middle")
line(400, 175, 450, 175, arrow=True); text(425, 165, "A0", 13, "middle")
line(525, 270, 525, 210, arrow=True)
line(600, 175, 650, 175, arrow=True); text(625, 160, "USB", 13, "middle")
line(760, 210, 760, 270, arrow=True); text(790, 245, "HAT", 13)
line(760, 340, 760, 390, arrow=True); text(790, 370, "8 outs", 13)
for (a, b), (c, d) in zip([(325, 340), (325, 372), (625, 372), (625, 200)], [(325, 372), (625, 372), (625, 200), (650, 200)]):
    line(a, b, c, d, dash="6 4", arrow=(c, d) == (650, 200))
text(400, 392, "USB (optional)", 13)
line(600, 415, 650, 330, arrow=True); text(612, 398, "in", 13)

# ---------------- 2. Uno <-> mux ----------------
text(30, 500, "2. Arduino Uno to CD4067 multiplexer", 20, weight="bold")
rect(60, 520, 190, 290, "#eef3ff")
text(155, 548, "Arduino Uno", 17, "middle", "bold")
rect(520, 520, 200, 290, "#eef3ff")
text(620, 548, "CD4067", 17, "middle", "bold")
rows = [("D6", "A  (pin 10)", "#d33"), ("D7", "B  (pin 11)", "#e80"), ("D8", "C  (pin 13)", "#cb0"),
        ("D9", "D  (pin 14)", "#3a3"), ("A0", "COM (pin 1)", "#06c"), ("5V", "VDD (pin 24)", "#d00"),
        ("GND", "VSS (pin 12)", "#111"), ("GND", "INH (pin 15)", "#111")]
for i, (u, m, c) in enumerate(rows):
    y = 580 + i * 31
    text(240, y + 5, u, 15, "end", "bold")
    line(250, y, 520, y, col=c, sw=3)
    text(530, y + 5, m, 15)
text(620, 835, "I0 ... I15 -> pad 1 ... pad 16", 15, "middle", "bold")
text(620, 855, "pins 9,8,7,6,5,4,3,2,23,22,21,20,19,18,17,16", 13, "middle", fill="#555")
text(620, 875, "(check against your chip's datasheet)", 13, "middle", fill="#555")
text(30, 905, "Add a 100 nF capacitor across VDD-VSS right at the chip.", 14, fill="#555")

# ---------------- 3. one pad ----------------
text(30, 960, "3. One pad (build 16 of these)", 20, weight="bold")
x0, ytop, ybot = 120, 1010, 1130
line(40, ytop, 520, ytop, col="#06c", sw=3); text(40, ytop - 10, "to mux input I(n)", 14)
line(40, ybot, 520, ybot, col="#111", sw=3); text(40, ybot + 24, "GND", 14, weight="bold")
# piezo
px = 170
line(px, ytop, px, 1050); circle(px, 1072, 22, "#fde9c9"); text(px, 1077, "~", 20, "middle", "bold")
line(px, 1094, px, ybot); text(px, 1165, "piezo disc", 14, "middle"); text(px + 28, 1062, "+ (red)", 12)
# resistor
rx = 300
line(rx, ytop, rx, 1040); rect(rx - 10, 1040, 20, 65, "#fff", rx=3); line(rx, 1105, rx, ybot)
text(rx, 1165, "1 M ohm", 14, "middle")
# zener
zx = 430
line(zx, ytop, zx, 1045)
add(f'<polygon points="{zx-14},1045 {zx+14},1045 {zx},1075" fill="#fff" stroke="#333" stroke-width="2"/>')
line(zx - 16, 1077, zx + 16, 1077, sw=3); line(zx, 1077, zx, ybot)
text(zx, 1165, "5.1 V zener (bar up)", 14, "middle")
for xx in (px, rx, zx): circle(xx, ytop, 4, "#333"); circle(xx, ybot, 4, "#333")
text(30, 1200, "Piezo, resistor and zener all sit in parallel. Solder them together at the piezo,", 14, fill="#555")
text(30, 1220, "then run two wires (signal + GND) to the multiplexer board.", 14, fill="#555")

# ---------------- 4. pots + buttons ----------------
text(30, 1275, "4. Knobs and buttons", 20, weight="bold")
# pot
rect(100, 1300, 130, 60, "#fff6e5"); text(165, 1336, "10k pot", 15, "middle", "bold")
line(100, 1315, 60, 1315); text(56, 1320, "5V", 13, "end", "bold")
line(230, 1315, 280, 1315); text(286, 1320, "GND", 13, "start", "bold")
line(165, 1360, 165, 1395, arrow=True); text(165, 1415, "wiper -> A1 / A2 / A3 / A4  (Q1-Q4)", 14, "middle")
text(165, 1435, "(same wiring for all four)", 13, "middle", fill="#555")
add('<g transform="translate(0,50)">')
text(30, 1420, "24 keys on three 74HC165 shift registers (only 3 Arduino pins: D2 latch, D3 clock, D4 data)", 16, weight="bold")
cx0 = [40, 330, 620]
for k in range(3):
    rect(cx0[k], 1450, 240, 150, "#eef3ff"); text(cx0[k] + 120, 1472, f"74HC165 #{k+1} (keys {k*8}-{k*8+7})", 12, "middle", "bold")
    names = [n if n in M.PANEL_KEYS else "(free: no key)" for n in M.KEY_NAMES[k * 8:k * 8 + 8]]
    for i, n in enumerate(names):
        text(cx0[k] + 10, 1494 + i * 13, f"{'ABCDEFGH'[i]}  (pin {[11,12,13,14,3,4,5,6][i]}) = {n}", 11, fill="#333")
line(30, 1625, 870, 1625, col="#d33", sw=3); text(30, 1618, "D2 -> SH/LD pin 1 of all three chips", 12, fill="#d33")
line(30, 1645, 870, 1645, col="#06c", sw=3); text(30, 1638, "D3 -> CLK pin 2 of all three chips", 12, fill="#06c")
text(30, 1672, "Chain:  chip 3 SER (pin 10) -> GND;  chip 3 QH (pin 9) -> chip 2 SER;  chip 2 QH -> chip 1 SER;  chip 1 QH -> D4.", 12, weight="bold")
text(30, 1690, "Every chip: VCC pin 16 -> 5V, GND pin 8 -> GND, CLK INH pin 15 -> GND, 100 nF across VCC/GND.", 12, fill="#555")
# one switch
rect(60, 1715, 330, 80, "#fff", sw=1)
line(80, 1735, 300, 1735, col="#d00"); text(80, 1729, "5V", 11, fill="#d00"); rect(150, 1727, 40, 16, "#fff", rx=2); text(170, 1739, "10k", 11, "middle")
line(170, 1743, 170, 1775); circle(170, 1760, 3, "#333"); line(170, 1775, 260, 1775); circle(262, 1775, 5, "#333"); line(266, 1771, 300, 1760); circle(304, 1775, 5, "#333"); line(309, 1775, 380, 1775)
text(170, 1790, "to chip input A..H", 11, "start"); text(310, 1765, "MX switch", 11, "start"); text(385, 1780, "GND", 11, "start", "bold")
text(430, 1735, "Each of the 24 keys: one MX switch between its input and GND,", 13); text(430, 1753, "plus a 10k pull-up from that input to 5V (use 3 x 9-pin 10k", 13); text(430, 1771, "bussed resistor networks, common pin to 5V). 30 MX switches", 13); text(430, 1789, "total: 24 here + 4 arrows, OK and SONG (Pi).", 13)

add('</g>')
text(30, 1866, "Rear lights: WS2812 strip data -> D5 via 330 ohm, 5V + GND, 470 uF across the strip.", 12, fill="#555")
text(30, 1882, "26 pixels: 0-11 VU left, 12-23 VU right, 24 PLAY, 25 REC. Plain green power LED: 5V-330R-LED-GND.", 12, fill="#555")
# ---------------- 5. layout ----------------
text(30, 1915, "5. Top panel layout (to scale, along the 7 deg slope)", 20, weight="bold")
S = 2.7; OX, OY = 40, 1955
def X(x): return OX + x * S
def Y(y): return OY + (M.SD - y) * S        # front (y=0) at the bottom of the drawing
rect(X(0), Y(M.SD), M.W * S, M.SD * S, "#f7f7f7", sw=3, rx=4)
ux, uy = M.UNO_ORIGIN
for n, (cx, cy) in enumerate(M.PAD_CENTERS, 1):
    rect(X(cx - M.HOLE / 2), Y(cy + M.HOLE / 2), M.HOLE * S, M.HOLE * S, "#dfe8ff", sw=2, rx=3)
    text(X(cx), Y(cy) + 6, str(n), 18, "middle", "bold")
rect(X(ux), Y(uy + 53.4), 68.6 * S, 53.4 * S, "#e9f7ec", sw=2, rx=3, dash="6 4")
text(X(ux + 34), Y(uy + 26) + 4, "Arduino Uno", 13, "middle", "bold"); text(X(ux + 34), Y(uy + 26) + 20, "(USB end left)", 11, "middle", fill="#555")
mx, my, mw, md = M.SR_BOARD
rect(X(mx), Y(my + md), mw * S, md * S, "#fff", sw=2, rx=3, dash="6 4")
text(X(mx + mw / 2), Y(my + md / 2), "3 x 74HC165 board (floor)", 12, "middle", "bold")
add(f'<rect x="{X(M.BACK_NOTCH[0])}" y="{Y(M.SD)-2}" width="{(M.BACK_NOTCH[1]-M.BACK_NOTCH[0])*S}" height="9" fill="#fff" stroke="#c33" stroke-width="2"/>')
text(X(sum(M.BACK_NOTCH) / 2), Y(M.SD) + 22, "cable slot", 11, "middle", fill="#c33")
add(f'<line x1="{X(M.SPLIT_X)}" y1="{Y(M.SD)-8}" x2="{X(M.SPLIT_X)}" y2="{Y(0)+8}" stroke="#c33" stroke-width="2" stroke-dasharray="10 5"/>')
text(X(M.SPLIT_X) + 4, Y(0) + 22, "split line (print as 2 halves)", 11, fill="#c33")
for jy in M.JOIN_Y:
    for jx in (M.SPLIT_X - M.JOIN_DX, M.SPLIT_X + M.JOIN_DX): circle(X(jx), Y(jy), 3.5, "#c33", "#c33", 1)
jx, jy = M.JOG_POS
circle(X(jx), Y(jy), M.JOG_WHEEL_D / 2 * S, "#f0f0f5", "#555", 2); circle(X(jx), Y(jy), 9, "#fff", "#333", 2)
text(X(jx), Y(jy) + 4, "JOG", 12, "middle", "bold"); text(X(jx), Y(jy) + 44, "50 mm wheel", 11, "middle", fill="#555")
for (ax, ay, sz), nm in zip(M.ARROW_POS, ["&#8593;", "&#8595;", "&#8592;", "&#8594;"]):
    rect(X(ax - sz / 2), Y(ay + sz / 2), sz * S, sz * S, "#e4f4e4", sw=2, rx=4); text(X(ax), Y(ay) + 6, nm, 18, "middle", "bold")
sx_, sy_, ssz = M.SONG_POS
rect(X(sx_ - ssz / 2), Y(sy_ + ssz / 2), ssz * S, ssz * S, "#e4f4e4", sw=2, rx=4); text(X(sx_), Y(sy_) - 2, "Pi", 11, "middle", "bold"); text(X(sx_), Y(sy_) + 11, "SONG", 9, "middle", fill="#444")
ox, oy, osz = M.OK_POS
rect(X(ox - osz / 2), Y(oy + osz / 2), osz * S, osz * S, "#ffe9c9", sw=2, rx=4); text(X(ox), Y(oy) + 5, "OK", 14, "middle", "bold")
for (cx, cy) in M.POT_POS:
    circle(X(cx), Y(cy), 7.5 * S, "#fff6e5"); text(X(cx), Y(cy) + 4, "Q", 12, "middle", "bold")
for k, (cx, cy, sz), nm in zip(M.KEY_BTN, M.KEY_POS, M.PANEL_KEYS):
    cw, cd = M.cap_wh(sz)
    rect(X(cx - cw / 2), Y(cy + cd / 2), cw * S, cd * S, "#fde9e9" if k < 5 else "#f3f3f8", sw=2, rx=4)
    text(X(cx), Y(cy) - 2, f"B{k}", 11, "middle", "bold"); text(X(cx), Y(cy) + 11, nm.replace("NOTE ", "N."), 9, "middle", fill="#444")
for (cx, cy) in M.SCREWS: circle(X(cx), Y(cy), 5, "#999", "#555", 1)
rect(X(M.FR_X0), Y(M.SD) - 6, M.FR_W * S, 12 * S, "none", stroke="#38c", sw=2, rx=3, dash="4 3")
text(X(M.W / 2), Y(M.SD) - 12, "hinged display frame pivots on the rod behind the panel", 11, "start", fill="#38c")
text(X(M.W / 2), Y(0) + 40, "FRONT (you play from here)", 15, "middle", "bold")
for x, z, dd, lab in M.FRONT_HOLES:
    circle(X(x), Y(0) + 14, dd / 2 * S, "#fff", "#c60", 2); text(X(x), Y(0) + 36, lab, 10, "middle", "bold", fill="#c60")
text(X(M.W / 2), Y(0) + 60, "grey dots = lid screws M3 x 10, red = split straps (under the lid). Full-size copy: panel_artwork.svg", 12, "middle", fill="#555")

# ---------------- 5a. rear console front face ----------------
fy0 = Y(0) + 100
text(30, fy0, "5a. Rear console, front face (to scale): logo, lights, VU meter, between the two hinge ears", 20, weight="bold")
FS = 2.7; FX0, FY0 = 40, fy0 + 30
fh = M.FASCIA_H
rect(FX0, FY0, M.W * FS, fh * FS, "#f7f7f7", sw=3, rx=3)
FY = lambda h: FY0 + (fh - h) * FS
rect(FX0 + M.LOGO[0] * FS, FY(M.LOGO[3]), (M.LOGO[1] - M.LOGO[0]) * FS, (M.LOGO[3] - M.LOGO[2]) * FS, "#e6e6ee", sw=2, rx=3); text(FX0 + (M.LOGO[0] + M.LOGO[1]) / 2 * FS, FY((M.LOGO[2] + M.LOGO[3]) / 2) + 5, "logo", 14, "middle", "bold")
for x, h, nm in M.LEDS:
    circle(FX0 + x * FS, FY(h), M.LED_D / 2 * FS, "#cfeccf" if nm != "REC" else "#f6cccc"); text(FX0 + x * FS, FY(h - 6.5) + 4, nm, 10, "middle")
for row, hrow in enumerate(M.VU_ROWS):
    for i in range(M.VU_N):
        cx = M.VU_X0 + i * M.VU_PITCH
        rect(FX0 + (cx - M.VU_WIN[0] / 2) * FS, FY(hrow + M.VU_WIN[1] / 2), M.VU_WIN[0] * FS, M.VU_WIN[1] * FS, "#cfeccf" if i < 8 else ("#fbeeb4" if i < 10 else "#f6cccc"), sw=1, rx=1)
    text(FX0 + (M.VU_X0 - 9) * FS, FY(hrow) + 4, "LR"[row], 12, "middle", "bold")
text(FX0, FY0 + fh * FS + 22, "VU windows 7 x 4 mm at 10 mm pitch (WS2812 strip behind, diffuser tape); LEDs 5 mm.", 11, fill="#555")

# ---------------- 5b. side profile ----------------
yf = Y(0) + 100 + 190
text(30, yf, "5b. Side view: wedge body, wooden cheek and hinge rod (to scale)", 20, weight="bold")
S2 = 2.2; sx0, sy0 = 210, yf + 330
def SX(y): return sx0 + y * S2
def SZ(z): return sy0 - z * S2
prof = M.cheek_profile()
add('<polygon points="' + " ".join(f"{SX(y):.1f},{SZ(z):.1f}" for y, z in prof) + '" fill="#e8c99a" stroke="#8a5a2b" stroke-width="2"/>')
bt = [(0, 0), (M.D, 0), (M.D, M.plane(0, M.D) + M.LID), (0, M.plane(0, 0) + M.LID)]
add('<polygon points="' + " ".join(f"{SX(y):.1f},{SZ(z):.1f}" for y, z in bt) + '" fill="#8c8f9a" fill-opacity="0.85" stroke="#333" stroke-width="2"/>')
pr = [(-M.PR_D, 0), (0, 0), (0, M.PR_CORE), (-M.PR_D, M.PR_CORE)]
add('<polygon points="' + " ".join(f"{SX(y):.1f},{SZ(z):.1f}" for y, z in pr) + '" fill="#8c8f9a" fill-opacity="0.85" stroke="#333" stroke-width="2"/>')
add('<polygon points="' + " ".join(f"{SX(y):.1f},{SZ(z):.1f}" for y, z in M.pad_outline()) + '" fill="#222" stroke="#000" stroke-width="1.5"/>')
text(SX(-M.PR_D / 2), SZ(M.PR_TOP) - 10, "padded vinyl palm rest", 13, "middle", fill="#333")
rs = [(M.D, 0), (M.D + M.RISER_D, 0), (M.D + M.RISER_D, M.RZB), (M.RYK, M.RT), (M.D, M.RT)]
add('<polygon points="' + " ".join(f"{SX(y):.1f},{SZ(z):.1f}" for y, z in rs) + '" fill="#6d7080" fill-opacity="0.9" stroke="#333" stroke-width="2"/>')
text(SX(M.D) - 8, SZ(M.RT) + 62, "rear console: rod, Pi 5 + HAT, jacks", 13, "end", fill="#333")
circle(SX(M.HINGE_Y), SZ(M.HINGE_Z), 4.3 * S2, "#fff", "#333", 2)
for y in M.CHEEK_SCREW_Y: circle(SX(y), SZ(M.CHEEK_SCREW_Z), 3 * S2, "#d9b84a", "#7a6310", 1)
text(SX(M.HINGE_Y) - 12, SZ(M.HINGE_Z) - 22, "M8 rod: frame pivots here", 13, "end", fill="#333")
text(SX(40), SZ(60), "wooden cheek, %.0f mm timber" % M.CHEEK_T, 13, fill="#7a4a1b")
text(SX(0), SZ(2) + 22, "panel slopes %.0f deg; 4 wood screws per side through the wall; full-size template: cheek_template.svg" % M.TILT, 12, fill="#555")
fx, fy = 612, yf + 150
rect(fx, fy, 230, 40, "#eef3ff", sw=2, rx=3); text(fx + 115, fy + 25, "frame: 7 in display only", 13, "middle", "bold")
text(fx, fy + 62, "jacks, ports, Pi + HAT: in the rear console", 11, "start", fill="#38c")
text(fx, fy + 80, "frame %.0f x %.0f x %.0f mm, ears on the M8 rod" % (M.FR_W, M.FR_H, M.FR_T), 11, "start", fill="#555")
text(fx, fy + 98, "nuts give friction; closed (-90) to +45 deg", 11, "start", fill="#555")
text(fx, fy + 116, "only 2 thin cables cross the hinge:", 11, "start", fill="#555")
text(fx, fy + 134, "micro-HDMI + USB (touch and power)", 11, "start", fill="#555")
fy = yf + 330 - 150
y0 = yf + 400
text(30, y0, "6. D-pad, OK, jog wheel and SONG key to the Raspberry Pi GPIO (BCM numbers)", 20, weight="bold")
import inputs as _in
pin_no = {5: 29, 6: 31, 13: 33, 12: 32, 16: 36, 17: 11, 10: 19, 9: 21, 11: 23}
names = [("up", "Arrow UP"), ("down", "Arrow DOWN"), ("left", "Arrow LEFT"), ("right", "Arrow RIGHT"), ("ok", "OK (centre of the D-pad)"),
         ("jog_a", "Jog A (CLK)"), ("jog_b", "Jog B (DT)"), ("jog_push", "Jog push"), ("song", "SONG key")]
gp = [(lab, f"BCM {_in.PINS[k]} (pin {pin_no[_in.PINS[k]]})") for k, lab in names]
gp += [("Other side of every switch + encoder common", "any GND pin (e.g. pin 6, 9, 14, 20)")]
for i, (a, b) in enumerate(gp):
    yy = y0 + 30 + i * 26
    text(60, yy, a, 15, weight="bold"); text(420, yy, b, 15)
yn = y0 + 30 + len(gp) * 26 + 8
text(30, yn, "GPIO 2-4 and 18-27 are kept free for the DAC8x + ADC8x. Keep SPI off (9, 10, 11).", 14, fill="#c33")
text(30, yn + 22, "No resistors: the Pi's internal pull-ups are used. Switches and the encoder connect the pin to GND.", 14, fill="#555")
text(30, yn + 44, "The Pi sits in the rear console: a 10-wire ribbon (9 signals + ground) from the body through the back-wall slot to the header.", 14, fill="#555")
y7 = yn + 90
text(30, y7, "7. Power button, headphones, back panel", 20, weight="bold")
text(30, y7 + 30, "POWER: 12 mm momentary button on the back -> the Pi 5's 2-pin J2 'power button' header. Press = start / clean shut-down; hold = force off.", 13)
text(30, y7 + 52, "PHONES: small stereo headphone amp board on the floor behind the front-right corner, input from OUT 1/2 (parallel with the jacks),", 13)
text(30, y7 + 70, "its 9 mm level pot through the front wall (LEVEL), 1/4 inch stereo jack next to it (PHONES). Power it from the 5 V rail.", 13)
text(30, y7 + 92, "BACK, as you face it, left to right: POWER, 5V IN (USB-C), LAN, USB | IN L, IN R; below: OUT 1 ... OUT 8; vents behind the Pi.", 13)
text(30, y7 + 110, "All names are engraved into the wall. Audio: 5 short 3.5 mm stereo leads, cut, each soldered to two mono 1/4 inch jacks:", 13)
text(30, y7 + 128, "DAC8x jack 1/2 -> OUT 1 + OUT 2, 3/4 -> OUT 3 + 4, 5/6 -> OUT 5 + 6, 7/8 -> OUT 7 + 8; ADC8x input 1/2 -> IN L + IN R.", 13)
text(30, y7 + 146, "In each lead: tip -> tip of the odd jack (OUT 1, 3, 5, 7 / IN L), ring -> tip of the even jack, sleeve -> both sleeves. No other ground wires.", 13)
add("</svg>")
open("wiring_diagram.svg", "w").write("\n".join(out))
print("ok")
