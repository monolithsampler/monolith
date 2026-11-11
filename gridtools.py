"""
gridtools.py - GRID's editing: a toolbar of plain icons and the touch behaviour of the note area (pads and piano roll).

Toolbar (under the header, left to right, grouped by job):
  tools      DRAW (pencil)  SELECT (dashed box)  ERASE (eraser)              = F1 F2 F3
  selection  ALL (select every note; SHIFT: this row)  DELETE (bin)          = F4 deletes
  view       SNAP < 1/16 >   ZOOM - 2 BARS +   ROWS 8 / 16   LANE (velocity / automation / off)

The note area, by tool:
  DRAW    tap empty: a note (drag right while holding: its length) - tap a note: select it - drag a note: move it
          (and the rest of the selection with it) - drag a note's right end: its length
  SELECT  drag on empty: a box; the notes in it are selected (SHIFT adds) - tap a note: select it (SHIFT: add / remove)
          - drag a selected note: move the selection
  ERASE   tap or drag over notes: gone
The knobs then work on the selection: Q1 NUDGE (one tick a click), Q2 LENGTH, Q3 VELOCITY, Q4 ZOOM; SHIFT + < > nudge,
the wheel sets velocity (SHIFT: length), F4 deletes.
"""
from uicore import ORANGE, CYAN, YEL, RED, TEXT, DIM, clamp
from engine import QUANT


# ---------------------------------------------------------------------------------------------------------- icons
def icon(r, kind, cx, cy, s, col):
    d = r.d
    w = max(1, round(s / 6))
    if kind == "draw":                                                # a pencil
        d.line([(cx - s * 0.55, cy + s * 0.55), (cx + s * 0.35, cy - s * 0.35)], fill=col, width=int(w * 2.4))
        d.polygon([(cx - s * 0.7, cy + s * 0.7), (cx - s * 0.62, cy + s * 0.36), (cx - s * 0.36, cy + s * 0.62)], fill=col)
        d.line([(cx + s * 0.42, cy - s * 0.42), (cx + s * 0.6, cy - s * 0.6)], fill=col, width=int(w * 2.4))
    elif kind == "select":                                            # a dashed box with a pointer
        x0, y0, x1, y1 = cx - s * 0.7, cy - s * 0.55, cx + s * 0.45, cy + s * 0.45
        for k in range(6):
            t0, t1 = k / 6.0, (k + 0.5) / 6.0
            d.line([(x0 + (x1 - x0) * t0, y0), (x0 + (x1 - x0) * t1, y0)], fill=col, width=w)
            d.line([(x0 + (x1 - x0) * t0, y1), (x0 + (x1 - x0) * t1, y1)], fill=col, width=w)
            d.line([(x0, y0 + (y1 - y0) * t0), (x0, y0 + (y1 - y0) * t1)], fill=col, width=w)
            d.line([(x1, y0 + (y1 - y0) * t0), (x1, y0 + (y1 - y0) * t1)], fill=col, width=w)
        d.polygon([(cx + s * 0.1, cy + s * 0.05), (cx + s * 0.75, cy + s * 0.35), (cx + s * 0.4, cy + s * 0.45),
                   (cx + s * 0.3, cy + s * 0.8)], fill=col)
    elif kind == "erase":                                             # an eraser
        d.polygon([(cx - s * 0.75, cy + s * 0.2), (cx - s * 0.05, cy - s * 0.6), (cx + s * 0.7, cy + s * 0.05),
                   (cx + s * 0.05, cy + s * 0.75)], outline=col, width=w)
        d.polygon([(cx - s * 0.75, cy + s * 0.2), (cx - s * 0.4, cy - s * 0.2), (cx + s * 0.35, cy + s * 0.45),
                   (cx + s * 0.05, cy + s * 0.75)], fill=col)
    elif kind == "bin":                                               # a bin
        d.line([(cx - s * 0.6, cy - s * 0.45), (cx + s * 0.6, cy - s * 0.45)], fill=col, width=w + 1)
        d.line([(cx - s * 0.2, cy - s * 0.62), (cx + s * 0.2, cy - s * 0.62)], fill=col, width=w + 1)
        d.polygon([(cx - s * 0.45, cy - s * 0.35), (cx + s * 0.45, cy - s * 0.35), (cx + s * 0.35, cy + s * 0.7),
                   (cx - s * 0.35, cy + s * 0.7)], outline=col, width=w)
        for k in (-0.15, 0.15): d.line([(cx + s * k, cy - s * 0.15), (cx + s * k, cy + s * 0.5)], fill=col, width=w)
    elif kind == "all":                                               # four notes in a box
        d.rectangle([cx - s * 0.7, cy - s * 0.6, cx + s * 0.7, cy + s * 0.6], outline=col, width=w)
        for (dx, dy) in ((-0.4, -0.3), (0.05, -0.3), (-0.2, 0.2), (0.3, 0.2)):
            d.rectangle([cx + s * dx, cy + s * dy - s * 0.1, cx + s * dx + s * 0.28, cy + s * dy + s * 0.1], fill=col)
    elif kind == "magnet":                                            # SNAP
        import math
        pts = [(cx + s * 0.6 * math.cos(math.pi + math.pi * k / 10), cy - s * 0.1 + s * 0.6 * math.sin(math.pi + math.pi * k / 10)) for k in range(11)]
        d.line(pts, fill=col, width=int(w * 2.2))
        for sx in (-0.6, 0.6):
            d.line([(cx + s * sx, cy - s * 0.1), (cx + s * sx, cy + s * 0.55)], fill=col, width=int(w * 2.2))
            d.line([(cx + s * sx - s * 0.12, cy + s * 0.55), (cx + s * sx + s * 0.12, cy + s * 0.55)], fill=RED, width=int(w * 2.2))
    elif kind == "zoom":                                              # a magnifier
        d.ellipse([cx - s * 0.6, cy - s * 0.6, cx + s * 0.25, cy + s * 0.25], outline=col, width=int(w * 1.6))
        d.line([(cx + s * 0.15, cy + s * 0.15), (cx + s * 0.65, cy + s * 0.65)], fill=col, width=int(w * 2.4))
    elif kind == "rows":                                              # lanes
        for k in range(3): d.rectangle([cx - s * 0.6, cy - s * 0.55 + k * s * 0.42, cx + s * 0.6, cy - s * 0.32 + k * s * 0.42], fill=col)
    elif kind == "lane":                                              # velocity bars
        for k, h in enumerate((0.5, 0.9, 0.3, 0.7)):
            x = cx - s * 0.6 + k * s * 0.38
            d.rectangle([x, cy + s * 0.6 - s * 1.2 * h, x + s * 0.2, cy + s * 0.6], fill=col)


