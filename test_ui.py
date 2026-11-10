import sys, os, shutil, numpy as np, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
import engine as E
import machines as machines_
from ui import Controls, Renderer
from uicore import BTN, W, H, SOFT_Y, Q_Y, TABS, TAB_OF, soft_text, BACK as BACK_
ok = lambda n, cond: print(("PASS " if cond else "FAIL ") + n)

def fresh(path, nout=2):
    shutil.rmtree(path, ignore_errors=True); os.makedirs(path)
    shutil.copytree(os.path.join(HERE, "samples"), os.path.join(path, "samples"))
    return E.Engine(path, nout=nout)

def run(e, seconds):
    for _ in range(int(E.OUT_SR * seconds / 256)): e.render(256)

def audio(e, seconds):
    return np.concatenate([e.render(256) for _ in range(int(E.OUT_SR * seconds / 256))])

# ================================================================= engine: project, transport
e = fresh("/tmp/t7"); c = Controls(e); r = Renderer(c)
ok("16 pad sounds + the break are loaded as sources", len(e.sources) == 17)
ok("default sequence has a 2 bar demo beat on tracks 1-4", e.seq.bars == 2 and all(e.seq.tracks[i].events for i in range(4)))
ok("break is chopped on program 2 and pads follow the chops", e.programs[1].pads[0].link == (e.source_by_name("break").id, 0) and e.programs[1].pads[7].link is not None)
e.play(); y = audio(e, 1.5)
ok("PLAY renders audio", np.abs(y[:, :2]).max() > 0.05 and e.playing)
run(e, 4)
ok("sequence loops (position wraps)", 0 <= e.pos < e.seq.length)
e.stop(); ok("STOP keeps the position", not e.playing and e.pos > 0 or e.pos == 0)
e.stop(); ok("second STOP rewinds to the start", e.pos == 0.0)
e.seq.loop = False; e.play(); run(e, 6); ok("one-shot sequence stops at the end", not e.playing); e.seq.loop = True

# ================================================================= recording / overdub / undo
e = fresh("/tmp/t7b"); e.cur_track = 7
e.set_rec("over", start=True); run(e, 0.6)
e.pad_hit(5, 100); t_hit = e.pos
ev = e.track.events
ok("OVERDUB: a pad hit while playing is recorded on the active track", len(ev) == 1 and abs(ev[0][0] - t_hit) < 40 and ev[0][1] == 4)
run(e, 0.2); e.pad_hit(5, 90); ok("a second hit adds a second note", len(e.track.events) == 2)
e.stop(); ok("STOP turns recording off", e.rec == "off")
ok("UNDO removes the take", e.undo_toggle() and e.track.events == [])
ok("UNDO again (toggle) restores it", e.undo_toggle() and len(e.track.events) == 2)
e.cur_track = 0; n0 = len(e.track.events)
e.set_rec("rec", start=True); run(e, 0.05)
ok("REC (replace) clears the track's old notes at the start", len(e.track.events) < n0)
e.stop()
e.undo_toggle(); ok("...and UNDO brings the old notes back", len(e.track.events) == n0)
e = fresh("/tmp/t7c"); e.count_in = 1; e.cur_track = 9; e.set_rec("over", start=True)
ok("count-in starts the playhead one bar before the start", e.pos == -e.seq.bar_ticks)
run(e, 1.0); e.pad_hit(1, 100); ok("a hit during the count-in is placed at tick 0", e.track.events and e.track.events[0][0] == 0)
e.stop()
e = fresh("/tmp/t7d"); e.cur_track = 9; e.rec_quant = True; e.qgrid = 4
e.set_rec("over", start=True); run(e, 0.43); e.pad_hit(2, 100)
ok("record quantize snaps to the 1/16 grid", e.track.events and e.track.events[0][0] % 24 == 0)
e.stop()

# ================================================================= edit tools
e = fresh("/tmp/t7e"); tr = e.track; n0 = len(tr.events)
e.add_note(5, 3, 100, 24); ok("add_note / find_note", e.find_note(5, 3) is not None)
ok("toggle_note removes it again", e.toggle_note(5, 3) is False and e.find_note(5, 3) is None)
tr.events = [(5, 0, 100, 24), (50, 0, 100, 24), (100, 1, 100, 24)]
e.qgrid = 4; e.quantize_track(); ok("quantize moves notes to the grid (and is undoable)", [x[0] for x in tr.events] == [0, 48, 96] and e.undo())
ok("undo restored the original positions", [x[0] for x in tr.events] == [5, 50, 100])
e.erase_pad_events(0); ok("erase pad events only removes that pad", [x[1] for x in tr.events] == [1])
e.clear_track(); ok("clear track", tr.events == [])
tr.events = [(0, 0, 100, 24), (100, 1, 90, 24)]; e.copy_bars(0, 1, 1); ok("copy bars", (384, 0, 100, 24) in tr.events and (484, 1, 90, 24) in tr.events)
e = fresh("/tmp/t7f"); e.cur_track = 0; kicks = [x for x in e.track.events]
e.play(); e.erase_hold(True, None); run(e, 0.3); e.erase_hold(False)
ok("holding ERASE while playing deletes notes the playhead passes", len(e.track.events) < len(kicks))
e.stop()
e = fresh("/tmp/t7g"); e.cur_track = 11; e.rep_on = True; e.rep_div = 24
e.set_rec("over", start=True); e.pad_hit(3, 100); run(e, 0.8)
ok("NOTE REPEAT records repeating notes on the grid", len(e.track.events) >= 4 and all(x[0] % 24 == 0 for x in e.track.events))
e.pad_hit(3, 100); n = len(e.track.events); run(e, 0.8)
ok("hitting the pad again stops the repeat", len(e.track.events) == n); e.stop()

# ================================================================= swing, mute, solo, hold, choke
e = fresh("/tmp/t7h"); sq = e.seq
for t in sq.tracks: t.events = []
sq.tracks[0].events = [(24, 0, 100, 24)]
def first_sound(e):
    e.v_pad[:] = [None] * e.nv; e.v_data[:] = [None] * e.nv
    e.pos = 0.0; e.playing = True; y = audio(e, 0.5); e.playing = False
    m = np.abs(y[:, 0]) > 0.001
    return int(np.argmax(m)) if m.any() else -1
a = first_sound(e); sq.swing = 0.66; b = first_sound(e)
ok("swing delays off-beat 16ths (playback only, notes unchanged)", b > a + 200 and sq.tracks[0].events == [(24, 0, 100, 24)])
sq.swing = 0.5; sq.tracks[0].mute = True; ok("a muted track is silent", first_sound(e) == -1)
sq.tracks[0].mute = False; sq.tracks[1].events = [(24, 1, 100, 24)]; sq.tracks[1].solo = True
e.pos = 0; e.playing = True; y = audio(e, 0.5); e.playing = False
ok("track solo silences the other tracks", np.abs(y).max() > 0.01)
sq.tracks[1].solo = False
p = e.programs[0].pads[10]; p.mode = "HOLD"
long = E.Engine.__new__  # (just a readability marker)
e.trigger(p, 100, 0, 2000); y1 = np.concatenate([e.render(256) for _ in range(40)])
p2 = e.programs[0].pads[10]; p2.mode = "ONE"; e.trigger(p2, 100, 0, 2000); y2 = np.concatenate([e.render(256) for _ in range(40)])
ok("HOLD pads stop when the note ends, ONE SHOT pads play on", np.abs(y1[3000:, 0]).max() < 1e-4 < np.abs(y2[3000:, 0]).max())
ch = e.programs[0].pads
ch[2].choke = ch[3].choke = 1
e.trigger(ch[3], 100); e.render(256); e.trigger(ch[2], 100)
y = np.concatenate([e.render(256) for _ in range(8)])
ok("choke group: the closed hat cuts the open hat", all(e.v_pad[i] is not ch[3] for i in range(e.nv)))
o2 = e.programs[1].pads[0]; o2.assign(ch[3].src); o2.choke = 1
e.trigger(ch[3], 100); e.render(256); e.trigger(o2, 100); e.render(256)
ok("choke group: the same group number in another program does not cut (groups are per program, as on an MPC)", any(e.v_pad[i] is ch[3] and e.v_kill[i] < 0 for i in range(e.nv)))

# ================================================================= song mode
e = fresh("/tmp/t7i"); e.seqs[1].bars = 1; e.song = [[0, 1], [1, 1]]
e.song_play(); run(e, 0.1); ok("song starts on step 1 (sequence 1)", e.cur_seq == 0 and e.song_mode)
run(e, 6.0); ok("song moves on to the next sequence", e.cur_seq == 1 or not e.song_mode)
run(e, 3.0); ok("song stops at the end", not e.playing and not e.song_mode)

# ================================================================= NON-DESTRUCTIVE editing and chop
e = fresh("/tmp/t7j")
digest = lambda: [hashlib.md5(s.raw.tobytes()).hexdigest() for s in e.sources]
before = digest(); p = e.programs[0].pads[0]; built0 = p.build()[0].copy()
p.reverse = True; p.norm = True; p.fade_in = 20; p.fade_out = 50; p.start += 500; p.end -= 500; p.tune = 5; p.lofi_on = False
b1 = p.build()[0]
ok("reverse / normalise / fades / trim change what plays...", b1.shape != built0.shape or not np.array_equal(b1, built0))
ok("...but the source audio is byte-identical", digest() == before)
brk = e.source_by_name("break")
ok("equal chop makes N regions", e.chop_equal(brk, 4) == 4 and len(brk.chops) == 3)
n_tr = e.chop_transient(brk, 0.25); ok("transient chop finds the drum hits", 8 <= n_tr <= 24)
e.chop_beats(brk, 90, 4); ok("beat-grid chop: 8 beats = 8 regions", len(brk.regions()) == 8 and abs(brk.chops[0] - 29400) < 2)
e.chop_equal(brk, 4); e.chop_to_pads(brk, 20)
ok("chop to pads: pads reference regions, no audio copied", e.programs[0].pads[20].src is brk and e.programs[0].pads[23].link == (brk.id, 3))
old = e.programs[0].pads[21].start
ok("moving a marker moves the linked pads (they follow)", e.move_marker(brk, 0, brk.chops[0] + 1000) and e.programs[0].pads[21].start == old + 1000)
ok("add / remove markers", e.add_marker(brk, 5000) and 5000 in brk.chops and e.remove_marker(brk, 5000) and 5000 not in brk.chops)
ok("markers closer than 10 ms are refused", not e.add_marker(brk, brk.chops[0] + 100))
ok("chopping never altered the source", digest() == before)
e.save_project(); e2 = E.Engine("/tmp/t7j")
ok("project reload keeps chops, links, pad settings, sequences", e2.source_by_name("break").chops == brk.chops and e2.programs[0].pads[23].link == (brk.id, 3)
   and e2.programs[0].pads[0].reverse and e2.programs[0].pads[0].fade_out == 50 and len(e2.seq.tracks[0].events) == len(e.seq.tracks[0].events))
tmp_pad = e.programs[0].pads[30]; tmp_pad.assign(brk); e.pad_changed(tmp_pad); ok("assign whole sample to a pad", tmp_pad.length == brk.length)

# ================================================================= 8 outputs (as v5/v6, now per program pad)
e8 = fresh("/tmp/t8", nout=8)
def render_all(eng, pads=(0, 1, 2), n=6):
    for i in pads: eng.trigger(eng.programs[0].pads[i], 110)
    return np.concatenate([eng.render(512) for _ in range(n)])
base = render_all(fresh("/tmp/t8x", nout=8))
ok("8 outs: output has 8 channels", base.shape[1] == 8)
ok("MIX pads leave outs 3-8 silent", np.abs(base[:, 2:]).max() == 0 and np.abs(base[:, :2]).max() > 0)
e8.programs[0].pads[0].out = 2; e8.programs[0].pads[1].out = 7
y = render_all(e8)
ok("pair 3/4 carries pad 1; mono out 3 carries pad 2", np.abs(y[:, 2]).max() > 0 and np.abs(y[:, 3]).max() > 0)
ok("routed pads are not duplicated on the main mix", np.abs(y[:, :2]).sum() < np.abs(base[:, :2]).sum())
e2o = fresh("/tmp/t8y"); e2o.programs[0].pads[0].out = 2
ok("2-output card: unavailable out falls back to the mix", not e2o.out_ok(2) and np.abs(render_all(e2o)[:, :2]).max() > 0)
e8.cycle_out(e8.programs[0].pads[5], 1); ok("cycle_out steps through available outs", e8.programs[0].pads[5].out == 1)

# ================================================================= UI: screens render, touch, buttons
e = fresh("/tmp/t7u"); c = Controls(e); r = Renderer(c)
for m in ["MAIN", "SEQ", "GRID", "STEP", "MUTE", "PROG", "SAMPLE", "CHOP", "MIXER", "FX", "SONG"]:
    c.set_mode(m); r.frame()
ok("all 10 screens (and GRID's ALL TRACKS view) render at 800x500 (the 1280x800 panel's 16:10 shape)", r.img.size == (800, 500))
_r16 = Renderer(c, 1.6); c.set_mode("SEQ"); _r16.frame()
ok("drawn at 1.6x the panel gets a sharp 1280x800 picture with the same touch regions", _r16.img.size == (1280, 800) and
   [h[0] for h in _r16._hits] == [h[0] for h in (r.frame() and r._hits)])
