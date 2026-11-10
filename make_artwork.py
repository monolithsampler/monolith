#!/usr/bin/env python3
"""1:1 printable templates (SVG, units = mm; print at 100 %):
   panel_artwork.svg  - the top panel: cut-outs, screw holes, legend text (use as a drill/label template or print on a vinyl sticker)
   cheek_template.svg - one wooden cheek with the hinge-rod hole and the 4 screw pilots (cut/drill both cheeks together)"""
import os
import make_stl as M

def svg(w, h, body, name):
    open(name, "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}" font-family="DejaVu Sans, Arial">'
                          f'<rect width="{w}" height="{h}" fill="white"/>{body}</svg>')
    print("wrote", name)

def panel():
    H = M.SD; b = []
    Y = lambda s: H - s                      # panel s (front = 0) -> svg y (front at the bottom)
    b.append(f'<rect x="0" y="0" width="{M.W}" height="{H}" fill="none" stroke="black" stroke-width="0.4"/>')
    b.append(f'<line x1="{M.SPLIT_X}" y1="0" x2="{M.SPLIT_X}" y2="{H}" stroke="#c00" stroke-width="0.3" stroke-dasharray="3 2"/>'
             f'<text x="{M.SPLIT_X+1.5}" y="6" font-size="3" fill="#c00">print split</text>')
    for i, (cx, cy) in enumerate(M.PAD_CENTERS):
        h = M.HOLE / 2
        b.append(f'<rect x="{cx-h}" y="{Y(cy)-h}" width="{M.HOLE}" height="{M.HOLE}" fill="none" stroke="black" stroke-width="0.4"/>'
                 f'<text x="{cx}" y="{Y(cy)+2}" font-size="6" text-anchor="middle" fill="#888">{i+1}</text>')
    def hole(x, y, d, label, dy=-9, fs=3.2):
        b.append(f'<circle cx="{x}" cy="{Y(y)}" r="{d/2}" fill="none" stroke="black" stroke-width="0.4"/>'
                 f'<line x1="{x-2}" y1="{Y(y)}" x2="{x+2}" y2="{Y(y)}" stroke="#999" stroke-width="0.2"/><line x1="{x}" y1="{Y(y)-2}" x2="{x}" y2="{Y(y)+2}" stroke="#999" stroke-width="0.2"/>'
                 f'<text x="{x}" y="{Y(y)+dy*-1 if dy>0 else Y(y)+dy}" font-size="{fs}" text-anchor="middle">{label}</text>')
    def mx(x, y, size, label, fill="none"):
        cw, cd = M.cap_wh(size); size = cd
        b.append(f'<rect x="{x-cw/2}" y="{Y(y)-cd/2}" width="{cw}" height="{cd}" rx="2" fill="{fill}" stroke="#bbb" stroke-width="0.25" stroke-dasharray="1.2 1"/>'      # cap outline (guide only)
                 f'<rect x="{x-M.MX_HOLE/2}" y="{Y(y)-M.MX_HOLE/2}" width="{M.MX_HOLE}" height="{M.MX_HOLE}" fill="none" stroke="black" stroke-width="0.4"/>'                   # 14.2 plate cut-out
                 f'<rect x="{x-M.MX_RECESS/2}" y="{Y(y)-M.MX_RECESS/2}" width="{M.MX_RECESS}" height="{M.MX_RECESS}" fill="none" stroke="#06c" stroke-width="0.2"/>'            # 15.8 recess
                 f'<text x="{x}" y="{Y(y)+1.1}" font-size="{2.5 if size < 20 else 3.2}" text-anchor="middle" font-weight="bold">{label}</text>')
    for (x, y, sz), n in zip(M.KEY_POS, M.PANEL_KEYS): mx(x, y, sz, n.replace("NOTE ", "N."))
    for (x, y, sz), n in zip(M.ARROW_POS, ["UP", "DOWN", "LEFT", "RIGHT"]): mx(x, y, sz, n)
    mx(M.OK_POS[0], M.OK_POS[1], M.OK_POS[2], "OK")
    mx(M.SONG_POS[0], M.SONG_POS[1], M.SONG_POS[2], "SONG (Pi)")
    for k, (x, y) in enumerate(M.POT_POS): hole(x, y, M.POT_D, f"Q{k+1}", -10)
    for x, y, sz in [M.KEY_POS[M.PANEL_KEYS.index(f)] for f in ("F1", "F2", "F3", "F4")]: b.append(f'<text x="{x}" y="{Y(y)+12}" font-size="2.6" text-anchor="middle" fill="#06c">soft key (on-screen F label)</text>')
    hole(M.JOG_POS[0], M.JOG_POS[1], M.JOG_D, "JOG", 0)
    b.append(f'<circle cx="{M.JOG_POS[0]}" cy="{Y(M.JOG_POS[1])}" r="{M.JOG_WHEEL_D/2}" fill="none" stroke="#999" stroke-width="0.3" stroke-dasharray="2 2"/>')
    for x, y in M.SCREWS: b.append(f'<circle cx="{x}" cy="{Y(y)}" r="1.7" fill="none" stroke="black" stroke-width="0.3"/>')
    b.append(f'<text x="2" y="{H+12}" font-size="3.5">Dashed circle = jog wheel clearance ({M.JOG_WHEEL_D:.0f} mm). Front edge at the bottom.</text>')
    b.append(f'<text x="2" y="{H+7}" font-size="3.5">Panel artwork, 1:1, slope length {M.SD:.0f} mm. Black square = 14.2 mm MX cut-out (blue = 15.8 mm top recess, grey dashes = printed keycap).</text>')
    svg(M.W, H + 16, "".join(b), "panel_artwork.svg")

