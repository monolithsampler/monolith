#!/usr/bin/env python3
"""
Generates every 3D-printable part for the sampler (sloped wedge body, wedge wooden cheeks, hinged 10.1 inch display, MX-switch key panel,
padded palm rest, rear console with the Pi 5 and the back panel)
as binary STL.   No libraries needed:   python3 make_stl.py
Edit the CONFIG block (mm) and re-run to change sizes.

BODY (pads, controls, Arduino, mux) - sloped top panel, cut in two so each piece fits a 220 mm bed:
  controller_base_left.stl / controller_base_right.stl   print 1x each
  controller_lid_left.stl  / controller_lid_right.stl    print 1x each (already flipped: smooth side down)
  join_strap.stl         print 10x (2 across the base posts, 2 under the lid, 2 inside the rear console, 1 under the palm rest,
                         3 inside the display tray;
                         screws go UP into blind pilots: nothing shows on top)
KEYCAPS (Cherry MX stem, print face down, 0.12-0.16 layers):
  keycaps_all.stl        print 1x  (ALL 29 caps on one bed, each with its name engraved in the top; arrows for the D-pad)
  keycaps/keycap_<name>.stl          one file per labelled cap, to reprint a single key
  keycap_transport.stl / keycap_small.stl / keycap_arrow.stl   blank spares (22 mm, 18 mm, 18 mm with an arrow)
DISPLAY FRAME (10.1 inch 1280x800 HDMI touch module only, 270 x 172 x 30 mm: the Pi 5, audio HAT and jacks are in the rear console).
  Too wide for a 220 mm bed, so it is in four pieces; the bezel and tray seams are 34 mm apart so they never line up:
  frame_bezel_left.stl / frame_bezel_right.stl   print 1x each (front face down); glue the seam, the 4 seam screws pull both halves
                         onto posts in the tray
  frame_tray_left.stl  / frame_tray_right.stl    print 1x each (open side up, supports under the hinge ear); joined by 3 join_straps
                         inside across the seam (M3 x 8 from the back + nuts) and glue
  hinge_spacer.stl       print 2x  (sleeve on the M8 hinge rod between each wooden cheek and the frame)
JOG WHEEL:
  jog_wheel.stl          print 1x top down: 50 mm wheel for a 6 mm D-shaft encoder; glue 3 x M16 washers into its underside
PALM REST (padded, along the front edge, MPC60 style):
  palmrest_left.stl / palmrest_right.stl   print 1x each (top down, as exported); bolted to the body's front wall (4 x M3 x 12 + nuts),
                         joined by a join_strap underneath; PHONES / LEVEL are on its front face. The pad on top is not printed:
                         3 mm hardboard + 10 mm foam wrapped in vinyl (see README).
BRANDING:
  logo_badge.stl         only once a logo is in brand/ (see brand/make_brand.py): print 1x face up, change filament at 1.0 mm for a
                         two-colour badge, glue it into the pocket on the console front (flush). Until then the pocket takes any badge or sticker.
TEST PRINT:
  pad_test_coupon.stl    print this FIRST: one pad opening, to check your MPC pad fits
REFERENCE (not printed, you cut these from wood): cheek_reference.stl, and see make_artwork.py for the 1:1 templates
ONE-PIECE versions (only for a 340 mm bed): controller_base_full.stl / controller_lid_full.stl
OPTIONAL: pad_cap.stl (printed pads, not needed with MPC pads)
"""
import math, struct

# ---------------- CONFIG ----------------
# >>> MEASURE YOUR PARTS, then edit these numbers and re-run (see README, "Before you print") <<<
PITCH = 34.0            # pad centre-to-centre spacing (MPC-style pads: measure yours)
HOLE = 31.0             # square opening in the lid for one pad rubber
CAP, FLANGE = 29.6, 32.6   # only for the optional printed pad_cap.stl (not needed with MPC pads)
JOG_D = 7.4             # hole for the jog encoder bushing (7 mm EC11-style = 7.4)
POT_D = 7.5             # hole for each Q-link pot bushing (7 mm = 7.5)
MX_HOLE, MX_RECESS = 14.2, 15.8   # Cherry MX switch: 14.2 mm square through the plate, 15.8 mm square recess on top
CAP_BIG, CAP_SMALL = 22.0, 18.0   # printed keycaps: transport key depth / square caps for everything else
TR_PITCH, TR_GAP = 31.5, 1.0     # transport row: tape-deck style, wide caps butted together with a 1 mm gap
CAP_TR = (TR_PITCH - TR_GAP, CAP_BIG)   # transport cap, width x depth (30.5 x 22 mm, about 1.6u: no stabiliser needed)


def cap_wh(sz):
    """(width, depth) of a keycap size: a number is a square cap, a pair is width x depth"""
    return (float(sz[0]), float(sz[1])) if isinstance(sz, (tuple, list)) else (float(sz), float(sz))
JOG_WHEEL_D = 50.0      # diameter of the jog wheel you will fit; keeps other controls clear
DISP_BOARD = (239.4, 157.4)    # 10.1 inch 1280x800 HDMI touch module (GT911, micro-USB 5 V): outline from the listing, measure yours
DISP_WINDOW = (221.0, 140.0)   # opening in the bezel: active area 216.6 x 135.4 + about 2 mm of the glass border each side
DISP_WIN_OFF = (0.0, 0.0)      # shift the window if the visible area is off-centre on the board (u, v mm): measure the black border each side
DISP_T = 12.3                  # module thickness (glass to the back of the driver board, not counting the plugs)
DISP_PORTS = (150.0, 192.0, 44.0, 112.0)   # u0, u1, v0, v1 on the board (front view, from its lower-left corner): floor opening behind the
                               # HDMI / power / touch sockets (on the back, left of centre seen from behind = right of centre from the front)
PI_HOLES = [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]     # Raspberry Pi 2B/3/4/5 mounting holes
TILT = 7.0              # degrees the top panel slopes up toward the back (0 = flat)
CHEEK_T = 20.0          # thickness of the wooden cheeks you will fit (18-22 mm timber)
# -----------------------------------------------------------------------------------------------
S_, C_ = math.sin(math.radians(TILT)), math.cos(math.radians(TILT))
TANT = math.tan(math.radians(TILT))
SD = 206.0                                            # depth of the panel measured along the slope
D = SD * C_                                           # depth of the body in plan view
FLOOR, WALL, LID = 3.0, 3.0, 3.0
FRONT_Z = 30.0                                        # underside of the lid at the front edge (27 mm inside height there)
def plane(x, y): return FRONT_Z + y * TANT            # underside of the lid, world coordinates
def R(x, s, h):                                       # panel coordinates (x, s along the slope, h out of the panel) -> world
    return (x, s * C_ - h * S_, FRONT_Z + s * S_ + h * C_)
PAD_X0 = PAD_Y0 = 7.0                                 # pad grid starts here (panel coordinates)
POST_SIZE = 22.0                                      # foam post under each piezo
FLANGE_T, PIEZO_T, FOAM_T = 1.5, 0.5, 2.0
STACK = FLANGE_T + PIEZO_T + FOAM_T                   # piezo + foam under the lid
CAP_TOP_ABOVE_LID = 1.2
PANEL_X0 = PAD_X0 + 4 * PITCH + 22                    # control panel starts right of the pads, with a 22 mm strip for the split
PANEL_W = 166.0                                       # 5 key columns + a 6th column for the Q-link knobs
W = PANEL_X0 + PANEL_W                                # width between the cheeks = 305 mm with the defaults
def P(x): return PANEL_X0 + x
# --- keys, as (x, y, cap size) in panel coordinates; the order IS the Arduino button number (0-23) ---
KEY_NAMES = ["REC", "OVERDUB", "STOP", "PLAY", "PLAY START",
             "MAIN", "GRID", "MUTE", "LOAD", "PROG", "SAMPLE", "CHOP", "MIXER", "FX",
             "SHIFT", "ERASE", "UNDO", "TAP", "BANK", "NOTE REPEAT", "F1", "F2", "F3", "F4"]