def tool_key(r, rect, kind, label, on, fn, accent=ORANGE):
    x0, y0, x1, y1 = rect
    r.keycap(rect, "lit" if on else "up", 4, accent)
    col = (255, 255, 255) if on else (185, 190, 200)
    icon(r, kind, x0 + 11, (y0 + y1) / 2, 7, col)
    if label: r.lab(x0 + 21, (y0 + y1) / 2, label, 5.4, col, "lm", "s", 0.06, floor=4.4, maxw=x1 - x0 - 23)
    r.hit((x0, y0 - 2, x1, y1 + 2), down=lambda *_: fn())


def stepper(r, x0, x1, y0, y1, kind, value, dec, inc):
    """an icon, then < value > (or - value +): one control for one setting"""
    r.well((x0, y0, x1, y1), 4, (20, 22, 26), 4)
    icon(r, kind, x0 + 10, (y0 + y1) / 2, 6, (165, 171, 183))
    sym = ("-", "+") if kind == "zoom" else ("<", ">")
    r.btn((x0 + 19, y0 + 2, x0 + 35, y1 - 2), sym[0], dec, 10, grow=2)
    r.btn((x1 - 18, y0 + 2, x1 - 2, y1 - 2), sym[1], inc, 10, grow=2)
    r.vt((x0 + 35 + x1 - 18) / 2.0, (y0 + y1) / 2.0, value, 11.5, (255, 176, 102), "mm", maxw=x1 - x0 - 56)


