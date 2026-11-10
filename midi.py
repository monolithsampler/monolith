"""
midi.py - USB MIDI in and out for Monolith, with no extra packages: it reads and writes the ALSA raw MIDI
devices (/dev/snd/midiC*D*) directly, so any class-compliant keyboard (Akai MPK249, MPK mini, Arturia, ...) works.

What comes in:
  * pads (notes on the pad channel, default channel 10, notes 36-99 = banks A-D)  -> the sampler's pads
  * keys (notes on any other channel)                                             -> played chromatically, recorded to a KEYS track
  * knobs / buttons you have MIDI-learned (MIDI page: SHIFT + MAIN)               -> Q1-Q4, PLAY, STOP, REC, OVERDUB, PLAY START,
                                                                                    PAD MODE, Q-LINK MODE, ...
  * MMC transport (what an MPK249 sends from its transport buttons by default) and MIDI Start / Stop
What goes out: the notes of every track that has a MIDI channel set (MIDI page), to all connected devices.
Devices can be plugged in and out while the sampler runs.
"""
import glob, heapq, json, os, select, threading, time
PPQ_ = 96                                                   # the engine's ticks per beat

LEARN_TARGETS = ["PADS", "Q1", "Q2", "Q3", "Q4", "JOG", "PLAY", "STOP", "REC", "OVERDUB", "PLAY START",
                 "F1", "F2", "F3", "F4", "SHIFT", "ERASE", "UNDO", "NOTE REPEAT", "TAP", "BANK", "LOAD", "PAD MODE", "Q-LINK MODE"]
PER_COL = 12                                                # MIDI page: learn rows per column
BUTTONS = {"PLAY": "PLAY", "STOP": "STOP", "REC": "REC", "OVERDUB": "OVERDUB", "PLAY START": "PLAYSTART", "F1": "F1", "F2": "F2",
           "F3": "F3", "F4": "F4", "SHIFT": "SHIFT", "ERASE": "ERASE", "UNDO": "UNDO", "NOTE REPEAT": "REPEAT", "TAP": "TAP", "BANK": "BANK", "LOAD": "LOAD",
           "PAD MODE": "PADMODE", "Q-LINK MODE": "QLINKMODE"}                # BANK and these two are not hardware keys: see Controls.midi_button


class Parser:
    """MIDI byte stream -> messages (tuples of ints). Running status, realtime bytes and SysEx are handled."""
    def __init__(self):
        self.status, self.data, self.sysex = None, [], None

    def feed(self, data):
        out = []
        for b in data:
            if b >= 0xF8:                                 # realtime: may appear anywhere, even inside other messages
                out.append((b,)); continue
            if b == 0xF0:
                self.sysex = [b]; continue
            if self.sysex is not None:
                if b == 0xF7:
                    out.append(tuple(self.sysex + [b])); self.sysex = None
                elif b < 0x80: self.sysex.append(b)
                else: self.sysex = None                     # broken SysEx: drop it, handle this byte normally
                if self.sysex is not None or b == 0xF7: continue
            if b & 0x80:
                self.status, self.data = b, []
                if b >= 0xF4: out.append((b,)); self.status = None
                continue
            if self.status is None: continue
            self.data.append(b)
            need = 1 if (self.status & 0xF0) in (0xC0, 0xD0) or self.status in (0xF1, 0xF3) else 2
            if len(self.data) == need:
                out.append((self.status,) + tuple(self.data))
                self.data = []
                if self.status >= 0xF0: self.status = None    # system common messages do not run
        return out