COLX = [P(18), P(44), P(70), P(96), P(122), P(148)]   # 26 mm columns; column 6 (P(148)) is the Q-link knob column
KCOL = [P(18 + 22.0 * k) for k in range(6)]           # key grid for the play and screen rows: 22 mm pitch (4 mm between 18 mm caps)
# Layout (front to back). The Arduino button NUMBER of each key never changes (it is its place in KEY_NAMES); only where it sits does.
#   F1 F2 F3 F4 in a row directly behind the pads, one over each pad column (the strip in front of the VU meter stays clear)
#   y 172  MAIN  GRID  LOAD  MUTE  PROG               screen keys (LOAD = the file browser, where STEP was: GRID cycles to STEP) ...
#   y 146  SAMPLE  CHOP  MIXER  FX  SONG              ... (a wider gap separates them from the play keys)
#   y 114  SHIFT  NOTE REPEAT  ERASE  TAP  UNDO       SHIFT and the keys you hold or hit while playing (SHIFT over the jog wheel)
#   y  67  jog wheel            D-pad + OK            centred between the transport row and the play keys; Q1-Q4 down the right edge
#   y 19.5 REC  OVERDUB  STOP  PLAY  PLAY START        a tape-deck bar: wide keys side by side, bottom edge in line with the bottom of the pads
TRANSPORT = ["REC", "OVERDUB", "STOP", "PLAY", "PLAY START"]
TR_Y = PAD_Y0 + (PITCH - HOLE) / 2 + CAP_BIG / 2      # 19.5: the caps' bottom edge lines up with the bottom pad openings
TR_X = [P(16 + TR_PITCH * k) for k in range(5)]       # one continuous bar across the key panel (two lid screws sit just in front of it)
PLAY_Y, SCR2_Y, SCR1_Y = 114.0, 146.0, 172.0
LAYOUT = {n: (TR_X[i], TR_Y, CAP_TR) for i, n in enumerate(TRANSPORT)}
LAYOUT.update({n: (KCOL[i], PLAY_Y, CAP_SMALL) for i, n in enumerate(["SHIFT", "NOTE REPEAT", "ERASE", "TAP", "UNDO"])})
# Arduino button 8 (the old STEP key) is LOAD. BANK (button 18) has no key: banks A-D are SHIFT + F1-F4; input 18 stays free
# (and BANK stays MIDI-learnable).
LAYOUT.update({n: (KCOL[i], SCR2_Y, CAP_SMALL) for i, n in enumerate(["SAMPLE", "CHOP", "MIXER", "FX"])})
LAYOUT.update({n: (KCOL[i], SCR1_Y, CAP_SMALL) for i, n in enumerate(["MAIN", "GRID", "LOAD", "MUTE", "PROG"])})
F_ROW_Y = PAD_Y0 + 4 * PITCH + 23.0                   # 166: one row behind the top pads, 15 mm clear of the pad openings
F_X = [PAD_X0 + PITCH / 2 + PITCH * i for i in range(4)]   # one F-key over each pad column (left to right = F1..F4, like the soft keys on screen)
PANEL_KEYS = [n for n in KEY_NAMES if n in LAYOUT or n in ("F1", "F2", "F3", "F4")]   # the 23 Arduino keys that are on the panel
KEY_BTN = [KEY_NAMES.index(n) for n in PANEL_KEYS]                                    # their Arduino button numbers
KEY_POS = [((F_X[int(n[1]) - 1], F_ROW_Y, CAP_SMALL) if n in ("F1", "F2", "F3", "F4") else LAYOUT[n]) for n in PANEL_KEYS]
SONG_POS = (KCOL[4], SCR2_Y, CAP_SMALL)               # the 10th screen key: wired to the Pi (GPIO), not the Arduino (kept on the Pi so input 18 stays a spare)
Q_X = COLX[5]                                         # Q-link column: the 6th column, down the right edge (the cheek beside it is a low 6 mm rail)
POT_POS = [(Q_X, y) for y in (162.0, 128.0, 94.0, 60.0)]                             # Q-link knobs 1-4: a column down the right edge, Q1 at the back

MID_Y = ((TR_Y + CAP_BIG / 2) + (PLAY_Y - CAP_SMALL / 2)) / 2   # centre of the band between the transport row and the play keys
DPAD_C = (P(96), MID_Y - 4.0)                         # D-pad centre (the OK key)
DPAD_R = 21.0                                         # distance of the four arrows from the centre
ARROW_POS = [(DPAD_C[0], DPAD_C[1] + DPAD_R, CAP_SMALL), (DPAD_C[0], DPAD_C[1] - DPAD_R, CAP_SMALL),
             (DPAD_C[0] - DPAD_R, DPAD_C[1], CAP_SMALL), (DPAD_C[0] + DPAD_R, DPAD_C[1], CAP_SMALL)]   # up, down, left, right
OK_POS = (DPAD_C[0], DPAD_C[1], CAP_SMALL)
JOG_POS = (P(32), MID_Y - 4.0)                        # jog wheel, 50 mm clear circle, level with the D-pad (both 4 mm below the band centre)
SPLIT_X = 158.0                                       # cut line, in the empty strip between the pads and the key panel
JOIN_Y = [40.0, 150.0]                                # two splice straps hold the halves together (panel coordinates)
JOIN_DX = 6.5                                         # screw distance each side of the cut
BACK_NOTCH = (100.0, 190.0)                            # x range of the back-wall slot where the display cables come in
UNO_ORIGIN = (70.0, 146.0)                            # lower-left of Arduino Uno, USB end facing the left wall (floor, world y)
UNO_HOLES = [(13.97, 2.54), (15.24, 50.8), (66.04, 7.62), (66.04, 35.56)]
SR_BOARD = (172.0, 100.0, 76.0, 32.0)                 # x, y, width, depth of the perfboard with the three 74HC165 chips (foam tape to the floor)
SCREWS = [(W - 6, 4.5), (W - 6, 200), (P(31.75), 4.5), (P(4), 200), (6, 202.5), (150, 6), (150, 202.5), (P(94.75), 4.5), (P(70), 202.5)]   # lid screws (panel coords)
CHEEK_SCREW_Y = [30.0, 95.0, 150.0, 188.0]            # 4 screws per cheek, through the body side wall into the wood (world y)
CHEEK_SCREW_Z = 16.0
# ---- hinged display frame ----
FR_W, FR_H, FR_T = 270.0, 172.0, 30.0                 # frame outer width, height, thickness: ONLY the screen (Pi, HAT and jacks live in the rear console)
FR_SPLIT = (FR_W / 2.0, FR_W / 2.0 - 34.0)            # u where the bezel / the tray are cut in two for a 220 mm bed (seams 34 mm apart)
LAP = 20.0                                            # width of the glued lap joint at each seam
FR_FLANGE = 9.0                                       # bezel overhang left and right of the tray
EAR_U = 55.0                                          # hinge ears: outer edge this far in from each side of the frame (keeps them
                                                      # clear of the badge pocket and the lights on the console face)
FR_BT = 3.0                                           # bezel plate thickness
EAR = 10.0                                            # half size of a hinge ear (square around the M8 rod)
HINGE_R = 4.3                                         # hinge rod hole radius (M8 threaded rod)
AX_V, AX_T = -EAR - 1.5, EAR + 4.0                         # hinge axis in frame coordinates
FR_X0 = W / 2.0 - FR_W / 2.0                          # frame left edge in world x
RISER_D = 36.0                                        # depth of the rear console, from the back wall of the body (room for the Pi + HAT stack)
HINGE_H = 32.0                                        # hinge axis height above the top of the panel's back edge (lets the frame fold down flat over the keys)
HINGE_Y = D + 8.0                                     # hinge axis, world y: inside the rear console (the 'L' behind the panel)
HINGE_Z = plane(0, D) + LID + HINGE_H                 # hinge axis, world z
SPACER = (10.6, 8.6, FR_X0 + EAR_U - 0.5)         # sleeve outer diameter, inner diameter, length (thin: it runs inside the rear console)
# ---- rear console: the upright part of the 'L' behind the panel. It hides the hinge rod and carries logo, lights and VU meter ----
ZB = plane(0, D) + LID                                # top of the panel's back edge (world z)
RT = HINGE_Z + 7.5                                    # top of the console in front of the hinge (2.5 mm below the frame's bottom edge)
LEAN_MAX = 40.0                                       # the console's top slopes away behind the hinge so the frame can lean back this far
RYK = HINGE_Y + 5.0                                   # the flat top ends here, then slopes down to the back
RZB = RT - (D + RISER_D - RYK) * math.tan(math.radians(LEAN_MAX))   # height of the back edge
RWALL = 3.0
FASCIA_H = RT - ZB                                    # visible height of the front face above the panel's back edge
LOGO = (16.0, 70.0, 7.0, 29.0)                        # logo badge pocket on the front face: x0, x1, h0, h1 (h = height above the panel's back edge):
                                                      # a low 54 x 22 mm nameplate, 14 mm clear of the left hinge-ear slot and level with the VU rows