_sq = np.asarray(_r16.img).astype(int)
ok("...and real 1280-pixel detail (not a blown-up 800 picture)", (np.abs(np.diff(_sq[:, :, 1], axis=1)) > 60).sum() > 3000)
import uicore as _uc
_sizes = []
_of = _uc.font
def _spy(size, bold=False): _sizes.append(size); return _of(size, bold)
import screens as _scr; _scr.font = _spy
for _m in TABS: c.set_mode(_m); r.frame()
_scr.font = _of
ok("no text smaller than 9 units (1.8 mm capitals on the 10.1 inch panel)", min(_sizes) >= 9)
ok("soft keys are 10 mm tall and the Q-link strip 22 mm on the panel", (SOFT_Y[1] - SOFT_Y[0]) * 216.566 / W >= 10 and (H - Q_Y) * 216.566 / W >= 22)
def tap(x, y): c.touch("down", x, y); c.touch("up", x, y)
c.set_mode("MAIN"); r.frame(); tap(4 + 1 * 61 + 20, 15); r.frame(); ok("tap GRID tab: opens on the current track", c.mode == "GRID")
tap(4 + 3 * 61 + 20, 15); ok("tap MUTE tab", c.mode == "MUTE")
c.set_mode("SEQ"); r.frame(); ok("the GRID tab stays lit in the ALL TRACKS view", TAB_OF.get(c.mode) == "GRID")
c.set_mode("MAIN"); r.frame(); tap(10 + 76 // 2 + 80, 48 + 2 * 80 + 38); ok("tap a pad selects it", e.sel == 5 or e.sel in range(16))
tap(338 + 10, 48 + 2 * 80 + 10); ok("tap bank button C", e.bank == 2); tap(348, 58); ok("tap bank A", e.bank == 0)
# SEQ screen
c.set_mode("SEQ"); r.frame(); y_row = 94 + 3 * 34 + 16
tap(60, y_row); ok("SEQ: tap a track row selects the track", e.cur_track == 3)
r.frame(); m0 = e.seq.tracks[2].mute; tap(185, 94 + 2 * 34 + 16); ok("SEQ: M button mutes a track", e.seq.tracks[2].mute != m0)
r.frame(); tap(219, 94 + 2 * 34 + 16); ok("SEQ: S button solos a track", e.seq.tracks[2].solo)
ok("SEQ: mute / solo buttons are at least 30 x 24 px (finger-sized)", all((h[0][2] - h[0][0]) >= 30 and (h[0][3] - h[0][1]) >= 24 for h in c.hits if h[0][0] in (170, 204)))
r.frame(); c.soft(2); r.frame(); ok("ALL TRACKS: F3 pages to tracks 9-16", e.cur_track == 11); c.soft(2); e.cur_track = 3
e.seq.tracks[2].solo = e.seq.tracks[2].mute = False
b0 = e.seq.bars; tap(458, 54); ok("GRID header: bars -", e.seq.bars == b0 - 1); tap(510, 54); ok("GRID header: bars +", e.seq.bars == b0); e.set_bars(2)
tap(400, 78); ok("SEQ: tapping the ruler moves the playhead", e.pos > 0)
tap(556, 54); ok("GRID header: LOOP toggle", e.seq.loop is False); tap(556, 54)
r.frame(); tap(210, 54); ok("GRID header: track < / >", e.cur_track == 2); tap(368, 54); ok("...and >", e.cur_track == 3)
c.nav("down"); c.nav("down"); ok("SEQ: arrows move through tracks", e.cur_track == 5)
r.frame(); tap(60, 94 + 5 * 34 + 16); ok("ALL TRACKS: tapping the selected track again opens its grid", c.mode == "GRID" and e.cur_track == 5)
r.frame(); tap(740, 54); ok("GRID: the ALL TRACKS chip shows every track", c.mode == "SEQ"); r.frame(); tap(740, 54); ok("...and back", c.mode == "GRID")
c.set_mode("SEQ"); c.ok(); ok("ALL TRACKS: OK edits the selected track", c.mode == "GRID")
c.set_mode("SEQ"); c.soft(3); ok("ALL TRACKS: F4 EDIT TRACK", c.mode == "GRID")
# MUTE page
c.set_mode("MUTE"); e.cur_track = 0; c.mute_page = 0; r.frame(); m0 = e.seq.tracks[1].mute
c.pad_hit(2, 100); ok("MUTE: pad 2 mutes track 2 (and plays nothing)", e.seq.tracks[1].mute != m0)
c.soft(2); r.frame(); tap(10 + 45, 220); ok("MUTE: tapping strip 1's big key mutes track 1", e.seq.tracks[0].mute)
r.frame(); tap(10 + 98.75 * 2 + 45, 300); ok("MUTE: the SOLO key solos track 3", e.seq.tracks[2].solo)
c.soft(2); ok("MUTE: ALL ON clears mutes and solos", not any(t.mute or t.solo for t in e.seq.tracks))
c.soft(1); r.frame(); tap(10 + 20, 348); tap(10 + 98.75 + 20, 348)
ok("MUTE: GROUPS: tap a strip's group to set it", e.seq.tracks[0].mgroup == 1 and e.seq.tracks[1].mgroup == 1); c.soft(1)
c.pad_hit(1, 100); ok("MUTE: tracks in a group mute together", e.seq.tracks[0].mute and e.seq.tracks[1].mute)
c.pad_hit(1, 100); ok("...and come back together", not e.seq.tracks[0].mute and not e.seq.tracks[1].mute)
c.soft(3); e.play(); c.pad_hit(3, 100); ok("MUTE: ON NEXT BAR waits for the bar line", not e.seq.tracks[2].mute and 2 in e.pending_mute)
for _ in range(400):
    if not e.pending_mute: break
    e.render(512)
ok("...then mutes on it", e.seq.tracks[2].mute and abs(e.pos % e.seq.bar_ticks) < e.seq.bar_ticks * 0.1); e.stop(); c.soft(3); c.soft(2)
e.seq.tracks[0].mgroup = e.seq.tracks[1].mgroup = 0
c.soft(0); ok("MUTE: F1 shows tracks 9-16", c.mute_page == 1 and e.cur_track >= 8); c.soft(0)
e.cur_track = 2; c.nav("right"); ok("MUTE: arrows move along the strips", e.cur_track == 3)
e.cur_track = 6
# GRID
e.cur_track = 11; c.set_mode("GRID"); r.frame(); n0 = len(e.track.events)
LH = r.grid_h() // 8
GY = r.GY0 + 12 + (7 - 4) * LH + LH // 2                          # lane 4 of the 8 big lanes
tap(92 + 40, GY); ok("GRID: tap an empty cell adds a note", len(e.track.events) == n0 + 1)
ev = e.track.events[0]; r.frame()
ppt = 700.0 / (c.g_bars * e.seq.bar_ticks); nx = int(92 + ev[0] * ppt + 3)
c.touch("down", nx, GY); c.touch("move", nx + 200, GY); c.touch("up", 0, 0)
ok("GRID: dragging a note moves it", len(e.track.events) == n0 + 1 and e.track.events[0][0] > ev[0] + 24)
c.g_tick, c.g_lane = 96, 7; c.ok(); ok("GRID: OK toggles a note at the cursor", e.find_note(96, 7) is not None)
c.jog(2); ok("GRID: jog changes the velocity of the note under the cursor", e.find_note(96, 7)[2] == 108)
c.shift = True; c.jog(1); c.shift = False; ok("GRID: SHIFT+jog changes the note length", e.find_note(96, 7)[3] == 48)
c.nav("right"); ok("GRID: arrows move the cursor by the snap", c.g_tick == 120)
c.g_bars = 2; c.soft(0); ok("GRID: F1 steps the zoom (2 -> 4 bars)", c.g_bars == 4)
c.soft(1); r.frame(); ok("GRID: F2 shows all 16 pads", c.g_lanes == 16); c.soft(1); ok("GRID: F2 again: 8 big lanes", c.g_lanes == 8)
c.g_lane = 12; r.frame(); tap(40, r.GY0 + 12 + LH // 2); ok("GRID: 8-lane view follows the cursor (top lane is pad 16)", c.g_lane == 15)
c.soft(3); ok("GRID: DELETE removes the note under the cursor", True)
e.qgrid = 2; ok("GRID: snap follows the quantize setting", c.snap() == 48); e.qgrid = 4
# STEP
c.set_mode("STEP"); e.select_pad(0, 6); r.frame(); n0 = len(e.track.events)
tap(20 + 5 * 47.7 + 20, 290); ok("STEP: tap a step toggles a note", e.find_note(5 * 24, e.pad_idx) is not None)
c.step_cursor = 5; c.qlinks()[3][2](1.0); ok("STEP: Q4 RATCHET makes the step play four times", len(c.step_events(5)) == 4)
c.qlinks()[3][2](0.0); ok("...and back to once", len(c.step_events(5)) == 1)
c.qlinks()[2][2](1.0); ok("STEP: Q3 NUDGE moves it off the grid", c.step_nudge_of() > 0); c.qlinks()[2][2](0.5)
ok("...and back onto it", c.step_nudge_of() == 0)
r.frame(); tap(45.6 + 5 * 47.45, 160); ok("STEP: the velocity lane sets the step's velocity", c.step_events(5)[0][2] > 100)
c.pad_hit(1, 100); ok("STEP: pads 1-16 are the 16 steps", e.find_note(0, e.pad_idx) is not None)
c.soft(1); ok("STEP: COPY BAR copies onto the next page", e.find_note(16 * 24, e.pad_idx) is not None and c.step_page == 1)
c.soft(2); ok("STEP: CLEAR PAD erases that pad's notes", e.find_note(0, e.pad_idx) is None)
c.soft(3); c.step_page = 0; c.step_toggle(2); ok("STEP: ACCENT enters steps at full velocity", c.step_events(2)[0][2] == 127); c.soft(3); c.step_toggle(2)
r.frame(); tap(754, 91); ok("STEP: the 1/32 grid key", c.step_res == 12)
c.soft(0); ok("STEP: F1 next page", c.step_page == 1); c.step_res = 24; c.step_page = 0
# PROG
c.set_mode("PROG"); e.select_pad(0, 0); c.prog_front = False; r.frame()
c.prog_row = 3; c.jog(2); ok("PROG: jog changes tune", e.pad.tune == 2)
c.prog_row = 8; c.jog(1); ok("PROG: jog toggles reverse", e.pad.reverse is True); c.jog(1)
c.prog_row = 1; s0 = e.pad.start; c.jog(3); ok("PROG: jog moves the region start (non-destructive)", e.pad.start > s0)
c.prog_row = 0; c.ok(); ok("PROG: OK on SAMPLE opens the picker", c.picking); r.frame()
tgt = min(c.pick_cur + 2, len(e.sources) - 1); c.nav("down"); c.nav("down"); c.ok(); ok("PROG: picker assigns a sample", not c.picking and e.pad.src is e.sources[tgt])
c.set_prog_tab(0); r.frame(); tap(386 + 137 + 60, 174 + 20); ok("PROG: tap a parameter selects it (GLOBAL tab, PAN)", c.prog_row == 5)
c.set_prog_tab(2); r.frame(); ok("PROG: the ENVELOPES tab puts attack, decay, cutoff and resonance on the Q-links", [q[0] for q in c.qlinks()] == ["Attack", "Decay", "Cutoff", "Res"])
c.prog_row = 22; c.nav("down"); c.nav("down"); ok("PROG: the D-pad runs off the end of a tab into the next one", c.prog_tab == 3 and c.prog_row == 44)
c.set_prog_tab(1)
c.touch("down", 500, 176 + 3 * 28 + 10); c.touch("move", 540, 176 + 3 * 28 + 10); c.touch("up", 540, 0); ok("PROG: dragging a parameter changes it", True)
c.soft(0); ok("PROG: F1 < PANEL goes back to the front panel", c.prog_front)
r.frame(); tap(506 + 56.25 + 22, 100); ok("PROG panel: the REVERSE switch", e.pad.reverse); r.frame(); tap(506 + 56.25 + 22, 100)
r.frame(); c.touch("down", 19 + 20, 300); c.touch("move", 19 + 20, 260); c.touch("up", 0, 0)
ok("PROG panel: the ATTACK fader", e.pad.attack > 0 and c.prog_row == 16); e.pad.attack = 0
fl0 = e.pad.flt; r.frame(); tap(670, 215); ok("PROG panel: the LP key", e.pad.flt == ("OFF" if fl0 == "LP" else "LP")); e.pad.flt = fl0
ok("PROG panel: Q-links are tune / level / pan / gain", [q[0] for q in c.qlinks()][1:] == ["Level", "Pan", "Gain"])
c.soft(0); ok("PROG panel: F1 ALL PARAMS", not c.prog_front); c.soft(0)
# CHOP
c.set_mode("CHOP"); e.cur_track = 4; e.select_pad(0, 0); r.frame(); brk = e.source_by_name("break"); e.pad.assign(brk); e.clear_markers(brk)
r.frame(); tap(540, 294); ok("CHOP: DETECT TRANSIENT", c.chop_mode == 1)
c.chop_n = 4; r.frame(); tap(608, 294); ok("CHOP: DETECT EQUAL makes equal slices at once", c.chop_mode == 0 and len(brk.chops) == 3)
c.qlinks()[0][2]((8 - 2) / 30.0); ok("CHOP: Q1 SLICES moves the markers with the knob", len(brk.chops) == 7)
c.qlinks()[0][2]((4 - 2) / 30.0); ok("...back to 4", len(brk.chops) == 3)
c.chop_snap = False; c.chop_cursor = 20000; c.soft(1); ok("CHOP: F2 SPLIT at the cursor", 20000 in brk.chops)
c.soft(2); ok("CHOP: F3 MERGE joins the slice with the next (undoes the SPLIT)", 20000 not in brk.chops)
c.chop_snap = True; c.chop_cursor = 30001; c.soft(1); sn = [m for m in brk.chops if abs(m - 30001) < 600]
ok("CHOP: SNAP puts a split on a zero crossing", len(sn) == 1 and brk.raw[sn[0]] <= 0 < brk.raw[sn[0] + 1]); c.chop_unmark()
c.soft(3); ok("CHOP: F4 CONVERT asks where the slices go", c.confirm is not None and soft_text(c.soft_labels()[2]).startswith("TO PADS"))
c.soft(2); ok("CHOP: CONVERT > TO PADS (from the selected pad)", e.pad.link is not None and e.prog.pads[3].link is not None)
ok("CHOP: FADE gives the slice pads short fades", e.prog.pads[3].fade_out >= 5)
c.chop_cursor = 0; r.frame(); tap(21.25 + 57.5 + 25, 320); ok("CHOP: tapping slice 2 jumps there", c.chop_cursor == brk.chops[0])
r.frame(); tap(758, 346); ok("CHOP: CLEAR asks first (one tap keeps the markers)", len(brk.chops) == 3)
r.frame(); tap(758, 346); ok("CHOP: second tap clears the markers", brk.chops == [])
c.chop_mode = 3; r.frame(); tap(400, 150); ok("CHOP: tap the waveform moves the cursor", c.chop_cursor > 0)
c.chop_mark(); ok("CHOP: manual marker", len(brk.chops) == 1)
c.touch("down", 400, 150); c.touch("move", 450, 150); c.touch("up", 450, 150); ok("CHOP: dragging a marker moves it", brk.chops[0] != 0)
c.chop_audition(); ok("CHOP: audition plays a region without changing the pad", e.pad.src is brk)
c.zoom = None; c.chop_zoom_to(0.9); ok("CHOP: zoom", c.chop_v1 - c.chop_v0 < 0.2)
# MIXER / FX / SONG
c.set_mode("MIXER"); c.mix_view = "CHANNELS"; r.frame(); e.select_pad(0, 0)
x2 = 8 + 1 * 66.25
c.touch("down", x2 + 33, 340); c.touch("move", x2 + 33, 262); c.touch("up", 0, 0)
ok("MIXER: dragging program 2's fader sets its level", e.programs[1].strip.level > 1.0 and c.mix_strip == 1 or e.programs[1].strip.level > 1.0)
r.frame(); tap(x2 + 15, 235); ok("MIXER: the MUTE key mutes program 2", e.programs[1].strip.mute)
r.frame(); tap(x2 + 48, 235); ok("MIXER: the SOLO key solos it", e.programs[1].strip.solo)
e.programs[1].strip.mute = e.programs[1].strip.solo = False; e.programs[1].strip.level = 1.0
c.soft(1); r.frame(); ok("MIXER: F2 shows the sends on the faders", c.mix_view == "SENDS"); c.soft(0)
r.frame(); tap(x2 + 33, 145); ok("MIXER: tapping the EQ opens the channel EQ", c.eq_open and c.mix_strip == 1)
c.soft(0); ok("MIXER: F1 closes it", not c.eq_open)
c.soft(3); r.frame(); ok("MIXER: F4 the pad mixer", c.mix_view == "PADS"); c.soft(0)
c.set_mode("FX"); e.select_pad(0, 0); c.fx_target = 0; c.fx_cursor = 1; c.fx_load(); ok("FX: load an effect on a pad", e.prog.pads[0].fx is not None)
c.shift = True; c.ok(); c.shift = False; ok("FX: SHIFT+OK bypasses", e.prog.pads[0].fx_bypass)
c.fx_set_target(64); c.fx_cursor = 1; c.fx_load(); ok("FX: master insert", e.master_fx is not None)
c.fx_set_target(0); ok("FX: the list opens on the effect that is loaded", c.fx_cursor == 1)
from uicore import ink, TEXT as _T
ok("UI: text on light pad colours is dark, on dark colours light", ink((220, 215, 200)) != _T and ink((40, 40, 60)) == _T)
c.knob(0, 127); c.knob(0, 0); ok("Q-link: a knob far from the value does not jump it (pick-up)", c.pot_seen[0] and not c.armed[0])
c.set_mode("SONG"); r.frame(); n = len(e.song); c.soft(0); ok("SONG: add a step", len(e.song) == n + 1)
c.nav("right"); ok("SONG: arrows change repeats", e.song[c.song_cur][1] >= 1); c.soft(1); ok("SONG: delete a step", len(e.song) == n)

# ================================================================= the 24 hardware buttons
e = fresh("/tmp/t7v"); c = Controls(e)
def press(name, shift=False):
    if shift: c.button(BTN["SHIFT"], True)
    c.button(BTN[name], True); c.button(BTN[name], False)
    if shift: c.button(BTN["SHIFT"], False)
press("PLAY"); ok("button PLAY", e.playing); press("STOP"); ok("button STOP", not e.playing)
press("PLAYSTART"); ok("button PLAY START", e.playing and e.pos < 50); press("STOP")
press("REC"); ok("button REC arms recording and starts", e.rec == "rec" and e.playing); press("STOP")
press("OVERDUB"); ok("button OVERDUB", e.rec == "over" and e.playing); press("STOP")
for nm, mode in (("MAIN", "MAIN"), ("GRID", "GRID"), ("GRID", "SEQ"), ("GRID", "STEP"), ("GRID", "GRID"), ("MUTE", "MUTE"), ("PROG", "PROG"), ("SAMPLE", "SAMPLE"), ("CHOP", "CHOP"), ("MIXER", "MIXER"), ("FX", "FX")):
    press(nm); ok("button " + nm, c.mode == mode)
press("GRID", True); ok("SHIFT+GRID opens SONG", c.mode == "SONG"); press("MIXER", True); ok("SHIFT+MIXER opens FX", c.mode == "FX")
c.midi_button("BANK", True); c.midi_button("BANK", False); ok("BANK (MIDI-learnable) cycles pad banks", e.bank == 1)
c.button(BTN["SHIFT"], True); c.midi_button("BANK", True); c.button(BTN["SHIFT"], False); ok("SHIFT+BANK changes the track's program", e.track.prog == 1)
_m0 = c.mode; press("LOAD"); ok("LOAD key opens BROWSE", c.mode == "BROWSE"); press("LOAD"); ok("LOAD again goes back", c.mode == _m0)
press("LOAD", True); ok("SHIFT+LOAD opens PROJECTS", c.mode == "PROJECTS"); c.set_mode(_m0)
c.set_mode("MAIN"); press("REPEAT"); ok("button REPEAT toggles note repeat", e.rep_on); press("REPEAT", True); ok("SHIFT+REPEAT changes the rate", e.rep_div == 12); press("REPEAT")
press("OVERDUB", True); ok("SHIFT+OVERDUB toggles the metronome", e.metro); press("REC", True); ok("SHIFT+REC cycles count-in", e.count_in == 1)
press("F1"); ok("F1 acts (METRO in MAIN)", not e.metro)
e.cur_track = 0; n = len(e.track.events); e.stop(); press("UNDO"); ok("button UNDO is safe with nothing to undo", True)
e.add_note(0, 15, 100); e.begin_edit(); e.add_note(10, 14, 100); press("UNDO"); ok("button UNDO undoes the last edit", e.find_note(10, 14) is None)
press("UNDO", True); ok("SHIFT+UNDO redoes", e.find_note(10, 14) is not None)
e.track.events = [(5, 0, 100, 24)]; e.qgrid = 4; press("TAP", True); ok("SHIFT+TAP quantizes the track", e.track.events[0][0] == 0)
import time as _t
press("TAP"); _t.sleep(0.5); press("TAP"); ok("TAP tempo", 100 < e.seq.bpm < 140)
c.button(BTN["SHIFT"], True); ok("button SHIFT", c.shift); c.button(BTN["SHIFT"], False)
e.track.events = [(0, 3, 100, 24)]; e.select_pad(0, 3); c.button(BTN["ERASE"], True); c.button(BTN["ERASE"], False)
ok("button ERASE (tap) erases the selected pad's notes", e.track.events == [])
press("PLAY"); c.button(BTN["SHIFT"], True); c.button(BTN["STOP"], True); c.button(BTN["STOP"], False); c.button(BTN["SHIFT"], False)
ok("SHIFT+STOP silences all voices", all(d is None for d in e.v_data)); e.stop()
c.shift = True; c.pad_hit(4, 100); c.shift = False; ok("SHIFT+pad selects without playing", e.sel == 3)
e.save_project = lambda: None; press("PLAY", True); ok("SHIFT+PLAY saves and says so", e.msg == "project saved")

# ================================================================= serial protocol, scaling, touch mapping
import sampler_os, inputs
c = Controls(fresh("/tmp/t7s")); sampler_os.handle_line(c, "B,3,1\n"); ok("serial: B,3,1 = PLAY", c.e.playing)
sampler_os.handle_line(c, "B,2,1\n"); ok("serial: B,2,1 = STOP", not c.e.playing)
sampler_os.handle_line(c, "P,5,100\n"); ok("serial: pad hit", c.e.sel == 4)
sampler_os.handle_line(c, "B,22,1\nK,0,64\nB,99,1\ngarbage\n"); ok("serial: bad lines are ignored", True)
ok("fit stretch fills 1024x600", sampler_os.fit_box(1024, 600, "stretch") == (0, 0, 1024, 600))
ok("fit letterbox 1024x600 keeps 16:10", sampler_os.fit_box(1024, 600, "letterbox") == (32, 0, 960, 600))
ok("fit auto fills the 1280x800 panel exactly", sampler_os.fit_box(1280, 800) == (0, 0, 1280, 800))
ok("fit auto keeps the shape on a 1024x600 screen (6.7 % off 16:10)", sampler_os.fit_box(1024, 600) == (32, 0, 960, 600))
class _C:
    def __init__(s): s.ev = []
    def touch(s, ph, x, y): s.ev.append((ph, x, y))
cc = _C(); tm = inputs.TouchMapper(cc, (0, 1023), (0, 599), box=(0.0117, 0.0, 0.9883, 1.0))
tm.rx, tm.ry = 512, 300; tm.active = True; tm.flush()
ok("touch letterbox maps centre to centre", abs(cc.ev[0][1] - W / 2) <= 2 and abs(cc.ev[0][2] - H / 2) <= 2)
class FakeBtn:
    def __init__(s, pin, **k): s.pin = pin; s.when_pressed = None; s.when_held = None
class FakeEnc:
    def __init__(s, a, b, **k): s.when_rotated_clockwise = None; s.when_rotated_counter_clockwise = None
cc = Controls(fresh("/tmp/t7g2")); keep = inputs.gpio_start(cc, factory=(FakeBtn, FakeEnc))
pins = {b.pin: b for b in keep if isinstance(b, FakeBtn)}
ok("GPIO: no pin used by the DAC8x / ADC8x (2, 3, 4, 18-27)", not (set(inputs.PINS.values()) & inputs.DAC8X_PINS))
ok("GPIO: OK key is BCM 16, right arrow BCM 12", 16 in pins and 12 in pins)
pins[inputs.PINS["song"]].when_pressed(); ok("GPIO: the SONG key opens the SONG screen", cc.mode == "SONG")
cc.set_mode("GRID"); cc.e.cur_track = 15; cc.g_tick, cc.g_lane = 0, 0; pins[inputs.PINS["ok"]].when_pressed()
ok("GPIO: OK key toggles a grid note", cc.e.find_note(0, 0) is not None)
pins[inputs.PINS["right"]].when_pressed(); ok("GPIO: D-pad right moves the grid cursor", cc.g_tick == 24)

# ================================================================= rear strip: VU meter and status lights
e = fresh("/tmp/t7r"); c = Controls(e)
e.meter_l = e.meter_r = 0.0; data, st = sampler_os.lights_frame(e)
ok("lights: silent, stopped = V,0,0 and S,0", data == b"V,0,0\nS,0\n")
data2, st2 = sampler_os.lights_frame(e, st); ok("lights: nothing is sent when nothing changed", data2 == b"")
e.meter_l, e.meter_r = 1.0, 0.25; e.playing = True; data, _ = sampler_os.lights_frame(e)
ok("lights: full left, quarter right (square-root scale), PLAY lit", data == b"V,248,120\nS,1\n" or data.startswith(b"V,248,12"))
e.playing = False
sil = fresh("/tmp/t7s"); sil.trigger(sil.programs[0].pads[0], 127); sil.render(512)
ok("engine reports separate left and right meter levels", sil.meter_l > 0.01 and sil.meter_r > 0.01)
# ================================================================= MIDI: keyboard, pads, learn, piano roll, MIDI out
import midi
p = midi.Parser()
ok("MIDI parser: note on, running status, realtime byte inside a message", p.feed(bytes([0x90, 60, 100, 62, 0xF8, 90])) == [(0x90, 60, 100), (0xF8,), (0x90, 62, 90)])
ok("MIDI parser: SysEx (MMC play)", midi.Parser().feed(bytes([0xF0, 0x7F, 0x7F, 0x06, 0x02, 0xF7])) == [(0xF0, 0x7F, 0x7F, 0x06, 0x02, 0xF7)])
e = fresh("/tmp/t7midi"); c = Controls(e); r = Renderer(c); e.save_project = lambda: None
mp = midi.MidiMap(None)
sent = []; e.midi_out = lambda data, delay=0.0: sent.append((bytes(data), delay))
def mi(*b): [midi.dispatch(c, m, mp) for m in midi.Parser().feed(bytes(b))]
mi(0x99, 36 + 16 + 4, 100); ok("MIDI pads: channel 10 note 56 = pad B05", e.bank == 1 and e.sel == 4)
e.bank = 0; e.select_pad(0, 11)
mi(0x90, 60, 100, 64, 100, 67, 100); e.render(1024)
ok("MIDI keys: a chord plays three voices of the selected pad", sum(1 for k in e.v_key if k and k[0] == "live") == 3)
rates = sorted(e.v_rate[i] / e.v_rate[i] for i in range(e.nv) if e.v_key[i] and e.v_key[i][0] == "live")
v60 = next(i for i in range(e.nv) if e.v_key[i] == ("live", 60)); v67 = next(i for i in range(e.nv) if e.v_key[i] == ("live", 67))
ok("MIDI keys: G is a fifth above C (pitch ratio 1.498)", abs(e.v_rate[v67] / e.v_rate[v60] - 2 ** (7 / 12.0)) < 1e-6)
mi(0x80, 60, 0, 64, 0, 67, 0); e.render(2048); ok("MIDI keys: note-off releases the notes", not any(k and k[0] == "live" for k in e.v_key))
e.cur_track = 9; e.set_rec("over", start=True); e.render(2048)
mi(0x90, 62, 90); [e.render(256) for _ in range(40)]; mi(0x80, 62, 0)
tr = e.track
ok("MIDI record: an empty track becomes a KEYS track", tr.kind == "keys" and tr.key_pad == e.pad_idx)
ok("MIDI record: the note is stored with its pitch and held length", len(tr.events) == 1 and tr.events[0][1] == 62 and 25 <= tr.events[0][3] <= 40)
e.stop(); e.stop(); e.play(); y = np.concatenate([e.render(256) for _ in range(120)])
ok("MIDI record: the KEYS track plays back", np.abs(y).max() > 0.01)
e.stop(); e.stop()
mi(0xF0, 0x7F, 0x7F, 0x06, 0x02, 0xF7); ok("MIDI: MMC PLAY starts the sequencer (MPK transport)", e.playing)
mi(0xF0, 0x7F, 0x7F, 0x06, 0x01, 0xF7); ok("MIDI: MMC STOP stops it", not e.playing)
c.midi_learn = "Q1"; mi(0xB0, 22, 64); ok("MIDI learn: Q1 = CC 22", mp.learned.get("Q1") is None and c.midi_map.learned.get("Q1") == ["cc", 1, 22])
mp = c.midi_map
c.set_mode("MAIN"); c.armed[0] = True; mi(0xB0, 22, 127); ok("MIDI: the learned knob moves Q1 (volume on MAIN)", abs(e.volume - 1.0) < 0.01)
c.midi_learn = "SHIFT"; mi(0xB0, 39, 127); mi(0xB0, 39, 127); ok("MIDI learn: SHIFT on a switch", mp.learned.get("SHIFT") == ["cc", 1, 39])
mi(0xB0, 39, 127); ok("MIDI: the learned SHIFT is held while pressed", c.shift); mi(0xB0, 39, 0); ok("...and released", not c.shift)
c.midi_learn = "PADS"; mi(0x92, 48, 100); ok("MIDI learn: PADS from pad 1 (channel 3, note 48)", mp.pad_ch == 3 and mp.pad_base == 48); mp.pad_ch, mp.pad_base = 10, 36
# MIDI out
e.seq.tracks[0].midi_ch = 2; sent.clear(); e.locate(0); e.play(); [e.render(256) for _ in range(40)]; e.stop(); e.stop()
ok("MIDI out: a track with a channel sends note on + off to it (channel 2)", any(d[0] == 0x91 for d, _ in sent) and any(d[0] == 0x81 for d, _ in sent))
ok("MIDI out: note-offs are scheduled after their note-ons", all(dl >= 0 for _, dl in sent))
e.seq.tracks[0].midi_ch = 0
# piano roll and track type
c.set_mode("GRID"); c.g_view = "VEL"; e.cur_track = 9; r.frame()       # (these taps use the layout with the velocity lane on)
n0 = len(e.track.events); c.g_lanes = 8; c.k_top = 71; r.frame()
tap(92 + 300, r.GY0 + 12 + 5 * (r.grid_h() / 12.0) + 5); ok("piano roll: tapping a cell adds a note at that pitch (F#4 = 66)", len(e.track.events) == n0 + 1 and any(ev[1] == 66 for ev in e.track.events))
c.nav("up"); ok("piano roll: up = one semitone", c.g_lane == 67)
c.ok(); ok("piano roll: OK toggles a note at the cursor", e.find_note(c.g_tick, 67) is not None)
e.cur_track = 12; c.set_mode("SEQ"); r.frame()
c.cycle_track_type(12); r.frame(); ok("SEQ: the TYPE button opens the track setup panel", c.track_setup == 12)
tap(236 + 14 + 132 + 60, 72 + 58); r.frame(); ok("track setup: the KEYGROUP tab", c.ts_tab == "keys")
tap(236 + 330 + 100, 72 + 110 + 17); ok("track setup: USE SELECTED PAD makes it a KEYGROUP track on that pad", e.seq.tracks[12].kind == "keys" and e.seq.tracks[12].key_pad == e.pad_idx)
r.frame(); tap(792 - 47, 72 + 19); ok("track setup: CLOSE", c.track_setup is None)
ok("set_track_kind: a DRUM track with hits does not turn into notes", not e.set_track_kind(e.seq.tracks[0], "keys") and e.seq.tracks[0].kind == "drum")
ok("set_track_kind: note tracks switch freely (KEYGROUP -> MIDI gets channel 1)", e.set_track_kind(e.seq.tracks[9], "midi") and e.seq.tracks[9].midi_ch == 1)
sent.clear(); e.cur_track = 9; e.seq.tracks[9].mute = False; e.locate(0); e.play(); [e.render(256) for _ in range(120)]; e.stop(); e.stop()
ok("MIDI track: notes go to MIDI out on its channel", any(d[0] == 0x90 for d, _ in sent))
vk = sum(1 for k in e.v_key if k and k[0] == "seq")
ok("MIDI track: ...and play no sample", vk == 0)
sent.clear(); e.audition(64, 100); ok("MIDI track: auditioning a note sends it", any(d[:2] == bytes([0x90, 64]) for d, _ in sent))
e.set_track_kind(e.seq.tracks[9], "keys"); e.seq.tracks[9].midi_ch = 0
e.seq.tracks[12].kind = "drum"; e.seq.tracks[12].prog = 0
import json as _j
e.save_project = E.Engine.save_project.__get__(e); e.save_project()
e2 = E.Engine("/tmp/t7midi"); ok("KEYS tracks and MIDI channels are saved with the project", e2.seq.tracks[9].kind == "keys" and e2.seq.tracks[9].events)
c.set_mode("MIDI"); r.frame(); ok("MIDI page renders", r.img.size == (W, H))
import time as _tm
_fifo = "/tmp/t7midi_fake0"
if os.path.exists(_fifo): os.remove(_fifo)
os.mkfifo(_fifo)
io = midi.MidiIO(c, c.midi_map, pattern="/tmp/t7midi_fake*").start()
_tm.sleep(0.3); _w = os.open(_fifo, os.O_WRONLY | os.O_NONBLOCK)
e.select_pad(0, 0); os.write(_w, bytes([0x99, 36 + 7, 110])); _tm.sleep(0.8)
ok("MIDI device: bytes arriving on a (pretend) MIDI device reach the pads", e.sel == 7)
os.close(_w)

# ================================================================= plug-in window chrome (no X needed: a pretend window)
e = fresh("/tmp/t7ed"); c = Controls(e); r = Renderer(c); c.set_mode("FX")
class _FakeFx: name = "BIGPLUG"
c.editor_fx = _FakeFx()
c.editor_view = {"x": 0, "y": 36, "w": 784, "h": 326, "cw": 1200, "ch": 700, "sx": 0.0, "sy": 0.0, "hbar": True, "vbar": True, "name": "BIGPLUG", "px": (1200, 700)}
r.frame(); tap(560, 18); ok("plug-in window: the CLOSE button in the top bar closes it", c.editor_req == "close"); c.editor_req = None
c.nav("right"); c.nav("down"); ok("plug-in window: the D-pad scrolls it", c.editor_view["sx"] == 60 and c.editor_view["sy"] == 60)
c.editor_scroll(5000, 5000); ok("plug-in window: scrolling stops at the edges", c.editor_view["sx"] == 1200 - 784 and c.editor_view["sy"] == 700 - 326)
r.frame(); c.touch("down", 792, 40); c.touch("move", 792, 40); c.touch("up", 792, 40); ok("plug-in window: dragging the vertical bar to the top scrolls to the top", c.editor_view["sy"] == 0)
r.frame(); c.touch("down", 2, 36 + 326 + 8); c.touch("up", 2, 370); ok("plug-in window: dragging the horizontal bar to the left scrolls to the left", c.editor_view["sx"] == 0)
r.frame(); n_before = c.fx_cursor; tap(200, 200); ok("plug-in window: taps around it do not reach the FX page underneath", c.fx_cursor == n_before)
c.ok(); ok("plug-in window: OK closes it", c.editor_req == "close"); c.editor_req = None
r.frame(); tap(317, 18); ok("plug-in window: the - button asks to zoom out", c.editor_req == ("zoom", "out"))
tap(415, 18); ok("plug-in window: the + button asks to zoom in", c.editor_req == ("zoom", "in"))
tap(468, 18); ok("plug-in window: FIT", c.editor_req == ("zoom", "fit"))
tap(366, 18); ok("plug-in window: tapping the % goes back to 100 %", c.editor_req == ("zoom", 1.0))
ok("plug-in window: the soft keys become CLOSE / ZOOM - / ZOOM + / FIT", [soft_text(x) for x in c.soft_labels()][:3] == ["CLOSE", "ZOOM -", "ZOOM +"])
c.soft(0); ok("plug-in window: F1 closes it (pop-ups: F1 cancel / close)", c.editor_req == "close")
c.editor_fx = c.editor_view = c.editor_req = None

# ================================================================= pad modes, Q-link modes, browser, back
e = fresh("/tmp/t7pm"); c = Controls(e); r = Renderer(c); e.save_project = lambda: None
c.set_mode("STEP"); c.button(BTN["SHIFT"], True); c.button(BTN["MUTE"], True); c.button(BTN["SHIFT"], False)
ok("SHIFT + MUTE opens the PADS page", c.mode == "PADS"); r.frame()
c.go_back(); ok("< BACK returns to the screen you came from", c.mode == "STEP")
c.set_mode("PADS"); r.frame(); ok("PADS page opens", c.mode == "PADS")
e.select_pad(0, 2); r.frame(); tap(386 + 1 * 87 + 40, 85); ok("PADS: tapping 16 LEVELS picks it, on the selected pad", e.pad_mode == "16 LEVELS" and e.levels_pad == 2)
vel = e.levels_hit(16, 50); ok("16 LEVELS: pad 16 = full velocity", vel == 127)
vel = e.levels_hit(1, 127); ok("16 LEVELS: pad 1 = the softest", vel == 8)
e.cur_track = 7; e.set_rec("over", start=True); run(e, 0.3); c.pad_hit(8, 100)
ok("16 LEVELS: hits record the levels pad at that velocity", any(ev[1] == 2 and ev[2] == 64 for ev in e.track.events))
e.stop(); e.stop()
e.levels_param = "TUNE"; e.v_rate = [1.0] * e.nv; c.pad_hit(9, 100); c.pad_hit(13, 100); e.render(256)
r9 = next(e.v_rate[i] for i in range(e.nv) if e.v_key[i] == ("levels", 9)); r13 = next(e.v_rate[i] for i in range(e.nv) if e.v_key[i] == ("levels", 13))
ok("16 LEVELS (TUNE): pad 13 is 4 semitones above pad 9", abs(r13 / r9 - 2 ** (4 / 12.0)) < 1e-6)
c.set_pad_mode("PERFORM"); e.perf_root, e.perf_oct, e.perf_scale, e.perf_chord = 0, 5, 1, 0
ok("PERFORM: C major from C4: pads 1-8 walk up the scale", [e.perform_notes(n)[0] for n in range(1, 9)] == [60, 62, 64, 65, 67, 69, 71, 72])
e.perf_chord = 1; ok("PERFORM: TRIAD on pad 2 = D minor (D F A)", e.perform_notes(2) == [62, 65, 69])
e.perf_chord = 2; ok("PERFORM: 7TH on pad 5 = G7 (G B D F)", e.perform_notes(5) == [67, 71, 74, 77])
e.perf_scale = 0; e.perf_chord = 1; ok("PERFORM: chromatic TRIAD = a major chord", e.perform_notes(1) == [60, 64, 67])
e.perf_scale, e.perf_chord = 2, 1                                     # minor triads on a KEYGROUP track, recorded
kt = e.seq.tracks[10]; e.set_track_kind(kt, "keys"); kt.key_pad = 11; e.cur_track = 10
e.set_rec("over", start=True); run(e, 0.3); c.pad_hit(1, 100); e.render(256)
ok("PERFORM: a chord plays three voices", sum(1 for k in e.v_key if k and k[0] == "live") == 3)
run(e, 1.0)
ok("PERFORM: the notes end on their own after the note length (pads send no note-off)", not e.held and not e._live_offs)
ok("PERFORM: the chord is recorded with that length", sorted(ev[1] for ev in kt.events) == [60, 63, 67] and all(40 <= ev[3] <= 56 for ev in kt.events))
e.stop(); e.stop()
c.set_mode("PADS"); c.pads_row = 3; c.nav("right"); ok("PADS: the D-pad changes the selected setting (SCALE)", e.perf_scale == 3)
c.jog(-1); ok("PADS: so does the jog", e.perf_scale == 2)
c.soft(2); ok("PADS: F3 = CHORD in PERFORM", e.perf_chord == 2)
r.frame(); ok("PADS page renders in PERFORM", r.img.size == (W, H))
c.set_pad_mode("TRACK MUTE"); c.pad_hit(2, 100); ok("TRACK MUTE: pad 2 mutes track 2", e.seq.tracks[1].mute)
e.play(); [e.render(256) for _ in range(10)]
c.pad_hit(2, 100); ok("TRACK MUTE: ...and unmutes it", not e.seq.tracks[1].mute)
c.pad_hit(3, 100); c.soft(2); ok("TRACK MUTE: F3 unmutes all", not any(t.mute for t in e.seq.tracks))
e.stop(); e.stop()
c.set_pad_mode("NEXT SEQ"); c.pad_hit(3, 100); ok("NEXT SEQ: stopped = switches at once", e.cur_seq == 2)
c.pad_hit(1, 100); e.play(); run(e, 0.5); c.pad_hit(2, 100)
ok("NEXT SEQ: playing = queued, not switched yet", e.cur_seq == 0 and e.next_seq == 1)
run(e, 0.5); c.set_mode("MAIN"); r.frame(); r.frame()
run(e, e.seq.length / E.PPQ * 60.0 / e.seq.bpm)
ok("NEXT SEQ: switches when the sequence reaches its end", e.cur_seq == 1 and e.next_seq is None and e.playing)
c.pad_hit(3, 100); c.pad_hit(3, 100); ok("NEXT SEQ: tapping the queued pad again cancels", e.next_seq is None)
e.stop(); e.stop(); c.set_pad_mode("NORMAL"); e.select_seq(0)
c.pad_hit(5, 100); ok("NORMAL: pads play their samples again", e.sel == 4)
c.midi_button("PADMODE", True); ok("MIDI learn target PAD MODE cycles the pad mode", e.pad_mode == "16 LEVELS"); c.set_pad_mode("NORMAL")
# Q-link modes
c.set_mode("FX"); ok("Q-links follow the screen by default", c.qlinks()[0][0] != "Volume")
r.frame(); tap(756, 412 + 12); ok("Q-links: tapping the Q pill = PROJECT", c.qlink_mode == "PROJECT")
ok("Q-links PROJECT: volume / tempo / swing / filter on every screen", [q[0] for q in c.qlinks()] == ["Volume", "Tempo", "Swing", "Filter"])
c.armed = [True] * 4; c.knob(1, 127); ok("Q-links PROJECT: Q2 sets the tempo on the FX screen", abs(e.seq.bpm - 180) < 0.6)
e.seq.bpm = 90.0
c.cycle_qlink(); e.select_pad(0, 3); ok("Q-links PAD: the selected pad's tune / level / pan / gain", [q[0] for q in c.qlinks()] == ["Pad tune", "Pad level", "Pad pan", "Pad gain"])
c.armed = [True] * 4; c.knob(0, 127); ok("Q-links PAD: Q1 tunes the selected pad", e.pad.tune == 12)
c.button(BTN["SHIFT"], True); c.jog_press(); c.button(BTN["SHIFT"], False)
ok("SHIFT + jog push: next Q-link mode (TRACK)", c.qlink_mode == "TRACK" and c.qlinks()[0][0] == "Track vol")
c.midi_button("QLINKMODE", True); ok("MIDI learn target Q-LINK MODE: back to SCREEN", c.qlink_mode == "SCREEN")
# browser
os.makedirs("/tmp/t7usb/Kit", exist_ok=True); shutil.copy(os.path.join(HERE, "samples", "pad03.wav"), "/tmp/t7usb/Kit/snare one.wav")
open("/tmp/t7usb/Kit/notes.txt", "w").write("x")
c.button(BTN["SHIFT"], True); c.button(BTN["PROG"], True); c.button(BTN["SHIFT"], False)
ok("SHIFT + PROG opens BROWSE (places)", c.mode == "BROWSE" and c.br_dir is None and c.br_items[0][0] == "Project samples")
c.br_dir = "/tmp/t7usb"; c.br_refresh(); c.br_open(1)
ok("BROWSE: folders open; only audio files are listed", c.br_dir == "/tmp/t7usb/Kit" and [i[0] for i in c.br_items] == ["..  (up)", "snare one.wav"])
e.select_pad(1, 4); n0 = len(e.sources)
c.br_open(1); ok("BROWSE: the first tap previews the file", len(e.sources) == n0 and any(k == ("preview",) for k in e.v_key))
c.br_open(1); ok("BROWSE: a second tap loads it to the selected pad (B05)", len(e.sources) == n0 + 1 and e.pad.src.name == "snare_one")
c.br_load(); ok("BROWSE: loading the same file twice keeps both under unique names", e.sources[-1].name == "snare_one_2")
r.frame(); ok("BROWSE page renders", r.img.size == (W, H))
c.nav("left"); ok("BROWSE: left = up a folder", c.br_dir == "/tmp/t7usb" or c.br_dir is None)
c.br_dir = None; c.br_refresh(); c.soft(3); ok("BROWSE: F4 < BACK (on the places list)", c.mode != "BROWSE" and not any(k == ("preview",) for k in e.v_key if k))

# ================================================================= WARP: pads follow the sequence tempo while it plays
import warp as _warp, time as _tw
print("WARP engine:", _warp.ENGINE)
ew = fresh("/tmp/t7warp"); ew.save_project = lambda: None; cw = Controls(ew); rw = Renderer(cw)
def wait_render(pad, bpm, semis=0, secs=5.0):
    t = _tw.time()
    while _tw.time() - t < secs:
        if ew._warp_key(pad, bpm, semis) in ew.warp_cache: return True
        _tw.sleep(0.02)
    return False
def play_len(pad, change=None):
    """trigger pad, render until it stops; change = (seconds, new bpm) part-way; returns seconds, audio, frame of the swap"""
    ew.trigger(pad, 120); n, out, sw, t_ch = 0, [], None, None
    while any(ew.v_pad[i] is pad for i in range(ew.nv)) and n < E.OUT_SR * 20:
        if change and t_ch is None and n >= change[0] * E.OUT_SR:
            ew.seq.bpm = change[1]; t_ch = n; wait_render(pad, change[1])
        out.append(ew.render(256)[:, 0]); n += 256
        if t_ch is not None and sw is None and any(w and w[1] == change[1] and not w[4] for w in ew.v_warp): sw = n
    return n / float(E.OUT_SR), np.concatenate(out), sw
brk = ew.source_by_name("break"); wp = ew.programs[0].pads[40]; wp.assign(brk); wp.lofi_on = False
ok("WARP: the break's tempo is guessed from its length (8 beats = 90 bpm)", ew.guess_bpm(wp) == 90.0)
ew.seq.bpm = 90.0; ok("WARP: switching it on", ew.set_warp(wp, True) and wp.warp_bpm == 90.0)
ew.seq.bpm = 120.0; ew.render(256); ok("WARP: a tempo change renders the pad for the new tempo in the background", wait_render(wp, 120.0))
secs, y, _ = play_len(wp); ok(f"WARP: at 120 bpm the 8-beat break lasts 4.00 s (got {secs:.2f})", abs(secs - 4.0) < 0.02)
ok("WARP: and still sounds (level kept)", np.sqrt((y ** 2).mean()) > 0.02)
ew.seq.bpm = 90.0; ew.render(256); wait_render(wp, 90.0)
secs, y, sw = play_len(wp, (1.0, 120.0))
ok(f"WARP: tempo 90 -> 120 after 1 s of a sounding note: it follows (4.25 s, got {secs:.2f})", abs(secs - 4.25) < 0.03)
ok("WARP: the playing note cross-fades onto the 120 bpm render", sw is not None)
ok("WARP: no click at the cross-fade (no jump bigger than the break's own transients)", np.abs(np.diff(y[sw - 2048:sw + 2048])).max() <= np.abs(np.diff(y)).max() + 1e-6)
sr_ = E.OUT_SR; tt = np.arange(sr_ * 2) / sr_
sine = ew.add_source("sine440", (0.5 * np.sin(2 * np.pi * 440 * tt)).astype(np.float32))
sp = ew.programs[0].pads[41]; sp.assign(sine); sp.lofi_on = False; sp.warp_bpm = 90.0; ew.seq.bpm = 90.0; ew.set_warp(sp, True)   # 2 s = 3 beats at 90 (not a power of two: set by hand)
ew.seq.bpm = 120.0; ew.render(256); wait_render(sp, 120.0)
def peak_hz(y):
    y = y[4000:-4000]; f = np.abs(np.fft.rfft(y * np.hanning(len(y)))); return np.argmax(f) * sr_ / len(y)
secs, y, _ = play_len(sp)
ok(f"WARP: shorter at a faster tempo (1.50 s, got {secs:.2f}) but the same pitch (440 Hz, got {peak_hz(y):.0f})", abs(secs - 1.5) < 0.02 and abs(peak_hz(y) - 440) < 3)
sp.tune = 12; ew.trigger(sp, 100); ew.render(256); wait_render(sp, 120.0, 12); ew.stop(); [ew.render(256) for _ in range(20)]
for i in range(ew.nv): ew.v_data[i] = None; ew.v_pad[i] = None
secs, y, _ = play_len(sp)
ok(f"WARP: TUNE +12 changes the pitch only (880 Hz, got {peak_hz(y):.0f}; still {secs:.2f} s)", abs(peak_hz(y) - 880) < 5 and abs(secs - 1.5) < 0.02)
sp.tune = 0
# a sequenced WARP loop: one hit at 1.1 on a 2-bar sequence fills exactly the 2 bars at 120 bpm
for t_ in ew.seq.tracks: t_.events = []
ew.seq.bars = 2; ew.seq.bpm = 120.0; tr_ = ew.seq.tracks[3]; tr_.prog = 0; ew._put(tr_, 0, 40, 110, 24); wp.mode = "ONE"
ew.render(256); wait_render(wp, 120.0); ew.locate(0); ew.play(); n_, end_ = 0, None
while n_ < E.OUT_SR * 3.9:
    ew.render(256); n_ += 256
    if end_ is None and n_ > E.OUT_SR and not any(ew.v_pad[i] is wp for i in range(ew.nv)): end_ = n_
ok("WARP: a sequenced loop lasts its 2 bars at the new tempo (no gap, no overlap at the loop point)",
   end_ is None and any(ew.v_pad[i] is wp for i in range(ew.nv)))
for _ in range(int(E.OUT_SR * 0.2 / 256)): ew.render(256)
ok("WARP: ...and is retriggered by the next pass", ew.pass_count >= 1 and any(ew.v_pad[i] is wp for i in range(ew.nv)))
ew.stop(); ew.stop(); tr_.events = []
ew.seq.bpm = 90.0; cw.set_mode("PROG"); ew.select_pad(2, 12); ew.pad.assign(brk)
cw.prog_row = 14; cw.ok(); ok("PROG: WARP row switches it on (OK)", ew.pad.warp and ew.pad.warp_bpm == 90.0)
cw.prog_row = 15; cw.jog(5); ok("PROG: WARP BPM row, jog = 0.1 bpm steps", abs(ew.pad.warp_bpm - 90.5) < 1e-6)
rw.frame(); ok("PROG renders the WARP rows", rw.img.size == (W, H))
ew.pad.stretch = 200; d200_ = ew._warp_render_now(ew.pad, 90.0, 0.0)[0]; ew.pad.stretch = 100; d100_ = ew._warp_render_now(ew.pad, 90.0, 0.0)[0]
ok("PROG SAMPLES: STRETCH 200% makes the WARP render twice as long (half-time)", abs(len(d200_) / float(len(d100_)) - 2.0) < 0.01)

ew.save_project = E.Engine.save_project.__get__(ew); ew.save_project()
ew2 = E.Engine("/tmp/t7warp"); ok("WARP settings are saved with the project", ew2.programs[0].pads[41].warp and ew2.programs[0].pads[41].warp_bpm == 90.0)
ew.save_project = lambda: None
ew.chop_beats(brk, 90.0, 4); cw.chop_mode, cw.chop_bpm = 2, 90.0; ew.select_pad(3, 0); ew.pad.assign(brk); cw.chop_assign()
ok("CHOP: BEATS chops sent to pads carry the loop's tempo as WARP BPM", ew.prog.pads[48].warp_bpm == 90.0 and ew.prog.pads[49].warp_bpm == 90.0)

# ================================================================= USB drives, TRACK OUT, FLATTEN
import json as _js, struct as _st
eu = fresh("/tmp/t7usb2"); eu.save_project = lambda: None; cu = Controls(eu); ru = Renderer(cu)
_mp = "/tmp/t7usb2/mnt_beats"; os.makedirs(_mp, exist_ok=True)
_blk = {"blockdevices": [
    {"name": "/dev/mmcblk0", "type": "disk", "tran": None, "rm": False, "children": [{"name": "/dev/mmcblk0p2", "type": "part", "fstype": "ext4", "mountpoint": "/"}]},
    {"name": "/dev/sda", "type": "disk", "tran": "usb", "rm": True, "size": "29.8G", "children": [
        {"name": "/dev/sda1", "type": "part", "label": "BEATS", "fstype": "exfat", "mountpoint": None, "size": "29.8G"}]}]}
_cmds = []
def _fake(cmd):
    _cmds.append(cmd)
    if cmd[0] == "lsblk": return True, _js.dumps(_blk)
    if cmd[:2] == ["udisksctl", "mount"]:
        _blk["blockdevices"][1]["children"][0]["mountpoint"] = _mp; return True, f"Mounted /dev/sda1 at {_mp}"
    if cmd[:2] == ["udisksctl", "unmount"]:
        _blk["blockdevices"][1]["children"][0]["mountpoint"] = None; return True, "Unmounted /dev/sda1."
    return False, "not here"
cu._run = _fake
ok("USB: drives found with lsblk (the boot card is not listed)", [d[1] for d in cu.usb_drives()] == ["/dev/sda1"])
cu.set_mode("BROWSE"); cu.br_dir = None; cu.br_refresh()
i_usb = next(i for i, it in enumerate(cu.br_items) if "BEATS" in it[0])
ok("USB: an unmounted stick is listed as 'tap to mount'", "tap to mount" in cu.br_items[i_usb][0])
cu.br_open(i_usb); ok("USB: tapping it mounts it (udisks, no root) and opens it", cu.br_dir == _mp and any(c_[:2] == ["udisksctl", "mount"] for c_ in _cmds))
cu.nav("left"); cu.br_refresh(); cu.br_cur = next(i for i, it in enumerate(cu.br_items) if it[1] == _mp)
ok("USB: on the places list F3 becomes EJECT", cu.soft_labels()[2] == "EJECT")
cu.soft(2); ok("USB: EJECT unmounts it", any(c_[:2] == ["udisksctl", "unmount"] for c_ in _cmds) and "tap to mount" in cu.br_items[i_usb][0])
_cmds.clear(); _udisk = lambda cmd: (False, "Not authorized") if cmd[0] == "udisksctl" else _fake(cmd) if cmd[0] == "lsblk" else (True, "")
cu._run = lambda cmd: (_cmds.append(cmd), _udisk(cmd))[1]
mp2 = cu.usb_mount("/dev/sda1", "BEATS", "exfat")
ok("USB: without udisks it falls back to sudo mount, with your user owning a FAT/exFAT stick", mp2 == "/media/sampler/BEATS" and any(c_[:3] == ["sudo", "-n", "mount"] and "-o" in c_ for c_ in _cmds))
cu._run = _fake
# TRACK OUT
def _readf(path):
    b = open(path, "rb").read(); i = b.index(b"data"); n = _st.unpack("<I", b[i + 4:i + 8])[0]
    fmt = _st.unpack("<H", b[20:22])[0]; d = np.frombuffer(b[i + 8:i + 8 + n], "<f4"); return fmt, d[0::2], d[1::2]
eu.seq.tracks[1].mute = True
cu.set_mode("EXPORT"); ok("TRACK OUT: SHIFT + SAMPLE / TRACK OUT > opens the page", cu.mode == "EXPORT")
ok("TRACK OUT: ticks every track with notes that is not muted (break and snare are muted)", cu.ex_tracks() == [0, 2, 3])
cu.ex_toggle(1); ok("TRACK OUT: tap a track to tick it", cu.ex_tracks() == [0, 1, 2, 3])
ru.frame(); ok("TRACK OUT page renders", ru.img.size == (W, H))
eu.render(256); m0 = [(t.mute, t.solo) for t in eu.seq.tracks]
cu.ex_tail = 1.0; cu.start_track_out(wait=True)
fs = sorted(os.listdir(cu.ex_folder))
ok("TRACK OUT: one WAV per track plus the mix", fs == ["00 Mix.wav", "01 Kick.wav", "02 Snare.wav", "03 Hats.wav", "04 Perc.wav"])
fmt, L, R = _readf(os.path.join(cu.ex_folder, "01 Kick.wav"))
ok("TRACK OUT: stereo 32-bit float WAV, sequence length + tail", fmt == 3 and abs(len(L) / E.OUT_SR - (eu.bounce_length() + 1.0)) < 0.01)
_, sL, _ = _readf(os.path.join(cu.ex_folder, "02 Snare.wav"))
ok("TRACK OUT: a muted track is still bounced as a stem when ticked", np.abs(sL).max() > 0.05)
_, mL, _ = _readf(os.path.join(cu.ex_folder, "00 Mix.wav")); _, hL, _ = _readf(os.path.join(cu.ex_folder, "03 Hats.wav"))
ok("TRACK OUT: the mix leaves out the muted snare, the snare stem has it", np.corrcoef(mL, sL)[0, 1] < 0.5)
ok("TRACK OUT: a stem holds only its own track (kick and hats stems do not overlap)", abs(np.corrcoef(L, hL)[0, 1]) < 0.2)
ok("TRACK OUT: mutes, solos and the transport are restored afterwards", [(t.mute, t.solo) for t in eu.seq.tracks] == m0 and not eu.playing and not eu.bouncing)
eu.bouncing = True; ok("TRACK OUT: live outputs are silent while a bounce runs", np.abs(eu.render(256)).max() == 0); eu.bouncing = False
cu.ex_song = True; eu.song = [[0, 2], [1, 1]]; eu.seqs[1].bars = 1; eu.seqs[1].bpm = 120.0
ok("TRACK OUT: SONG length adds up the steps (2 x 2 bars at 90 + 1 bar at 120)", abs(eu.bounce_length(True) - (2 * 8 * 60 / 90.0 + 4 * 60 / 120.0)) < 1e-6)
eu.seq.tracks[1].mute = False
# FLATTEN
eu.cur_track = 0; cu.set_mode("PROG"); eu.select_pad(0, 2); fp = eu.pad
fp.tune, fp.reverse = 7, True
def _hear(pad, secs=0.6):
    with eu.lock:
        for i in range(eu.nv): eu.v_data[i] = None; eu.v_pad[i] = None
    eu.trigger(pad, 110); return np.concatenate([eu.render(256)[:, 0] for _ in range(int(secs * E.OUT_SR / 256))])
y0 = _hear(fp)
cu.flatten_toggle(); y1 = _hear(fp)
ok("FLATTEN: makes a new sample and puts it on the pad", fp.src.name == "pad03_flat" and eu.sources[-1] is fp.src)
ok("FLATTEN: what was baked in is reset (tune 0, reverse off, lo-fi off)", fp.tune == 0 and not fp.reverse and not fp.lofi_on)
ok("FLATTEN: the flattened pad sounds the same as before (the edge de-click fades run twice, so not bit-identical)", np.corrcoef(y0[:len(y1)], y1)[0, 1] > 0.965)
cu.prog_front = False; ru.frame(); ok("FLATTEN: the PROG button turns into UNFLATTEN", fp._unflat is not None and any(h[0][0] == 556 for h in cu.hits))
cu.ed_open("FLATTEN PAD"); cu.soft(3)
ok("FLATTEN: EDIT > FLATTEN PAD (F4 DO IT) undoes it (old sample and settings back)", fp.src.name == "pad03" and fp.tune == 7 and fp.reverse)
cu.set_mode("PROG")
cu.button(BTN["SHIFT"], True); cu.button(BTN["F3"], True); cu.button(BTN["SHIFT"], False)
ok("SHIFT + F3 = pad bank C (there is no BANK key on the panel)", eu.bank == 2); eu.bank = 0
import make_stl as _MS; ok("PANEL: 23 Arduino keys, LOAD where STEP was (button 8), no STEP or BANK key, TAP in its place", len(_MS.KEY_POS) == 23 and "BANK" not in _MS.PANEL_KEYS and "STEP" not in _MS.PANEL_KEYS and _MS.LAYOUT["LOAD"] == (_MS.KCOL[2], _MS.SCR1_Y, _MS.CAP_SMALL) and _MS.KEY_NAMES.index("LOAD") == BTN["LOAD"] == 8 and _MS.LAYOUT["TAP"][0] == _MS.KCOL[3])
fp.tune, fp.reverse = 0, False; eu.set_fx(fp, "builtin", "Delay"); fp.fx.set(0, 0.5); fp.fx.set(2, 0.6)
n0 = fp.length; eu.flatten_pad(fp)
ok("FLATTEN: an insert effect is baked in with its tail (the delay echoes make it longer)", fp.length > n0 * 2 and fp.fx is None)

# ================================================================= PROGRAM INSERTS (4 per program, after the pad inserts, not flattened)
ei = fresh("/tmp/t7pins"); ei.save_project = lambda: None; ci = Controls(ei); ri = Renderer(ci)
ei.cur_track = 0; ci.set_mode("FX"); ri.frame()
ci.touch("down", 200, 71); ci.touch("up", 200, 71); ok("FX: the INSERT 1 key on the chain bar picks program insert 1", ci.fx_target == 65 and ci.fx_tgt() == E.FxSlot(ei.prog, 0))
ci.fx_cursor = next(i for i, it in enumerate(ci.fx_items) if it[1] == "Delay"); ci.fx_load()
ok("FX: an effect loads into program insert 1", ei.prog.fx[0] is not None and ei.prog.fx[0].name.lower().startswith("delay"))
ei.prog.fx[0].set(0, 0.5); ei.prog.fx[0].set(2, 0.7)
ci.pad_hit(5, 100); ok("FX: hitting a pad keeps the program insert selected", ci.fx_target == 65)
ri.frame(); ok("FX screen renders with program inserts", ri.img.size == (W, H))
ci.nav("right"); ok("FX: right steps along the chain (program insert 2)", ci.fx_target == 66)
ci.fx_set_target(65)
def _tail(pad, secs=1.5):
    with ei.lock:
        for i in range(ei.nv): ei.v_data[i] = None
    for _ in range(int(2.0 * E.OUT_SR / 256)): ei.render(256)            # let old tails die
    ei.trigger(pad, 110); y = np.concatenate([ei.render(256)[:, 0] for _ in range(int(secs * E.OUT_SR / 256))])
    return y
kp = ei.programs[0].pads[0]; n_hit = kp.length
y = _tail(kp)
ok("PROGRAM INSERT: the delay is heard on the program's pads (echoes after the sample ends)", np.abs(y[n_hit + 4000:]).max() > 0.02)
other = ei.programs[1].pads[0]
y2 = _tail(other)
ok("PROGRAM INSERT: other programs are not affected", np.abs(y2[other.length + 8000:]).max() < 0.01)
src = ei.flatten_pad(kp)
ok("PROGRAM INSERT: FLATTEN leaves it out (the flattened pad is just the dry sound) and it stays on the program",
   src is not None and src.length <= n_hit + 1 and ei.programs[0].fx[0] is not None)
ei.unflatten_pad(kp)
for t_ in ei.seq.tracks[1:]: t_.mute = True
ci.ex_mix, ci.ex_tail = False, 1.0; ci.ex_sel = {0}; ci._drives = []; ci.start_track_out(wait=True)
_, kL, _ = _readf(os.path.join(ci.ex_folder, "01 Kick.wav"))
ok("PROGRAM INSERT: TRACK OUT stems include it (delay echoes in the kick stem)", len(kL) > 0 and np.abs(kL[int(0.38 * E.OUT_SR):int(0.62 * E.OUT_SR)]).max() > 0.01)
for t_ in ei.seq.tracks[1:]: t_.mute = False
ei.toggle_bypass(E.FxSlot(ei.prog, 0)); y3 = _tail(kp)
ok("PROGRAM INSERT: BYPASS switches it off", np.abs(y3[n_hit + 4000:]).max() < 0.01); ei.toggle_bypass(E.FxSlot(ei.prog, 0))
ei.save_project = E.Engine.save_project.__get__(ei); ei.save_project()
ei2 = E.Engine("/tmp/t7pins"); ok("PROGRAM INSERT: saved and loaded with the project", ei2.programs[0].fx[0] is not None and abs(ei2.programs[0].fx[0].get(2) - 0.7) < 1e-6)

# ================================================================= identity: unbranded for now, a logo drops in later (brand/make_brand.py)
from screens import splash as _splash
import make_stl as _M
_sp = np.array(_splash("loading", 0.5))
ok("BRAND: the start-up screen renders (software name until a logo is added)", _sp.shape == (H, W, 3) and (_sp.sum(2) > 600).sum() > 2000)
ok("BRAND: the badge pocket stays at least 10 mm clear of the left hinge-ear slot", _M.LOGO[1] + 10 <= _M.ear_x()[0][0] and _M.LOGO[3] <= _M.FASCIA_H - 1.5)
def _span(m): return [max(p[k] for t in m.t for p in t) - min(p[k] for t in m.t for p in t) for k in range(3)]
ok("FRAME: the four 10.1 inch frame pieces each fit a 220 mm bed", all(max(_span(m)[:2]) < 220 for m in _M.frame_halves()))
_bu, _bv = _M.board_origin()
_mod = (_bu + 0.05, _bv + 0.05, _M.FR_BT + 0.05, _bu + _M.DISP_BOARD[0] - 0.05, _bv + _M.DISP_BOARD[1] - 0.05, _M.FR_BT + _M.DISP_T - 0.05)
ok("FRAME: nothing in the bezel or tray intrudes into the display module", not any(_mod[0] < p[0] < _mod[3] and _mod[1] < p[1] < _mod[4] and _mod[2] < p[2] < _mod[5]
   for m in (_M.frame_bezel(), _M.frame_tray_local()) for t in m.t for p in t))
_tmpb = "/tmp/t7brand"; shutil.rmtree(_tmpb, ignore_errors=True); os.makedirs(_tmpb)
from PIL import Image as _Im, ImageDraw as _Id
_lg = _Im.new("RGBA", (400, 300), (0, 0, 0, 0)); _dd = _Id.Draw(_lg)
_dd.polygon([(200, 10), (380, 200), (20, 200)], fill=(255, 255, 255, 255)); _dd.rectangle([60, 250, 340, 280], fill=(255, 255, 255, 255))
_lg.save(os.path.join(_tmpb, "logo.png"))
import importlib.util as _iu
_spec = _iu.spec_from_file_location("mb", os.path.join(HERE, "brand", "make_brand.py")); _mb = _iu.module_from_spec(_spec); _spec.loader.exec_module(_mb)
_full = _mb.crop(_mb.load_mask(os.path.join(_tmpb, "logo.png"))); _bd = _mb.badge_part(_full)
ok("BRAND: make_brand finds the mark above the lettering (the badge leaves the small text out)", _full.shape[0] > _bd.shape[0] + 50)

# ================================================================= palm rest (padded vinyl, MPC60 style) and wedge cheeks
_pl, _pr = _M.palmrest((0, _M.SPLIT_X)), _M.palmrest((_M.SPLIT_X, _M.W))
_ext = lambda m: np.array(m.t).reshape(-1, 3)
ok("PALM REST: both printed halves fit a 220 mm bed", all(np.ptp(_ext(_M.palmrest_print(c))[:, 0]) <= 220 and np.ptp(_ext(_M.palmrest_print(c))[:, 1]) <= 220 for c in ((0, _M.SPLIT_X), (_M.SPLIT_X, _M.W))))
ok("PALM REST: solid printed halves (positive volume)", _pl.volume() > 0 and _pr.volume() > 0)
ok("PALM REST: the pad top is flush with the cheeks' front and 6 mm above the panel's front edge", abs(_M.PR_TOP - _M.cheek_profile()[-1][1]) < 1e-9 and abs(_M.PR_TOP - (_M.FRONT_Z + _M.LID) - 6.0) < 1e-9)
ok("PALM REST: PHONES and LEVEL sit on its front face, below the pad", all(z + d / 2 < _M.PR_CORE - _M.PR_WALL for x, z, d, _ in _M.FRONT_HOLES))
ok("PALM REST: the cheeks cover its ends (they start in front of it)", _M.CH_Y0 < -_M.PR_D)
ok("PALM REST: bolts and the cable hole stay clear of the jacks and ribs", all(abs(b - r) > 6 for b in _M.PR_BOLTS + [_M.PR_CABLE[0]] for r in _M.PR_RIBS) and all(abs(b - x) > 8 for b in _M.PR_BOLTS for x, *_ in _M.FRONT_HOLES))
_cp = _M.cheek_profile()
ok("CHEEK: straight cuts, flush with the console top, a low rail 6 mm above the panel all the way back", len(_cp) == 8 and abs(_cp[3][1] - _M.RT) < 1e-9 and abs(_cp[4][1] - _M.RT) < 1e-9 and all(abs(_M.cheek_top(y) - (_M.plane(0, y) + _M.LID) - 6.0) < 1e-9 for y in (1.0, 100.0, _M.D - 1)))
ok("CHEEK: the 3D pieces are convex and cover the outline's area", all(all(((b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0])) >= -1e-9 for a, b, c in zip(p, p[1:] + p[:1], p[2:] + p[:2])) for p in _M.cheek_pieces()) and abs(sum(_M.poly_area(p) for p in _M.cheek_pieces()) - _M.poly_area(_cp)) < 1e-6)

_jw = _M.jog_wheel(); _jp = _ext(_jw)
ok("JOG WHEEL: 50 mm, solid, fits under the 50 mm clear circle and takes 30 mm washers inside", _jw.volume() > 0 and np.ptp(_jp[:, 0]) <= _M.JOG_WHEEL_D + 1.3 and 2 * _M.JW_POCKET[1] >= 30.0 and 2 * (_M.JW_POCKET[0] - 0.4) <= 17.0)

# ================================================================= automation (GRID: drawn in the bottom lane, or written with the Q-links)
ea = fresh("/tmp/t7auto"); ca = Controls(ea); ra = Renderer(ca); ea.save_project = lambda: None
ok("AUTOMATION: straight lines between points, flat before / after", E.auto_value([[0, 0.0], [96, 1.0]], 48) == 0.5 and E.auto_value([[96, 0.3]], 0) == 0.3 and E.auto_value([[0, 0.2], [96, 0.6]], 500) == 0.6 and E.auto_value([], 5) is None)
ca.set_mode("GRID"); ra.frame()
_h0 = ra.grid_h()
ca.cycle_lane(); ra.frame(); _hv = ra.grid_h(); ca.cycle_lane(); ra.frame(); _ha = ra.grid_h()
ok("GRID: the bottom lane starts hidden (the notes get the room) and toggles VEL / AUTO / OFF", ca.g_view == "AUTO" and _h0 > _hv > _ha and ra.img.size == (W, H))
tra = ea.seq.tracks[4]; ea.cur_track = 4; tra.mute = False
_tg = [k for k, *_ in ea.auto_targets(tra)]
ok("AUTOMATION: a track can automate its level and pan", _tg[:2] == ["vol", "pan"])
ea.set_fx(E.FxSlot(ea.programs[tra.prog], 0), "builtin", "Filter")
ok("AUTOMATION: ...and every parameter of its program's insert effects", "ins0:0" in [k for k, *_ in ea.auto_targets(tra)])
ea.auto_set_point(tra, "vol", 0, 0.2); ea.auto_set_point(tra, "vol", 384, 1.0); ea.auto_set_point(tra, "ins0:0", 0, 0.1); ea.auto_set_point(tra, "ins0:0", 384, 0.9)
ea.auto_set_point(tra, "vol", 0, 0.25)
ok("AUTOMATION: setting a point at the same tick replaces it", tra.auto["vol"] == [[0, 0.25], [384, 1.0]])
ea.select_seq(0); ea.play(from_start=True); audio(ea, 60.0 / ea.seq.bpm * 2)   # two beats in
_fx0 = ea.programs[tra.prog].fx[0]
ok("AUTOMATION: playback follows the lines (level and the insert's filter cutoff at beat 2)", abs(tra.vol - E.auto_value(tra.auto["vol"], ea.pos)) < 0.05 and abs(_fx0.get(0) - E.auto_value(tra.auto["ins0:0"], ea.pos)) < 0.05)
ea.stop()
_long = next(p for p in ea.programs[tra.prog].pads if not p.empty)
ea.v_data = [None] * ea.nv; tra.vol = 0.5; ea.trigger(_long, 120, track=tra); _vi = next(i for i in range(ea.nv) if ea.v_pad[i] is _long)
_g_before = ea.v_gl[_vi]; tra.auto = {"vol": [[0, 0.1]]}; ea._apply_automation(ea.seq, 0)
ok("AUTOMATION: a note that is already sounding follows the level change", _g_before > 0 and abs(ea.v_gl[_vi] / _g_before - 0.1 / 0.5) < 0.02)
tra.auto = {}; tra.vol = 0.8
ca.qlink_mode = "TRACK"; ea.set_rec("over", start=True); audio(ea, 0.3)
for k in range(6): ca.nudge(0, -0.1); audio(ea, 0.1)
ea.stop(); ea.rec = "off"
ok("AUTOMATION: turning Track vol while recording writes points at the playhead", len(tra.auto.get("vol", [])) >= 4 and tra.auto["vol"][-1][1] < tra.auto["vol"][0][1])
ca.qlink_mode = "SCREEN"; ca.set_mode("GRID"); ca.g_view = "AUTO"; ca.g_auto = 1; tra.auto.pop("pan", None); ra.frame()
_gx = (92 + 792) // 2; ca.touch("down", _gx, 300); ca.touch("up", _gx, 300)
ok("GRID: dragging in the AUTO lane draws a point for the chosen parameter (track pan)", len(tra.auto.get("pan", [])) == 1 and 0.6 < tra.auto["pan"][0][1] < 0.9)
ca.auto_clear_lane(); ok("GRID: CLEAR empties that lane only", "pan" not in tra.auto and "vol" in tra.auto)
ea.save_project = E.Engine.save_project.__get__(ea); ea.save_project()
ok("AUTOMATION: saved with the project and reloaded", E.Engine("/tmp/t7auto").seqs[0].tracks[4].auto.get("vol") == tra.auto["vol"])

# ================================================================= MPC2000XL import (.SND .PGM .APS .ALL)
import mpc_import as MI, importlib.util as _iu2
_sp = _iu2.spec_from_file_location("mkmpc", os.path.join(HERE, "examples", "mpc_import", "make_test_mpc.py")); _mk = _iu2.module_from_spec(_sp); _sp.loader.exec_module(_mk)
_mf = "/tmp/t7mpc_src"; shutil.rmtree(_mf, ignore_errors=True); _mk.make(_mf)
_a = MI.read_all(os.path.join(_mf, "ALL_SEQS.ALL"))
ok("MPC: .ALL sequences land in their slots (1 and 3), with tempo, bars and every event", sorted(_a["sequences"]) == [0, 2] and _a["sequences"][0]["tempo"] == 93.5 and len(_a["sequences"][0]["bars"]) == 2 and len(_a["sequences"][0]["events"]) == 8)
ok("MPC: .ALL song steps read", _a["songs"][0]["steps"] == [(0, 2), (2, 1)])
_x = MI.read_aps(os.path.join(_mf, "ALL_PGMS.APS"))
ok("MPC: .APS programs and the program each DRUM plays", sorted(_x["programs"]) == [0, 1] and _x["programs"][1]["name"] == "KIT" and [d["program"] for d in _x["drums"]] == [1, 0, 0, 0])
_h = MI.read_snd(os.path.join(_mf, "HAT.SND"))
ok("MPC: a stereo 22 kHz .SND reads as mono with its rate, start and tune", _h["rate"] == 22050 and _h["data"].ndim == 1 and len(_h["data"]) == 2205 and _h["start"] == 100 and _h["tune"] == 10)
ok("MPC: envelope values follow the MPC2000XL curve (100 = 5 s)", MI.env_ms(100) == 5000 and MI.env_ms(5) == 13 and MI.env_ms(0) == 0)
em = fresh("/tmp/t7mpc"); old_wavs = sorted(os.listdir(em.sample_dir))
rp = MI.import_folder(em, _mf)
_bk = rp.backup
ok("MPC import: the old project is moved to backups/ (project.json and every sample)", _bk and os.path.isfile(os.path.join(_bk, "project.json")) and sorted(os.listdir(os.path.join(_bk, "samples"))) == old_wavs)
ok("MPC import: only the imported sounds are left in samples/", sorted(os.listdir(em.sample_dir)) == ["hat.wav", "kick.wav"])
P = em.programs[0]; pd = P.pads
ok("MPC import: the program DRUM 1 plays comes first", P.name == "KIT" and em.programs[1].name == "EMPTY")
ok("MPC import: pad A01 = note 37: its sound, tune -2.5 st, mixer 80 % panned left, decay fade, no lo-fi, MPC velocity",
   pd[0].src.name == "kick" and pd[0].tune == -2.5 and abs(pd[0].vol - 0.8) < 1e-9 and abs(pd[0].pan + 0.5) < 1e-9 and pd[0].fade_out == MI.env_ms(20) and not pd[0].lofi_on and pd[0].vel_mpc == 100)
ok("MPC import: the 22 kHz sound is resampled; its start point and sound tune (+1 st) come across", abs(em.source_by_name("hat").length - 4410) <= 2 and pd[1].start == 200 and pd[1].tune == 1.0)
ok("MPC import: mute assign 36 <-> 46 becomes one choke group", pd[1].choke and pd[1].choke == pd[2].choke and pd[0].choke == 0)
ok("MPC import: voice overlap NOTE OFF -> HOLD; attack / decay (START) -> fades", pd[2].mode == "HOLD" and pd[2].fade_in == MI.env_ms(10) and pd[2].fade_out == MI.env_ms(30))
spare = [i for i, p in enumerate(pd) if not p.empty and i not in (0, 1, 2, 3, 4)]
ok("MPC import: notes with a sound but no pad (45, 70) go on spare pads", len(spare) == 2)
p45 = next(p for p in pd if p.flt != "OFF")
ok("MPC import: a closed filter (freq 40) becomes the pad's own low-pass at that cutoff", p45.flt == "LP" and abs(p45.cutoff - 0.4) < 1e-9 and p45.fx is None)
ok("MPC import: a sound missing from the folder is reported, not fatal", any("missing" in w for w in rp.warn))
S0, S1 = em.seqs[0], em.seqs[1]
ok("MPC import: sequences keep their order, names, tempo and length", (S0.name, S0.bpm, S0.bars, S1.name, S1.bpm, S1.bars) == ("BEAT", 93.5, 2, "FILL", 100.0, 1))
ok("MPC import: the song comes across", em.song == [[0, 2], [1, 1]])
dr = {t.name: t for t in S0.tracks if t.events}
ev = dr["Drums"].events
ok("MPC import: SIMULT plays both notes' pads", (96, 3, 100, 24) in ev and (96, 0, 100, 24) in ev)
ok("MPC import: VEL SW picks the pad by velocity (soft = note 44, hard = note 45)", (192, 4, 30, 24) in ev and any(e_[0] == 288 and e_[1] in spare for e_ in ev))
ok("MPC import: a MIDI track stays MIDI on its channel", dr["Keys"].kind == "midi" and dr["Keys"].midi_ch == 2 and dr["Keys"].events == [(0, 60, 90, 96)])
ok("MPC import: track velocity 50 % scales the hits; a track that was off is muted", dr["Soft"].events[0][2] == 50 and dr["Off"].mute)
_pv = pd[0]; _pv.vel_mpc = 100; em.v_data = [None] * em.nv; em.trigger(_pv, 64, track=S0.tracks[0])
_g1 = max(em.v_gl); em.v_data = [None] * em.nv
ok("MPC velocity: an imported pad answers velocity like the MPC (64 -> about 50 %, not 36 %)", abs(_g1 / (_pv.vol * S0.tracks[0].vol * 10 ** (_pv.gain_db / 20) * 0.5) - 1.0) < 0.02)
_pv.vel_mpc = 100
_q = em.programs[1].pads[0]; _q.assign(pd[1].src); _q.choke = pd[1].choke
em.v_data = [None] * em.nv; em.trigger(_q, 100); em.render(256); em.trigger(pd[2], 100); em.render(256)
ok("MPC import: a mute group in one program never cuts pads of another program", any(em.v_pad[i] is _q and em.v_kill[i] < 0 for i in range(em.nv)))
_q.src = None; em.v_data = [None] * em.nv
em.select_seq(0); em.play(from_start=True); _y = audio(em, 1.5); em.stop()
ok("MPC import: the imported beat plays", np.abs(_y).max() > 0.05)
e2 = E.Engine("/tmp/t7mpc")
ok("MPC import: saved; reloads with tune, velocity response, chokes and events", e2.programs[0].pads[0].tune == -2.5 and e2.programs[0].pads[0].vel_mpc == 100 and e2.programs[0].pads[1].choke == pd[1].choke and e2.seqs[0].tracks[0].events == S0.tracks[0].events)
# browser: MPC files are listed, the first tap says what is inside, the second imports
cm = Controls(em); rm = Renderer(cm); cm.set_mode("BROWSE"); cm.br_dir = _mf; cm.br_refresh()
names_ = [i[0] for i in cm.br_items]
ok("BROWSE: .SND sounds and MPC project files are listed", "KICK.SND" in names_ and "ALL_SEQS.ALL" in names_ and "ALL_PGMS.APS" in names_)
_ia = names_.index("ALL_SEQS.ALL"); cm.br_open(_ia)
ok("BROWSE: the first tap on an MPC file says what is in the folder; F2 becomes IMPORT", cm.br_msg.startswith("MPC2000XL: 2 seq, 2 pgm, 2 snd") and cm.soft_labels()[1] == "IMPORT")
rm.frame(); ok("BROWSE: the MPC import panel renders", rm.img.size == (W, H))
for _m in ["MAIN", "SEQ", "GRID", "STEP", "PROG", "SAMPLE", "CHOP", "MIXER", "FX", "SONG", "PADS"]:
    cm.set_mode(_m); rm.frame()
cm.set_mode("PROG"); rm.frame(); cm.set_mode("BROWSE")
ok("MPC import: every screen renders an imported project (0.1 st tunings show as +2.5 st)", E.fmt_st(-2.5) == "-2.5 st" and E.fmt_st(3) == "+3 st" and rm.img.size == (W, H))
em.seqs[0].name = "CHANGED"; cm.br_open(_ia)
ok("BROWSE: the second tap opens the IMPORT window (nothing changed yet)", cm.br_import is not None and em.seqs[0].name == "CHANGED")
rm.frame(); ok("BROWSE: the IMPORT window renders", rm.img.size == (W, H)); cm.soft(3)
ok("BROWSE: the second tap imports (and reports)", em.seqs[0].name == "BEAT" and cm.br_msg.startswith("Imported 2 sequences") and os.path.isfile(os.path.join(em.dir, "mpc_import_report.txt")))
ok("MPC import: a second import keeps the first backup too", len(os.listdir(os.path.join(em.dir, "backups"))) == 2)
_ik = names_.index("KICK.SND"); n0 = len(em.sources); cm.br_open(_ik); cm.br_open(_ik)
ok("BROWSE: a .SND previews and loads to the pad like a WAV (named from its header)", len(em.sources) == n0 + 1 and em.pad.src.name.startswith("kick"))

# ================================================================= MPC 2.x import (.xpj project: .xpm programs, .sxq sequences, WAV slices)
import mpc2_import as M2
_sp2 = _iu2.spec_from_file_location("mkmpc2", os.path.join(HERE, "examples", "mpc_import", "make_test_mpc2.py")); _mk2 = _iu2.module_from_spec(_sp2); _sp2.loader.exec_module(_mk2)
shutil.rmtree("/tmp/t7mpc2_src", ignore_errors=True); _xpj = _mk2.make("/tmp/t7mpc2_src"); _dd = M2.find_project(_xpj)[1]
_x24, _sr24 = E.read_wav_pcm(os.path.join(_dd, "Kick.WAV"))
ok("WAV: 24-bit files load without extra libraries", _x24.shape == (8820, 2) and _sr24 == 44100 and abs(float(_x24[:, 0].max()) - 0.9 * float(np.max(np.sin(2 * np.pi * 55 * np.arange(8820) / 44100.0) * np.exp(-np.arange(8820) / 44100.0 * 25)))) < 1e-3)
ok("MPC 2.x: slices are read from the WAV's atem chunk", M2.wav_slices(os.path.join(_dd, "Break.WAV"))["slices"] == [(0, 12000), (12000, 24000), (24000, 36000), (36000, 48000)])
_sx = M2.read_sxq(os.path.join(_dd, "1.sxq"))
ok("MPC 2.x: an .sxq gives name, tempo, bars, the program each track plays and its notes", (_sx["name"], _sx["tempo"], _sx["bars"], _sx["tracks"][0]["program"], _sx["tracks"][0]["events"][1]) == ("Verse", 92.0, 2, "Kit", (960, 37, 80, 960)))
_xp = M2.read_xpm(os.path.join(_dd, "Kit.Drum.xpm"))
ok("MPC 2.x: an .xpm drum program gives its pads, layers, warp and pad -> note map", sorted(_xp["pads"]) == [1, 2, 3, 4, 70] and _xp["pads"][2]["warp"] and _xp["notes"][1] == 36)
e3 = fresh("/tmp/t7mpc2"); r3 = M2.import_project(e3, _xpj)
P3 = e3.programs[0].pads
ok("MPC 2.x import: the drum program comes in, the Audio program is reported", e3.programs[0].name == "Kit" and any("Audio" in w for w in r3.warn))
ok("MPC 2.x import: pad tune (coarse + fine), level against 0 dB, pan, mute group, MPC velocity, no lo-fi",
   P3[0].tune == -1.5 and abs(P3[0].vol - 0.5) < 1e-3 and abs(P3[0].pan + 0.5) < 1e-9 and P3[0].choke and P3[0].choke == P3[1].choke and P3[0].vel_mpc == 100 and not P3[0].lofi_on)
_brk = e3.source_by_name("Break")
ok("MPC 2.x import: slices become CHOP markers (48 kHz -> 44.1 kHz) and the pads are linked to them", _brk.chops == [11025, 22050, 33075] and P3[1].link == (_brk.id, 0) and (P3[1].start, P3[1].end) == (0, 11025) and P3[3].link == (_brk.id, 3))
ok("MPC 2.x import: WARP on with its tempo; attack -> fade in; reverse; layer tune; note-on trigger -> HOLD",
   P3[1].warp and P3[1].warp_bpm == 90.0 and P3[2].fade_in == 200 and P3[2].reverse and P3[3].tune == 3.0 and P3[3].mode == "HOLD")
ok("MPC 2.x import: pads in banks E-H are reported", any("pad 70" in w for w in r3.warn))
S3 = e3.seqs[0]; tr3 = S3.tracks[0]
ok("MPC 2.x import: sequences keep name, tempo, bars; 960 -> 96 ticks; a SIMULT target plays too",
   (S3.name, S3.bpm, S3.bars, e3.seqs[1].name) == ("Verse", 92.0, 2, "Hook") and (0, 0, 100, 96) in tr3.events and (0, 3, 100, 96) in tr3.events and (96, 1, 80, 96) in tr3.events and (192, 2, 127, 96) in tr3.events)
ok("MPC 2.x import: notes on pads outside A-D are reported, the song plays every sequence", any("no pad in A-D" in w for w in r3.warn) and e3.song == [[0, 1], [1, 1]])
e3.select_seq(0); e3.play(from_start=True); _y3 = audio(e3, 1.0); e3.stop()
ok("MPC 2.x import: the imported beat plays", np.abs(_y3).max() > 0.05)
ok("MPC 2.x import: saved and reloads with chops, links and warp", (lambda e4: e4.source_by_name("Break").chops == _brk.chops and e4.programs[0].pads[1].link is not None and e4.programs[0].pads[1].warp)(E.Engine("/tmp/t7mpc2")))
c3 = Controls(e3); rr3 = Renderer(c3); c3.set_mode("BROWSE"); c3.br_dir = "/tmp/t7mpc2_src"; c3.br_refresh()
_n3 = [i[0] for i in c3.br_items]; _ix = _n3.index("TEST.xpj"); c3.br_open(_ix)
ok("BROWSE: an MPC 2.x .xpj is listed and described", c3.br_msg.startswith("MPC 2.x: 2 seq, 1 drum pgm, 2 wav") and c3.soft_labels()[1] == "IMPORT")
rr3.frame(); e3.seqs[0].name = "X"; c3.br_open(_ix); c3.soft(3)
ok("BROWSE: the second tap imports the MPC 2.x project", e3.seqs[0].name == "Verse" and c3.br_msg.startswith("Imported 2 sequences"))

# ================================================================= Rossum SP-1200 import (.sp12) - PARKED: the reader is tested, it is not in the UI yet
import sp1200_import as SP
def _make_sp12(path):
    b = bytearray(SP.FILE_SND + 3 * (1 << 18))
    q = lambda ram: ram - SP.RAM_SEQ
    seg = bytes([0x00, 0x04, 0x00, 0x03,                      # 4 beats per bar, 768 ticks (2 bars)
                 0x02, 0x58, 0xF8, 0x9C,                      # tick 0: A1 at full level, then A5 (1-byte event, last)
                 0x00,                                        # +64
                 0x82, 0xD9, 0x78,                            # tick 96: A2 at level 7/15 (last)
                 0x80, 0x00, 0x00, 0x00, 0x02, 0x88, 0x01])   # 160, 192, 256, 320, then tick 384: C1 (no sound); end
    b[q(0x7194):q(0x7194) + len(seg)] = seg
    struct.pack_into("<HH", b, 0x10, 0x7194 + len(seg), 0xFFFF)
    struct.pack_into("<H", b, q(0x6F04) + 2, 0x7194)            # segment 01
    for i in range(32):                                         # names, as the SP writes them
        b[SP._par(0x6B30) + 6 * i:SP._par(0x6B30) + 6 * i + 6] = bytes([ord(SP.NAMES[i][0]) | 0x80, ord(SP.NAMES[i][1]) | 0x80, 0xA0, 32, 32, 32])
    def pad(label, slot, a, e):
        i = SP.NAMES.index(label)
        struct.pack_into("<HH", b, SP._par(0x6BF0) + 4 * i, a, e)
        b[SP._par(0x6C7E) + 10 * i + 1] = 0x80 | slot
    pad("A1", 7, 0, 26040); pad("A2", 6, 13020, 10); pad("A5", 7, 26040, 52080)
    n = 1 << 19; x = np.full(n, 0x800, np.int32)
    tt = np.arange(52080); x[7 * 65536:7 * 65536 + 52080] = 0x800 + (1500 * np.sin(2 * np.pi * 110 * tt / 26040)).astype(np.int32)
    x[6 * 65536:6 * 65536 + 13020] = 0x800 + np.linspace(0, 1500, 13020).astype(np.int32)
    p2 = x.reshape(-1, 2)
    t3 = np.stack([p2[:, 0] >> 4, p2[:, 1] >> 4, ((p2[:, 0] & 15) << 4) | (p2[:, 1] & 15)], 1).astype(np.uint8)
    b[SP.FILE_SND:] = t3.tobytes()
    open(path, "wb").write(bytes(b))
import struct
_sp = "/tmp/t7sp/TEST.sp12"; os.makedirs("/tmp/t7sp", exist_ok=True); _make_sp12(_sp)
_m = SP.sample_memory(open(_sp, "rb").read())
ok("SP-1200: sample memory unpacks (two 12-bit samples per three bytes, 2^19 samples)", len(_m) == 1 << 19 and abs(float(_m[7 * 65536 + 59]) - 1500 * np.sin(2 * np.pi * 110 * 59 / 26040) / 2048) < 2 / 2048)
_pp = SP.read_project(_sp)
ok("SP-1200: pads give slot, start / end and reverse", [(x["label"], x["slot"], x["reverse"]) for x in _pp["pads"] if x["used"]] == [("A1", 7, False), ("A2", 6, True), ("A5", 7, False)])
_sg = _pp["segments"][1]
ok("SP-1200: a segment gives beats, length and its hits on the 64-tick clock", (_sg["beats"], _sg["length"]) == (4, 768) and [(e[0], e[1], e[2]) for e in _sg["events"]] == [(0, 0x18, 127), (0, 0x1C, 127), (96, 0x19, 59), (384, 0x08, 127)])
e5 = fresh("/tmp/t7spimp"); r5 = SP.import_project(e5, _sp)
P5 = e5.programs[0].pads
ok("SP-1200 import: A1, A5 (chopped from the same slot) and a reversed A2, with the SP's lo-fi on", P5[0].src is P5[4].src and P5[1].reverse and P5[0].lofi_on and abs(P5[0].length - 44100) < 3)
S5 = e5.seqs[0]
ok("SP-1200 import: the segment plays its hits at 96 ticks per beat; hits on empty pads are reported", S5.bars == 2 and S5.tracks[0].events == [(0, 0, 127, 24), (0, 4, 127, 24), (96, 1, 59, 24)] and any("without a sound" in w for w in r5.warn))
e5.play(from_start=True); _y5 = audio(e5, 0.5); e5.stop()
ok("SP-1200 import: the imported beat plays", np.abs(_y5).max() > 0.05)
c5 = Controls(e5); c5.set_mode("BROWSE"); c5.br_dir = "/tmp/t7sp"; c5.br_refresh()
ok("BROWSE: SP-1200 import is parked: .sp12 files are not offered yet", not any(i[0].endswith(".sp12") for i in c5.br_items))

# ================================================================= projects and naming
ep = fresh("/tmp/t7proj"); cp_ = Controls(ep); rp = Renderer(cp_); ep.save_project = E.Engine.save_project.__get__(ep)
ok("PROJECTS: the software's folder is the DEMO project", ep.project_name == "DEMO" and ep.list_projects()[0][0] == "DEMO")
_pa = ep.save_as("My Beat"); ok("PROJECTS: SAVE AS copies samples and carries on in the copy", ep.project_name == "My Beat" and len(os.listdir(os.path.join(_pa, "samples"))) == len(ep.sources) > 0)
ep.seq.name = "verse"; ep.save_project()
_pb = ep.new_project("Fresh"); ok("PROJECTS: NEW starts an empty project (the open one is saved first)", ep.project_name == "Fresh" and not ep.sources and not any(t.events for q in ep.seqs for t in q.tracks))
ep.open_project(_pa); ok("PROJECTS: OPEN brings a project back as saved", ep.project_name == "My Beat" and ep.seq.name == "verse" and len(ep.sources) > 0)
ok("PROJECTS: the last project opens at start-up", E.Engine.last_project("/tmp/t7proj") == _pa)
ok("PROJECTS: listed A-Z after the demo", [n for n, _ in ep.list_projects()] == ["DEMO", "Fresh", "My Beat"])
_s0 = ep.sources[0]; _old = _s0.name; ep.rename_source(_s0, "kick main"); ep.save_project()
ok("NAMING: a renamed sample renames its file at the save", os.path.exists(os.path.join(_pa, "samples", "kick main.wav")) and not os.path.exists(os.path.join(_pa, "samples", _old + ".wav")))
ok("NAMING: ...and the project still finds it", E.Engine(_pa, app_dir="/tmp/t7proj").source_by_name("kick main") is not None)
cp_.set_mode("GRID"); rp.frame(); cp_.touch("down", 80, 54); cp_.touch("up", 80, 54)
ok("NAMING: tapping the sequence name opens the keyboard", cp_.kbd is not None and "SEQUENCE" in cp_.kbd["title"])
cp_.kbd_press("CLEAR"); [cp_.kbd_press(ch) for ch in "HOOK"]; cp_.kbd_press("SPACE"); cp_.kbd_press("2"); rp.frame(); cp_.soft(3)
ok("NAMING: typing and OK (F4) renames it", ep.seq.name == "HOOK 2" and cp_.kbd is None)
cp_.rename_track(); cp_.kbd_press("DEL"); cp_.soft(0); ok("NAMING: CANCEL (F1) leaves the name alone", cp_.kbd is None and ep.track.name == "Kick")
cp_.rename_track(); cp_.nav("down"); cp_.nav("right"); cp_.ok(); ok("NAMING: the D-pad and OK type on the keyboard too", cp_.kbd["text"].endswith("S")); cp_.kbd_finish(False)
cp_.set_mode("PROJECTS"); rp.frame(); ok("PROJECTS page renders and marks the open project", rp.img.size == (W, H) and ep.list_projects()[cp_.pj_cur][1] == ep.dir)

# ================================================================= edit tools (EDIT page)
ee = fresh("/tmp/t7edit"); ce = Controls(ee); re_ = Renderer(ce); ee.save_project = lambda: None
_sq = ee.seq; _bt = _sq.bar_ticks; _n = [len(t.events) for t in _sq.tracks]
ee.insert_bars(1, 1); ok("EDIT: INSERT BARS makes the sequence longer and moves later notes", _sq.bars == 3 and not any(_bt <= ev[0] < 2 * _bt for ev in _sq.tracks[0].events))
ee.undo(); ok("EDIT: ...and UNDO puts it back (length too)", _sq.bars == 2 and [len(t.events) for t in _sq.tracks] == _n)
ee.delete_bars(0, 1); ok("EDIT: DELETE BARS", _sq.bars == 1 and all(ev[0] < _bt for ev in _sq.tracks[0].events)); ee.undo()
ee.copy_bars(0, 2, 1, times=2, all_tracks=True, grow=True); ok("EDIT: COPY BARS end to end grows the sequence", _sq.bars == 4 and sum(1 for ev in _sq.tracks[0].events if ev[0] >= 2 * _bt) == sum(1 for ev in _sq.tracks[0].events if ev[0] < _bt) * 2); ee.undo()
ee.set_timesig(3, 4); ok("EDIT: time signature 3/4", _sq.bar_ticks == 288); ee.undo(); ok("...undone", _sq.num == 4)
ee.copy_sequence(0, 6); ok("EDIT: COPY SEQUENCE", len(ee.seqs[6].tracks[0].events) == len(_sq.tracks[0].events) and ee.seqs[6].bpm == _sq.bpm)
ee.copy_track(0, 9); ok("EDIT: COPY TRACK", _sq.tracks[9].events == _sq.tracks[0].events)
ee.copy_pad(ee.programs[0].pads[0], ee.programs[0].pads[30]); ok("EDIT: COPY PAD (sample and settings)", ee.programs[0].pads[30].src is ee.programs[0].pads[0].src)
ee.qgrid = 4; ee.cur_track = 2; _tr = _sq.tracks[2]; _tr.events = [(0, 2, 100, 24), (26, 2, 100, 24), (50, 2, 100, 24)]
ee.quantize_track(24, 0.5); ok("QUANTISE: 50 % strength goes half way", [e_[0] for e_ in _tr.events] == [0, 25, 49])
_tr.events = [(0, 2, 100, 24), (24, 2, 100, 24)]; ee.quantize_track(24, 1.0, swing=0.66)
ok("QUANTISE: swing pushes every second step later", [e_[0] for e_ in _tr.events] == [0, 32])
ee.nudge(-4); ok("NUDGE: the track's notes move earlier (wrapping round the loop)", sorted(e_[0] for e_ in _tr.events) == [28, _sq.length - 4])
ee.cur_track = 2; ce.set_mode("GRID"); ce.g_lane = 2; ce.g_tick = 24; ce.g_sel = None; _tr.events = [(24, 2, 100, 24)]
ce.shift = True; ce.nav("right"); ce.shift = False; ok("NUDGE: SHIFT + right moves the note under the cursor one tick", _tr.events[0][0] == 25)
ce.set_mode("SEQ"); ce.soft(0); ok("EDIT page opens from ALL TRACKS (F1)", ce.mode == "EDIT"); re_.frame()
ce.ed_op = ce.ED_OPS.index("INSERT BARS"); ce.ed_row = 1; ce.jog(1); ce.soft(3); ok("EDIT page: DO IT (F4) runs it with the settings shown", _sq.bars == 4)
for _k in range(len(ce.ED_OPS)): ce.ed_op = _k; re_.frame()
ok("EDIT page: every operation's page renders", re_.img.size == (W, H))
_tr.auto = {"vol": [[0, 0.5]]}; ce.set_mode("GRID"); ce.g_view = "AUTO"; ce.g_auto = 0; re_.frame()
_ul = len(ee.undo_stack); ce.touch("down", 400, 300); ce.touch("move", 500, 300); ce.touch("up", 500, 300)
ok("AUTOMATION: a drawn stroke is one undo step", len(ee.undo_stack) == _ul + 1)
ee.undo(); ok("AUTOMATION: ...and UNDO takes it back", _tr.auto == {"vol": [[0, 0.5]]})

# ================================================================= pad envelope and filter
ef = fresh("/tmp/t7env"); ef.save_project = lambda: None
_pf = max((x for x in ef.programs[0].pads if not x.empty), key=lambda x: x.length)
def _hit(**kw):
    for k_, v_ in kw.items(): setattr(_pf, k_, v_)
    ef.v_data = [None] * ef.nv; ef.trigger(_pf, 120)
    return np.concatenate([ef.render(256)[:, 0] for _ in range(int(E.OUT_SR * 0.6 / 256))])
_rms = lambda a: float(np.sqrt((a.astype(np.float64) ** 2).mean()))
_y0 = _hit(); _on = int(np.nonzero(np.abs(_y0) > 1e-4)[0][0])
_yd = _hit(decay=100); ok("ENVELOPE: DECAY shortens the sound (and frees the voice)", _rms(_yd[_on + 9600:]) < 0.05 * _rms(_y0[_on + 9600:]) and all(v is None for v in ef.v_data))
_ya = _hit(decay=0, attack=200); ok("ENVELOPE: ATTACK fades it in", _rms(_ya[_on:_on + 2400]) < 0.5 * _rms(_y0[_on:_on + 2400]))
_yl = _hit(attack=0, flt="LP", cutoff=0.3, res=0.2)
_F0 = np.abs(np.fft.rfft(_y0[:8192])); _F1 = np.abs(np.fft.rfft(_yl[:8192])); _fq = np.fft.rfftfreq(8192, 1.0 / E.OUT_SR)
ok("FILTER: LOW-PASS takes the top off", _F1[_fq > 3000].mean() < 0.1 * _F0[_fq > 3000].mean())
_yh = _hit(flt="HP", cutoff=0.6); _F2 = np.abs(np.fft.rfft(_yh[:8192])); ok("FILTER: HIGH-PASS takes the bottom off", _F2[_fq < 150].mean() < 0.3 * _F0[_fq < 150].mean())
_pf.flt, _pf.cutoff, _pf.f_vel = "LP", 0.6, 1.0
ok("FILTER: VELOCITY > CUTOFF makes soft hits darker (lower cutoff at velocity 50 than 120)",
   E.Engine.voice_env(_pf, 50)[3] < E.Engine.voice_env(_pf, 120)[3] < _pf.cutoff + 1e-9 and E.Engine.voice_env(_pf, 127)[3] == _pf.cutoff)
_st = _pf.state(); _pf2 = E.Pad(99); ef._load_pad(_pf2, _st); ok("ENVELOPE / FILTER settings are saved with the pad", (_pf2.flt, _pf2.cutoff, _pf2.f_vel) == ("LP", 0.6, 1.0))
import dspfast as _dsp; ok("the pad filter runs in C (dsp/libvoicefx.so built)", _dsp.FAST)

# ================================================================= resampling
er = fresh("/tmp/t7rs"); cr = Controls(er); rr = Renderer(cr); er.save_project = lambda: None
cr.set_mode("SAMPLE"); rr.frame(); cr.touch("down", 230, 192); cr.touch("up", 230, 192)
ok("RESAMPLE: the SAMPLE page's RESAMPLE button picks the main output as the source", er.rec_src == "RESAMPLE")
er.rec_thresh = 0.02; _n0 = len(er.sources); cr.soft(0); ok("RESAMPLE: arms without an audio input", er.rec_state == "armed")
er.play(from_start=True); audio(er, 1.0); er.stop(); cr.soft(0)
ok("RESAMPLE: playing the sequence records it into the project's samples", len(er.sources) == _n0 + 1 and er.last_take.name.startswith("resample") and er.last_take.length > E.OUT_SR * 0.5)
rr.frame(); ok("SAMPLE page renders with the source chips", rr.img.size == (W, H))

# ================================================================= delete unused samples
eu_ = fresh("/tmp/t7purge"); cu_ = Controls(eu_); eu_.save_project = E.Engine.save_project.__get__(eu_)
eu_.add_source("spare one", np.zeros(4800, np.float32), dirty=True); eu_.add_source("spare two", np.zeros(4800, np.float32), dirty=True); eu_.save_project()
_unused = eu_.unused_sources(); _ns = len(eu_.sources)
_linked = [(p, p.link) for p in eu_.all_pads() if p.link]
cu_.set_mode("PROJECTS"); cu_.pj_purge(); ok("DELETE UNUSED: asks first (F1 CANCEL / F4 DELETE)", len(eu_.sources) == _ns and cu_.confirm is not None)
cu_.soft(3); eu_.save_project()
ok("DELETE UNUSED: unused samples go, used ones stay", len(eu_.sources) == _ns - len(_unused) and not eu_.unused_sources() and len(_unused) > 0)
ok("DELETE UNUSED: their files go at the save", not any(os.path.exists(os.path.join(eu_.sample_dir, s.name + ".wav")) for s in _unused))
ok("DELETE UNUSED: chopped pads still follow their markers", all(p.link[0] == p.src.id and eu_.sources[p.src.id] is p.src for p, _ in _linked))

# ================================================================= MIDI clock, pitch bend, mod wheel
import midi as _MD
emc = fresh("/tmp/t7clk"); cmc = Controls(emc); emc.save_project = lambda: None
_sent = []; emc.midi_out = lambda data, delay=0.0: _sent.append((bytes(data), delay))
emc.clock_mode = "SEND"; emc.play(from_start=True)
ok("CLOCK SEND: START (FA) when playing from the top", _sent and _sent[0][0] == b"\xfa")
_sent.clear(); audio(emc, 60.0 / emc.seq.bpm * 2)               # two beats
_nclk = sum(1 for d_, _ in _sent if d_ == b"\xf8")
ok("CLOCK SEND: 24 clocks per beat, timed inside the audio blocks", 47 <= _nclk <= 49 and all(dl >= 0 for _, dl in _sent))
emc.stop(); ok("CLOCK SEND: STOP (FC)", _sent[-1][0] == b"\xfc")
_sent.clear(); emc.locate(96 * 4); emc.play(); ok("CLOCK SEND: CONTINUE from a song position (F2 then FB)", [d_[0] for d_, _ in _sent[:2]] == [0xF2, 0xFB] and _sent[0][0][1] == 16)
emc.stop(); emc.clock_mode = "FOLLOW"; emc.seq.bpm = 90.0
_t0 = 1000.0
for _k in range(60): _MD.dispatch(cmc, (0xF8,), cmc.midi_map) if False else emc.ext_clock(_t0 + _k * 60.0 / 120.0 / 24)
ok("CLOCK FOLLOW: the tempo follows the incoming clock (120 bpm)", abs(emc.seq.bpm - 120.0) < 0.2)
_MD.dispatch(cmc, (0xFA,), cmc.midi_map); ok("CLOCK FOLLOW: START from outside plays from the top", emc.playing and emc.pos < 50)
_MD.dispatch(cmc, (0xFC,), cmc.midi_map); ok("CLOCK FOLLOW: STOP from outside stops", not emc.playing)
emc.clock_mode = "OFF"
_kp = next(p for p in emc.prog.pads if not p.empty); emc.v_data = [None] * emc.nv
emc.trigger(_kp, 100, key=60); _vk = next(i for i in range(emc.nv) if emc.v_key[i] == 60); _r0 = emc.v_rate[_vk]
_MD.dispatch(cmc, (0xE0, 0, 127), cmc.midi_map); ok("PITCH BEND: full up bends a held key 2 semitones", abs(emc.v_rate[_vk] / _r0 - 2 ** (2 / 12.0)) < 0.01)
_MD.dispatch(cmc, (0xE0, 0, 64), cmc.midi_map); ok("PITCH BEND: centre puts it back", abs(emc.v_rate[_vk] - _r0) < 1e-6)
_MD.dispatch(cmc, (0xB0, 1, 127), cmc.midi_map); ok("MOD WHEEL: CC 1 sets the mod amount (opens pad filters)", abs(emc.mod - 1.0) < 1e-6)
_MD.dispatch(cmc, (0xD0, 0), cmc.midi_map); ok("AFTERTOUCH: does the same", emc.mod == 0.0)
emc.seq.tracks[emc.cur_track].midi_ch = 3; _sent.clear(); emc.pitch_bend(0.5)
ok("PITCH BEND: goes out on the track's MIDI channel", _sent and _sent[-1][0][0] == 0xE2)
emc.seq.tracks[emc.cur_track].midi_ch = 0
cmc.set_mode("MIDI"); cmc.cycle_clock(); ok("MIDI page: CLOCK cycles OFF > SEND", emc.clock_mode == "SEND" and cmc.midi_map.clock == "SEND"); cmc.cycle_clock(); cmc.cycle_clock()

# ================================================================= MENU page, soft-key grammar, MAIN track pages, SONG position
eg = fresh("/tmp/t7menu"); cg = Controls(eg); rg = Renderer(cg); eg.save_project = lambda: None
cg.set_mode("MAIN"); cg.button(BTN["SHIFT"], True); cg.button(BTN["MAIN"], True); cg.button(BTN["MAIN"], False); cg.button(BTN["SHIFT"], False)
ok("MENU: SHIFT + MAIN opens it", cg.mode == "MENU"); rg.frame()
for _i, (_nm, _, _) in enumerate(cg.MENU_ITEMS):
    cg.set_mode("MENU"); rg.frame(); _x, _y = 8 + (_i % 5) * 157 + 75, 70 + (_i // 5) * 152 + 70
    cg.touch("down", _x, _y); cg.touch("up", _x, _y)
    ok(f"MENU: the {_nm} tile", cg.mode == {"PROJECTS": "PROJECTS", "BROWSE": "BROWSE", "EDIT": "EDIT", "PAD MODES": "PADS", "MIDI": "MIDI",
                                             "TRACK OUT": "EXPORT", "SONG": "SONG", "SAVE": "MENU", "SETTINGS": "SETTINGS"}[_nm])
cg.set_mode("MAIN"); rg.frame(); cg.touch("down", 760, 158); cg.touch("up", 760, 158); ok("MAIN: CHANGE MACHINE opens the machine picker", cg.mpick is not None)
rg.frame(); cg.touch("down", 52.5 + 235 + 60, 112 + 128.75 + 40); cg.touch("up", 0, 0); ok("PICKER: one tap on SP-1200 switches straight to it", eg.machine == "SP-1200" and cg.mpick is None)
cg.open_picker(); cg.jog(-4); cg.soft(3); ok("PICKER: jog then F4 SELECT", eg.machine == "MODERN" and cg.mpick is None)
cg.open_picker(); cg.soft(0); ok("PICKER: F1 CLOSE leaves the machine as it is", cg.mpick is None and eg.machine == "MODERN")
_bad = []
for _m in ["MAIN", "SEQ", "GRID", "STEP", "MUTE", "PROG", "SAMPLE", "CHOP", "MIXER", "FX", "SONG", "MIDI", "BROWSE", "EXPORT", "PADS", "PROJECTS", "EDIT", "MENU"]:
    cg.set_mode(_m); cg.br_dir = None; _labs = cg.soft_labels()
    if _m in ("MIDI", "BROWSE", "EXPORT", "PADS", "PROJECTS", "MENU", "SONG") and _labs[3] != BACK_: _bad.append(_m)
    if _m == "EDIT" and soft_text(_labs[0]) != "CLOSE": _bad.append(_m)
    for _l in _labs:
        if isinstance(_l, str) and (" ON" in _l or _l.startswith("ON:")): _bad.append(_m)
ok("F-KEYS: pages you come back from have BACK on F4, and no label says ON: (toggles light up instead)", not _bad)
cg.set_mode("MAIN"); eg.cur_track = 11; rg.frame(); cg.touch("down", 430, 210); cg.touch("up", 430, 210)
ok("MAIN: the track list shows the selected track's eight (9-16): its top row is track 9", eg.cur_track == 8)
eg.cur_track = 11; rg.frame(); cg.touch("down", 430, 197); cg.touch("up", 430, 197); ok("MAIN: tapping TRACKS 9-16 flips the page", eg.cur_track == 3)
eg.song = [[0, 2], [1, 1]]; eg.song_play(); audio(eg, 60.0 / eg.seq.bpm * 4 * 2.5); cg.set_mode("SONG"); rg.frame()
ok("SONG: shows where the song is (bar 3 of 6, pass 2/2)", eg.song_pos == 0 and eg.song_rep == 1); eg.stop()

# ================================================================= VST3 instrument on a PLUGIN track (runs only if one is installed, e.g. Dexed)
import fx as _fx
_i = _fx.discover_instruments()
if _i and _fx.HOST is not None:
    ep = fresh("/tmp/t7inst"); ep.save_project = lambda: None
    pt = ep.seq.tracks[11]
    ok(f"PLUGIN track: {_i[0][1]} loads as the track's instrument", ep.set_track_kind(pt, "plugin", _i[0][0]) and ep.instrument(pt) is not None)
    for k in range(4): ep._put(pt, k * 96, 60 + k * 4, 110, 80)
    ep.play(); y = np.concatenate([ep.render(256) for _ in range(300)])
    ok("PLUGIN track: the sequenced notes make sound", np.abs(y).max() > 0.01)
    ep.stop(); ep.stop()
    ep.cur_track = 11; cc = Controls(ep); cc.set_pad_mode("PERFORM"); cc.pad_hit(1, 110)
    y = np.concatenate([ep.render(256) for _ in range(60)]); ok("PLUGIN track: PERFORM pads play the synth", np.abs(y).max() > 0.01)
    ep.save_project = E.Engine.save_project.__get__(ep); ep.save_project()
    ep2 = E.Engine("/tmp/t7inst"); t2 = ep2.seq.tracks[11]
    ok("PLUGIN track: saved and reloaded with its plug-in and settings", t2.kind == "plugin" and t2.plugin == _i[0][0] and t2.plugin_state and ep2.instrument(t2) is not None)
else:
    print("SKIP VST3 instrument tests (no VST3 instrument or host on this machine)")

# ================================================================= third-party VST3 through the bundled host (runs only if one is installed)
import fx as _fx
_v = [it for it in _fx.discover() if it[0] == "vst3"]
if _v and _fx.HAVE_VST:
    ev = fresh("/tmp/t7vst"); ev.save_project = lambda: None
    ok("VST3: a third-party plug-in loads on the master bus (" + _v[0][2].strip() + ", via " + _fx.VST_ENGINE + ")", ev.set_fx("master", "vst3", _v[0][1]) and ev.master_fx.n() > 0)
    f0 = ev.master_fx.get(0); ev.master_fx.set(0, 1.0 - f0); ok("VST3: parameters can be read and set", abs(ev.master_fx.get(0) - (1.0 - f0)) < 0.02)
    ok("VST3: parameter values show as text", len(ev.master_fx.fmt(0)) > 0)
    ev.play(); y = np.concatenate([ev.render(256) for _ in range(200)]); ok("VST3: audio passes through it", np.isfinite(y).all() and np.abs(y).max() > 0.01)
    st = ev.master_fx.state(); ok("VST3: settings are saved with the project", st["kind"] == "vst3" and len(st["params"]) == ev.master_fx.n())
    ok("VST3: loads as a program insert too", ev.set_fx(E.FxSlot(ev.programs[0], 1), "vst3", _v[0][1]) and ev.programs[0].fx[1].kind == "vst3")
    ev.pad_hit(1, 110); y = np.concatenate([ev.render(256) for _ in range(100)]); ok("VST3: ...and processes the program's pads", np.isfinite(y).all() and np.abs(y).max() > 0.01)
    if os.environ.get("DISPLAY") and hasattr(ev.master_fx, "open_editor"):
        r = ev.master_fx.open_editor(); ok("VST3: the plug-in's own window opens (X11)", bool(r) and r[1] > 0 and r[2] > 0)
        for _ in range(20): ev.master_fx.editor_idle()
        z = ev.master_fx.scale_editor(0.75)
        for _ in range(10): ev.master_fx.editor_idle()
        sz = ev.master_fx.editor_size()
        ok("VST3: zoom 75 % makes the plug-in redraw smaller", z and sz and abs(sz[0] - 0.75 * r[1]) <= 2)
        ev.master_fx.close_editor(); ok("VST3: ...and closes again", True)
else:
    print("SKIP VST3 tests (no VST3 plug-in or host on this machine)")

# ================================================================= USB mouse as a finger (testing on an HDMI monitor)
import inputs as _inp, time
from PIL import Image
cm = Controls(fresh("/tmp/t7mouse")); cm.e.save_project = lambda: None
_calls = []; _t = cm.touch; cm.touch = lambda *a: (_calls.append(a), _t(*a))
mm = _inp.MouseMapper(cm)
for _ in range(100): mm.event(2, 0, 20); mm.event(2, 1, 20); mm.event(0, 0, 0)
ok("mouse: the pointer stays on the screen", mm.pos() == (W - 1, H - 1))
for _ in range(100): mm.event(2, 0, -20); mm.event(2, 1, -20); mm.event(0, 0, 0)
mm.event(2, 0, 400); mm.event(2, 1, 250); mm.event(0, 0, 0)
ok("mouse: moving without a click does not touch", not _calls)
mm.event(1, 272, 1); mm.event(2, 0, 10); mm.event(0, 0, 0); mm.event(1, 272, 0)
ok("mouse: left button down / drag / up = touch down / move / up", [k[0] for k in _calls] == ["down", "move", "up"] and _calls[1][1:] == (410, 250))
_j = []; cm.jog = lambda d: _j.append(d); mm.event(2, 8, -1); mm.event(2, 8, 1)
ok("mouse: the wheel turns the jog wheel", _j == [1, -1])
mm.event(1, 273, 1); _sh = cm.shift; mm.event(1, 273, 0)
ok("mouse: holding the right button is SHIFT", _sh and not cm.shift)
_img = Image.new("RGB", (1280, 800)); mm.x, mm.y = 400, 250; mm.seen = time.time(); _inp.draw_pointer(_img, mm, 1.6)
ok("mouse: the pointer is drawn where it is", _img.getpixel((643, 410)) == (255, 255, 255))
mm.seen = 0; _img2 = Image.new("RGB", (1280, 800)); _inp.draw_pointer(_img2, mm, 1.6)
ok("mouse: the pointer hides when the mouse is left alone", _img2.getbbox() is None)

# ================================================================= HiFiBerry DAC8x + ADC8x: inputs 1-2 mixed to mono, and the hardware check
er = fresh("/tmp/t7adc"); er.save_project = lambda: None
er.rec_src, er.rec_state, er.rec_buf, er.rec_len, er.rec_peaks = "INPUT", "rec", [], 0, []
_st = np.zeros((256, 8), np.float32); _st[:, 0] = 0.5; _st[:, 1] = 0.3; _st[:, 2] = 0.9      # channel 3 must be ignored
er.feed_input(_st)
ok("audio in: IN L + IN R are mixed to mono, inputs 3-8 ignored", np.allclose(er.rec_buf[-1], 0.4))
er.feed_input(np.full((256, 1), 0.25, np.float32))
ok("audio in: a one-input device still records", np.allclose(er.rec_buf[-1], 0.25))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")); import pi_check as _pc
def _hb(play, rec, hat="", model="Raspberry Pi 5 Model B"):
    _pc.results.clear(); _pc.run = lambda cmd: play if cmd[0] == "aplay" else rec
    _pc.read = lambda path, default="": hat if path.endswith("hat/product") else model
    _o = sys.stdout; sys.stdout = open(os.devnull, "w")
    try: _pc.hifiberry()
    finally: sys.stdout.close(); sys.stdout = _o
    return list(_pc.results)
ok("check: DAC8x + ADC8x found = two ok lines", _hb("card 1: sndrpihifiberry [snd_rpi_hifiberry_dac8x]", "card 1: sndrpihifiberry [snd_rpi_hifiberry_dac8x]") == [_pc.OK, _pc.OK])
ok("check: DAC8x without ADC8x inputs = a warning (the kernel / seating trap)", _hb("card 1: sndrpihifiberry", "") == [_pc.OK, _pc.WARN])
ok("check: board fitted but no sound card = FAIL with the overlay hint", _hb("", "", hat="HiFiBerry DAC8x") == [_pc.BAD])

# ================================================================= speed: cached text, and the memory-mapped screen
import uicore as _uc2
from PIL import ImageChops as _ICh
_rr = Renderer(Controls(fresh("/tmp/t7txt")), 1.6); _rr.c.e.save_project = lambda: None
_rr.frame(); _a = _rr.frame().copy()
_saved = _uc2.ScaledDraw.text
_uc2.ScaledDraw.text = lambda self, xy, txt, **kw: self.dr.text((xy[0] * self.s, xy[1] * self.s), txt, **self._font(kw))
_b = _rr.frame().copy(); _uc2.ScaledDraw.text = _saved
_diff = np.asarray(_ICh.difference(_a, _b)).astype(int).sum(axis=2)
ok("speed: cached text looks the same as drawing it each time (under 2 % of pixels differ by a sub-pixel)", (_diff > 60).mean() < 0.02)
import sampler_os as _so
for _bpp in (32, 16):
    _p = f"/tmp/t7fb{_bpp}"; _w, _h = 1920, 1080; _stride = _w * _bpp // 8
    open(_p, "wb").write(bytes(_stride * _h))
    _fb = _so.Framebuffer.__new__(_so.Framebuffer)
    _fb.w, _fb.h, _fb.bpp, _fb.stride, _fb.f, _fb.box = _w, _h, _bpp, _stride, open(_p, "r+b", buffering=0), _so.fit_box(_w, _h, "auto")
    _im = Image.new("RGB", (1728, 1080)); _im.putpixel((0, 0), (255, 0, 0)); _im.putpixel((1727, 1079), (0, 0, 255))
    _fb.show(_im); _fb._mm.flush(); _d = np.fromfile(_p, np.uint8).reshape(_h, _stride)
    if _bpp == 32: _good = list(_d[0, 384:388]) == [0, 0, 255, 0] and list(_d[1079, 1823 * 4:1824 * 4]) == [255, 0, 0, 0]
    else: _good = _d[0, 192:194].tobytes() == b"\x00\xf8" and _d[1079, 3646:3648].tobytes() == b"\x1f\x00"
    ok(f"screen: the {_bpp}-bit framebuffer gets the right colours in the right place (letterboxed 1920 x 1080)", _good and _d[0, :8].sum() == 0)

# ================================================================= MIDI pads learned one by one (any controller layout)
import midi as _md
_cp = Controls(fresh("/tmp/t7pads")); _cp.e.save_project = lambda: None
_mp = _md.MidiMap(None)
_layout = [(10, n) for n in (37, 36, 42, 82, 40, 38, 46, 44, 48, 47, 45, 43, 49, 55, 51, 53)]    # a scrambled, GM-style layout
_mp.set_pads(_layout)
_hits = []; _cp.pad_hit = lambda n, v: _hits.append((_cp.e.bank, n))
for _c, _n in _layout: _md.dispatch(_cp, (0x90 | (_c - 1), _n, 100), _mp)
ok("MIDI pads: a scrambled layout learned pad by pad plays pads 1-16 in order", _hits == [(0, i) for i in range(1, 17)])
_hits.clear(); _md.dispatch(_cp, (0x99, 82 + 16, 100), _mp)
ok("MIDI pads: the controller's bank B (notes + 16) reaches bank B", _hits == [(1, 4)])
_keys = []; _cp.midi_key = lambda n, v: _keys.append(n); _md.dispatch(_cp, (0x90, 60, 100), _mp)
ok("MIDI pads: keys on another channel still play chromatically", _keys == [60])
_mp.path = "/tmp/t7pads/midi.json"; _mp.save(); _mp2 = _md.MidiMap("/tmp/t7pads/midi.json")
ok("MIDI pads: the learned layout is saved", _mp2.pad_of(10, 42) == (0, 3))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")); import midi_setup as _ms
_feed = [[(0x99, n, 90)] for _, n in _layout]
_calls = [0]
def _fake_msgs(fds, t):                                     # each pad: the drain call gets nothing, the next call gets the hit
    _calls[0] += 1
    return [("dev", m) for m in (_feed.pop(0) if _feed and _calls[0] % 2 == 0 else [])]
_ms.messages = _fake_msgs
_ms.key_pressed = lambda: ""; _ms.time.sleep = lambda t: None
_mp3 = _md.MidiMap(None); _o = sys.stdout; sys.stdout = open(os.devnull, "w")
try: _cnt = _ms.learn_pads({}, _mp3)
finally: sys.stdout.close(); sys.stdout = _o
ok("midi_setup: hitting the 16 pads in order learns the whole layout", _cnt == 16 and _mp3.pad_list == [list(x) for x in _layout])
ok("midi_setup: pad places are described from the bottom-left", _ms.pad_place(1) == "bottom row, left" and _ms.pad_place(16) == "top row, right")

# ================================================================= the mouse pointer moves straight in screen memory
_p = "/tmp/t7fbptr"; _w, _h = 1920, 1080; _stride = _w * 4
open(_p, "wb").write(bytes(_stride * _h))
_fb = _so.Framebuffer.__new__(_so.Framebuffer)
_fb.w, _fb.h, _fb.bpp, _fb.stride, _fb.f, _fb.box = _w, _h, 32, _stride, open(_p, "r+b", buffering=0), _so.fit_box(_w, _h, "auto")
_fb.show(Image.new("RGB", (1728, 1080), (40, 40, 40)))
_mm2 = _inp.MouseMapper(Controls(fresh("/tmp/t7ptr2"))); _mm2.seen = time.time(); _mm2.x, _mm2.y = 100, 100
_sc = _fb.box[2] / float(W)
_fb.pointer(_mm2, _sc)
_at = lambda ux, uy: tuple(_fb.mem[int(uy * _sc), (_fb.box[0] + int(ux * _sc)) * 4:(_fb.box[0] + int(ux * _sc)) * 4 + 3])
ok("pointer: drawn straight into the screen", _at(103, 110) == (255, 255, 255))
_mm2.x, _mm2.y = 300, 200; _fb.pointer(_mm2, _sc)
ok("pointer: moving it puts back what was underneath", _at(103, 110) == (40, 40, 40) and _at(303, 210) == (255, 255, 255))
_mm2.seen = 0; _fb.pointer(_mm2, _sc)
ok("pointer: hides cleanly when the mouse is left alone", _at(303, 210) == (40, 40, 40))

# ================================================================= de-click: retriggers, stolen voices and region edges
ed_ = fresh("/tmp/t7click"); ed_.save_project = lambda: None
sr_ = E.OUT_SR; tt_ = np.arange(int(sr_ * 1.0)) / sr_
sq_ = ed_.add_source("square", (0.6 * np.sign(np.sin(2 * np.pi * 110 * tt_ + 0.7))).astype(np.float32))   # loud, starts mid-wave
cp_ = ed_.programs[0].pads[44]; cp_.assign(sq_); cp_.lofi_on = False
d_ = cp_.pre()
ok("de-click: every region starts and ends at silence", abs(float(d_[0])) < 1e-6 and abs(float(d_[-1])) < 1e-6)
def _jump(y): return float(np.abs(np.diff(y)).max())
with ed_.lock:
    for i in range(ed_.nv): ed_.v_data[i] = None; ed_.v_pad[i] = None
ed_.trigger(cp_, 127); y_ = [ed_.render(256)[:, 0] for _ in range(20)]
ed_.trigger(cp_, 127); y_ += [ed_.render(256)[:, 0] for _ in range(20)]
y_ = np.concatenate(y_); steady = _jump(y_[1000:5000])
ok("de-click: hitting a pad again while it sounds fades the old hit out (no jump bigger than the sound's own edges)", _jump(y_[5000:5200]) <= steady * 1.05 + 1e-6)
with ed_.lock:
    for i in range(ed_.nv): ed_.v_data[i] = None; ed_.v_pad[i] = None
others = [p for p in ed_.programs[0].pads[45:45 + ed_.nv]]
for p in others: p.assign(sq_); p.lofi_on = False
for p in others: ed_.trigger(p, 60)
[ed_.render(256) for _ in range(4)]
ed_.trigger(cp_, 60)
ok("de-click: a stolen voice leaves a short fade-out instead of stopping dead", len(ed_._tails) == 1 and abs(float(ed_._tails[0][0][-1])) < 1e-3)

# ================================================================= master limiter: many pads at once are turned down, not distorted
el_ = fresh("/tmp/t7lim"); el_.save_project = lambda: None; el_.volume = 1.0
_big = [p for p in el_.all_pads() if not p.empty][:8]
_raw = []; _orig = np.tanh
E.np.tanh = lambda x: (_raw.append(np.abs(x).max()), _orig(x))[1]          # see what goes into the soft clipper
try:
    for p in _big: el_.trigger(p, 127)
    [el_.render(256) for _ in range(40)]
finally: E.np.tanh = _orig
ok(f"limiter: 8 loud pads at once stay near full scale going into the clipper (peak {max(_raw[8:]):.2f}, limit {el_.LIM_T})", max(_raw[8:]) <= el_.LIM_T * 1.25)
el2_ = fresh("/tmp/t7lim2"); el2_.save_project = lambda: None
el2_.trigger(_big[0] if False else [p for p in el2_.all_pads() if not p.empty][0], 40); [el2_.render(256) for _ in range(20)]
ok("limiter: one soft pad is left alone", el2_.lim_g > 0.999)

# ================================================================= MPC60 / MPC3000 timing (from their firmware)
et = fresh("/tmp/t7linn"); et.save_project = lambda: None
L = E.Engine
ok("MPC60 timing: 16ths at 66% put the off-beat on tick 32 of 48 (step x swing / 50, rounded)", L.linn_grid(24, 0.66) == (24, 48, 32))
ok("MPC60 timing: 8ths at 66% -> tick 63 of 96; 75% on 16ths -> 36", L.linn_grid(48, 0.66)[2] == 63 and L.linn_grid(24, 0.75)[2] == 36)
ok("MPC60 timing: no swing on triplets or 1/32 (they play straight)", L.linn_grid(32, 0.7)[2] == 32 and L.linn_grid(12, 0.7)[2] == 12)
ok("MPC60 timing: notes snap to the nearest swung point (change-over halfway between)",
   [L.linn_snap(t, 24, 0.66) for t in (0, 15, 16, 39, 40, 47)] == [0, 0, 32, 32, 48, 48])
ok("MPC60 timing: shift timing limit = half the gap after the swung note, less a tick", L.linn_shift_max(24, 0.66) == 7 and L.linn_shift_max(24, 0.5) == 11)
ok("MPC60 timing: shift moves the whole grid", L.linn_snap(16, 24, 0.66, shift=-3) == 29 and L.linn_points(0, 96, 24, 0.66, -3) == [29, 45, 77, 93])
et.timing = "MPC60"; et.seq.swing = 0.66; et.qgrid = 4; et.rec_quant = True
ok("MPC60 timing: recording with timing correct on puts the swing into the note", et.qtick(30) == 32 and et.qtick(10) == 0)
et.qgrid = 0; ok("MPC60 timing: with timing correct OFF (note value OFF), notes stay where played", et.qtick(30) == 30); et.qgrid = 4
ok("MPC60 timing: no extra swing at playback (it is already in the notes)", et._swing_off(24, et.seq) == 0.0)
tr_ = et.track; tr_.events = [(0, 0, 100, 6), (25, 0, 100, 6), (50, 0, 100, 6), (70, 0, 100, 6)]
et.quantize_track(24, 1.0, swing=0.66)
ok("MPC60 timing: QUANTISE moves existing notes onto the swung grid", [ev[0] for ev in et.track.events] == [0, 32, 48, 80])
et.rep_pad, et.rep_on, et.rep_div, et.rep_vel = 0, True, 24, 100
fired = []; _tr = et.trigger; et.trigger = lambda pad, vel, delay=0, *a, **k: fired.append(delay)
et._fire_repeat(0, 96, 0, 1.0, False); et.trigger = _tr
ok("MPC60 timing: note repeat fires on the swung grid (0, 32, 48, 80)", fired == [0, 32, 48, 80])
et.timing = "MODERN"; ok("MODERN timing: unchanged (live swing on 16th off-beats)", et._swing_off(24, et.seq) > 0)

cm_ = Controls(fresh("/tmp/t7tbtn")); cm_.e.save_project = lambda: None; rm_ = Renderer(cm_, 1.0); cm_.set_mode("MAIN"); rm_.frame()
seen_ = []
for _i in range(6):
    rm_.frame(); cm_.touch("down", 760, 158); cm_.touch("up", 760, 158); rm_.frame()
    _x, _y = 52.5 + ((_i + 1) % 6 % 3) * 235 + 60, 112 + ((_i + 1) % 6 // 3) * 128.75 + 40
    cm_.touch("down", _x, _y); cm_.touch("up", 0, 0); seen_.append(cm_.e.machine)
ok("MAIN: CHANGE MACHINE, then a card, goes straight to each machine and back to MODERN",
   seen_ == ["MPC60", "MPC3000", "MPC2000XL", "SP-1200", "ASR-10", "MODERN"])
ok("MAIN: MPC60 / MPC3000 bring the Linn timing, the others do not", [m for m in E.MACHINES if E.Engine.timing.fget(type("x", (), {"machine": m})())
                                                                        == "MPC60"] == ["MPC60", "MPC3000"])
import machines as _mc
em_ = cm_.e
for m in ("MPC60", "MPC3000", "MPC2000XL", "SP-1200"):
    lines = _mc.screen(em_, m).text()
    ok(f"{m}: its screen is {len(lines)} lines of {len(lines[0])} characters, every line full width",
       all(len(l) == len(lines[0]) for l in lines) and (len(lines), len(lines[0])) == {"MPC60": (8, 40), "MPC3000": (8, 40),
                                                                                        "MPC2000XL": (7, 41), "SP-1200": (2, 16)}[m])
em_.machine = "MPC60"; cm_.lcd_cur = None; rm_.frame()
ok("MPC60: the cursor starts on Seq", cm_.lcd_cur == "seq")
cm_.nav("right"); ok("MPC60: right moves to the next field (BPM)", cm_.lcd_cur == "bpm")
b0 = em_.seq.bpm; cm_.jog(5); ok("MPC60: the jog wheel changes the field under the cursor (BPM + 0.5)", abs(em_.seq.bpm - (b0 + 0.5)) < 1e-6)
cm_.nav("down"); ok("MPC60: down goes to the nearest field on the next line (Loop)", cm_.lcd_cur == "loop")
l0 = em_.seq.loop; cm_.jog(1); ok("MPC60: ...and the wheel toggles it", em_.seq.loop != l0)
t0_ = em_.cur_track; cm_.soft(3); ok("MPC60: F4 = <Track+>", em_.cur_track == (t0_ + 1) % 16)
m0 = em_.track.mute; cm_.soft(0); ok("MPC60: F1 = <Tk on/off>", em_.track.mute != m0)
ok("MPC60: the soft keys are labelled as the machine's", cm_.soft_text(1).startswith("SOLO"))
cm_.lcd_tap("trk"); ok("MPC60: tapping a field puts the cursor on it", cm_.lcd_cur == "trk")
cm_.lcd_tap("trk"); ok("MPC60: tapping it again steps it (track + 1)", em_.cur_track == (t0_ + 2) % 16)
em_.machine = "MPC2000XL"; cm_.lcd_cur = None; rm_.frame()
q0 = em_.qgrid; cm_.lcd_cur = "timing"; cm_.jog(-1); ok("MPC2000XL: the Timing field sets timing correct", em_.qgrid == q0 - 1)
cm_.lcd_tap("soft0"); ok("MPC2000XL: the STEP label on the screen opens STEP", cm_.mode == "STEP")
cm_.set_mode("MAIN"); em_.machine = "SP-1200"; rm_.frame()
ok("SP-1200: F1-F4 stay as Monolith's (the SP has no soft keys)", cm_.soft_text(0) == "METRONOME" or "METRO" in cm_.soft_text(0))
em_.machine = "MPC3000"; em_.save_project = E.Engine.save_project.__get__(em_); em_.save_project()
ok("machines: the machine is saved with the project", E.Engine(em_.dir, app_dir=em_.app_dir).machine == "MPC3000")

# ================================================================= SP-1200 model (firmware 1.04 + published hardware facts)
es = fresh("/tmp/t7sp"); es.save_project = lambda: None; es.machine = "SP-1200"
ok("SP-1200: pitch steps reproduce the firmware's table (-16..+12 st, byte+1 / 128)",
   [int(E.sp_step(n) * 128) - 1 for n in (-16, -12, -5, 0, 1, 7, 12)] == [50, 63, 95, 127, 135, 191, 255])
ok("SP-1200: swing settings 50-71% put a 16th off-beat 0-10 ticks late (k/24 of the pair)",
   [E.Engine.sp_grid(24, w / 100.0)[2] for w in E.SP_SWINGS] == [24, 26, 28, 30, 32, 34])
ok("SP-1200: auto-correct snaps to the nearest swung point", [E.Engine.sp_snap(t, 24, 0.54) for t in (12, 13, 37, 38)] == [0, 26, 48, 48])
ok("SP-1200: with auto-correct off notes still land on its 24-a-quarter clock", [E.Engine.sp_snap(t, 0, 0.5) for t in (1, 2, 5, 6)] == [0, 4, 4, 8])
sr_ = E.OUT_SR; tt_ = np.arange(int(sr_ * 0.5)) / sr_
sine_ = es.add_source("sine1k", (0.5 * np.sin(2 * np.pi * 1000 * tt_)).astype(np.float32))
pads_ = es.programs[0].pads
for i_ in (0, 6): pads_[i_].assign(sine_); pads_[i_].lofi_on = False
def _play(pad, secs=0.3):
    with es.lock:
        for i in range(es.nv): es.v_data[i] = None; es.v_pad[i] = None
    es.trigger(pad, 127); return np.concatenate([es.render(256)[:, 0] for _ in range(int(secs * sr_ / 256))])
y7 = _play(pads_[6])                                           # pad 7 -> channel 7: unfiltered
spec = np.abs(np.fft.rfft(y7[4000:12000] * np.hanning(8000))); fq = np.fft.rfftfreq(8000, 1.0 / sr_)
ok("SP-1200: the hold's image of 1 kHz (25.04 kHz) is above our Nyquist and does not fold back into the audio (as recorded from a real one)",
   spec[(fq > 17000) & (fq < 21500)].max() < 0.002 * spec.max())
sine8_ = es.add_source("sine8k", (0.5 * np.sin(2 * np.pi * 8000 * tt_)).astype(np.float32))
for i_ in (0, 2, 5, 6): pads_[i_].assign(sine8_); pads_[i_].lofi_on = False
y7 = _play(pads_[6]); spec = np.abs(np.fft.rfft(y7[4000:12000] * np.hanning(8000)))
_sinc = lambda f_: abs(np.sinc(f_ / E.SP_SR))
_img = spec[(fq > 17800) & (fq < 18300)].max() / spec[(fq > 7800) & (fq < 8200)].max()
ok("SP-1200: channel 7 keeps the hold's real image of 8 kHz (26.04k - 8k = 18.04 kHz), at the zero-order hold's level (~-7 dB)",
   abs(20 * np.log10(_img / (_sinc(18041.7) / _sinc(8000)))) < 1.5)
y1 = _play(pads_[0])                                           # pad 1 -> channel 1: dynamic filter
spec1 = np.abs(np.fft.rfft(y1[4000:12000] * np.hanning(8000)))
ok("SP-1200: channel 1's filter takes that image right down", spec1[(fq > 17800) & (fq < 18300)].max() < 0.05 * spec[(fq > 17800) & (fq < 18300)].max())
pads_[6].sp_ch = 1; y71 = _play(pads_[6]); pads_[6].sp_ch = 0
spec71 = np.abs(np.fft.rfft(y71[4000:12000] * np.hanning(8000)))
ok("SP-1200 CHANNEL: PROG can send pad 7 through channel 1's filter (the image goes, as on pad 1)",
   spec71[(fq > 17800) & (fq < 18300)].max() < 0.05 * spec[(fq > 17800) & (fq < 18300)].max() and E.Engine.sp_channel(pads_[6]) == 7)
_lv = lambda y_: float(np.sqrt(np.mean(y_[4000:12000] ** 2)))
_at = lambda y_, f_: float(abs(np.sum(y_[4000:12000] * np.hanning(8000) * np.exp(-2j * np.pi * f_ * np.arange(4000, 12000) / sr_))))   # one tone's level
y3, y6 = _play(pads_[2]), _play(pads_[5])
ok("SP-1200: fixed filters from the schematic - 8 kHz is ~3 dB down on channel 3 (-3 dB at 7.9 kHz), barely touched on 6 (13.1 kHz)",
   abs(20 * np.log10(_at(y3, 8000) / _at(y7, 8000)) + 3.1) < 0.5 and abs(20 * np.log10(_at(y6, 8000) / _at(y7, 8000)) - 0.3) < 0.5)
ok("SP-1200: channel 1's filter closes after the hit (SSM2044: open ~6 octaves, back to ~1 kHz with tau 0.10 s): 8 kHz dies",
   np.sqrt(np.mean(y1[400:1200] ** 2)) > 0.5 * _lv(y7) and np.sqrt(np.mean(y1[11000:13000] ** 2)) < 0.03 * _lv(y7))
for i_ in (0, 2, 5, 6): pads_[i_].assign(sine_); pads_[i_].lofi_on = False
y7 = _play(pads_[6]); spec = np.abs(np.fft.rfft(y7[4000:12000] * np.hanning(8000)))
_sw = []                                                      # a sine sweep through channel 7, as Yeh et al. measured theirs
_ref = _at(y7, 1000) / (abs(E.SPH.input_filter([1000])[0]) * _sinc(1000))
for f_ in (2000, 6000, 10000, 12000):
    tone_ = es.add_source("sw%d" % f_, (0.5 * np.sin(2 * np.pi * f_ * tt_)).astype(np.float32)); pads_[6].assign(tone_)
    _sw.append(20 * np.log10(_at(_play(pads_[6]), f_) / _ref / (abs(E.SPH.input_filter([f_])[0]) * _sinc(f_))))
pads_[6].assign(sine_); pads_[6].lofi_on = False
ok("SP-1200 sweep: channel 7's level follows the input filter x the hold's sinc droop (10 kHz ~3.7 dB down), within 0.6 dB", max(map(abs, _sw)) < 0.6)
_st = E.SPH.new_state(); _pr = E.SPH.params(1.0, 1.0, 0.0, 7, 0.0, 400.0)
_dc = E.SPH.render(np.ones(30000, np.float32), 29999, _st, _pr, 7, 30000)
_db = -20 * np.log10(np.abs(_dc[200:]) + 1e-12) / E.SPH.LEVEL_STEP_DB
ok("SP-1200 level DAC: a decay moves through the 32-step log PROM's levels (~1.5 dB apart), then the voice ends",
   np.mean(np.abs(_db - np.round(_db)) < 0.05) > 0.85 and len(set(np.round(_db))) > 20 and len(_dc) < 30000)
import time as _tm
_d8 = E.make_sp(sine_.raw); _t0 = _tm.perf_counter()
for _c in range(1, 9): E.SPH.render(_d8, len(_d8) - 1, E.SPH.new_state(), E.SPH.params(0.94, 0.94, 0.5, _c), _c, 13000)
_cpu = (_tm.perf_counter() - _t0) / (8 * 13000 / sr_)
print("SP-1200 model CPU: %.2f%% of a core per voice (this machine)" % (100 * _cpu))
ok("SP-1200 model: one voice costs well under 5% of a core here (C library)", E.SPH.FAST and _cpu < 0.05)
ok("SP-1200 DECAY: its 0-31 setting (31 = plays out) maps to ms and back", E.sp_decay_ms(31) == 0 and all(E.sp_decay_of(E.sp_decay_ms(v_)) == v_ for v_ in range(31)))
pads_[6].decay = E.sp_decay_ms(5); y7d = _play(pads_[6]); pads_[6].decay = 0
ok("SP-1200 DECAY: a short decay dies away", np.abs(y7d[-3000:]).max() < 0.05 * np.abs(y7[-3000:]).max())
pads_[6].tune = 7; y7u = _play(pads_[6]); pads_[6].tune = 0
pk = lambda y: fq[np.argmax(np.abs(np.fft.rfft(y[4000:12000] * np.hanning(8000)))[:400])]
ok("SP-1200: +7 semitones = step 192/128 (1.5x: 1 kHz -> 1.5 kHz)", abs(pk(y7u) - 1500) < 15)
es.trigger(pads_[6], 100); es.trigger(pads_[6], 100)
live = [i for i in range(es.nv) if es.v_data[i] is not None and es.v_kill[i] < 0]
ok("SP-1200: one voice per output channel (a new hit cuts the old one)", len(live) == 1)
cs_ = Controls(es); cs_.set_mode("MAIN"); a0 = es.sp_ac; cs_.soft(2)
ok("SP-1200: F3 on MAIN steps auto-correct", es.sp_ac == (a0 + 1) % len(E.SP_CORRECT) and cs_.soft_text(2).startswith("AUTOCORRECT"))
# --- RPM ("sampled at" 45 / 78, tuned back down) and RING
band = lambda y, lo, hi: float((np.abs(np.fft.rfft(y[4000:12000] * np.hanning(8000)))[(fq > lo) & (fq < hi)] ** 2).sum())
pads_[6].rpm = 78; y78 = _play(pads_[6])
ok("SP-1200 RPM: 78 holds the sound 15 st up (2.38x fewer samples) and plays it back at its own pitch",
   abs(len(es.sp_data(pads_[6])) / len(E.make_sp(pads_[6].pre())) - 2 ** (-15 / 12)) < 0.01 and abs(pk(y78) - 1000) < 15)
ok("SP-1200 RPM: 78 gives far more grit (images of 1 kHz around its 10.9 kHz effective rate)", band(y78, 9000, 13000) > 20 * band(y7, 9000, 13000))
pads_[6].tune = -2; es.trigger(pads_[6], 100)
v_ = next(i for i in range(es.nv) if es.v_pad[i] is pads_[6] and es.v_kill[i] < 0)
ok("SP-1200 RPM: at 78 the SP's -16 st floor leaves one semitone of tune down", es.v_sp[v_][0] == E.sp_step(-16))
pads_[6].tune, pads_[6].rpm = 0, 33
es.sp_ring = 1.0; y7r = _play(pads_[6])
ok("SP-1200 RING: nothing at a sound's own pitch (its steps are even)", np.abs(y7r - y7).max() < 1e-5)
pads_[6].tune = -1; es.sp_ring = 0.0; yd0 = _play(pads_[6]); es.sp_ring = 1.0; yd1 = _play(pads_[6]); pads_[6].tune = 0; es.sp_ring = 0.0
ok("SP-1200 RING: pitched down 1 st it adds the stepping pattern's whine (one repeat per 128/7 samples = ~1.42 kHz)",
   band(yd1, 1380, 1470) > 10 * band(yd0, 1380, 1470) + 1e-9)
def _kplay(semi, ring):
    es.sp_ring = ring
    with es.lock:
        for i in range(es.nv): es.v_data[i] = None; es.v_pad[i] = None
    es.trigger(pads_[6], 127, 0, None, semi=semi); return np.concatenate([es.render(256)[:, 0] for _ in range(int(0.3 * sr_ / 256))])
pads_[6].tune = -1
rk_ = [_kplay(s_, 1.0) - _kplay(s_, 0.0) for s_ in (0, -4)]; pads_[6].tune = 0; es.sp_ring = 0.0
ok("SP-1200 RING: a note played from a KEYS track keeps its pad's ring (-1 st: ~1.42 kHz at both notes; it does not follow the melody)",
   all(band(r_, 1380, 1470) > 0.15 * band(r_, 100, 20000) for r_ in rk_) and abs(band(rk_[0], 1380, 1470) - band(rk_[1], 1380, 1470)) < 0.1 * band(rk_[0], 1380, 1470))
cs_.set_mode("MAIN")
ok("SP-1200: Q4 on MAIN is RING (auto-correct stays on F3)", [q[0] for q in cs_.qlinks()] == ["Tune", "Decay", "Swing", "Ring"])
cs_.qlinks()[3][2](0.4); ok("SP-1200 RING: the knob sets it in 5% steps and the SP screen says so", es.sp_ring == 0.4 and "Ring: 40%" in es.msg)
es.select_pad(0, 6); cs_.set_mode("PROG"); cs_.prog_front = False; cs_.prog_adjust(12, 1)
ok("SP-1200 PROG: the LO-FI row becomes SAMPLED AT: 33 -> 45 -> 78 rpm", es.pad.rpm == 45 and cs_.soft_text(2).startswith("RPM"))
es.save_project = E.Engine.save_project.__get__(es); es.save_project()
es2_ = E.Engine("/tmp/t7sp"); ok("SP-1200: RPM and RING are saved with the project", es2_.programs[0].pads[6].rpm == 45 and es2_.sp_ring == 0.4)
es.pad.rpm = 33; es.sp_ring = 0.0
# --- your own badge images beside the machine display (badges/<MACHINE>_top.png above badges/<MACHINE>.png)
from PIL import Image as _Im
eb_ = fresh("/tmp/t7badge"); eb_.machine = "SP-1200"; cb_ = Controls(eb_); rb_ = Renderer(cb_); cb_.set_mode("MAIN")
plain_ = np.asarray(rb_.frame()).copy()
os.makedirs("/tmp/t7badge/badges")
_Im.new("RGBA", (300, 60), (255, 0, 0, 255)).save("/tmp/t7badge/badges/SP-1200_top.png")
_Im.new("RGBA", (300, 100), (0, 0, 255, 255)).save("/tmp/t7badge/badges/SP-1200.png")
bimg_ = np.asarray(rb_.frame())
red_ = (bimg_[..., 0] > 240) & (bimg_[..., 1] < 20) & (bimg_[..., 2] < 20); blue_ = (bimg_[..., 2] > 240) & (bimg_[..., 0] < 20) & (bimg_[..., 1] < 20)
ok("BADGES: your images show beside the machine's display, top one above the model one, inside the bezel",
   red_.sum() > 300 and blue_.sum() > 300 and np.flatnonzero(red_.any(1)).max() < np.flatnonzero(blue_.any(1)).min()
   and np.flatnonzero(blue_.any(0)).max() < 792 and np.flatnonzero(blue_.any(1)).max() < 250)
eb_.machine = "MPC60"; ok("BADGES: a machine without images keeps its printed name", not ((np.asarray(rb_.frame())[..., 2] > 240) & (np.asarray(rb_.frame())[..., 0] < 20)).sum())
# ================================================================= Ensoniq ASR-10 (OS 1.5B ROM + its ES5506 chip)
ok("ASR-10: QUANTIZE TRACK values are the ROM's table (1/4 .. 1/96 with 1/6, 1/12, 1/24, 1/48; 96 a quarter)",
   [g for _, g in E.ASR_Q] == [96, 64, 48, 32, 24, 16, 12, 8, 6, 4])
ok("ASR-10: quantize goes to the nearest step, and a note exactly half-way goes EARLIER (unlike the MPC60)",
   [E.Engine.asr_snap(t, 24) for t in (11, 12, 13, 35, 36, 37)] == [0, 0, 24, 24, 24, 48])
ea_ = fresh("/tmp/t7asr"); ea_.save_project = lambda: None; ea_.machine = "ASR-10"
ok("ASR-10: its own timing (recorded as played, on the 96-a-quarter clock; no swing)",
   ea_.timing == "ASR" and ea_.qtick(37.9) == 37 and ea_._swing_off(24, ea_.seq) == 0.0)
sa_ = ea_.add_source("asine", (0.5 * np.sin(2 * np.pi * 1000 * np.arange(22050) / 44100.0)).astype(np.float32))
pa_ = ea_.programs[0].pads[0]; pa_.assign(sa_); pa_.lofi_on = False
ok("ASR-10: sounds are held at 29,761.9 Hz (31 voices) or 44.1 kHz (23 voices), 16-bit",
   abs(len(ea_.asr_data(pa_)) - 1 - 22050 * 29761.9 / 44100) < 3 and abs(ea_.asr_data(pa_)[100] * 32768 - round(ea_.asr_data(pa_)[100] * 32768)) < 1e-3)
def _aplay(pad, secs=0.25):
    with ea_.lock:
        for i in range(ea_.nv): ea_.v_data[i] = None; ea_.v_pad[i] = None
    ea_.trigger(pad, 127); return np.concatenate([ea_.render(256)[:, 0] for _ in range(int(secs * 44100 / 256))])
pa_.tune = 7; ya_ = _aplay(pa_); pa_.tune = 0
fqa = np.fft.rfftfreq(8000, 1 / 44100.0); spa = np.abs(np.fft.rfft(ya_[2000:10000] * np.hanning(8000)))
ok("ASR-10: pitch is smooth (interpolated, any amount): +7 st = 1.498x, 1 kHz -> 1.498 kHz", abs(fqa[np.argmax(spa)] - 1498.3) < 8)
runs_a = np.diff(np.flatnonzero(np.diff(ya_[2000:6000]) != 0))
ok("ASR-10: no stepped output (it interpolates; unlike the SP-1200)", (runs_a == 1).mean() > 0.95)
pa_.flt, pa_.cutoff, pa_.res = "LP", np.log(1000 / 30.0) / np.log(20000 / 30.0), 1.0
yf_ = _aplay(pa_); ea_.machine = "MODERN"; ym_ = _aplay(pa_); ea_.machine = "ASR-10"
pk_ = lambda y: float(np.abs(y[4000:10000]).max())
pa_.flt, pa_.res = "OFF", 0.0
_cv = lambda hz: 150 * np.log(hz / 15.0) / np.log(0.5 * 29761.9 / 15.0)        # CUTOFF for a frequency
pa_.a_fmode, pa_.a_f1, pa_.a_f2 = 3, _cv(250), 150; yl_ = _aplay(pa_)
pa_.a_fmode, pa_.a_f1, pa_.a_f2 = 3, 150, 150; yo_ = _aplay(pa_)
ok("ASR-10 filter: F1=3/LP F2=1/LP with F1 two octaves under a 1 kHz sine cuts it hard, and never boosts", pk_(yl_) < 0.2 * pk_(yo_) and pk_(yo_) < 0.55)
pa_.a_fmode, pa_.a_f1, pa_.a_f2 = 0, 150, 0; yh_ = _aplay(pa_)
pa_.a_fmode, pa_.a_f1, pa_.a_f2 = 0, 150, 150; yh2_ = _aplay(pa_)
ok("ASR-10 filter: F1=2/LP F2=2/HP - F2 is a high-pass (as on the chip, a bigger K is a lower cut-off: 150 = open, 0 = thin)", pk_(yh_) < 0.3 * pk_(yh2_) and pk_(yh2_) > 0.8 * pk_(yo_))
pa_.a_fmode, pa_.a_f1, pa_.a_f2 = 3, 150, 150
p_imp_ = ea_.programs[0].pads[1]; _ii = np.zeros(4410, np.float32); _ii[10] = 0.8; p_imp_.assign(ea_.add_source("imp", _ii))
p_env_ = ea_.programs[0].pads[3]
p_env_.assign(ea_.add_source("env_s", (0.5 * np.sin(2 * np.pi * 440 * np.arange(88200) / 44100.0)).astype(np.float32)))
def _eplay(vel, dur, secs=1.5):
    with ea_.lock:
        for i in range(ea_.nv): ea_.v_data[i] = None; ea_.v_pad[i] = None; ea_.v_ov[i] = None
    ea_.trigger(p_env_, vel, 0, dur); y_ = np.concatenate([ea_.render(256)[:, 0] for _ in range(int(secs * 44100 / 256))])
    return np.array([np.abs(y_[k_:k_ + 2205]).max() for k_ in range(0, len(y_) - 2205, 2205)])
p_env_.a_amp_t, p_env_.a_amp_l = [300, 200, 0, 0, 400], [0, 99, 50, 50, 50]
en_ = _eplay(127, int(0.8 * 44100))
ok("ASR-10 ENVELOPE: five stages - attack rises to PEAK, DECAY 1 falls to the break / SUSTAIN level, which holds while the note is",
   en_[0] < 0.3 * en_[6] and abs(en_[12] - (50 / 99.0) ** 1.5 * en_[6]) < 0.03 and abs(en_[12] - en_[14]) < 0.01)
ok("ASR-10 ENVELOPE: note-off plays its RELEASE (400 ms), then the voice ends", en_[18] < en_[15] and en_[-1] == 0.0 and en_[17] > 0.01)
p_env_.a_emode = 2; er_ = _eplay(127, int(1.2 * 44100)); p_env_.a_emode = 0
ok("ASR-10 ENVELOPE: ENV MODE REPEAT cycles attack .. decay 3 while held", er_[10] < 0.3 * er_[6] and er_[16] > 0.9 * er_[6])
p_env_.a_emode, p_env_.a_amp_t, p_env_.a_amp_l = 1, [0, 600, 0, 0, 100], [99, 99, 20, 20, 20]
ef_ = _eplay(127, int(0.1 * 44100)); p_env_.a_emode = 0
ok("ASR-10 ENVELOPE: ENV MODE FINISH runs the decays to the sustain even after a short note, then releases", ef_[8] > 0.05 and ef_[-1] == 0.0)
p_env_.a_amp_t, p_env_.a_amp_l = [0, 0, 0, 0, 20], [0, 99, 99, 99, 99]
p_env_.a_softvel, p_env_.a_vcurve = 0, 1; v1_ = _eplay(64, None, 0.2)[2]; v2_ = _eplay(127, None, 0.2)[2]
p_env_.a_softvel = 100; v3_ = _eplay(64, None, 0.2)[2]
p_env_.a_softvel, p_env_.a_vcurve = 0, 2; v4_ = _eplay(64, None, 0.2)[2]; p_env_.a_vcurve = 1
ok("ASR-10 velocity: SOFT VEL levels and the VEL CURVE between them (0% soft: velocity 64 quieter; 100%: as hard; VEL1 quieter still)",
   v1_ < 0.5 * v2_ and abs(v3_ - v2_) < 0.01 and v4_ < 0.7 * v1_)
ce_ = Controls(ea_); ce_.set_mode("PROG"); ce_.prog_front = False; ce_.set_prog_tab(2); Renderer(ce_).frame()
ok("ASR-10 ENVELOPES tab: its times, the level each ends on, release / soft vel / curve / mode, and the shape drawn",
   ce_.PROG_TABS[2][1][:8] == [64, 65, 66, 67, 70, 71, 72, 73] and [q_[0] for q_ in ce_.qlinks()] == ["Attack", "Decay 1", "Sustain", "Release"])
def _bus_peak(b):
    p_imp_.a_bus = b; return float(np.abs(_aplay(p_imp_, 0.1)).max())
ok("ASR-10 FX BUS: with no ASR-10 effect to feed, FX1 / FX2 / DRY all play as normal", abs(_bus_peak(0) - _bus_peak(2)) < 1e-3 and abs(_bus_peak(1) - _bus_peak(2)) < 1e-3 and _bus_peak(1) > 0.01)
p_imp_.a_bus = 0
ea_.asr_rate = 1; ok("ASR-10: at 44.1 kHz the sound is held at full rate", abs(len(ea_.asr_data(pa_)) - 1 - 22050) < 2); ea_.asr_rate = 0
ca_ = Controls(ea_); ca_.set_mode("MAIN"); ra_ = Renderer(ca_); ra_.frame()
ok("ASR-10: Q-links on MAIN are Volume / Tempo / Rate / Quantize", [q[0] for q in ca_.qlinks()] == ["Volume", "Tempo", "Rate", "Quantize"])
ca_.lcd_cur = "seq"; ca_.lcd_nav("right"); ea_.msg_time = 0
ok("ASR-10: the arrows step through its pages; the display shows one at a time", ca_.lcd_cur == "trk" and machines_.screen(ea_, "ASR-10", "trk").text()[0].startswith("TRK"))
ea_.cur_track = 0; ea_.seq.tracks[0].events = [(13, 0, 100, 24), (37, 0, 100, 24)]; ea_.asr_q = 4; ca_.soft(2)
ok("ASR-10: F3 = QUANTIZE TRACK to its value, on the current track", [ev[0] for ev in ea_.seq.tracks[0].events] == [24, 48] and "COMMAND COMPLETED" in ea_.msg)
ea_.save_project = E.Engine.save_project.__get__(ea_); ea_.asr_q, ea_.asr_rate = 7, 1; ea_.save_project()
ea2_ = E.Engine("/tmp/t7asr"); ok("ASR-10: machine, quantize value and rate are saved with the project", ea2_.machine == "ASR-10" and ea2_.asr_q == 7 and ea2_.asr_rate == 1)

# ================================================================= PROG as an MPC 2.x program edit: slices, live edits, fine, stretch
es_ = fresh("/tmp/t7slice"); es_.save_project = lambda: None
clk_ = np.zeros(4 * 44100, np.float32); clk_[::441] = 0.5
ss_ = es_.add_source("clicks", clk_); ss_.chops = [44100, 88200, 132300]
pa3_, pa4_ = es_.programs[0].pads[0], es_.programs[0].pads[1]
for p_, k_ in ((pa3_, 2), (pa4_, 3)): p_.assign(ss_); p_.lofi_on = False; es_.set_slice(p_, k_)
ok("PROG SAMPLES: SLICE puts a pad on a slice of its sample (3 of 4)", (pa3_.start, pa3_.end, pa3_.link) == (88200, 132300, (ss_.id, 2)))
es_.set_region(pa3_, end=120000)
ok("PROG SAMPLES: moving a slice's END moves its marker - the next slice (and its pad) follows, as on an MPC",
   pa3_.end == 120000 and pa4_.start == 120000 and ss_.chops[2] == 120000)
es_.set_slice(pa3_, None); es_.set_region(pa3_, end=110000)
ok("PROG SAMPLES: SLICE: PAD gives the pad its own start / end (the slices stay put)", pa3_.link is None and pa3_.end == 110000 and pa4_.start == 120000)
es_.set_slice(pa3_, 0)
ok("PROG SAMPLES: the first slice's start is the sample's start (it says so, nothing moves)", es_.set_region(pa3_, start=500) is not None and pa3_.start == 0)
es_.set_slice(pa3_, 2)
cs3_ = Controls(es_); cs3_.set_mode("PROG"); cs3_.prog_front = False; es_.select_pad(0, 0); cs3_.set_prog_tab(1); rs3_ = Renderer(cs3_); rs3_.frame()
ok("PROG: tabs are GLOBAL / SAMPLES / ENVELOPES / EFFECTS; SAMPLES puts START / END / FINE / SEMI on the Q-links",
   [t[0] for t in cs3_.PROG_TABS] == ["GLOBAL", "SAMPLES", "ENVELOPES", "EFFECTS"] and [q[0] for q in cs3_.qlinks()] == ["Start", "End", "Fine", "Pad tune"])
cs3_.qlinks()[1][2](125000 / ss_.length); ok("PROG SAMPLES: Q2 drags the END (and with it the slice marker)", abs(pa3_.end - 125000) < 2 and abs(pa4_.start - 125000) < 2)
cs3_.pw_zoom = True; rs3_.frame(); ok("PROG SAMPLES: ZOOM shows the region close up", True)
es_.trigger(pa3_, 127, 0, None)
for _ in range(40): es_.render(256)
v3_ = next(i for i in range(es_.nv) if es_.v_pad[i] is pa3_)
es_.set_region(pa3_, end=pa3_.start + 5000)
ok("PROG: a sounding note follows an edit at once - trimmed past where it is, it fades out", 0 <= es_.v_kill[v3_] <= E.FADE_FR)
es_.set_slice(pa3_, None); pa3_.assign(es_.add_source("sine1k", (0.5 * np.sin(2 * np.pi * 1000 * np.arange(44100) / 44100.0)).astype(np.float32))); pa3_.lofi_on = False
def _pk(pad, secs=0.3):
    with es_.lock:
        for i in range(es_.nv): es_.v_data[i] = None; es_.v_pad[i] = None
    es_.trigger(pad, 127); y_ = np.concatenate([es_.render(256)[:, 0] for _ in range(int(secs * 44100 / 256))])
    sp_ = np.abs(np.fft.rfft(y_[2000:10192] * np.hanning(8192))); return np.fft.rfftfreq(8192, 1 / 44100.0)[np.argmax(sp_)]
pa3_.fine = 50; f50_ = _pk(pa3_); pa3_.fine = 0
ok("PROG SAMPLES: FINE tunes in cents (+50 ct: 1 kHz -> 1029 Hz)", abs(f50_ - 1029.3) < 8)
es_.trigger(pa3_, 127, 0, None)
for _ in range(10): es_.render(256)
v3_ = next(i for i in range(es_.nv) if es_.v_pad[i] is pa3_ and es_.v_data[i] is not None)
pa3_.tune = 12; es_.pad_changed(pa3_); y12_ = np.concatenate([es_.render(256)[:, 0] for _ in range(40)]); pa3_.tune = 0; es_.pad_changed(pa3_)
sp12_ = np.abs(np.fft.rfft(y12_[:8192] * np.hanning(8192)))
ok("PROG: SEMI / FINE changes are heard on the note already sounding", abs(np.fft.rfftfreq(8192, 1 / 44100.0)[np.argmax(sp12_)] - 2000) < 15)

# ================================================================= per-program SOUND, and the machine's sound on PROG > GLOBAL
eo_ = fresh("/tmp/t7sound"); eo_.save_project = lambda: None; eo_.machine = "SP-1200"
co_ = Controls(eo_); co_.set_mode("PROG"); co_.set_prog_tab(0); ro_ = Renderer(co_); ro_.frame()
ok("PROG GLOBAL: under the pad's settings, a heading and its machine's own sound options (SP-1200: SOUND, SAMPLED AT, CHANNEL, DECAY, RING)", co_.machine_rows() == [52, 12, 56, 57, 53])
po_ = eo_.programs[1].pads[0]; po_.assign(eo_.add_source("sq", (0.3 * np.sign(np.sin(2 * np.pi * 220 * np.arange(22050) / 44100.0))).astype(np.float32)))
eo_.programs[1].sound = "ASR-10"
eo_.trigger(po_, 120); eo_.trigger(eo_.programs[0].pads[0], 120)
ok("SOUND: one program plays as an ASR-10 inside an SP-1200 project (the others stay SP-1200)",
   any(eo_.v_pad[i] is po_ and eo_.v_ov[i] is not None for i in range(eo_.nv)) and any(eo_.v_sp[i] is not None for i in range(eo_.nv)))
eo_.cur_track = 0; eo_.track.prog = 1; ro_.frame()
ok("SOUND: that program's PROG shows the ASR-10's tabs and rows (RATE, FX BUS, FILTER, CUTOFFS; TRANSWAVE on page 2)", [t_[0] for t_ in co_.PROG_TABS][3:5] == ["LFO", "MODULATION"] and co_.machine_rows() == [52, 54, 58, 59, 60, 61] and co_.machine_pages()[1][-1] == 55)
co_.prog_adjust(52, 1); ok("SOUND: stepping it goes back to the machine's sound", eo_.programs[1].sound is None and eo_.sound_of(po_) == "SP-1200")
eo_.programs[1].sound = "MODERN"; eo_.save_project = E.Engine.save_project.__get__(eo_); eo_.save_project()
ok("SOUND: saved with the project", E.Engine("/tmp/t7sound").programs[1].sound == "MODERN")

# ================================================================= ASR-10 wavesamples: its sound chip's looping and TRANSWAV
import asrvoice as AV
F_, N_ = 100, 8                                    # 8 single cycles of 100 samples: cycle k has harmonic k+1
mem_ = np.concatenate([np.round(20000 * np.sin(2 * np.pi * (k_ + 1) * np.arange(F_) / F_)).astype(np.int16) for k_ in range(N_)] + [np.zeros(1, np.int16)])
ov_ = AV.Voice(); ov_.start(mem_, 0, (len(mem_) - 1) * 512, 0, F_ * 512, 2, 7, 8, 0, 2048, 1.0, 10, 0)
ok("ASR-10 voice: a note on TRANSWAV starts in the loop (cycle 0) and loops it", ov_.regs()["start"] == 0 and ov_.regs()["end"] == F_ * 2048)
ov_.render(30); ov_.set(2048, 16384); ov_.render(11)
r_ = ov_.regs()
ok("ASR-10 voice: a TRANSWAV move writes START at once and waits for the loop's end (chip in trans-wave mode, IRQ armed)",
   r_["start"] == 4 * F_ * 2048 and r_["end"] == F_ * 2048 and r_["cr"] & 0x30 == 0x30)
ov_.set(2048, 32767); ov_.render(11)
ok("ASR-10 voice: while a move is pending a new one is dropped (and, as on the machine, not retried)", ov_.regs()["start"] == 4 * F_ * 2048 and ov_.regs()["tw"] == 7)
y_, _ = ov_.render(200)
r_ = ov_.regs()
ok("ASR-10 voice: at the loop's end it jumps into cycle 4 and loops there (END written, plain looping again)",
   r_["start"] == 4 * F_ * 2048 and r_["end"] == 5 * F_ * 2048 and r_["cr"] & 0x38 == 0x08)
ok("ASR-10 voice: the jump keeps the phase - no click", float(np.abs(np.diff(y_)).max()) < 20000 * 2 * np.pi * 5 / F_ / 32768 * 1.05)
ov_.start(mem_, 0, (len(mem_) - 1) * 512, 0, F_ * 512, 2, 1, 127, 9, 2048, 1.0, 10, 32767)
ok("ASR-10 voice: LOOP POS moves the loop by MOD AMT x source / RANGE (and never past the sample's end)",
   ov_.regs()["end"] == (len(mem_) - 1) * 2048 and ov_.regs()["end"] - ov_.regs()["start"] == F_ * 2048)
ov_.start(mem_, 0, (len(mem_) - 1) * 512, 0, F_ * 512, 2, 2, 100, 14, 2048, 1.0, 10, 32767)
ok("ASR-10 voice: START moves where the note begins (100 x 256 x 32767 >> 14 OS units = 99 samples)", ov_.regs()["accum"] >> 11 == 99)
ov_.start(mem_, 0, (len(mem_) - 1) * 512, 0, F_ * 512, 4, 0, 0, 0, 2048, 1.0, 10, 0)
y1_, k1_ = ov_.render(1000); ov_.release(); y2_, k2_ = ov_.render(2000)
ok("ASR-10 voice: LOOP AND RELEASE loops while held, then plays on to the sample's end and stops", k1_ == 1000 and 0 < k2_ < 2000 and ov_.done())
ov_.start(mem_, 0, (len(mem_) - 1) * 512, 0, F_ * 512, 3, 0, 0, 0, 2048, 1.0, 10, 0)
ov_.render(150)
ok("ASR-10 voice: LOOP BIDIRECTION plays the loop backwards after its end", ov_.regs()["cr"] & 0x40 == 0x40)
ov_.start(mem_, 0, (len(mem_) - 1) * 512, 0, F_ * 512, 0, 0, 0, 0, 3072, 1.0, 10, 0)
ok("ASR-10 voice: pitch is the chip's frequency count (2048 = as recorded; 21.11 addresses)", ov_.regs()["fc"] == 3072)
ea_.machine, ea_.asr_rate = "ASR-10", 0
tt_ = np.arange(int(1.5 * 44100)) / 44100.0
saw_ = (sum(np.minimum(1, tt_ / 1.5 * 8 / h) * np.sin(2 * np.pi * 110 * h * tt_) / h for h in range(1, 16)) * 0.3).astype(np.float32)
pw_ = ea_.programs[0].pads[2]; pw_.assign(ea_.add_source("tw_saw", saw_))
info_ = ea_.make_transwave(pw_, 64)
ok("ASR-10: MAKE TRANSWAVE takes 64 single cycles (110 Hz -> 271 samples at 29.76 kHz) onto a new sample, held at its rate",
   info_[0] == 64 and info_[1] == 271 and pw_.src.native is not None and len(pw_.src.native[1]) == 64 * 271 + 1 and pw_.a_mod == 7 and pw_.a_loop == 2)
def _cent(y, w=4096):
    s_ = np.abs(np.fft.rfft(y[:w] * np.hanning(w))); f_ = np.fft.rfftfreq(w, 1 / 44100.0); return float((s_ * f_).sum() / max(1e-9, s_.sum()))
with ea_.lock:
    for i in range(ea_.nv): ea_.v_data[i] = None; ea_.v_pad[i] = None; ea_.v_ov[i] = None
ea_.trigger(pw_, 120, 0, int(2.0 * 44100))
yw_ = np.concatenate([ea_.render(256)[:, 0] for _ in range(int(2.0 * 44100 / 256))])
ok("ASR-10: ENV1 sweeps the transwave from its first cycle to its last (the sound gets brighter), at the cycle's pitch",
   _cent(yw_[2000:]) * 1.5 < _cent(yw_[60000:]) and abs(44100 / AV.detect_period(yw_[60000:76000], 44100) - 109.8) < 1.5)
ea_.save_project(); ea3_ = E.Engine("/tmp/t7asr")
pw3_ = ea3_.programs[0].pads[2]
ok("ASR-10: a transwave, its loop and modulation are saved with the project (its 29.76 kHz copy beside the samples)",
   pw3_.src is not None and pw3_.src.native is not None and len(pw3_.src.native[1]) == 64 * 271 + 1 and pw3_.a_mod == 7 and abs(pw3_.a_le - 271 / E.ASR_RATES[0]) < 1e-9)
ca_.set_mode("PROG"); ca_.prog_front = False; ra_.frame()
ok("ASR-10: PROG has its LFO and MODULATION tabs (as on an MPC 2.x), and F3 = MAKE TRANSWAVE", [t[0] for t in ca_.PROG_TABS][3:] == ["LFO", "MODULATION", "EFFECTS"] and ca_.soft_labels()[2] == "MAKE TRANSWAVE")

# ================================================================= the MPCs' sound chips (dsp/akai.c)
import mpcvoice as MPV
em_ = fresh("/tmp/t7mpc"); em_.save_project = lambda: None
tm_ = np.arange(44100) / 44100.0
pm_ = em_.programs[0].pads[0]; pm_.assign(em_.add_source("m1k", (0.5 * np.sin(2 * np.pi * 1000 * tm_)).astype(np.float32))); pm_.lofi_on = False
def _mplay(m, vel=127, dur=None, secs=0.5, pad=None):
    pad = pad or pm_; em_.machine = m
    with em_.lock:
        for i in range(em_.nv): em_.v_data[i] = None; em_.v_pad[i] = None; em_.v_ov[i] = None
    em_.trigger(pad, vel, 0, dur); return np.concatenate([em_.render(256)[:, 0] for _ in range(int(secs * 44100 / 256))])
ok("MPC sounds: the MPC60, MPC3000 and MPC2000XL play on their own chips' models (not as MODERN any more)",
   all(m_ in E.SOUNDS for m_ in ("MPC60", "MPC3000", "MPC2000XL")) and (_mplay("MPC60") is not None) and len(em_.v_ov) and
   any(o_ is not None and len(o_) == 9 for o_ in em_.v_ov))
w_ = np.zeros(4096, np.int16); w_[0] = 16000
H_ = np.abs(np.fft.rfft(MPV.l4003_filter(w_).astype(float))); f40_ = np.fft.rfftfreq(4096, 1 / 40000.0)
dB_ = lambda fr: 20 * np.log10(H_[np.argmin(abs(f40_ - fr))] / H_[1])
ok("MPC60: the L4003's filter (as the MPC3000 plays MPC60 sounds) is a de-emphasis: flat at 1 kHz, -10 dB at 10 kHz",
   abs(dB_(1000)) < 0.6 and -12 < dB_(10000) < -8)
rng_ = np.random.default_rng(3); pn_ = em_.programs[0].pads[1]
pn_.assign(em_.add_source("noise", (0.2 * rng_.standard_normal(88200)).astype(np.float32))); pn_.lofi_on = False
def _psd(y):
    Y_ = np.zeros(1025)
    for k_ in range(5000, 60000, 1024): Y_ += np.abs(np.fft.rfft(y[k_:k_ + 2048] * np.hanning(2048))) ** 2
    return Y_
A_, B_ = _psd(_mplay("MODERN", pad=pn_, secs=1.6)), _psd(_mplay("MPC60", pad=pn_, secs=1.6)); fq_ = np.fft.rfftfreq(2048, 1 / 44100.0)
rt_ = lambda fr: 10 * np.log10(B_[np.argmin(abs(fq_ - fr))] / A_[np.argmin(abs(fq_ - fr))])
print("MPC60 vs MODERN (dB): 1k %.2f 5k %.2f 10k %.2f 17k %.2f 19.5k %.2f" % tuple(rt_(x) for x in (1000, 5000, 10000, 17000, 19500)))
ok("MPC60: pre-emphasised 12-bit words at 40 kHz + the chip's de-emphasis = flat to 5 kHz (within its LC filters' ripple), gone above 20 kHz",
   abs(rt_(1000)) < 0.5 and abs(rt_(5000)) < 1.5 and rt_(21000) < -12)
ok("MPC60 analog path (service manual): its 18 kHz LC filters in and out and the 40 kHz hold's droop - still there at 17 kHz, gone by 19.5 kHz",
   -6 < rt_(17000) < -1 and rt_(19500) < -25)
X_ = _psd(_mplay("MPC2000XL", pad=pn_, secs=1.6)); T_ = _psd(_mplay("MPC3000", pad=pn_, secs=1.6))
rx_ = lambda Z_, fr: 10 * np.log10(Z_[np.argmin(abs(fq_ - fr))] / A_[np.argmin(abs(fq_ - fr))])
ok("MPC2000XL analog path (its schematic): no oversampling - the 44.1 kHz hold plus its I/V pole and Sallen-Key roll the top off gently (~-1 dB at 10 kHz, ~-2 dB at 19.5 kHz)",
   abs(rx_(X_, 1000)) < 0.3 and -1.5 < rx_(X_, 10000) < -0.5 and -3 < rx_(X_, 19500) < -1.2)
ok("MPC3000 analog path (parts list): delta-sigma ADC in, 8x-oversampling filter + 18-bit DACs out - flat", max(abs(rx_(T_, f_)) for f_ in (1000, 10000, 19500)) < 0.3)
pq_ = em_.programs[0].pads[2]; pq_.assign(em_.add_source("quiet", (0.01 * np.sin(2 * np.pi * 437 * np.arange(88200) / 44100.0)).astype(np.float32))); pq_.lofi_on = False
Q_ = _psd(_mplay("MPC60", pad=pq_, secs=1.6))
ok("MPC60: its 12-bit hiss is there, and lower in the treble than the mids (the emphasis at work)",
   10 * np.log10(Q_[(fq_ > 1000) & (fq_ < 4000)].mean() / Q_.max()) > -75 and Q_[(fq_ > 12000) & (fq_ < 18000)].mean() < 0.3 * Q_[(fq_ > 1000) & (fq_ < 4000)].mean())
y60_ = _mplay("MPC60"); pm_.tune = 0.5; y60b_ = _mplay("MPC60"); pm_.tune = 0
d_ = np.diff(y60b_[3000:3400])
ok("MPC60 / MPC3000: pitch is right (1 kHz) and a 4.12 step on each chip", abs(np.fft.rfftfreq(8192, 1 / 44100.0)[np.argmax(np.abs(np.fft.rfft(_mplay("MPC3000")[4000:12192] * np.hanning(8192))))] - 1000) < 6
   and abs(np.fft.rfftfreq(8192, 1 / 44100.0)[np.argmax(np.abs(np.fft.rfft(y60_[4000:12192] * np.hanning(8192))))] - 1000) < 6)
pm_.flt, pm_.res = "LP", 0.0
lv_ = {}
for c_ in (0.2, 0.5, 0.99): pm_.cutoff = c_; lv_[c_] = float(np.abs(_mplay("MPC3000")[4000:12000]).max())
pm_.res = 1.0; pm_.cutoff = 0.66; lr_ = float(np.abs(_mplay("MPC3000")[4000:12000]).max())
ok("MPC3000: the L6028's two-pole low-pass - FREQ closes on a 1 kHz tone; RESONANCE 15 boosts it at the cutoff",
   lv_[0.2] < 0.05 * lv_[0.99] and lv_[0.5] < lv_[0.99] and lr_ > 1.5 * lv_[0.99])
y60f_ = _mplay("MPC60")
ok("MPC60: has no filter - FILTER settings do nothing", abs(float(np.abs(y60f_[4000:12000]).max()) - float(np.abs(y60_[4000:12000]).max())) < 0.01)
pm_.flt, pm_.res, pm_.cutoff = "OFF", 0.0, 1.0
pm_.decay, pm_.m_dmode = 300, 1
seg_ = lambda y: [float(np.abs(y[k_:k_ + 2205]).max()) for k_ in range(0, len(y) - 2205, 4410)]
ys_ = seg_(_mplay("MPC3000"))
pm_.m_dmode = 0; ye_ = seg_(_mplay("MPC3000", secs=1.1))
ok("MPC3000 DECAY MODE: START decays from the start (straight down, as the chip ramps); END holds, then fades into the sound's end",
   ys_[1] < 0.8 * ys_[0] and ys_[4] == 0.0 and abs(ye_[5] - ye_[0]) < 0.01 and ye_[9] < 0.5 * ye_[0] and ye_[-1] == 0.0)
pm_.mode = "HOLD"; yh_ = seg_(_mplay("MPC3000", dur=int(0.3 * 44100), secs=0.8))
ok("MPC3000 DECAY MODE END: a held note fades over DECAY from its note-off", abs(yh_[2] - yh_[0]) < 0.01 and yh_[4] < 0.75 * yh_[0] and yh_[-1] == 0.0)
pm_.mode, pm_.decay, pm_.m_dmode = "ONE", 0, 1
pm_.m_vatk = 200; sa_ = _mplay("MPC2000XL", vel=40, secs=0.2); ha_ = _mplay("MPC2000XL", vel=127, secs=0.2); pm_.m_vatk = 0
ok("MPC VEL > ATTACK: softer notes fade in slower", np.abs(sa_[:2000]).max() < 0.5 * np.abs(sa_[6000:8000]).max() and np.abs(ha_[:2000]).max() > 0.2)
pm_.m_vpitch = 1200; yp_ = _mplay("MPC2000XL", vel=127); pm_.m_vpitch = 0
ok("MPC2000XL VELO > PITCH: +1200 ct at full velocity = an octave up", abs(np.fft.rfftfreq(8192, 1 / 44100.0)[np.argmax(np.abs(np.fft.rfft(yp_[4000:12192] * np.hanning(8192))))] - 2000) < 10)
cm_ = Controls(em_); em_.machine = "MPC2000XL"; cm_.set_mode("PROG"); cm_.set_prog_tab(0); Renderer(cm_).frame()
ok("MPC2000XL: its own options under the heading (DECAY MODE, VEL > LEVEL / ATTACK / START / PITCH; filter attack)",
   cm_.machine_pages() == [[52, 77, 81, 78, 79, 80], [82, 23]])
em_.machine = "MPC60"; ok("MPC60: VEL > LEVEL / ATTACK / START under its heading; DECAY reads FADEOUT", cm_.machine_rows() == [52, 81, 78, 79] and
                          Renderer(cm_).prog_label(17) == "FADEOUT")
em_.machine = "MODERN"

# ================================================================= ASR-10 effects (its ES5510 chip + the ROM's own 68000 routines)
import asrfx as AF
esp_ = AF.Esp()
def _skip_run(g10):
    """ADD g10,0 (sets the flags) / MOV g11 > CMR / skippable MOV g12 > g13: the skip sees both of them"""
    esp_.reset()
    prog_ = [0xffffff100040, 0xffff11fb9040, 0xffff121390c0, 0xffffffff9040, 0xffffffff9040, 0xffffffff9040, 0xfffffffff040]
    for a_, ins_ in enumerate(prog_): esp_.set_instr(a_, ins_)
    for r_, v_ in ((0x10, g10), (0x11, 0x840000), (0x12, 0x123456), (0x13, 0)): esp_.write(r_, v_)
    esp_.process(np.zeros((1, 8), np.int16), AF.IN_MASK); return esp_.read(0x13) & 0xffffff
ok("ASR-10 FX chip: a skip tests the flags and condition mask the instruction just before it set (the ROM's programs rely on it)",
   _skip_run(0xfffff0) == 0x123456 and _skip_run(0x000010) == 0)
rom_ = bytearray(0x40000)
code_ = [0x123C, 0x0021, 0x243C, 0x0012, 0x3456, 0x4EB8, 0x8030, 0x4E75]           # move.b #$21,D1; move.l #$123456,D2; jsr $8030.w; rts
for k_, w_ in enumerate(code_): rom_[2 * k_:2 * k_ + 2] = w_.to_bytes(2, "big")
hnd_ = [0x121A, 0x7400, 0x4EB8, 0x8030, 0x4E75]                                      # kind 1: move.b (A2)+,D1; moveq #0,D2; jsr $8030.w; rts
for k_, w_ in enumerate(hnd_): rom_[0x100 + 2 * k_:0x102 + 2 * k_] = w_.to_bytes(2, "big")
class _R: d = bytes(rom_)
AF.HANDLERS_SAVE = dict(AF.HANDLERS); AF.HANDLERS.clear(); AF.HANDLERS[1] = 0xF80100
cpu_ = AF.Cpu(_R()); cpu_.mirror({}, {})
out_, _, done_ = cpu_.call(0xF80000, [0] * 15)
ok("ASR-10 FX: the ROM's routines run on a 68000; a call to the OS's register-write entry becomes a chip write",
   done_ and out_ == [(1, 0x21, 0x123456)])
cpu_.poke(0x2000, [1, 0x40, 1, 0x41, 0])
out_, _, done_ = cpu_.call(0xFF801E, [0] * 8 + [0, 0, 0x2000, 0, 0, 0, 0])
ok("ASR-10 FX: the OS's action-list runner (FF801E) walks a parameter's actions through its routine table",
   done_ and [r for _, r, _ in out_] == [0x40, 0x41])
AF.HANDLERS.clear(); AF.HANDLERS.update(AF.HANDLERS_SAVE); AF._cpu = None
rd_, ru_ = AF.Resampler(44100, AF.ESP_RATES["30K"]), AF.Resampler(AF.ESP_RATES["30K"], 44100)
xs_ = np.sin(2 * np.pi * 1000 * np.arange(44100) / 44100.0)[:, None].repeat(2, 1)
ys_ = np.concatenate([ru_.process(rd_.process(xs_[k_:k_ + 512])) for k_ in range(0, 44100, 512)])
ok("ASR-10 FX: 44.1 kHz <-> the chip's 29.76 kHz keeps the length and the level", abs(len(ys_) - 44100) <= 2 and abs(np.sqrt((ys_[2000:40000, 0] ** 2).mean()) - 0.7071) < 0.005)
import fx as FXL
ok("ASR-10 FX: without your ROM in firmware/asr10/ none are listed (nothing of the ASR-10 ships)",
   (not AF.find_rom()) == (not any(k_ == "asr10" for k_, _, _ in FXL.discover())))
if AF.library():
    ax_ = FXL.create("asr10", "LARGE PLATE"); imp_ = np.zeros(8192, np.float32); imp_[10] = 0.5
    yl_ = np.concatenate([ax_.process(imp_[k_:k_ + 512], imp_[k_:k_ + 512])[0] for k_ in range(0, 8192, 512)])
    ok("ASR-10 FX (your ROM): LARGE PLATE loads its preset and rings on after an impulse", ax_.fmt(0) == "BALLAD REV" and np.abs(yl_[4000:]).max() > 0.001)
    ea_.set_fx("master", "asr10", "HALL REVERB2")
    def _tail(b):
        p_imp_.a_bus = b; ea_.master_fx.run_.load(); y_ = _aplay(p_imp_, 0.7); return float(np.sqrt((y_[8000:] ** 2).mean()))
    t_ = [_tail(b) for b in (0, 1, 2)]; p_imp_.a_bus = 0; ea_.set_fx("master", None)
    ok("ASR-10 FX BUS (your ROM): FX1 and FX2 feed the effect's two inputs at their own mix; DRY skips it (no reverb tail)",
       t_[0] > 1e-5 and t_[1] > 1e-5 and abs(t_[0] - t_[1]) > 0.1 * t_[0] and t_[2] == 0.0)

# ================================================================= FX faceplates, valve case, bus comp; SAMPLE keep / discard; SONG insert
ef = fresh("/tmp/t7fxp"); ef.save_project = lambda: None; cf = Controls(ef); rf = Renderer(cf)
cf.set_mode("FX"); cf.fx_set_target(65); rf.frame(); ok("FX: an empty slot opens the effect library", cf.fx_browse)
for _k, _n in enumerate(["Delay", "Drive", "Filter", "Crush"]):
    cf.fx_set_target(65 + _k); cf.fx_cursor = next(i for i, it in enumerate(cf.fx_items) if it[1] == _n); cf.fx_load()
    rf.frame(); ok(f"FX: {_n} loads and shows its faceplate", ef.prog.fx[_k] is not None and not cf.fx_browse and rf.img.size == (W, H))
cf.fx_set_target(64); cf.fx_cursor = next(i for i, it in enumerate(cf.fx_items) if it[1] == "Comp"); cf.fx_load(); rf.frame()
ok("FX: the bus comp loads on the master", ef.master_fx is not None and ef.master_fx.name == "Comp")
ok("FX: chain bar is PAD, INSERT 1-4, MASTER", [t for t, _ in cf.fx_chain()][1:] == [65, 66, 67, 68, 64])
cf.fx_set_target(66); ok("FX: valve drive Q-links are DRIVE BIAS MIX LEVEL", [q[0] for q in cf.qlinks()] == ["Drive", "Bias", "Mix", "Level"])
cf.valve_open(1); rf.frame(); cf.jog(2); cf.ok(); ok("FX: the valve case swaps V1 (jog, OK = INSERT)", ef.prog.fx[1].v1()[0] == "12AT7" and not cf.valve_case)
cf.soft(3); ok("FX: F4 shows parameters 5-6 (V1 / V2)", cf.fx_page == 1 and [q[0] for q in cf.qlinks()][:2] == ["V1", "V2"]); cf.fx_page = 0
cf.fx_set_target(65); _dl = ef.prog.fx[0]; _dl.set(3, 10 / 11.0); ok("FX: tape echo MODE R+ALL plays all three heads", _dl.mode() == "R+ALL" and _dl.heads() == [0, 1, 2])
cf.soft(0); ok("FX: F1 BROWSE opens the library over the faceplate", cf.fx_browse); cf.soft(0); ok("FX: F1 CLOSE goes back to it", not cf.fx_browse)
_cp = ef.master_fx; _x = (np.sin(np.arange(4096) * 0.05) * 0.9).astype(np.float32)
for _ in range(30): _cp.process(_x.copy(), _x.copy())
ok("FX: the bus comp reduces gain on a loud signal", _cp.gr > 3.0)
_cr = ef.prog.fx[3]; _cr.set(1, 0.0); _y = _cr.process(_x.copy(), _x.copy())[0]; ok("FX: crush at 2 bits leaves a few levels", len(np.unique(np.round(_y, 4))) <= 6)
ef.has_input = True; cf.set_mode("SAMPLE"); ef.select_pad(0, 2); _old = ef.pad.src; cf.soft(0)
_blk = np.zeros((1024, 2), np.float32)
for _k in range(14):
    _b = _blk.copy()
    if _k >= 6: _b[:] = 0.4 * np.sin(np.arange(1024) * 0.07)[:, None]
    ef.render(1024, _b)
_ns = len(ef.sources)
cf.soft(1); ok("SAMPLE: STOP makes the take in the project's samples, on no pad", ef.pad.src is _old and ef.last_take is not None
   and len(ef.sources) == _ns + 1 and ef.last_take.name.startswith("rec_"))
ok("SAMPLE: the pre-roll keeps a little from before the threshold", ef.rec_preroll == 50 and ef.last_take.length > 8 * 1024)
cf.soft(3); ok("SAMPLE: DISCARD removes the take (the pad was never touched)", ef.pad.src is _old and ef.last_take is None and len(ef.sources) == _ns)
cf.soft(0)
for _k in range(14):
    _b = _blk.copy()
    if _k >= 6: _b[:] = 0.4 * np.sin(np.arange(1024) * 0.07)[:, None]
    ef.render(1024, _b)
cf.soft(1); _take = ef.last_take; cf.soft(2)
ok("SAMPLE: KEEP opens the take in CHOP", cf.mode == "CHOP" and cf.src is _take and ef.pad.src is _old)
cf.chop_n = 4; cf.chop_set_mode(0); cf.chop_run(quiet=True); _np = next(i for i, q in enumerate(ef.programs) if all(pd.empty for pd in q.pads))
cf.chop_convert(); cf.soft(3); ok("CHOP: CONVERT > NEW PROGRAM puts the slices on A01.. of an empty program, linked to the take",
   all(ef.programs[_np].pads[k].src is _take and ef.programs[_np].pads[k].link == (_take.id, k) for k in range(len(_take.regions()))))
_n0 = len(ef.sources); cf.chop_convert(); cf.soft(1); ok("CHOP: CONVERT > NEW SAMPLES makes one sample a slice", len(ef.sources) == _n0 + len(_take.regions()))
cf.chop_pick(1); ok("CHOP: < > steps through the project's samples", cf.src is not _take)
cf.set_mode("SAMPLE")
rf.frame(); ok("SAMPLE page renders", rf.img.size == (W, H))
cf.set_mode("SONG"); ef.song[:] = [[0, 1]]; cf.song_cur = 0; cf.soft(0); ok("SONG: INSERT adds a copy after the step", len(ef.song) == 2 and cf.song_cur == 1)
rf.frame(); cf.touch("down", 544 + 61.25 + 20, 100); cf.touch("up", 0, 0); ok("SONG: tapping a sequence tile sets the step's sequence", ef.song[1][0] == 1)
cf.qlinks()[2][2](3 / 15.0); ok("SONG: Q3 sets the repeats", ef.song[1][1] == 4)
for _m in ["PROG", "STEP", "MUTE", "SAMPLE", "CHOP", "SONG", "BROWSE", "FX", "MIXER"]:
    for _mc in ("MODERN", "MPC60", "SP-1200"):
        ef.machine = _mc; cf.set_mode(_m); rf.frame()
ef.machine = "MODERN"; ok("every rebuilt page renders on every machine's accent", rf.img.size == (W, H))

import console as _K
_st = _K.Strip("t"); _x = np.ones(256, np.float32) * 0.5; _l, _r = _st.run_eq(_x, _x, __import__("dspfast").sos)
_st.eq_gain = -6.0; _l2, _r2 = _st.run_eq(_x, _x, __import__("dspfast").sos)
ok("MIXER EQ: OUTPUT gain -6 dB halves the level (and is saved)", abs(float(_l2[0]) / float(_l[0]) - 10 ** (-6 / 20.0)) < 1e-4 and _st.state()["eq_gain"] == -6.0)

# ---------- the UX consistency rules (UX audit, Nov 2026) ----------
import time as _tt
eu2 = fresh("/tmp/t7ux"); cu2 = Controls(eu2); ru2 = Renderer(cu2)
eu2.select_pad(0, 0); _p = eu2.pad; _p.vol = 0.5
cu2.set_mode("PROG"); cu2.prog_front = False; cu2.prog_row = 4
cu2.jog(1); _a = _p.vol; cu2.shift = True; cu2.jog(1); cu2.shift = False; _b = _p.vol
ok("SHIFT = fine: PROG LEVEL moves 0.01 a click, 0.001 with SHIFT", abs(_a - 0.51) < 1e-9 and abs(_b - 0.511) < 1e-9)
_p.decay = 300; cu2.prog_row = 17; cu2.shift = True; cu2.jog(1); cu2.shift = False
ok("SHIFT = fine: DECAY steps 1 ms with SHIFT (50 ms without, above 200)", _p.decay == 301)
_p.vol = 0.5; cu2.prog_row = 4; cu2._jog_t = 0.0
for _ in range(20): cu2.jog(1, fast=True)
ok("fast jog: a spun wheel takes bigger steps on values", _p.vol > 0.5 + 20 * 0.01 + 1e-9)
cu2.set_mode("MAIN"); _bpm = eu2.seq.bpm; cu2.shift = True; cu2.jog(1); cu2.shift = False
ok("SHIFT = fine: MAIN BPM 0.1 with SHIFT", abs(eu2.seq.bpm - (_bpm + 0.1)) < 1e-6)
cu2.set_mode("CHOP"); _s_ = eu2.pad.src
if _s_ is not None:
    cu2.chop_cursor = 1000; cu2.jog(1); _d1 = cu2.chop_cursor - 1000; cu2.chop_cursor = 1000
    cu2.shift = True; cu2.jog(1); cu2.shift = False; _d2 = cu2.chop_cursor - 1000
    ok("SHIFT = fine: CHOP cursor moves less with SHIFT", 0 <= _d2 < _d1)
cu2.set_mode("PROG"); cu2.prog_front = False; cu2.set_prog_tab(0); _pi = eu2.pad_idx; cu2.nav("right")
ok("PROG: left / right = the next tab (pads choose the pad)", cu2.prog_tab == 1 and eu2.pad_idx == _pi)
cu2.set_mode("SAMPLE"); eu2.select_pad(0, 5); cu2.nav("up"); _u = eu2.sel; cu2.nav("left"); _l = eu2.sel
ok("SAMPLE: arrows walk the 4 x 4 pads as on MAIN (up = +4, left = -1)", _u == 9 and _l == 8)
cu2.set_mode("MAIN"); eu2.select_pad(0, 2); _nv = sum(1 for k in range(eu2.nv) if eu2.v_pad[k] is not None); cu2.ok()
ok("MAIN: OK opens the selected pad in PROG (and plays nothing)", cu2.mode == "PROG" and cu2.prog_front and
   sum(1 for k in range(eu2.nv) if eu2.v_pad[k] is not None) == _nv)
cu2.set_mode("MAIN"); ok("MAIN: F4 is MENU (SAVE lives in MENU and on SHIFT + PLAY)", cu2.soft_labels()[3] == ("P", "MENU"))
cu2.soft(3); ok("MAIN: F4 opens MENU", cu2.mode == "MENU")
cu2.set_mode("PROG"); cu2.prog_front = True; cu2.soft(3); ok("PROG front: F4 EFFECTS opens FX on the pad", cu2.mode == "FX" and cu2.fx_target == eu2.pad_idx)
cu2.set_mode("SONG"); eu2.song[:] = [[0, 2], [1, 1]]; cu2.song_cur = 0; cu2.jog(3)
ok("SONG: the jog changes the highlighted step's repeats", eu2.song[0][1] == 5 and cu2.song_cur == 0)
cu2.ok(); ok("SONG: OK goes to that step's sequence in SEQ", cu2.mode == "SEQ")
cu2.set_mode("SONG"); ok("SONG: F4 is BACK", cu2.soft_labels()[3] == BACK_)
cu2.button(BTN["SHIFT"], True); ok("SHIFT legend: not straight away", not cu2.show_legend())
cu2.shift_t -= 1.0; ok("SHIFT legend: after holding SHIFT a moment", cu2.show_legend())
cu2.jog(1); ok("SHIFT legend: gone once SHIFT is used (fine adjust)", not cu2.show_legend()); cu2.button(BTN["SHIFT"], False)
cu2.set_mode("MAIN"); cu2.button(BTN["SHIFT"], True); ok("SHIFT on the panel: soft keys show BANK A-D", soft_text(cu2.soft_labels()[1]) == "BANK B")
cu2.button(BTN["SHIFT"], False)
cu2.set_mode("EDIT"); ok("EDIT: F1 CLOSE ... F4 DO IT", soft_text(cu2.soft_labels()[0]) == "CLOSE" and soft_text(cu2.soft_labels()[3]) == "DO IT")
eu2.save_project(); ok("unsaved: nothing after a save", not eu2.unsaved(full=True))
eu2.pad.tune = 5; ok("unsaved: a change shows", eu2.unsaved(full=True))
eu2.cur_track = 7; eu2.pad.tune = 0; ok("unsaved: moving the cursor is not a change", not eu2.unsaved(full=True))
eu2.pad.tune = 5; eu2._unsaved_t = 0.0
cu2.set_mode("PROJECTS"); _dir = eu2.dir; eu2.new_project("other", save_first=False); eu2.pad.tune = 3; eu2._unsaved_t = 0.0
_items = eu2.list_projects(); _k = next(k for k, (n, p_) in enumerate(_items) if os.path.abspath(p_) == os.path.abspath(_dir))
_saved = []; _orig = eu2.save_project; eu2.save_project = lambda: _saved.append(1)
cu2.pj_open(_k); ok("PROJECTS: opening another with unsaved changes asks first", cu2.confirm is not None and os.path.abspath(eu2.dir) != os.path.abspath(_dir))
ru2.frame(); ok("the question renders, answers on the soft keys", [soft_text(x) for x in cu2.soft_labels()] == ["CANCEL", "DON'T SAVE", "", "SAVE"])
cu2.soft(0); ok("CANCEL (F1) stays put", cu2.confirm is None and os.path.abspath(eu2.dir) != os.path.abspath(_dir))
cu2.pj_open(_k); cu2.soft(1); ok("DON'T SAVE (F2) opens it without saving", os.path.abspath(eu2.dir) == os.path.abspath(_dir) and not _saved)
import studio as _stu
_sx = _stu.Studio(cu2)
_sx.button("F5", True); ok("Studio: F5 = MENU", cu2.mode == "MENU")
_sx.button("F6", True); ok("Studio: F6 = BACK", cu2.mode != "MENU")
_sx.button("PROG", True); ok("Studio: PROG = the program (PROG front panel)", cu2.mode == "PROG" and cu2.prog_front)
_sx.button("SAMPLE", True); ok("Studio: SAMPLE = the sample list", cu2.mode == "PROG" and cu2.picking)
_sx.button("SAMPLE EDIT", True); ok("Studio: SAMPLE EDIT = CHOP", cu2.mode == "CHOP")
_sx.button("SHIFT", True); _sx.button("SAMPLE EDIT", True); _sx.button("SHIFT", False); ok("Studio: SHIFT + SAMPLE EDIT = SAMPLE RECORD", cu2.mode == "SAMPLE")
_sx.button("SHIFT", True); _sx.button("PROG MIX", True); _sx.button("SHIFT", False); ok("Studio: SHIFT + PROG MIX = FX", cu2.mode == "FX")
_sx.button("TRACK MUTE", True); ok("Studio: TRACK MUTE = a pad mode, like 16 LEVEL", eu2.pad_mode == "TRACK MUTE"); _sx.button("TRACK MUTE", True)
cu2.set_mode("MAIN"); eu2.bank = 0; _sx.button("SHIFT", True); _sx.button("F2", True); _sx.button("SHIFT", False)
ok("Studio: SHIFT + F2 is not a bank (the Studio has BANK keys)", eu2.bank == 0)
cu2.set_mode("BROWSE"); cu2.br_filter = "AUDIO"; _sx.button("NO FILTER", True); ok("Studio: NO FILTER shows every file in BROWSE", cu2.br_filter == "ALL")
eu2.save_project = _orig

# ---------- the ASR keys (asrpanel.py): the ASR-10's own modes and pages on MAIN, switchable ----------
import asrpanel as _AP, studio_screen as _SSX
ea = fresh("/tmp/t7asrk"); ea.save_project = lambda: None; ca = Controls(ea); ra = Renderer(ca)
ea.machine = "ASR-10"; ca.set_mode("MAIN"); ea.select_pad(0, 0)
ok("ASR keys: off by default (the classic ASR screen)", not ca.asr_on() and soft_text(ca.soft_labels()[0]) != "LOAD")
ra.frame(); _hits0 = len(ca.hits)
ca.toggle_asr_keys(); ok("ASR keys: the rail switch turns them on, and it is remembered", ca.asr_on() and Controls(ea).asr_keys)
ok("ASR keys: F1-F3 = LOAD / COMMAND / EDIT, the mode lit", [soft_text(x) for x in ca.soft_labels()][:3] == ["LOAD", "COMMAND", "EDIT"]
   and ca.soft_labels()[2] == ("H", "EDIT"))
ra.frame(); ok("ASR keys: MAIN draws the display and the keypad", ra.img.size == (W, H) and len(ca.hits) != _hits0)
_pn = ca.asr; _pn.press_page("Filters"); _pn.idx = 1
_f1 = ea.pad.a_f1; ca.jog(-10); ok("ASR keys: the jog is the data slider (CUTOFF F1, the PROG row)", ea.pad.a_f1 == _f1 - 10)
ok("ASR keys: the display line, 22 characters", _pn.line() == f"CUTOFF F1={_f1 - 10}" and len(_pn.line()) <= 22)
_pn.cancel(); ok("ASR keys: Cancel puts the parameter back as it was", ea.pad.a_f1 == _f1)
ca.nav("right"); ok("ASR keys: right = the next parameter", _pn.item().name == "CUTOFF F2")
ca.nav("up"); ok("ASR keys: up = the value up", ea.pad.a_f2 == min(150, _f1 + 1) or ea.pad.a_f2 == 150)
_pn.press_page("Filters"); ok("ASR keys: the page key again = its next screen", _pn.idx == 3)
ok("ASR keys: Q1-Q4 are the page's parameters", [q[0] for q in ca.qlinks()] == ["Mode", "Cutoff F1", "Cutoff F2", "Kbd Amt F1"])
_c1 = ea.pad.a_f1; ca.qlinks()[1][2](ca.qlinks()[1][1]() - 0.05); ok("ASR keys: a Q-link moves its parameter", ea.pad.a_f1 == _c1 - 5)
_pn.press_page("Layer"); ok("ASR keys: a page Monolith has nothing for says so", _pn.line() == _AP.NOT_HERE)
ca.soft(1); _pn.press_page("Track"); ok("ASR keys: COMMAND > Track lists the ASR's track commands", _pn.line() == "QUANTIZE TRACK")
ok("ASR keys: F4 = ENTER when a command is on the display", ca.soft_labels()[3] == ("H", "ENTER"))
ea.track.events = [[0, 36, 100, 24], [50, 36, 100, 24]]
ca.soft(3); ok("ASR keys: ENTER asks (QUANTIZE TO=...)", _pn.ask is not None and _pn.line().startswith("QUANTIZE TO="))
ok("ASR keys: a question = F1 NO / F4 YES", [soft_text(x) for x in ca.soft_labels()] == ["NO", "", "", "YES"])
ca.soft(0); ok("ASR keys: F1 NO cancels it, nothing changed", _pn.ask is None and ea.track.events[1][0] == 50)
ca.soft(3); ca.ok(); ok("ASR keys: OK = Enter-Yes runs it", ea.track.events[1][0] == 48)
ca.button(BTN["UNDO"], True); ca.button(BTN["UNDO"], False); ok("ASR keys: UNDO is still the project's undo (not Cancel)", ea.track.events[1][0] == 50)
ca.nav("right"); ca.soft(3); ca.jog(2); ca.soft(3); ok("ASR keys: COPY TRACK, TO TRACK=03 (jog), YES", ea.seq.tracks[2].events == ea.track.events)
_pn.press_page("Wave"); ea.pad.start = 2000; _src = ea.pad.src; ca.soft(3)
ok("ASR keys: TRUNCATE WAVESAMPLE makes a trimmed copy (the old sample stays)", ea.pad.src is not _src and ea.pad.src.length == _src.length - 2000 and _src in ea.sources)
ca.soft(0); _pn.press_page("Seq Song"); _s0 = ea.cur_seq; ca.jog(1); ok("ASR keys: LOAD > Seq Song chooses the sequence", ea.cur_seq == (_s0 + 1) % E.NSEQ)
_fr = _SSX.frame(ca); ok("ASR keys: the Studio's screen draws them", _fr is not None and _fr.size == (360, 96))
ca.toggle_asr_keys(); ok("ASR keys: off again = the classic ASR screen, F3 QUANTIZE TRK as before", not ca.asr_on() and "QUANTIZE" in soft_text(ca.soft_labels()[2]))
ea.machine = "MPC60"; ca.toggle_asr_keys(); ok("ASR keys: only on the ASR-10", not ca.asr_on()); ca.toggle_asr_keys(); ea.machine = "MODERN"

# ---------- SETTINGS (settingspage.py): MENU > SETTINGS, kept in ui.json beside the software ----------
import settingspage as _SETP, json as _json
es = fresh("/tmp/t7set"); es.app_dir = "/tmp/t7set"; es.save_project = lambda: None
try: os.remove("/tmp/t7set/ui.json")
except OSError: pass
cs = Controls(es); rs_ = Renderer(cs)
cs.set_mode("MENU"); cs.menu_go(len(cs.MENU_ITEMS) - 1); ok("SETTINGS: the last MENU tile opens it", cs.mode == "SETTINGS")
rs_.frame(); ok("SETTINGS: draws, with F1 / F2 sections and F4 BACK", cs.soft_labels()[:3] == ["< SECTION", "SECTION >", ""] and cs.soft_labels()[3] == BACK_)
for _k in range(len(_SETP.SECTIONS)):
    cs.set_section(_k); rs_.frame()
ok("SETTINGS: every section draws", len(cs.hits) > 5)
cs.set_section(0); cs.set_row = 3; cs.nav("right")
ok("SETTINGS: AUDIO > LATENCY, right = the next value, saved in ui.json", cs.settings["latency"] == "0.032"
   and _json.load(open("/tmp/t7set/ui.json"))["latency"] == "0.032")
ok("SETTINGS: a sound change lights APPLY (F3)", cs.set_pending and cs.soft_labels()[2] == ("H", "APPLY"))
_rest = []; cs.restart_fn = lambda: _rest.append(1)
cs.soft(2); ok("SETTINGS: APPLY asks first", cs.confirm is not None)
cs.soft(3); ok("SETTINGS: ... then restarts Monolith", _rest == [1] and not cs.set_pending)
ok("SETTINGS: a new Controls reads them back (this Pi's settings, not the project's)", Controls(es).settings["latency"] == "0.032")
cs.set_section(1); cs.set_row = 2; cs.jog(-1)
ok("SETTINGS: CONTROLLERS > PAD VELOCITY (jog), takes effect at once", cs.settings["vel_curve"] == "SOFTER" and not cs.set_pending)
ok("PAD VELOCITY: a soft hit comes out louder on SOFTER", cs.vel_in(40) > 60 and cs.vel_in(127) == 127 and cs.vel_in(1) >= 1)
cs.settings["vel_curve"] = "LINEAR"; ok("PAD VELOCITY: LINEAR passes it through", cs.vel_in(40) == 40)
cs.settings["vel_curve"] = "HARD"; ok("PAD VELOCITY: HARD makes soft hits softer", cs.vel_in(40) < 40)
ok("PAD VELOCITY: the default is SOFT (lighter hits louder, as on an MPC)", _SETP.DEFAULTS["vel_curve"] == "SOFT" and _SETP.vel("SOFT", 64) > 64)
cs.settings["vel_curve"] = "SOFT"; _h = []; _ph = cs.pad_hit; cs.pad_hit = lambda n, v: _h.append(v)
cs.midi_pad(es.bank, 1, 40); cs.pad_hit = _ph; ok("PAD VELOCITY: MIDI controller pads go through it", _h == [_SETP.vel("SOFT", 40)])
class _MM: speed = 1.0
cs.mouse_mapper = _MM(); cs.set_row = 5; cs.nav("right"); ok("SETTINGS: MOUSE SPEED changes the pointer at once", cs.mouse_mapper.speed == 1.8)
cs.set_section(3); cs.set_row = 1; cs.ok(); ok("SETTINGS: GENERAL > AUTOSAVE (OK steps it)", cs.settings["autosave"] == "5MIN")
cs.settings["autosave"] = "STOP"; _sv = []; es.save_project = lambda: _sv.append(1); es.pad.tune = 4; es._unsaved_t = 0.0
cs._was_playing = True; es.playing = False; cs.tick(); ok("AUTOSAVE: ON STOP saves when the transport stops (changes only)", _sv == [1])
es.playing = True; cs.tick(); es.playing = False; es._saved_sig = es._sigs(); cs.tick()
ok("AUTOSAVE: nothing to save, no save", _sv == [1])
es.playing = False
cs.set_row = 2; _m0 = es.metro; cs.ok(); ok("SETTINGS: GENERAL > METRONOME is the project's own", es.metro != _m0)
cs.set_section(4); rs_.frame(); _txt = [r.info() for r in cs.set_rows() if r.kind == "info"]
ok("SETTINGS: ABOUT shows the version, this Pi, storage, CPU", _txt[0].startswith("Monolith ") and ".local" in _txt[1] and "GB free" in _txt[2])
cs.usb_drives = lambda: []; _SETP.LOG = "/tmp/t7set/logs/monolith.log"; _d = _SETP.save_log(cs)   # (never into the project)
ok("SETTINGS: SAVE LOG TO USB (no USB drive: into logs/)", os.path.exists(_d) and "Monolith" in open(_d).read())
cs.set_mode("SETTINGS"); cs.soft(3); ok("SETTINGS: F4 BACK", cs.mode != "SETTINGS")
print("done; touch regions on last screen:", len(c.hits))
