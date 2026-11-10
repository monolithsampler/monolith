"""
asrpanel.py - the ASR-10's own way of working, as a switchable option on the ASR-10's MAIN screen ("ASR KEYS" on the rail).

The real machine (Musician's Manual, Section 1): three mode buttons - LOAD, COMMAND, EDIT - and fourteen page buttons
(Instrument, Seq-Song, System-MIDI, Effects, then 1-9 and 0: Env 1, Env 2, Env 3, Pitch, Filters, Amp, LFO, Wave, Layer,
Track). Any parameter is two presses away: a mode, a page. Pressing the page again steps to its next screen. Left / right
= the next parameter, up / down and the data slider = its value, Enter-Yes runs a command, Cancel-No puts a parameter back
as it was before you touched it. The display: the mode word top left, the page word(s), the sequencer status top right,
one 22-character line.

Only what Monolith really does is on the pages: the rows are PROG's own (ui.prog_adjust / Renderer.prog_value), so the
ASR keys and PROG always agree. Pages Monolith has nothing for (Env 2, Layer) say so instead of showing dead parameters.
The classic ASR screen (machines.asr10) is untouched; this only runs while the switch is on.
"""
import copy

W = 22                                                         # the display's characters
MODES = ("LOAD", "COMMAND", "EDIT")
PAGES = ("Instrument", "Seq Song", "Sys MIDI", "Effects", "Env 1", "Env 2", "Env 3", "Pitch", "Filters", "Amp", "LFO",
         "Wave", "Layer", "Track")
NUM = {"Env 1": 1, "Env 2": 2, "Env 3": 3, "Pitch": 4, "Filters": 5, "Amp": 6, "LFO": 7, "Wave": 8, "Layer": 9, "Track": 0}
WORDS = {"Instrument": ["INST"], "Seq Song": ["SEQ"], "Sys MIDI": ["MIDI"], "Effects": ["FX"], "Env 1": ["PITCH", "ENV"],
         "Env 2": ["FILTER", "ENV"], "Env 3": ["AMP", "ENV"], "Pitch": ["PITCH"], "Filters": ["FILTER"], "Amp": ["AMP"],
         "LFO": ["LFO"], "Wave": ["WAVE"], "Layer": ["LAYER"], "Track": ["TRACK"]}

# EDIT: the PROG rows on each page, with the ASR's names. (row, name, Q-link?)
EDIT_ROWS = {
    "Env 1": [(36, "ENV1 ATTACK"), (37, "ENV1 DECAY"), (38, "ENV1 SUSTAIN"), (39, "ENV1 RELEASE")],
    "Env 3": [(64, "ATTACK TIME"), (65, "DECAY1 TIME"), (66, "DECAY2 TIME"), (67, "DECAY3 TIME"), (68, "RELEASE TIME"),
              (69, "INITIAL LEVEL"), (70, "PEAK LEVEL"), (71, "BREAK1 LEVEL"), (72, "BREAK2 LEVEL"), (73, "SUSTAIN LEVEL"),
              (74, "SOFT VEL LEVEL"), (75, "SOFT VEL CURVE"), (76, "ENVELOPE MODE")],
    "Pitch": [(3, "SEMITONE"), (41, "FINE TUNE")],
    "Filters": [(59, "MODE"), (60, "CUTOFF F1"), (61, "CUTOFF F2"), (62, "KBD AMT F1"), (63, "KBD AMT F2")],
    "Amp": [(4, "WS VOLUME"), (5, "WS PAN"), (43, "BOOST")],
    "LFO": [(32, "LFO WAVE"), (33, "LFO RATE"), (34, "LFO DEPTH"), (35, "LFO DELAY")],
    "Wave": [(1, "SMPL START"), (2, "SAMPLE END"), (24, "LOOP"), (25, "LOOPSTART"), (26, "LOOPEND"), (31, "LOOPPOS"),
             (27, "MOD"), (28, "MOD SRC"), (29, "MOD AMT"), (30, "MOD RANGE")],
    "Effects": [(58, "FX BUS"), (44, "EFFECT")],
    "Sys MIDI": [(54, "SYSTEM RATE")],
}
NOT_HERE = "NOT IN MONOLITH YET"