LOGO_DEPTH = 1.6                                      # pocket depth = badge thickness: the badge sits flush with the face
BADGE_GAP, BADGE_BASE, BADGE_MARGIN = 0.2, 1.0, 1.8   # clearance per side; badge plate thickness (the raised logo is the rest); border
LOGO_ICON = "brand/badge_mask.png"                    # the badge artwork: made by brand/make_brand.py from your logo (none yet = no badge)
LOGO_STAR = "brand/key_mark.png"                      # optional symbol engraved above SHIFT on its keycap (none = plain SHIFT)
LEDS = [(W - 49.0, 22.0, "PWR"), (W - 35.0, 22.0, "PLAY"), (W - 21.0, 22.0, "REC")]    # 5 mm holes: x, h, name
LED_D = 5.0
VU_PITCH, VU_N, VU_ROWS = 10.0, 12, (27.0, 12.0)                              # two rows of 12 windows (left channel above right)
VU_X0 = W / 2.0 - (VU_N - 1) * VU_PITCH / 2.0                                   # centred between the two hinge ears
VU_WIN = (7.0, 4.0)
RISER_SCREWS = [(D + 9.0, 14.0), (D + 23.0, 14.0)]    # (y, z): M3 screws from the console's end walls into the wooden cheeks
# ---- front edge: headphones (fed from OUT 1/2 through a small headphone amp board inside the body) ----
FRONT_HOLES = [(W - 19.0, 12.0, 9.8, "PHONES"), (W - 43.0, 12.0, 7.2, "LEVEL")]   # x, z, hole diameter, label (9 mm pot: M7 bushing)
# ---- padded vinyl palm rest along the front (as on the MPC60 mk1): a printed core bolted to the body's front wall, with a
#      removable pad on top (3 mm hardboard + 10 mm foam, wrapped in vinyl). PHONES / LEVEL move to the core's front face. ----
PR_D = 58.0                                           # depth of the palm rest in front of the body
PAD_T = 13.0                                          # pad thickness: 3 mm hardboard + 10 mm foam (the vinyl adds ~1 mm)
PR_TOP = FRONT_Z + LID + 6.0                          # top of the pad = 6 mm above the panel's front edge, flush with the cheek fronts
PR_CORE = PR_TOP - PAD_T                              # top of the printed core (the pad sits on it)
PR_WALL = 2.4
PR_BOLTS = [30.0, 128.0, 200.0, 300.0]                # M3 bolts through the core's back wall and the body's front wall (z = PR_BOLT_Z)
PR_BOLT_Z = 12.0
PR_CABLE = (W - 31.0, 12.0, 12.0)                     # cable hole from the jack / level pot back into the body: x, z, diameter
PR_RIBS = [60.0, 105.0, 225.0, 270.0]                 # stiffening ribs under the pad (front to back), away from the bolts and jacks
# ---- rear panel of the console (looking at the back wall from behind it is mirrored: x below is the sampler's own x, 0 = left as you face the keys) ----
JACK_D = 9.8                                          # hole for a 1/4 inch panel jack (3/8 in = 9.5 mm bushing)
JACK_X_OUT = [250.0, 230.0, 210.0, 190.0, 170.0, 146.0, 126.0, 106.0]   # OUT 1..8: numbered left to right as you look at the back; 24 mm gap keeps the cut out of the holes
JACK_Z_OUT = 22.0                                     # height of the output row above the console floor level (z, world)
JACK_X_IN = [126.0, 106.0]                            # IN L, IN R (to the ADC8x), upper row, L on the left seen from behind
JACK_Z_IN = 50.0
PORTS = [("USB-A", 186.0, 50.0, 15.0, 8.0), ("ETHERNET", 222.0, 50.0, 21.0, 16.0), ("USB-C PWR", 265.0, 50.0, 10.0, 4.0)]   # name, x, z, window width, window height
POWER_BTN = (W - 15.0, 50.0, 12.2)                       # x, z, hole: 12 mm momentary push button -> the Pi 5's J2 power-button header (press = on / clean shut-down)
PORT_SCREWS = 1.7                                     # M3 pilot radius for the panel-mount connectors
VENT_X, VENT_Z = [22.0, 32.0, 42.0, 52.0, 62.0], (24.0, 60.0)            # 5 vertical vent slots behind the Pi (3 mm wide)
PI_ORIGIN = (8.0, 14.0)                               # Pi 5 lower-left corner (x, z world): board stands on the back wall, parts facing the front; 11 mm below for right-angle plugs
PI_STAND = 5.0                                        # standoff height between the back wall and the Pi board
# ---- wooden cheeks (cut from timber; STL is only for the pictures) ----
# A plain wedge board with square corners (the sketch): flat outer faces, the top runs straight from the front up to the
# rear console and then follows the console's top exactly, so each cheek finishes flush with the platform. No tower, no
# holes or caps on the outside: the hinge rod sits in BLIND holes drilled into the inner faces.
CH_Y0, CH_Y1 = -PR_D - 4.0, D + RISER_D               # front (4 mm proud of the palm rest) and back (flush with the console's back wall)
CH_ZF = PR_TOP                                        # top of the cheek at the front: flush with the palm rest pad
CH_RAIL = 6.0                                         # beside the panel the cheek is a low rail this far above the panel top, then steps up to the console
ROD_IN = 12.0                                         # depth of the blind rod hole in each cheek's inner face (8 mm left to the outer face)
ROD_LEN = W + 2 * ROD_IN - 1.0                        # M8 rod between the two blind holes (1 mm play so the cheeks pull tight)
# ----------------------------------------

PAD_CENTERS = [(PAD_X0 + PITCH / 2 + PITCH * i, PAD_Y0 + PITCH / 2 + PITCH * j)
               for j in range(4) for i in range(4)]   # pad 1 = front-left, pad 16 = back-right (panel coordinates)


def clip_x(poly, xa=None, xb=None):
    """Sutherland-Hodgman clip of a convex polygon to xa <= x <= xb."""
    def clip(pts, inside, xl):
        out = []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            ia, ib = inside(a), inside(b)
            if ia: out.append(a)
            if ia != ib:
                t = (xl - a[0]) / (b[0] - a[0])
                out.append((xl, a[1] + t * (b[1] - a[1])))
        return out
    if xa is not None: poly = clip(poly, lambda p: p[0] >= xa, xa)
    if xb is not None and len(poly) >= 3: poly = clip(poly, lambda p: p[0] <= xb, xb)
    dedup = []
    for p in poly:
        if not dedup or abs(p[0] - dedup[-1][0]) + abs(p[1] - dedup[-1][1]) > 1e-9: dedup.append(p)
    if len(dedup) > 1 and abs(dedup[0][0] - dedup[-1][0]) + abs(dedup[0][1] - dedup[-1][1]) < 1e-9: dedup.pop()
    return dedup


class Mesh:
    def __init__(self, clip=None):
        self.t = []
        self.clip = clip                      # (xa, xb): keep only this slice of everything added

    def recenter(self):
        xs = [p[0] for t in self.t for p in t]; ys = [p[1] for t in self.t for p in t]
        dx, dy = min(xs), min(ys)
        self.t = [tuple((p[0] - dx, p[1] - dy, p[2]) for p in tri) for tri in self.t]

    def tri(self, a, b, c):
        self.t.append((a, b, c))

    def prism(self, poly, z0, z1, ztop=None):  # convex polygon, counter-clockwise; ztop(x, y) gives a sloped top face
        if self.clip:
            poly = clip_x(poly, *self.clip)
            if len(poly) < 3: return
            if abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                       for i in range(len(poly)))) < 1e-6: return
        n = len(poly)
        bot = [(x, y, z0) for x, y in poly]
        top = [(x, y, ztop(x, y) if ztop else z1) for x, y in poly]
        for i in range(1, n - 1):
            self.tri(bot[0], bot[i + 1], bot[i])
            self.tri(top[0], top[i], top[i + 1])
        for i in range(n):
            j = (i + 1) % n
            self.tri(bot[i], bot[j], top[j])
            self.tri(bot[i], top[j], top[i])

    def box(self, x0, y0, z0, x1, y1, z1, ztop=None):
        self.prism([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, ztop)

    def cyl(self, cx, cy, r, z0, z1, n=20, ztop=None):
        self.prism([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
                    for k in range(n)], z0, z1, ztop)

    def ring(self, cx, cy, half, r, z0, z1, n=32, ztop=None):
        """square cell (side 2*half) with a round hole radius r, built from convex wedges"""
        def inner(a): return (cx + r * math.cos(a), cy + r * math.sin(a))
        def outer(a):
            c, s = abs(math.cos(a)), abs(math.sin(a))
            t = min(half / c if c > 1e-9 else 1e9, half / s if s > 1e-9 else 1e9)
            return (cx + t * math.cos(a), cy + t * math.sin(a))
        for k in range(n):
            a0 = math.radians(45 + 360.0 * k / n)
            a1 = math.radians(45 + 360.0 * (k + 1) / n)
            self.prism([outer(a0), outer(a1), inner(a1), inner(a0)], z0, z1, ztop)

    def plate(self, x0, y0, x1, y1, z0, z1, rects, rounds):
        special = list(rects) + [(cx - h, cy - h, cx + h, cy + h) for cx, cy, r, h in rounds]
        xs = sorted({x0, x1, *[s[0] for s in special], *[s[2] for s in special]})
        ys = sorted({y0, y1, *[s[1] for s in special], *[s[3] for s in special]})
        for j in range(len(ys) - 1):
            run = None
            for i in range(len(xs) - 1):
                cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
                inside = any(s[0] < cx < s[2] and s[1] < cy < s[3] for s in special)
                if not inside and run is None:
                    run = xs[i]
                if inside and run is not None:
                    self.box(run, ys[j], z0, xs[i], ys[j + 1], z1)
                    run = None
            if run is not None:
                self.box(run, ys[j], z0, xs[-1], ys[j + 1], z1)
        for cx, cy, r, h in rounds:
            self.ring(cx, cy, h, r, z0, z1)

    def volume(self):
        v = 0.0
        for a, b, c in self.t:
            v += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                  + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        return v

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"sampler parts".ljust(80, b" "))
            f.write(struct.pack("<I", len(self.t)))
            for a, b, c in self.t:
                u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
                v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
                n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                L = math.sqrt(sum(k * k for k in n)) or 1.0
                f.write(struct.pack("<3f", n[0] / L, n[1] / L, n[2] / L))
                for p in (a, b, c):
                    f.write(struct.pack("<3f", *p))
                f.write(b"\0\0")
        xs = [p[0] for t in self.t for p in t]; ys = [p[1] for t in self.t for p in t]
        zs = [p[2] for t in self.t for p in t]
        print(f"{path}: {len(self.t)} triangles, size "
              f"{max(xs)-min(xs):.1f} x {max(ys)-min(ys):.1f} x {max(zs)-min(zs):.1f} mm")