def cheek():
    prof = M.cheek_profile(); ys = [p[0] for p in prof]; zs = [p[1] for p in prof]
    ox, W, Hh = -min(ys) + 5, max(ys) - min(ys) + 10, max(zs) + 30
    X = lambda y: y + ox; Z = lambda z: max(zs) + 8 - z
    pts = " ".join(f"{X(y):.2f},{Z(z):.2f}" for y, z in prof)
    b = [f'<polygon points="{pts}" fill="#e8c99a" stroke="black" stroke-width="0.4"/>']
    for y, z, d, note in M.cheek_holes():
        b.append(f'<circle cx="{X(y)}" cy="{Z(z)}" r="{d/2}" fill="{'none' if d > 20 else 'white'}" stroke="black" stroke-width="0.4" {'stroke-dasharray="1.5 1"' if d > 20 else ''}/>'
                 f'<line x1="{X(y)-5}" y1="{Z(z)}" x2="{X(y)+5}" y2="{Z(z)}" stroke="#c00" stroke-width="0.2"/><line x1="{X(y)}" y1="{Z(z)-5}" x2="{X(y)}" y2="{Z(z)+5}" stroke="#c00" stroke-width="0.2"/>'
                 + (f'<text x="{X(y)}" y="{Z(z)+d/2+4}" font-size="3" text-anchor="middle">{d:g} x 12 deep, outer face</text>' if d > 20 else
                  f'<text x="{X(y)}" y="{Z(z)-8 if d>5 else Z(z)-5}" font-size="3" text-anchor="middle">{d:g} mm</text>'))
    b.append(f'<text x="5" y="{Hh-13}" font-size="3.4">Cheek template 1:1, timber {M.CHEEK_T:.0f} mm thick. Front is on the left, bottom edge sits flat on the table.</text>'
             f'<text x="5" y="{Hh-8}" font-size="3.4">Cut both cheeks together (the second is a mirror image).</text>'
             f'<text x="5" y="{Hh+2}" font-size="3.4">Rod hole (inner face only, {M.ROD_IN:.0f} mm deep): {M.HINGE_Y-M.CH_Y0:.1f} mm from the front edge, {M.HINGE_Z:.1f} mm up. Screw pilots 3 mm, 17 mm deep, from the inner face. Nothing goes through to the outer face.</text>')
    svg(W, Hh + 6, "".join(b), "cheek_template.svg")

panel(); cheek()


