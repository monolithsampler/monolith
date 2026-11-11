import math
"""
ui.py - controls logic for Monolith (v7). The drawing code is in screens.py.

Screens (800x480):  MAIN | SEQ (sequence + tracks, DAW style) | GRID (piano-roll) | STEP (16 pads = 16 steps)
                    PROG (drum program / pad editor) | SAMPLE (record) | CHOP (non-destructive chop) | MIXER | FX | SONG
Hardware: 16 pads, 4 Q-link knobs, 24 buttons on the Arduino (see uicore.BTN), D-pad + OK + jog wheel on the Pi.
"""
import os
import time
import numpy as np
from engine import OUT_SR, OUT_NAMES, QUANT, BANKS, MODES, NPROG, NSEQ, PPQ, NOTE_KINDS, KIND_NAMES, PAD_MODES, SCALES, CHORDS, NOTE_NAMES, note_name, MAX_BARS, TIMINGS, MACHINES

QLINK_MODES = ("SCREEN", "PROJECT", "PAD", "TRACK")      # what the four Q knobs control (tap the pill on the Q strip, SHIFT + jog push)
GATES = [(12, "1/32"), (24, "1/16"), (48, "1/8"), (96, "1/4"), (192, "1/2")]
import fx as fxlib
from uicore import *


def lin(label, obj, attr, lo, hi, fmt, rnd=None, after=None):
    """A Q-link that maps 0..1 onto obj.attr in lo..hi."""
    def get(): return (getattr(obj, attr) - lo) / float(hi - lo)
    def set_(f):
        v = lo + f * (hi - lo)
        if rnd is not None: v = round(v, rnd) if rnd > 0 else int(round(v))
        setattr(obj, attr, v)
        if after: after()
    return (label, get, set_, lambda: fmt(getattr(obj, attr)))


from engine import fmt_st as E_fmt_st
import engine as E_eng


import settingspage as _SET
SETTINGS_DEFAULTS = _SET.DEFAULTS