def remap(tris, f, flip=False):
    out = []
    for a, b, c in tris:
        a, b, c = f(a), f(b), f(c)
        out.append((a, c, b) if flip else (a, b, c))
    return out


def inrange(m, x0, x1):
    return m.clip is None or (m.clip[0] <= (x0 + x1) / 2.0 <= m.clip[1])


def base(clip=None, joins=True):
    m = Mesh(clip)
    m.box(0, 0, 0, W, D, FLOOR)
    front = Mesh(clip)                                         # front wall (behind the palm rest): its bolts and the jack cable hole
    fr = [(x, PR_BOLT_Z, 1.7, 5.0) for x in PR_BOLTS] + [(PR_CABLE[0], PR_CABLE[1], PR_CABLE[2] / 2, 8.0)]
    front.plate(0, FLOOR, W, 24.0, 0, WALL, [], fr)                               # local (x, z, y)
    m.t += remap(front.t, lambda p: (p[0], p[2], p[1]), flip=True)
    m.box(0, 0, 24.0, W, WALL, 0, ztop=plane)                  # rest of the front wall, top follows the sloped lid
    nx0, nx1 = BACK_NOTCH                                      # back wall with a slot for the display cables
    m.box(0, D - WALL, FLOOR, nx0, D, 0, ztop=plane)
    m.box(nx1, D - WALL, FLOOR, W, D, 0, ztop=plane)
    m.box(nx0, D - WALL, FLOOR, nx1, D, 0, ztop=lambda x, y: plane(x, y) - 22.0)
    for x0 in (0.0, W - WALL):                                  # side walls: lower strip drilled for the cheek screws, upper part sloped
        if not inrange(m, x0, x0 + WALL): continue
        low = Mesh()
        low.plate(0, FLOOR, D, 24.0, 0, WALL, [], [(y, CHEEK_SCREW_Z, 2.2, 6.0) for y in CHEEK_SCREW_Y])    # (x=y, y=z, z=x)
        m.t += remap(low.t, lambda p, x0=x0: (p[2] + x0, p[0], p[1]))
        boss_x = (WALL, WALL + 3.0) if x0 == 0 else (W - WALL - 3.0, W - WALL)
        for y in CHEEK_SCREW_Y:
            b = Mesh(); b.ring(y, CHEEK_SCREW_Z, 5.0, 2.1, boss_x[0], boss_x[1])
            m.t += remap(b.t, lambda p: (p[2], p[0], p[1]))
        m.box(x0, 0, 24.0, x0 + WALL, D, 0, ztop=plane)
    for cx, cs in PAD_CENTERS:                                 # foam posts under each pad, top follows the sloped lid
        y = cs * C_
        m.box(cx - POST_SIZE / 2, y - POST_SIZE / 2, FLOOR, cx + POST_SIZE / 2, y + POST_SIZE / 2, 0, ztop=lambda x, yy: plane(x, yy) - STACK - 1.0)
    ux, uy = UNO_ORIGIN
    for hx, hy in UNO_HOLES:                                   # Arduino Uno posts + locating pins
        x, y = ux + hx, uy + hy
        m.box(x - 3.5, y - 3.5, FLOOR, x + 3.5, y + 3.5, FLOOR + 5)
        m.cyl(x, y, 1.5, FLOOR + 5, FLOOR + 9)
    for x, s in SCREWS:                                        # lid screw posts, 2.6 mm pilot hole for M3
        m.ring(x, s * C_, 3.5, 1.3, FLOOR, 0, ztop=plane)
    if joins:                                                  # posts that the splice straps screw down onto
        for jy in JOIN_Y:
            for jx in (SPLIT_X - JOIN_DX, SPLIT_X + JOIN_DX):
                m.ring(jx, jy * C_, 3.5, 1.3, FLOOR, FLOOR + 5)
    return m


def lid_panel(clip=None, joins=True):
    """The lid in panel coordinates (flat, h = 0 at the underside).  Key holes are MX plate cut-outs:
    14.2 mm square through the lower 1.5 mm, 15.8 mm square recess in the upper 1.5 mm (the switch clips grip the thin lower plate)."""
    m = Mesh(clip)
    pads = [(cx - HOLE / 2, cy - HOLE / 2, cx + HOLE / 2, cy + HOLE / 2) for cx, cy in PAD_CENTERS]
    keys = [(x, y) for x, y, _ in KEY_POS + ARROW_POS + [OK_POS, SONG_POS]]
    low = pads + [(x - MX_HOLE / 2, y - MX_HOLE / 2, x + MX_HOLE / 2, y + MX_HOLE / 2) for x, y in keys]
    up = pads + [(x - MX_RECESS / 2, y - MX_RECESS / 2, x + MX_RECESS / 2, y + MX_RECESS / 2) for x, y in keys]
    rounds = [(x, y, POT_D / 2, 7.0) for x, y in POT_POS]
    rounds += [(JOG_POS[0], JOG_POS[1], JOG_D / 2, 8.0)]
    rounds += [(x, y, 1.7, 3.5) for x, y in SCREWS]
    zm = LID / 2.0
    m.plate(0, 0, W, SD, 0, zm, low, rounds)
    m.plate(0, 0, W, SD, zm, LID, up, rounds)
    if joins:                                      # blind pilots: the splice straps screw up into bosses, nothing shows on top
        for jy in JOIN_Y:
            for jx in (SPLIT_X - JOIN_DX, SPLIT_X + JOIN_DX):
                m.ring(jx, jy, 3.5, 1.3, -5, 0)
    return m


def lid(clip=None, joins=True):
    """Printing orientation: flat, flipped so the smooth outside face is on the bed."""
    m = lid_panel(clip, joins)
    m.t = [tuple((W - p[0], p[1], LID - p[2]) for p in tri) for tri in m.t]   # rotate 180 deg about Y
    if clip: m.recenter()
    return m


def lid_world():
    """The lid as it sits on the case: tilted."""
    return [tuple(R(*p) for p in tri) for tri in lid_panel(None, False).t]


def board_origin():
    """lower-left corner of the display module inside the frame (frame coordinates): centred"""
    return (FR_W - DISP_BOARD[0]) / 2.0, (FR_H - DISP_BOARD[1]) / 2.0


def window_rect():
    bu, bv = board_origin()
    cu, cv = bu + DISP_BOARD[0] / 2 + DISP_WIN_OFF[0], bv + DISP_BOARD[1] / 2 + DISP_WIN_OFF[1]
    return (cu - DISP_WINDOW[0] / 2, cv - DISP_WINDOW[1] / 2, cu + DISP_WINDOW[0] / 2, cv + DISP_WINDOW[1] / 2)


BEZEL_SCREWS = [(4.5, 20), (4.5, FR_H - 20), (FR_W - 4.5, 20), (FR_W - 4.5, FR_H - 20)]      # in the flanges, into the tray's side posts
SEAM_SCREWS = [(FR_SPLIT[0] + d, v) for d in (-8.0, 8.0) for v in (3.5, FR_H - 3.5)]        # each side of the bezel seam, into posts in the tray
STRAP_V = [30.0, FR_H / 2.0, FR_H - 30.0]             # join straps inside the tray across its seam (M3 x 8 from the back + nuts)
STOP_H = min(10.0, DISP_T - 2.0)                       # corner stops: how far they reach back along the module's edges


def frame_bezel(clip=None):
    """Front plate, printed front face down. Window for the screen, countersunk holes for the M3 screws, corner stops that
    locate the module (they sit just OUTSIDE its outline). clip=(u0, u1) keeps one half for a 220 mm bed."""
    m = Mesh(clip)
    bw, bh = DISP_BOARD
    bu, bv = board_origin()
    m.plate(0, 0, FR_W, FR_H, 0, FR_BT, [window_rect()], [(x, y, 1.7, 3.5) for x, y in BEZEL_SCREWS + SEAM_SCREWS])
    x0, y0, x1, y1 = bu - 0.3, bv - 0.3, bu + bw + 0.3, bv + bh + 0.3
    for bx, sx in ((x0, -1), (x1, 1)):                          # s = the outward direction at that corner
        for by, sy in ((y0, -1), (y1, 1)):
            m.box(min(bx - sx * 12, bx + sx * 2), min(by, by + sy * 2), FR_BT, max(bx - sx * 12, bx + sx * 2), max(by, by + sy * 2), FR_BT + STOP_H)
            m.box(min(bx, bx + sx * 2), min(by - sy * 12, by + sy * 2), FR_BT, max(bx, bx + sx * 2), max(by - sy * 12, by + sy * 2), FR_BT + STOP_H)
    return m