def _clip(s): return s.upper()[:W]


class Item:
    """one parameter / command on a page. kind: 'row' (a PROG row), 'fn' (get / adjust / show), 'cmd' (Enter runs it),
    'none' (a page Monolith has nothing for)."""
    def __init__(self, kind, name, row=None, get=None, adj=None, show=None, run=None, q=True):
        self.kind, self.name, self.row, self.get, self.adj, self.show, self.run, self.q = kind, name, row, get, adj, show, run, q


class Panel:
    def __init__(self, ctl):
        self.c, self.e = ctl, ctl.e
        self.mode, self.page, self.idx = "EDIT", "Filters", 0
        self.ask = None                         # a question: {"text": fn, "adj": fn or None, "yes": fn, "no": label, "yesl": label}
        self.before = None                      # (page, idx, snapshot): what Cancel puts back
        self.flash = None                       # a message the display shows for a moment (as the ASR's own)

    # ---------------------------------------------------------------- the pages
    def items(self, mode=None, page=None):
        e, c = self.e, self.c
        mode, page = mode or self.mode, page or self.page
        sq, tr = e.seq, e.track
        if mode == "EDIT":
            if page in EDIT_ROWS: return [Item("row", n, row=r) for r, n in EDIT_ROWS[page]]
            if page == "Instrument":
                return [Item("fn", "INST", get=lambda: e.programs[tr.prog].name, show=lambda: e.programs[tr.prog].name.upper(),
                             adj=lambda n: setattr(tr, "prog", (tr.prog + (1 if n > 0 else -1)) % len(e.programs))),
                        Item("fn", "MIDI OUT CHAN", get=lambda: tr.midi_ch, show=lambda: "OFF" if not tr.midi_ch else str(tr.midi_ch),
                             adj=lambda n: setattr(tr, "midi_ch", max(0, min(16, tr.midi_ch + n))))]
            if page == "Seq Song":
                return [Item("fn", "TEMPO", get=lambda: sq.bpm, show=lambda: f"{sq.bpm:5.1f} BPM".strip(),
                             adj=lambda n: setattr(sq, "bpm", max(60.0, min(180.0, round(sq.bpm + (0.1 if c.shift else 1.0) * n, 1))))),
                        Item("fn", "LOOP", get=lambda: sq.loop, show=lambda: "ON" if sq.loop else "OFF",
                             adj=lambda n: setattr(sq, "loop", not sq.loop)),
                        Item("fn", "BARS", get=lambda: sq.bars, show=lambda: str(sq.bars), adj=lambda n: e.set_bars(sq.bars + n))]
            if page == "Track":
                return [Item("fn", "MIX", get=lambda: tr.vol, show=lambda: f"{tr.vol * 99:.0f}",
                             adj=lambda n: setattr(tr, "vol", max(0.0, min(1.0, round(tr.vol + 0.01 * n, 2))))),
                        Item("fn", "PAN", get=lambda: tr.pan, show=lambda: f"{tr.pan * 99:+.0f}" if abs(tr.pan) > 0.005 else "0",
                             adj=lambda n: setattr(tr, "pan", max(-1.0, min(1.0, round(tr.pan + 0.02 * n, 2))))),
                        Item("fn", "STATUS", get=lambda: tr.mute, show=lambda: "MUTE" if tr.mute else "PLAY",
                             adj=lambda n: setattr(tr, "mute", not tr.mute))]
            return [Item("none", NOT_HERE)]
        if mode == "COMMAND":
            if page == "Wave":
                return [Item("cmd", "TRUNCATE WAVESAMPLE", run=self.truncate, row=(1, 2)),     # Q1 / Q2: where it cuts
                        Item("cmd", "NORMALIZE GAIN", run=self.normalize),
                        Item("cmd", "TIME COMPRESS/EXPAND", run=self.warp),
                        Item("cmd", "CREATE TRANSWAVE", run=self.transwave)]
            if page == "Track":
                return [Item("cmd", "QUANTIZE TRACK", run=self.quantize),
                        Item("cmd", "COPY TRACK", run=self.copy_track),
                        Item("cmd", "ERASE TRACK", run=self.erase_track),
                        Item("cmd", "SHIFT TRACK BY CLOCKS", run=self.shift_track)]
            if page == "Seq Song":
                return [Item("cmd", "COPY SEQUENCE", run=self.copy_seq),
                        Item("cmd", "ERASE SEQUENCE", run=self.erase_seq),
                        Item("cmd", "EDIT SONG STEPS", run=lambda: c.set_mode("SONG"))]
            if page == "Instrument":
                return [Item("cmd", "SAVE BANK", run=self.save)]
            return [Item("none", NOT_HERE)]
        # LOAD: what is in memory (the solid LOAD), and the disk (BROWSE)
        if page == "Instrument":
            return [Item("fn", "", get=lambda: tr.prog, show=lambda: f"INST {tr.prog + 1}={e.programs[tr.prog].name.upper()}",
                         adj=lambda n: setattr(tr, "prog", (tr.prog + (1 if n > 0 else -1)) % len(e.programs)), q=False),
                    Item("cmd", "LOAD FROM DISK", run=lambda: c.set_mode("BROWSE"))]
        if page == "Seq Song":
            return [Item("fn", "", get=lambda: e.cur_seq, show=lambda: f"SEQ {e.cur_seq + 1:02d}={sq.name.upper()}",
                         adj=lambda n: e.select_seq(e.cur_seq + (1 if n > 0 else -1)), q=False),
                    Item("cmd", "LOAD FROM DISK", run=lambda: c.set_mode("BROWSE"))]
        return [Item("cmd", "LOAD FROM DISK", run=lambda: c.set_mode("BROWSE"))]

    def item(self):
        its = self.items()
        self.idx %= len(its)
        return its[self.idx]

    # ---------------------------------------------------------------- what the display says
    def value_text(self, it):
        if it.kind == "row":
            e, p = self.e, self.e.pad
            short = {74: lambda: f"{p.a_softvel}%", 33: lambda: str(p.a_lfo_rate),
                     31: lambda: f"{self._loop_len()} SMP", 54: lambda: "44.1 KHZ" if e.asr_rate else "29.76 KHZ",
                     44: lambda: (e.get_fx(p).name[:12] if e.get_fx(p) is not None else "NONE")}
            if it.row in short: return short[it.row]().upper()
            from screens import Renderer
            v = Renderer.prog_value(_Shim(self.e), it.row)
            return str(v).upper().replace(" (OPEN)", "").strip()
        if it.kind == "fn": return str(it.show())
        return ""

    def _loop_len(self):
        from engine import ASR_RATES, OUT_SR
        p = self.e.pad
        reg = p.length / OUT_SR; le = p.a_le if p.a_le > 0 else reg
        return int(max(0.0, le - p.a_ls) * ASR_RATES[self.e.asr_rate])

    def line(self):
        if self.ask is not None: return _clip(self.ask["text"]())
        if self.flash is not None:
            import time
            if time.time() - self.flash[1] < 1.8: return _clip(self.flash[0])
            self.flash = None
        it = self.item()
        if it.kind in ("cmd", "none"): return _clip(it.name)
        v = self.value_text(it)
        return _clip(v if not it.name else f"{it.name}={v}")              # (LOAD's memory lists: the name is in the value)

    def words(self):
        return WORDS[self.page] + (["SONG"] if self.page == "Seq Song" and self.e.song_mode else [])

    def status(self):
        """the sequencer status word, and whether it flashes (count-in, standby)"""
        e = self.e
        if e.playing and e.pos < 0: return "PLAY", True
        if e.playing and e.rec == "rec": return "REC", False
        if e.playing and e.rec == "over": return "ODUB", False
        if e.playing: return "PLAY", False
        if e.rec == "rec": return "REC", True
        if e.rec == "over": return "ODUB", True
        return "STOP", False

    def waiting(self):
        """Enter has something to do: a question, or a command on the display"""
        return self.ask is not None or self.item().kind == "cmd"

    # ---------------------------------------------------------------- keys
    def set_mode(self, m):
        self.ask = None; self.before = None
        if m != self.mode: self.mode, self.idx = m, 0

    def press_page(self, pg):
        """a page key: that page; pressed again, its next screen (as the ASR's page buttons)"""
        self.ask = None
        if pg == self.page: self.idx = (self.idx + 1) % len(self.items())
        else: self.page, self.idx, self.before = pg, 0, None

    def move(self, d):
        """left / right: the previous / next parameter or command on the page"""
        if self.ask is not None: return
        self.idx = (self.idx + d) % len(self.items()); self.before = None

    def data(self, n):
        """the data slider / up-down: change the value shown (or the question's value)"""
        if self.ask is not None:
            if self.ask.get("adj"): self.ask["adj"](n)
            return
        it = self.item()
        if it.kind not in ("row", "fn"): return
        if self.before is None or self.before[:2] != (self.page, self.idx): self.before = (self.page, self.idx, self._snap(it))
        if it.kind == "row":
            if it.row == 44: return                                   # EFFECT: Enter opens the FX page (the jog leaves it)
            self.c.prog_adjust(it.row, n)
        else: it.adj(n)

    def adjust_item(self, it, n):
        """a Q-link turned: change that parameter (Cancel can put it back, as with the slider)"""
        if it.kind == "row" and self.item().kind == "cmd":             # a command's own setting: straight to the PROG row
            self.c.prog_adjust(it.row, n); return
        its = self.items()
        k = next((i for i, x in enumerate(its) if x.name == it.name), None)
        if k is None: return
        self.idx = k
        self.data(n)

    def enter(self):
        """Enter-Yes: answer yes, or run the command on the display (EFFECT: its page)"""
        if self.ask is not None:
            q, self.ask = self.ask, None
            q["yes"](); return
        it = self.item()
        if it.kind == "cmd": it.run()
        elif it.kind == "row" and it.row == 44: self.c.prog_adjust(44, 1)

    def cancel(self):
        """Cancel-No: answer no; otherwise put the parameter back as it was before it was last edited"""
        if self.ask is not None:
            self.ask = None; self.say("COMMAND CANCELLED"); return
        if self.before is not None and self.before[:2] == (self.page, self.idx):
            self._restore(self.item(), self.before[2]); self.before = None

    def _snap(self, it):
        if it.kind == "row":
            p = self.e.pad
            return {k: copy.deepcopy(v) for k, v in vars(p).items()
                    if not k.startswith("_") and isinstance(v, (int, float, str, bool, list, tuple, type(None)))}
        return copy.deepcopy(it.get())

    def _restore(self, it, snap):
        if it.kind == "row":
            p = self.e.pad
            for k, v in snap.items(): setattr(p, k, v)
            self.e.pad_changed(p)
        else:                                                          # step back to the old value
            for _ in range(400):
                if it.get() == snap: break
                cur = it.get()
                try: it.adj(-1 if (isinstance(cur, (int, float)) and cur > snap) else 1)
                except Exception: break
                if it.get() == cur: break

    def qlinks(self):
        """the four main parameters of the page (the ASR has one data slider; Monolith adds these)"""
        if self.ask is not None and self.ask.get("adj"):
            return [(self.ask.get("qname", "VALUE"), self.ask["text"])]
        cur = self.item()
        if cur.kind == "cmd" and cur.row:                              # a command with settings (TRUNCATE: start / end)
            return [Item("row", n, row=r) for r, n in zip(cur.row, ("SMPL START", "SAMPLE END"))]
        out = []
        for it in self.items():
            if it.kind in ("row", "fn") and it.q and not (it.kind == "row" and it.row == 44): out.append(it)
            if len(out) == 4: break
        return out

    def say(self, t):
        import time
        self.flash = (t, time.time())

    # ---------------------------------------------------------------- commands
    def _pad_ok(self):
        if self.e.pad.empty: self.say("NO WAVESAMPLE ON PAD"); return False
        return True

    def truncate(self):
        """TRUNCATE WAVESAMPLE: keep only start .. end. A new sample (the old one stays in the project until DELETE
        UNUSED SAMPLES), so the pad's own edits are not lost."""
        if not self._pad_ok(): return
        e, p = self.e, self.e.pad
        s0, s1 = int(p.start), int(p.end)
        if s0 <= 0 and s1 >= p.src.length: self.say("NOTHING TO TRUNCATE"); return
        base = (p.src.name + "_t")[:20]; name, k = base, 2
        while e.source_by_name(name) is not None: name, k = f"{base}{k}", k + 1
        src = e.add_source(name, p.src.raw[s0:s1].copy(), dirty=True)
        p.assign(src); e.pad_changed(p)
        self.say("WAVESAMPLE TRUNCATED")

    def normalize(self):
        if not self._pad_ok(): return
        p = self.e.pad
        if not p.norm: self.c.prog_adjust(9, 1)
        self.say("COMMAND COMPLETED")

    def warp(self):
        if not self._pad_ok(): return
        p = self.e.pad
        self.ask = {"text": lambda: f"STRETCH={p.stretch}% {'ON' if p.warp else 'OFF'}"[:W], "qname": "STRETCH",
                    "adj": lambda n: setattr(p, "stretch", int(max(25, min(400, p.stretch + n)))),
                    "yes": lambda: (self.e.set_warp(p, True), self.say("COMMAND COMPLETED"))}

    def transwave(self):
        if not self._pad_ok(): return
        self.c.make_transwave(); self.say("TRANSWAVE CREATED")

    def quantize(self):
        from engine import ASR_Q
        e = self.e
        def go():
            if e.playing: self.say("STOP SEQUENCER FIRST"); return
            if not e.track.events: self.say("NO DATA ON SOURCE TRK"); return
            e.quantize_track(ASR_Q[e.asr_q][1]); self.say("COMMAND COMPLETED")
        self.ask = {"text": lambda: f"QUANTIZE TO={ASR_Q[e.asr_q][0]}", "qname": "QUANTIZE",
                    "adj": lambda n: setattr(e, "asr_q", max(0, min(len(ASR_Q) - 1, e.asr_q + (1 if n > 0 else -1)))), "yes": go}

    def copy_track(self):
        e = self.e; st = {"to": (e.cur_track + 1) % 16}
        self.ask = {"text": lambda: f"TO TRACK={st['to'] + 1:02d}", "qname": "TO TRACK",
                    "adj": lambda n: st.__setitem__("to", (st["to"] + (1 if n > 0 else -1)) % 16),
                    "yes": lambda: (e.copy_track(e.cur_track, st["to"]), self.say("COMMAND COMPLETED"))}

    def erase_track(self):
        e = self.e
        self.ask = {"text": lambda: f"ERASE TRACK {e.cur_track + 1:02d}?", "yes": lambda: (e.clear_track(), self.say("COMMAND COMPLETED"))}

    def shift_track(self):
        e = self.e; st = {"n": 0}
        self.ask = {"text": lambda: f"SHIFT={st['n']:+d} CLOCKS", "qname": "CLOCKS",
                    "adj": lambda n: st.__setitem__("n", max(-96, min(96, st["n"] + n))),
                    "yes": lambda: (e.nudge(st["n"]) if st["n"] else None, self.say("COMMAND COMPLETED"))}

    def copy_seq(self):
        from engine import NSEQ
        e = self.e; st = {"to": (e.cur_seq + 1) % NSEQ}
        self.ask = {"text": lambda: f"TO SEQ={st['to'] + 1:02d}", "qname": "TO SEQ",
                    "adj": lambda n: st.__setitem__("to", (st["to"] + (1 if n > 0 else -1)) % NSEQ),
                    "yes": lambda: (e.copy_sequence(e.cur_seq, st["to"]), self.say("COMMAND COMPLETED"))}

    def erase_seq(self):
        e = self.e
        self.ask = {"text": lambda: f"ERASE SEQ {e.cur_seq + 1:02d}?", "yes": lambda: (e.clear_sequence(), self.say("COMMAND COMPLETED"))}

    def save(self):
        self.c.save(); self.say("BANK SAVED")


class _Shim:
    """lets the PROG page's value formatter (Renderer.prog_value) run without a screen"""
    PROG_ROWS = None

    def __init__(self, e):
        self.e = e
        from screens import Renderer
        _Shim.PROG_ROWS = Renderer.PROG_ROWS

    def asr_value(self, row):
        from screens import Renderer
        return Renderer.asr_value(self, row)