class Controls:
    def __init__(self, eng):
        self.e = eng
        self.mode, self.shift = "MAIN", False
        self.shift_studio, self.shift_t, self.shift_used = False, 0.0, False    # SHIFT: from the Studio? held since, used for something?
        self.confirm = None                                       # a question on screen: {"title", "text", "keys": [(label, fn) x 4]}
        self.asr_keys = self._ui_setting("asr_keys", False)       # ASR-10 MAIN: the ASR's own keys and pages (asrpanel.py), or the classic screen
        self._asr = None
        self.settings = dict(SETTINGS_DEFAULTS); self.settings.update(self._ui_settings_all())   # SETTINGS (ui.json, this Pi)
        self.set_sec, self.set_row, self.set_pending = 0, 0, False
        self.restart_fn = None                                    # sampler_os: restarts Monolith (APPLY)
        self.mouse_mapper = None; self.xruns = None; self.audio_now = ""
        self._was_playing, self._auto_t = False, time.time()
        self._jog_t, self._jog_run = 0.0, 0                       # jog speed (fast turns take bigger steps)
        self.armed, self.pot, self.pot_seen = [False] * 4, [0] * 4, [False] * 4   # pot_seen: a real knob has reported
        self.step_vel = 100
        self.erase_down, self.erase_t, self.erase_used = False, 0.0, False
        self.taps = []
        self.hits, self.drag = [], None
        # per-screen state
        self.g_tick, self.g_lane, self.g_bars, self.g_off, self.g_sel = 0, 0, 2, 0, None
        self.g_tool, self.g_set, self.g_box = "DRAW", [], None      # GRID: the tool, the selected notes, the marquee being dragged
        self._g_acc = [0.0, 0.0]                                    # Q-link remainders (nudge, length)
        self.g_lanes = 8                                              # GRID shows 8 big lanes (touch friendly) or all 16
        self.g_view = "OFF"                                           # GRID bottom lane: OFF (notes get the room), VEL or AUTO
        self.g_auto = 0                                               # which automation target the AUTO lane shows
        self._clear_t = 0.0                                           # CHOP: CLEAR ALL needs a second tap within 3 s
        self.step_page, self.step_cursor = 0, 0
        self.prog_row, self.picking, self.pick_cur = 3, False, 0
        self.prog_tab = 1                                             # PROG: 0 GLOBAL, 1 SAMPLES, 2 ENVELOPES, ... EFFECTS
        self.pw_zoom, self.pw_snap = False, True                      # PROG waveform: zoomed onto the region; snap to zero crossings
        self.chop_mode, self.chop_n, self.chop_sens, self.chop_bpm, self.chop_div = 0, 8, 0.25, 90.0, 8
        self.chop_cursor, self.chop_sel, self.chop_v0, self.chop_v1 = 0, 0, 0.0, 1.0
        self.seq_off, self.seq_bars = 0, 4
        self.mute_solo = False                                        # MUTE page: taps and pads solo instead of mute
        self.mute_page, self.mute_groups = 0, False                   # MUTE: tracks 1-8 / 9-16; GROUPS: tap a strip's group to change it
        self.prog_front = False                                       # PROG is one set of tabs (the old separate front panel is retired)
        self.step_res, self.step_accent = 24, False                   # STEP: ticks per step (1/8 48, 1/16 24, 1/32 12); ACCENT: taps at 127
        self.chop_snap, self.chop_fade = True, True                   # CHOP: markers snap to zero crossings; TO PADS gives slices short fades
        self.chop_src = None                                           # CHOP: its own sample (a take, a loaded file, < >), not the pad's
        self.br_filter, self.br_sort, self.br_audition, self.br_to = "ALL", "NAME", True, "PAD"
        self.br_import = None                                         # BROWSE: the MPC project the IMPORT window is open for
        self.kbd = None                                               # on-screen keyboard while naming something (see text_entry)
        self.pj_cur = 0                                               # PROJECTS page: highlighted row
        self.menu_cur = 0                                             # MENU page: highlighted tile
        self.lcd_cur = None                                           # MAIN in a machine mode: the field under the cursor
        self.ed_op, self.ed_row, self.ed = 0, 0, {}                    # EDIT page: operation, highlighted row, its settings
        self.mix_page, self.mix_row = 0, 0
        # the console (MIXER): which view, which strip is selected, what the jog / Q-links change, the EQ page
        self.mix_view, self.mix_strip, self.mix_param, self.mix_send = "CHANNELS", 0, 0, 0
        self.eq_open, self.eq_band, self.eq_analyser, self.eq_ab = False, 2, True, {}
        self.fx_target, self.fx_cursor, self.fx_page = 0, 0, 0       # fx_target 0-63 = pad, 64 = master, 65-68 = program insert 1-4
        self.fx_items = [('', '', '- none -')] + fxlib.discover()
        self.mpick = None                                             # MAIN: the machine picker is open (the highlighted card)
        self.fx_browse = False                                        # FX: the effect library is open over the faceplate
        self.valve_case, self.valve_pick = None, 0                    # FX valve drive: the valve case open for V1 / V2, valve highlighted
        self.song_cur = 0
        self.main_field = "seq"             # MAIN (MODERN): the display field the arrows pick and the wheel changes
        self.editor_fx, self.editor_req, self.editor_view = None, None, None
        self.editor_zooms = {}                              # last zoom per plug-in (path -> factor)
        import midi as _midi
        self.midi_map = _midi.MidiMap(__import__("os").path.join(eng.app_dir, "midi.json"))   # MIDI setup belongs to the machine, not a project
        eng.clock_mode, eng.bend_range = self.midi_map.clock, self.midi_map.bend_range
        self.midi_learn, self.midi_seen, self.midi_io = None, 0.0, None   # learn target, last MIDI activity, the MidiIO
        self.midi_row = 0                                   # MIDI page cursor
        self.k_top = 72                                     # piano roll: highest note shown
        self.track_setup = None                             # SEQ: track number whose setup panel is open
        self.editor_obj, self.editor_where = None, ""       # what the plug-in window shows, and a label for its title bar
        self.br_dir, self.br_cur, self.br_items, self.br_msg = None, 0, [], ""   # BROWSE: folder (None = places), cursor
        self.ex_song, self.ex_mix, self.ex_tail, self.ex_dest = False, True, 2.0, 0     # TRACK OUT page
        self.ex_sel, self.ex_files, self.ex_thread, self.ex_err = None, [], None, ""
        self._drives = []                                    # USB drives seen by the browser: (label, device, mountpoint, fstype)
        self._run = None                                     # command runner (tests replace it)
        self.qlink_mode = "SCREEN"
        self.pads_row = 0                                   # PADS page cursor
        self.pad_flash = {}                                 # pad (1-16) -> time it was hit, for tiles in the pad modes
        self.prev_mode = "MAIN"   # the plug-in window: opened / closed by the display loop (X11 thread)

    # ---------- helpers ----------
    @property
    def slot(self): return self.e.pad
    @property
    def src(self):
        """the sample CHOP is working on: its own pick (a recording, a loaded file, < > through the project's samples),
        else the selected pad's sample"""
        cs = getattr(self, "chop_src", None)
        if cs is not None and cs in self.e.sources: return cs
        return self.e.pad.src

    def chop_open(self, src):
        """CHOP on this sample (no pad involved until CONVERT)"""
        self.chop_src = src
        self.set_mode("CHOP")

    def chop_pick(self, d):
        """< > on CHOP: the next / previous sample in the project (newest first)"""
        ss = list(reversed(self.e.sources))
        if not ss: return
        cur = self.src
        k = ss.index(cur) if cur in ss else -1
        self.chop_src = ss[(k + d) % len(ss)]
        self.chop_v0, self.chop_v1, self.chop_sel, self.chop_cursor = 0.0, 1.0, 0, 0

    def chop_convert(self):
        """F4 CONVERT: where the slices go - NEW PROGRAM (pads A01.. of an empty program, WARP at the loop's tempo), TO
        PADS (this program, from the selected pad), NEW SAMPLES (each slice its own sample). Pads keep pointing at the
        original sample, so moving a marker later moves them too; nothing is cut unless NEW SAMPLES."""
        s = self.src
        if s is None: self.say("no sample to convert"); return
        n = len(s.regions())
        self.confirm = {"title": f"CONVERT {s.name.upper()[:18]}", "text": f"{n} slice{'s' if n != 1 else ''}: where do they go?",
                        "keys": [("CANCEL", None), ("NEW SAMPLES", self.chop_new_samples), (f"TO PADS {BANKS[self.e.pad_idx // 16]}{self.e.pad_idx % 16 + 1:02d}", self.chop_assign),
                                 (HOT("NEW PROGRAM"), self.chop_new_program)]}

    def chop_new_program(self):
        e, s = self.e, self.src
        pr = next((q for q in e.programs if all(pd.empty for pd in q.pads)), None)
        if pr is None: self.say("no empty program left: use TO PADS"); return
        pr.name = s.name.upper()[:16]
        k = e.chop_to_pads(s, 0, pr, bpm=self.chop_bpm if self.chop_mode == 2 else None)
        if self.chop_fade:
            for q in pr.pads[:k]: q.fade_in, q.fade_out = max(q.fade_in, 1), max(q.fade_out, 5); e.pad_changed(q)
        pn = e.programs.index(pr)
        # into the beat: the program goes on an empty track of this sequence (this one if it is empty), which is selected,
        # so REC + pads records the slices straight away next to the other tracks
        sq = e.seq
        tr = e.track if not e.track.events else next((t for t in sq.tracks if not t.events and t.kind == "drum"), None)
        if tr is None:
            self.say(f"program {pn + 1} {pr.name}: {k} slices on A01-A{k:02d} (no empty track: set one on MAIN)"); return
        tr.prog, tr.kind = pn, "drum"
        if tr.name.startswith("Track "): tr.name = pr.name.title()[:14]
        e.cur_track, e.bank = tr.n, 0
        self.say(f"{pr.name}: {k} slices on pads A01-A{k:02d}, track {tr.n + 1} of {sq.name}: REC to play them in")

    def chop_new_samples(self):
        e, s = self.e, self.src
        made = 0
        for k, (a, b) in enumerate(s.regions()):
            if b - a < 32: continue
            nm, j = f"{s.name}_{k + 1:02d}"[:24], 2
            while e.source_by_name(nm) is not None: nm, j = f"{s.name}_{k + 1:02d}_{j}"[:24], j + 1
            e.add_source(nm, s.raw[a:b].copy(), dirty=True); made += 1
        self.say(f"{made} new samples in the project ({s.name}_01..)")

    # ---------- settings kept with the software (not a project): ui.json ----------
    def _ui_setting(self, key, default):
        import json, os
        try: return json.load(open(os.path.join(self.e.app_dir, "ui.json"))).get(key, default)
        except Exception: return default

    def _ui_settings_all(self):
        import json, os
        try: d = json.load(open(os.path.join(self.e.app_dir, "ui.json")))
        except Exception: return {}
        return {k: v for k, v in d.items() if k in SETTINGS_DEFAULTS}

    # ---------- SETTINGS (settingspage.py) ----------
    def set_rows(self): return _SET.rows(self, _SET.SECTIONS[self.set_sec])

    def set_section(self, k):
        self.set_sec = k % len(_SET.SECTIONS); self.set_row = 0

    def set_apply(self):
        """APPLY: restarts Monolith with the new audio / controller / screen settings (asks to save first)"""
        dirty = self.e.unsaved(full=True)
        def go(save):
            if save: self.e.save_project()
            self.set_pending = False
            if self.restart_fn: self.restart_fn()
            else: self.say("settings saved: they take effect when Monolith starts again")
        self.ask("APPLY SETTINGS?", "Monolith restarts to apply them (the sound stops for a few seconds)."
                 + (" Save the project first?" if dirty else ""),
                 "SAVE + RESTART" if dirty else "RESTART", lambda: go(dirty),
                 "DON'T SAVE" if dirty else None, (lambda: go(False)) if dirty else None)

    def vel_in(self, v):
        """a pad's velocity through the PAD VELOCITY curve"""
        return _SET.vel(self.settings.get("vel_curve", "LINEAR"), v)

    def tick(self):
        """once a frame: AUTOSAVE (only while stopped, so a save never touches a playing beat)"""
        e, mode_ = self.e, self.settings.get("autosave", "OFF")
        playing = e.playing
        if mode_ != "OFF" and not playing:
            due = (mode_ == "STOP" and self._was_playing) or (mode_ == "5MIN" and time.time() - self._auto_t > 300)
            if due:
                self._auto_t = time.time()
                if e.unsaved(full=True): e.save_project()
        self._was_playing = playing

    def _save_ui_setting(self, key, value):
        import json, os
        path = os.path.join(self.e.app_dir, "ui.json")
        try: d = json.load(open(path))
        except Exception: d = {}
        d[key] = value
        try: json.dump(d, open(path, "w"))
        except OSError: pass

    # ---------- the ASR-10's own keys and pages on MAIN (asrpanel.py), switched on with ASR KEYS on the rail ----------
    @property
    def asr(self):
        if self._asr is None:
            import asrpanel
            self._asr = asrpanel.Panel(self)
        return self._asr

    def asr_on(self):
        """the ASR keys are what MAIN is showing now"""
        return self.asr_keys and self.e.machine == "ASR-10" and self.mode == "MAIN" and self.mpick is None

    def toggle_asr_keys(self):
        self.asr_keys = not self.asr_keys; self._save_ui_setting("asr_keys", self.asr_keys)
        self.say("ASR keys: the ASR-10's own pages" if self.asr_keys else "ASR keys off: the classic ASR-10 screen")

    def asr_qlinks(self):
        """the page's main parameters on Q1-Q4 (knobs move them by steps from where they are)"""
        pn = self.asr
        if not hasattr(self, "_asr_qpos"): self._asr_qpos = {}
        out = []
        if pn.ask is not None and pn.ask.get("adj"):
            key = ("ask", id(pn.ask))
            def qset(f, key=key):
                old = self._asr_qpos.get(key, 0.5); st = int(round((f - old) * 24))
                if st: pn.ask["adj"](st); self._asr_qpos[key] = old + st / 24.0
            out.append((pn.ask.get("qname", "VALUE").title(), lambda key=key: self._asr_qpos.get(key, 0.5), qset,
                        lambda: pn.ask["text"]().split("=")[-1] if pn.ask is not None else ""))
        else:
            for k, it in enumerate(pn.qlinks()):
                key = (pn.mode, pn.page, it.name)
                def qset(f, it=it, key=key):
                    old = self._asr_qpos.get(key, 0.5); st = int(round((f - old) * 100))
                    if st: pn.adjust_item(it, st); self._asr_qpos[key] = old + st / 100.0
                out.append((it.name.title(), lambda key=key: self._asr_qpos.get(key, 0.5), qset, lambda it=it: pn.value_text(it)))
        while len(out) < 4: out.append(("-", lambda: 0.0, lambda f: None, lambda: ""))
        return out[:4]

    # ---------- MIDI (see midi.py) ----------
    def button_name(self, name):
        if name.replace(" ", "") == "BANK": self.bank_button(); return
        i = BTN[name.replace(" ", "")]
        self.button(i, True); self.button(i, False)

    def midi_button(self, name, down):
        """a learned button on the MIDI controller: press and release (SHIFT and ERASE are held)"""
        if self.midi_learn: return
        if name in ("PADMODE", "QLINKMODE", "BANK"):          # learnable functions that have no key of their own
            if down and name == "BANK": self.bank_button()
            elif down: self.cycle_pad_mode() if name == "PADMODE" else self.cycle_qlink()
            return
        self.button(BTN[name], down)

    # MAIN on MODERN works like an MPC's main screen: the arrows move a cursor over the display's fields, the wheel
    # (DATA + / -) changes the one under it. Playing, a new sequence starts when this one ends.
    MAIN_ROWS = [["seq", "bars"], ["trk", "pgm"], ["swing", "q", "bpm"]]

    def main_move(self, d):
        rows = self.MAIN_ROWS
        ri = next(i for i, r_ in enumerate(rows) if self.main_field in r_)
        ci = rows[ri].index(self.main_field)
        if d in ("left", "right"):
            flat = [f for r_ in rows for f in r_]
            self.main_field = flat[(flat.index(self.main_field) + (1 if d == "right" else -1)) % len(flat)]
        else:
            ri = (ri + (1 if d == "down" else -1)) % len(rows)
            self.main_field = rows[ri][min(ci, len(rows[ri]) - 1)]

    MAIN_LABELS = {"seq": "SEQ", "bars": "BARS", "trk": "TRK", "pgm": "PGM", "swing": "SWING", "q": "Q", "bpm": "BPM"}

    def main_value(self, f):
        """the value alone (the display prints its label next to it, so value and heading look different)"""
        e = self.e; sq = e.seq; tr = e.track
        if f == "seq":
            if e.next_seq is not None: return f"{e.cur_seq + 1:02d} > {e.next_seq + 1:02d}"
            empty = not any(t.events for t in sq.tracks)
            return f"{e.cur_seq + 1:02d} " + ("EMPTY" if empty else sq.name.upper()[:12])
        return {"bars": str(sq.bars), "trk": f"{tr.n + 1:02d} {tr.name.upper()[:9]}",
                "pgm": e.programs[tr.prog].name.upper()[:9], "swing": f"{sq.swing * 100:.0f}%",
                "q": QUANT[e.qgrid][0], "bpm": f"{sq.bpm:.1f}"}[f]

    def main_adjust(self, n, acc=None):
        e = self.e; sq = e.seq; f = self.main_field
        acc = n if acc is None else acc
        if f == "seq":
            base = e.next_seq if (e.playing and e.next_seq is not None) else e.cur_seq
            e.queue_seq((base + n) % NSEQ)
        elif f == "bars": e.set_bars(int(clamp(sq.bars + n, 1, MAX_BARS))); self.say(f"{e.seq.bars} bars")
        elif f == "trk": e.cur_track = (e.cur_track + n) % 16
        elif f == "pgm": self.track_prog_step(e.cur_track, 1 if n > 0 else -1)
        elif f == "swing": sq.swing = round(clamp(sq.swing + 0.01 * n, 0.5, 0.75), 2)
        elif f == "q": e.qgrid = int(clamp(e.qgrid + n, 0, len(QUANT) - 1))
        else: sq.bpm = clamp(round(sq.bpm + (0.1 if self.shift else 0.5) * acc, 1), 60.0, 180.0)

    def prog_view(self):
        """the part of the pad's sample PROG's wave view shows: all of it, or (ZOOM) the region and a little either side"""
        p = self.e.pad
        if p.src is None: return 0, 1
        if self.pw_zoom:
            m_ = max(int(0.1 * p.length), int(0.02 * OUT_SR))
            return max(0, p.start - m_), min(p.src.length, p.end + m_)
        return 0, p.src.length

    def track_prog_step(self, k, d=1):
        """MAIN: the program track k plays (the PGM chip on its row): the next / previous program that has sounds"""
        e = self.e
        tr = e.seq.tracks[k % 16]
        used = [i for i, p in enumerate(e.programs) if not all(q.empty for q in p.pads)] or [0]
        if tr.prog not in used: used = sorted(used + [tr.prog])
        tr.prog = used[(used.index(tr.prog) + d) % len(used)]
        e.cur_track = tr.n
        self.say(f"{tr.name}: program {tr.prog + 1} {e.programs[tr.prog].name}")

    def bank_button(self):
        """BANK (MIDI-learnable, no key on the panel): next pad bank; with SHIFT, the track's next program"""
        e = self.e
        if self.shift:
            e.track.prog = (e.track.prog + 1) % NPROG; self.say("track program: " + e.prog.name)
        else:
            e.bank = (e.bank + 1) % 4; self.say(f"pad bank {BANKS[e.bank]}")

    def midi_pad(self, bank, n, vel):
        """a pad on the MIDI controller: bank A-D follows the controller's pad bank"""
        if bank != self.e.bank: self.e.bank = bank
        self.pad_hit(n, self.vel_in(vel))

    def midi_key(self, note, vel):
        self.e.key_on(note, vel)
        if self.mode == "GRID" and self.e.track.kind in NOTE_KINDS:
            self.g_lane = note; self.k_follow(note)

    def midi_key_off(self, note):
        self.e.key_off(note)

    def learn_from(self, kind, ch, num):
        t, mp = self.midi_learn, self.midi_map
        if t == "PADS":
            mp.set_pads([]); mp.pad_ch, mp.pad_base = ch, num          # pad 1 + the 63 notes after it (tools/midi_setup.py learns any layout)
            self.say(f"pads: channel {ch}, pad 1 = note {num}")
        else:
            for k in [k for k, v in mp.learned.items() if v == [kind, ch, num]]: del mp.learned[k]   # one control, one job
            mp.learned[t] = [kind, ch, num]
            self.say(f"{t} = {'CC' if kind == 'cc' else 'note'} {num}, channel {ch}")
        mp.save(); self.midi_learn = None

    def k_follow(self, note):
        """keep `note` inside the visible piano-roll range"""
        vis = 12 if self.g_lanes == 8 else 24
        if note > self.k_top: self.k_top = min(127, note + 2)
        elif note <= self.k_top - vis: self.k_top = max(vis - 1, note + vis - 3)

    # ---------- BROWSE: audio files from USB sticks and folders ----------
    AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac", ".snd")
    MPC_EXT = (".all", ".aps", ".pgm", ".xpj")       # MPC2000XL files (the whole folder) and MPC 2.x projects (SP-1200 .sp12: parked, see SP1200_NOTES.md)

    # ---------- USB drives: listed, mounted on a tap, ejected with F1 (works without a desktop) ----------
    def run(self, cmd):
        """run a command, (ok, text); tests swap self._run"""
        if self._run is not None: return self._run(cmd)
        import subprocess
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return r.returncode == 0, (r.stdout + r.stderr).strip()
        except Exception as ex: return False, str(ex)

    def usb_drives(self):
        """partitions of USB drives / card readers: [(label, device, mountpoint or None, fstype)]"""
        import json
        ok_, txt = self.run(["lsblk", "-J", "-p", "-o", "NAME,LABEL,MOUNTPOINT,FSTYPE,SIZE,RM,TRAN,TYPE"])
        if not ok_: return []
        try: devs = json.loads(txt).get("blockdevices", [])
        except ValueError: return []
        out = []
        for d in devs:
            if d.get("type") != "disk" or not (d.get("tran") == "usb" or d.get("rm") in (True, "1", 1)): continue
            for part in (d.get("children") or [d]):
                mp, fs = part.get("mountpoint"), part.get("fstype")
                if not fs or fs in ("swap",) or (mp and (mp == "/" or mp.startswith("/boot"))): continue
                label = part.get("label") or f"{part.get('size', '')} drive".strip()
                out.append((label, part["name"], mp or None, fs))
        return out

    def usb_mount(self, dev, label="", fstype=""):
        """udisks first (no root needed, see README), then sudo mount; returns the mount point or None"""
        import os, re
        ok_, txt = self.run(["udisksctl", "mount", "-b", dev, "--no-user-interaction"])
        m = re.search(r" at (/\S+?)\.?$", txt or "")
        if ok_ and m: return m.group(1)
        mp = "/media/sampler/" + ("".join(ch for ch in (label or os.path.basename(dev)) if ch.isalnum() or ch in "-_") or "usb")
        opts = ["-o", f"uid={os.getuid()},gid={os.getgid()}"] if fstype in ("vfat", "exfat", "ntfs", "ntfs3", "msdos") else []
        if self.run(["sudo", "-n", "mkdir", "-p", mp])[0] and self.run(["sudo", "-n", "mount"] + opts + [dev, mp])[0]: return mp
        self.say("could not mount the drive (see README: USB drives)"); return None

    def usb_eject(self, dev, mp):
        import os
        try: os.sync()
        except Exception: pass
        if self.run(["udisksctl", "unmount", "-b", dev, "--no-user-interaction"])[0] or self.run(["sudo", "-n", "umount", mp])[0]:
            self.say("safe to unplug"); return True
        self.say("drive is busy - not ejected"); return False

    def br_places(self):
        import glob, os
        out = [("Project samples", self.e.sample_dir)]
        exp = os.path.join(self.e.dir, "exports")
        if os.path.isdir(exp): out.append(("Track outs (this project)", exp))
        self._drives = self.usb_drives()
        for label, dev, mp, fs in self._drives:
            out.append((f"USB  {label}", mp) if mp else (f"USB  {label}  - tap to mount", ("mount", dev, label, fs)))
        for p in sorted(glob.glob("/media/*/*") + glob.glob("/media/*")):    # drives a desktop mounted (when lsblk is missing)
            if os.path.isdir(p) and os.path.ismount(p) and not any(isinstance(q[1], str) and (q[1] == p or p.startswith(q[1] + "/")) for q in out):
                out.append(("Drive  " + os.path.basename(p), p))
        out.append(("Home", os.path.expanduser("~")))
        return out

    def br_selected_drive(self):
        """the mounted USB drive under the cursor on the places list: (device, mountpoint) or None"""
        if self.br_dir is not None or not self.br_items: return None
        path = self.br_items[self.br_cur][1]
        return next(((dev, mp) for _, dev, mp, _ in self._drives if mp and mp == path), None)

    def br_refresh(self):
        import os
        if self.br_dir is None:
            self.br_items = [(n, p, True) for n, p in self.br_places()]
        else:
            try: names = sorted(os.listdir(self.br_dir), key=str.lower)
            except OSError as ex: names = []; self.br_msg = str(ex)[:60]
            dirs = [(n + "/", os.path.join(self.br_dir, n), True) for n in names if not n.startswith(".") and os.path.isdir(os.path.join(self.br_dir, n))]
            ext = {"AUDIO": self.AUDIO_EXT, "PROJECTS": self.MPC_EXT}.get(self.br_filter, self.AUDIO_EXT + self.MPC_EXT)
            files = [(n, os.path.join(self.br_dir, n), False) for n in names if n.lower().endswith(ext)]
            if self.br_sort == "DATE":
                def mt(f):
                    try: return -os.path.getmtime(f[1])
                    except OSError: return 0
                files.sort(key=mt)
            elif self.br_sort == "SIZE":
                def sz(f):
                    try: return -os.path.getsize(f[1])
                    except OSError: return 0
                files.sort(key=sz)
            self.br_items = [("..  (up)", None, True)] + dirs + files
        self.br_cur = clamp(self.br_cur, 0, max(0, len(self.br_items) - 1))

    def br_open(self, i=None):
        """folders open; a file is previewed (tap it again, or F3, to load it)"""
        import os
        i = self.br_cur if i is None else i
        if not self.br_items: return
        name, path, isdir = self.br_items[i]
        if isdir and isinstance(path, tuple):                          # an unmounted USB drive: mount it and open it
            mp = self.usb_mount(path[1], path[2], path[3])
            if mp: self.br_dir, self.br_cur = mp, 0; self.say(f"{path[2]} mounted")
            self.br_refresh(); return
        if isdir:
            self.br_msg, self._br_heard = "", None                  # a message about a file no longer on screen goes
            if path is None:
                up = os.path.dirname(self.br_dir.rstrip("/"))
                places = [p for _, p in self.br_places()]
                self.br_dir = None if self.br_dir in places else up
            else: self.br_dir = path
            self.br_cur = 0; self.br_refresh(); return
        if self.br_cur == i and getattr(self, "_br_heard", None) == path:
            self.br_load(); return
        self.br_cur = i
        if not self.br_audition and not path.lower().endswith(self.MPC_EXT):
            self._br_heard = path; self.br_msg = f"{name} - tap again or LOAD"; return
        if path.lower().endswith(self.MPC_EXT):                        # an MPC project: say what is in it, import on the next tap
            import mpc_import, mpc2_import, sp1200_import
            try: self.br_msg = (mpc2_import.describe(path) if path.lower().endswith(".xpj") else sp1200_import.describe(path) if path.lower().endswith(".sp12")
                                else mpc_import.describe(os.path.dirname(path))) + \
                     ". Tap again or F3: IMPORT (replaces this project, the old one is kept in backups/)"
            except Exception as ex: self.br_msg = f"cannot read {name}: {str(ex)[:40]}"
            self._br_heard = path; return
        try: secs = self.e.preview_file(path); self.br_msg = f"{name}  {secs:.2f} s - tap again or F3 to load"; self._br_heard = path
        except Exception as ex: self.br_msg = f"cannot read {name}: {str(ex)[:40]}"

    def _br_drive(self):
        """the USB drive to eject: the one under the cursor on the places list, or the one being browsed"""
        drv = self.br_selected_drive()
        if drv or self.br_dir is None: return drv
        return next(((dev, mp) for _, dev, mp, _ in getattr(self, "_drives", []) if mp and (self.br_dir == mp or self.br_dir.startswith(mp + "/"))), None)

    def br_info(self, path):
        """length, rate, bits of an audio file (cached) - for the preview panel"""
        cache = self.__dict__.setdefault("_br_info", {})
        if path in cache: return cache[path]
        info = None
        try:
            import soundfile as sf
            i = sf.info(path)
            bits = {"PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "FLOAT": 32, "PCM_U8": 8, "PCM_S8": 8, "DOUBLE": 64}.get(i.subtype, 0)
            info = (i.frames / float(i.samplerate), i.samplerate, bits, i.channels)
        except Exception:
            try:
                import wave
                with wave.open(path) as w: info = (w.getnframes() / float(w.getframerate()), w.getframerate(), w.getsampwidth() * 8, w.getnchannels())
            except Exception: info = None
        if len(cache) > 400: cache.clear()
        cache[path] = info
        return info

    def br_peaks(self, path, n=200):
        """a small min / max outline of a file for the preview (cached; long files: the first 20 s)"""
        cache = self.__dict__.setdefault("_br_peaks", {})
        if path in cache: return cache[path]
        out = None
        try:
            from engine import read_audio
            x, sr, _ = read_audio(path)
            x = np.asarray(x, np.float32)
            if x.ndim > 1: x = x.mean(axis=1)
            x = x[: int(sr * 20)]
            m = len(x) // n * n
            if m: x = x[:m].reshape(n, -1); out = (x.min(axis=1), x.max(axis=1))
        except Exception: out = None
        if len(cache) > 50: cache.clear()
        cache[path] = out
        return out

    def br_mpc_selected(self):
        it = self.br_items[self.br_cur] if self.br_items and self.br_dir is not None else None
        return bool(it and not it[2] and it[1] and it[1].lower().endswith(self.MPC_EXT))

    def import_mpc(self, path):
        """import an MPC2000XL folder or an MPC 2.x .xpj project (replaces the project; the old one goes to backups/)"""
        import os, mpc_import, mpc2_import, sp1200_import
        try:
            rep = mpc2_import.import_project(self.e, path) if path.lower().endswith(".xpj") else \
                sp1200_import.import_project(self.e, path) if path.lower().endswith(".sp12") else \
                mpc_import.import_folder(self.e, path if os.path.isdir(path) else os.path.dirname(path))
        except Exception as ex:
            self.br_msg = f"import failed: {str(ex)[:60]}"; self.say("MPC import failed"); return None
        try: open(os.path.join(self.e.dir, "mpc_import_report.txt"), "w").write(rep.text() + "\n")
        except OSError: pass
        nseq = sum(1 for sq in self.e.seqs if any(t.events for t in sq.tracks))
        nprog = sum(1 for p in self.e.programs if any(not x.empty for x in p.pads))
        self.br_msg = (f"Imported {nseq} sequences, {nprog} programs, {len(self.e.sources)} sounds. "
                       + (f"{len(rep.warn)} thing{'s' if len(rep.warn) != 1 else ''} could not come across: see mpc_import_report.txt" if rep.warn else "Everything came across."))
        self.fx_target, self.chop_cursor, self._br_heard = 0, 0, None
        self.say(f"MPC project imported: {nseq} seq")
        return rep

    def br_load(self):
        name, path, isdir = self.br_items[self.br_cur] if self.br_items else (None, None, True)
        if isdir or path is None: return
        if path.lower().endswith(self.MPC_EXT):
            self.br_import = path; return                                # the IMPORT window: what is in it, then IMPORT / CANCEL
        try:
            s = self.e.import_file(path)
            if self.br_to == "CHOP":                                       # into the project's samples, opened in CHOP (no pad)
                self.say(f"{s.name} loaded: chop it, then CONVERT"); self.chop_open(s); return
            pad = self.e.pad; pad.assign(s); self.e.pad_changed(pad)
            self.say(f"{s.name} -> pad {BANKS[self.e.bank]}{self.e.sel + 1:02d}")
        except Exception as ex: self.say(f"cannot load: {str(ex)[:40]}")

    # ---------- on-screen keyboard: naming projects, sequences, tracks, programs, samples ----------
    KBD_ROWS = [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL-"), list("ZXCVBNM_.'"), ["CASE", "SPACE", "DEL", "CLEAR", "OK"]]

    def text_entry(self, title, text, maxlen, done):
        """open the keyboard; done(text) runs on OK (not on CANCEL)"""
        self.kbd = {"title": title, "text": text[:maxlen], "max": maxlen, "done": done, "row": 1, "col": 0, "caps": True}

    def kbd_press(self, key):
        k = self.kbd
        if k is None: return
        if key == "OK": self.kbd_finish(True)
        elif key == "CANCEL": self.kbd_finish(False)
        elif key == "DEL": k["text"] = k["text"][:-1]
        elif key == "CLEAR": k["text"] = ""
        elif key == "CASE": k["caps"] = not k["caps"]
        elif len(k["text"]) < k["max"]:
            k["text"] += " " if key == "SPACE" else (key if k["caps"] else key.lower())

    def kbd_finish(self, ok):
        k, self.kbd = self.kbd, None
        if ok and k and k["text"].strip():
            try: k["done"](k["text"].strip())
            except Exception as ex: self.say(f"could not do that: {str(ex)[:40]}")

    def kbd_move(self, d):
        k = self.kbd
        rows = self.KBD_ROWS
        if d in ("up", "down"): k["row"] = clamp(k["row"] + (1 if d == "down" else -1), 0, len(rows) - 1)
        else: k["col"] += 1 if d == "right" else -1
        k["col"] = k["col"] % len(rows[k["row"]])

    def kbd_jog(self, n):
        k = self.kbd
        flat = [(r, c_) for r, row in enumerate(self.KBD_ROWS) for c_ in range(len(row))]
        i = flat.index((k["row"], min(k["col"], len(self.KBD_ROWS[k["row"]]) - 1)))
        k["row"], k["col"] = flat[(i + n) % len(flat)]

    def cycle_clock(self):
        mp, e = self.midi_map, self.e
        mp.clock = {"OFF": "SEND", "SEND": "FOLLOW", "FOLLOW": "OFF"}[mp.clock]
        e.clock_mode, e.ext_bpm, e._ext_clock = mp.clock, None, []
        mp.save()
        self.say({"OFF": "MIDI clock off", "SEND": "MIDI clock: SEND (other gear follows this tempo)",
                  "FOLLOW": "MIDI clock: FOLLOW (tempo, start and stop come from outside)"}[mp.clock])

    def cycle_bend(self):
        mp = self.midi_map
        mp.bend_range = {2: 7, 7: 12, 12: 24, 24: 2}.get(mp.bend_range, 2)
        self.e.bend_range = mp.bend_range; mp.save(); self.say(f"pitch bend range {mp.bend_range} semitones")

    # ---------- MENU page (SHIFT + MAIN, or MENU > on MAIN): the pages that have no key of their own ----------
    MENU_ITEMS = [("PROJECTS", "new, open, save as", "projects"), ("BROWSE", "samples from USB / folders", "browse"),
                  ("EDIT", "bars, copy, quantize, nudge", "edit"), ("PAD MODES", "16 levels, perform, mute", "pads"),
                  ("MIDI", "learn, clock, channels", "midi"), ("TRACK OUT", "export stems as WAVs", "export"),
                  ("SONG", "chain sequences", "song"), ("SAVE", "save the project now", "save"),
                  ("SETTINGS", "audio, controllers, about", "settings")]
    MENU_COLS = 5

    def menu_go(self, i):
        name = self.MENU_ITEMS[i][0]
        if name == "SAVE": self.save(); return
        if name == "EDIT": self.ed_open(); return
        self.set_mode({"PROJECTS": "PROJECTS", "BROWSE": "BROWSE", "PAD MODES": "PADS", "MIDI": "MIDI", "TRACK OUT": "EXPORT", "SONG": "SONG",
                       "SETTINGS": "SETTINGS"}[name])

    MACHINE_SAY = {"MODERN": "MODERN: Monolith's own screen and timing (live swing on 16ths)",
                   "MPC60": "MPC60: its screen and timing - swing goes into the notes, repeats swing",
                   "MPC3000": "MPC3000: its screen and timing - swing goes into the notes, repeats swing",
                   "MPC2000XL": "MPC2000XL: its screen (its timing is not emulated yet)",
                   "SP-1200": "SP-1200: its screen, timing and sound - Q4 = RING, PROG > RPM",
                   "ASR-10": "ASR-10: its display, timing and sound - arrows = pages, F3 = QUANTIZE TRACK"}

    def set_machine(self, m):
        """straight to a machine (the selector keys on MAIN)"""
        if m in MACHINES and m != self.e.machine: self.cycle_machine(MACHINES.index(m) - MACHINES.index(self.e.machine))

    def cycle_machine(self, n=1):
        e = self.e
        e.machine = MACHINES[(MACHINES.index(e.machine) + n) % len(MACHINES)]
        if e.machine == "SP-1200": e.warm_sp()                     # its sounds sampled in now, not at the first hits
        self.lcd_cur = None
        self.say(self.MACHINE_SAY[e.machine])

    def cycle_timing(self): self.cycle_machine()                  # (older name)

    # ---------- the machine picker (CHANGE MACHINE): one tap, straight to it ----------
    PICK = ["MODERN", "MPC60", "MPC3000", "MPC2000XL", "SP-1200", "ASR-10"]

    def open_picker(self):
        if self.mode != "MAIN": self.set_mode("MAIN")
        self.mpick = self.PICK.index(self.e.machine) if self.e.machine in self.PICK else 0

    def close_picker(self): self.mpick = None

    def pick_machine(self, m):
        self.mpick = None
        self.set_machine(m)

    def lcd_tap(self, key):
        """a tap on a field of the machine's screen: the cursor goes there; the 2000XL's soft-key labels act as keys"""
        import machines
        if key.startswith("soft"):
            i = int(key[4:])
            if i == 0: self.set_mode("STEP")
            elif i == 1: self.ed_open()
            else: machines.soft(self.e, self.e.machine, i - 2)
            return
        if self.lcd_cur == key: machines.adjust(self.e, key, 1)    # a second tap steps it, like a turn of the wheel
        self.lcd_cur = key

    def lcd_fields(self):
        import machines
        scr = machines.screen(self.e, self.e.machine, self.lcd_cur)
        return [] if scr is None else [f for f in scr.fields if not f[0].startswith("soft")]

    def lcd_nav(self, d):
        """arrows on a machine's screen: left / right = previous / next field, up / down = the nearest field on the
        line above / below (as on the real machines)"""
        fs = self.lcd_fields()
        if not fs: return
        i = next((k for k, f in enumerate(fs) if f[0] == self.lcd_cur), 0)
        if d in ("left", "right"):
            self.lcd_cur = fs[(i + (1 if d == "right" else -1)) % len(fs)][0]; return
        r, col = fs[i][1], fs[i][2]
        rows = sorted({f[1] for f in fs})
        k = rows.index(r) + (1 if d == "down" else -1)
        if 0 <= k < len(rows):
            same = [f for f in fs if f[1] == rows[k]]
            self.lcd_cur = min(same, key=lambda f: abs(f[2] - col))[0]

    def set_rec_src(self, src):
        e = self.e
        if e.rec_state != "idle": self.say("stop recording first"); return
        e.rec_src = src
        self.say("record: " + ("the audio input" if src == "INPUT" else "the sampler's own output (RESAMPLE)"))

    def rename_seq(self):
        sq = self.e.seq
        self.text_entry(f"NAME SEQUENCE {self.e.cur_seq + 1:02d}", sq.name, 16, lambda t: setattr(sq, "name", t))

    def rename_track(self):
        tr = self.e.track
        self.text_entry(f"NAME TRACK {tr.n + 1:02d}", tr.name, 12, lambda t: setattr(tr, "name", t))

    def rename_program(self):
        pr = self.e.prog
        self.text_entry("NAME PROGRAM", pr.name, 12, lambda t: setattr(pr, "name", t))

    def rename_sample(self):
        src = self.e.pad.src
        if src is None: self.say("this pad has no sample"); return
        self.text_entry("NAME SAMPLE (renames its file at the next save)", src.name, 24,
                        lambda t: self.say("sample renamed: " + self.e.rename_source(src, t)))

    # ---------- EDIT page: sequence / track / pad operations (GRID ALL TRACKS F1, or MENU > EDIT) ----------
    ED_OPS = ["COPY BARS", "INSERT BARS", "DELETE BARS", "TIME SIGNATURE", "QUANTIZE", "NUDGE", "COPY SEQUENCE", "COPY TRACK", "COPY PAD", "FLATTEN PAD"]
    ED_HELP = {"COPY BARS": "copies bars to another place (or end to end), replacing or adding to what is there",
               "INSERT BARS": "adds empty bars; everything after them moves later", "DELETE BARS": "removes bars; what follows moves up",
               "TIME SIGNATURE": "beats per bar and the beat; notes keep their place", "QUANTIZE": "pulls notes toward the grid, with swing",
               "NUDGE": "moves notes earlier or later (96 ticks = one beat)", "COPY SEQUENCE": "the whole sequence over another one",
               "COPY TRACK": "notes, automation and what it plays, onto another track", "COPY PAD": "sample and every setting, onto another pad",
               "FLATTEN PAD": "renders the pad's settings into a new sample (DO IT again puts the original back)"}

    def ed_open(self, op=None):
        self.ed_defaults()
        if op is not None: self.ed_op = self.ED_OPS.index(op)
        self.ed_row = 0
        self.set_mode("EDIT")

    def ed_defaults(self):
        e, sq = self.e, self.e.seq
        bar = int(max(0, e.pos) // sq.bar_ticks) if e.pos < sq.length else 0
        nxt_seq = next((i for i in range(NSEQ) if i != e.cur_seq and not any(t.events for t in e.seqs[i].tracks)), (e.cur_seq + 1) % NSEQ)
        nxt_trk = next((i for i in range(16) if i != e.cur_track and not sq.tracks[i].events), (e.cur_track + 1) % 16)
        nxt_pad = next((i for i in range(64) if i != e.pad_idx and e.prog.pads[i].empty), (e.pad_idx + 1) % 64)
        self.ed = dict(src=bar, nb=1, dst=min(bar + 1, sq.bars - 1), times=1, merge=False, all=True, at=bar, num=sq.num, den=sq.den,
                       sseq=e.cur_seq, dseq=nxt_seq, strk=e.cur_track, dtrk=nxt_trk, dpad=nxt_pad, grid=max(1, e.qgrid),
                       strength=100, swing=int(round(sq.swing * 100)), ticks=0)

    def ed_rows(self):
        e, d, sq = self.e, self.ed, self.e.seq
        op = self.ED_OPS[self.ed_op]
        def step(key, lo, hi, k=1):
            def f(n): d[key] = int(clamp(d[key] + n * k, lo, hi))
            return f
        def flip(key):
            def f(n): d[key] = not d[key]
            return f
        tracks = ("TRACKS", "ALL" if d["all"] else f"track {e.cur_track + 1:02d} only", flip("all"))
        bars = sq.bars
        if op == "COPY BARS":
            return [("FROM BAR", str(d["src"] + 1), step("src", 0, bars - 1)), ("BARS", str(d["nb"]), step("nb", 1, 16)),
                    ("TO BAR", str(d["dst"] + 1), step("dst", 0, MAX_BARS - 1)), ("TIMES", str(d["times"]), step("times", 1, 16)),
                    ("MODE", "ADD TO WHAT IS THERE" if d["merge"] else "REPLACE", flip("merge")), tracks]
        if op == "INSERT BARS":
            return [("BEFORE BAR", str(d["at"] + 1), step("at", 0, bars)), ("BARS", str(d["nb"]), step("nb", 1, 16))]
        if op == "DELETE BARS":
            return [("FROM BAR", str(d["at"] + 1), step("at", 0, bars - 1)), ("BARS", str(d["nb"]), step("nb", 1, 16))]
        if op == "TIME SIGNATURE":
            dens = [2, 4, 8, 16]
            def den(n): d["den"] = dens[clamp(dens.index(d["den"]) + n, 0, 3)]
            return [("BEATS PER BAR", str(d["num"]), step("num", 1, 16)), ("BEAT", f"1/{d['den']}", den)]
        if op == "QUANTIZE":
            def timing(n): self.cycle_machine(1 if n > 0 else -1)
            def shift(n): e.tc_shift = int(clamp(e.tc_shift + n, -48, 48)); e.tc_shift = e.shift_ticks(QUANT[d["grid"]][1])
            g_ = QUANT[d["grid"]][1]
            swing_txt = f"{d['swing']}%" + ("  (1/8 and 1/16 only)" if e.timing == "MPC60" and g_ not in (48, 24) and d["swing"] != 50 else "")
            if e.timing == "ASR":                                    # ASR-10: its own values, nearest step, no swing
                def aq(n): e.asr_q = int(clamp(e.asr_q + n, 0, len(E_eng.ASR_Q) - 1))
                return [("QUANTIZE TO", E_eng.ASR_Q[e.asr_q][0] + "  (ASR-10 values)", aq), ("STRENGTH", f"{d['strength']}%", step("strength", 0, 100, 5)),
                        ("SWING", "none on the ASR-10", lambda n: None), tracks, ("MACHINE", e.machine + "  (ASR-10 timing)", timing)]
            rows = [("GRID", QUANT[d["grid"]][0], step("grid", 1, len(QUANT) - 1)), ("STRENGTH", f"{d['strength']}%", step("strength", 0, 100, 5)),
                    ("SWING", swing_txt, step("swing", 50, 75)), tracks,
                    ("MACHINE", e.machine + ("  (MPC60 timing)" if e.timing == "MPC60" else "  (modern timing)"), timing)]
            if e.timing == "MPC60":
                sh = e.shift_ticks(g_)
                rows.append(("SHIFT TIMING", "OFF" if not sh else f"{abs(sh)} ticks {'EARLIER' if sh < 0 else 'LATER'}", shift))
            return rows
        if op == "NUDGE":
            return [("MOVE BY", f"{d['ticks']:+d} ticks" + (f"  ({d['ticks'] / 96.0:+.2f} beat)" if d["ticks"] else ""), step("ticks", -96, 96)), tracks]
        if op == "COPY SEQUENCE":
            return [("FROM", f"{d['sseq'] + 1:02d} {e.seqs[d['sseq']].name}", step("sseq", 0, NSEQ - 1)),
                    ("TO", f"{d['dseq'] + 1:02d} {e.seqs[d['dseq']].name}" + ("" if not any(t.events for t in e.seqs[d['dseq']].tracks) else "  (has notes!)"),
                     step("dseq", 0, NSEQ - 1))]
        if op == "COPY TRACK":
            return [("FROM", f"{d['strk'] + 1:02d} {sq.tracks[d['strk']].name}", step("strk", 0, 15)),
                    ("TO", f"{d['dtrk'] + 1:02d} {sq.tracks[d['dtrk']].name}" + ("  (has notes!)" if sq.tracks[d['dtrk']].events else ""), step("dtrk", 0, 15))]
        if op == "COPY PAD":
            p = e.prog.pads[d["dpad"]]
            return [("FROM", f"{BANKS[e.bank]}{e.sel + 1:02d} {e.pad.src.name if e.pad.src else 'empty'}  (hit a pad)", lambda n: None),
                    ("TO", f"{BANKS[d['dpad'] // 16]}{d['dpad'] % 16 + 1:02d} {p.src.name if p.src else 'empty'}", step("dpad", 0, 63))]
        if op == "FLATTEN PAD":
            flat = bool(getattr(e.pad, "_unflat", None))
            return [("PAD", f"{BANKS[e.bank]}{e.sel + 1:02d} {e.pad.src.name if e.pad.src else 'empty'}  (hit a pad)", lambda n: None),
                    ("NOW", "FLATTENED - DO IT puts the original back" if flat else "as it is - DO IT flattens it", lambda n: None)]
        return []

    def ed_adjust(self, n):
        rows = self.ed_rows()
        if rows: rows[clamp(self.ed_row, 0, len(rows) - 1)][2](n)

    def ed_do(self):
        e, d = self.e, self.ed
        op = self.ED_OPS[self.ed_op]
        if op == "COPY BARS":
            k = e.copy_bars(d["src"], d["dst"], d["nb"], times=d["times"], merge=d["merge"], all_tracks=d["all"], grow=True)
            self.say(f"copied {k} notes to bar {d['dst'] + 1}")
        elif op == "INSERT BARS": e.insert_bars(d["at"], d["nb"])
        elif op == "DELETE BARS": e.delete_bars(d["at"], d["nb"])
        elif op == "TIME SIGNATURE": e.set_timesig(d["num"], d["den"])
        elif op == "QUANTIZE" and e.timing == "ASR": e.quantize_track(E_eng.ASR_Q[e.asr_q][1], d["strength"] / 100.0, all_tracks=d["all"])
        elif op == "QUANTIZE": e.quantize_track(QUANT[d["grid"]][1], d["strength"] / 100.0, swing=d["swing"] / 100.0, all_tracks=d["all"])
        elif op == "NUDGE":
            if d["ticks"]: e.nudge(d["ticks"], all_tracks=d["all"])
        elif op == "COPY SEQUENCE": e.copy_sequence(d["sseq"], d["dseq"])
        elif op == "COPY TRACK": e.copy_track(d["strk"], d["dtrk"])
        elif op == "COPY PAD": e.copy_pad(e.pad, e.prog.pads[d["dpad"]])
        elif op == "FLATTEN PAD":
            if e.pad.empty: self.say("no sample on this pad")
            else: self.flatten_toggle()

    # ---------- PROJECTS page (MENU > PROJECTS) ----------
    def ask(self, title, text, yes, yes_fn, no=None, no_fn=None):
        """a question on screen, answered with the soft keys: F1 CANCEL, F2 the other answer (if any), F4 the main one"""
        self.confirm = {"title": title, "text": text,
                        "keys": [("CANCEL", None), (no, no_fn) if no else ("", None), ("", None), (HOT(yes), yes_fn)]}

    def save_first(self, what, go):
        """go(save_first) now if nothing is unsaved; otherwise ask SAVE / DON'T SAVE / CANCEL"""
        if not self.e.unsaved(full=True): go(False); return
        self.ask(f"SAVE {self.e.project_name.upper()}?", f"It has unsaved changes. Save them before {what}?",
                 "SAVE", lambda: go(True), "DON'T SAVE", lambda: go(False))

    def pj_open(self, i=None):
        e = self.e
        items = e.list_projects()
        i = self.pj_cur if i is None else i
        if not (0 <= i < len(items)): return
        name, path = items[i]
        if os.path.abspath(path) == os.path.abspath(e.dir): self.say(f"{name} is already open"); return
        def go(save):
            self.say(f"opening {name}...")
            e.open_project(path, save_first=save); self._after_project_change()
        self.save_first(f"opening {name}", go)

    def pj_new(self):
        def go(save):
            self.text_entry("NEW PROJECT - its name", "", 24,
                            lambda t: (self.e.new_project(t, save_first=save), self._after_project_change()))
        self.save_first("starting a new project", go)

    def pj_save_as(self):
        self.text_entry("SAVE AS - name of the copy", self.e.project_name + " 2", 24,
                        lambda t: (self.e.save_as(t), self.say(f"saved as {self.e.project_name}"), self._after_project_change()))

    def pj_purge(self):
        """PROJECTS: DELETE UNUSED SAMPLES - asks first (it cannot be undone once saved)"""
        n = len(self.e.unused_sources())
        if not n: self.say("every sample is used by a pad"); return
        def go(): self.e.delete_unused(); self.pick_cur = 0
        self.ask("DELETE UNUSED SAMPLES?", f"{n} sample{'s' if n > 1 else ''} no pad uses. Undo can't bring them back once saved.",
                 "DELETE", go)

    def _after_project_change(self):
        self.g_sel, self.track_setup, self.picking = None, None, False
        self.armed = [False] * 4
        items = self.e.list_projects()
        self.pj_cur = next((k for k, (_, p) in enumerate(items) if os.path.abspath(p) == os.path.abspath(self.e.dir)), 0)

    def go_back(self):
        """back to the screen you came from (pages that are not tabs: MIDI, BROWSE, PADS)"""
        self.set_mode(self.prev_mode if self.prev_mode and self.prev_mode != self.mode else "MAIN")

    # ---------- TRACK OUT (export page: SHIFT + SAMPLE, or TRACK OUT > on MAIN) ----------
    def ex_dests(self):
        import os
        out = [("PROJECT", os.path.join(self.e.dir, "exports"))]
        for label, dev, mp, fs in (self._drives or []):
            if mp: out.append(("USB " + label, mp))
        return out

    def ex_tracks(self):
        """the ticked tracks (default: every track that has notes, makes sound inside the sampler and is not muted)"""
        if self.ex_sel is None: self.ex_sel = set(self.e.bounce_tracks(self.ex_song))
        return sorted(self.ex_sel)

    def ex_toggle(self, n):
        sel = set(self.ex_tracks())
        sel.symmetric_difference_update({n}); self.ex_sel = sel

    def start_track_out(self, wait=False):
        import os, threading as th
        e = self.e
        if e.bouncing: return
        tracks = self.ex_tracks()
        if not tracks and not self.ex_mix: self.say("nothing ticked to bounce"); return
        label, base = self.ex_dests()[self.ex_dest % len(self.ex_dests())]
        name = "Song" if self.ex_song else e.seq.name
        folder = os.path.join(base, "Track outs" if label != "PROJECT" else "", 
                              "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name) + time.strftime(" %Y-%m-%d %H%M%S"))
        self.ex_files, self.ex_err = [], ""
        def job():
            try: self.ex_files = e.track_out(folder, tracks, self.ex_song, self.ex_mix, self.ex_tail)
            except Exception as ex: self.ex_err = str(ex)[:60]; e.say("track out failed: " + self.ex_err)
            self.ex_folder = folder
        self.ex_folder = folder
        if wait: job(); return
        self.ex_thread = th.Thread(target=job, daemon=True); self.ex_thread.start()

    # ---------- FLATTEN (PROG: the FLATTEN button, or SHIFT + F4) ----------
    def flatten_toggle(self):
        p = self.e.pad
        if getattr(p, "_unflat", None): self.e.unflatten_pad(p)
        else: self.e.flatten_pad(p)

    # ---------- the plug-in's own window ----------
    def editor_possible(self, f=None):
        f = f if f is not None else self.e.get_fx(self.fx_tgt())
        return f is not None and hasattr(f, "editor_idle") and bool(__import__("os").environ.get("DISPLAY"))

    def toggle_editor(self, obj=None, where=None):
        """open / close a plug-in's own window: the FX screen's effect, or (obj) a PLUGIN track's instrument"""
        if self.editor_fx is not None: self.editor_req = "close"; return
        obj = obj if obj is not None else self.e.get_fx(self.fx_tgt())
        if self.editor_possible(obj):
            self.editor_obj, self.editor_req = obj, "open"
            if where is None:
                where = self.fx_target_name(short=True)
            self.editor_where = where
        else: self.say("plug-in window needs the X11 display mode (--x11) and vst3host")

    def editor_scroll_to(self, sx=None, sy=None):
        v = self.editor_view
        if not v: return
        if sx is not None: v["sx"] = clamp(sx, 0.0, max(0.0, v["cw"] - v["w"]))
        if sy is not None: v["sy"] = clamp(sy, 0.0, max(0.0, v["ch"] - v["h"]))

    def editor_zoom(self, how):
        """how: 'in', 'out', 'fit' or a factor. Carried out by the display loop."""
        if self.editor_fx is not None: self.editor_req = ("zoom", how)

    def editor_scroll(self, dx, dy):
        v = self.editor_view
        if v: self.editor_scroll_to(v["sx"] + dx, v["sy"] + dy)

    def set_mode(self, m):
        if m == "BROWSE" and self.mode != "BROWSE": self.br_refresh()
        if m == "EXPORT" and self.mode != "EXPORT": self._drives = self.usb_drives(); self.ex_sel = None
        if self.mode == "BROWSE" and m != "BROWSE": self.e.stop_preview()
        if self.editor_fx is not None: self.editor_req = "close"
        self.kbd, self.confirm = None, None
        if m == "PROJECTS": self._after_project_change()
        if m == "EDIT" and not self.ed: self.ed_defaults()
        if m != self.mode: self.prev_mode = self.mode
        if m != "MAIN": self.mpick = None
        self.track_setup = None
        if m == "FX" and self.mode != "FX":
            if self.fx_target < 65:                                  # a program insert slot stays chosen; master only from MIXER
                self.fx_target = self.e.pad_idx if not (self.fx_target == 64 and self.mode == "MIXER") else 64
            self.fx_items = [('', '', '- none -')] + fxlib.discover()
            self.fx_page = 0; self.fx_cursor_to_loaded(); self.valve_case = None
            self.fx_browse = self.e.get_fx(self.fx_tgt()) is None
        if m == "CHOP":
            s = self.src
            self.chop_v0, self.chop_v1, self.chop_sel = 0.0, 1.0, 0
            self.chop_cursor = 0 if (s is None or s is not self.e.pad.src) else self.e.pad.start
        if m == "GRID": self.g_lane = self.e.sel
        self.mode, self.picking = m, False
        self.armed = [False] * 4

    def select(self, n):
        self.e.sel = n % 16
        self.armed = [False] * 4

    def say(self, t): self.e.say(t)

    def _mx_sel(self, n):
        if self.mix_page == 1: self.e.cur_track = n
        else: self.select(n)

    # ---------- the console (MIXER) ----------
    MIX_VIEWS = ("CHANNELS", "SENDS", "GROUPS", "PADS")
    MIX_PARAMS = ("LEVEL", "PAN", "SEND A", "SEND B")

    def mix_strips(self):
        """the strips of the current console view: [(kind, strip, label)]; kind 'prog' / 'rtn' / 'grp' / 'master'"""
        e = self.e
        out = [("prog", pr.strip, pr.name) for pr in e.programs]
        if self.mix_view == "GROUPS": out += [("grp", g, g.name) for g in e.groups]
        else: out += [("rtn", rt, rt.name) for rt in e.returns]
        return out + [("master", e.master_strip, "MASTER")]

    def mix_sel(self):
        ss = self.mix_strips()
        self.mix_strip = clamp(self.mix_strip, 0, len(ss) - 1)
        return ss[self.mix_strip]

    def mix_select(self, i):
        ss = self.mix_strips()
        self.mix_strip = clamp(i, 0, len(ss) - 1)
        if ss[self.mix_strip][0] == "prog":                         # a program's channel: say which tracks play it
            e = self.e
            if self.mix_strip < len(e.programs):
                pr = e.programs[self.mix_strip]
                trs = [f"{t.n + 1:02d}" for t in e.seq.tracks if t.kind == "drum" and t.prog == self.mix_strip and t.events]
                e.say(f"PGM {self.mix_strip + 1:02d} {pr.name}: " + ("tracks " + " ".join(trs) if trs else "no track plays it yet"), "info")
        if self.eq_open: self.e.analyse = ss[self.mix_strip][1]
        self.armed = [False] * 4

    def mix_set_view(self, v):
        self.mix_view = v; self.mix_page = 0; self.armed = [False] * 4
        self.mix_strip = clamp(self.mix_strip, 0, len(self.mix_strips()) - 1)

    def mix_adjust(self, param, n):
        """turn the selected strip's level / pan / send A / send B by n steps"""
        e = self.e
        kind, st, _ = self.mix_sel()
        import console as K
        if param == 0:
            if kind == "master": e.volume = clamp(e.volume + 0.01 * n, 0.0, 1.25)
            elif self.mix_view == "SENDS" and kind == "prog":
                st.sends[self.mix_send] = clamp(st.sends[self.mix_send] + 0.01 * n, 0.0, 1.0)
            else: st.level = K.fader_to_gain(clamp(K.gain_to_fader(st.level) + 0.01 * n, 0.0, 1.0))
        elif param == 1:
            if kind == "master": e.monitor = clamp(getattr(e, "monitor", 1.0) + 0.02 * n, 0.0, 1.0)
            else: st.pan = clamp(round(st.pan + 0.02 * n, 3), -1.0, 1.0)
        else:
            k = param - 2
            if kind == "master": e.send_master[k] = clamp(e.send_master[k] + 0.01 * n, 0.0, 1.0)
            elif kind == "prog": st.sends[k] = clamp(st.sends[k] + 0.01 * n, 0.0, 1.0)

    def mix_cycle_out(self, st, kind):
        import console as K
        opts = K.GROUP_OUTS if kind == "grp" else K.OUTS
        st.out = opts[(opts.index(st.out) + 1) % len(opts)] if st.out in opts else opts[-1 if kind != "grp" else 0]

    def eq_toggle(self, open_=None):
        self.eq_open = (not self.eq_open) if open_ is None else open_
        kind, st, _ = self.mix_sel()
        self.e.analyse = st if self.eq_open else None
        self.armed = [False] * 4

    def eq_flat(self):
        import console as K
        _, st, _ = self.mix_sel(); st.eq = [dict(b) for b in K.EQ_DEFAULT]

    def eq_swap_ab(self):
        """A / B: swap the strip's EQ with the other stored setting (the first time, B is a copy of A)"""
        _, st, _ = self.mix_sel()
        other = self.eq_ab.get(id(st)) or [dict(b) for b in st.eq]
        self.eq_ab[id(st)], st.eq = [dict(b) for b in st.eq], other
        self.eq_ab.setdefault("ab_" + str(id(st)), 0)
        self.eq_ab["ab_" + str(id(st))] ^= 1

    def eq_is_b(self):
        _, st, _ = self.mix_sel(); return bool(self.eq_ab.get("ab_" + str(id(st)), 0))

    # ---------- the four Q-link knobs change meaning per screen ----------
    def qlinks(self):
        e, p, sq, tr, m = self.e, self.e.pad, self.e.seq, self.e.track, self.mode
        volume = lin("Volume", e, "volume", 0, 1, lambda v: f"{v * 100:.0f}%")
        tempo = lin("Tempo", sq, "bpm", 60, 180, lambda v: f"{v:.1f} bpm", 1)
        swing = lin("Swing", sq, "swing", 0.5, 0.75, lambda v: f"{v * 100:.0f}%", 2)
        tune = lin("Pad tune", p, "tune", -12, 12, E_fmt_st, 0)
        if self.qlink_mode == "PROJECT":
            return [volume, tempo, swing, lin("Filter", e, "filt", 0, 1, lambda v: "open" if v > 0.98 else f"{v * 100:.0f}%")]
        if self.qlink_mode == "PAD":
            return [tune, lin("Pad level", p, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                    lin("Pad pan", p, "pan", -1, 1, lambda v: "C" if abs(v) < 0.05 else f"{'L' if v < 0 else 'R'}{abs(v) * 100:.0f}", 2),
                    lin("Pad gain", p, "gain_db", -12, 12, lambda v: f"{v:+.1f} dB", 1)]
        if self.qlink_mode == "TRACK":
            out = [lin("Track vol", tr, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                   lin("Track pan", tr, "pan", -1, 1, lambda v: "C" if abs(v) < 0.05 else f"{'L' if v < 0 else 'R'}{abs(v) * 100:.0f}", 2)]
            inst = e.instruments.get(id(tr)) if tr.kind == "plugin" else None
            if inst is not None and inst.n() >= 2:                     # PLUGIN track: its instrument's first two parameters
                for i in (0, 1):
                    out.append((inst.labels[i][:10], (lambda i=i: inst.get(i)), (lambda v, i=i: inst.set(i, v)), (lambda i=i: inst.fmt(i))))
            else:
                out += [lin("Velocity", self, "step_vel", 1, 127, lambda v: str(v), 0),
                        lin("Note len", e, "note_len", 6, 96, lambda v: f"{v} t", 0)]
            return out
        if m == "SAMPLE":
            return [lin("Gain", e, "in_gain_db", -12, 24, lambda v: f"{v:+.0f} dB", 0),
                    ("Threshold", lambda: (e.rec_thresh - 0.004) / 0.496,
                     lambda f: setattr(e, "rec_thresh", round(0.004 + f * 0.496, 4)), lambda: f"{20 * math.log10(max(1e-4, e.rec_thresh)):.0f} dB"),
                    lin("Pre-roll", e, "rec_preroll", 0, 500, lambda v: f"{v} ms", 0),
                    lin("Max len", e, "rec_max", 0, 60, lambda v: f"{v} s" if v else "no limit", 0)]
        if m == "PROG" and self.prog_front and not self.picking:
            return [tune, lin("Level", p, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                    lin("Pan", p, "pan", -1, 1, lambda v: "C" if abs(v) < 0.05 else f"{'L' if v < 0 else 'R'}{abs(v) * 100:.0f}", 2),
                    lin("Gain", p, "gain_db", -12, 12, lambda v: f"{v:+.1f} dB", 1)]
        if m == "BROWSE":
            return [("Scroll", lambda: self.br_cur / max(1.0, len(self.br_items) - 1.0),
                     lambda f: setattr(self, "br_cur", int(round(f * max(0, len(self.br_items) - 1)))),
                     lambda: f"{self.br_cur + 1} / {len(self.br_items)}"), volume,
                    ("Pad", lambda: e.pad_idx / 63.0, lambda f: self._pick_pad(int(round(f * 63))), lambda: f"{BANKS[e.bank]}{e.sel + 1:02d}"),
                    lin("Pad level", p, "vol", 0, 1, lambda v: f"{v * 100:.0f}%")]
        if m == "PROG" and self.prog_tab_name() == "SAMPLES":
            # START / END move across the visible waveform (ZOOM in for finer moves, SHIFT finer still), as in CHOP.
            # With WARP on, Q3 / Q4 are the warp pair: SAMPLE BPM and STRETCH (MPC 2.x); off: FINE and TUNE.
            def edge_get(which):
                a_, b_ = self.prog_view()
                return clamp((getattr(p, which) - a_) / float(max(1, b_ - a_)), 0.0, 1.0)
            def edge_set(f, which):
                if p.src is None: return
                a_, b_ = self.prog_view()
                r_ = e.set_region(p, **{which: int(a_ + f * (b_ - a_))})
                if r_: self.say(r_)
            def bpm_set(f):
                if p.src is None: return
                p.warp_bpm = round(60.0 + f * 140.0, 1); e.set_warp(p, True); e.pad_changed(p)
            edges = [("Start", lambda: edge_get("start"), lambda f: edge_set(f, "start"), lambda: f"{p.start / OUT_SR:.3f} s"),
                     ("End", lambda: edge_get("end"), lambda f: edge_set(f, "end"), lambda: f"{p.end / OUT_SR:.3f} s")]
            if p.warp:
                return edges + [("Sample BPM", lambda: clamp(((p.warp_bpm or 90.0) - 60.0) / 140.0, 0.0, 1.0), bpm_set,
                                 lambda: f"{p.warp_bpm:.1f}"),
                                lin("Stretch", p, "stretch", 25, 400, lambda v: f"{v}%", 0)]
            return edges + [lin("Fine", p, "fine", -99, 99, lambda v: f"{v:+d} ct" if v else "0", 0), tune]
        if m == "PROG" and self.prog_tab_name() == "EFFECTS":
            fxp = e.get_fx(p)
            out = []
            for k_ in range(4):
                if fxp is not None and k_ < fxp.n():
                    out.append((fxp.labels[k_][:10], (lambda k_=k_: fxp.get(k_)), (lambda v, k_=k_: fxp.set(k_, v)), (lambda k_=k_: fxp.fmt(k_))))
                else: out.append(("-", lambda: 0.0, lambda v: None, lambda: ""))
            return out
        if m == "PROG" and self.prog_tab_name() in ("LFO", "MODULATION"):
            return [lin("Mod amt", p, "a_amt", -127, 127, lambda v: f"{v:+d}", 0), lin("LFO rate", p, "a_lfo_rate", 0, 99, lambda v: str(v), 0),
                    lin("LFO depth", p, "a_lfo_depth", 0, 127, lambda v: str(v), 0), tune]
        if m == "PROG" and self.prog_tab_name() == "ENVELOPES" and e.sound_of(e.prog) == "ASR-10":
            def amp(name, lst, k_, hi, fmt):
                return (name, lambda: getattr(p, lst)[k_] / float(hi), lambda v: (getattr(p, lst).__setitem__(k_, int(round(v * hi))), e.pad_changed(p)),
                        lambda: fmt(getattr(p, lst)[k_]))
            return [amp("Attack", "a_amp_t", 0, 5000, lambda v: f"{v} ms"), amp("Decay 1", "a_amp_t", 1, 5000, lambda v: f"{v} ms"),
                    amp("Sustain", "a_amp_l", 4, 99, str), amp("Release", "a_amp_t", 4, 5000, lambda v: f"{v} ms")]
        if m == "PROG" and self.prog_tab_name() == "ENVELOPES":
            return [lin("Attack", p, "attack", 0, 2000, lambda v: f"{v} ms" if v else "off", 0),
                    lin("Decay", p, "decay", 0, 5000, lambda v: f"{v} ms" if v else "off", 0),
                    lin("Cutoff", p, "cutoff", 0, 1, lambda v: f"{e.cut_hz(v):.0f} Hz" if e.cut_hz(v) < 1000 else f"{e.cut_hz(v) / 1000:.1f} kHz", 3),
                    lin("Res", p, "res", 0, 1, lambda v: f"{v * 100:.0f}%", 2)]
        if m == "PROG":
            return [tune, lin("Level", p, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                    lin("Pan", p, "pan", -1, 1, lambda v: "C" if abs(v) < 0.05 else f"{'L' if v < 0 else 'R'}{abs(v) * 100:.0f}", 2),
                    lin("Gain", p, "gain_db", -12, 12, lambda v: f"{v:+.1f} dB", 1)]
        if m == "MIXER" and self.mix_view != "PADS":
            import console as K
            kind, st, _ = self.mix_sel()
            if self.eq_open:
                b = st.eq[self.eq_band]
                def fset(f, b=b): b["freq"] = 20.0 * 1000.0 ** f; b["on"] = True
                def gset(f, b=b): b["gain"] = round(-15 + 30 * f, 1); b["on"] = True
                def qset(f, b=b): b["q"] = round(0.3 + 5.7 * f, 2); b["on"] = True
                def tset(f, b=b):
                    if self.eq_band == 0: b["slope"] = 24 if f > 0.5 else 12
                    else: b["type"] = ("LOW SHELF", "BELL", "HIGH SHELF")[min(2, int(f * 3))]; b["on"] = True
                hz = lambda v: f"{v:.0f} Hz" if v < 1000 else f"{v / 1000:.1f}k"
                return [("Freq", lambda b=b: math.log(b["freq"] / 20.0) / math.log(1000.0), fset, lambda b=b: hz(b["freq"])),
                        ("Gain", lambda b=b: (b["gain"] + 15) / 30.0, gset, lambda b=b: f"{b['gain']:+.0f} dB") if self.eq_band else
                        ("-", lambda: 0.0, lambda f: None, lambda: ""),
                        ("Q", lambda b=b: (b["q"] - 0.3) / 5.7, qset, lambda b=b: f"{b['q']:.1f}") if self.eq_band else
                        ("-", lambda: 0.0, lambda f: None, lambda: ""),
                        ("Slope" if self.eq_band == 0 else "Type",
                         lambda b=b: (1.0 if b.get("slope", 12) >= 24 else 0.0) if self.eq_band == 0 else
                         {"LOW SHELF": 0.0, "BELL": 0.5, "HIGH SHELF": 1.0}.get(b["type"], 0.5), tset,
                         lambda b=b: f"{b.get('slope', 12)} dB/oct" if self.eq_band == 0 else b["type"])]
            if kind == "master":
                lev = ("Master", lambda: e.volume / 1.25, lambda f: setattr(e, "volume", f * 1.25), lambda: K.fader_label(e.volume / 0.8))
                return [lev, ("Monitor", lambda: getattr(e, "monitor", 1.0), lambda f: setattr(e, "monitor", f), lambda: f"{getattr(e, 'monitor', 1.0) * 100:.0f}%"),
                        ("Send A mst", lambda: e.send_master[0], lambda f: e.send_master.__setitem__(0, f), lambda: f"{e.send_master[0] * 100:.0f}%"),
                        ("Send B mst", lambda: e.send_master[1], lambda f: e.send_master.__setitem__(1, f), lambda: f"{e.send_master[1] * 100:.0f}%")]
            lev = ("Level", lambda: K.gain_to_fader(st.level), lambda f: setattr(st, "level", K.fader_to_gain(f)), lambda: K.fader_label(st.level) + " dB")
            pan = ("Pan", lambda: (st.pan + 1) / 2, lambda f: setattr(st, "pan", round(f * 2 - 1, 2)),
                   lambda: "C" if abs(st.pan) < 0.05 else f"{'L' if st.pan < 0 else 'R'} {abs(st.pan) * 100:.0f}")
            if kind != "prog": return [lev, pan, ("-", lambda: 0.0, lambda f: None, lambda: ""), ("-", lambda: 0.0, lambda f: None, lambda: "")]
            sa = ("Send A", lambda: st.sends[0], lambda f: st.sends.__setitem__(0, f), lambda: f"{st.sends[0] * 100:.0f}%")
            sb = ("Send B", lambda: st.sends[1], lambda f: st.sends.__setitem__(1, f), lambda: f"{st.sends[1] * 100:.0f}%")
            return [lev, pan, sa, sb]
        if m == "MIXER":
            if self.mix_page == 1:
                return [lin("Track vol", tr, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                        lin("Track pan", tr, "pan", -1, 1, lambda v: "C" if abs(v) < 0.05 else f"{'L' if v < 0 else 'R'}{abs(v) * 100:.0f}", 2),
                        volume, lin("Filter", e, "filt", 0, 1, lambda v: "open" if v > 0.98 else f"{v * 100:.0f}%")]
            return [lin("Pad level", p, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                    lin("Pan", p, "pan", -1, 1, lambda v: "C" if abs(v) < 0.05 else f"{'L' if v < 0 else 'R'}{abs(v) * 100:.0f}", 2),
                    volume, lin("Filter", e, "filt", 0, 1, lambda v: "open" if v > 0.98 else f"{v * 100:.0f}%")]
        if m == "MUTE":
            return [("Track", lambda: e.cur_track / 15.0, lambda f: (setattr(e, "cur_track", int(round(f * 15))), setattr(self, "mute_page", int(round(f * 15)) // 8)),
                     lambda: f"{e.cur_track + 1:02d} {tr.name}"[:16]),
                    ("Group", lambda: tr.mgroup / 4.0, lambda f: setattr(tr, "mgroup", int(round(f * 4))), lambda: "-ABCD"[tr.mgroup]),
                    lin("Track vol", tr, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                    ("Timing", lambda: 1.0 if e.mute_quant else 0.0, lambda f: setattr(e, "mute_quant", f > 0.5), lambda: "next bar" if e.mute_quant else "at once")]
        if m == "SONG" and e.song:
            st = e.song[clamp(self.song_cur, 0, len(e.song) - 1)]
            ssq = e.seqs[st[0]]
            return [("Step", lambda: self.song_cur / max(1.0, len(e.song) - 1.0), lambda f: setattr(self, "song_cur", int(round(f * (len(e.song) - 1)))),
                     lambda: f"{self.song_cur + 1:02d}"),
                    ("Sequence", lambda: st[0] / (NSEQ - 1.0), lambda f: st.__setitem__(0, int(round(f * (NSEQ - 1)))),
                     lambda: f"{st[0] + 1:02d} {e.seqs[st[0]].name}"[:14]),
                    ("Repeats", lambda: (st[1] - 1) / 15.0, lambda f: st.__setitem__(1, 1 + int(round(f * 15))), lambda: f"x{st[1]}"),
                    lin("Tempo", ssq, "bpm", 60, 180, lambda v: f"{v:.1f} bpm", 1)]
        if m in ("SEQ", "SONG", "MUTE"):
            return [tempo, swing,
                    lin("Track vol", tr, "vol", 0, 1, lambda v: f"{v * 100:.0f}%"),
                    lin("Track pan", tr, "pan", -1, 1, lambda v: "C" if abs(v) < 0.05 else f"{'L' if v < 0 else 'R'}{abs(v) * 100:.0f}", 2)]
        if m == "GRID":
            # the knobs work on the selected notes (one, or a marquee's worth): NUDGE, LENGTH, VELOCITY; Q4 zooms
            def rel(slot, per, fn):
                def set_(f):
                    self._g_acc[slot] += (f - 0.5) * 127.0 * per
                    a_ = self._g_acc[slot]
                    k = int(round(a_)) if abs(a_) >= 0.999 else 0
                    if k: self._g_acc[slot] -= k; fn(k)
                return set_
            sel = self.g_selection()
            first = sel[0] if sel else None
            def vel_set(f):
                cur = self.g_selection()
                if cur: self.g_velocity(int(round(1 + f * 126)) - cur[0][2])
                else: self.step_vel = int(round(1 + f * 126))
            return [("Nudge", lambda: 0.5, rel(0, 1.0, self.g_nudge), lambda: (f"tick {first[0] % sq.beat_ticks}" if first else "-")),
                    ("Length", lambda: 0.5, rel(1, 2.0, self.g_length), lambda: (f"{first[3]} t" if first else "-")),
                    ("Velocity", lambda: ((first[2] if first else self.step_vel) - 1) / 126.0, vel_set,
                     lambda: str(first[2] if first else self.step_vel)),
                    ("Zoom", lambda: [1, 2, 4, 8].index(self.g_bars) / 3.0, lambda f: self.set_zoom([1, 2, 4, 8][int(round(f * 3))]),
                     lambda: f"{self.g_bars} bar" + ("s" if self.g_bars > 1 else ""))]
        if m == "STEP":
            evs = self.step_events()
            if evs:                                                      # a note under the cursor: its velocity, nudge, ratchet
                vel = ("Velocity", lambda: (sorted(self.step_events() or evs)[0][2] - 1) / 126.0,
                       lambda f: self.step_set_vel(self.step_cursor, 1 + f * 126), lambda: str(sorted(self.step_events() or evs)[0][2]))
            else: vel = lin("Velocity", self, "step_vel", 1, 127, lambda v: str(v), 0)
            half = max(1, self.step_res // 8)
            return [vel, lin("Note len", e, "note_len", 6, 96, lambda v: f"{v} t", 0),
                    ("Nudge", lambda: 0.5 + self.step_nudge_of() / float(2 * half), self.step_nudge,
                     lambda: (f"{self.step_nudge_of():+d} tk" if self.step_nudge_of() else "0 tk") if self.step_events() else "-"),
                    ("Ratchet", lambda: (max(1, len(self.step_events())) - 1) / 3.0, lambda f: self.step_ratchet(1 + int(round(f * 3))),
                     lambda: f"x{len(self.step_events())}" if self.step_events() else "-")]
        if m == "CHOP":
            s = self.src
            rerun = lambda: self.chop_run(quiet=True)                         # the markers follow the knob
            if self.chop_mode == 0: a = lin("Slices", self, "chop_n", 2, 32, lambda v: str(v), 0, rerun)
            elif self.chop_mode == 1: a = lin("Sensitivity", self, "chop_sens", 0, 1, lambda v: f"{v * 100:.0f}%", 2, rerun)
            elif self.chop_mode == 2: a = lin("BPM", self, "chop_bpm", 60, 180, lambda v: f"{v:.1f}", 1, rerun)
            else:
                nr = lambda: len(s.regions()) if s else 1
                a = ("Slice", lambda: self.chop_k() / max(1.0, nr() - 1),
                     lambda f: self.chop_select(int(round(f * max(0, nr() - 1))), play=False),
                     lambda: f"{self.chop_k() + 1}/{nr()}" if s else "-")
            # START / END of the selected slice: a knob turn moves the edge across the visible window, so zooming in
            # makes it finer (SHIFT finer still)
            return [a, ("Start", lambda: self.chop_edge_get(0), lambda f: self.chop_edge_set(0, f), lambda: self.chop_edge_txt(0)),
                    ("End", lambda: self.chop_edge_get(1), lambda f: self.chop_edge_set(1, f), lambda: self.chop_edge_txt(1)),
                    ("Zoom", lambda: 1.0 - (self.chop_v1 - self.chop_v0), self.chop_zoom_to,
                     lambda: f"{1.0 / max(0.001, self.chop_v1 - self.chop_v0):.1f}x")]
        if m == "FX":
            effect = e.get_fx(self.fx_tgt())
            if self.valve_case and effect is not None and effect.name == "Drive":
                from fx import VALVES_V1, VALVES_V2
                names = [v[0] for v in (VALVES_V1 if self.valve_case == 1 else VALVES_V2)]
                n = len(names)
                vq = ("Valve", lambda: self.valve_pick / float(n - 1), lambda v: setattr(self, "valve_pick", int(round(v * (n - 1)))),
                      lambda: names[self.valve_pick])
                rest = [(effect.labels[i], (lambda i=i: effect.get(i)), (lambda v, i=i: effect.set(i, v)), (lambda i=i: effect.fmt(i)))
                        for i in (3, 1, 2)]
                return [vq] + rest
            order = self.fx_order(effect)
            out = []
            for k in range(4):
                i = order[self.fx_page * 4 + k] if effect is not None and self.fx_page * 4 + k < len(order) else 999
                if effect is not None and i < effect.n():
                    out.append((effect.labels[i][:10], (lambda i=i, fx_=effect: fx_.get(i)),
                                (lambda v, i=i, fx_=effect: fx_.set(i, v)), (lambda i=i, fx_=effect: fx_.fmt(i))))
                else:
                    out.append(("-", lambda: 0.0, lambda v: None, lambda: ""))
            return out
        if m == "MAIN" and e.machine == "SP-1200":                     # SP-1200: its sliders' jobs + swing + RING (F3 = auto-correct)
            from engine import SP_TUNE, SP_SWINGS, SP_CORRECT
            p = e.pad
            def set_tune(f):
                v = int(round(SP_TUNE[0] + f * (SP_TUNE[1] - SP_TUNE[0])))
                if v != p.tune: p.tune = v; e.pad_changed(p); e.say(f"Tune {BANKS[e.bank]}{e.sel + 1}: {v:+d}")
            def set_decay(f):
                v = int(round(f * 31))                                   # the SP's decay slider: 0-31, 31 = plays out
                ms = 0 if v >= 31 else int(40 * 1.16 ** v)
                if ms != p.decay: p.decay = ms; e.say(f"Decay = {v:02d}")
            def set_swing(f):
                k = int(round(f * 5))
                if E_eng.Engine.sp_swing_k(e.seq.swing) != k: e.seq.swing = SP_SWINGS[k] / 100.0; e.say(f"Swing: {SP_SWINGS[k]}%")
            def set_ring(f):
                v = round(f * 20) / 20.0                                 # 5% steps
                if v != e.sp_ring: e.sp_ring = v; e.say("Ring: off" if not v else f"Ring: {v * 100:.0f}%")
            dec_v = lambda: 31 if not p.decay else max(0, min(30, int(round(np.log(max(40, p.decay) / 40.0) / np.log(1.16)))))
            return [("Tune", lambda: (int(round(p.tune)) - SP_TUNE[0]) / float(SP_TUNE[1] - SP_TUNE[0]), set_tune,
                     lambda: f"{int(round(p.tune)):+d} st"),
                    ("Decay", lambda: dec_v() / 31.0, set_decay, lambda: "full" if dec_v() >= 31 else f"{dec_v()}"),
                    ("Swing", lambda: E_eng.Engine.sp_swing_k(e.seq.swing) / 5.0, set_swing,
                     lambda: f"{SP_SWINGS[E_eng.Engine.sp_swing_k(e.seq.swing)]}%"),
                    ("Ring", lambda: e.sp_ring, set_ring, lambda: "off" if not e.sp_ring else f"{e.sp_ring * 100:.0f}%")]
        if self.qlink_mode == "SCREEN" and self.asr_on(): return self.asr_qlinks()
        if m == "MAIN" and e.machine == "ASR-10":                      # ASR-10: no swing; its quantize values and system rate
            from engine import ASR_Q
            def set_q(f):
                k = int(round(f * (len(ASR_Q) - 1)))
                if k != e.asr_q: e.asr_q = k; e.say("QUANTIZE TO " + ASR_Q[k][0])
            def set_rate(f):
                k = 1 if f >= 0.5 else 0
                if k != e.asr_rate: e.asr_rate = k; e.say(("RATE=29.7619 KHZ", "RATE=44.1000 KHZ")[k])
            return [volume, tempo, ("Rate", lambda: float(e.asr_rate), set_rate, lambda: ("29.8k", "44.1k")[e.asr_rate]),
                    ("Quantize", lambda: e.asr_q / float(len(ASR_Q) - 1), set_q, lambda: ASR_Q[e.asr_q][0])]
        if m == "MAIN" and e.machine != "MODERN":                      # machine modes: Q4 = timing correct note value
            timing = ("Timing", lambda: e.qgrid / (len(QUANT) - 1.0), lambda f: setattr(e, "qgrid", int(round(f * (len(QUANT) - 1)))),
                      lambda: QUANT[e.qgrid][0])
            return [volume, tempo, swing, timing]
        return [volume, tempo, swing, tune]

    def cycle_qlink(self, d=1):
        self.qlink_mode = QLINK_MODES[(QLINK_MODES.index(self.qlink_mode) + d) % len(QLINK_MODES)]
        self.armed = [False] * 4
        self.say("Q-links: " + {"SCREEN": "follow the screen", "PROJECT": "volume / tempo / swing / filter",
                                "PAD": "selected pad", "TRACK": "current track"}[self.qlink_mode])

    # ---------- pad modes (PADS page: SHIFT + MUTE, or PADS > on MAIN) ----------
    def set_pad_mode(self, m):
        e = self.e
        if m == "16 LEVELS": e.levels_pad = e.pad_idx                 # 16 LEVELS spreads the selected pad over all 16
        e.pad_mode = m; self.pads_row = 0
        self.say("pads: " + {"NORMAL": "normal", "16 LEVELS": f"16 levels of {BANKS[e.levels_pad // 16]}{e.levels_pad % 16 + 1:02d} ({e.levels_param.lower()})",
                             "PERFORM": "scale notes / chords on the track", "TRACK MUTE": "mute tracks 1-16",
                             "NEXT SEQ": "choose the next sequence"}[m])

    def cycle_pad_mode(self, d=1):
        self.set_pad_mode(PAD_MODES[(PAD_MODES.index(self.e.pad_mode) + d) % len(PAD_MODES)])

    def pads_rows(self):
        """PADS page rows: (label, value text, adjust(step))"""
        e = self.e
        rows = [("PAD MODE", e.pad_mode, lambda d: self.cycle_pad_mode(d))]
        if e.pad_mode == "16 LEVELS":
            lp = e.prog.pads[e.levels_pad]
            rows += [("PARAMETER", e.levels_param, lambda d: setattr(e, "levels_param", "TUNE" if e.levels_param == "VELOCITY" else "VELOCITY")),
                     ("PAD", f"{BANKS[e.levels_pad // 16]}{e.levels_pad % 16 + 1:02d}  {lp.src.name[:10] if lp.src else 'empty'}",
                      lambda d: setattr(e, "levels_pad", (e.levels_pad + d) % 64))]
        elif e.pad_mode == "PERFORM":
            gi = next((i for i, (g, _) in enumerate(GATES) if g == e.perf_gate), 2)
            rows += [("KEY", NOTE_NAMES[e.perf_root], lambda d: setattr(e, "perf_root", (e.perf_root + d) % 12)),
                     ("OCTAVE", f"pad 1 = {note_name(12 * e.perf_oct + e.perf_root)}", lambda d: setattr(e, "perf_oct", clamp(e.perf_oct + d, 1, 8))),
                     ("SCALE", SCALES[e.perf_scale][0], lambda d: setattr(e, "perf_scale", (e.perf_scale + d) % len(SCALES))),
                     ("CHORD", CHORDS[e.perf_chord], lambda d: setattr(e, "perf_chord", (e.perf_chord + d) % len(CHORDS))),
                     ("NOTE LENGTH", GATES[gi][1], lambda d: setattr(e, "perf_gate", GATES[clamp(gi + d, 0, len(GATES) - 1)][0]))]
        elif e.pad_mode == "NEXT SEQ":
            rows += [("NEXT", "-" if e.next_seq is None else e.seqs[e.next_seq].name, lambda d: setattr(e, "next_seq", None))]
        return rows

    def pads_adjust(self, d):
        rows = self.pads_rows()
        self.pads_row = clamp(self.pads_row, 0, len(rows) - 1)
        rows[self.pads_row][2](d)

    def pad_mode_hit(self, n, vel):
        """a pad hit in one of the pad modes; returns False in NORMAL mode"""
        e, pm = self.e, self.e.pad_mode
        if pm == "NORMAL": return False
        self.pad_flash[n] = time.time()
        if pm == "16 LEVELS": e.levels_hit(n, vel)
        elif pm == "PERFORM":
            notes = e.perform_hit(n, vel)
            if self.mode == "GRID" and e.track.kind in NOTE_KINDS: self.g_lane = notes[0]; self.k_follow(notes[0])
        elif pm == "TRACK MUTE": e.toggle_track_mute(n)
        elif pm == "NEXT SEQ": e.queue_seq(n - 1)
        return True

    def _pick_pad(self, idx):
        self.e.select_pad(idx // 16, idx % 16); self.armed = [False] * 4

    def knob(self, i, v):
        if i >= 4:                                       # micro:bit tilt extras
            if i == 4: self.e.filt = v / 127.0
            elif i == 5: self.e.drive = 1.0 + v / 127.0 * 5.0
            return
        self.pot[i] = v; self.pot_seen[i] = True
        q = self.qlinks()[i]
        f = v / 127.0
        if not self.armed[i]:
            if abs(f - q[1]()) < 0.05: self.armed[i] = True
            else: return
        q[2](f)
        self._auto_rec(i)

    def nudge(self, i, delta):                           # keyboard test mode
        q = self.qlinks()[i]
        q[2](max(0.0, min(1.0, q[1]() + delta)))
        self._auto_rec(i)
        self.armed[i] = True
        self.pot[i] = int(q[1]() * 127)

    # ---------- GRID bottom lane and automation ----------
    def cycle_lane(self):
        self.g_view = {"OFF": "VEL", "VEL": "AUTO", "AUTO": "OFF"}[self.g_view]
        self.say({"OFF": "lane hidden", "VEL": "velocity lane", "AUTO": "automation lane"}[self.g_view])

    def auto_target(self):
        tg = self.e.auto_targets(self.e.track)
        if not tg: return None
        self.g_auto %= len(tg)
        return tg[self.g_auto]

    def next_auto_target(self, d=1):
        tg = self.e.auto_targets(self.e.track)
        self.g_auto = (self.g_auto + d) % max(1, len(tg))
        self.say("automate: " + tg[self.g_auto][1])

    def auto_clear_lane(self):
        tg = self.auto_target()
        if tg and self.e.track.auto.get(tg[0]):
            self.e.begin_edit(); self.e.auto_clear(self.e.track, tg[0]); self.say(tg[1] + " automation cleared")

    def _auto_rec(self, i):
        """a Q-link moved: if it drives something automatable on this track and we are recording, write it"""
        e = self.e
        if not (e.playing and e.rec != "off"): return
        label = self.qlinks()[i][0]
        key = None
        if label == "Track vol": key = "vol"
        elif label == "Track pan": key = "pan"
        elif self.mode == "FX" and 65 <= self.fx_target <= 68:
            order = self.fx_order(e.get_fx(self.fx_tgt()))
            key = f"ins{self.fx_target - 65}:{order[self.fx_page * 4 + i]}" if self.fx_page * 4 + i < len(order) else None
        if key is None: return
        tg = next((t for t in e.auto_targets(e.track) if t[0] == key), None)
        if tg is not None and e.auto_write(e.track, key, tg[2]()):
            names = [t[0] for t in e.auto_targets(e.track)]
            if key in names and self.mode == "GRID": self.g_auto = names.index(key)

    # ---------- grid view helpers ----------
    def snap(self):
        g = QUANT[self.e.qgrid][1]
        return g if g else 24

    # ---------- GRID: tools and the selection (DRAW / SELECT / ERASE; nudge, length, velocity, delete work on the selection)
    def g_pitch(self):
        """the note / pad under the cursor"""
        return self.g_lane if self.e.track.kind in NOTE_KINDS else self.e.bank * 16 + self.g_lane

    def g_selection(self):
        """the selected notes still on the track; none: the single note last touched, or the one under the cursor"""
        evs = self.e.track.events
        sel = [ev for ev in self.g_set if ev in evs]
        if sel: return sel
        if self.g_sel in evs: return [self.g_sel]
        ev = self.e.find_note(self.g_tick, self.g_pitch())
        return [ev] if ev else []

    def g_edit(self, fn, undo=True):
        """replace each selected note by fn(note) (None deletes it); the selection follows. Returns how many changed."""
        e = self.e
        sel = self.g_selection()
        if not sel: return 0
        if undo: e.begin_edit()
        new = []
        with e.lock:
            evs = list(e.track.events)
            for ev in sel:
                if ev in evs: evs.remove(ev)
            for ev in sel:
                nv = fn(ev)
                if nv is not None: nv = tuple(nv); evs.append(nv); new.append(nv)
            e.track.events = sorted(evs)
        multi = len(self.g_set) > 1 or (self.g_set and self.g_set[0] in sel)
        self.g_set = new if (multi or len(new) > 1) else []
        self.g_sel = new[0] if new else None
        return len(sel)

    def g_nudge(self, ticks):
        n = self.e.seq.length
        k = self.g_edit(lambda ev: ((ev[0] + ticks) % n,) + tuple(ev[1:]))
        if k: self.say(f"{k} note{'s' if k > 1 else ''} nudged {ticks:+d} tick{'s' if abs(ticks) != 1 else ''}")
        else: self.say("no note selected")

    def g_length(self, d):
        k = self.g_edit(lambda ev: (ev[0], ev[1], ev[2], int(clamp(ev[3] + d, 3, self.e.seq.length))))
        sel = self.g_selection()
        if k and sel: self.say(f"length {sel[0][3]} ticks" + (f" ({k} notes)" if k > 1 else ""))
        elif not k: self.say("no note selected")

    def g_velocity(self, d):
        k = self.g_edit(lambda ev: (ev[0], ev[1], int(clamp(ev[2] + d, 1, 127)), ev[3]))
        if not k: self.step_vel = int(clamp(self.step_vel + d, 1, 127))

    def g_delete(self):
        k = self.g_edit(lambda ev: None)
        self.g_set, self.g_sel = [], None
        self.say(f"{k} note{'s' if k != 1 else ''} deleted" if k else "no note selected")

    def g_select_all(self):
        """every note of the track; with a pad's row lit and SHIFT held: that row only"""
        evs = self.e.track.events
        if self.shift: self.shift_used = True; evs = [ev for ev in evs if ev[1] == self.g_pitch()]
        self.g_set = list(evs); self.g_sel = evs[0] if evs else None
        self.say(f"{len(evs)} notes selected" if evs else "no notes here")

    def g_set_tool(self, t):
        self.g_tool = t
        if t != "SELECT" and len(self.g_set) > 1: pass                 # the selection stays: nudge / delete still work on it
        self.say({"DRAW": "DRAW: tap to add a note, drag its end for length", "SELECT": "SELECT: drag a box around notes",
                  "ERASE": "ERASE: tap or drag over notes"}[t])

    def g_snap_step(self, d):
        self.e.qgrid = int(clamp(self.e.qgrid + d, 1, len(QUANT) - 1))

    def g_zoom_step(self, d):
        z = [1, 2, 4, 8]
        self.set_zoom(z[int(clamp(z.index(self.g_bars) + d, 0, 3))])

    def g_pad_flag(self, lane, which):
        """M / S on a pad's row"""
        pad = self.e.prog.pads[self.e.bank * 16 + lane]
        setattr(pad, which, not getattr(pad, which))
        self.e.pad_changed(pad) if hasattr(self.e, "pad_changed") else None

    def set_zoom(self, bars):
        self.g_bars = bars; self._g_scroll_to(self.g_off)

    def _g_scroll_to(self, tick):
        sq = self.e.seq
        span = self.g_bars * sq.bar_ticks
        tick = clamp(int(tick) // sq.bar_ticks * sq.bar_ticks, 0, max(0, sq.length - span))
        self.g_off = tick

    def g_follow(self):
        sq = self.e.seq
        span = self.g_bars * sq.bar_ticks
        if self.g_tick < self.g_off or self.g_tick >= self.g_off + span:
            self._g_scroll_to(self.g_tick)

    # ---------- chop view helpers ----------
    def chop_zoom_to(self, f):
        w = clamp(1.0 - f, 0.005, 1.0)
        s = self.src
        c = self.chop_cursor / float(s.length) if s is not None else (self.chop_v0 + self.chop_v1) / 2   # zoom on the cursor
        self.chop_v0 = clamp(c - w / 2, 0.0, 1.0 - w); self.chop_v1 = self.chop_v0 + w

    def chop_scroll_to(self, f):
        w = self.chop_v1 - self.chop_v0
        self.chop_v0 = clamp(f * (1.0 - w), 0.0, 1.0 - w); self.chop_v1 = self.chop_v0 + w

    def chop_keep_cursor(self):
        s = self.src
        if s is None: return
        f = self.chop_cursor / float(s.length)
        w = self.chop_v1 - self.chop_v0
        if f < self.chop_v0 or f > self.chop_v1:
            self.chop_v0 = clamp(f - w / 2, 0.0, 1.0 - w); self.chop_v1 = self.chop_v0 + w

    def chop_k(self):
        """the selected slice"""
        s = self.src
        if s is None: return 0
        return int(clamp(self.chop_sel, 0, len(s.regions()) - 1))

    def chop_show(self, a, b):
        """scroll (and zoom out if needed) so a..b is on screen"""
        s = self.src
        if s is None: return
        fa, fb = a / float(s.length), b / float(s.length)
        w = self.chop_v1 - self.chop_v0
        if fb - fa > w * 0.9: w = min(1.0, (fb - fa) / 0.8)
        if fa < self.chop_v0 or fb > self.chop_v1 or w != self.chop_v1 - self.chop_v0:
            c_ = (fa + fb) / 2
            self.chop_v0 = clamp(c_ - w / 2, 0.0, 1.0 - w); self.chop_v1 = self.chop_v0 + w

    def chop_select(self, k, play=True, vel=110):
        """pick slice k: it lights up, comes into view, and plays"""
        s = self.src
        if s is None: return
        regs = s.regions()
        k = int(clamp(k, 0, len(regs) - 1))
        self.chop_sel = k
        a, b = regs[k]
        if not (a <= self.chop_cursor < b): self.chop_cursor = a
        self.chop_show(a, b)
        if play: self.chop_audition(k, vel)

    def _chop_win(self):
        s = self.src
        A = self.chop_v0 * s.length; B = max(self.chop_v1 * s.length, A + 64)
        return A, B

    def chop_edge_get(self, which):
        s = self.src
        if s is None: return 0.0
        A, B = self._chop_win()
        pos = s.regions()[self.chop_k()][which]
        if not (A <= pos <= B):                                   # the edge is off screen: bring it into view first
            w = self.chop_v1 - self.chop_v0
            self.chop_v0 = clamp(pos / float(s.length) - w / 2, 0.0, 1.0 - w); self.chop_v1 = self.chop_v0 + w
            A, B = self._chop_win()
        return clamp((pos - A) / (B - A), 0.0, 1.0)

    def chop_edge_set(self, which, f):
        s = self.src
        if s is None: return
        A, B = self._chop_win()
        k = self.chop_k()
        pos = int(A + f * (B - A))
        self.e.set_slice_edge(s, k, **({"start": pos} if which == 0 else {"end": pos}))
        a, b = s.regions()[k]
        self.chop_cursor = a if which == 0 else max(a, b - 1)
        self.chop_keep_cursor()

    def chop_edge_txt(self, which):
        s = self.src
        if s is None: return "-"
        return f"{s.regions()[self.chop_k()][which] / OUT_SR:.3f} s"

    def chop_set_mode(self, k):
        """DETECT: EQUAL / TRANSIENT / BEATS place the markers at once; MANUAL leaves them"""
        self.chop_mode = k; self.armed = [False] * 4
        if k != 3: self.chop_run()

    def chop_run(self, quiet=False):
        """Create markers with the current chop mode."""
        e, s = self.e, self.src
        if s is None:
            if not quiet: self.say("this pad has no sample")
            return
        if self.chop_mode == 0: n = e.chop_equal(s, self.chop_n)
        elif self.chop_mode == 1: n = e.chop_transient(s, self.chop_sens)
        elif self.chop_mode == 2: n = e.chop_beats(s, self.chop_bpm, self.chop_div)
        else: n = len(s.regions())
        self.chop_sel = 0
        if not quiet: self.say(f"{n} chops (source file is not changed)")

    def chop_mark(self):
        s = self.src
        if s is None: return
        pos = self.chop_cursor
        if self.chop_snap:                                              # SNAP: the nearest rising zero crossing
            w_ = s.raw[max(0, pos - 512):pos + 512]
            zc = np.flatnonzero((w_[:-1] <= 0) & (w_[1:] > 0)) + max(0, pos - 512)
            if len(zc): pos = int(zc[np.argmin(np.abs(zc - pos))])
        if self.e.add_marker(s, pos):
            self.chop_sel = self.e.slice_at(s, pos - 1); self.say(f"split: {len(s.regions())} slices")
        else: self.say("no room to split here")

    def chop_unmark(self):
        s = self.src
        if s is None or len(s.regions()) < 2: self.say("one slice: nothing to merge"); return
        k = self.e.merge_slice(s, self.chop_k())
        if k is not None: self.chop_sel = k; self.say(f"slices {k + 1} and {k + 2} merged")

    def chop_step(self, d):
        """jump the cursor to the previous / next chop and play it"""
        s = self.src
        if s is None: return
        self.chop_select(self.chop_k() + d)

    def clear_armed(self): return time.time() - self._clear_t < 3.0

    def chop_clear(self):
        """CLEAR ALL removes every marker; markers are not covered by UNDO, so it asks for a second tap"""
        s = self.src
        if s is None or len(s.regions()) < 2: self.say("no slices to clear"); return
        if not self.clear_armed():
            self._clear_t = time.time(); self.say(f"tap CLEAR again to remove all {len(s.regions())} slices"); return
        self._clear_t = 0.0; self.e.clear_markers(s); self.chop_sel = 0; self.say("markers cleared")

    def save(self):
        self.e.save_project(); self.say("project saved")

    # ---------- STEP ----------
    def step_tick(self, i=None):
        return (self.step_page * 16 + (self.step_cursor if i is None else i)) * self.step_res

    def step_pages(self):
        return max(1, -(-self.e.seq.length // (16 * self.step_res)))

    def step_events(self, i=None, pad=None):
        """the notes of the pad inside step i (a ratchet is several)"""
        e = self.e
        t0 = self.step_tick(i); pad = e.pad_idx if pad is None else pad
        a = max(1, self.step_res // 8)                                    # a step owns [t0 - a, t0 + res - a): room for nudge + ratchet
        lo, hi = t0 - a, t0 + self.step_res - a
        return [ev for ev in e.track.events if ev[1] == pad and lo <= ev[0] < hi]

    def step_toggle(self, i):
        e = self.e
        t = self.step_tick(i)
        if t >= e.seq.length: return
        self.step_cursor = i
        evs = self.step_events(i)
        e.begin_edit()
        if evs:
            for ev in evs: e.remove_note(ev)
        else:
            v = 127 if self.step_accent else self.step_vel
            e.add_note(t, e.pad_idx, v, e.note_len); e.trigger(e.pad, v)

    def step_set_vel(self, i, v):
        for ev in self.step_events(i):
            self.e.remove_note(ev); self.e.add_note(ev[0], ev[1], int(clamp(v, 1, 127)), ev[3])

    def step_nudge(self, f):
        """Q3: the step's notes move off the grid, -half .. +half a step"""
        evs = self.step_events()
        if not evs: return
        a = max(1, self.step_res // 8)
        off = int(clamp(round((f - 0.5) * 2 * a), -a, a - 1))
        t0 = self.step_tick()
        k = len(evs); gap = self.step_res / float(k)
        for j, ev in enumerate(sorted(evs)):
            self.e.remove_note(ev); self.e.add_note(int(t0 + off + j * gap) if k > 1 else t0 + off, ev[1], ev[2], ev[3])

    def step_nudge_of(self):
        evs = sorted(self.step_events())
        return (evs[0][0] - self.step_tick()) if evs else 0

    def step_ratchet(self, n):
        """Q4: the step plays 1-4 times, evenly inside it (real notes, so they show in GRID)"""
        e = self.e
        evs = sorted(self.step_events())
        if not evs: return
        n = int(clamp(n, 1, 4))
        if n == len(evs): return
        v, ln, t0 = evs[0][2], evs[0][3], self.step_tick() + max(0, self.step_nudge_of())
        for ev in evs: e.remove_note(ev)
        gap = self.step_res // n
        for j in range(n): e.add_note(t0 + j * gap, e.pad_idx, v, max(3, min(ln, gap)) if n > 1 else ln)

    def step_copy_page(self):
        """COPY BAR: this page's notes (every pad of the track) onto the next page"""
        e = self.e
        span = 16 * self.step_res
        a = self.step_page * span; b = a + span
        nxt = (self.step_page + 1) % self.step_pages()
        if nxt == self.step_page: self.say("only one page"); return
        e.begin_edit()
        d = (nxt - self.step_page) * span
        for ev in [ev for ev in e.track.events if a <= ev[0] < b and ev[0] + d < e.seq.length]:
            if not e.find_note(ev[0] + d, ev[1]): e.add_note(ev[0] + d, ev[1], ev[2], ev[3])
        self.step_page = nxt; self.say(f"copied to page {nxt + 1}")

    # ---------- MUTE ----------
    def mute_toggle(self, tr):
        e = self.e
        now = e.pending_mute.get(tr.n, tr.mute)
        e.set_track_mute(tr, not now)
        when = " on the next bar" if e.mute_quant and e.playing else ""
        self.say(f"{tr.name}: {'muted' if not now else 'on'}{when}")

    def chop_assign(self):
        s = self.src
        if s is None: self.say("this pad has no sample"); return
        self.e.chop_to_pads(s, self.e.pad_idx, bpm=self.chop_bpm if self.chop_mode == 2 else None)
        if self.chop_fade:                                              # FADE: a click-free start and end on every slice pad
            for q in self.e.prog.pads:
                if q.link and q.link[0] == s.id:
                    q.fade_in, q.fade_out = max(q.fade_in, 1), max(q.fade_out, 5); self.e.pad_changed(q)

    def chop_audition(self, k=None, vel=110):
        s = self.src
        if s is None: return
        regs = s.regions()
        if k is None: k = self.chop_k()
        a, b = regs[min(k, len(regs) - 1)]
        from engine import Pad
        pad = self.e.pad
        t = Pad(pad.idx); t.__dict__.update(pad.__dict__)           # throw-away copy: plays the region, the real pad is untouched
        t.assign(s, a, b); t.fx, t.out, t.choke, t.mode = None, 0, 0, "ONE"
        self.e.trigger(t, vel)

    # ---------- SHIFT + pad ----------
    def legend(self):
        """(key, what it does with SHIFT held) pairs for the on-screen help - the Studio's own keys when its SHIFT is held"""
        if self.shift_studio:
            return [("PLAY", "save project"), ("STOP", "all notes off"), ("REC", "count-in off/1/2 bars"), ("OVERDUB", "metronome"),
                    ("ERASE", "solo pad"), ("UNDO", "redo (toggles)"), ("TAP TEMPO", "quantize track"), ("NOTE REPEAT", "repeat rate"),
                    ("SAMPLE EDIT", "SAMPLE RECORD"), ("PROG MIX", "FX"), ("TRACK MUTE", "MUTE page"), ("SEQ EDIT", "SONG"),
                    ("PADS", "select without playing"), ("DATA WHEEL", "fine steps"), ("WINDOW (FX)", "bypass the effect"),
                    ("F5", "MENU (projects, MIDI...)"), ("F6", "BACK")]
        return [("PLAY", "save project"), ("STOP", "all notes off"), ("REC", "count-in off/1/2 bars"), ("OVERDUB", "metronome"),
                ("ERASE", "solo pad"), ("UNDO", "redo (toggles)"), ("TAP", "quantize track"), ("F1-F4", "pad bank A-D"),
                ("REPEAT", "repeat rate"), ("GRID", "SONG"), ("MIXER", "FX"), ("PADS", "select without playing"),
                ("JOG", "fine steps"), ("OK (FX)", "bypass the effect"), ("MAIN", "MENU (projects, MIDI...)"), ("PROG", "BROWSE files"),
                ("LOAD", "PROJECTS"), ("MUTE", "PAD MODES"), ("JOG PUSH", "Q-link mode"), ("SAMPLE", "TRACK OUT (export WAVs)")]

    def show_legend(self):
        """the SHIFT help: only once SHIFT has been held a moment on its own (not while it is doing a fine adjust)"""
        return self.shift and not self.shift_used and time.time() - self.shift_t > 0.6

    def shift_pad(self, n):
        e = self.e
        if self.mode == "MIXER":
            if self.mix_page == 1: e.cur_track = n - 1; self.say(f"track {n}")
            else:
                p = e.prog.pads[e.bank * 16 + n - 1]; p.mute = not p.mute
                self.say(f"pad {n} {'muted' if p.mute else 'unmuted'}")
        else:
            self.select(n - 1)
            if self.mode == "GRID": self.g_lane = n - 1
            if self.mode == "FX" and self.fx_target < 64: self.fx_target, self.fx_page = e.pad_idx, 0
            self.say(f"pad {BANKS[e.bank]}{n:02d} selected")

    # ---------- FX helpers ----------
    FX_TARGETS = 74                                          # 0-63 pads, 64 master 1, 65-68 program inserts, 69-72 returns, 73 master 2

    def fx_tgt(self):
        from engine import FxSlot
        t = self.fx_target
        if t == 64: return "master"
        if t == 73: return FxSlot(self.e.master_strip, 0)
        if t >= 69: return FxSlot(self.e.returns[(t - 69) // 2], (t - 69) % 2)
        if t >= 65: return FxSlot(self.e.prog, t - 65)
        return self.e.prog.pads[self.fx_target]

    def fx_target_name(self, short=False):
        t = self.fx_target
        if t == 64: return "MASTER BUS 1"
        if t == 73: return "MASTER BUS 2"
        if t >= 69: return f"RTN {'AB'[(t - 69) // 2]}  INSERT {(t - 69) % 2 + 1}"
        if t >= 65: return (f"PROGRAM INSERT {t - 64}" if short else f"{self.e.prog.name}  INSERT {t - 64}")
        return f"PAD {BANKS[t // 16]}{t % 16 + 1:02d}"

    def fx_load(self):
        kind, ident, name = self.fx_items[self.fx_cursor]
        if kind: self.say("loading " + name[:20] + "...")
        self.e.set_fx(self.fx_tgt(), kind or None, ident or None)
        self.fx_page, self.armed = 0, [False] * 4
        self.fx_browse = self.e.get_fx(self.fx_tgt()) is None

    @staticmethod
    def fx_order(effect):
        """the order an effect's parameters go on Q1-Q4 (its faceplate's own: e.g. DRIVE BIAS MIX LEVEL), then the rest"""
        if effect is None: return []
        q = [i for i in getattr(effect, "qmap", ()) if i < effect.n()]
        return q + [i for i in range(effect.n()) if i not in q]

    def fx_chain(self):
        """the chain bar: the slots that sit in a row with the current target - [(target, label)]"""
        t = self.fx_target
        if 69 <= t <= 73:
            return [(69, "RTN A1"), (70, "RTN A2"), (71, "RTN B1"), (72, "RTN B2"), (64, "MASTER 1"), (73, "MASTER 2")]
        return [(self.e.pad_idx, f"PAD {BANKS[self.e.pad_idx // 16]}{self.e.pad_idx % 16 + 1:02d}")] + \
               [(65 + k, f"INSERT {k + 1}") for k in range(4)] + [(64, "MASTER")]

    def fx_step(self, n):
        """move along the chain bar"""
        ch = [t for t, _ in self.fx_chain()]
        cur = ch.index(self.fx_target) if self.fx_target in ch else 0
        self.fx_set_target(ch[(cur + n) % len(ch)])

    def valve_open(self, which):
        from fx import VALVES_V1, VALVES_V2
        eff = self.e.get_fx(self.fx_tgt())
        if eff is None or eff.name != "Drive": return
        self.valve_case = which
        cur = eff.v1()[0] if which == 1 else eff.v2()[0]
        self.valve_pick = [v[0] for v in (VALVES_V1 if which == 1 else VALVES_V2)].index(cur)
        self.armed = [False] * 4

    def valve_insert(self):
        eff = self.e.get_fx(self.fx_tgt())
        if eff is not None and eff.name == "Drive" and self.valve_case:
            eff.set_valve(self.valve_case, self.valve_pick)
            self.say(f"V{self.valve_case}: {eff.v1()[0] if self.valve_case == 1 else eff.v2()[0]}")
        self.valve_case = None; self.armed = [False] * 4

    def _fx_params_label(self, effect):
        if effect is None: return ""
        a = self.fx_page * 4 + 1
        return T(f"PARAMS {a}-{min(a + 3, effect.n())}", True) if effect.n() > 4 else T(f"PARAMS 1-{effect.n()}", True)

    def fx_pages(self):
        effect = self.e.get_fx(self.fx_tgt())
        return 1 if effect is None else max(1, (effect.n() + 3) // 4)

    def fx_set_page(self, p):
        self.fx_page = max(0, min(self.fx_pages() - 1, p)); self.armed = [False] * 4

    def fx_set_target(self, t):
        self.fx_target, self.fx_page, self.armed = t % self.FX_TARGETS, 0, [False] * 4
        self.fx_cursor_to_loaded(); self.valve_case = None
        self.fx_browse = self.e.get_fx(self.fx_tgt()) is None

    def fx_cursor_to_loaded(self):
        """the list opens on the effect that is loaded, not on '- none -'"""
        effect = self.e.get_fx(self.fx_tgt())
        self.fx_cursor = 0 if effect is None else next((i for i, it in enumerate(self.fx_items) if (it[0], it[1]) == effect.ident), 0)

    # ---------- directional keys ----------
    def nav(self, d):
        e, m, sq = self.e, self.mode, self.e.seq
        if self.shift: self.shift_used = True
        if self.confirm is not None: return
        if self.kbd is not None: self.kbd_move(d); return
        if self.mpick is not None and m == "MAIN":
            self.mpick = (self.mpick + {"left": -1, "right": 1, "up": -3, "down": 3}[d]) % len(self.PICK); return
        if m == "PROJECTS":
            if d in ("up", "down"): self.pj_cur = clamp(self.pj_cur + (1 if d == "down" else -1), 0, len(e.list_projects()) - 1)
            return
        if m == "MENU":
            self.menu_cur = (self.menu_cur + {"left": -1, "right": 1, "up": -self.MENU_COLS, "down": self.MENU_COLS}[d]) % len(self.MENU_ITEMS); return
        if m == "EDIT":
            if d in ("up", "down"): self.ed_row = clamp(self.ed_row + (1 if d == "down" else -1), 0, max(0, len(self.ed_rows()) - 1))
            else: self.ed_adjust(1 if d == "right" else -1)
            return
        if self.editor_view is not None:                          # plug-in window open: the D-pad scrolls it
            self.editor_scroll({"left": -60, "right": 60}.get(d, 0), {"up": -60, "down": 60}.get(d, 0)); return
        if self.picking:
            if d in ("up", "down"): self.pick_cur = clamp(self.pick_cur + (1 if d == "down" else -1), 0, len(e.sources))
            return
        if m == "SETTINGS":                                           # up / down: the rows; < >: the value
            rs = self.set_rows()
            if d in ("up", "down"): self.set_row = (self.set_row + (1 if d == "down" else -1)) % len(rs)
            else: _SET.step(self, rs[self.set_row % len(rs)], 1 if d == "right" else -1)
            return
        if self.asr_on():                                           # the ASR: < > the next parameter, up / down its value
            if d in ("left", "right"): self.asr.move(1 if d == "right" else -1)
            else: self.asr.data(1 if d == "up" else -1)
        elif m == "MAIN" and e.machine != "MODERN":
            self.lcd_nav(d)
        elif m == "MAIN":
            self.main_move(d)
        elif m == "MUTE":                                          # the eight strips: left / right; up / down: the other eight
            if d in ("left", "right"): e.cur_track = (e.cur_track + (1 if d == "right" else -1)) % 16
            else: e.cur_track = (e.cur_track + 8) % 16
            self.mute_page = e.cur_track // 8
        elif m == "SEQ":
            if d in ("up", "down"): e.cur_track = (e.cur_track + (1 if d == "down" else -1)) % 16
            else: self.seq_off = clamp(self.seq_off + (1 if d == "right" else -1), 0, max(0, sq.bars - 1))
        elif m == "GRID" and self.shift and d in ("left", "right"):      # SHIFT + left / right: nudge the note by one tick
            self.g_nudge(1 if d == "right" else -1)
        elif m == "GRID" and e.track.kind in NOTE_KINDS:                 # piano roll: up / down = one semitone
            s = self.snap()
            if d == "left": self.g_tick = max(0, self.g_tick - s)
            elif d == "right": self.g_tick = min(sq.length - s, self.g_tick + s)
            else: self.g_lane = clamp(self.g_lane + (1 if d == "up" else -1), 0, 127); self.k_follow(self.g_lane)
            self.g_follow()
        elif m == "BROWSE":
            if d in ("up", "down"): self.br_cur = clamp(self.br_cur + (1 if d == "down" else -1), 0, max(0, len(self.br_items) - 1))
            elif d == "right": self.br_open()
            else: self.br_open(0) if self.br_dir is not None else None
        elif m == "PADS":
            if d in ("up", "down"): self.pads_row = clamp(self.pads_row + (1 if d == "down" else -1), 0, len(self.pads_rows()) - 1)
            else: self.pads_adjust(1 if d == "right" else -1)
        elif m == "MIDI":
            import midi as _m
            n = len(_m.LEARN_TARGETS)
            self.midi_row = (self.midi_row + {"up": -1, "down": 1, "left": -_m.PER_COL, "right": _m.PER_COL}[d]) % n
        elif m == "GRID":
            s = self.snap()
            if d == "left": self.g_tick = max(0, self.g_tick - s)
            elif d == "right": self.g_tick = min(sq.length - s, self.g_tick + s)
            elif d == "up": self.g_lane = min(15, self.g_lane + 1)
            else: self.g_lane = max(0, self.g_lane - 1)
            if d in ("up", "down"): self.e.sel = self.g_lane
            self.g_sel = None                                         # the knobs now work on the note under the cursor (or the box)
            self.g_follow()
        elif m == "STEP":
            if d in ("left", "right"): self.step_cursor = (self.step_cursor + (1 if d == "right" else -1)) % 16
            else: self.select(e.sel + (1 if d == "up" else -1))
        elif m == "PROG":
            if d in ("up", "down"):                                       # through the tab's eight settings, then on to the next tab
                rows = self.PROG_TABS[self.prog_tab][1]
                i = rows.index(self.prog_row) if self.prog_row in rows else 0
                i += 1 if d == "down" else -1
                if not 0 <= i < len(rows):
                    self.prog_tab = (self.prog_tab + (1 if i >= len(rows) else -1)) % len(self.PROG_TABS)
                    rows = self.PROG_TABS[self.prog_tab][1]; i = 0 if d == "down" else len(rows) - 1
                self.prog_row = rows[i]
            elif not self.prog_front and not self.picking: self.set_prog_tab(self.prog_tab + (1 if d == "right" else -1))
        elif m == "SAMPLE":                                               # the pad to record into: the 4 x 4 grid, as on MAIN
            b = e.bank * 16
            self._pick_pad(b + (e.sel + {"left": -1, "right": 1, "up": 4, "down": -4}[d]) % 16)
        elif m == "CHOP":
            s = self.src
            if s is None: return
            w = (self.chop_v1 - self.chop_v0) * s.length
            if self.shift and d in ("left", "right"): self.shift_used = True; self.chop_pick(1 if d == "right" else -1); return
            if d in ("left", "right"): self.chop_step(1 if d == "right" else -1)           # the previous / next slice
            else: self.chop_zoom_to(clamp(1.0 - (self.chop_v1 - self.chop_v0) * (0.5 if d == "up" else 2.0), 0.0, 0.995))
        elif m == "MIXER" and self.eq_open:
            if d in ("left", "right"): self.eq_band = (self.eq_band + (1 if d == "right" else -1)) % 5
            else:
                b = self.mix_sel()[1].eq[self.eq_band]
                if self.eq_band: b["gain"] = clamp(b["gain"] + (1 if d == "up" else -1) * (0.25 if self.shift else 1), -15.0, 15.0); b["on"] = True
        elif m == "MIXER" and self.mix_view != "PADS":
            if d in ("left", "right"): self.mix_select(self.mix_strip + (1 if d == "right" else -1))
            else: self.mix_param = (self.mix_param + (1 if d == "down" else -1)) % 4
        elif m == "MIXER":
            if d in ("left", "right"):
                if self.mix_page == 1: e.cur_track = (e.cur_track + (1 if d == "right" else -1)) % 16
                else: self.select(e.sel + (1 if d == "right" else -1))
            else: self.mix_row = (self.mix_row + (1 if d == "down" else -1)) % 3
        elif m == "FX":
            if self.valve_case:
                if d in ("left", "right"): self.jog(1 if d == "right" else -1)
            elif d in ("up", "down"):
                if self.fx_browse: self.fx_cursor = clamp(self.fx_cursor + (1 if d == "down" else -1), 0, len(self.fx_items) - 1)
                else: self.fx_set_page(self.fx_page + (1 if d == "down" else -1))
            elif self.shift: self.fx_set_page(self.fx_page + (1 if d == "right" else -1))
            else: self.fx_step(1 if d == "right" else -1)
        elif m == "SONG":
            if d in ("up", "down"): self.song_cur = clamp(self.song_cur + (1 if d == "down" else -1), 0, len(e.song) - 1)
            else:
                st = e.song[self.song_cur]
                if d == "left": st[1] = max(1, st[1] - 1)
                else: st[1] = min(16, st[1] + 1)

    # ---------- jog wheel ----------
    def jog(self, n, fast=False):
        """n clicks. SHIFT = fine steps everywhere; fast=True (the hardware wheel, turned quickly) = bigger steps on values"""
        e, m, sq, p = self.e, self.mode, self.e.seq, self.e.pad
        if self.shift: self.shift_used = True
        if self.confirm is not None: return
        if self.kbd is not None: self.kbd_jog(n); return
        if self.mpick is not None and m == "MAIN": self.mpick = (self.mpick + n) % len(self.PICK); return
        if m == "PROJECTS":
            self.pj_cur = clamp(self.pj_cur + n, 0, len(e.list_projects()) - 1); return
        acc = n * self.jog_speed() if fast else n                   # for values (lists move one row a click)
        if m == "EDIT": self.ed_adjust(acc); return
        if m == "MENU": self.menu_cur = (self.menu_cur + n) % len(self.MENU_ITEMS); return
        if m == "BROWSE":
            self.br_cur = clamp(self.br_cur + n, 0, max(0, len(self.br_items) - 1)); return
        if m == "PADS":
            self.pads_adjust(1 if n > 0 else -1); return
        if m == "EXPORT":
            self.ex_tail = clamp(round(self.ex_tail + (0.1 if self.shift else 0.5) * acc, 1), 0.0, 10.0); return
        if self.editor_view is not None:                          # plug-in window open: the jog scrolls it up / down
            self.editor_scroll(0, 20 * n * (5 if self.shift else 1)); return
        if self.picking:
            self.pick_cur = clamp(self.pick_cur + n, 0, len(e.sources)); return
        if self.asr_on(): self.asr.data(acc); return                 # the ASR's data slider
        if m == "SETTINGS":
            rs = self.set_rows(); _SET.step(self, rs[self.set_row % len(rs)], n); return
        if m == "MAIN" and e.machine != "MODERN" and self.lcd_cur:   # the jog is the machine's data wheel
            import machines
            machines.adjust(e, self.lcd_cur, acc if self.lcd_cur in ("bpm", "vel") else n)
        elif m == "MAIN":
            self.main_adjust(n, acc)
        elif m == "SEQ":                                                 # the playhead: a beat a click (SHIFT: a 16th)
            e.locate(e.pos + acc * (sq.beat_ticks // 4 if self.shift else sq.beat_ticks))
        elif m == "MUTE":
            e.cur_track = (e.cur_track + n) % 16; self.mute_page = e.cur_track // 8
        elif m == "GRID":                             # the wheel: velocity of the selection (SHIFT: its length, a snap step a click)
            if self.shift: self.shift_used = True; self.g_length(n * self.snap())
            else: self.g_velocity(4 * n)
        elif m == "STEP":
            evs = self.step_events()
            dv = (1 if self.shift else 4) * acc
            if evs: self.step_set_vel(self.step_cursor, evs[0][2] + dv)
            else: self.step_vel = clamp(self.step_vel + dv, 1, 127)
        elif m == "PROG":
            self.prog_adjust(self.prog_row, acc)
        elif m == "SAMPLE":
            e.rec_thresh = clamp(round(e.rec_thresh + (0.001 if self.shift else 0.01) * acc, 4), 0.004, 0.5)
        elif m == "CHOP":
            s = self.src
            if s is None: return
            w = (self.chop_v1 - self.chop_v0) * s.length
            self.chop_cursor = int(clamp(self.chop_cursor + acc * w / (400 if not self.shift else 4000), 0, s.length - 1))
            self.chop_keep_cursor()
        elif m == "MIXER" and self.eq_open:
            b = self.mix_sel()[1].eq[self.eq_band]
            b["freq"] = clamp(b["freq"] * (2 ** (acc / (96.0 if self.shift else 24.0))), 20.0, 20000.0); b["on"] = True
        elif m == "MIXER" and self.mix_view != "PADS":
            self.mix_adjust(self.mix_param, acc * (0.2 if self.shift else 1))
        elif m == "MIXER":
            tr = e.track
            if self.mix_row == 0:
                tgt = tr if self.mix_page == 1 else p
                tgt.vol = clamp(tgt.vol + 0.01 * acc * (0.2 if self.shift else 1), 0.0, 1.0)
            elif self.mix_row == 2 and self.mix_page == 0: e.cycle_out(p, 1 if n > 0 else -1)
            else:
                tgt = tr if self.mix_page == 1 else p
                tgt.pan = clamp(round(tgt.pan + (0.01 if self.shift else 0.05) * acc, 2), -1.0, 1.0)
        elif m == "FX":
            if self.valve_case:
                from fx import VALVES_V1, VALVES_V2
                self.valve_pick = clamp(self.valve_pick + n, 0, len(VALVES_V1 if self.valve_case == 1 else VALVES_V2) - 1)
            elif self.fx_browse: self.fx_cursor = clamp(self.fx_cursor + n, 0, len(self.fx_items) - 1)
            else: self.fx_step(n)
        elif m == "SONG":                         # the wheel: the highlighted step's sequence (up / down = step, left / right = repeats)
            if e.song:
                st = e.song[self.song_cur]; st[0] = (st[0] + (1 if n > 0 else -1)) % NSEQ
                self.say(f"step {self.song_cur + 1:02d}: sequence {st[0] + 1:02d} {e.seqs[st[0]].name}")

    def jog_speed(self):
        """how fast the wheel is turning: 1 (slow) .. 10 (spun), from the gap between clicks"""
        now = time.time()
        self._jog_run = self._jog_run + 1 if now - self._jog_t < 0.06 else 0
        self._jog_t = now
        return 1 if self._jog_run < 4 else 4 if self._jog_run < 14 else 10

    chop_move_on = False

    # PROG, laid out as an MPC 2.x program edit: GLOBAL / SAMPLES / ENVELOPES / (LFO / MODULATION on the ASR-10) / EFFECTS
    PROG_TABS_ALL = [("GLOBAL", [4, 5, 6, 7, 13, 12, 9, 43]),
                     ("SAMPLES", [0, 40, 1, 2, 3, 41, 14, 15, 42, 8, 10, 11]),
                     ("ENVELOPES", [16, 17, 18, 19, 20, 21, 22, 23])]
    PROG_TABS_ASR = [("LFO", [32, 33, 34, 35, 36, 37, 38, 39]), ("MODULATION", [24, 25, 26, 31, 27, 28, 29, 30])]
    PROG_TABS_FX = [("EFFECTS", [44, 45, 46, 47, 48, 49, 50, 51])]
    PROG_TOGGLES = (6, 8, 9, 12, 14, 18, 24, 27, 28, 32, 40, 44, 45, 52, 54, 55, 56, 58, 59, 75, 76, 77)  # rows a tap flips / cycles (EFFECT: opens the FX page)

    @property
    def PROG_TABS(self):
        """the PROG page's tabs: the ASR-10 adds its wavesample LFO / ENV1 and loop / modulation"""
        snd = self.e.sound_of(self.e.prog)
        glob = [4, 5, 43, 6, 7, 13] + self.machine_rows()               # the pad, then the sound of its machine (under a heading)
        env = ("ENVELOPES", [64, 65, 66, 67, 70, 71, 72, 73, 69, 68, 74, 75, 76]) if snd == "ASR-10" else self.PROG_TABS_ALL[2]   # ASR-10: its five-stage amp env (times | the level each one ends on | ...)
        tabs = [("GLOBAL", glob), self.PROG_TABS_ALL[1], env] + (self.PROG_TABS_ASR if snd == "ASR-10" else []) + self.PROG_TABS_FX
        if getattr(self, "prog_tab", 0) >= len(tabs):                     # (the machine changed under an ASR tab)
            self.prog_tab = 1
        if getattr(self, "prog_row", 0) not in sum((r for _, r in tabs), []): self.prog_row = 3
        return tabs

    def prog_tab_name(self): return self.PROG_TABS[self.prog_tab][0]

    def machine_rows(self):
        """PROG > GLOBAL: SOUND, then what only this sound has (shown under its own heading)"""
        pages = self.machine_pages()
        self.mach_page = getattr(self, "mach_page", 0) % len(pages)
        return pages[self.mach_page]

    def machine_pages(self):
        """the machine's own sound options, in pages of six (the heading's page button steps through them)"""
        snd = self.e.sound_of(self.e.prog)
        if snd == "SP-1200": return [[52, 12, 56, 57, 53]]
        if snd == "ASR-10": return [[52, 54, 58, 59, 60, 61], [62, 63, 21, 22, 23, 55]]
        if snd == "MPC60": return [[52, 81, 78, 79]]
        if snd == "MPC3000": return [[52, 77, 81, 79, 23]]
        if snd == "MPC2000XL": return [[52, 77, 81, 78, 79, 80], [82, 23]]
        return [[52, 12]]

    def set_prog_tab(self, k):
        self.prog_tab = k % len(self.PROG_TABS)
        if self.prog_row not in self.PROG_TABS[self.prog_tab][1]: self.prog_row = self.PROG_TABS[self.prog_tab][1][0]
        self.armed = [False] * 4

    def prog_tab_of(self, row):
        return next(k for k, (_, rows) in enumerate(self.PROG_TABS) if row in rows)

    def rename_picked(self):
        """PROG sample list: rename the highlighted sample"""
        if 0 <= self.pick_cur < len(self.e.sources):
            src = self.e.sources[self.pick_cur]
            self.text_entry("NAME SAMPLE (renames its file at the next save)", src.name, 24,
                            lambda t: self.say("sample renamed: " + self.e.rename_source(src, t)))

    def prog_adjust(self, row, n):
        e, p = self.e, self.e.pad
        sh = self.shift                                               # SHIFT = fine steps (spin the wheel fast for big ones)
        f = 0.1 if sh else 1.0
        if sh: self.shift_used = True
        if row == 0:                                                  # SAMPLE
            if not e.sources: return
            cur = p.src.id if p.src else -1
            nxt = clamp(cur + n, 0, len(e.sources) - 1)
            if p.src is None or nxt != cur: p.assign(e.sources[nxt]); self.say("sample: " + e.sources[nxt].name)
        elif row in (1, 2) and p.src is not None:                    # START / END: 5 ms * k (SHIFT: one sample)
            step = (int(0.005 * OUT_SR) if not sh else 1) * n
            r_ = e.set_region(p, start=p.start + step) if row == 1 else e.set_region(p, end=p.end + step)
            if r_: self.say(r_)
            return
        elif row == 40 and p.src is not None:                         # SLICE: PAD, 1 .. n
            nsl = e.slice_count(p)
            cur = -1 if not (p.link and p.link[0] == p.src.id) else p.link[1]
            nxt = (cur + 1 + (1 if n > 0 else -1)) % (nsl + 1) - 1
            e.set_slice(p, None if nxt < 0 else nxt)
            self.say("SLICE: PAD - this pad's own start and end" if nxt < 0 else f"SLICE {nxt + 1} of {nsl}: follows its markers")
            return
        elif row == 52:                                               # SOUND: this program's (or the machine's)
            ch = [None] + list(E_eng.SOUNDS)
            pr = e.prog
            pr.sound = ch[(ch.index(pr.sound if pr.sound in ch else None) + (1 if n > 0 else -1)) % len(ch)]
            self.say(f"{pr.name}: sound of the machine ({e.sound_of(pr)})" if pr.sound is None else f"{pr.name}: {pr.sound} sound (this program only)")
            return
        elif row == 53: e.sp_ring = clamp(round(e.sp_ring + 0.05 * n, 2), 0.0, 1.0)
        elif row == 56:
            p.sp_ch = (p.sp_ch + (1 if n > 0 else -1)) % 9
            ch = e.sp_channel(p)
            self.say(f"SP channel {ch}: " + ("dynamic filter" if ch <= 2 else "fixed filter" if ch <= 6 else "no filter - the aliasing comes straight out"))
        elif row == 57: p.decay = E_eng.sp_decay_ms(int(clamp(E_eng.sp_decay_of(p.decay) + n, 0, 31)))
        elif row == 54: e.asr_rate = 1 - e.asr_rate; self.say("ASR-10 rate: " + ("44.1 kHz, 23 voices" if e.asr_rate else "29.76 kHz, 31 voices"))
        elif row == 55: self.make_transwave(); return
        elif row == 58: p.a_bus = (p.a_bus + (1 if n > 0 else -1)) % 3
        elif row == 59: p.a_fmode = (p.a_fmode + (1 if n > 0 else -1)) % 4
        elif row == 60: p.a_f1 = int(clamp(p.a_f1 + n, 0, 150))
        elif row == 61: p.a_f2 = int(clamp(p.a_f2 + n, 0, 150))
        elif row == 62: p.a_kbd1 = int(clamp(p.a_kbd1 + n, -127, 127))
        elif row == 63: p.a_kbd2 = int(clamp(p.a_kbd2 + n, -127, 127))
        elif row == 41: p.fine = int(clamp(p.fine + n, -99, 99))
        elif row == 42: p.stretch = int(clamp(p.stretch + n, 25, 400))
        elif row == 43: p.gain_db = clamp(round(p.gain_db + (0.1 if sh else 0.5) * n, 1), -12.0, 12.0)
        elif row == 44:                                               # EFFECT: the FX page, on this pad
            self.fx_target, self.fx_page = e.pad_idx, 0; self.set_mode("FX"); self.fx_cursor_to_loaded(); return
        elif row == 45:
            if e.get_fx(p) is not None: e.toggle_bypass(p)
            return
        elif 46 <= row <= 51:
            fxp = e.get_fx(p)
            if fxp is not None and row - 46 < fxp.n(): fxp.set(row - 46, fxp.get(row - 46) + 0.01 * n * f)
            return
        elif row == 3: p.tune = clamp(p.tune + n, -24, 24)
        elif row == 4: p.vol = clamp(round(p.vol + 0.01 * n * f, 3), 0.0, 1.0)
        elif row == 5: p.pan = clamp(round(p.pan + (0.01 if sh else 0.05) * n, 2), -1.0, 1.0)
        elif row == 6: p.mode = MODES[(MODES.index(p.mode) + (1 if n > 0 else -1)) % 2]
        elif row == 7: p.choke = clamp(p.choke + n, 0, 8)
        elif row == 8: p.reverse = not p.reverse
        elif row == 9: p.norm = not p.norm
        elif row == 10: p.fade_in = int(clamp(p.fade_in + (1 if sh else 5) * n, 0, 500))
        elif row == 11: p.fade_out = int(clamp(p.fade_out + (1 if sh else 5) * n, 0, 500))
        elif row == 12 and e.sound_of(p) == "SP-1200":               # SP-1200: "sampled at" 33 / 45 / 78 rpm, tuned back down
            rp = sorted(E_eng.SP_RPMS); p.rpm = rp[(rp.index(p.rpm if p.rpm in rp else 33) + (1 if n > 0 else -1)) % len(rp)]
            self.say({33: "Sampled at 33: as it is", 45: "Sampled at 45: held 5 st up, played back down - grittier",
                      78: "Sampled at 78: held 15 st up, played back down - grittiest (only -1 st of tune left)"}[p.rpm])
        elif row == 12: p.lofi_on = not p.lofi_on
        elif row == 13: e.cycle_out(p, 1 if n > 0 else -1)
        elif row == 14:
            e.set_warp(p, not p.warp)
            self.say(f"WARP on: plays at {p.warp_bpm:.1f} bpm length, follows the tempo" if p.warp else ("WARP off" if p.src else "no sample on this pad"))
        elif row == 16: p.attack = int(clamp(p.attack + (1 if sh or p.attack < 20 else 10) * n, 0, 2000))
        elif row == 17: p.decay = int(clamp(p.decay + (1 if sh else 10 if p.decay < 200 else 50) * n, 0, 5000))
        elif row == 18:
            fl = ["OFF", "LP", "HP", "BP"]; p.flt = fl[(fl.index(p.flt) + (1 if n > 0 else -1)) % 4]
            if p.flt != "OFF" and p.cutoff >= 0.99 and p.flt == "LP": p.cutoff = 0.7          # a low-pass that does something
        elif row == 19: p.cutoff = clamp(round(p.cutoff + 0.01 * n * f, 3), 0.0, 1.0)
        elif row == 20: p.res = clamp(round(p.res + 0.02 * n * f, 3), 0.0, 1.0)
        elif row == 21: p.f_env = clamp(round(p.f_env + 0.02 * n * f, 3), -1.0, 1.0)
        elif row == 22: p.f_dec = int(clamp(p.f_dec + (1 if sh else 10) * n, 10, 5000))
        elif row == 23: p.f_vel = clamp(round(p.f_vel + (0.01 if sh else 0.05) * n, 2), 0.0, 1.0)
        elif 24 <= row <= 39: self._asr_adjust(row, n, sh, p)
        elif 64 <= row <= 68:                                         # ASR amp env times (ms)
            j = row - 64; v = p.a_amp_t[j]
            p.a_amp_t[j] = int(clamp(v + (1 if sh or v < 20 else 10 if v < 500 else 50) * n, 0, 20000))
        elif 69 <= row <= 73: p.a_amp_l[row - 69] = int(clamp(p.a_amp_l[row - 69] + n, 0, 99))
        elif row == 74: p.a_softvel = int(clamp(p.a_softvel + n, 0, 100))
        elif row == 75: p.a_vcurve = (p.a_vcurve + (1 if n > 0 else -1)) % 4
        elif row == 76: p.a_emode = (p.a_emode + (1 if n > 0 else -1)) % 3
        elif row == 77:
            p.m_dmode = 1 - p.m_dmode
            self.say("DECAY MODE START: decays from the start" if p.m_dmode else "DECAY MODE END: fades out at the note's (or the sound's) end")
        elif row == 78: p.m_vatk = int(clamp(p.m_vatk + (1 if sh or p.m_vatk < 20 else 10) * n, 0, 2000))
        elif row == 79: p.m_vstart = int(clamp(p.m_vstart + n, 0, 500))
        elif row == 80: p.m_vpitch = int(clamp(p.m_vpitch + (1 if sh else 5) * n, -1200, 1200))
        elif row == 81:
            v_ = -1 if p.vel_mpc is None else p.vel_mpc
            v_ = int(clamp(v_ + n, -1, 100)); p.vel_mpc = None if v_ < 0 else v_
        elif row == 82: p.f_atk = int(clamp(p.f_atk + (1 if sh or p.f_atk < 20 else 10) * n, 0, 5000))
        elif row == 15 and p.src is not None:
            if not p.warp_bpm: p.warp_bpm = e.guess_bpm(p)
            p.warp_bpm = clamp(round(p.warp_bpm + (0.01 if sh else 0.1) * n, 2), 30.0, 300.0)
            if p.warp: e.set_warp(p, True)
        e.pad_changed(p)

    def _asr_adjust(self, row, n, sh, p):
        """the ASR-10's wavesample rows (PROG > LOOP / MOD, LFO / ENV1)"""
        import asrvoice as AV
        e = self.e
        rate = E_eng.ASR_RATES[e.asr_rate]
        reg = p.length / E_eng.OUT_SR
        le = p.a_le if p.a_le > 0 else reg
        cyc = lambda: max(1e-6, (le - p.a_ls))
        if row == 24: p.a_loop = (p.a_loop + (1 if n > 0 else -1)) % len(AV.LOOP_MODES)
        elif row in (25, 26, 31):                                        # loop points: one sample at the ASR's rate per step
            st = n * (1 if sh else 10) / rate                          # 10 samples a click (SHIFT: one)
            if row == 25: p.a_ls = clamp(p.a_ls + st, 0.0, le - 2.0 / rate)
            elif row == 26: p.a_le = clamp(le + st, p.a_ls + 2.0 / rate, reg)
            else:                                                       # LOOP POS: moves the loop, keeping its length
                ln = cyc(); a = clamp(p.a_ls + st, 0.0, reg - ln); p.a_ls, p.a_le = a, a + ln
        elif row == 27: p.a_mod = (p.a_mod + (1 if n > 0 else -1)) % len(AV.MOD_TYPES)
        elif row == 28:
            i = AV.MOD_SOURCES.index(p.a_src) if p.a_src in AV.MOD_SOURCES else 0
            p.a_src = AV.MOD_SOURCES[(i + (1 if n > 0 else -1)) % len(AV.MOD_SOURCES)]
        elif row == 29: p.a_amt = int(clamp(p.a_amt + n, -127, 127))
        elif row == 30: p.a_range = int(clamp(p.a_range - n, 0, len(AV.RANGES) - 1))
        elif row == 32: p.a_lfo_wave = (p.a_lfo_wave + (1 if n > 0 else -1)) % len(AV.LFO_WAVES)
        elif row == 33: p.a_lfo_rate = int(clamp(p.a_lfo_rate + n, 0, 99))
        elif row == 34: p.a_lfo_depth = int(clamp(p.a_lfo_depth + n, 0, 127))
        elif row == 35: p.a_lfo_delay = int(clamp(p.a_lfo_delay + n, 0, 99))
        elif row in (36, 37, 39):
            j = {36: 0, 37: 1, 39: 3}[row]
            v = p.a_env1[j]; p.a_env1[j] = int(clamp(v + (1 if sh else 5 if v < 100 else 50) * n, 0, 20000))
        elif row == 38: p.a_env1[2] = clamp(round(p.a_env1[2] + (0.001 if sh else 0.01) * n, 3), 0.0, 1.0)

    def make_transwave(self):
        """PROG F3 on the ASR-10: the pad's sound becomes a transwave (64 single cycles), swept by ENV1"""
        e = self.e
        if e.pad.empty: self.say("no sample on this pad"); return
        self.say("making a transwave...")
        r = e.make_transwave(e.pad, 64)
        if r: self.say(f"TRANSWAVE: {r[0]} cycles of {r[1]} samples ({r[2]:.1f} Hz) - ENV1 sweeps them; see LOOP / MOD")

    # ---------- OK / jog press ----------
    def ok(self):
        e, m, sq = self.e, self.mode, self.e.seq
        if self.shift: self.shift_used = True
        if self.kbd is not None:
            k = self.kbd; self.kbd_press(self.KBD_ROWS[k["row"]][k["col"] % len(self.KBD_ROWS[k["row"]])]); return
        if self.confirm is not None: self.soft(3); return                   # a question: OK = its F4 answer
        if self.editor_fx is not None: self.editor_req = "close"; return     # OK closes the plug-in window
        if self.mpick is not None and m == "MAIN": self.pick_machine(self.PICK[self.mpick]); return
        if m == "PROJECTS": self.pj_open(); return
        if m == "EDIT": self.ed_do(); return
        if m == "MENU": self.menu_go(self.menu_cur); return
        if self.picking:
            if self.pick_cur < len(e.sources):
                e.pad.assign(e.sources[self.pick_cur]); e.pad_changed(e.pad); self.say("sample: " + e.sources[self.pick_cur].name)
            self.picking = False; return
        if self.asr_on(): self.asr.enter(); return                  # the ASR keys: OK = Enter-Yes
        if m == "SETTINGS":                                           # OK: a key row runs; a row of keys steps on (wraps)
            rs = self.set_rows(); r_ = rs[self.set_row % len(rs)]
            if r_.kind == "key" and r_.action: r_.action()
            elif r_.kind in ("seg", "list") and r_.options:
                vals = [v for _, v in r_.options]; cur = _SET.get(self, r_.key)
                _SET.put(self, r_.key, vals[((vals.index(cur) if cur in vals else -1) + 1) % len(vals)])
            return
        if m == "MAIN": self.prog_front = False; self.set_mode("PROG")    # OK opens the selected pad (pads are for playing)
        elif m == "SEQ": self.set_mode("GRID")                         # ALL TRACKS: OK edits the selected track
        elif m == "MUTE": self.mute_tap(e.cur_track)
        elif m == "GRID" and e.track.kind in NOTE_KINDS:
            on = e.toggle_note(self.g_tick, self.g_lane, self.step_vel, self.snap())
            if on: e.audition(self.g_lane, self.step_vel)
        elif m == "BROWSE": self.br_open()
        elif m == "PADS": self.pads_adjust(1)
        elif m == "MIDI":
            import midi as _m
            t = _m.LEARN_TARGETS[self.midi_row]
            self.midi_learn = None if self.midi_learn == t else t
        elif m == "GRID":
            on = e.toggle_note(self.g_tick, self.g_lane, self.step_vel, self.snap())
            self.g_sel = e.find_note(self.g_tick, self.g_lane) if on else None
            if on: e.trigger(e.prog.pads[e.bank * 16 + self.g_lane], self.step_vel)
        elif m == "STEP": self.step_toggle(self.step_cursor)
        elif m == "PROG":
            if self.prog_row == 0: self.picking, self.pick_cur = True, (e.pad.src.id if e.pad.src else 0)
            elif self.prog_row in self.PROG_TOGGLES: self.prog_adjust(self.prog_row, 1)
        elif m == "SAMPLE": e.rec_toggle()
        elif m == "CHOP": self.chop_mark() if self.chop_mode == 3 else self.chop_run()
        elif m == "MIXER" and self.mix_view != "PADS":
            if self.eq_open: b = self.mix_sel()[1].eq[self.eq_band]; b["on"] = not b["on"]
            else: st = self.mix_sel()[1]; st.mute = not st.mute
        elif m == "MIXER":
            tgt = e.track if self.mix_page == 1 else e.pad
            tgt.mute = not tgt.mute
        elif m == "FX":
            if self.valve_case: self.valve_insert()
            elif self.shift:
                if e.get_fx(self.fx_tgt()) is not None: e.toggle_bypass(self.fx_tgt())
            elif self.fx_browse: self.fx_load()
            else: self.fx_browse = True
        elif m == "SONG":                                                # OK: that step's sequence, in SEQ
            if e.song and not e.playing: e.select_seq(e.song[self.song_cur][0])
            self.set_mode("SEQ")

    def jog_press(self):
        if self.shift: self.shift_used = True; self.cycle_qlink(); return     # SHIFT + jog push: Q-link mode
        self.ok()

    # ---------- soft keys F1-F4 ----------
    def soft_labels(self):
        """F1-F4 labels, in the soft-key grammar (uicore.py): plain text = action, T() = toggle, C() = setting, P() = page, BACK on F4"""
        e, m = self.e, self.mode
        p = e.pad
        if self.confirm is not None: return [k[0] for k in self.confirm["keys"]]
        if self.mpick is not None and m == "MAIN": return ["CLOSE", "", "", HOT("SELECT")]
        if self.shift and not self.shift_studio and self.editor_fx is None:     # SHIFT + F1-F4 = pad bank (the Studio has BANK keys)
            return [HOT(f"BANK {b}") if e.bank == k else f"BANK {b}" for k, b in enumerate("ABCD")]
        mt = e.track if self.mix_page == 1 else p
        if self.kbd is not None: return ["CANCEL", "DELETE", "SPACE", HOT("OK")]
        if self.editor_fx is not None:                       # the soft keys run the plug-in window while it is open
            z = (self.editor_view or {}).get("zoom", 1.0)
            return ["CLOSE", "ZOOM -", "ZOOM +", C("FIT", f"{z * 100:.0f}%")]
        effect = e.get_fx(self.fx_tgt()) if m == "FX" else None
        notes = e.track.kind in NOTE_KINDS
        return {
            "MAIN": (self.asr_soft_labels() if self.asr_on() else None)
                    or (__import__("machines").soft_labels(e, e.machine) if e.machine != "MODERN" else None)
                    or [T("METRONOME", e.metro), C("COUNT-IN", ("OFF", "1 BAR", "2 BARS")[e.count_in]),
                        C("AUTOCORRECT", E_eng.SP_CORRECT[e.sp_ac][0]) if e.machine == "SP-1200" else
                        ("QUANTIZE TRK " + E_eng.ASR_Q[e.asr_q][0]) if e.machine == "ASR-10" else T("REC QUANTIZE", e.rec_quant), P("MENU")],
            "SEQ": [P("EDIT"), P("COPY SEQUENCE"), C("TRACKS", "1-8" if e.cur_track < 8 else "9-16"), P("EDIT TRACK")],
            "MENU": ["", "", "", BACK],
            "PROJECTS": ["NEW", "SAVE AS", "OPEN", BACK],
            "EDIT": ["CLOSE", C("OPERATION", self.ED_OPS[self.ed_op]), "UNDO", HOT("DO IT")],
            "MUTE": [C("TRACKS", "1-8" if self.mute_page == 0 else "9-16"), T("GROUPS", self.mute_groups), "UNMUTE ALL", T("ON NEXT BAR", e.mute_quant)],
            "GRID": [T("DRAW", self.g_tool == "DRAW"), T("SELECT", self.g_tool == "SELECT"), T("ERASE", self.g_tool == "ERASE"),
                     (lambda k: f"DELETE {k} NOTES" if k > 1 else "DELETE NOTE")(len([ev for ev in self.g_set if ev in e.track.events]))],
            "STEP": [C("PAGE", f"{self.step_page + 1} OF {self.step_pages()}"), "COPY BAR", "CLEAR PAD", T("ACCENT", self.step_accent)],
            "PROG": ([P("ALL PARAMS"), "AUDITION", P("SAMPLES"), P("EFFECTS")] if self.prog_front and not self.picking else
                     ["AUDITION", T("NORMALIZE", p.norm), C("RPM", str(p.rpm)) if e.sound_of(p) == "SP-1200" else ("MAKE TRANSWAVE" if e.sound_of(p) == "ASR-10" else T("LO-FI", p.lofi_on)), P("PICK SAMPLE")]),
            "SAMPLE": [T("ARM", e.rec_state in ("rec", "armed")), "STOP", "KEEP" if e.last_take else "", "DISCARD" if e.last_take else ""],
            "CHOP": ["AUDITION", "SPLIT", "MERGE", HOT("CONVERT")],
            "MIXER": (["CLOSE", "BAND <", "BAND >", "FLAT"] if self.eq_open else
                      [T("PROGRAMS", self.mix_view == "CHANNELS"), T("SENDS " + "AB"[self.mix_send], self.mix_view == "SENDS"),
                       T("GROUPS", self.mix_view == "GROUPS"),
                       T("TRACKS" if (self.mix_view == "PADS" and self.mix_page == 1) else "PADS", self.mix_view == "PADS")]),
            "FX": (["CLOSE", T("V1 / V2", True), "", HOT("INSERT")] if self.valve_case else
                   ["CLOSE" if effect is not None else "", T("BYPASS", bool(effect is not None and e.get_bypass(self.fx_tgt()))),
                    "", HOT("LOAD")] if self.fx_browse else
                   [T("BROWSE", False), T("BYPASS", bool(effect is not None and e.get_bypass(self.fx_tgt()))),
                    T("PLUG-IN WINDOW", self.editor_fx is not None) if (effect is not None and effect.kind == "vst3") else "REMOVE",
                    self._fx_params_label(effect)]),
            "SONG": ["INSERT", "DELETE", T("PLAY SONG", e.playing and e.song_mode), BACK],
            "SETTINGS": ["< SECTION", "SECTION >", HOT("APPLY") if self.set_pending else "", BACK],
            "MIDI": [T("LEARN", self.midi_learn is not None), "CLEAR", C("KEYS CHANNEL", "ANY" if self.midi_map.key_ch == 0 else str(self.midi_map.key_ch)), BACK],
            "BROWSE": (["CANCEL", "", "", HOT("IMPORT")] if self.br_import else
                       [T("AUDITION", self.br_audition), "IMPORT" if self.br_mpc_selected() else "LOAD", "EJECT" if self._br_drive() else "",
                        "< UP" if self.br_dir is not None else BACK]),
            "EXPORT": [C("WHAT", "SONG" if self.ex_song else "SEQUENCE"), C("TO", self.ex_dests()[self.ex_dest % len(self.ex_dests())][0][:14]),
                       HOT("BOUNCING...") if self.e.bouncing else "START TRACK OUT", BACK],
            "PADS": ["< MODE", "MODE >", {"16 LEVELS": C("LEVELS OF", e.levels_param), "PERFORM": C("CHORD", CHORDS[e.perf_chord]),
                                          "TRACK MUTE": "UNMUTE ALL", "NEXT SEQ": HOT("CANCEL NEXT") if e.next_seq is not None else "CANCEL NEXT"}.get(e.pad_mode, ""), BACK],
        }[m]

    def asr_soft_labels(self):
        """F1-F3 = LOAD / COMMAND / EDIT (the mode lit), F4 = ENTER when it has something to do; a question: F1 NO, F4 YES"""
        pn = self.asr
        if pn.ask is not None: return ["NO", "", "", HOT("YES")]
        import asrpanel
        return [HOT(m) if m == pn.mode else m for m in asrpanel.MODES] + [HOT("ENTER") if pn.waiting() else ""]

    def soft_text(self, i): return soft_text(self.soft_labels()[i])

    def soft(self, i):
        e, m, sq = self.e, self.mode, self.e.seq
        if self.kbd is not None: self.kbd_press(("CANCEL", "DEL", "SPACE", "OK")[i]); return
        if self.confirm is not None:
            fn = self.confirm["keys"][i][1]
            if fn is not None or i == 0: self.confirm = None
            if fn is not None: fn()
            return
        if self.mpick is not None and m == "MAIN":
            if i == 0: self.close_picker()
            elif i == 3: self.pick_machine(self.PICK[self.mpick])
            return
        if m == "SETTINGS":
            if i == 0: self.set_section(self.set_sec - 1)
            elif i == 1: self.set_section(self.set_sec + 1)
            elif i == 2 and self.set_pending: self.set_apply()
            elif i == 3: self.go_back()
            return
        if m == "EDIT":
            if i == 0: self.go_back()
            elif i == 1: self.ed_op = (self.ed_op + 1) % len(self.ED_OPS); self.ed_row = 0
            elif i == 2: e.undo_toggle()
            else: self.ed_do()
            return
        if m == "MENU":
            if i == 3: self.go_back()
            return
        if m == "PROJECTS":
            if i == 0: self.pj_new()
            elif i == 1: self.pj_save_as()
            elif i == 2: self.pj_open()
            else: self.go_back()
            return
        if self.shift and not self.shift_studio and self.editor_fx is None:   # SHIFT + F1-F4 = pad bank A-D (no BANK keys on the panel)
            e.bank = i; self.shift_used = True; self.say(f"pad bank {BANKS[i]}"); return
        if self.editor_fx is not None:
            if i == 0: self.editor_req = "close"
            else: self.editor_zoom(("out", "in", "fit")[i - 1])
            return
        if self.asr_on():
            pn = self.asr
            if pn.ask is not None:
                if i == 0: pn.cancel()
                elif i == 3: pn.enter()
            elif i < 3:
                import asrpanel; pn.set_mode(asrpanel.MODES[i])
            elif pn.waiting(): pn.enter()
            return
        if m == "MAIN" and e.machine != "MODERN":
            import machines
            if machines.soft_labels(e, e.machine) is not None: machines.soft(e, e.machine, i); return
        if m == "MAIN":
            if i == 0: e.metro = not e.metro
            elif i == 1: e.count_in = (e.count_in + 1) % 3
            elif i == 2 and e.machine == "SP-1200":
                e.sp_ac = (e.sp_ac + 1) % len(E_eng.SP_CORRECT); self.say("Autocorrect:" + E_eng.SP_CORRECT[e.sp_ac][0])
            elif i == 2 and e.machine == "ASR-10":                    # ASR-10: QUANTIZE TRACK (an edit, undoable)
                if e.playing: self.say("STOP SEQUENCER FIRST")
                elif not e.track.events: self.say("NO DATA ON SOURCE TRK")
                else: e.quantize_track(E_eng.ASR_Q[e.asr_q][1]); self.say("COMMAND COMPLETED")
            elif i == 2: e.rec_quant = not e.rec_quant
            else: self.set_mode("MENU")
        elif m == "SEQ":
            if i == 0: self.ed_open()
            elif i == 1: self.ed_open("COPY SEQUENCE")
            elif i == 2: e.cur_track = (e.cur_track + 8) % 16
            else: self.set_mode("GRID")
        elif m == "MUTE":
            if i == 0: self.mute_page ^= 1; e.cur_track = self.mute_page * 8 + e.cur_track % 8
            elif i == 1: self.mute_groups = not self.mute_groups; self.say("tap a GROUP to change it" if self.mute_groups else "groups set")
            elif i == 2:
                for t in sq.tracks: t.mute = t.solo = False
                e.pending_mute = {}; self.say("all tracks on, solo off")
            else: e.mute_quant = not e.mute_quant; self.say("mutes switch on the next bar line" if e.mute_quant else "mutes switch at once")
        elif m == "GRID":
            if i < 3: self.g_set_tool(("DRAW", "SELECT", "ERASE")[i])
            else: self.g_delete()
        elif m == "STEP":
            if i == 0: self.step_page = (self.step_page + 1) % self.step_pages()
            elif i == 1: self.step_copy_page()
            elif i == 2: e.begin_edit(); e.erase_pad_events(e.pad_idx); self.say("pad steps cleared")
            else: self.step_accent = not self.step_accent
        elif m == "PROG" and self.prog_front and not self.picking:
            if i == 0: self.prog_front = False
            elif i == 1: e.trigger(e.pad, 110)
            elif i == 2: self.picking, self.pick_cur = True, (e.pad.src.id if e.pad.src else 0)
            else: self.prog_adjust(44, 1)                                 # EFFECTS: the FX page, on this pad
        elif m == "PROG":
            if i == 0 and self.picking: self.picking = False
            elif i == 0: e.trigger(e.pad, 110)
            elif i == 1: self.prog_adjust(9, 1)
            elif i == 2 and e.sound_of(e.pad) == "ASR-10": self.make_transwave()
            elif i == 2: self.prog_adjust(12, 1)
            else: self.picking, self.pick_cur = True, (e.pad.src.id if e.pad.src else 0)
        elif m == "SAMPLE":
            if i == 0: e.rec_toggle()
            elif i == 1:
                if e.rec_state != "idle": e.rec_toggle()
                else: e.stop_preview() if hasattr(e, "stop_preview") else None
            elif i == 2:
                src = e.rec_keep()
                if src is not None: self.chop_open(src)                     # KEEP: straight into CHOP with the take
            else: e.rec_discard()
        elif m == "CHOP":
            if i == 0: self.chop_audition()
            elif i == 1: self.chop_mark()
            elif i == 2: self.chop_unmark()
            else: self.chop_convert()
        elif m == "MIXER":
            if self.eq_open:
                if i == 0: self.eq_toggle(False)
                elif i == 1: self.eq_band = (self.eq_band - 1) % 5
                elif i == 2: self.eq_band = (self.eq_band + 1) % 5
                else: self.eq_flat()
            elif i == 1 and self.mix_view == "SENDS": self.mix_send ^= 1           # SENDS again: the other send
            elif i == 3 and self.mix_view == "PADS":                               # PADS again: the TRACKS of this sequence (and back)
                self.mix_page ^= 1; self.armed = [False] * 4
                self.say("TRACKS: level, pan, mute, solo of each track" if self.mix_page else "PADS: this program's pads")
            else: self.mix_set_view(self.MIX_VIEWS[i])
        elif m == "FX":
            tgt = self.fx_tgt()
            eff = e.get_fx(tgt)
            if self.valve_case:
                if i == 0: self.valve_case = None
                elif i == 1: self.valve_open(2 if self.valve_case == 1 else 1)
                elif i == 3: self.valve_insert()
            elif self.fx_browse:                                         # the effect list: F1 closes it, F4 loads
                if i == 0: self.fx_browse = eff is None
                elif i == 1 and eff is not None: e.toggle_bypass(tgt)
                elif i == 3: self.fx_load()
            elif i == 0: self.fx_browse = True; self.fx_cursor_to_loaded()
            elif i == 1:
                if eff is not None: e.toggle_bypass(tgt)
            elif i == 2:
                if eff is not None and eff.kind == "vst3": self.toggle_editor()
                else: e.set_fx(tgt); self.fx_browse = True; self.fx_cursor = 0
            elif eff is not None:                                        # F4: the next four parameters
                self.fx_set_page((self.fx_page + 1) % self.fx_pages())
        elif m == "MIDI":
            import midi as _m
            t = _m.LEARN_TARGETS[self.midi_row]
            if i == 0: self.midi_learn = None if self.midi_learn == t else t
            elif i == 1:
                if t == "PADS": self.midi_map.pad_ch, self.midi_map.pad_base = 10, 36
                else: self.midi_map.learned.pop(t, None)
                self.midi_map.save(); self.say(f"{t}: back to default" if t == "PADS" else f"{t}: cleared")
            elif i == 2: self.midi_map.key_ch = (self.midi_map.key_ch + 1) % 17; self.midi_map.save()
            else: self.go_back()
        elif m == "PADS":
            if i == 0: self.cycle_pad_mode(-1)
            elif i == 1: self.cycle_pad_mode(1)
            elif i == 2:
                if e.pad_mode == "16 LEVELS": e.levels_param = "TUNE" if e.levels_param == "VELOCITY" else "VELOCITY"
                elif e.pad_mode == "PERFORM": e.perf_chord = (e.perf_chord + 1) % len(CHORDS)
                elif e.pad_mode == "TRACK MUTE":
                    for t in e.seq.tracks: t.mute = False
                    self.say("all tracks on")
                elif e.pad_mode == "NEXT SEQ": e.next_seq = None
            else: self.go_back()
        elif m == "EXPORT":
            if self.e.bouncing: return
            if i == 0: self.ex_song = not self.ex_song; self.ex_sel = None
            elif i == 1: self.ex_dest = (self.ex_dest + 1) % len(self.ex_dests())
            elif i == 2: self.start_track_out()
            else: self.go_back()
        elif m == "BROWSE":
            if self.br_import:
                if i == 0: self.br_import = None
                elif i == 3: path, self.br_import = self.br_import, None; self.import_mpc(path)
            elif i == 0: self.br_audition = not self.br_audition
            elif i == 1: self.br_load()
            elif i == 2:
                drv = self._br_drive()
                if drv and self.usb_eject(*drv): self.br_dir = None; self.br_refresh()
            elif self.br_dir is not None: self.br_open(0)
            else: self.go_back()
        elif m == "SONG":
            if i == 0:                                                  # INSERT: a copy of this step after it
                cur = e.song[self.song_cur] if e.song else [e.cur_seq, 1]
                e.song.insert(self.song_cur + 1 if e.song else 0, [cur[0], cur[1]]); self.song_cur = min(len(e.song) - 1, self.song_cur + 1)
            elif i == 1:
                if len(e.song) > 1: del e.song[self.song_cur]; self.song_cur = clamp(self.song_cur, 0, len(e.song) - 1)
            elif i == 2: e.song_play()
            else: self.go_back()

    # ---------- touch ----------
    def touch(self, phase, x, y):
        if phase == "down":
            self.drag = None
            for (x0, y0, x1, y1), down, drag in reversed(self.hits):
                if x0 <= x < x1 and y0 <= y < y1:
                    if down: down(x, y)
                    self.drag = drag
                    return
        elif phase == "move" and self.drag:
            self.drag(x, y)
        elif phase == "up":
            self.drag = None; self.g_box = None

    # ---------- pads ----------
    def pad_hit(self, n, vel):
        e = self.e
        if e.bouncing: return                                      # TRACK OUT running
        if self.shift:
            self.shift_used = True; self.shift_pad(n); return
        if self.erase_down:                                       # ERASE + pad: erase that pad's notes while the sequence plays
            idx = e.bank * 16 + n - 1
            e.erase_hold(True, idx); self.erase_used = True
            e.trigger(e.prog.pads[idx], vel); return
        if self.mode == "MUTE":                                   # MUTE page: pad n mutes (or solos) track n, like an MPC's Track Mute
            self.pad_flash[n] = time.time(); self.mute_tap(n - 1); return
        if self.mode == "STEP" and e.track.kind not in NOTE_KINDS:
            self.step_toggle(n - 1)
            return
        if self.mode == "SONG" and e.song and not e.playing:      # SONG: pad n = sequence n for the highlighted step
            st = e.song[self.song_cur]; st[0] = (n - 1) % NSEQ
            self.pad_flash[n] = time.time()
            self.say(f"step {self.song_cur + 1:02d}: sequence {st[0] + 1:02d} {e.seqs[st[0]].name}")
            return
        if self.mode == "CHOP" and self.src is not None:          # CHOP: pad n plays (and selects) slice n of this bank
            k = e.bank * 16 + n - 1
            if k < len(self.src.regions()): self.pad_flash[n] = time.time(); self.chop_select(k, vel=vel)
            return
        if self.pad_mode_hit(n, vel): return
        e.pad_hit(n, vel)
        self.armed = [False] * 4
        if self.mode == "FX" and self.fx_target < 64: self.fx_target, self.fx_page = e.pad_idx, 0
        if self.mode == "GRID" and e.track.kind not in NOTE_KINDS: self.g_lane = n - 1

    def step_track(self, d):
        """GRID header < / >: the previous / next track (its grid opens at the selected pad)"""
        self.e.cur_track = (self.e.cur_track + d) % 16
        self.track_setup = None
        if self.e.track.kind not in NOTE_KINDS: self.g_lane = self.e.sel
        self.g_sel = None

    def mute_tap(self, k):
        """MUTE page: a tile tap or pad hit mutes / unmutes track k (in SOLO MODE: solos it)"""
        tr = self.e.seq.tracks[k % 16]
        self.e.cur_track = k % 16
        if self.mute_solo: tr.solo = not tr.solo; self.say(f"{tr.name}: {'solo' if tr.solo else 'solo off'}")
        else: self.mute_toggle(tr)

    def cycle_track_type(self, k):
        """the TYPE button on a SEQ track row opens the track setup panel (DRUM / KEYGROUP / PLUGIN / MIDI)"""
        self.e.cur_track = k
        self.track_setup = None if self.track_setup == k else k
        self.ts_tab = None

    # ---------- the 24 buttons ----------
    def button(self, i, down):
        e = self.e
        if e.bouncing and i != BTN["SHIFT"] and i not in MODE_KEYS: return       # TRACK OUT running: transport keys wait
        if i == BTN["SHIFT"]:
            self.shift = down
            if down: self.shift_t, self.shift_used = time.time(), False
            else: self.shift_studio = False
            return
        if self.shift and down: self.shift_used = True
        if i == BTN["ERASE"]:
            if down:
                self.erase_down, self.erase_t, self.erase_used = True, time.time(), False
                if self.shift:
                    e.pad.solo = not e.pad.solo; self.erase_used = True
                    self.say(f"pad {e.pad_idx + 1} solo {'on' if e.pad.solo else 'off'}")
                else: e.erase_hold(True, None)
            else:
                e.erase_hold(False); self.erase_down = False
                if not self.erase_used and not e.playing:
                    if time.time() - self.erase_t > 1.0: e.clear_track(); self.say("track cleared")
                    else:
                        if self.mode == "GRID":
                            ev = e.find_note(self.g_tick, self.g_lane)
                            if ev: e.begin_edit(); e.remove_note(ev); self.say("note deleted")
                        else: e.erase_pad_events(e.pad_idx); self.say(f"pad {e.pad_idx + 1} notes erased")
            return
        if not down: return
        s = self.shift
        if i == BTN["PLAY"]:
            self.save() if s else e.play()
        elif i == BTN["STOP"]:
            if s:
                with e.lock:
                    for k in range(e.nv): e.v_data[k], e.v_pad[k] = None, None
                self.say("all notes off")
            else: e.stop()
        elif i == BTN["PLAYSTART"]: e.play_start()
        elif i == BTN["REC"]:
            if s: e.count_in = (e.count_in + 1) % 3; self.say("count-in: " + ("off", "1 bar", "2 bars")[e.count_in])
            elif self.mode == "SAMPLE": e.rec_toggle()
            else: e.set_rec("rec", start=True)
        elif i == BTN["OVERDUB"]:
            if s: e.metro = not e.metro; self.say("metronome " + ("on" if e.metro else "off"))
            else: e.set_rec("over", start=True)
        elif i in MODE_KEYS:
            m = MODE_KEYS[i]
            if s and m == "GRID": self.set_mode("SONG")
            elif m == "GRID" and self.mode in ("GRID", "SEQ", "STEP"):        # GRID again: track grid -> all tracks -> STEP -> ...
                self.set_mode({"GRID": "SEQ", "SEQ": "STEP", "STEP": "GRID"}[self.mode])
            elif s and m == "MAIN": self.set_mode("MENU")
            elif s and m == "PROG": self.set_mode("BROWSE")
            elif s and m == "MIXER": self.set_mode("FX")
            elif s and m == "MUTE": self.set_mode("PADS")                   # pad modes (there is no STEP key: GRID cycles to STEP)
            elif s and m == "SAMPLE": self.set_mode("EXPORT")
            else: self.set_mode(m)
        elif i == BTN["UNDO"]:
            e.redo() if s else e.undo_toggle()
        elif i == BTN["TAP"]:
            if s: e.quantize_track()
            else: self.tap()
        elif i == BTN["LOAD"]:                                         # LOAD: the file browser (SHIFT + LOAD: projects)
            if s: self.set_mode("PROJECTS")
            elif self.mode == "BROWSE": self.set_mode(self.prev_mode if self.prev_mode and self.prev_mode != "BROWSE" else "MAIN")
            else: self.set_mode("BROWSE")
        elif i == BTN["REPEAT"]:
            if s:
                rates = [48, 24, 12]; e.rep_div = rates[(rates.index(e.rep_div) + 1) % 3] if e.rep_div in rates else 24
                self.say({48: "repeat 1/8", 24: "repeat 1/16", 12: "repeat 1/32"}[e.rep_div])
            else:
                e.rep_on = not e.rep_on
                if not e.rep_on: e.rep_pad = None
                self.say("note repeat " + ("on: hit a pad to start, hit it again to stop" if e.rep_on else "off"))
        elif BTN["F1"] <= i <= BTN["F4"]: self.soft(i - BTN["F1"])

    def tap(self):
        now = time.time()
        self.taps = [t for t in self.taps if now - t < 2.0] + [now]
        if len(self.taps) >= 2:
            gaps = [b - a for a, b in zip(self.taps, self.taps[1:])][-4:]
            self.e.seq.bpm = clamp(60.0 / (sum(gaps) / len(gaps)), 60.0, 180.0)
            self.say(f"tap tempo {self.e.seq.bpm:.1f}")


from screens import Renderer          # noqa: E402  (re-exported: `from ui import Controls, Renderer`)