def frame_tray_local(clip=None):
    """Tray in frame coordinates: u across, v up the frame, t from the front face (t=0) to the back (t=FR_T).
    clip=(u0, u1) keeps one piece (the tray is cut at FR_SPLIT[1] for a 220 mm bed)."""
    m = Mesh(clip)
    u0, u1 = FR_FLANGE, FR_W - FR_FLANGE
    t0, fl = FR_BT, FR_T - 3.0                                 # walls start behind the bezel; floor at t = fl .. FR_T
    bu, bv = board_origin()
    pu0, pu1, pv0, pv1 = DISP_PORTS
    ports = (bu + pu0, bv + pv0, bu + pu1, bv + pv1)             # opening behind the module's HDMI / power / touch sockets
    straps = [(FR_SPLIT[1] + d, v, 1.7, 3.5) for d in (-JOIN_DX, JOIN_DX) for v in STRAP_V]
    m.plate(u0, 0, u1, FR_H, fl, FR_T, [ports], straps)        # floor
    m.box(u0, FR_H - 3, t0, u1, FR_H, fl)                      # top wall
    m.box(u0, 0, t0, u0 + 3, FR_H, fl)                         # left and right walls
    m.box(u1 - 3, 0, t0, u1, FR_H, fl)
    m.box(u0 + 3, 0, t0, 60, 3, fl); m.box(FR_W - 60, 0, t0, u1 - 3, 3, fl)   # bottom wall, open in the middle for the cables
    for u, v in BEZEL_SCREWS:                                  # screw posts for the bezel, outside the side walls
        m.ring(u, v, 3.5, 1.3, FR_BT, 14)
        if u < u0: m.box(u + 3.5, v - 3.5, FR_BT, u0, v + 3.5, 14)
        else: m.box(u1, v - 3.5, FR_BT, u - 3.5, v + 3.5, 14)
    for u, v in SEAM_SCREWS:                                   # posts each side of the bezel seam, bezel to floor, beside the module's edge
        m.ring(u, v, 3.5, 1.3, FR_BT, fl)
    pt = FR_BT + DISP_T + 1.0                                  # rests behind the module: 1 mm of foam tape on each holds it against the bezel
    for du, dv in ((25.0, 25.0), (DISP_BOARD[0] - 25.0, 25.0), (25.0, DISP_BOARD[1] - 25.0), (DISP_BOARD[0] - 25.0, DISP_BOARD[1] - 25.0)):
        m.box(bu + du - 5, bv + dv - 5, pt, bu + du + 5, bv + dv + 5, fl)
    for a, b in ((EAR_U, EAR_U + 10), (FR_W - EAR_U - 10, FR_W - EAR_U)):   # hinge ears: square around the axis with the rod hole
        if clip and not (clip[0] <= a and b <= clip[1]): continue
        e = Mesh(); e.ring(AX_T, AX_V, EAR, HINGE_R, a, b)         # (x=t, y=v, z=u)
        m.t += remap(e.t, lambda p: (p[2], p[1], p[0]), flip=True)   # swap axes = mirror, so flip winding
        m.box(a, -1.6, AX_T - EAR, b, 0.2, AX_T + EAR)               # bridge between the ear and the tray's bottom edge (the axis sits 1.5 mm lower)
    return m


def frame_tray(clip=None):
    """Printed with the floor on the bed: u mirrored, t reversed (a 180 degree turn), shifted to positive coordinates."""
    m = frame_tray_local(clip)
    m.t = [tuple((FR_W - p[0], p[1] - (AX_V - EAR), FR_T - p[2]) for p in tri) for tri in m.t]
    if clip: m.recenter()
    return m


def frame_halves():
    """the frame in four pieces that each fit a 220 mm bed: bezel cut at FR_SPLIT[0], tray at FR_SPLIT[1] (seams apart)"""
    b = [frame_bezel((-1.0, FR_SPLIT[0])), frame_bezel((FR_SPLIT[0], FR_W + 1.0))]
    b[1].recenter()
    t = [frame_tray((-30.0, FR_SPLIT[1])), frame_tray((FR_SPLIT[1], FR_W + 30.0))]
    return b + t


def frame_pose(alpha_deg):
    """Returns f(u, v, t) -> world (x, y, z) for the frame tilted alpha degrees back from upright (negative = leaning toward you)."""
    a = math.radians(alpha_deg); s, c = math.sin(a), math.cos(a)
    def f(p):
        u, v, t = p
        vr, tr = v - AX_V, t - AX_T
        return (FR_X0 + u, HINGE_Y + vr * s + tr * c, HINGE_Z + vr * c - tr * s)
    return f


def tube(m, cx, cy, ro, ri, z0, z1, n=40):
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        m.prism([(cx + ro * math.cos(a0), cy + ro * math.sin(a0)), (cx + ro * math.cos(a1), cy + ro * math.sin(a1)),
                 (cx + ri * math.cos(a1), cy + ri * math.sin(a1)), (cx + ri * math.cos(a0), cy + ri * math.sin(a0))], z0, z1)


def hinge_spacer():
    m = Mesh(); od, idm, L = SPACER
    tube(m, 0, 0, od / 2, idm / 2, 0, L)
    return m


# ---- jog wheel: printed, weighted, for a small 7 mm-collar encoder with a 6 mm D shaft (EC11 / Bourns PEC11R / Alps EC11 type) ----
JW_H, JW_TOP, JW_BORE = 14.0, 3.0, 11.0          # wheel height, solid top, shaft bore depth (a 15-20 mm shaft above a 3 mm panel)
JW_POCKET = (8.6, 15.6)                           # underside pocket radii: takes a stack of M16 flat washers (ID 17, OD 30) as a flywheel


def jog_wheel():
    """50 mm wheel printed TOP DOWN: solid top with grip ribs round the rim, a D-bore hub, and an open pocket underneath for
    3 x M16 washers (about 30 g, glued in) so it has weight and keeps spinning a little, like a sampler's data wheel."""
    m = Mesh()
    R = JOG_WHEEL_D / 2
    tube(m, 0, 0, R, 0.01, 0, JW_TOP, 72)                                        # top (on the bed)
    tube(m, 0, 0, R, JW_POCKET[1] + 0.4, JW_TOP, JW_H, 72)                       # outer wall: the washers sit inside it
    tube(m, 0, 0, JW_POCKET[0] - 0.4, 3.1, JW_TOP, JW_H, 36)                    # hub with the shaft bore (6 mm + clearance)
    m.box(1.5, -3.1, JW_H - JW_BORE, 3.1, 3.1, JW_H)                             # the flat of the D (6 mm shaft, 4.5 mm across the flat)
    m.box(-3.1, -3.1, JW_TOP, 3.1, 3.1, JW_H - JW_BORE + 0.01)                   # solid above the bore
    for k in range(36):                                                          # grip ribs round the rim (0.6 mm)
        a = 2 * math.pi * k / 36
        c, s_ = math.cos(a), math.sin(a)
        pts = [(R * c - 0.6 * s_, R * s_ + 0.6 * c), (R * c + 0.6 * s_, R * s_ - 0.6 * c),
               ((R + 0.6) * c + 0.6 * s_, (R + 0.6) * s_ - 0.6 * c), ((R + 0.6) * c - 0.6 * s_, (R + 0.6) * s_ + 0.6 * c)]
        m.prism(pts, JW_TOP + 1.0, JW_H - 1.0)
    return m


def join_strap():
    m = Mesh()
    L = 2 * JOIN_DX + 14
    m.plate(0, 0, L, 12, 0, 3, [], [(L / 2 - JOIN_DX, 6, 1.7, 3.5), (L / 2 + JOIN_DX, 6, 1.7, 3.5)])
    return m


# ---- keycap legends: engraved 0.6 mm into the top face, so every key says what it does (fill with paint or wax if you like) ----
LEGEND_DEPTH, LEGEND_RES = 0.6, 0.12                  # engraving depth; raster size in mm (finer = smoother letters, more triangles)
LEGEND_LINES = {"PLAY START": ["PLAY", "START"], "NOTE REPEAT": ["NOTE", "REPEAT"], "OVERDUB": ["OVER", "DUB"],
                "SAMPLE": ["SAMPLE"], "MIXER": ["MIXER"]}
LEGEND_MAX_H = 3.4                                    # tallest capital letter, mm (bold strokes stay about 0.5 mm wide or more)


def _legend_runs(lines, box_w, box_h, res=LEGEND_RES):
    """Rasterise the legend centred in a box_w x box_h window. Returns boxes (x0, y0, x1, y1), in mm centred on 0,
    covering the SOLID part of the window (everything except the letters), merged into as few rectangles as possible."""
    from PIL import Image, ImageDraw, ImageFont
    fp = None
    for base in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/"):
        try: ImageFont.truetype(base + "DejaVuSansCondensed-Bold.ttf", 10); fp = base + "DejaVuSansCondensed-Bold.ttf"; break
        except OSError: continue
    nx, ny = int(round(box_w / res)), int(round(box_h / res))
    best = None
    for size in range(int(LEGEND_MAX_H / res * 1.38), 4, -1):          # biggest font that fits the window
        f = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        ws = [f.getbbox(t) for t in lines]
        lh = int(size * 0.95)
        tw = max(bb[2] - bb[0] for bb in ws); th = lh * len(lines)
        if tw <= nx - 2 and th <= ny - 2: best = (f, lh); break
    f, lh = best
    im = Image.new("L", (nx, ny), 0); d = ImageDraw.Draw(im)
    y = (ny - lh * len(lines)) / 2.0
    for t in lines:
        d.text((nx / 2.0, y + lh / 2.0), t, font=f, fill=255, anchor="mm"); y += lh
    px = im.load()
    rows = []
    for j in range(ny):
        runs, i = [], 0
        while i < nx:
            if px[i, j] < 128:
                i0 = i
                while i < nx and px[i, j] < 128: i += 1
                runs.append((i0, i))
            else: i += 1
        rows.append(runs)
    out, active = [], {}
    for j in range(ny + 1):                                       # merge identical runs on consecutive rows into one box
        cur = set(rows[j]) if j < ny else set()
        for r in list(active):
            if r not in cur: out.append((r[0], active.pop(r), r[1], j))
        for r in cur:
            if r not in active: active[r] = j
    x0, y0 = -box_w / 2.0, box_h / 2.0                            # image row 0 is the top of the window
    return [(x0 + a * res, y0 - j1 * res, x0 + b * res, y0 - j0 * res) for a, j0, b, j1 in out]