def toolbar(r, y0=69, y1=91):
    c, e = r.c, r.e
    notes = e.track.kind in ("keys", "plugin", "midi")
    tool_key(r, (6, y0, 52, y1), "draw", "DRAW", c.g_tool == "DRAW", lambda: c.g_set_tool("DRAW"))
    tool_key(r, (55, y0, 108, y1), "select", "SELECT", c.g_tool == "SELECT", lambda: c.g_set_tool("SELECT"))
    tool_key(r, (111, y0, 158, y1), "erase", "ERASE", c.g_tool == "ERASE", lambda: c.g_set_tool("ERASE"))
    nsel = len([ev for ev in c.g_set if ev in e.track.events])
    tool_key(r, (166, y0, 202, y1), "all", "ALL", False, c.g_select_all)
    tool_key(r, (205, y0, 246, y1), "bin", str(nsel) if nsel > 1 else "", False, c.g_delete, RED)
    stepper(r, 254, 350, y0, y1, "magnet", QUANT[e.qgrid][0], lambda: c.g_snap_step(-1), lambda: c.g_snap_step(1))
    stepper(r, 356, 462, y0, y1, "zoom", f"{c.g_bars} BAR" + ("S" if c.g_bars > 1 else ""), lambda: c.g_zoom_step(-1),
            lambda: c.g_zoom_step(1))
    rows_lab = ("1 OCT" if c.g_lanes == 8 else "2 OCT") if notes else ("8 ROWS" if c.g_lanes == 8 else "16 ROWS")
    tool_key(r, (468, y0, 530, y1), "rows", rows_lab, False, lambda: setattr(c, "g_lanes", 16 if c.g_lanes == 8 else 8))
    tool_key(r, (533, y0, 600, y1), "lane", {"OFF": "LANE", "VEL": "VELOCITY", "AUTO": "AUTOMATE"}[c.g_view], c.g_view != "OFF",
             c.cycle_lane, CYAN)
    # what the selection is, at the right (the knobs edit it)
    sel = c.g_selection()
    if sel:
        ev = sel[0]
        txt = (f"{len(sel)} NOTES" if len(sel) > 1 else "NOTE") + f"  VEL {ev[2]}  LEN {ev[3]}t"
        r.lab(790, (y0 + y1) / 2, txt, 4.8, (230, 233, 240), "rm", "s", 0.08, maxw=185)
    else:
        hint = {"DRAW": "TAP TO ADD - DRAG END = LENGTH", "SELECT": "DRAG A BOX AROUND NOTES", "ERASE": "TAP / DRAG TO ERASE"}[c.g_tool]
        r.lab(790, (y0 + y1) / 2, hint, 4.4, (130, 136, 148), "rm", "s", 0.08, maxw=185)


# ---------------------------------------------------------------------------------------------------------- touch
def note_rect(ev, gx0, ppt, off, y_of, lane_h, gx1):
    x = gx0 + (ev[0] - off) * ppt
    w = max(3, min(ev[3] * ppt - 1.5, gx1 - 4 - x))
    y = y_of(ev[1])
    return x, y, w