class MidiMap:
    """Which MIDI controls do what. Saved next to the project as midi.json."""
    def __init__(self, path=None):
        self.path = path
        self.pad_ch, self.pad_base = 10, 36                 # pads: channel 1-16, first note (bank A pad 1)
        self.key_ch = 0                                     # 0 = every channel except the pad channel
        self.clock = "OFF"                                  # MIDI clock: OFF | SEND | FOLLOW
        self.bend_range = 2                                 # pitch bend range, semitones
        self.learned = {}                                   # target -> [kind ('cc' | 'note'), channel 1-16, number]
        self.pad_list = []                                  # pads learned one by one: [channel, note] for pad 1, 2, ... (any layout)
        self._pad_lk = None
        self.track_out = {}                                 # kept on the tracks themselves; not used here
        self.load()

    def load(self):
        if not self.path or not os.path.exists(self.path): return
        try:
            d = json.load(open(self.path))
            self.pad_ch, self.pad_base, self.key_ch = int(d.get("pad_ch", 10)), int(d.get("pad_base", 36)), int(d.get("key_ch", 0))
            self.clock = d.get("clock", "OFF") if d.get("clock") in ("OFF", "SEND", "FOLLOW") else "OFF"
            self.bend_range = int(d.get("bend_range", 2))
            self.learned = {k: list(v) for k, v in d.get("learned", {}).items() if k in LEARN_TARGETS}
            self.pad_list = [list(map(int, v)) for v in d.get("pad_list", [])][:64]; self._pad_lk = None
        except Exception as ex:
            print("midi.json could not be read:", ex)

    def save(self):
        if not self.path: return
        try: json.dump({"pad_ch": self.pad_ch, "pad_base": self.pad_base, "key_ch": self.key_ch, "learned": self.learned,
                        "clock": self.clock, "bend_range": self.bend_range, "pad_list": self.pad_list}, open(self.path, "w"), indent=1)
        except OSError as ex: print("midi.json could not be written:", ex)

    def pad_of(self, ch, note):
        """(bank 0-3, pad 1-16) for a note learned pad by pad, or None. A controller whose pad banks shift every note by 16
        (most do) reaches banks B-D with only bank A learned."""
        if not self.pad_list: return None
        if self._pad_lk is None: self._pad_lk = {(c, n): i for i, (c, n) in enumerate(self.pad_list)}
        i = self._pad_lk.get((ch, note))
        if i is not None: return i // 16, i % 16 + 1
        if len(self.pad_list) <= 16:
            for k in (1, 2, 3):
                i = self._pad_lk.get((ch, note - 16 * k))
                if i is not None: return k, i + 1
        return None

    def set_pads(self, pads):
        self.pad_list = [list(p) for p in pads][:64]; self._pad_lk = None
        if pads: self.pad_ch, self.pad_base = pads[0][0], pads[0][1]

    def target_of(self, kind, ch, num):
        for t, (k, c, n) in self.learned.items():
            if k == kind and c == ch and n == num: return t
        return None