def _image_runs(path, box_w, box_h, res=LEGEND_RES, solid="ink"):
    """A black/white image (white = the mark) fitted and centred in a box_w x box_h window, rasterised at `res` mm.
    Returns merged boxes (x0, y0, x1, y1) in mm centred on 0 covering the mark (solid='ink') or everything else ('paper')."""
    from PIL import Image
    here = __import__("os").path.dirname(__import__("os").path.abspath(__file__))
    src = Image.open(__import__("os").path.join(here, path)).convert("L")
    nx, ny = int(round(box_w / res)), int(round(box_h / res))
    k = min(nx / src.width, ny / src.height)
    w_, h_ = max(1, int(src.width * k)), max(1, int(src.height * k))
    im = Image.new("L", (nx, ny), 0); im.paste(src.resize((w_, h_), Image.LANCZOS), ((nx - w_) // 2, (ny - h_) // 2))
    return _runs_of(im, lambda v: (v >= 128) == (solid == "ink"), box_w, box_h, res)


def _runs_of(im, keep, box_w, box_h, res):
    nx, ny = im.size
    px = im.load()
    rows = []
    for j in range(ny):
        runs, i = [], 0
        while i < nx:
            if keep(px[i, j]):
                i0 = i
                while i < nx and keep(px[i, j]): i += 1
                runs.append((i0, i))
            else: i += 1
        rows.append(runs)
    out, active = [], {}
    for j in range(ny + 1):
        cur = set(rows[j]) if j < ny else set()
        for r in list(active):
            if r not in cur: out.append((r[0], active.pop(r), r[1], j))
        for r in cur:
            if r not in active: active[r] = j
    x0, y0 = -box_w / 2.0, box_h / 2.0
    return [(x0 + a * res, y0 - j1 * res, x0 + b * res, y0 - j0 * res) for a, j0, b, j1 in out]


def _brand(rel):
    import os
    return os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), rel))


def logo_badge():
    """Your logo as a badge for the console's front pocket (None until brand/make_brand.py has made badge_mask.png), printed face UP:
    a 1.0 mm plate, then the mark raised 0.6 mm. Change filament at 1.0 mm (e.g. black plate, silk gold mark),
    or print one colour and paint the raised mark. Glue it into the pocket; it sits flush with the face."""
    if not _brand(LOGO_ICON): return None
    m = Mesh()
    bw, bh = LOGO[1] - LOGO[0] - 2 * BADGE_GAP, LOGO[3] - LOGO[2] - 2 * BADGE_GAP
    m.prism(rounded([(0, 0), (bw, 0), (bw, bh), (0, bh)], 1.2), 0, BADGE_BASE)
    iw, ih = bw - 2 * BADGE_MARGIN, bh - 2 * BADGE_MARGIN
    for x0, y0, x1, y1 in _image_runs(LOGO_ICON, iw, ih, 0.1):
        m.box(bw / 2 + x0, bh / 2 + y0, BADGE_BASE - 0.01, bw / 2 + x1, bh / 2 + y1, LOGO_DEPTH)
    return m


def palmrest(clip=None):
    """Printed core of the palm rest, world coordinates (y from -PR_D to 0), open underneath, top plate for the pad.
    Front face: PHONES jack and LEVEL pot with engraved labels. Back wall: 2 M3 bolts per half into the body's front
    wall (nuts inside the body) and the cable hole. End walls: one wood screw each, from inside, into the cheek."""
    m = Mesh(clip)
    y0 = -PR_D
    m.box(0, y0, PR_CORE - PR_WALL, W, 0, PR_CORE)                              # top plate (the pad lies on it)
    front = Mesh(clip)                                                           # front face: local (x, z, thickness)
    fr = [(x, z, d / 2, 6.0) for x, z, d, _ in FRONT_HOLES]
    fl = [(lab, x, z + 9.0, 18.0) for x, z, d, lab in FRONT_HOLES]
    front.plate(0, 0, W, PR_CORE - PR_WALL, LEGEND_DEPTH, PR_WALL, [], fr)
    front.plate(0, 0, W, PR_CORE - PR_WALL, 0, LEGEND_DEPTH, [(x - w / 2, z - 2.3, x + w / 2, z + 2.3) for _, x, z, w in fl], fr)
    for text, x, z, w in fl:
        for a, b_, c, d_ in _legend_runs([text], w, 4.6):
            front.box(x + a, z + b_, 0, x + c, z + d_, LEGEND_DEPTH)
    m.t += remap(front.t, lambda p: (p[0], y0 + p[2], p[1]), flip=True)
    back = Mesh(clip)
    br = [(x, PR_BOLT_Z, 1.7, 5.0) for x in PR_BOLTS] + [(PR_CABLE[0], PR_CABLE[1], PR_CABLE[2] / 2, 8.0)]
    back.plate(0, 0, W, PR_CORE - PR_WALL, -PR_WALL, 0, [], br)
    m.t += remap(back.t, lambda p: (p[0], p[2], p[1]), flip=True)
    for x0 in (0.0, W - PR_WALL):                                                 # end walls, against the cheeks
        if not inrange(m, x0, x0 + PR_WALL): continue
        e = Mesh()
        e.plate(y0 + PR_WALL, 0, -PR_WALL, PR_CORE - PR_WALL, 0, PR_WALL, [], [(y0 + PR_D / 2, PR_BOLT_Z, 2.2, 5.0)])   # (x=y, y=z, z=x)
        m.t += remap(e.t, lambda p, x0=x0: (p[2] + x0, p[0], p[1]))
    for rx in PR_RIBS:                                                            # ribs: the pad takes your hands' weight
        if inrange(m, rx - 1, rx + 1): m.box(rx - 1.0, y0 + PR_WALL, 0, rx + 1.0, -PR_WALL, PR_CORE - PR_WALL)
    for jx in (SPLIT_X - JOIN_DX, SPLIT_X + JOIN_DX):                             # posts for a join strap under the split
        if inrange(m, jx - 3.5, jx + 3.5): m.ring(jx, -PR_D / 2, 3.5, 1.3, PR_CORE - PR_WALL - 6.0, PR_CORE - PR_WALL)
    return m


def palmrest_print(clip=None):
    """printing orientation: top plate down on the bed (a half turn about the x axis), each half moved to the origin"""
    m = palmrest(clip)
    m.t = [tuple((p[0], -p[1], PR_CORE - p[2]) for p in tri) for tri in m.t]
    m.recenter()
    return m


def pad_outline():
    """(y, z) profile of the vinyl pad as it sits on the core: rounded front and back edges"""
    return rounded([(-PR_D + 0.5, PR_CORE), (-0.5, PR_CORE), (-0.5, PR_TOP), (-PR_D + 0.5, PR_TOP)], 5.0)


def _clip_y(poly, ya=None, yb=None):
    sw = [(p[1], p[0]) for p in poly]
    return [(p[1], p[0]) for p in clip_x(sw, ya, yb)]


