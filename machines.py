"""
machines.py - the classic machines' main screens, built from the sampler's own state: what each line says, which fields
the cursor can visit, what turning the jog wheel on a field does, and what the soft keys do.

MAIN shows one of these in place of its sequence panel when a machine is chosen (tap the machine name on the panel, or
EDIT > QUANTISE > MACHINE). Layouts follow photos of the real screens; the text is generated here, nothing is copied
from the machines' firmware. MPC60 and MPC3000 also switch the sequencer to their timing (see EMULATION_NOTES.md).
"""
from engine import NSEQ, NPROG, MAX_BARS, QUANT, BANKS, PPQ
import lcd

from engine import MACHINES
LINN = ("MPC60", "MPC3000")                       # Roger Linn's timing: swing into the notes, swung note repeat
NOTE = chr(1)                                      # the quarter-note glyph


class Screen:
    """lines of text plus the fields on them: fields = [(key, row, col, length)] in cursor order; legends = the lit /
    unlit words a fluorescent display has printed above its characters [(word, lit)]"""
    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.lines = [[" "] * cols for _ in range(rows)]
        self.fields, self.inverse, self.legends = [], [], []

    def put(self, row, col, text, key=None, inverse=False):
        text = str(text)
        if col < 0: col = self.cols + col - len(text) + 1        # negative: right-aligned, ending at that column
        for i, ch in enumerate(text):
            if 0 <= col + i < self.cols: self.lines[row][col + i] = ch
        if key: self.fields.append((key, row, col, len(text)))
        if inverse: self.inverse.append((row, col, len(text)))
        return col + len(text)

    def right(self, row, parts, end=None):
        """parts [(text, key or None)] placed so the last one ends at the right edge (or before column `end`)"""
        total = sum(len(str(t)) for t, _ in parts)
        col = (self.cols if end is None else end) - total
        for t, k in parts: col = self.put(row, col, t, k)

    def rule(self, row, title="", tail=""):
        """=== title === across the row (tail = a character at the far right, e.g. the pad bank)"""
        width = self.cols - len(tail)
        t = f" {title} " if title else ""
        left = (width - len(t)) // 2
        self.put(row, 0, "=" * left + t + "=" * (width - left - len(t)) + tail)

    def text(self): return ["".join(r) for r in self.lines]