def install(r, area, ppt, s, pitch_at, y_of, lane_h, lo, hi):
    """the note area's touch: area = (gx0, gy0, gx1, gy1) in layout units; pitch_at(py) -> pitch row; y_of(pitch) -> top y;
    lo..hi = the pitches visible (moves are kept inside them)"""
    c, e = r.c, r.e
    sq, tr = e.seq, e.track
    gx0, gy0, gx1, gy1 = area
    state = {}

    def tick_at(px, snap=True):
        t = c.g_off + (px - gx0) / ppt
        return int(t // s * s) if snap else t

    def note_at(px, py):
        raw = tick_at(px, False); p = pitch_at(py)
        cand = [ev for ev in tr.events if ev[1] == p and ev[0] <= raw < ev[0] + max(ev[3], s * 0.5)]
        return cand[-1] if cand else None

    def place(evs):                                                  # put a list of notes in, return them as stored
        with e.lock:
            tr.events = sorted(tr.events + [tuple(v) for v in evs])
        return [tuple(v) for v in evs]

    def take(evs):
        with e.lock:
            for ev in evs:
                if ev in tr.events: tr.events.remove(ev)

    def down(px, py):
        tick, p = clamp(tick_at(px), 0, sq.length - s), pitch_at(py)
        c.g_tick = tick; c.g_lane = p if tr.kind in ("keys", "plugin", "midi") else p - e.bank * 16
        if tr.kind not in ("keys", "plugin", "midi"): e.sel = c.g_lane
        ev = note_at(px, py)
        state.clear(); state.update(x=px, y=py, tick=tick, p=p)
        tool = c.g_tool
        if tool == "ERASE":
            e.begin_edit(); state["mode"] = "erase"
            if ev: take([ev]); c.g_set = [x for x in c.g_set if x != ev]
            return
        if ev is not None:
            x, y, w = note_rect(ev, gx0, ppt, c.g_off, y_of, lane_h, gx1)
            edge = px >= x + w - max(4.0, min(10.0, w * 0.3))
            if c.shift and tool == "SELECT":                          # SHIFT + tap: add / remove
                c.shift_used = True
                c.g_set = [x_ for x_ in c.g_set if x_ != ev] if ev in c.g_set else [x_ for x_ in c.g_set if x_ in tr.events] + [ev]
                c.g_sel = ev; state["mode"] = None; return
            group = [x_ for x_ in c.g_set if x_ in tr.events]
            if ev not in group: c.g_set, group = [], [ev]
            c.g_sel = ev
            e.begin_edit()
            if edge and tool == "DRAW": state.update(mode="len", orig=group, ref=ev)
            else: state.update(mode="move", orig=group, cur=list(group), ref=ev)
            if tool == "DRAW" or len(group) == 1:
                pad = e.prog.pads[ev[1]] if tr.kind == "drum" and ev[1] < len(e.prog.pads) else None
                if pad is not None: e.trigger(pad, ev[2])
                elif tr.kind != "drum": e.audition(ev[1], ev[2])
            return
        if tool == "SELECT":                                          # a box
            if not c.shift: c.g_set = []
            else: c.shift_used = True
            c.g_box = (px, py, px, py); state["mode"] = "box"; state["base"] = [x_ for x_ in c.g_set if x_ in tr.events]
            return
        e.begin_edit()                                               # DRAW on empty: a new note; dragging right sets its length
        new = place([(tick, p, c.step_vel, s)])[0]
        c.g_sel, c.g_set = new, []
        state.update(mode="len", orig=[new], ref=new)
        if tr.kind == "drum": e.trigger(e.prog.pads[p], c.step_vel)
        else: e.audition(p, c.step_vel)

    def drag(px, py):
        m = state.get("mode")
        if m == "erase":
            ev = note_at(px, py)
            if ev: take([ev]); c.g_set = [x for x in c.g_set if x != ev]
        elif m == "box":
            x0_, y0_ = state["x"], state["y"]
            c.g_box = (x0_, y0_, px, py)
            ta, tb = sorted((c.g_off + (x0_ - gx0) / ppt, c.g_off + (px - gx0) / ppt))
            pa, pb = sorted((pitch_at(y0_), pitch_at(py)))
            inside = [ev for ev in tr.events if pa <= ev[1] <= pb and ev[0] + ev[3] > ta and ev[0] <= tb]
            c.g_set = list(dict.fromkeys(state["base"] + inside))
            c.g_sel = c.g_set[0] if c.g_set else None
        elif m == "len":
            ref = state["ref"]
            end = max(ref[0] + 3, int(round((c.g_off + (px - gx0) / ppt) / s)) * s)
            dl = max(3, end - ref[0]) - ref[3]
            cur = state.get("cur", state["orig"])
            new = [(ev[0], ev[1], ev[2], int(clamp(ev[3] + dl, 3, sq.length))) for ev in state["orig"]]
            if new != cur:
                take(cur); state["cur"] = place(new)
                c.g_sel = state["cur"][state["orig"].index(ref)]
                if len(new) > 1 or c.g_set: c.g_set = list(state["cur"])
        elif m == "move":
            dt = int(round((c.g_off + (px - gx0) / ppt - (c.g_off + (state["x"] - gx0) / ppt)) / s)) * s
            dp = pitch_at(py) - state["p"]
            orig = state["orig"]
            dp = int(clamp(dp, lo - min(ev[1] for ev in orig), hi - max(ev[1] for ev in orig)))
            new = [((ev[0] + dt) % sq.length, ev[1] + dp, ev[2], ev[3]) for ev in orig]
            cur = state["cur"]
            if new != cur:
                take(cur); state["cur"] = place(new)
                ref_i = orig.index(state["ref"])
                c.g_sel = state["cur"][ref_i]
                if len(orig) > 1: c.g_set = list(state["cur"])
                c.g_tick = c.g_sel[0]
    r.hit(area, down=down, drag=drag)


def draw_box(r):
    c = r.c
    if c.g_box is None: return
    x0, y0, x1, y1 = c.g_box
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
    r.d.rectangle([x0, y0, x1, y1], outline=CYAN, width=1)


def selected(c, ev):
    return ev in c.g_set or ev == c.g_sel