def keycap(size, arrow=False, legend=None):
    """MX keycap, printed face down. Flat top, rounded corners, MX cross socket in a square stem boss underneath.
    arrow=True engraves an up-pointing triangle 0.8 mm deep in the top face; legend='TEXT' engraves the key's name."""
    m = Mesh()
    H_STEM, H_TOP = 4.6, 3.0
    cw, cd = cap_wh(size)
    h, hd = cw / 2.0, cd / 2.0
    size = min(cw, cd)                                            # legend box is sized from the short side
    out = rounded([(-h, -hd), (h, -hd), (h, hd), (-h, hd)], 2.2)
    TOPZ = H_STEM + H_TOP
    cut_z = TOPZ - (LEGEND_DEPTH if legend else 0.8)
    m.prism(out, H_STEM, cut_z)                                   # cap body below the engraving
    if legend:
        lines = LEGEND_LINES.get(legend, legend.split(" ") if len(legend) > 7 else [legend])
        star = legend == "SHIFT" and _brand(LOGO_STAR)            # an optional brand symbol engraved above SHIFT
        bw, bh = cw - 3.4, (size - 4.4 if star else min(size - 6.0, 4.4 * len(lines) + 1.0))
        wx, wy = bw / 2.0, bh / 2.0
        for piece in (clip_x(out, None, -wx), clip_x(out, wx, None)):
            if len(piece) >= 3: m.prism(piece, cut_z, TOPZ)
        mid = clip_x(out, -wx, wx)
        for piece in (_clip_y(mid, None, -wy), _clip_y(mid, wy, None)):
            if len(piece) >= 3: m.prism(piece, cut_z, TOPZ)
        if star:                                                  # top 60 %: the symbol, bottom 40 %: the word
            sh = bh * 0.6
            for x0, y0, x1, y1 in _image_runs(LOGO_STAR, bw, sh, LEGEND_RES, solid="paper"):
                m.box(x0, y0 + bh / 2 - sh / 2, cut_z, x1, y1 + bh / 2 - sh / 2, TOPZ)
            for x0, y0, x1, y1 in _legend_runs(lines, bw, bh - sh):
                m.box(x0, y0 - bh / 2 + (bh - sh) / 2, cut_z, x1, y1 - bh / 2 + (bh - sh) / 2, TOPZ)
        else:
            for x0, y0, x1, y1 in _legend_runs(lines, bw, bh):
                m.box(x0, y0, cut_z, x1, y1, TOPZ)
    elif not arrow:
        m.prism(out, cut_z, TOPZ)
    else:                                                         # top layer = rounded square minus a triangle, built from strips
        n, tri_h, tri_w = 10, 8.0, 9.0
        wx = tri_w / 2.0 + 0.5
        for piece in (clip_x(out, None, -wx), clip_x(out, wx, None)):
            m.prism(piece, cut_z, TOPZ)
        mid = clip_x(out, -wx, wx)
        for piece in (_clip_y(mid, None, -tri_h / 2), _clip_y(mid, tri_h / 2, None)):
            m.prism(piece, cut_z, TOPZ)
        for k in range(n):
            y0 = -tri_h / 2 + tri_h * k / n; y1 = y0 + tri_h / n
            w = tri_w / 2.0 * (1 - (y0 + tri_h / 2) / tri_h) + 0.01   # half width at the strip's lower edge: wide at the bottom, point at the top
            m.box(-wx, y0, cut_z, -w, y1, TOPZ); m.box(w, y0, cut_z, wx, y1, TOPZ)
    sock = [(-2.05, -0.72, 2.05, 0.72), (-0.72, -2.05, 0.72, 2.05)]   # MX cross (4.1 x 1.44 mm bars, tolerances for printing)
    m.plate(-3.6, -3.6, 3.6, 3.6, 0, H_STEM, sock, [])               # stem boss with the cross cut right through the boss
    m.t = remap(m.t, lambda p: (p[0] + h, hd - p[1], TOPZ - p[2]))     # turned over (a rotation, not a mirror: the legend reads correctly once flipped back)
    return m


def keycap_set():
    """[(file name, keycap mesh, size)] for every key on the panel, legends included"""
    caps = []
    for (x, y, sz), name in zip(KEY_POS, PANEL_KEYS):
        caps.append(("keycap_" + name.lower().replace(" ", "_"), keycap(sz, legend=name), sz))
    caps.append(("keycap_ok", keycap(CAP_SMALL, legend="OK"), CAP_SMALL))
    caps.append(("keycap_song", keycap(CAP_SMALL, legend="SONG"), CAP_SMALL))
    for k in range(4): caps.append((f"keycap_arrow_{k + 1}", keycap(CAP_SMALL, True), CAP_SMALL))
    return caps


def keycap_plate(caps=None):
    """all the caps laid out on one bed, face down: the wide transport caps in their own row (34 mm pitch),
    then the square caps 6 per row at 26 mm pitch"""
    caps = caps or keycap_set()
    m = Mesh()
    wide = [c for c in caps if cap_wh(c[2])[0] > 22.0]
    square = [c for c in caps if cap_wh(c[2])[0] <= 22.0]
    for i, (_, cap, sz) in enumerate(wide):
        w, d = cap_wh(sz)
        ox, oy = i * 34.0, (22.0 - d) / 2.0
        m.t += [tuple((p[0] + ox, p[1] + oy, p[2]) for p in tri) for tri in cap.t]
    y0 = 26.0 if wide else 0.0
    for i, (_, cap, sz) in enumerate(square):
        w, d = cap_wh(sz)
        ox, oy = (i % 6) * 26.0 + (22.0 - w) / 2.0, y0 + (i // 6) * 26.0 + (22.0 - d) / 2.0
        m.t += [tuple((p[0] + ox, p[1] + oy, p[2]) for p in tri) for tri in cap.t]
    return m


def pad_test_coupon():
    """One pad opening in a lid-thickness plate: print it first and check your MPC pad sits in it properly."""
    m = Mesh()
    side = HOLE + 16
    m.plate(0, 0, side, side, 0, LID, [(8, 8, 8 + HOLE, 8 + HOLE)], [])
    return m


def pad_cap():
    m = Mesh()
    m.box(-FLANGE / 2, -FLANGE / 2, 0, FLANGE / 2, FLANGE / 2, FLANGE_T)
    m.box(-CAP / 2, -CAP / 2, FLANGE_T, CAP / 2, CAP / 2, FLANGE_T + LID + CAP_TOP_ABOVE_LID)
    return m


def rounded(pts, r, n=8):
    """Round the corners of a convex polygon (counter-clockwise) with radius r."""
    out = []
    for i in range(len(pts)):
        p0, v, p1 = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
        a = (p0[0] - v[0], p0[1] - v[1]); b = (p1[0] - v[0], p1[1] - v[1])
        la, lb = math.hypot(*a), math.hypot(*b)
        a = (a[0] / la, a[1] / la); b = (b[0] / lb, b[1] / lb)
        ang = math.acos(max(-1, min(1, a[0] * b[0] + a[1] * b[1])))
        d = min(r / math.tan(ang / 2.0), la / 2.0, lb / 2.0)
        q0 = (v[0] + a[0] * d, v[1] + a[1] * d); q1 = (v[0] + b[0] * d, v[1] + b[1] * d)
        for k in range(n + 1):
            t = k / float(n)
            out.append(((1 - t) ** 2 * q0[0] + 2 * t * (1 - t) * v[0] + t * t * q1[0],
                        (1 - t) ** 2 * q0[1] + 2 * t * (1 - t) * v[1] + t * t * q1[1]))
    return out


def ear_x():
    """x ranges of the two hinge ears (they slide in slots in the console's top and front)"""
    a = FR_X0 + EAR_U
    b = FR_X0 + FR_W - EAR_U
    return [(a - 1.5, a + 10 + 1.5), (b - 10 - 1.5, b + 1.5)]


CABLE_X = (110.0, 200.0)                              # cable slot through the sloped top, for the cables from the display frame


def _segments(xa, xb, windows, clip):
    """x intervals of [xa, xb] left after removing the windows, limited to the clip slice"""
    cuts = sorted(windows); out = []; x = xa
    for w0, w1 in cuts:
        if w0 > x: out.append((x, w0))
        x = max(x, w1)
    if x < xb: out.append((x, xb))
    if clip:
        out = [(max(a, clip[0]), min(b, clip[1])) for a, b in out if min(b, clip[1]) - max(a, clip[0]) > 1e-6]
    return out


def pi_holes():
    """world (x, z) of the four Pi mounting holes (board standing against the back wall)"""
    return [(PI_ORIGIN[0] + hx, PI_ORIGIN[1] + hy) for hx, hy in PI_HOLES]


def back_wall_holes():
    """(rects, rounds) for the console's back wall in (x, z): ports, vents, jacks; screw holes for the panel-mount connectors"""
    rects, rounds = [], []
    for name, x, z, w, h in PORTS:
        rects.append((x - w / 2, z - h / 2, x + w / 2, z + h / 2))
        for sx in (-1, 1): rounds.append((x + sx * (w / 2 + 5.0), z, PORT_SCREWS, 3.5))
    for x in VENT_X: rects.append((x - 1.5, VENT_Z[0], x + 1.5, VENT_Z[1]))
    rounds += [(x, JACK_Z_OUT, JACK_D / 2, 6.0) for x in JACK_X_OUT] + [(x, JACK_Z_IN, JACK_D / 2, 6.0) for x in JACK_X_IN]
    rounds.append((POWER_BTN[0], POWER_BTN[1], POWER_BTN[2] / 2, 8.0))
    return rects, rounds


def back_labels():
    """(text, x, z, window width) engraved into the back wall; they read correctly from behind"""
    out = [(f"OUT {k + 1}", x, JACK_Z_OUT - 11.0, 16.0) for k, x in enumerate(JACK_X_OUT)]
    out += [(f"IN {'LR'[k]}", x, JACK_Z_IN + 10.5, 14.0) for k, x in enumerate(JACK_X_IN)]
    out += [({"USB-A": "USB", "ETHERNET": "LAN", "USB-C PWR": "5V IN"}[name], x, 62.0, max(14.0, w + 2)) for name, x, z, w, h in PORTS]
    out.append(("POWER", POWER_BTN[0], 62.0, 15.0))
    return out


def riser(clip=None):
    """Rear console, in world coordinates (flat, y from the body's back wall). Hollow; open underneath."""
    m = Mesh(clip)
    zr = lambda h: ZB + h
    # --- front wall: logo recess 1 mm deep, then the through holes for the lights and VU windows ---
    ears = ear_x()
    pockets = [(x0, HINGE_Z - 15.0, x1, RT + 1) for x0, x1 in ears]               # slots for the hinge ears
    cable = [(CABLE_X[0] - 20, ZB - 24.0, CABLE_X[1] + 20, ZB - 4.0)]               # cable way from the body's back-wall slot into the console
    vu = []
    for hrow in VU_ROWS:
        for i in range(VU_N):
            cx = VU_X0 + i * VU_PITCH
            vu.append((cx - VU_WIN[0] / 2, zr(hrow) - VU_WIN[1] / 2, cx + VU_WIN[0] / 2, zr(hrow) + VU_WIN[1] / 2))
    leds = [(x, zr(h), LED_D / 2, LED_D / 2 + 2.5) for x, h, _ in LEDS]
    lg = (LOGO[0], zr(LOGO[2]), LOGO[1], zr(LOGO[3]))
    def layer(c0, c1, extra):
        loc = Mesh(clip)
        loc.plate(0, 0, W, RT, c0, c1, pockets + cable + vu + extra, leds)
        m.t += remap(loc.t, lambda p: (p[0], D + p[2], p[1]), flip=True)           # local (x, z, thickness) -> world (x, y, z): a swap, so flip
    layer(0.0, LOGO_DEPTH, [lg])                                                 # the pocket for logo_badge.stl
    layer(LOGO_DEPTH, RWALL, [])
    # --- floor and back wall ---
    m.box(0, D, 0, W, D + RISER_D, RWALL)
    back = Mesh(clip)                                                              # back wall with the audio jacks, ports, vents and the Pi standoffs
    rects, rounds = back_wall_holes()
    t_eng = RISER_D - LEGEND_DEPTH
    back.plate(0, RWALL, W, RZB, RISER_D - RWALL, t_eng, rects, rounds)            # local (x, z, y offset)
    wins = [(x - w / 2, z - 2.3, x + w / 2, z + 2.3) for _, x, z, w in back_labels()]
    back.plate(0, RWALL, W, RZB, t_eng, RISER_D, rects + wins, rounds)             # outer skin with a window for each label ...
    for text, x, z, w in back_labels():                                            # ... filled in except for the letters (mirrored: read from behind)
        for x0, z0, x1, z1 in _legend_runs([text], w, 4.6):
            back.box(x - x1, z + z0, t_eng, x - x0, z + z1, RISER_D)
    m.t += remap(back.t, lambda p: (p[0], D + p[2], p[1]), flip=True)
    pi = Mesh(clip)
    for x, z in pi_holes():
        if inrange(pi, x - 3.2, x + 3.2): pi.ring(x, z, 3.2, 1.1, RISER_D - RWALL - PI_STAND, RISER_D - RWALL)
    m.t += remap(pi.t, lambda p: (p[0], D + p[2], p[1]), flip=True)
    # --- flat top (y D .. RYK) with the ear slots ---
    flat = Mesh(clip)
    flat.plate(0, D, W, RYK, RT - 2.0, RT, [(a, D - 1, b, RYK + 1) for a, b in ears], [])
    m.t += flat.t
    # --- sloped top: extruded (y, z) quad between the slots ---
    for xa, xb in _segments(0, W, ears + [CABLE_X], clip):
        q = Mesh(); q.prism([(RYK, RT - 2.0), (D + RISER_D, RZB - 2.0), (D + RISER_D, RZB), (RYK, RT)][::1], xa, xb)   # local (y, z, x)
        m.t += remap(q.t, lambda p: (p[2], p[0], p[1]))
    # --- end walls: full rectangles in (y, z), with the rod hole and the cheek screw holes ---
    for x0 in (0.0, W - RWALL):
        if not inrange(m, x0, x0 + RWALL): continue
        e = Mesh()
        e.plate(D, 0, D + RISER_D, RT, 0, RWALL, [], [(HINGE_Y, HINGE_Z, 5.0, 8.0)] + [(y, z, 1.7, 5.0) for y, z in RISER_SCREWS])   # (x=y, y=z, z=x)
        m.t += remap(e.t, lambda p, x0=x0: (p[2] + x0, p[0], p[1]))
    # --- floor posts for the splice straps ---
    for jy in (D + 10.0, D + 22.0):
        for jx in (SPLIT_X - JOIN_DX, SPLIT_X + JOIN_DX):
            m.ring(jx, jy, 3.5, 1.3, RWALL, RWALL + 5)
    return m


def riser_print(clip=None):
    """Printing orientation: front face down on the bed (x, y, z) -> (x, RT - z, y - D); a proper rotation."""
    m = riser(clip)
    m.t = [tuple((p[0], RT - p[2], p[1] - D) for p in tri) for tri in m.t]
    if clip: m.recenter()
    return m


def poly_area(p):
    """signed area of a (y, z) outline (positive when anticlockwise)"""
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p, p[1:] + p[:1])) / 2