def fascia():
    """1:1 template of the rear console's front face: cut-outs for lights, VU windows and the logo recess; plus the back wall (jacks, ports, vents)"""
    h = M.FASCIA_H; b = []
    Y = lambda hh: h - hh
    b.append(f'<rect x="0" y="0" width="{M.W}" height="{h}" fill="none" stroke="black" stroke-width="0.4"/>')
    x0, x1, h0, h1 = M.LOGO
    b.append(f'<rect x="{x0}" y="{Y(h1)}" width="{x1-x0}" height="{h1-h0}" fill="none" stroke="#06c" stroke-width="0.3"/>'
             f'<text x="{x0}" y="{Y(h0)+3.2}" font-size="2.4" fill="#06c">badge pocket {M.LOGO_DEPTH} mm deep (for a logo badge or sticker later)</text>')
    badge_svg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand", "badge.svg")
    if os.path.exists(badge_svg):                                   # once there is a logo (brand/make_brand.py): the badge, 1:1
        import re
        icon = open(badge_svg).read()
        vw, vh = [float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', icon).groups()]
        dpath = re.search(r' d="([^"]+)"', icon).group(1)
        fill = re.search(r' fill="([^"]+)"', icon).group(1)
        g = M.BADGE_GAP; bw, bh = x1 - x0 - 2 * g, h1 - h0 - 2 * g
        iw, ih = bw - 2 * M.BADGE_MARGIN, bh - 2 * M.BADGE_MARGIN
        k = min(iw / vw, ih / vh)
        ox, oy_ = x0 + g + (bw - vw * k) / 2, Y(h1) + g + (bh - vh * k) / 2
        b.append(f'<rect x="{x0+g}" y="{Y(h1)+g}" width="{bw}" height="{bh}" rx="1.2" fill="#141418"/>'
                 f'<path transform="translate({ox:.3f},{oy_:.3f}) scale({k:.5f})" fill="{fill}" fill-rule="evenodd" d="{dpath}"/>')
    for x, hh, nm in M.LEDS:
        b.append(f'<circle cx="{x}" cy="{Y(hh)}" r="{M.LED_D/2}" fill="none" stroke="black" stroke-width="0.4"/><text x="{x}" y="{Y(hh-6)}" font-size="2.6" text-anchor="middle">{nm}</text>')
    for row, hrow in enumerate(M.VU_ROWS):
        for i in range(M.VU_N):
            cx = M.VU_X0 + i * M.VU_PITCH
            b.append(f'<rect x="{cx-M.VU_WIN[0]/2}" y="{Y(hrow)-M.VU_WIN[1]/2}" width="{M.VU_WIN[0]}" height="{M.VU_WIN[1]}" fill="none" stroke="black" stroke-width="0.4"/>')
        b.append(f'<text x="{M.VU_X0-9}" y="{Y(hrow)+1.2}" font-size="3.5" text-anchor="middle">{"LR"[row]}</text>')
    b.append(f'<text x="2" y="{h+6}" font-size="3">Rear console, front face, 1:1. h = 0 is the top of the panel back edge; the face continues {M.ZB:.0f} mm below that, hidden behind the body.</text>')
    # --- back wall, seen from BEHIND (so it is mirrored left-right compared with the sampler's own x); z = 0 is the table ---
    oy = h + 16; hb = M.RZB
    X = lambda x: M.W - x; Z = lambda z: oy + hb - z
    b.append(f'<rect x="0" y="{oy}" width="{M.W}" height="{hb}" fill="none" stroke="black" stroke-width="0.4"/>')
    for k, x in enumerate(M.JACK_X_OUT):
        b.append(f'<circle cx="{X(x)}" cy="{Z(M.JACK_Z_OUT)}" r="{M.JACK_D/2}" fill="none" stroke="black" stroke-width="0.4"/><text x="{X(x)}" y="{Z(M.JACK_Z_OUT-10)}" font-size="3" text-anchor="middle">OUT {k+1}</text>')
    for k, x in enumerate(M.JACK_X_IN):
        b.append(f'<circle cx="{X(x)}" cy="{Z(M.JACK_Z_IN)}" r="{M.JACK_D/2}" fill="none" stroke="black" stroke-width="0.4"/><text x="{X(x)}" y="{Z(M.JACK_Z_IN+8)}" font-size="3" text-anchor="middle">IN {"LR"[k]}</text>')
    for name, x, z, w, hh in M.PORTS:
        b.append(f'<rect x="{X(x)-w/2}" y="{Z(z)-hh/2}" width="{w}" height="{hh}" fill="none" stroke="black" stroke-width="0.4"/><text x="{X(x)}" y="{Z(z+hh/2+3)}" font-size="3" text-anchor="middle">{name}</text>')
        for sx in (-1, 1): b.append(f'<circle cx="{X(x)+sx*(w/2+5)}" cy="{Z(z)}" r="{M.PORT_SCREWS}" fill="none" stroke="black" stroke-width="0.3"/>')
    for x in M.VENT_X:
        b.append(f'<rect x="{X(x)-1.5}" y="{Z(M.VENT_Z[1])}" width="3" height="{M.VENT_Z[1]-M.VENT_Z[0]}" fill="none" stroke="#c60" stroke-width="0.3"/>')
    px0, pz0 = M.PI_ORIGIN
    b.append(f'<rect x="{X(px0+85)}" y="{Z(pz0+56)}" width="85" height="56" fill="none" stroke="#2a2" stroke-width="0.3" stroke-dasharray="2 1"/><text x="{X(px0+42.5)}" y="{Z(pz0+56)-1.5}" font-size="3" text-anchor="middle" fill="#2a2">Pi 5 + HAT inside (standoffs on this wall)</text>')
    b.append(f'<line x1="{X(M.SPLIT_X)}" y1="{oy}" x2="{X(M.SPLIT_X)}" y2="{oy+hb}" stroke="#999" stroke-width="0.3" stroke-dasharray="1 1"/>')
    b.append(f'<text x="2" y="{oy+hb+6}" font-size="3">Rear console, back wall seen from behind, 1:1 (mirrored compared with the front). Bottom edge = table. Dashed grey = print split. Check your connectors\' cut-outs before printing.</text>')
    svg(M.W, oy + hb + 10, "".join(b), "console_artwork.svg")


fascia()