def _now(e):
    sq = e.seq
    pos = max(0.0, e.pos)
    bar = int(pos // sq.bar_ticks) + 1
    beat = int((pos % sq.bar_ticks) // sq.beat_ticks) + 1
    tick = int(pos % sq.beat_ticks)
    secs = pos / PPQ * 60.0 / max(1.0, sq.bpm)
    return bar, beat, tick, secs


def _name(e, i=None):
    sq = e.seqs[e.cur_seq if i is None else i]
    used = any(t.events for t in sq.tracks)
    return sq.name if used else "(unused)"


def _status(e):
    if e.rec == "rec": return "(Recording)" if e.playing else "(Record Ready)"
    if e.rec == "over": return "(Overdubbing)" if e.playing else "(Overdub Ready)"
    return ""


def _kind(tr):
    return {"drum": "DRUM", "keys": "KEYS", "plugin": "PLUG", "midi": "MIDI"}.get(tr.kind, "DRUM")


def mpc_linn(e, machine):
    """MPC60 / MPC3000 Play/Record screen: 40 x 8"""
    s, sq, tr = Screen(40, 8), e.seq, e.track
    title = "Play/Record" + (" " + _status(e) if _status(e) else "")
    s.rule(0, title, BANKS[e.bank] if machine == "MPC60" else "")
    s.put(1, 0, "Seq:"); s.put(1, 4, f"{e.cur_seq + 1:2d}", "seq"); s.put(1, 6, "-" + _name(e)[:16])
    s.right(1, [("BPM:", None), (f"{sq.bpm:5.1f}", "bpm"), (" (SEQ)", None)])
    s.put(2, 0, "Sig:"); s.put(2, 4, f"{sq.num:2d}", "num"); s.put(2, 6, "/"); s.put(2, 7, f"{sq.den:2d}", "den")
    s.put(2, 12, "Bars:"); s.put(2, 17, f"{sq.bars:3d}", "bars")
    s.right(2, [("Loop:", None), ("TO BAR   1" if sq.loop else "OFF       ", "loop")])
    s.rule(3, "Track Data")
    s.put(4, 0, "Trk:"); s.put(4, 4, f"{tr.n + 1:2d}", "trk"); s.put(4, 6, "-" + tr.name[:16])
    s.right(4, [("Type:" + _kind(tr) + " On:", None), ("NO " if tr.mute else "YES", "on")])
    s.put(5, 0, "Chn:"); s.put(5, 4, f"{tr.midi_ch:>3}" if tr.midi_ch else "OFF", "chn"); s.put(5, 7, "-(off)" if not tr.midi_ch else "-(out)")
    s.put(5, 18, "& OFF")
    s.right(5, [("Vel%:", None), (f"{int(round(tr.vol * 100)):3d}", "vel"), (" Pgm:", None), (f"{tr.prog + 1:3d}", "pgm")])
    bar, beat, tick, secs = _now(e)
    hh, mm, ss, ff = int(secs // 3600), int(secs // 60) % 60, int(secs) % 60, int((secs % 1) * 30)
    s.rule(6, f"Now:{bar:03d}.{beat:02d}.{tick:02d} ({hh:02d}:{mm:02d}:{ss:02d}:{ff:02d})")
    s.put(7, 0, f"<Tk on/off> <Solo={'ON ' if tr.solo else 'OFF'}> <Track-> <Track+>")
    return s


def mpc_xl(e):
    """MPC2000XL main screen: a 248 x 60 graphic LCD, here 41 x 7 characters with its soft keys F1-F6 on the last row"""
    s, sq, tr = Screen(41, 7), e.seq, e.track
    bar, beat, tick, secs = _now(e)
    st = {"(Recording)": "REC", "(Record Ready)": "REC", "(Overdubbing)": "ODUB", "(Overdub Ready)": "ODUB"}.get(_status(e), "")
    if st: s.put(0, 0, f" {st} ", inverse=True)
    s.put(0, -1, f"Now:{bar:03d}.{beat:02d}.{tick:02d}")
    s.put(1, 0, "Sq:"); s.put(1, 3, f"{e.cur_seq + 1:02d}", "seq"); s.put(1, 5, "-" + _name(e).replace("(unused)", "(Unused)")[:12])
    s.put(1, 19, "Timing:"); s.put(1, 26, QUANT[e.qgrid][0].ljust(5), "timing")
    s.right(1, [("TSig:", None), (f"{sq.num}", "num"), ("/", None), (f"{sq.den}", "den")])
    s.put(2, 0, NOTE + "="); s.put(2, 2, f"{sq.bpm:5.1f}", "bpm"); s.put(2, 7, "(SEQ)")
    s.put(2, 19, "Loop:"); s.put(2, 24, "ON " if sq.loop else "OFF", "loop")
    s.right(2, [("Bars:", None), (f"{sq.bars:2d}", "bars")])
    s.put(3, 0, "Count:"); s.put(3, 6, ("OFF", "1BAR", "2BAR")[e.count_in].ljust(4), "count")
    s.right(3, [("Pgm:", None), (f"{tr.prog + 1:3d}", "pgm")])
    s.put(4, 0, "Tr:"); s.put(4, 3, f"{tr.n + 1:02d}", "trk"); s.put(4, 5, "-" + tr.name[:12])
    s.put(4, 19, "ON:"); s.put(4, 22, "NO " if tr.mute else "YES", "on")
    s.right(4, [("Velo%:", None), (f"{int(round(tr.vol * 100)):3d}", "vel")])
    s.put(5, 0, f"S:{_kind(tr)}{tr.prog + 1}:{'OFF' if not tr.midi_ch else tr.midi_ch} {e.prog.name[:12]}")
    for i, lab in enumerate(("STEP", "EDIT", "TrMUTE", "SOLO", "Tr -", "Tr +")):
        s.put(6, i * 7, lab.center(6), "soft%d" % i, inverse=True)
    return s


def sp1200(e):
    """SP-1200: a 16 x 2 character LCD. Line 2 shows the sampler's messages (the SP uses it for prompts)."""
    s, sq = Screen(16, 2), e.seq
    s.put(0, 0, "Seg "); s.put(0, 4, f"{e.cur_seq + 1:02d}", "seq"); s.put(0, 8, NOTE + "="); s.put(0, 10, f"{sq.bpm:05.1f}", "bpm")
    import time
    from engine import SP_CORRECT, SP_SWINGS
    import engine as _eng
    if e.msg and getattr(e, "msg_level", "info") in ("info", "warn") and time.time() - e.msg_time < 2.2:
        s.put(1, 0, e.msg[:16])                                          # the SP's prompts and messages
    else:                                                                # resting: auto-correct and swing, both editable
        s.put(1, 0, "AC:"); s.put(1, 3, SP_CORRECT[e.sp_ac][0].ljust(5), "ac")
        s.put(1, 9, "Sw:"); s.put(1, 12, "%d%%" % SP_SWINGS[_eng.Engine.sp_swing_k(sq.swing)], "swing")
    return s


ASR_PAGES = ("seq", "trk", "asrq", "bpm", "rate")


def asr10(e, cur=None):
    """ASR-10: its blue-green fluorescent display - one 20-character line, with the lit words above it saying where you
    are. It shows one thing at a time: the arrows step through the pages (sequence, track / instrument, QUANTIZE TRACK,
    tempo, system rate), the jog wheel changes the one shown. Messages take over the line for a moment, as on the machine."""
    import time
    from engine import ASR_Q
    s, sq, tr = Screen(20, 1), e.seq, e.track
    page = cur if cur in ASR_PAGES else "seq"
    if e.msg and getattr(e, "msg_level", "info") in ("info", "warn") and time.time() - e.msg_time < 2.2:
        s.put(0, 0, e.msg.upper()[:20])                                  # (only a message that is meant to be seen)
    elif page == "seq":
        if e.playing or e.pos > 0:
            bar, beat, _, _ = _now(e); s.put(0, 0, f"SEQ{e.cur_seq + 1:02d} BAR{bar:3d} BEAT{beat}")
        else: s.put(0, 0, f"SEQ{e.cur_seq + 1:02d}={_name(e).upper()[:13]}")
    elif page == "trk": s.put(0, 0, f"TRK{tr.n + 1:2d} INST{tr.prog + 1}={e.programs[tr.prog].name.upper()[:7]}")
    elif page == "asrq": s.put(0, 0, f"QUANTIZE TO {ASR_Q[e.asr_q][0]}")
    elif page == "bpm": s.put(0, 0, f"TEMPO={sq.bpm:5.1f} BPM")
    else: s.put(0, 0, ("RATE=29.7619 KHZ", "RATE=44.1000 KHZ")[e.asr_rate])
    for k in ASR_PAGES: s.fields.append((k, 0, 0, 20 if k == page else 0))      # only the page shown can be tapped
    rec = e.rec != "off"
    s.legends = [("LOAD", page in ("trk",)), ("INST", page == "trk"), ("EDIT", page == "asrq"), ("SEQ", page == "seq"),
                 ("SONG", e.song_mode), ("TRACK", page == "trk"), ("BAR", e.playing), ("BEAT", e.playing),
                 ("CLOCK", page in ("bpm", "rate")), ("REC", rec), ("PLAY", e.playing), ("STOP", not e.playing)]
    return s


def screen(e, machine, cur=None):
    if machine in LINN: return mpc_linn(e, machine)
    if machine == "MPC2000XL": return mpc_xl(e)
    if machine == "SP-1200": return sp1200(e)
    if machine == "ASR-10": return asr10(e, cur)
    return None


STYLE = {"MPC60": lcd.MPC_BLUE, "MPC3000": lcd.MPC_BLUE, "MPC2000XL": lcd.XL_GREY, "SP-1200": lcd.SP_GREEN,
         "ASR-10": lcd.VFD_CYAN}
# printed on the bezel: (small line, big name), plus the bezel colour
BEZEL = {"MPC60": ("MIDI PRODUCTION|CENTER", "MPC60", (16, 16, 18)),
         "MPC3000": ("MIDI PRODUCTION|CENTER", "MPC3000", (16, 16, 18)),
         "MPC2000XL": ("16 BIT SAMPLER|MIDI SEQUENCER", "MPC2000XL", (22, 22, 24)),
         "SP-1200": ("SAMPLING|PERCUSSION", "SP 1200", (80, 84, 92)),
         "ASR-10": ("ADVANCED SAMPLING|RECORDER", "ASR-10", (20, 21, 26))}
# a lighter plate behind the name / badges on the right of the bezel (the SP: dark slate panel, light grey strip)
PLATE = {"SP-1200": (212, 212, 206)}


def adjust(e, key, n):
    """turn the jog wheel on a field"""
    sq, tr = e.seq, e.track
    if key == "seq":
        e.queue_seq((e.cur_seq + n) % NSEQ)
    elif key == "bpm": sq.bpm = max(30.0, min(300.0, round(sq.bpm + 0.1 * n, 1)))
    elif key == "num": e.set_timesig(max(1, min(16, sq.num + n)), sq.den)
    elif key == "den":
        dens = [2, 4, 8, 16]; e.set_timesig(sq.num, dens[max(0, min(3, dens.index(sq.den) + (1 if n > 0 else -1)))])
    elif key == "bars": e.set_bars(sq.bars + n)
    elif key == "loop": sq.loop = not sq.loop
    elif key == "trk": e.cur_track = (e.cur_track + n) % 16
    elif key == "on": tr.mute = not tr.mute
    elif key == "chn": tr.midi_ch = max(0, min(16, tr.midi_ch + n))
    elif key == "vel": tr.vol = max(0.0, min(1.0, round(tr.vol + 0.01 * n, 2)))
    elif key == "pgm": tr.prog = (tr.prog + n) % NPROG
    elif key == "timing": e.qgrid = max(0, min(len(QUANT) - 1, e.qgrid + (1 if n > 0 else -1)))
    elif key == "count": e.count_in = (e.count_in + (1 if n > 0 else -1)) % 3
    elif key == "ac":
        from engine import SP_CORRECT
        e.sp_ac = max(0, min(len(SP_CORRECT) - 1, e.sp_ac + (1 if n > 0 else -1))); e.say("Autocorrect:" + SP_CORRECT[e.sp_ac][0])
    elif key == "asrq":
        from engine import ASR_Q
        e.asr_q = max(0, min(len(ASR_Q) - 1, e.asr_q + (1 if n > 0 else -1)))
    elif key == "rate": e.asr_rate = 1 - e.asr_rate
    elif key == "swing":
        from engine import SP_SWINGS, Engine
        k = max(0, min(5, Engine.sp_swing_k(sq.swing) + (1 if n > 0 else -1))); sq.swing = SP_SWINGS[k] / 100.0
        e.say(f"Swing: {SP_SWINGS[k]}%")


def soft_labels(e, machine):
    """F1-F4 under the screen, as the machine's own soft keys (None = keep Monolith's)"""
    tr = e.track
    if machine in LINN: return ["TK ON/OFF", "SOLO=" + ("ON" if tr.solo else "OFF"), "TRACK -", "TRACK +"]
    if machine == "MPC2000XL": return ["TrMUTE", "SOLO", "Tr -", "Tr +"]
    return None


def soft(e, machine, i):
    tr = e.track
    if i == 0: tr.mute = not tr.mute; e.say(f"track {tr.n + 1:02d} {'off' if tr.mute else 'on'}")
    elif i == 1: tr.solo = not tr.solo; e.say(f"track {tr.n + 1:02d} solo {'on' if tr.solo else 'off'}")
    elif i == 2: e.cur_track = (e.cur_track - 1) % 16
    elif i == 3: e.cur_track = (e.cur_track + 1) % 16