def dispatch(ctl, msg, mp):
    """One MIDI message -> the Controls object (also used by the tests)."""
    st = msg[0]
    e = ctl.e
    if st == 0xF8:                                          # clock: only listened to in FOLLOW
        if e.clock_mode == "FOLLOW": e.ext_clock(time.time())
        return
    if e.clock_mode == "SEND" and st in (0xFA, 0xFB, 0xFC, 0xF2): return     # we are the master: ignore start / stop echoes
    if st == 0xFA: ctl.button_name("PLAY START"); return
    if st == 0xFB: ctl.button_name("PLAY"); return
    if st == 0xFC:
        if e.playing: ctl.button_name("STOP")
        return
    if st == 0xF2 and len(msg) == 3:                        # song position (16ths): where the master will continue from
        if not e.playing: e.locate(((msg[2] << 7) | msg[1]) * (PPQ_ // 4))
        return
    if st == 0xF0:                                          # MMC: F0 7F <dev> 06 <cmd> F7
        if len(msg) >= 6 and msg[1] == 0x7F and msg[3] == 0x06:
            cmd = msg[4]
            name = {0x01: "STOP", 0x02: "PLAY", 0x03: "PLAY", 0x06: "REC", 0x04: None, 0x05: None, 0x09: "STOP"}.get(cmd)
            if name: ctl.button_name(name)
            elif cmd == 0x05: ctl.e.locate(0)               # rewind
        return
    if st < 0x80 or st >= 0xF0: return
    kind, ch = st & 0xF0, (st & 0x0F) + 1
    ctl.midi_seen = time.time()
    if kind == 0x90 and msg[2] > 0:
        if ctl.midi_learn:
            ctl.learn_from("note", ch, msg[1]); return
        t = mp.target_of("note", ch, msg[1])
        if t in BUTTONS: ctl.midi_button(BUTTONS[t], True); return
        p = mp.pad_of(ch, msg[1])
        if p: ctl.midi_pad(p[0], p[1], msg[2]); return
        if mp.pad_list: pass                                # pads learned one by one: other notes are keys
        elif ch == mp.pad_ch and mp.pad_base <= msg[1] < mp.pad_base + 64:
            idx = msg[1] - mp.pad_base
            ctl.midi_pad(idx // 16, idx % 16 + 1, msg[2]); return
        if mp.key_ch in (0, ch) and ch != mp.pad_ch:
            ctl.midi_key(msg[1], msg[2])
    elif kind == 0x80 or (kind == 0x90 and msg[2] == 0):
        t = mp.target_of("note", ch, msg[1])
        if t in BUTTONS: ctl.midi_button(BUTTONS[t], False); return
        if ch != mp.pad_ch and mp.key_ch in (0, ch):
            ctl.midi_key_off(msg[1])
    elif kind == 0xE0:                                      # pitch bend (from the keys, not the pads)
        if ch != mp.pad_ch: e.pitch_bend((((msg[2] << 7) | msg[1]) - 8192) / 8192.0)
    elif kind == 0xD0:                                      # channel aftertouch: like the mod wheel
        if ch != mp.pad_ch: e.mod_wheel(msg[1] / 127.0, 128)
    elif kind == 0xB0:
        if ctl.midi_learn:
            if msg[2] > 0: ctl.learn_from("cc", ch, msg[1])
            return
        t = mp.target_of("cc", ch, msg[1])
        if t is None:
            if msg[1] == 1 and ch != mp.pad_ch: e.mod_wheel(msg[2] / 127.0, 1)        # mod wheel (unless learned for something)
            return
        if t in ("Q1", "Q2", "Q3", "Q4"): ctl.knob(int(t[1]) - 1, msg[2])
        elif t == "JOG":                                    # an ordinary knob: each movement is a jog step
            prev = mp.__dict__.setdefault("_jog_prev", None); mp._jog_prev = msg[2]
            if prev is not None and msg[2] != prev: ctl.jog(1 if msg[2] > prev else -1)
        elif t in BUTTONS: ctl.midi_button(BUTTONS[t], msg[2] >= 64)     # >= 64 pressed, < 64 released


class MidiIO:
    """Finds the MIDI devices, reads them in a thread, and sends scheduled output (note-offs later) in another."""
    def __init__(self, ctl, mp, pattern="/dev/snd/midiC*D*"):
        self.ctl, self.mp, self.pattern = ctl, mp, pattern
        self.fds, self.parsers, self.names = {}, {}, {}
        self.q, self.qlock, self.qcv = [], threading.Lock(), threading.Condition()
        self.seq = 0
        ctl.e.midi_out = self.send
        ctl.midi_io = self

    @staticmethod
    def device_name(path):
        try:
            card = os.path.basename(path)[5:].split("D")[0]
            return open(f"/proc/asound/card{card}/id").read().strip() + " " + os.path.basename(path)[5:]
        except Exception: return os.path.basename(path)

    def rescan(self):
        found = set(glob.glob(self.pattern))
        for p in list(self.fds):
            if p not in found: self._close(p)
        for p in sorted(found - set(self.fds)):
            for flags in (os.O_RDWR, os.O_RDONLY):
                try:
                    self.fds[p] = os.open(p, flags | os.O_NONBLOCK)
                    self.parsers[p], self.names[p] = Parser(), self.device_name(p)
                    print("MIDI device:", self.names[p]); break
                except OSError: continue

    def _close(self, p):
        try: os.close(self.fds.pop(p))
        except Exception: self.fds.pop(p, None)
        self.parsers.pop(p, None); self.names.pop(p, None)

    def read_loop(self):
        last_scan = 0.0
        while True:
            if time.time() - last_scan > 2.0: self.rescan(); last_scan = time.time()
            if not self.fds: time.sleep(0.5); continue
            byfd = {fd: p for p, fd in self.fds.items()}
            try: r, _, _ = select.select(list(byfd), [], [], 0.5)
            except (OSError, ValueError): self.rescan(); continue
            for fd in r:
                p = byfd[fd]
                try: data = os.read(fd, 256)
                except BlockingIOError: continue
                except OSError: self._close(p); continue
                for msg in self.parsers[p].feed(data):
                    try: dispatch(self.ctl, msg, self.mp)
                    except Exception as ex: print("MIDI message error:", ex)

    def send(self, data, delay=0.0):
        with self.qcv:
            self.seq += 1
            heapq.heappush(self.q, (time.time() + max(0.0, delay), self.seq, bytes(data)))
            self.qcv.notify()

    def send_loop(self):
        while True:
            with self.qcv:
                while not self.q: self.qcv.wait()
                t, _, data = self.q[0]
                now = time.time()
                if t > now: self.qcv.wait(min(0.05, t - now)); continue
                heapq.heappop(self.q)
            for p, fd in list(self.fds.items()):
                try: os.write(fd, data)
                except OSError: pass

    def start(self):
        threading.Thread(target=self.read_loop, daemon=True).start()
        threading.Thread(target=self.send_loop, daemon=True).start()
        return self