def cheek_top(y):
    """height of the cheek's top edge: flat beside the palm rest, a low rail parallel to the panel, then the console's top"""
    if y <= 0: return CH_ZF
    if y < D: return plane(0, y) + LID + CH_RAIL
    if y <= RYK: return RT
    return RT - (y - RYK) * (RT - RZB) / (CH_Y1 - RYK)


def cheek_profile():
    """Outline of one wooden cheek as (y, z) points, front at the left, all straight saw cuts: flat beside the palm rest,
    a low rail 6 mm above the panel (so the cheek never walls in the Q knobs or pads), a square step up at the console's
    front face, the console's flat top, and the short bevel at the back that lets the screen lean back."""
    return [(CH_Y0, 0.0), (CH_Y1, 0.0), (CH_Y1, RZB), (RYK, RT), (D, RT), (D, ZB + CH_RAIL), (0.0, CH_ZF), (CH_Y0, CH_ZF)]


def cheek_pieces():
    """convex pieces whose union is the cheek (for the 3D model): beside the palm rest, beside the panel, the console end"""
    return [[(CH_Y0, 0.0), (0.0, 0.0), (0.0, CH_ZF), (CH_Y0, CH_ZF)],
            [(0.0, 0.0), (D, 0.0), (D, ZB + CH_RAIL), (0.0, CH_ZF)],
            [(D, 0.0), (CH_Y1, 0.0), (CH_Y1, RZB), (RYK, RT), (D, RT)]]


def cheek_holes():
    """(y, z, diameter, note) for the wood: hinge rod through, cheek screws as blind pilots."""
    return [(HINGE_Y, HINGE_Z, 8.2, f"hinge rod, BLIND hole {ROD_IN:.0f} mm deep from the inner face (not through)")] + \
           [(-PR_D / 2, PR_BOLT_Z, 3.0, "pilot for the palm rest, 17 mm deep, from the inner face")] + \
           [(y, CHEEK_SCREW_Z, 3.0, "pilot, 17 mm deep, from the inner face") for y in CHEEK_SCREW_Y] + \
           [(y, z, 3.0, "pilot for the rear console, 17 mm deep") for y, z in RISER_SCREWS]


def cheek_world(side):
    """Reference cheek: side 0 on the left (x < 0), side 1 on the right (x > W)."""
    m = Mesh()
    for poly in cheek_pieces(): m.prism(poly, 0, CHEEK_T)       # (x=y, y=z, z=thickness)
    x0 = -CHEEK_T if side == 0 else W
    return remap(m.t, lambda p: (p[2] + x0, p[0], p[1]))


def cheek_reference():
    m = Mesh(); m.t = cheek_world(0)
    return m


if __name__ == "__main__":
    left, right = (0, SPLIT_X), (SPLIT_X, W)
    parts = [("controller_base_left", base(left)), ("controller_base_right", base(right)),
             ("controller_lid_left", lid(left)), ("controller_lid_right", lid(right)),
             ("join_strap", join_strap()), ("rear_console_left", riser_print(left)), ("rear_console_right", riser_print(right)), ("keycap_transport", keycap(CAP_TR)), ("keycap_small", keycap(CAP_SMALL)),
             ("keycap_arrow", keycap(CAP_SMALL, True)), ("keycaps_all", keycap_plate()), *zip(["frame_bezel_left", "frame_bezel_right", "frame_tray_left", "frame_tray_right"], frame_halves()),
             ("hinge_spacer", hinge_spacer()), ("jog_wheel", jog_wheel()), ("pad_test_coupon", pad_test_coupon()), ("logo_badge", logo_badge()),
             ("palmrest_left", palmrest_print(left)), ("palmrest_right", palmrest_print(right)), ("pad_cap", pad_cap()),
             ("cheek_reference", cheek_reference()),
             ("controller_base_full", base(joins=False)), ("controller_lid_full", lid(joins=False))]
    for name, mesh in parts:
        if mesh is not None: mesh.save(name + ".stl")             # (logo_badge only exists once a logo is in brand/)
    import os
    os.makedirs("keycaps", exist_ok=True)
    for name, mesh, _ in keycap_set():                         # one file per key, for reprinting a single cap
        if "arrow" not in name: mesh.save(os.path.join("keycaps", name + ".stl"))
    print(f"body {W:.0f} x {D:.0f} mm plan ({SD:.0f} along the slope, tilt {TILT:.0f} deg), cut at x = {SPLIT_X:.1f} mm; "
          f"between cheeks {W:.0f} mm, overall with {CHEEK_T:.0f} mm cheeks {W + 2 * CHEEK_T:.0f} mm; frame {FR_W:.0f} x {FR_H:.0f} x {FR_T:.0f} mm; "
          f"hinge rod M8 x {ROD_LEN:.0f} mm (in blind holes: nothing on the outer faces)")
