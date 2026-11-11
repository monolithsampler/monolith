import re
"""
engine.py - audio engine + sequencer for Monolith (v7).

Data model (MPC style)
  Source    a sample file in memory. NEVER modified after loading/recording: every edit is stored as parameters.
  Pad       one drum pad: references a Source region (start/end) plus reverse / normalise / fades / tune / level / pan / mode / choke / fx / output.
  Program   64 pads = 4 banks (A-D) x 16. Tracks play programs.
  Track     a list of note events (tick, pad, velocity, length), a program, mixer settings.
            A KEYS track (kind "keys") stores (tick, MIDI note, velocity, length) instead and plays one pad of its
            program chromatically (note 60 = the sample's own pitch): that is what an external keyboard records into.
            A PLUGIN track plays a VST3 instrument (synth) with the same note events; a MIDI track only sends its
            notes to external gear (MIDI out). Any track can also send its notes out (midi_ch 1-16).
  Sequence  16 tracks, length in bars, time signature, tempo, swing, loop.  96 ticks per quarter note.
  Song      a list of (sequence, repeats) steps.
Non-destructive chop: markers live on the Source; chops are pads that point at a region of it and follow marker moves.
"""
import bisect, json, os, threading, time, wave
import numpy as np
import fx as fxlib
import warp as warplib
import dspfast
import asrvoice, mpcvoice
import sp1200hw as SPH
import mpchw
import console
from collections import OrderedDict

OUT_SR = 44100
PPQ = 96
NTRACK, NPROG, NSEQ = 16, 8, 16
OUT_NAMES = ["MIX", "1/2", "3/4", "5/6", "7/8", "1", "2", "3", "4", "5", "6", "7", "8"]
LOFI_SR = 26040                 # SP-1200 sample rate
RATIO = LOFI_SR / OUT_SR
NVOICES = 16
FADE_FR = int(0.008 * OUT_SR)   # 8 ms fade when a voice is choked or gated
EDGE_IN, EDGE_OUT = int(0.0007 * OUT_SR), int(0.003 * OUT_SR)   # every region: 0.7 ms in, 3 ms out, so chops never click
STEAL_FR = int(0.004 * OUT_SR)  # a stolen voice fades over 4 ms instead of stopping dead
NOTE_KINDS = ("keys", "plugin", "midi")            # tracks whose events are notes (piano roll), not pads
KIND_NAMES = {"drum": "DRUM", "keys": "KEYGROUP", "plugin": "PLUGIN", "midi": "MIDI"}
MAX_BARS = 32                                       # longest sequence
PAD_MODES = ("NORMAL", "16 LEVELS", "PERFORM", "TRACK MUTE", "NEXT SEQ")   # what the 16 pads do (PADS page)
SCALES = [("Chromatic", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)), ("Major", (0, 2, 4, 5, 7, 9, 11)),
          ("Minor", (0, 2, 3, 5, 7, 8, 10)), ("Harm. minor", (0, 2, 3, 5, 7, 8, 11)), ("Dorian", (0, 2, 3, 5, 7, 9, 10)),
          ("Mixolydian", (0, 2, 4, 5, 7, 9, 10)), ("Pent. major", (0, 2, 4, 7, 9)), ("Pent. minor", (0, 3, 5, 7, 10)),
          ("Blues", (0, 3, 5, 6, 7, 10))]
CHORDS = ("SINGLE", "TRIAD", "7TH")
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
def note_name(n): return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"          # 60 = C4 (as the piano roll shows it)
def fmt_st(v):
    """a pad tune for display: whole semitones as +3 st, imported MPC tunings (0.1 st steps) as +2.5 st"""
    v = float(v)
    return f"{int(v):+d} st" if v.is_integer() else f"{v:+.1f} st"
TIMINGS = ("MODERN", "MPC60")   # MPC60 = the Linn timing of the MPC60 / MPC3000 (see EMULATION_NOTES.md)
MACHINES = ("MODERN", "MPC60", "MPC3000", "MPC2000XL", "SP-1200", "ASR-10")   # machine emulations (machines.py draws their screens)
QUANT = [("OFF", 0), ("1/4", 96), ("1/8", 48), ("1/8T", 32), ("1/16", 24), ("1/16T", 16), ("1/32", 12)]
BANKS = "ABCD"
MODES = ("ONE", "HOLD")
VERSION = 2


# ---------------------------------------------------------------- audio file helpers
def read_wav_pcm(path):
    """(frames x channels float32, rate) from a RIFF WAV without extra libraries: 8/16/24/32-bit PCM and 32/64-bit
    float, plain or WAVE_FORMAT_EXTENSIBLE (MPC 2.x saves 24-bit WAVs with extra chunks)"""
    import struct
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF": raise RuntimeError("not a WAV file")
        f.read(4)
        if f.read(4) != b"WAVE": raise RuntimeError("not a WAV file")
        fmt = data = None
        while True:
            hd = f.read(8)
            if len(hd) < 8: break
            cid, n = hd[:4], struct.unpack("<I", hd[4:])[0]
            if cid == b"fmt ": fmt = f.read(n)
            elif cid == b"data": data = f.read(n)
            else: f.seek(n, 1)
            if n & 1: f.seek(1, 1)
            if fmt is not None and data is not None: break
    if fmt is None or data is None: raise RuntimeError("WAV file without audio")
    tag, ch, sr = struct.unpack("<HHI", fmt[:8]); bits = struct.unpack("<H", fmt[14:16])[0]
    if tag == 0xFFFE and len(fmt) >= 26: tag = struct.unpack("<H", fmt[24:26])[0]
    nb = bits // 8
    data = data[:len(data) // (nb * ch) * nb * ch]
    if tag == 3: x = np.frombuffer(data, dtype="<f4" if nb == 4 else "<f8").astype(np.float32)
    elif nb == 1: x = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif nb == 2: x = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    elif nb == 3:
        b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8).astype(np.float32) / 8388608.0
    elif nb == 4: x = np.frombuffer(data, dtype="<i4").astype(np.float32) / 2147483648.0
    else: raise RuntimeError(f"{bits}-bit WAV files are not supported")
    return x.reshape(-1, ch), sr


def load_wav(path):
    try:
        import soundfile as sf
        x, sr = sf.read(path, dtype="float32", always_2d=True)
    except ImportError:
        x, sr = read_wav_pcm(path)
    return x.mean(axis=1).astype(np.float32), sr


def read_audio(path):
    """(mono samples, rate, name) from a WAV / AIFF / FLAC file or an MPC2000/2000XL .SND"""
    if path.lower().endswith(".snd"):
        import mpc_import
        sd = mpc_import.read_snd(path)
        x = sd["data"][min(sd["start"], len(sd["data"]) - 2):max(sd["end"], 2)]
        return x, sd["rate"], sd["name"]
    x, sr = load_wav(path)
    return x, sr, os.path.splitext(os.path.basename(path))[0]


def save_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(OUT_SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def save_wav_float(path, L, R):
    """stereo 32-bit float WAV (no clipping; every DAW reads it) - used for TRACK OUT"""
    import struct
    data = np.empty(len(L) * 2, dtype="<f4"); data[0::2], data[1::2] = L, R
    raw = data.tobytes()
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + 26 + 12 + 8 + len(raw)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHHH", 18, 3, 2, OUT_SR, OUT_SR * 8, 8, 32, 0))
        f.write(b"fact" + struct.pack("<II", 4, len(L)))
        f.write(b"data" + struct.pack("<I", len(raw)) + raw)


def resample(x, sr_in, sr_out):
    if sr_in == sr_out:
        return x.astype(np.float32)
    n = int(len(x) * sr_out / sr_in)
    return np.interp(np.arange(n) * sr_in / sr_out, np.arange(len(x)), x).astype(np.float32)


def make_lofi(x):
    """SP-1200 flavour: 26.04 kHz + 12-bit."""
    y = resample(x, OUT_SR, LOFI_SR)
    y = np.convolve(y, [0.25, 0.5, 0.25], mode="same")
    return (np.round(y * 2047.0) / 2047.0).astype(np.float32)


# ---------- SP-1200 model (see EMULATION_NOTES.md: firmware 1.04 + published hardware details) ----------
SP_SR = 20e6 / 768                # 26,041.67 Hz: the SP-1200's sample clock (20 MHz crystal / 768)
SP_RATIO = SP_SR / OUT_SR         # SP sample frames per output frame
SP_TICK = 0.0012288 * OUT_SR      # its decay steps once per 1.2288 ms housekeeping tick


def sp_decay_ms(v):
    """the SP-1200's decay setting 0-31 as the pad's decay in ms (31 = the sound plays out)"""
    return 0 if v >= 31 else int(40 * 1.16 ** v)


def sp_decay_of(ms):
    return 31 if not ms else max(0, min(30, int(round(np.log(max(40, ms) / 40.0) / np.log(1.16)))))
SP_TUNE = (-16, 12)               # the firmware's pitch table spans -16 .. +12 semitones, in whole semitones
SP_SWINGS = (50, 54, 58, 63, 67, 71)   # its six swing settings: the off-beat of a pair late by 0-5 24ths of the pair
SP_CORRECT = [("Off", 0), ("1/4", 96), ("1/4t", 64), ("1/8", 48), ("1/8t", 32), ("1/16", 24), ("1/16t", 16), ("1/32", 12),
              ("1/32t", 8), ("HiRes", 4)]   # its auto-correct values (firmware: 24 per quarter; here x4 = our 96 ticks)
# output filters, from the service manual's schematic (sp1200hw.py): 1-2 an SSM2044 4-pole low-pass that every hit opens
# ~6 octaves and that closes back to ~1 kHz (tau 0.10 s); 3-6 fixed 5th-order low-passes at ~7.9 / 9.6 / 11.6 / 13.1 kHz;
# 7-8 none. The voice itself (stepping, level DAC, hold, filters, output) runs in sp1200hw / dsp/sp1200.c.
SP_DYN_REST, SP_DYN_OCT, SP_DYN_TAU = SPH.DYN_REST, SPH.DYN_OCT, SPH.DYN_TAU
SP_FIXED = {ch: SPH.cutoff_3db(lambda f, c=ch: SPH.out_filter(f, c)) for ch in SPH.OUT_PARTS}
# "sampled at" a faster record speed, then tuned back down on the pad (the classic SP memory trick): the sound is held
# shorter, so playback repeats samples and the SP's grit gets stronger. The SP tunes in whole semitones, so each speed is the
# nearest whole number of semitones up (45 rpm = 5 st, 78 rpm = 15 st) and the pad plays back at the original pitch.
SP_RPMS = {33: 0, 45: 5, 78: 15}
# ---------- Ensoniq ASR-10 (OS 1.5B ROM + its ES5506 sound chip; see EMULATION_NOTES.md) ----------
ASR_Q = [("1/4", 96), ("1/6", 64), ("1/8", 48), ("1/12", 32), ("1/16", 24), ("1/24", 16), ("1/32", 12), ("1/48", 8),
         ("1/64", 6), ("1/96", 4)]       # its QUANTIZE TRACK values (the ROM's table, in its 96-per-quarter clocks)
ASR_RATES = (15238090.0 / 512, 44100.0)  # system rate: 29,761.9 Hz with 31 voices, or 44.1 kHz with 23
ASR_FILTERS = ("3LP/1LP", "2LP/2HP")     # how a pad's LP / HP (and BP) map onto the chip's four filter poles
SP_RING_K = 1.5                   # RING at 100%: how loud the stepping error comes through (a model, see EMULATION_NOTES.md)


def sp_step(semis):
    """playback step through the sample for a tuning: round(128 x 2^(n/12)) / 128 reproduces the firmware's table exactly.
    semis = the pad's tune minus its SP_RPMS speed-up (so 78 rpm leaves room for only one more semitone down)"""
    n = max(SP_TUNE[0], min(SP_TUNE[1], int(round(semis))))
    return round(128.0 * 2.0 ** (n / 12.0)) / 128.0


def make_sp(x, speed=1.0):
    """a sound as the SP-1200 holds it: through its input filter (the 7th-order elliptic low-pass on the schematic, -3 dB
    at ~13.2 kHz: a little above the 13.02 kHz Nyquist, so a little aliasing gets in, as on the real one), sampled at
    26,041.67 Hz, truncated to 12 bits by its successive-approximation converter.
    speed > 1: sampled from a faster record (45 / 78 rpm): the sound arrives higher, so the input filter takes away more
    of it, and it is held in fewer samples"""
    x = np.asarray(x, np.float32)
    fir = SPH.input_fir(OUT_SR, speed)
    h = len(fir) // 2
    y = np.convolve(x, fir)[h:h + len(x)]
    n = int(len(y) * SP_SR / OUT_SR / speed)
    y = SPH.sample_at(y, OUT_SR, np.arange(n) * (OUT_SR * speed / SP_SR))       # the converter samples the filtered signal
    return (np.floor(np.clip(y, -1.0, 0.99951) * 2048.0) / 2048.0).astype(np.float32)


_ASR_AA = {}


def make_asr(x, rate):
    """a sound as the ASR-10 holds it: low-passed below half its system rate, at that rate, in 16 bits (plus one spare
    sample for the interpolation)"""
    if rate not in _ASR_AA:
        k = np.arange(-48, 49); fc = 0.45 * rate / OUT_SR
        h = 2 * fc * np.sinc(2 * fc * k) * np.blackman(len(k)); _ASR_AA[rate] = (h / h.sum()).astype(np.float32)
    aa = _ASR_AA[rate]
    x = np.asarray(x, np.float32)
    y = np.convolve(x, aa, mode="same") if (rate < OUT_SR and len(x) > len(aa)) else x
    n = max(2, int(len(y) * rate / OUT_SR))
    y = np.interp(np.arange(n) * (OUT_SR / rate), np.arange(len(y)), y)
    y = np.round(np.clip(y, -1.0, 32767 / 32768.0) * 32768.0) / 32768.0
    return np.append(y, 0.0).astype(np.float32)


def make_click(freq, ms=22, amp=0.35):
    n = int(OUT_SR * ms / 1000)
    t = np.arange(n) / OUT_SR
    return (np.sin(2 * np.pi * freq * t) * np.exp(-t * 180) * amp).astype(np.float32)


CLICK_HI, CLICK_LO = make_click(1900), make_click(1250, amp=0.25)


# ---------------------------------------------------------------- data classes
class Source:
    """A sample. `raw` is never changed after creation. Chop markers are stored here (sample positions)."""
    def __init__(self, sid, name, raw):
        self.id, self.name = sid, name
        self.raw = np.asarray(raw, dtype=np.float32)
        self.chops = []
        self.slices = None              # explicit [start, end] per slice once a start / end is edited on its own (else: between markers)
        self.dirty = False              # True for new recordings that still need writing to disk
        self._env = None
        self.native = None              # (ASR rate index, int16 at that rate): a transwave's own copy (ASR-10 machine)

    @property
    def length(self): return len(self.raw)

    def regions(self):
        if self.slices: return [(int(a), int(b)) for a, b in self.slices]
        edges = [0] + list(self.chops) + [self.length]
        return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

    def envelope(self, width, a=0, b=None):
        """(mins, maxs) per pixel column for the window a..b of the source."""
        b = self.length if b is None else b
        key = (width, a, b)
        if self._env is None or self._env[0] != key:
            seg = self.raw[a:b]
            if len(seg) < width * 2:
                seg = np.interp(np.linspace(0, max(len(seg) - 1, 1), width * 2), np.arange(max(len(seg), 1)),
                                seg if len(seg) else np.zeros(1, np.float32))
            n = len(seg) // width * width
            m = seg[:n].reshape(width, -1)
            self._env = (key, m.min(axis=1), m.max(axis=1))
        return self._env[1], self._env[2]


class Pad:
    def __init__(self, idx):
        self.idx = idx
        self.src, self.start, self.end = None, 0, 0
        self.reverse = self.norm = False
        self.fade_in = self.fade_out = 0            # ms
        self.gain_db, self.tune, self.vol, self.pan = 0.0, 0, 0.8, 0.0
        self.mute = self.solo = False
        self.lofi_on = True
        self.rpm = 33                               # SP-1200 mode: the speed it was "sampled at" (SP_RPMS), tuned back down
        self.sp_ch = 0                              # SP-1200 output channel 1-8 (its filter); 0 = AUTO (pad n -> channel n)
        self.mode = "ONE"                           # ONE = plays to the end, HOLD = stops when the note ends
        self.choke = 0                              # voices with the same non-zero group cut each other off (within one program)
        self.owner = None                           # the Program this pad belongs to (set by Program)
        self.fx, self.fx_bypass = None, False
        self.out = 0
        self.link = None                            # (source id, chop index): follows chop marker edits
        self.warp, self.warp_bpm = False, 0.0       # WARP: follow the sequence tempo; warp_bpm = the tempo of the region as recorded
        self.fine = 0                               # fine tune, cents (-99..99), on top of tune (semitones)
        self.stretch = 100                          # WARP: length in % of the region at its BPM (200 = twice as long, half-time)
        self.gen = 0                                # bumped on every edit: sounding WARP notes move onto the new render
        self.vel_mpc = None                         # None: level = (velocity/127)^1.5. 0-100: MPC2000XL velocity -> level (imported pads)
        # amp envelope and filter (all off by default: the pad plays as the sample is)
        self.attack, self.decay = 0, 0              # ms; decay 0 = no decay (the sound plays out)
        self.flt = "OFF"                            # OFF | LP | HP | BP
        self.cutoff, self.res = 1.0, 0.0            # 0-1 (30 Hz .. 20 kHz, log), resonance 0-1
        self.f_env, self.f_dec = 0.0, 300           # filter envelope amount -1..1 (of the cutoff range), its decay in ms
        self.f_vel = 0.0                            # velocity -> cutoff, 0-1 (soft hits darker)
        # ASR-10 wavesample (machine = ASR-10): loop, sample modulation (TRANSWAV...), its LFO and ENV1 (asrvoice.py)
        self.a_loop = 0                             # asrvoice.LOOP_MODES: 0 = FORWARD-NO LOOP
        self.a_ls, self.a_le = 0.0, 0.0             # loop start / end, seconds from the pad's start (end 0 = the pad's end)
        self.a_mod, self.a_src, self.a_amt, self.a_range = 0, "ENV1", 0, 14   # MOD type, MOD SRC, MOD AMT, RANGE (128)
        self.a_lfo_wave, self.a_lfo_rate, self.a_lfo_depth, self.a_lfo_delay = 0, 40, 127, 0
        self.a_env1 = [0, 2000, 1.0, 200]           # ENV1: attack ms, decay ms, sustain 0-1, release ms
        self.a_fmode, self.a_f1, self.a_f2 = 3, 150, 150    # the chip's filter: mode (asrvoice.FILTER_MODES), CUTOFF F1 / F2 0-150
        self.a_kbd1, self.a_kbd2 = 0, 0             # KBD AMT F1 / F2 (-127..127): cutoff follows the key (127 = the pitch)
        self.a_bus = 0                              # the ASR effect bus it feeds: FX1, FX2, DRY (asrvoice.BUSES)
        self.a_amp_t = [0, 0, 0, 0, 20]             # ASR-10 amp envelope: ATTACK, DECAY 1-3, RELEASE (ms)
        self.a_amp_l = [0, 99, 99, 99, 99]          # ... INITIAL, PEAK, BREAK 1, BREAK 2, SUSTAIN (0-99, hard velocity)
        self.a_softvel, self.a_vcurve, self.a_emode = 0, 1, 0   # SOFT VEL levels (% of hard), VEL CURVE, ENV MODE
        self.m_dmode = 1                            # MPC3000 / 2000XL decay mode: 0 END, 1 START (mpcvoice.DCY_MODES)
        self.m_vatk, self.m_vstart, self.m_vpitch = 0, 0, 0     # MPC VEL>ATTACK (ms), VEL>START (ms; soft = later), VELO>PITCH (ct)
        self.f_atk = 0                              # filter envelope attack (ms; MPC2000XL)
        self.meter = 0.0
        self._key = self._val = None
        self._pkey = self._pval = None
        self._unflat = None                         # FLATTEN: what the pad was before (one step of undo)

    @property
    def empty(self): return self.src is None or self.end - self.start < 2
    @property
    def pitch(self): return self.tune + self.fine / 100.0     # semitones, with the fine tune
    @property
    def length(self): return 0 if self.src is None else self.end - self.start

    def assign(self, src, start=None, end=None):
        self.src = src
        self.start = 0 if start is None else int(start)
        self.end = src.length if end is None else int(end)
        self.link = None

    def pre_key(self):
        return (id(self.src), self.start, self.end, self.reverse, self.norm, self.fade_in, self.fade_out)

    def pre(self, edges=True):
        """the region with fades / reverse / normalise applied, at full rate, before lo-fi (WARP stretches this).
        edges=False: without the de-click at its ends (an ASR-10 loop or transwave plays its edges as they are)"""
        key = self.pre_key() + (edges,)
        if key == self._pkey: return self._pval
        x = self.src.raw[self.start:self.end].copy()
        n = len(x)
        if self.fade_in:
            k = min(int(self.fade_in * OUT_SR / 1000), n // 2)
            if k > 1: x[:k] *= np.linspace(0, 1, k, dtype=np.float32)
        if self.fade_out:
            k = min(int(self.fade_out * OUT_SR / 1000), n // 2)
            if k > 1: x[n - k:] *= np.linspace(1, 0, k, dtype=np.float32)
        if self.reverse: x = x[::-1].copy()
        if edges and n > 4 * (EDGE_IN + EDGE_OUT):           # de-click the edges (more than any fade set above leaves alone)
            x[:EDGE_IN] *= np.linspace(0, 1, EDGE_IN, endpoint=False, dtype=np.float32)
            x[n - EDGE_OUT:] *= np.linspace(1, 0, EDGE_OUT, dtype=np.float32)
        if self.norm:
            pk = float(np.abs(x).max()) if n else 0.0
            if pk > 1e-4: x = x * (0.95 / pk)
        self._pkey, self._pval = key, x
        return x

    def build(self):
        """Processed audio for playback: (array with one spare sample, rate scale). Cached; source is never touched."""
        key = self.pre_key() + (self.lofi_on,)
        if key == self._key:
            return self._val
        x = self.pre()
        n = len(x)
        sc = 1.0
        if self.lofi_on and n > 4:
            x, sc = make_lofi(x), RATIO
        self._val = (np.append(x, np.float32(0)).astype(np.float32), sc)
        self._key = key
        return self._val

    def state(self):
        return {"src": self.src.name if self.src else None, "start": self.start, "end": self.end,
                "reverse": self.reverse, "norm": self.norm, "fade_in": self.fade_in, "fade_out": self.fade_out,
                "gain_db": self.gain_db, "tune": self.tune, "vol": self.vol, "pan": self.pan, "mute": self.mute,
                "solo": self.solo, "lofi_on": self.lofi_on, "rpm": self.rpm, "mode": self.mode, "choke": self.choke, "out": self.out,
                "warp": self.warp, "warp_bpm": self.warp_bpm, "vel_mpc": self.vel_mpc, "fine": self.fine, "stretch": self.stretch, "sp_ch": self.sp_ch,
                "attack": self.attack, "decay": self.decay, "flt": self.flt, "cutoff": self.cutoff, "res": self.res,
                "f_env": self.f_env, "f_dec": self.f_dec, "f_vel": self.f_vel,
                "a_loop": self.a_loop, "a_ls": self.a_ls, "a_le": self.a_le, "a_mod": self.a_mod, "a_src": self.a_src,
                "a_amt": self.a_amt, "a_range": self.a_range, "a_lfo_wave": self.a_lfo_wave, "a_lfo_rate": self.a_lfo_rate,
                "a_lfo_depth": self.a_lfo_depth, "a_lfo_delay": self.a_lfo_delay, "a_env1": list(self.a_env1),
                "a_fmode": self.a_fmode, "a_f1": self.a_f1, "a_f2": self.a_f2, "a_kbd1": self.a_kbd1, "a_kbd2": self.a_kbd2, "a_bus": self.a_bus,
                "a_amp_t": list(self.a_amp_t), "a_amp_l": list(self.a_amp_l), "a_softvel": self.a_softvel, "a_vcurve": self.a_vcurve,
                "a_emode": self.a_emode, "m_dmode": self.m_dmode, "m_vatk": self.m_vatk, "m_vstart": self.m_vstart,
                "m_vpitch": self.m_vpitch, "f_atk": self.f_atk,
                "link": list(self.link) if self.link else None,
                "fx": self.fx.state() if self.fx else None, "fx_bypass": self.fx_bypass}


SOUNDS = ("MODERN", "MPC60", "MPC3000", "MPC2000XL", "SP-1200", "ASR-10")    # the machines whose sound is emulated


class Program:
    NFX = 4                                         # program insert slots (after the pad inserts, on everything the program plays)
    def __init__(self, n):
        self.n = n
        self.name = f"DRUM {n + 1}"
        self.pads = [Pad(i) for i in range(64)]
        for p in self.pads: p.owner = self
        self.fx, self.fx_bypass = [None] * self.NFX, [False] * self.NFX
        self.strip = console.Strip(self.name)           # its channel on the MIXER console (EQ, fader, pan, sends, output)
        self.sound = None                           # None = the machine's sound; or one of SOUNDS for this program only

    def fx_active(self):
        return [f for f, b in zip(self.fx, self.fx_bypass) if f is not None and not b]


class FxSlot:
    """one program insert slot; it has .fx / .fx_bypass like a pad, so the effect code treats both the same way"""
    def __init__(self, program, slot): self.program, self.slot = program, slot
    fx = property(lambda s: s.program.fx[s.slot], lambda s, v: s.program.fx.__setitem__(s.slot, v))
    fx_bypass = property(lambda s: s.program.fx_bypass[s.slot], lambda s, v: s.program.fx_bypass.__setitem__(s.slot, v))
    def __eq__(self, o): return isinstance(o, FxSlot) and o.program is self.program and o.slot == self.slot
    def __hash__(self): return hash((id(self.program), self.slot))


class Track:
    def __init__(self, n):
        self.n = n
        self.name = f"Track {n + 1:02d}"
        self.prog = 0
        self.mute = self.solo = False
        self.vol, self.pan = 0.8, 0.0
        self.events = []                    # sorted list of (tick, pad 0-63 | MIDI note for KEYS tracks, velocity, length in ticks)
        self.kind = "drum"                  # "drum" (pads) or "keys" (one pad played chromatically from a keyboard)
        self.key_pad = 0                    # KEYS: which pad of the program is the instrument
        self.root = 60                      # KEYS: the note that plays the sample at its own pitch (C3/C4 = 60)
        self.midi_ch = 0                    # 0 = off, 1-16: also send this track's notes to MIDI out
        self.plugin = ""                    # PLUGIN: path of the VST3 instrument
        self.plugin_state = None            # PLUGIN: saved parameters (restored when the instrument loads)
        self.auto = {}                      # automation: key -> sorted [[tick, value 0-1], ...]  (keys: AUTO_KEYS doc in auto_targets)
        self.mgroup = 0                     # MUTE page: mute group 0 = none, 1-4 = A-D (tracks in a group mute / unmute together)


class Sequence:
    def __init__(self, n):
        self.n = n
        self.name = f"Seq {n + 1:02d}"
        self.bars, self.num, self.den = 2, 4, 4
        self.bpm, self.swing, self.loop = 90.0, 0.5, True
        self.tracks = [Track(i) for i in range(NTRACK)]

    @property
    def beat_ticks(self): return PPQ * 4 // self.den
    @property
    def bar_ticks(self): return self.num * self.beat_ticks
    @property
    def length(self): return self.bars * self.bar_ticks


def auto_value(points, tick):
    """automation value at a tick: straight lines between the points, held flat before the first / after the last"""
    if not points: return None
    if tick <= points[0][0]: return points[0][1]
    if tick >= points[-1][0]: return points[-1][1]
    i = bisect.bisect_right([p[0] for p in points], tick)
    (t0, v0), (t1, v1) = points[i - 1], points[i]
    return v0 + (v1 - v0) * (tick - t0) / float(max(1, t1 - t0))


# ---------------------------------------------------------------- engine
class Engine:
    def __init__(self, folder, nout=2, nvoices=NVOICES, app_dir=None, blank=False, lock=None):
        """folder = the project folder (samples/ + project.json). app_dir = where the software lives: its own folder is the
        demo project, and saved projects go in app_dir/projects/<name>. blank = a new project starts empty, not the demo."""
        self.nout = max(2, int(nout))
        self.nv = int(nvoices)
        self.dir = folder
        self.app_dir = app_dir or folder
        self._blank = blank
        self.sample_dir = os.path.join(folder, "samples")
        self.project_file = os.path.join(folder, "project.json")
        os.makedirs(self.sample_dir, exist_ok=True)
        self.lock = lock or threading.RLock()
        self._renamed = []                          # sample files to remove at the next save (the sample was renamed)
        self._saved_sig, self._unsaved_t, self._unsaved = None, 0.0, False     # unsaved(): what was last saved / opened
        self._allpads = None
        self.sources, self.programs = [], [Program(i) for i in range(NPROG)]
        self.seqs = [Sequence(i) for i in range(NSEQ)]
        self.cur_seq, self.cur_track = 0, 0
        self.bank, self.sel = 0, 0                  # current pad bank (0-3) and pad (0-15) within it
        self.song, self.song_mode, self.song_pos, self.song_rep = [[0, 1]], False, 0, 0
        # voices
        nv = self.nv
        self.v_data, self.v_pad = [None] * nv, [None] * nv
        self.v_pos, self.v_rate, self.v_end = [0.0] * nv, [1.0] * nv, [0.0] * nv
        self.v_gl, self.v_gr = [0.0] * nv, [0.0] * nv
        self.v_delay, self.v_age, self.v_kill = [0] * nv, [0] * nv, [-1] * nv
        self.v_lofi = [False] * nv
        self.v_key = [None] * nv                    # which held key (MIDI note) a voice belongs to, for note-off
        self.v_trk = [None] * nv                    # the track that played a voice (automated level / pan follow it live)
        self.v_base = [(0.0, 0.0)] * nv             # (gain before track level, pad pan) of each voice
        self._auto_touch = {}                       # (id(track), key) -> (last written tick, wall time): recording automation
        self.v_warp = [None] * nv                   # WARP voices: [start beat, rendered bpm, wanted semitones, rendered semitones, fading]
        self.v_fin = [0] * nv                       # fade-in frames left (a WARP voice taking over from an older render)
        self.v_t = [0] * nv                         # frames each voice has played (its envelopes run on this)
        self.v_env = [None] * nv                    # (attack fr, decay tau fr, filter mode, cutoff 0-1 at the hit, res, env amount, env tau fr)
        self.v_fst = [np.zeros(2, np.float32) for _ in range(nv)]   # filter state per voice
        self.v_sp = [None] * nv                     # SP-1200 voices: (step, channel 1-8); None = the normal voice path
        self.v_spf = [0.0] * nv                     # SP-1200 voices: SP sample frames played
        self.v_sps = [None] * nv                    # SP-1200 voices: the hardware model's state (sp1200hw.new_state)
        self.v_spp = [None] * nv                    # ... and its parameters (sp1200hw.params)
        self._sp_cache = {}                         # pad -> (its region key, the region as the SP holds it)
        self.v_asr = [False] * nv                   # ASR-10 voices: interpolated at its rate, its non-resonant 4-pole filter
        self.v_afs = [[np.zeros(1, np.float32) for _ in range(4)] for _ in range(nv)]   # the four poles' states
        self._asr_cache = {}
        self.v_reg = [None] * nv                    # plain voices: (start, end, reverse, data frames per source frame) as triggered
        self.v_mos = [None] * nv                    # MPC voices: their machine's DAC + output filter (mpchw.OutStage)
        self.v_ov = [None] * nv                     # ASR-10 voices on the sound chip's model: [asrvoice.Voice, Sources, t, released]
        self.beat_clock = 0.0                       # free-running beat counter (runs when stopped too): WARP voices follow it
        self.warp_cache = OrderedDict()             # (pad id, pad state, bpm, semitones) -> (stretched data, rate scale)
        self._warp_todo, self._warp_cv, self._warp_thread = OrderedDict(), threading.Condition(), None
        self._warp_br = None
        self.bouncing, self._bounce_raw, self._bounce_thread = False, False, None   # TRACK OUT: live audio paused while bouncing
        self.bounce_status = ""
        self.held = {}                              # live keyboard notes: note -> (start tick or None, velocity)
        self.midi_out = None                        # set by midi.py: callable(bytes, delay_seconds)
        self.instruments = {}                       # id(track) -> loaded VST3 instrument (PLUGIN tracks)
        self._note_offs = []                        # [frames until due, instrument, pitch] for sequenced instrument notes
        # pad modes (PADS page)
        self.pad_mode = "NORMAL"
        self.levels_param, self.levels_pad = "VELOCITY", 0          # 16 LEVELS: VELOCITY or TUNE, of this pad (0-63)
        self.perf_scale, self.perf_root, self.perf_oct, self.perf_chord = 2, 0, 4, 0   # PERFORM: SCALES index, key, octave, CHORDS index
        self.perf_gate = 48                                         # PERFORM: how long a pad note lasts (pads send no note-off)
        self._live_offs = []                                        # [frames until due, note] for PERFORM notes
        self.next_seq = None                                        # NEXT SEQ: sequence to switch to at the end of this one
        self.counter = 0
        self.ramp = np.arange(8192, dtype=np.float64)
        # master
        self.volume, self.filt, self.drive = 0.8, 1.0, 1.0
        self.lim_g = 1.0                                     # master limiter gain (1 = not limiting)
        self.lim_on = True                                   # MIXER > MASTER > LIMIT (off: only the soft clipper)
        self.dim = False
        self.monitor = 1.0                                     # MIXER > MASTER > DIM: the outputs 20 dB down (monitoring only)
        self.lp = [0.0, 0.0]
        self.master_meter = 0.0
        self.meter_l = self.meter_r = 0.0
        self.master_fx, self.master_fx_bypass = None, False
        self.returns = [console.Strip("RTN A", 2), console.Strip("RTN B", 2)]   # the two effect returns (sends A / B feed them)
        self.master_strip = console.Strip("MASTER", 1)      # bus insert 2 (insert 1 is master_fx) and the master EQ
        self.send_master = [1.0, 1.0]                       # send masters A / B
        self.groups = [console.Strip("GROUP 1-2"), console.Strip("GROUP 3-4")]   # the two group (submix) buses
        self.analyse, self.an_buf = None, np.zeros(4096, np.float32)   # the EQ page's analyser: the strip it listens to
        self.cpu, self._over = 0.0, 0
        self.track_meter = [0.0] * NTRACK
        # transport
        self.pos = 0.0                              # playhead in ticks (negative = count-in)
        self.playing = False
        self.rec = "off"                            # off | rec (replace) | over (overdub)
        self.count_in, self.metro = 0, False
        self.qgrid, self.rec_quant = 4, False       # QUANT index, quantize while recording
        self.machine, self.tc_shift = "MODERN", 0    # machine emulation (machines.py); MPC60 "shift timing" in ticks
        self.sp_ac = 5                               # SP-1200 auto-correct: index into SP_CORRECT (5 = 1/16)
        self.asr_q, self.asr_rate = 4, 0             # ASR-10: QUANTIZE TRACK value (ASR_Q, 4 = 1/16), system rate (ASR_RATES)
        self.sp_ring = 0.75                          # SP-1200 RING 0-1: the pitched-sample hum of a worn unit (0 = off)
        self.note_len = 24
        self.erasing, self.erase_pad = False, None
        self.rep_on, self.rep_div, self.rep_pad, self.rep_vel = False, 24, None, 100
        self.rep_pos = 0.0
        self._skip = {}
        self._clicks = []
        self._tails = []                                     # fading ends of stolen voices: [L, R, position]
        self.undo_stack, self.redo_stack = [], []
        self.pass_count = 0
        self._replace_pending, self._undone = False, False
        # input recording
        self.rec_state = "idle"
        self.rec_buf, self.rec_len, self.rec_peaks = [], 0, []
        self.rec_thresh, self.in_meter, self.has_input = 0.08, 0.0, False
        self.rec_src = "INPUT"                      # SAMPLE page: record the INPUT, or RESAMPLE (the sampler's own output)
        self.rec_in = "1-2"                         # which inputs: "1-2" (mixed to mono), "1" or "2"
        self.in_gain_db = 0.0                       # input gain before the recorder (-12 .. +24 dB)
        self.rec_preroll = 50                       # ms kept from before the level passed the threshold
        self.rec_max = 0                            # s: a take stops itself after this long (0 = no limit)
        self.rec_trim, self.rec_norm = True, True   # trim the quiet start / normalise the take
        self.in_monitor = False                     # hear the input through the outputs
        self.in_meter_lr = [0.0, 0.0]
        self.last_take = None                       # the new take (a sample in the project, on no pad): KEEP / DISCARD on SAMPLE
        self._pre = []                              # armed: the last blocks, for the pre-roll
        self.pending_mute = {}                      # MUTE > ON NEXT BAR: track n -> mute, switched on the next bar line
        self.mute_quant = False
        self.out_meter_mono = 0.0
        # MIDI clock and the keyboard's wheels
        self.clock_mode = "OFF"                     # OFF | SEND (we are the master) | FOLLOW (an external clock sets tempo, start, stop)
        self._ext_clock = []                        # FOLLOW: arrival times of the last MIDI clocks
        self.ext_bpm = None
        self.bend, self.bend_range = 0.0, 2         # pitch bend -1..1, range in semitones
        self.mod = 0.0                              # mod wheel / aftertouch 0..1: opens (or closes) pad filters on live notes
        self.v_rate0 = [1.0] * self.nv              # each voice's rate before the pitch bend
        self.msg, self.msg_time, self.msg_level, self.warn_time = "", 0.0, "info", 0.0
        self.load_project()
        self.warm_sp()

    # ---------- shortcuts the UI uses ----------
    @property
    def seq(self): return self.seqs[self.cur_seq]
    @property
    def track(self): return self.seq.tracks[self.cur_track]
    @property
    def prog(self): return self.programs[self.track.prog]
    @property
    def pad_idx(self): return self.bank * 16 + self.sel
    @property
    def pad(self): return self.prog.pads[self.pad_idx]
    @property
    def bpm(self): return self.seq.bpm

    # status messages, by how much attention they deserve (screens.py draws them in the transport glass, not over the page):
    #   quiet: the thing is already visible (a lit key, the counter, the page) - nothing is shown
    #   save:  background saving - a small disk icon blinks in the glass
    #   info:  feedback on what you just did - a dot-matrix line in the glass for a few seconds
    #   warn:  something you need to know - amber line, and the warning LED in the glass stays lit for a while
    _QUIET = re.compile(r"^(bank [A-D]$|pad bank |pad [A-D]\d\d selected|track \d+$|sequence \d\d$|metronome |note repeat |"
                        r"FULL LEVEL |count-in|all tracks on|solo off|redo$|undo$)")
    _SAVE = re.compile(r"(^project saved|^project .* saved$|^saved as )")
    _WARN = re.compile(r"(^no |\bnot\b|cannot|could not|can't|failed|error|overload|first$|first:|already|needs|busy|^nothing|"
                       r"at most|at least|STOP SEQUENCER|NO DATA|n/a)", re.I)

    def say(self, text, level=None):
        if level is None:
            level = ("quiet" if self._QUIET.search(text) else "save" if self._SAVE.search(text)
                     else "warn" if self._WARN.search(text) else "info")
        self.msg_level = level
        if level == "warn": self.warn_time = time.time()
        if level == "quiet": return
        self.msg, self.msg_time = text, time.time()

    def all_pads(self):
        if self._allpads is None:
            self._allpads = [p for pr in self.programs for p in pr.pads]
            self._pad_prog = {id(p): pr for pr in self.programs for p in pr.pads}     # pad -> its program (program inserts)
        return self._allpads

    all_pads_cache = all_pads

    def select_pad(self, bank, sel):
        self.bank, self.sel = bank % 4, sel % 16

    # ---------- sources ----------
    def add_source(self, name, raw, dirty=False):
        s = Source(len(self.sources), name, raw)
        s.dirty = dirty
        self.sources.append(s)
        return s

    def import_file(self, path):
        """Load an audio file from anywhere (USB stick, folder) into the project as a new source; it is copied into
        samples/ when the project is saved. Returns the Source."""
        x, sr, label = read_audio(path)
        x = resample(x, sr, OUT_SR)
        base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)[:24] or "sample"
        name, k = base, 2
        while self.source_by_name(name) is not None: name, k = f"{base}_{k}", k + 1
        return self.add_source(name, x, dirty=True)

    def preview_file(self, path, vel=110):
        """hear a file without adding it to the project"""
        x, sr, _ = read_audio(path)
        x = resample(x, sr, OUT_SR)[: OUT_SR * 20]
        src = Source(-1, "preview", x)
        tmp = Pad(-1); tmp.assign(src)
        tmp.vol, tmp.mode = 0.9, "ONE"
        self.stop_preview()
        self.trigger(tmp, vel, key=("preview",))
        return src.length / float(OUT_SR)

    def stop_preview(self): self.release_key(("preview",))

    def source_by_name(self, name):
        return next((s for s in self.sources if s.name == name), None)

    def pad_changed(self, pad):
        pad.gen += 1
        if pad.warp: self._warp_br = None                             # an edited WARP pad is re-rendered straight away
        if not pad.empty: pad.build()
        if not pad.empty and not pad.warp and self.sound_of(pad) == "SP-1200":
            self.sp_data(pad)                                         # (sampled into the SP here, not at the next hit)
        self._live_edit(pad)

    def _live_edit(self, pad):
        """notes of this pad that are sounding follow an edit of its region (as on an MPC): a plain voice moves onto the new
        sound at the same place in the sample (and ends if that place is now outside the region); WARP notes cross-fade
        onto a new render as soon as it is ready (_warp_update)"""
        if pad.empty: return
        with self.lock:
            for i in range(self.nv):
                rg = self.v_reg[i]
                if rg is None or self.v_pad[i] is not pad or self.v_data[i] is None or self.v_warp[i] is not None: continue
                s0, e0, rev0, sc0, semi_ = rg
                bend = self.v_rate[i] / self.v_rate0[i] if self.v_rate0[i] else 1.0
                if rg[:3] == (pad.start, pad.end, pad.reverse) and self.v_data[i] is pad.build()[0]:
                    self.v_rate0[i] = 2.0 ** ((pad.pitch + semi_) / 12.0) * sc0; self.v_rate[i] = self.v_rate0[i] * bend   # tune: live
                    continue
                src_pos = (e0 - self.v_pos[i] / sc0) if rev0 else (s0 + self.v_pos[i] / sc0)
                data, sc = pad.build()
                p_new = ((pad.end - src_pos) if pad.reverse else (src_pos - pad.start)) * sc
                self.v_data[i], self.v_end[i] = data, float(len(data) - 1)
                self.v_rate0[i] = 2.0 ** ((pad.pitch + semi_) / 12.0) * sc; self.v_rate[i] = self.v_rate0[i] * bend
                self.v_reg[i] = (pad.start, pad.end, pad.reverse, sc, semi_)
                if 0 <= p_new < len(data) - 1: self.v_pos[i] = p_new
                else:
                    self.v_pos[i] = max(0.0, min(float(len(data) - 2), p_new))
                    self.v_kill[i] = FADE_FR if self.v_kill[i] < 0 else min(self.v_kill[i], FADE_FR)

    # ---------- project ----------
    def _default_project(self):
        pr = self.programs[0]
        for i in range(16):
            s = self.source_by_name(f"pad{i + 1:02d}")
            if s is None and i < len(self.sources): s = self.sources[i]
            if s is not None:
                p = pr.pads[i]; p.assign(s)
                p.lofi_on = True
        pr.pads[2].choke = 1; pr.pads[3].choke = 1          # closed + open hat cut each other
        sq = self.seqs[0]; sq.name = "Demo beat"; sq.bpm = 90.0
        T = sq.tracks
        T[0].name, T[1].name, T[2].name, T[3].name = "Kick", "Snare", "Hats", "Perc"
        for bar in range(2):
            b = bar * 384
            for st in (0, 7, 10) + ((14,) if bar else ()): self._put(T[0], b + st * 24, 0, 110, 24)
            for st in (4, 12): self._put(T[1], b + st * 24, 1, 105, 24)
            for st in range(0, 16, 2): self._put(T[2], b + st * 24, 2, 80 if st % 4 else 95, 24)
            self._put(T[2], b + 15 * 24, 3, 70, 24)
            self._put(T[3], b + (6 if bar else 11) * 24, 5, 90, 24)
        for i in (0, 1, 2, 3): T[i].vol = 0.8
        brk = self.source_by_name("break")
        if brk is not None:                                         # program 2: the break cut into 8 beats (non-destructive)
            self.programs[1].name = "BREAK"
            self.chop_equal(brk, 8)
            self.chop_to_pads(brk, 0, self.programs[1])
            T[4].name, T[4].prog, T[4].mute = "Break", 1, True
            for k in range(8): self._put(T[4], k * 96, k, 100, 96)
        self.seqs[1].name = "Empty"
        self.song = [[0, 2]]

    def load_project(self):
        paths = sorted(f for f in os.listdir(self.sample_dir) if f.lower().endswith(".wav"))
        for f in paths:
            try:
                x, sr = load_wav(os.path.join(self.sample_dir, f))
                x = resample(x, sr, OUT_SR)
                self.add_source(os.path.splitext(f)[0], x)
            except Exception as e:
                print("could not load", f, e)
        d = None
        if os.path.exists(self.project_file):
            try:
                d = json.load(open(self.project_file))
                if d.get("version") != VERSION: d = None
            except Exception as e:
                print("could not read project.json:", e); d = None
        if d is None:
            if not self._blank: self._default_project()
            return
        try:
            self.volume = float(d.get("volume", 0.8))
            self.lim_on = bool(d.get("lim_on", True))
            for sd in d.get("sources", []):
                s = self.source_by_name(sd["name"])
                if s: s.chops = [int(c) for c in sd.get("chops", []) if 0 < int(c) < s.length]
                if s and sd.get("slices"):
                    sl = [[max(0, int(a)), min(s.length, int(b))] for a, b in sd["slices"]]
                    s.slices = [x for x in sl if x[1] - x[0] >= 32] or None
                if s and "asr_native" in sd:                              # a transwave's own copy at the ASR-10's rate
                    try:
                        with wave.open(os.path.join(self.sample_dir, "asr", s.name + ".wav"), "rb") as w:
                            s.native = (int(sd["asr_native"]), np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.int16))
                    except Exception as ex: print("transwave copy missing for", s.name, ex)
            for pr, pd in zip(self.programs, d.get("programs", [])):
                pr.name = pd.get("name", pr.name)
                pr.sound = pd.get("sound") if pd.get("sound") in SOUNDS else None
                for pad, ps in zip(pr.pads, pd.get("pads", [])):
                    self._load_pad(pad, ps)
                for k, (st, byp) in enumerate(zip(pd.get("fx", []), pd.get("fx_bypass", []))):
                    if st and k < Program.NFX: self._restore_fx(FxSlot(pr, k), st, byp)
                pr.strip.load(pd.get("mix"))
            cons = d.get("console") or {}
            for rt, rd in zip(self.returns, cons.get("returns", [])):
                rt.load(rd.get("mix"))
                for k, (st, byp) in enumerate(zip(rd.get("fx", []), rd.get("fx_bypass", []))):
                    if st and k < len(rt.fx): self._restore_fx(FxSlot(rt, k), st, byp)
            md = cons.get("master") or {}
            self.master_strip.load(md.get("mix"))
            for k, (st, byp) in enumerate(zip(md.get("fx", []), md.get("fx_bypass", []))):
                if st and k < len(self.master_strip.fx): self._restore_fx(FxSlot(self.master_strip, k), st, byp)
            self.send_master = [float(x) for x in cons.get("send_master", [1.0, 1.0])][:2]
            for g, gd in zip(self.groups, cons.get("groups", [])): g.load(gd)
            for sq, sd in zip(self.seqs, d.get("sequences", [])):
                sq.name, sq.bars, sq.num, sq.den = sd["name"], sd["bars"], sd["num"], sd["den"]
                sq.bpm, sq.swing, sq.loop = sd["bpm"], sd["swing"], sd["loop"]
                for tr, td in zip(sq.tracks, sd["tracks"]):
                    tr.name, tr.prog, tr.mute, tr.solo = td["name"], td["prog"], td["mute"], td["solo"]
                    tr.vol, tr.pan = td["vol"], td["pan"]
                    tr.events = sorted(tuple(ev) for ev in td["events"])
                    tr.kind, tr.key_pad = td.get("kind", "drum"), int(td.get("key_pad", 0))
                    tr.root, tr.midi_ch = int(td.get("root", 60)), int(td.get("midi_ch", 0))
                    tr.plugin, tr.plugin_state = td.get("plugin", ""), td.get("plugin_state")
                    tr.mgroup = int(td.get("mgroup", 0))
                    tr.auto = {k: sorted([int(p[0]), float(p[1])] for p in v) for k, v in (td.get("auto") or {}).items() if v}
            self.song = d.get("song", [[0, 1]])
            self.cur_seq = int(d.get("cur_seq", 0)); self.cur_track = int(d.get("cur_track", 0))
            st = d.get("settings", {})
            self.qgrid, self.metro, self.count_in = st.get("qgrid", 4), st.get("metro", False), st.get("count_in", 0)
            self.rec_quant = st.get("rec_quant", False)
            self.machine = st.get("machine") or ("MPC60" if st.get("timing") == "MPC60" else "MODERN")
            if self.machine not in MACHINES: self.machine = "MODERN"
            self.tc_shift = int(st.get("tc_shift", 0))
            self.sp_ac = max(0, min(len(SP_CORRECT) - 1, int(st.get("sp_ac", 5))))
            self.sp_ring = max(0.0, min(1.0, float(st.get("sp_ring", 0.75))))
            self.asr_q = max(0, min(len(ASR_Q) - 1, int(st.get("asr_q", 4))))
            self.asr_rate = 1 if int(st.get("asr_rate", 0)) == 1 else 0
            pf = st.get("perform")
            if pf and len(pf) == 5: self.perf_scale, self.perf_root, self.perf_oct, self.perf_chord, self.perf_gate = [int(x) for x in pf]
            self.levels_param = st.get("levels", "VELOCITY")
            self._restore_fx(None, d.get("master_fx"), d.get("master_fx_bypass", False))
        except Exception as e:
            print("project.json is damaged, starting fresh:", e)
            try: os.replace(self.project_file, self.project_file + ".bak")
            except OSError: pass
            self.__init__(self.dir, self.nout, self.nv, self.app_dir, self._blank, self.lock)

    def _load_pad(self, pad, ps):
        s = self.source_by_name(ps["src"]) if ps.get("src") else None
        if s is not None:
            pad.src, pad.start, pad.end = s, int(ps["start"]), min(int(ps["end"]), s.length)
        for k in ("reverse", "norm", "fade_in", "fade_out", "gain_db", "tune", "vol", "pan", "mute", "solo",
                  "lofi_on", "rpm", "mode", "choke", "fx_bypass", "warp", "warp_bpm", "vel_mpc", "fine", "stretch", "sp_ch",
                  "attack", "decay", "flt", "cutoff", "res", "f_env", "f_dec", "f_vel",
                  "a_loop", "a_ls", "a_le", "a_mod", "a_src", "a_amt", "a_range", "a_lfo_wave", "a_lfo_rate", "a_lfo_depth",
                  "a_lfo_delay", "a_env1", "a_fmode", "a_f1", "a_f2", "a_kbd1", "a_kbd2", "a_bus", "a_amp_t", "a_amp_l", "a_softvel", "a_vcurve", "a_emode",
                  "m_dmode", "m_vatk", "m_vstart", "m_vpitch", "f_atk"):
            if k in ps: setattr(pad, k, ps[k])
        if pad.rpm not in SP_RPMS: pad.rpm = 33
        if pad.a_src not in asrvoice.MOD_SOURCES: pad.a_src = "ENV1"
        pad.a_env1 = list(pad.a_env1)[:4] if len(pad.a_env1) >= 4 else [0, 2000, 1.0, 200]
        pad.a_amp_t = list(pad.a_amp_t)[:5] if len(pad.a_amp_t) >= 5 else [0, 0, 0, 0, 20]
        pad.a_amp_l = list(pad.a_amp_l)[:5] if len(pad.a_amp_l) >= 5 else [0, 99, 99, 99, 99]
        pad.out = int(ps.get("out", 0)) if 0 <= int(ps.get("out", 0)) < len(OUT_NAMES) else 0
        pad.link = tuple(ps["link"]) if ps.get("link") and s is not None else None
        if s is not None and pad.link: pad.link = (s.id, pad.link[1])
        self._restore_fx(pad, ps.get("fx"), ps.get("fx_bypass", False))

    def save_project(self):
        for s in self.sources:
            if s.dirty:
                save_wav(os.path.join(self.sample_dir, s.name + ".wav"), s.raw); s.dirty = False
                if getattr(s, "native", None) is not None:              # the transwave as the ASR-10 holds it
                    os.makedirs(os.path.join(self.sample_dir, "asr"), exist_ok=True)
                    with wave.open(os.path.join(self.sample_dir, "asr", s.name + ".wav"), "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(round(ASR_RATES[s.native[0]])))
                        w.writeframes(np.asarray(s.native[1], "<i2").tobytes())
        for old in self._renamed:                                     # a renamed sample: its old file goes
            if self.source_by_name(old) is None:
                try: os.remove(os.path.join(self.sample_dir, old + ".wav"))
                except OSError: pass
        self._renamed = []
        d = self.project_state()
        tmp = self.project_file + ".tmp"                              # write then swap: a power cut never leaves half a file
        with open(tmp, "w") as f: json.dump(d, f)
        os.replace(tmp, self.project_file)
        self._saved_sig = {k: self._sig(f()) for k, f in self._parts(d)}; self._cur_sig = dict(self._saved_sig)
        self._remember()
        self.say(f"project {self.project_name} saved")

    @staticmethod
    def _sig(v):
        import hashlib
        return hashlib.sha1(json.dumps(v, sort_keys=True, default=str).encode()).hexdigest()

    def _parts(self, d):
        """the project in small pieces (one program each, the sequences, the rest): each is quick to fingerprint, so the
        unsaved check never holds the audio up (the whole project at once took 10-30 ms: longer than an audio block)"""
        rest = {k: v for k, v in d.items() if k not in ("programs", "cur_seq", "cur_track")}
        return [("p%d" % i, (lambda i=i: d["programs"][i])) for i in range(len(d.get("programs", [])))] + [("rest", lambda: rest)]

    def _sigs(self):
        d = self.project_state()
        return {k: self._sig(f()) for k, f in self._parts(d)}

    @staticmethod
    def _prog_state(p):
        return {"name": p.name, "sound": p.sound, "pads": [x.state() for x in p.pads],
                "fx": [f.state() if f else None for f in p.fx], "fx_bypass": list(p.fx_bypass), "mix": p.strip.state()}

    def unsaved(self, full=False):
        """True when the project differs from what was last saved or opened. For the screen: ONE piece a call (one
        program, or the rest), four a second, so the audio is never held up. full=True: the whole project now - for a
        decision (the save question, autosave), which only happens when you act."""
        if getattr(self, "_saved_sig", None) is None:
            self._saved_sig = self._sigs(); self._cur_sig = dict(self._saved_sig); self._unsaved = False
        if full:
            self._cur_sig = self._sigs()
            self._unsaved = self._cur_sig != self._saved_sig or any(s.dirty for s in self.sources) or bool(self._renamed)
            return self._unsaved
        now = time.time()
        if now - getattr(self, "_unsaved_t", 0.0) < 0.25: return self._unsaved   # four pieces a second is plenty
        self._unsaved_t = now
        names = list(self._saved_sig)
        self._chk = (getattr(self, "_chk", -1) + 1) % len(names)
        k = names[self._chk]
        if k.startswith("p") and int(k[1:]) < len(self.programs): v = self._prog_state(self.programs[int(k[1:])])
        else:
            pr, self.programs = self.programs, []                     # the rest, without building the programs again
            try: d = self.project_state()
            finally: self.programs = pr
            v = {kk: vv for kk, vv in d.items() if kk not in ("programs", "cur_seq", "cur_track")}
        self._cur_sig[k] = self._sig(v)
        self._unsaved = self._cur_sig != self._saved_sig or any(s.dirty for s in self.sources) or bool(self._renamed)
        return self._unsaved

    def project_state(self):
        """everything project.json holds"""
        d = {"version": VERSION, "volume": self.volume, "lim_on": self.lim_on, "cur_seq": self.cur_seq, "cur_track": self.cur_track,
             "settings": {"qgrid": self.qgrid, "metro": self.metro, "count_in": self.count_in, "rec_quant": self.rec_quant,
                          "machine": self.machine, "tc_shift": self.tc_shift, "sp_ac": self.sp_ac, "sp_ring": self.sp_ring, "asr_q": self.asr_q, "asr_rate": self.asr_rate,
                          "perform": [self.perf_scale, self.perf_root, self.perf_oct, self.perf_chord, self.perf_gate],
                          "levels": self.levels_param},
             "sources": [dict({"name": s.name, "chops": list(s.chops)}, **({"asr_native": s.native[0]} if getattr(s, "native", None) else {}),
                              **({"slices": [list(x) for x in s.slices]} if getattr(s, "slices", None) else {}))
                         for s in self.sources],
             "programs": [self._prog_state(p) for p in self.programs],
             "console": {"returns": [{"mix": rt.state(), "fx": [f.state() if f else None for f in rt.fx], "fx_bypass": list(rt.fx_bypass)}
                                     for rt in self.returns],
                         "master": {"mix": self.master_strip.state(), "fx": [f.state() if f else None for f in self.master_strip.fx],
                                    "fx_bypass": list(self.master_strip.fx_bypass)},
                         "groups": [g.state() for g in self.groups],
                         "send_master": list(self.send_master)},
             "sequences": [{"name": q.name, "bars": q.bars, "num": q.num, "den": q.den, "bpm": q.bpm, "swing": q.swing,
                            "loop": q.loop,
                            "tracks": [{"name": t.name, "prog": t.prog, "mute": t.mute, "solo": t.solo, "vol": t.vol,
                                        "pan": t.pan, "events": [list(e) for e in t.events],
                                        "kind": t.kind, "key_pad": t.key_pad, "root": t.root, "midi_ch": t.midi_ch,
                                        "plugin": t.plugin, "plugin_state": (self.instruments[id(t)].state() if id(t) in self.instruments else t.plugin_state),
                                        "auto": {k: v for k, v in t.auto.items() if v}, "mgroup": t.mgroup}
                                       for t in q.tracks]}
                           for q in self.seqs],
             "song": self.song,
             "master_fx": self.master_fx.state() if self.master_fx else None,
             "master_fx_bypass": self.master_fx_bypass}
        return d

    # ---------- projects: the software's own folder is the DEMO project, the rest live in projects/<name> ----------
    @property
    def project_name(self):
        return "DEMO" if os.path.abspath(self.dir) == os.path.abspath(self.app_dir) else os.path.basename(os.path.normpath(self.dir))

    @property
    def projects_root(self): return os.path.join(self.app_dir, "projects")

    def list_projects(self):
        """[(name, folder)]: the demo first, then saved projects A-Z"""
        out = [("DEMO", self.app_dir)]
        if os.path.isdir(self.projects_root):
            for n in sorted(os.listdir(self.projects_root), key=str.lower):
                p = os.path.join(self.projects_root, n)
                if os.path.isdir(p) and (os.path.exists(os.path.join(p, "project.json")) or os.path.isdir(os.path.join(p, "samples"))):
                    out.append((n, p))
        return out

    @staticmethod
    def clean_name(name, maxlen=24):
        return "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip()[:maxlen]

    def _project_path(self, name):
        base = self.clean_name(name) or "Project"
        if base.upper() == "DEMO": base += " 2"
        path, k = os.path.join(self.projects_root, base), 2
        while os.path.exists(path): path, k = os.path.join(self.projects_root, f"{base} {k}"), k + 1
        return path

    def _remember(self):
        try:
            with open(os.path.join(self.app_dir, "last_project.txt"), "w") as f: f.write(os.path.abspath(self.dir))
        except OSError: pass

    @staticmethod
    def last_project(app_dir):
        """the project that was open last time (None = the demo)"""
        try:
            p = open(os.path.join(app_dir, "last_project.txt")).read().strip()
            return p if p and os.path.isdir(p) else None
        except OSError: return None

    def _switch(self, folder, blank=False):
        with self.lock:
            if self.playing: self.stop()
            midi_out, lock, clk, br = self.midi_out, self.lock, self.clock_mode, self.bend_range
            self.__init__(folder, self.nout, self.nv, self.app_dir, blank, lock)
            self.midi_out, self.clock_mode, self.bend_range = midi_out, clk, br

    def open_project(self, folder, save_first=True):
        """open a project; the one that is open is saved first"""
        if os.path.abspath(folder) == os.path.abspath(self.dir): return
        if save_first: self.save_project()
        self._switch(folder)
        self._remember()
        self.say(f"project {self.project_name} open")

    def new_project(self, name, save_first=True):
        """an empty project in projects/<name> (the one that is open is saved first)"""
        if save_first: self.save_project()
        path = self._project_path(name)
        os.makedirs(os.path.join(path, "samples"), exist_ok=True)
        self._switch(path, blank=True)
        self.save_project()
        self.say(f"new project {self.project_name}")
        return path

    def save_as(self, name):
        """copy the open project, samples and all, to projects/<name> and carry on in the copy"""
        path = self._project_path(name)
        with self.lock:
            os.makedirs(os.path.join(path, "samples"), exist_ok=True)
            self.dir, self.sample_dir, self.project_file = path, os.path.join(path, "samples"), os.path.join(path, "project.json")
            self._blank, self._renamed = True, []
            for s in self.sources: s.dirty = True
        self.save_project()
        return path

    def unused_sources(self):
        """samples no pad of any program plays"""
        used = {id(p.src) for p in self.all_pads() if p.src is not None}
        return [s for s in self.sources if id(s) not in used]

    def delete_unused(self):
        """remove samples no pad uses (their files go at the next save); the rest are renumbered"""
        gone = self.unused_sources()
        if not gone: self.say("every sample is used by a pad"); return 0
        with self.lock:
            keep = [s for s in self.sources if s not in gone]
            remap = {s.id: k for k, s in enumerate(keep)}
            for p in self.all_pads():
                if p.link and p.link[0] in remap: p.link = (remap[p.link[0]], p.link[1])
            for k, s in enumerate(keep): s.id = k
            self.sources = keep
            self._renamed += [s.name for s in gone]
        self.say(f"{len(gone)} unused sample{'s' if len(gone) > 1 else ''} deleted (the files go when the project is saved)")
        return len(gone)

    def rename_source(self, src, name):
        """rename a sample (its file is renamed at the next save)"""
        name = self.clean_name(name)
        if not name or name == src.name: return src.name
        base, k = name, 2
        while self.source_by_name(name) is not None: name, k = f"{base}_{k}", k + 1
        self._renamed.append(src.name)
        src.name, src.dirty = name, True
        return name

    # ---------- insert effects (target = a Pad, or 'master') ----------
    def _restore_fx(self, pad, state, bypass):
        if not state: return
        try:
            effect = fxlib.from_state(state)
        except Exception as ex:
            print("could not restore effect:", ex); return
        if pad is None: self.master_fx, self.master_fx_bypass = effect, bypass
        else: pad.fx, pad.fx_bypass = effect, bypass             # a pad or a program slot (FxSlot)

    def get_fx(self, t): return self.master_fx if t == "master" else t.fx
    def get_bypass(self, t): return self.master_fx_bypass if t == "master" else t.fx_bypass

    def toggle_bypass(self, t):
        if t == "master": self.master_fx_bypass = not self.master_fx_bypass
        else: t.fx_bypass = not t.fx_bypass

    def set_fx(self, t, kind=None, ident=None):
        effect = None
        if kind:
            try:
                effect = fxlib.create(kind, ident)
            except Exception as ex:
                self.say(f"could not load: {str(ex)[:40]}"); return False
        if t == "master": self.master_fx, self.master_fx_bypass = effect, False
        else: t.fx, t.fx_bypass = effect, False
        self.say(f"{effect.name} loaded" if effect else "effect removed")
        return True

    def _bus_target(self, pad, progbus):
        """the ASR-10 effect a pad's sound reaches first (its FX1 / FX2 / DRY bus matters there), or None: the pad's own
        effect, else its program's first insert, else the master effect - only if that is an ASR-10 effect"""
        is_asr = lambda f: f is not None and getattr(f, "kind", "") == "asr10"
        if pad.fx is not None and not pad.fx_bypass: return ("pad", id(pad)) if is_asr(pad.fx) else None
        if self.out_ok(pad.out): return None
        pr_ = self._pad_prog.get(id(pad))
        if pr_ is not None and pr_.n in progbus:
            first = next((f for f, b in zip(pr_.fx, pr_.fx_bypass) if f is not None and not b), None)
            if first is not None: return ("prog", pr_.n) if is_asr(first) else None
        return "master" if (not self.master_fx_bypass and is_asr(self.master_fx)) else None

    def _strip_out(self, st, bl, br, anysolo, snd, L, R, routed, group=False):
        """a console strip: EQ, fader / pan, meter, mute / solo, sends (post-fader), then to a group bus or the mix
        (a group bus: to the mix or a direct output pair)"""
        if st.is_default() and not anysolo and st is not self.analyse:  # untouched strip: straight into the mix
            st.meter_in(bl, br); L += bl; R += br; return
        bl, br = st.run_eq(bl, br, dspfast.sos)
        if st is self.analyse:                                         # the EQ analyser: the last 4096 samples after the EQ
            x = (0.5 * (np.asarray(bl) + np.asarray(br))).astype(np.float32)[-4096:]
            self.an_buf = np.concatenate((self.an_buf[len(x):], x))
        gl, gr = st.gains()
        bl = bl * gl; br = br * gr
        st.meter_in(bl, br)
        if st.mute or (anysolo and not st.solo and snd is not None): return
        if snd is not None:
            for k in (0, 1):
                a = st.sends[k] * self.send_master[k]
                if a > 0: snd[k][0] += bl * a; snd[k][1] += br * a
        if not group and st.out in ("1-2", "3-4"):
            g = self._grp[0 if st.out == "1-2" else 1]; g[0] += bl; g[1] += br; return
        code = console.OUT_CODE.get(st.out, 0) if group else 0
        if code and self.out_ok(code): routed.append((code, bl, br))
        else: L += bl; R += br

    def _run_fx(self, owner_fx, L, R, owner, buses=None):
        try:
            if buses is not None and hasattr(owner_fx, "process_buses"):        # an ASR-10 effect: its three buses
                return owner_fx.process_buses(L, R, buses[0][0], buses[0][1], buses[1][0], buses[1][1])
            return owner_fx.process(L, R)
        except Exception as ex:                                  # a crashing plugin must never kill the audio thread
            print("effect error:", ex)
            if owner == "master": self.master_fx_bypass = True
            else: owner.fx_bypass = True
            self.say("effect error - bypassed")
            return L, R

    # ---------- voices ----------
    def any_pad_solo(self, prog): return any(p.solo for p in prog.pads)

    def trigger(self, pad, vel, delay=0, dur_frames=None, track=None, semi=0, key=None, hold=False):
        """Start a pad. dur_frames only matters for HOLD pads (or hold=True: keyboard notes always stop at their length).
        semi = extra transposition in semitones (KEYS tracks / keyboard); key = a held keyboard note this voice belongs to:
        keyboard notes get a voice of their own (chords), and release_key() fades them out."""
        if pad.empty or pad.mute: return
        if self.bouncing and threading.current_thread() is not self._bounce_thread: return   # live hits stay out of a bounce
        eng = self.sound_of(pad)
        sp = eng == "SP-1200" and not pad.warp
        asr = eng == "ASR-10" and not pad.warp
        ak = None if pad.warp else mpcvoice.CHIPS.get(eng)     # an MPC: its sound chip (0 = the MPC60's, 1 = the 3000 / 2000XL's)
        if ak is not None:
            data, sc = self.mpc_data(pad, ak), (mpcvoice.MPC60_SR / OUT_SR if ak == 0 else 1.0)
        elif sp:                                           # SP-1200: its own copy of the sound, stepped through without interpolation
            data, sc = self.sp_data(pad), 1.0
        elif asr:                                        # ASR-10: held at its system rate in 16 bits, played back interpolated
            data, sc = self.asr_data(pad), ASR_RATES[self.asr_rate] / OUT_SR
        else:
            data, sc = pad.build()
        start, end = 0, len(data) - 1
        if end < 2: return
        rate = 2.0 ** (((pad.tune if sp else pad.pitch) + semi) / 12.0) * sc     # (the SP-1200 has no fine tune)
        wv = None
        if pad.warp:                                     # WARP: a stretched render that lasts as long at this tempo as at warp_bpm
            bpm = self.seq.bpm
            semis = round(pad.pitch + semi, 2)
            with self.lock: data, sc, bpm_r, s_r = self.warp_get(pad, self.warp_q(bpm), semis)
            end = len(data) - 1
            rate = sc * bpm / bpm_r
            wv = [self.beat_clock + delay * bpm / 60.0 / OUT_SR, bpm_r, semis, s_r, False, pad.gen, semi]
        trk = track if track is not None else self.track
        tvol, tpan = trk.vol, trk.pan
        vg = (vel / 127.0) ** 1.5 if pad.vel_mpc is None else max(0.0, 1.0 - (127 - vel) * pad.vel_mpc / 12700.0)
        if asr: vg = 1.0                                 # ASR-10: velocity works through its amp envelope's levels
        g0 = pad.vol * vg * 10.0 ** (pad.gain_db / 20.0)
        gl, gr = self._pan_gains(g0 * tvol, pad.pan + tpan)
        kill = int(dur_frames) if ((pad.mode == "HOLD" or hold) and dur_frames) else -1
        with self.lock:
            if sp:                                       # one voice per SP channel: a new hit there cuts the old one
                ch = self.sp_channel(pad)
                for i in range(self.nv):
                    if self.v_data[i] is not None and self.v_sp[i] is not None and self.v_sp[i][1] == ch and self.v_delay[i] == 0:
                        self.v_kill[i] = 44 if self.v_kill[i] < 0 else min(self.v_kill[i], 44)
            if pad.choke:
                for i in range(self.nv):
                    q = self.v_pad[i]
                    if q is not None and q is not pad and q.choke == pad.choke and q.owner is pad.owner:   # groups are per program
                        self.v_kill[i] = FADE_FR if self.v_kill[i] < 0 else min(self.v_kill[i], FADE_FR)
            same = None if (key is not None or semi) else next((i for i in range(self.nv) if self.v_pad[i] is pad and self.v_key[i] is None
                                                                and self.v_data[i] is not None), None)
            v = None
            if key is not None: v = next((i for i in range(self.nv) if self.v_key[i] == key and self.v_data[i] is not None), None)
            if same is not None:                         # the pad is still sounding: fade it out under the new hit (no click)
                if self.v_delay[same] > 0: v = same         # (not started yet: just replace it)
                else: self.v_kill[same] = FADE_FR if self.v_kill[same] < 0 else min(self.v_kill[same], FADE_FR)
            if v is None: v = next((i for i in range(self.nv) if self.v_data[i] is None), None)
            if v is None:                                # all busy: take a voice that is already fading, else the oldest...
                fading = [i for i in range(self.nv) if self.v_kill[i] >= 0 and i != same]
                v = min(fading or range(self.nv), key=lambda i: self.v_age[i])
                self._steal_tail(v)                      # ...and let what it was playing fade out instead of stopping dead
            self.counter += 1
            self.v_data[v], self.v_pos[v], self.v_rate[v], self.v_end[v] = data, float(start), rate, float(end)
            self.v_gl[v], self.v_gr[v], self.v_kill[v] = gl, gr, kill
            self.v_delay[v], self.v_pad[v], self.v_age[v], self.v_lofi[v] = int(delay), pad, self.counter, sc != 1.0
            self.v_key[v] = key
            self.v_trk[v], self.v_base[v] = trk, (g0, pad.pan)
            self.v_warp[v], self.v_fin[v] = wv, 0
            self.v_t[v] = 0
            self.v_rate0[v] = rate
            if key is not None and self.bend and wv is None: self.v_rate[v] = rate * 2.0 ** (self.bend * self.bend_range / 12.0)
            self.v_env[v] = None if (asr or ak is not None) else self.voice_env(pad, vel)   # ASR-10 / MPCs: their own envelopes
            self.v_fst[v][:] = 0.0
            self.v_sp[v] = (sp_step(pad.tune + semi - SP_RPMS.get(pad.rpm, 0)), self.sp_channel(pad),
                            sp_step(pad.tune - SP_RPMS.get(pad.rpm, 0))) if sp else None      # (the pad's own step: RING)
            self.v_spf[v] = 0.0
            if sp:
                ev_ = self.v_env[v]
                self.v_sps[v] = SPH.new_state()
                self.v_spp[v] = SPH.params(self.v_sp[v][0], self.v_sp[v][2], 0.0, self.v_sp[v][1],
                                           ev_[0] * SP_RATIO if ev_ else 0.0, ev_[1] * SP_RATIO if ev_ else 0.0, OUT_SR)
            self.v_asr[v] = asr
            for st_ in self.v_afs[v]: st_[:] = 0.0
            self.v_ov[v] = None
            self.v_reg[v] = (pad.start, pad.end, pad.reverse, sc, semi) if not (sp or asr or pad.warp) else None
            if asr:
                k_ = self._ov_start(v, pad, vel, semi, dur_frames)
                if k_ is not None and self.v_kill[v] < 0: self.v_kill[v] = k_
            if ak is not None:
                self._ak_start(v, pad, vel, semi, dur_frames if kill >= 0 else None, ak); self.v_kill[v] = -1
            self.v_mos[v] = mpchw.OutStage(eng) if (ak is not None and mpchw.stage(eng) is not None) else None

    LIM_T = 0.9                                              # the limiter keeps the mix under this, before the soft clipper
    LIM_REL = 0.12                                           # seconds to come back up after a peak

    def _limit(self, L, R, frames):
        """master limiter, one gain per block: drops at once (over 1.5 ms) when a block would go over LIM_T, then recovers
        smoothly. Cheap enough for the Pi; the soft clipper after it catches what is left."""
        if not self.lim_on:
            self.lim_g = 1.0; return None
        pk = max(float(np.abs(L).max()) if len(L) else 0.0, float(np.abs(R).max()) if len(R) else 0.0)
        target = 1.0 if pk <= self.LIM_T else self.LIM_T / pk
        g0 = self.lim_g
        if target < g0: g1 = target
        else: g1 = g0 + (target - g0) * (1.0 - np.exp(-frames / (self.LIM_REL * OUT_SR)))
        self.lim_g = g1
        if g0 >= 0.9999 and g1 >= 0.9999: return None
        gains = np.full(frames, g1, np.float32)
        k = min(frames, int(0.0015 * OUT_SR))
        if k > 1 and g0 != g1: gains[:k] = np.linspace(g0, g1, k, dtype=np.float32)
        return gains

    def asr_data(self, pad):
        rate = ASR_RATES[self.asr_rate]
        key = pad.pre_key() + (rate,)
        hit = self._asr_cache.get(id(pad))
        if hit is None or hit[0] != key:
            hit = self._asr_cache[id(pad)] = (key, make_asr(pad.pre(), rate))
        return hit[1]

    def sound_of(self, pad_or_prog):
        """the sound a program plays with: its own SOUND, else the machine's"""
        prog = pad_or_prog if isinstance(pad_or_prog, Program) else getattr(pad_or_prog, "owner", None)
        if prog is not None and prog.sound in SOUNDS: return prog.sound
        return self.machine if self.machine in SOUNDS else "MODERN"

    def asr_loops(self, pad):
        """True when the pad uses the ASR-10's loop or sample modulation"""
        return pad.a_loop >= 2 or pad.a_mod != 0

    def mpc_mem(self, pad, ak):
        """the pad's sound as an MPC's chip holds it: the MPC60's 12-bit words at 40 kHz, or 16-bit at 44.1 kHz"""
        key = pad.pre_key() + (ak,)
        hit = self._asr_cache.get(("mpc", id(pad)))
        if hit is None or hit[0] != key:
            x = pad.pre()
            if ak == 0:                                        # the MPC60 samples through its 18 kHz LC filter (mpchw.py)
                h_ = mpchw.fir("MPC60", "in", OUT_SR, 255)
                x = np.convolve(np.asarray(x, np.float32), h_)[len(h_) // 2:len(h_) // 2 + len(x)].astype(np.float32)
            mem, g = mpcvoice.mpc60_words(x, OUT_SR) if ak == 0 else (mpcvoice.l6028_words(x), 1.0)
            hit = self._asr_cache[("mpc", id(pad))] = (key, mem, mem.astype(np.float32) / 32768.0, g)
        return hit[1]

    def mpc_data(self, pad, ak):
        self.mpc_mem(pad, ak)
        return self._asr_cache[("mpc", id(pad))][2]

    def _ak_start(self, v, pad, vel, semi, dur, ak):
        """an MPC voice on its chip's model (dsp/akai.c): VEL>START moves the start later when soft, VELO>PITCH
        bends it by velocity; the envelope and filter run per block in _ak_block"""
        mem = self.mpc_mem(pad, ak)
        chip_sr = mpcvoice.MPC60_SR if ak == 0 else mpcvoice.L6028_SR
        st = int(min(len(mem) - 2, max(0, pad.m_vstart * (1.0 - vel / 127.0) / 1000.0 * chip_sr)))
        ratio = 2.0 ** ((pad.pitch + semi + pad.m_vpitch / 100.0 * vel / 127.0) / 12.0)
        vo = mpcvoice.Voice(ak)
        vo.start(mem, st, len(mem), -1, ratio, OUT_SR)
        end_t = (len(mem) - st) / chip_sr / min(16.0, ratio)
        self.v_ov[v] = [vo, self._asr_cache[("mpc", id(pad))][3], 0.0, None, ratio, (vel, int(semi)), dur / OUT_SR if dur else None,
                        end_t, ak]

    def _ak_block(self, i, ovs, n):
        vo, lvl, t, _, ratio, (vel, semi), off, end_t, ak = ovs
        pad = self.v_pad[i]
        r = ratio * (self.v_rate[i] / self.v_rate0[i] if self.v_rate0[i] else 1.0)
        vo.set_step(r)
        f0 = f1 = -1
        if ak == 1 and pad.flt != "OFF":                     # the L6028's low-pass (LP only: HP / BP play as LP)
            c = mpcvoice.cutoff_at(pad, vel, np.array([t, t + n / OUT_SR]))
            f0, f1 = mpcvoice.cutoff_reg(c[0]), mpcvoice.cutoff_reg(c[1])
            if (f0 < 0) != (f1 < 0): f0, f1 = [mpcvoice.cutoff_reg(99.99) if f_ < 0 else f_ for f_ in (f0, f1)]
            vo.set_res(int(round(pad.res * 15)))
        s, k = vo.render(n, f0, f1)
        g, fin = mpcvoice.amp_env(pad, vel, t + np.arange(n) / OUT_SR, off, end_t * ratio / max(1e-6, r), ak == 0)
        s = s[:k] * (g[:k] * np.float32(lvl))
        if fin:                                              # the envelope has closed: the voice ends here
            nz = np.flatnonzero(g[:k] > 0); k = int(nz[-1]) + 1 if len(nz) else 0; s = s[:k]
        ovs[2] = t + n / OUT_SR
        return s, k

    def asr_mem(self, pad):
        """the pad's sound as the ASR-10's chip holds it: 16-bit, at its rate (a transwave made here: its own copy)"""
        rate = ASR_RATES[self.asr_rate]
        nat = getattr(pad.src, "native", None)
        if (nat is not None and nat[0] == self.asr_rate and pad.start == 0 and pad.end == pad.src.length
                and not (pad.reverse or pad.norm or pad.fade_in or pad.fade_out)):
            return nat[1]
        edges = not self.asr_loops(pad)
        key = pad.pre_key() + (rate, edges, "mem")
        hit = self._asr_cache.get(("mem", id(pad)))
        if hit is None or hit[0] != key:
            x = make_asr(pad.pre(edges), rate)
            hit = self._asr_cache[("mem", id(pad))] = (key, np.round(np.clip(x, -1.0, 32767 / 32768.0) * 32768.0).astype(np.int16))
        return hit[1]

    def asr_points(self, pad, mem):
        """(sample start, sample end, loop start, loop end) in the OS's units (samples x 512)"""
        rate = ASR_RATES[self.asr_rate]
        se = (len(mem) - 1) * 512
        le = int(round((pad.a_le if pad.a_le > 0 else pad.length / OUT_SR) * rate * 512))
        ls = int(round(pad.a_ls * rate * 512))
        le = max(min(le, se), 1024); ls = max(0, min(ls, le - 512))
        return 0, se, ls, le

    def _ov_start(self, v, pad, vel, semi, dur):
        """an ASR-10 voice on the sound chip's model (dsp/otto.c). Returns the kill frames for a looping sound."""
        mem = self.asr_mem(pad)
        rate = ASR_RATES[self.asr_rate]
        ss, se, ls, le = self.asr_points(pad, mem)
        fc0 = int(round(2.0 ** ((pad.pitch + semi) / 12.0) * 2048))
        srcs = asrvoice.Sources(pad, vel, 60 + int(semi), seed=self.counter)
        ov = asrvoice.Voice()
        ov.start(mem, ss, se, ls, le, pad.a_loop, pad.a_mod, pad.a_amt, pad.a_range, min(0x1ffff, fc0), rate / OUT_SR,
                 int(round(asrvoice.VOICE_TICK_S * rate)), srcs.value(pad.a_src, 0.0, self.mod))
        rel = None
        off = dur / OUT_SR if dur else None              # note-off: the amp envelope's RELEASE (and ENV1's)
        if pad.a_loop >= 2:                              # a loop sounds while the note is held
            held = int(dur) if dur else int(1.0 * OUT_SR)
            off = held / OUT_SR
            if pad.a_loop == 4: rel = held               # LOOP AND RELEASE: then on to the end of the sample
        self.v_ov[v] = [ov, srcs, 0.0, rel, fc0, (vel, int(semi)), off]
        self._ov_filter(ov, pad, vel, int(semi), 0.0)
        return None

    def _ov_filter(self, ov, pad, vel, semi, t):
        """the chip's filter for this moment: CUTOFF F1 / F2, plus KBD AMT (key from C4), the filter envelope (FILTER ENV
        / DECAY: the ASR's ENV2 on both) and velocity (softer = darker)"""
        rate = ASR_RATES[self.asr_rate]
        env = pad.f_env * 150.0 * float(np.exp(-t / max(0.001, pad.f_dec / 4000.0)))
        velo = -75.0 * pad.f_vel * (1.0 - vel / 127.0)
        key = semi + pad.pitch
        k1 = asrvoice.cutoff_k(pad.a_f1 + pad.a_kbd1 / 127.0 * asrvoice.UNITS_PER_SEMI * key + env + velo, rate)
        k2 = asrvoice.cutoff_k(pad.a_f2 + pad.a_kbd2 / 127.0 * asrvoice.UNITS_PER_SEMI * key + env + velo, rate)
        ov.filter(1, pad.a_fmode, k1, k2)

    def make_transwave(self, pad, frames=64):
        """turn the pad's sound into a transwave: `frames` single cycles taken through it (asrvoice.make_transwave),
        held at the ASR-10's rate, on a new sample; the pad then loops the first cycle and TRANSWAV moves through them
        with ENV1 (a 1.5 s sweep; any source and amount can be set after). Returns (frames, frame length, pitch Hz)."""
        if pad.empty: return None
        rate = ASR_RATES[self.asr_rate]
        mem, F, per = asrvoice.make_transwave(pad.pre(edges=False), OUT_SR, rate, frames)
        mem = np.append(mem, mem[-F])                    # the chip reads one sample past a loop's end: the cycle again
        raw = resample(mem[:-1].astype(np.float32) / 32768.0, rate, OUT_SR)
        base = (pad.src.name[:20] + "_TW")
        name, k = base, 2
        while self.source_by_name(name) is not None: name, k = f"{base}{k}", k + 1
        src = self.add_source(name, raw, dirty=True)
        src.native = (self.asr_rate, mem)
        with self.lock:
            pad.assign(src)
            pad.reverse = pad.norm = False; pad.fade_in = pad.fade_out = 0
            pad.a_loop, pad.a_ls, pad.a_le = 2, 0.0, F / rate
            pad.a_mod, pad.a_src, pad.a_amt, pad.a_range = 7, "ENV1", min(127, frames), pad.a_range
            pad.a_env1 = [1500, 0, 1.0, 300]
        self.pad_changed(pad)
        return frames, F, rate / F

    def _ov_block(self, i, ovs, n):
        """n output frames of an ASR-10 voice"""
        if len(ovs) == 9:                                            # (an MPC voice: its chip, then its DAC and
            s_, k_ = self._ak_block(i, ovs, n)                        # output filter - mpchw.py)
            if self.v_mos[i] is not None and k_: s_ = self.v_mos[i].process(s_)
            return s_, k_
        ov, srcs, t, rel, fc0 = ovs[:5]
        if rel is not None and rel >= 0:
            if rel < n: ov.release(); srcs.rel_t = t + rel / OUT_SR; ovs[3] = -1
            else: ovs[3] = rel - n
        fc = int(round(fc0 * self.v_rate[i] / self.v_rate0[i])) if self.v_rate0[i] else fc0
        ov.set(min(0x1ffff, fc), srcs.value(self.v_pad[i].a_src, t, self.mod))
        self._ov_filter(ov, self.v_pad[i], ovs[5][0], ovs[5][1], t)
        s, k = ov.render(n)
        off = ovs[6]
        if off is not None and srcs.rel_t is None and off < t + n / OUT_SR: srcs.rel_t = off       # ENV1 releases too
        g, done = asrvoice.amp_env(self.v_pad[i], ovs[5][0], t, n, OUT_SR, off)
        s = s[:k] * g[:k]
        if done:                                         # the release has run out: the voice ends here
            k = min(k, max(0, int(np.ceil((off + self.v_pad[i].a_amp_t[4] / 1000.0 - t) * OUT_SR))))
        ovs[2] = t + n / OUT_SR
        return s, k

    def _asr_filter(self, i, s, mode, c0, c1):
        """the ES5506's filter: four one-pole stages with no resonance. Poles 1-2 are always low-pass (cutoff K1); poles
        3-4 low-pass or high-pass (K2). LP = 3LP/1LP with K1 = K2 (24 dB); HP = 2LP/2HP with K1 open (12 dB); BP =
        2LP/2HP with K1 an octave above the cutoff and K2 an octave below"""
        fc = self.cut_hz(0.5 * (c0 + c1))
        a = lambda f: float(min(1.0, 1.0 - np.exp(-2.0 * np.pi * min(f, 0.49 * OUT_SR) / OUT_SR)))
        k1, k2 = {1: (fc, fc), 2: (20000.0, fc), 3: (fc * 2.0, fc * 0.5)}.get(mode, (20000.0, 20000.0))
        st = self.v_afs[i]
        x = np.array(s, np.float32)
        x = dspfast.onepole(x, st[0], a(k1)); x = dspfast.onepole(x, st[1], a(k1))
        if mode == 1:
            x = dspfast.onepole(x, st[2], a(k1)); return dspfast.onepole(x, st[3], a(k2))
        for j in (2, 3):                                           # high-pass poles: the input less its low-passed self
            lp = dspfast.onepole(x.copy(), st[j], a(k2)); x = x - lp
        return x.astype(np.float32)

    def warm_sp(self):
        """sample every SP-1200 pad into the SP now, in the background, so the first hit of each needs no work in the
        audio thread (sampling a sound in through the input filter takes a few tens of ms)"""
        pads = [p for p in self.all_pads() if not p.empty and not p.warp and self.sound_of(p) == "SP-1200"]
        if not pads: return None
        def run():
            for p in pads:
                try: self.sp_data(p)
                except Exception: pass
        t = threading.Thread(target=run, daemon=True); t.start()
        return t

    def sp_data(self, pad):
        key = pad.pre_key() + (pad.rpm,)
        hit = self._sp_cache.get(id(pad))
        if hit is None or hit[0] != key:
            hit = self._sp_cache[id(pad)] = (key, make_sp(pad.pre(), 2.0 ** (SP_RPMS.get(pad.rpm, 0) / 12.0)))
        return hit[1]

    @staticmethod
    def sp_channel(pad):
        """the SP-1200 gives each of its 8 pads (per bank) its own output channel: pad n -> channel n, unless the pad
        is set to one (CHANNEL on PROG: 1-2 dynamic filters, 3-6 fixed filters, 7-8 none)"""
        return pad.sp_ch if 1 <= getattr(pad, "sp_ch", 0) <= 8 else pad.idx % 8 + 1

    def _steal_tail(self, i):
        """the next few ms of a voice that is about to be reused, faded to silence and mixed into the main outs"""
        d = self.v_data[i]
        if d is None or self.v_delay[i] > 0: return
        n = STEAL_FR
        if self.v_ov[i] is not None:                                 # ASR-10 voice: a few ms more from its chip model
            x, k = self._ov_block(i, self.v_ov[i], n)
            x = x[:k] * np.linspace(1, 0, k, dtype=np.float32)
            if self.v_kill[i] >= 0: x *= np.clip((self.v_kill[i] - np.arange(len(x))) / float(FADE_FR), 0.0, 1.0).astype(np.float32)
            self._tails.append([x * self.v_gl[i], x * self.v_gr[i], 0]); self.v_ov[i] = None
            return
        idx = self.v_pos[i] + self.ramp[:n] * self.v_rate[i]
        idx = idx[idx < self.v_end[i]]
        if len(idx) < 2: return
        i0 = idx.astype(np.int64); fr = (idx - i0).astype(np.float32)
        x = (d[i0] * (1.0 - fr) + d[i0 + 1] * fr) * np.linspace(1, 0, len(idx), dtype=np.float32)
        if self.v_kill[i] >= 0: x *= np.clip((self.v_kill[i] - np.arange(len(x))) / float(FADE_FR), 0.0, 1.0).astype(np.float32)
        self._tails.append([x * self.v_gl[i], x * self.v_gr[i], 0])

    # ---------- MIDI clock, pitch bend, mod wheel ----------
    def clock_send_on(self): return self.clock_mode == "SEND" and self.midi_out is not None

    def _clock_out(self, clock0, frames, bpb):
        """SEND: 24 MIDI clocks per beat, timed inside this audio block (they run while stopped too, so gear can lock on)"""
        k0, k1 = int(np.ceil(clock0 * 24)), int(np.ceil((clock0 + frames * bpb) * 24))
        for k in range(k0, k1):
            self.midi_out(b"\xf8", max(0.0, (k / 24.0 - clock0) / bpb / OUT_SR))

    def ext_clock(self, t):
        """FOLLOW: one incoming MIDI clock (24 per beat): the tempo follows the average of the last beat"""
        q = self._ext_clock
        q.append(t)
        if len(q) > 49: del q[:-49]
        if len(q) >= 25:
            dt = (q[-1] - q[-25]) / 24.0
            if dt > 0:
                bpm = 60.0 / (dt * 24.0)
                if 30.0 <= bpm <= 300.0:
                    self.ext_bpm = bpm
                    if abs(bpm - self.seq.bpm) > 0.05: self.seq.bpm = round(bpm, 1)

    def pitch_bend(self, v):
        """-1..1: live keyboard notes (KEYS tracks) bend, plug-in instruments get it too"""
        self.bend = max(-1.0, min(1.0, v))
        k = 2.0 ** (self.bend * self.bend_range / 12.0)
        with self.lock:
            for i in range(self.nv):
                if self.v_data[i] is not None and self.v_key[i] is not None and self.v_warp[i] is None: self.v_rate[i] = self.v_rate0[i] * k
        tr = self.track
        inst = self.instruments.get(id(tr))
        if inst is not None and hasattr(inst, "controller"): inst.controller(129, (self.bend + 1) / 2.0)
        if tr.midi_ch and self.midi_out:
            b = int(round((self.bend + 1) / 2.0 * 16383)); b = max(0, min(16383, b))
            self.midi_out(bytes([0xE0 | (tr.midi_ch - 1), b & 127, b >> 7]))

    def mod_wheel(self, v, number=1):
        """mod wheel (CC 1) or aftertouch (number 128), 0..1: sweeps the filter of pads with one on (live), and goes
        to the track's plug-in instrument / MIDI channel"""
        self.mod = max(0.0, min(1.0, v))
        tr = self.track
        inst = self.instruments.get(id(tr))
        if inst is not None and hasattr(inst, "controller"): inst.controller(number, self.mod)
        if tr.midi_ch and self.midi_out:
            ch = tr.midi_ch - 1
            self.midi_out(bytes([0xD0 | ch, int(self.mod * 127)]) if number == 128 else bytes([0xB0 | ch, number & 127, int(self.mod * 127)]))

    @staticmethod
    def voice_env(pad, vel):
        """the envelope / filter settings a voice keeps for its life (None = pad plays plain)"""
        mode = {"LP": 1, "HP": 2, "BP": 3}.get(pad.flt, 0)
        if not (pad.attack or pad.decay or mode): return None
        cut = pad.cutoff + 0.5 * pad.f_vel * (vel / 127.0 - 1.0) if mode else 1.0   # softer hits close the filter (up to half the range)
        return (pad.attack * OUT_SR / 1000.0, pad.decay * OUT_SR / 4000.0, mode, cut, pad.res, pad.f_env,
                max(1.0, pad.f_dec * OUT_SR / 4000.0))

    @staticmethod
    def cut_hz(c):
        return 30.0 * (20000.0 / 30.0) ** min(1.0, max(0.0, c))

    @staticmethod
    def _pan_gains(g, p):
        p = max(-1.0, min(1.0, p))
        return g * min(1.0, 1.0 - p), g * min(1.0, 1.0 + p)

    # ---------- automation (drawn on GRID, or written with the Q-links while recording) ----------
    def auto_targets(self, tr):
        """[(key, label, getter 0-1, setter 0-1)] a track can automate: its level, its pan, and every parameter of the
        insert effects on its program (keys 'vol', 'pan', 'ins<slot>:<param>')"""
        out = [("vol", "Track level", lambda: tr.vol, lambda v: setattr(tr, "vol", v)),
               ("pan", "Track pan", lambda: (tr.pan + 1) / 2.0, lambda v: setattr(tr, "pan", v * 2 - 1))]
        if tr.kind == "drum" or tr.kind == "keys":
            pr = self.programs[tr.prog]
            for k, fx in enumerate(pr.fx):
                if fx is None: continue
                for i in range(fx.n()):
                    out.append((f"ins{k}:{i}", f"Ins {k + 1} {fx.name[:10]} {fx.labels[i][:10]}",
                                lambda fx=fx, i=i: fx.get(i), lambda v, fx=fx, i=i: fx.set(i, v)))
        return out

    def auto_set_point(self, tr, key, tick, value):
        """add or replace one automation point"""
        with self.lock:
            pts = tr.auto.setdefault(key, [])
            tick, value = int(tick), float(min(1.0, max(0.0, value)))
            i = bisect.bisect_left([p[0] for p in pts], tick)
            if i < len(pts) and pts[i][0] == tick: pts[i][1] = value
            else: pts.insert(i, [tick, value])

    def auto_clear(self, tr, key=None):
        with self.lock:
            if key is None: tr.auto = {}
            else: tr.auto.pop(key, None)

    def auto_write(self, tr, key, value):
        """called when a control that is automatable moves: while recording (REC / OVERDUB) and playing, the movement is
        written at the playhead, replacing what was there since the last written point (like a write pass)"""
        if not (self.playing and self.rec != "off" and self.pos >= 0): return False
        t = int(self.pos)
        k = (id(tr), key)
        last = self._auto_touch.get(k)
        with self.lock:
            pts = tr.auto.setdefault(key, [])
            if last is not None and last[0] <= t and time.time() - last[1] < 0.5:
                pts[:] = [p for p in pts if not (last[0] < p[0] <= t)]
            elif last is None or last[0] > t:
                pts[:] = [p for p in pts if not (t <= p[0] <= t + 6)]
        self.auto_set_point(tr, key, t, value)
        self._auto_touch[k] = (t, time.time())
        return True

    def _apply_automation(self, sq, tick):
        """set every automated parameter of the playing sequence to its value at this tick; sounding voices follow
        track level and pan straight away"""
        now = time.time()
        for tr in sq.tracks:
            if not tr.auto: continue
            changed = False
            for key, pts in tr.auto.items():
                if not pts: continue
                t = self._auto_touch.get((id(tr), key))
                if t is not None and now - t[1] < 0.3: continue        # your hand is on that control right now
                v = auto_value(pts, tick)
                if key == "vol":
                    if abs(tr.vol - v) > 1e-6: tr.vol = v; changed = True
                elif key == "pan":
                    v = v * 2 - 1
                    if abs(tr.pan - v) > 1e-6: tr.pan = v; changed = True
                elif key.startswith("ins"):
                    try:
                        k, i = key[3:].split(":"); fx = self.programs[tr.prog].fx[int(k)]
                        if fx is not None and int(i) < fx.n(): fx.set(int(i), v)
                    except (ValueError, IndexError): pass
            if changed:
                for j in range(self.nv):
                    if self.v_trk[j] is tr and self.v_data[j] is not None:
                        g0, pp = self.v_base[j]
                        self.v_gl[j], self.v_gr[j] = self._pan_gains(g0 * tr.vol, pp + tr.pan)

    def release_key(self, key):
        """note-off for a live keyboard note: a short fade instead of a click"""
        with self.lock:
            for i in range(self.nv):
                if self.v_key[i] == key and self.v_data[i] is not None:
                    ovs = self.v_ov[i]
                    if ovs is not None:                            # ASR-10: its envelopes release (ENV1 and the amp's)
                        if ovs[6] is None or ovs[6] > ovs[2]: ovs[6] = ovs[2]
                        if len(ovs) != 9 and self.v_pad[i].a_loop == 4: ovs[0].release(); ovs[3] = -1    # LOOP AND RELEASE: on to the end
                        self.v_key[i] = None; continue
                    self.v_kill[i] = FADE_FR if self.v_kill[i] < 0 else min(self.v_kill[i], FADE_FR)
                    self.v_key[i] = None

    # ---------- WARP: pads that follow the tempo while the sequence plays ----------
    @staticmethod
    def warp_q(bpm): return round(bpm * 2) / 2.0             # renders are made in 0.5 bpm steps; the rest is a tiny speed change

    def guess_bpm(self, pad, near=None):
        """the region's tempo, assuming it is a whole number of beats (1, 2, 4 ... 64) between 60 and 200 bpm"""
        secs = max(1e-3, pad.length / float(OUT_SR)); near = near or self.seq.bpm
        best = None
        for beats in (1, 2, 4, 8, 16, 32, 64):
            b = 60.0 * beats / secs
            if 60 <= b <= 200 and (best is None or abs(b - near) < abs(best - near)): best = b
        return round(best or near, 1)

    def set_warp(self, pad, on):
        pad.warp = bool(on) and not pad.empty
        if pad.warp and not pad.warp_bpm: pad.warp_bpm = self.guess_bpm(pad)
        self._warp_br = None                                          # render it for the tempos in use (next audio block)
        return pad.warp

    def _warp_key(self, pad, bpm_r, semis):
        return (id(pad), pad.pre_key() + (pad.lofi_on, round(pad.warp_bpm, 2), int(pad.stretch)), bpm_r, semis)

    def warp_request(self, pad, bpm_r, semis):
        if pad.empty or not pad.warp_bpm: return
        k = self._warp_key(pad, bpm_r, semis)
        if k in self.warp_cache: return
        with self._warp_cv:
            self._warp_todo[k] = (pad, bpm_r, semis); self._warp_todo.move_to_end(k)
            if self._warp_thread is None:
                self._warp_thread = threading.Thread(target=self._warp_worker, daemon=True); self._warp_thread.start()
            self._warp_cv.notify()

    def _warp_worker(self):
        while True:
            with self._warp_cv:
                while not self._warp_todo: self._warp_cv.wait()
                k, (pad, bpm_r, semis) = self._warp_todo.popitem(last=True)   # newest first: the tempo you are at now
            try:
                if pad.empty or self._warp_key(pad, bpm_r, semis) != k or k in self.warp_cache: continue
                self._warp_render_now(pad, bpm_r, semis)
            except Exception as ex:
                print("warp render failed:", ex)

    def _warp_render_now(self, pad, bpm_r, semis):
        """make one WARP render here and now (the worker thread, or a bounce that cannot wait); returns (data, scale)"""
        k = self._warp_key(pad, bpm_r, semis)
        hit = self.warp_cache.get(k)
        if hit is not None: return hit
        x = pad.pre()
        y = warplib.render(x, int(round(len(x) * pad.warp_bpm / bpm_r * pad.stretch / 100.0)), semis, OUT_SR)
        sc = 1.0
        if pad.lofi_on and len(y) > 4: y, sc = make_lofi(y), RATIO
        data = np.append(y, np.float32(0)).astype(np.float32)
        with self.lock:
            self.warp_cache[k] = (data, sc)
            while len(self.warp_cache) > 64: self.warp_cache.popitem(last=False)
        return data, sc

    def warp_get(self, pad, bpm_r, semis):
        """the best render there is now: this tempo, else the nearest tempo at this pitch, else the plain sample.
        Whatever is missing is rendered in the background and swapped in while the note plays."""
        k = self._warp_key(pad, bpm_r, semis)
        hit = self.warp_cache.get(k)
        if hit is not None:
            self.warp_cache.move_to_end(k); return hit[0], hit[1], bpm_r, semis
        self.warp_request(pad, bpm_r, semis)
        best = None
        for (pid, base, b, s_), v in list(self.warp_cache.items()):
            if pid == k[0] and base == k[1] and s_ == semis and (best is None or abs(b - bpm_r) < abs(best[0] - bpm_r)): best = (b, v)
        if best: return best[1][0], best[1][1], best[0], semis
        data, sc = pad.build()
        return data, sc, pad.warp_bpm, 0

    def _warp_update(self, bpm0):
        """start of each audio block: a new tempo gets new renders, and playing WARP voices cross-fade onto them"""
        br = self.warp_q(bpm0)
        nxt = [self.seq]                                              # the sequence playing, and the one coming next (other tempo?)
        if self.next_seq is not None: nxt.append(self.seqs[self.next_seq])
        if self.song_mode and self.song_pos + 1 < len(self.song): nxt.append(self.seqs[self.song[self.song_pos + 1][0] % NSEQ])
        want = tuple((sq.n, self.warp_q(sq.bpm)) for sq in nxt)
        if want != self._warp_br:                                    # tempo moved: render the WARP pads for it (and for what is next)
            self._warp_br = want
            for sq in reversed(nxt):                                  # requested last = rendered first: the tempo playing now
                for tr in sq.tracks:                                  # KEYGROUP on a WARP pad: every pitch it may be played at
                    kp = self.programs[tr.prog].pads[tr.key_pad] if tr.kind == "keys" else None
                    if kp is not None and kp.warp and not kp.empty:
                        for d in sorted(range(-12, 13), key=abs, reverse=True):
                            self.warp_request(kp, self.warp_q(sq.bpm), round(kp.pitch + d, 2))
                for pr in {tr.prog for tr in sq.tracks}:
                    for p in self.programs[pr].pads:
                        if p.warp and not p.empty: self.warp_request(p, self.warp_q(sq.bpm), round(p.pitch, 2))
        for i in range(self.nv):
            w = self.v_warp[i]
            pad = self.v_pad[i]
            if w is None or w[4] or self.v_data[i] is None: continue
            if w[5] != pad.gen: w[2] = round(pad.pitch + w[6], 2)          # the pad was edited: its pitch may have changed too
            if w[1] == br and w[3] == w[2] and w[5] == pad.gen: continue
            hit = self.warp_cache.get(self._warp_key(pad, br, w[2]))
            if hit is None: self.warp_request(pad, br, w[2]); continue
            j = next((k for k in range(self.nv) if self.v_data[k] is None), None)
            if j is None: continue
            data, sc = hit
            self.v_data[j], self.v_end[j], self.v_pos[j], self.v_rate[j] = data, float(len(data) - 1), 0.0, sc * bpm0 / br
            self.v_gl[j], self.v_gr[j], self.v_pad[j], self.v_age[j] = self.v_gl[i], self.v_gr[i], pad, self.v_age[i]
            self.v_delay[j], self.v_kill[j], self.v_lofi[j], self.v_key[j] = self.v_delay[i], self.v_kill[i], sc != 1.0, self.v_key[i]
            self.v_trk[j], self.v_base[j] = self.v_trk[i], self.v_base[i]
            self.v_warp[j], self.v_fin[j] = [w[0], br, w[2], w[2], False, pad.gen, w[6]], (FADE_FR if self.v_delay[i] == 0 else 0)
            w[4] = True; self.v_key[i] = None                         # the old render fades out under the new one
            if self.v_delay[i] > 0: self.v_data[i], self.v_pad[i], self.v_warp[i] = None, None, None
            else: self.v_kill[i] = FADE_FR if self.v_kill[i] < 0 else min(self.v_kill[i], FADE_FR)

    # ---------- FLATTEN PAD (as on an MPC: bake what you did to a pad into a new sample) ----------
    def flatten_pad(self, pad, tail=3.0):
        """Render the pad as it sounds - region, fades, reverse, normalise, tune, WARP at this tempo, lo-fi, gain and its
        insert effect with the effect's tail - into a new sample, put that on the pad and reset what is now baked in.
        Level, pan, mode, choke and output stay as pad settings. The old sample is kept: unflatten_pad() undoes it."""
        if pad.empty: self.say("nothing to flatten: the pad is empty"); return None
        bpm = self.seq.bpm
        if pad.warp:
            br = self.warp_q(bpm)
            data, sc = self._warp_render_now(pad, br, int(round(pad.tune)))
            rate = sc * bpm / br
        else:
            data, sc = pad.build()
            rate = 2.0 ** (pad.tune / 12.0) * sc
        n = max(1, int((len(data) - 1) / rate))
        x = np.interp(np.arange(n) * rate, np.arange(len(data)), data).astype(np.float32) * np.float32(10.0 ** (pad.gain_db / 20.0))
        if pad.fx is not None and not pad.fx_bypass:                  # a fresh copy of the effect: the live one keeps playing
            try:
                fx = fxlib.from_state(pad.fx.state())
                src_ = np.concatenate([x, np.zeros(int(tail * OUT_SR), np.float32)])
                outl, outr = [], []
                for i in range(0, len(src_), 256):
                    blk = src_[i:i + 256].copy()
                    l_, r_ = fx.process(blk, blk.copy())
                    outl.append(np.asarray(l_, np.float32)); outr.append(np.asarray(r_, np.float32))
                x = 0.5 * (np.concatenate(outl) + np.concatenate(outr))      # samples are mono here: a stereo effect is folded
                loud = np.nonzero(np.abs(x) > 1e-4)[0]
                x = x[: (loud[-1] + 1 if len(loud) else 1)]
            except Exception as ex:
                self.say(f"effect could not be flattened: {str(ex)[:30]}"); return None
        base = (pad.src.name + ("_chop%d" % (pad.link[1] + 1) if pad.link else ""))[:20] + "_flat"
        name, k = base, 2
        while self.source_by_name(name) is not None: name, k = f"{base}{k}", k + 1
        src = self.add_source(name, x.astype(np.float32), dirty=True)
        keep = ("src", "start", "end", "link", "reverse", "norm", "fade_in", "fade_out", "tune", "gain_db", "lofi_on",
                "warp", "warp_bpm", "fx", "fx_bypass")
        undo = {a: getattr(pad, a) for a in keep}
        with self.lock:
            pad.assign(src)
            pad.reverse = pad.norm = False
            pad.fade_in = pad.fade_out = 0
            pad.tune, pad.gain_db, pad.lofi_on = 0, 0.0, False
            pad.warp_bpm = bpm if undo["warp"] else (0.0 if undo["tune"] else undo["warp_bpm"])
            pad.warp = False
            pad.fx, pad.fx_bypass = None, False
            pad._unflat = undo
        self.pad_changed(pad)
        self.say(f"flattened to new sample {name} ({len(x) / OUT_SR:.2f} s)")
        return src

    def unflatten_pad(self, pad):
        undo = getattr(pad, "_unflat", None)
        if not undo: self.say("this pad has not been flattened"); return False
        with self.lock:
            for a, v in undo.items(): setattr(pad, a, v)
            pad._unflat = None
        self.pad_changed(pad); self.say("flatten undone (the flattened sample stays in the sample list)")
        return True

    # ---------- TRACK OUT: every track (and the mix) to its own WAV, faster than real time ----------
    def song_seqs(self, song):
        return [self.seqs[st[0] % NSEQ] for st in self.song] if song else [self.seq]

    def bounce_length(self, song=False):
        """seconds of music in the sequence (or the whole song)"""
        if not song: return self.seq.length / PPQ * 60.0 / self.seq.bpm
        return sum(max(1, st[1]) * self.seqs[st[0] % NSEQ].length / PPQ * 60.0 / self.seqs[st[0] % NSEQ].bpm for st in self.song)

    def bounce_tracks(self, song=False):
        """track numbers worth bouncing: they have notes and make sound inside the sampler (MIDI tracks do not)"""
        out = set()
        for sq in self.song_seqs(song):
            for tr in sq.tracks:
                if tr.events and tr.kind != "midi" and not tr.mute: out.add(tr.n)
        return sorted(out)

    def track_out(self, folder, tracks=None, song=False, mix=True, tail=2.0, progress=None):
        """Bounce each track (track n of every sequence in the song) to `NN name.wav` and the full mix to `00 Mix.wav`,
        stereo 32-bit float, 44.1 kHz. Stems are taken before the master effect / filter / limiter; the mix after them.
        Live audio is silent while this runs (live pad hits are ignored). Returns the files written."""
        tracks = self.bounce_tracks(song) if tracks is None else sorted(tracks)
        os.makedirs(folder, exist_ok=True)
        seqs = self.song_seqs(song)
        if self.playing: self.stop()
        snap = dict(pos=self.pos, playing=False, rec=self.rec, metro=self.metro, song_mode=self.song_mode, song_pos=self.song_pos,
                    song_rep=self.song_rep, cur_seq=self.cur_seq, rep_on=self.rep_on, next_seq=self.next_seq)
        flags = {id(t): (t.mute, t.solo) for sq in seqs for t in sq.tracks}
        jobs = ([("Mix", None)] if mix else []) + [(None, n) for n in tracks]
        files = []
        self._bounce_thread = threading.current_thread()
        self.bouncing = True
        try:
            for sq in seqs:                                              # WARP pads: every render ready before we start
                for tr in sq.tracks:
                    pr = self.programs[tr.prog]
                    if tr.kind == "keys" and pr.pads[tr.key_pad].warp:
                        for nn in {e[1] for e in tr.events}:
                            self._warp_render_now(pr.pads[tr.key_pad], self.warp_q(sq.bpm), int(round(pr.pads[tr.key_pad].tune)) + nn - tr.root)
                    elif tr.kind == "drum":
                        for idx in {e[1] for e in tr.events}:
                            if pr.pads[idx].warp and not pr.pads[idx].empty:
                                self._warp_render_now(pr.pads[idx], self.warp_q(sq.bpm), int(round(pr.pads[idx].tune)))
            total = self.bounce_length(song)
            for j, (label, n) in enumerate(jobs):
                name = label or (seqs[0].tracks[n].name if n is not None else "")
                self.bounce_status = f"{j + 1}/{len(jobs)}  {name}"
                if progress: progress(j, len(jobs), name)
                for sq in seqs:
                    for t in sq.tracks:
                        t.mute, t.solo = (flags[id(t)] if n is None else (t.n != n, False))
                self._bounce_raw = n is not None
                self._bounce_flush()
                self.rec, self.metro, self.rep_on, self.next_seq = "off", False, False, None
                self.pos, self.beat_clock = 0.0, 0.0
                if song: self.song_mode, self.song_pos, self.song_rep, self.cur_seq = True, 0, 0, self.song[0][0] % NSEQ
                else: self.song_mode = False
                self.playing = True
                L, R, done = [], [], 0
                need = int(round(total * OUT_SR))
                while done < need:
                    k = min(256, need - done)
                    o = self._render(k); L.append(o[:, 0].copy()); R.append(o[:, 1].copy()); done += k
                self.playing = False
                for inst in self.instruments.values():
                    for nn in range(128): inst.note(0, nn, 0, False)
                self._note_offs = []
                for _ in range(int(tail * OUT_SR / 256)):                 # the ring-out: reverb / delay tails, long samples
                    o = self._render(256); L.append(o[:, 0].copy()); R.append(o[:, 1].copy())
                fname = "00 Mix.wav" if n is None else f"{n + 1:02d} " + "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip() + ".wav"
                path = os.path.join(folder, fname)
                save_wav_float(path, np.concatenate(L), np.concatenate(R)); files.append(path)
        finally:
            for sq in seqs:
                for t in sq.tracks: t.mute, t.solo = flags[id(t)]
            self._bounce_flush()
            for k_, v in snap.items(): setattr(self, k_, v)
            self._bounce_raw, self.bouncing, self._bounce_thread = False, False, None
            self.bounce_status = ""
        self.say(f"track out: {len(files)} files")
        return files

    def _bounce_flush(self):
        """silence between bounces: no voice, note or effect tail from one file may leak into the next"""
        self.playing = False
        with self.lock:
            for i in range(self.nv): self.v_data[i], self.v_pad[i], self.v_key[i], self.v_warp[i] = None, None, None, None
            self._clicks, self._live_offs = [], []
        for _ in range(int(1.5 * OUT_SR / 256)): self._render(256)

    # ---------- an external keyboard (MIDI) ----------
    def instrument(self, tr):
        """the VST3 instrument of a PLUGIN track (loaded on first use); None if it cannot load"""
        if tr.kind != "plugin" or not tr.plugin: return None
        inst = self.instruments.get(id(tr))
        if inst is not None and getattr(inst, "path", None) == tr.plugin: return inst
        try:
            inst = fxlib.create_instrument(tr.plugin)
            if tr.plugin_state: inst.load_state(tr.plugin_state)
        except Exception as ex:
            self.say(f"could not load {os.path.basename(tr.plugin)}: {str(ex)[:30]}"); tr.kind = "keys"; return None
        self.instruments[id(tr)] = inst
        return inst

    def set_track_kind(self, tr, kind, plugin=None):
        """DRUM / KEYGROUP / PLUGIN / MIDI. Note tracks (all but DRUM) can switch freely; DRUM <-> notes only when empty."""
        if (tr.kind == "drum") != (kind == "drum") and tr.events:
            self.say("clear the track first: pad hits and notes do not convert"); return False
        tr.kind = kind
        if tr.name == f"Track {tr.n + 1:02d}" or tr.name in ("Keys", "MIDI") or (tr.plugin and tr.name == os.path.basename(tr.plugin).replace(".vst3", "")[:12]):
            tr.name = {"keys": "Keys", "midi": "MIDI", "drum": f"Track {tr.n + 1:02d}"}.get(kind, os.path.basename(plugin or tr.plugin).replace(".vst3", "")[:12])
        if kind == "keys" and tr.root < 1: tr.root = 60
        if kind == "midi" and not tr.midi_ch: tr.midi_ch = 1
        if kind == "plugin":
            if plugin: tr.plugin, tr.plugin_state = plugin, None
            self.instruments.pop(id(tr), None)
            if self.instrument(tr) is None: return False
        return True

    def audition(self, note, vel=100, secs=0.35, tr=None):
        """hear one note of a note track (piano roll taps): KEYGROUP pad, PLUGIN synth or MIDI out"""
        tr = tr or self.track
        if tr.kind == "plugin":
            inst = self.instrument(tr)
            if inst: inst.note(0, note, vel, True); self._note_offs.append([int(secs * OUT_SR), inst, note])
        elif tr.kind == "midi":
            ch = (tr.midi_ch or 1) - 1
            self.send_midi(bytes([0x90 | ch, note & 127, vel & 127])); self.send_midi(bytes([0x80 | ch, note & 127, 0]), secs)
        else:
            root = tr.root if tr.kind == "keys" else 60
            self.trigger(self.keys_pad(), vel, 0, secs * OUT_SR, None, semi=note - root, key=("audition", note), hold=True)

    def keys_pad(self):
        """the pad the keyboard plays: the KEYS track's instrument, or else the selected pad"""
        tr = self.track
        return self.prog.pads[tr.key_pad] if tr.kind == "keys" else self.pad

    def sound_note(self, tr, note, vel, on, delay=0):
        """play / release a note on the track's own instrument (KEYGROUP pad, PLUGIN synth, MIDI out)"""
        if self.bouncing and on: return
        if tr.kind == "plugin":
            inst = self.instrument(tr)
            if inst: inst.note(delay, note, vel, on)
        elif tr.kind == "midi":
            ch = (tr.midi_ch or 1) - 1
            self.send_midi(bytes([(0x90 if on else 0x80) | ch, note & 127, vel & 127 if on else 0]), delay / float(OUT_SR))
        elif on:
            root = tr.root if tr.kind == "keys" else 60
            self.trigger(self.keys_pad(), vel, delay, None, None, semi=note - root, key=("live", note))
        else:
            self.release_key(("live", note))

    def key_on(self, note, vel):
        tr = self.track
        self.sound_note(tr, note, vel, True)
        start = None
        if self.playing and self.rec != "off":
            if tr.kind not in NOTE_KINDS:
                if tr.events:
                    self.say("select a KEYS track to record the keyboard"); self.held[note] = (None, vel); return
                tr.kind, tr.key_pad, tr.root = "keys", self.pad_idx, 60          # an empty track becomes a KEYS track
                self.say(f"track {tr.n + 1} is now a KEYS track ({BANKS[self.bank]}{self.sel + 1:02d})")
            start = max(0.0, self.pos)
            with self.lock:                                                  # placed now with a short length, stretched at note-off
                tick = self.qtick(start)
                self._put(tr, tick, note, vel, max(6, QUANT[self.qgrid][1] or 24))
                self._skip[(tr.n, tick, note)] = 1
            start = (tick, start)
        self.held[note] = (start, vel)
        if tr.midi_ch and tr.kind != "midi": self.send_midi(bytes([0x90 | (tr.midi_ch - 1), note & 127, vel & 127]))

    def key_off(self, note):
        tr = self.track
        self.release_key(("live", note))
        if tr.kind in ("plugin", "midi"): self.sound_note(tr, note, 0, False)
        st = self.held.pop(note, None)
        if tr.midi_ch and tr.kind != "midi": self.send_midi(bytes([0x80 | (tr.midi_ch - 1), note & 127, 0]))
        if not st or st[0] is None or tr.kind not in NOTE_KINDS: return
        (tick, t_on), vel = st[0], st[1]
        n = self.seq.length
        dur = (max(0.0, self.pos) - t_on) % n if n else 24
        with self.lock:
            ev = next((e for e in tr.events if e[0] == tick and e[1] == note), None)
            if ev: tr.events.remove(ev)
            self._put(tr, tick, note, vel, max(6, int(round(dur))))

    def send_midi(self, data, delay=0.0):
        if self.midi_out is not None:
            try: self.midi_out(data, delay)
            except Exception: pass

    def playhead(self, pad):
        """Position (in source samples) of the voice playing `pad`, or None. For waveform cursors."""
        for i in range(self.nv):
            if self.v_pad[i] is pad and self.v_data[i] is not None and pad.src is not None:
                f = self.v_pos[i] / max(1.0, self.v_end[i])
                f = 1.0 - f if pad.reverse else f
                return pad.start + f * (pad.end - pad.start)
        return None

    def pad_hit(self, n, vel):
        """A physical/touch pad hit, n = 1..16 in the current bank. Plays now and records if armed."""
        idx = self.bank * 16 + (n - 1)
        self.sel = n - 1
        pad = self.prog.pads[idx]
        self.trigger(pad, vel, 0, self.note_len * self.frames_per_tick())
        if self.rep_on:
            self.rep_pad, self.rep_vel = (None if self.rep_pad == idx else idx), vel
        if self.playing and self.rec != "off" and not self.rep_on:
            self._record_event(idx, vel)

    # ---------- pad modes ----------
    def levels_hit(self, n, vel):
        """16 LEVELS: the 16 pads play one pad (levels_pad) at 16 velocities or 16 tunings"""
        pad = self.prog.pads[self.levels_pad]
        if self.levels_param == "VELOCITY":
            v = max(1, int(round(n * 127 / 16.0)))
            self.trigger(pad, v, 0, self.note_len * self.frames_per_tick())
        else:                                                        # TUNE: pad 9 = the pad's own pitch, -8 .. +7 semitones
            v, semi = vel, n - 9
            self.trigger(pad, v, 0, self.note_len * self.frames_per_tick(), semi=semi, key=("levels", n))
        if self.playing and self.rec != "off" and self.track.kind == "drum":
            self._record_event(self.levels_pad, v)
        return v

    def perform_notes(self, n):
        """PERFORM: the notes pad n (1-16) plays: pads walk up the scale from the key, bottom-left to top-right"""
        steps = SCALES[self.perf_scale][1]
        root = 12 * self.perf_oct + self.perf_root
        def deg(d): return root + 12 * (d // len(steps)) + steps[d % len(steps)]
        d = n - 1
        if CHORDS[self.perf_chord] == "SINGLE": out = [deg(d)]
        elif len(steps) == 12: out = [deg(d) + i for i in ((0, 4, 7) if self.perf_chord == 1 else (0, 4, 7, 10))]
        else: out = [deg(d + i) for i in ((0, 2, 4) if self.perf_chord == 1 else (0, 2, 4, 6))]
        return [max(0, min(127, x)) for x in out]

    def perform_hit(self, n, vel):
        """PERFORM: play (and record) the scale note / chord of pad n on the current track's instrument"""
        notes = self.perform_notes(n)
        gate = int(self.perf_gate * self.frames_per_tick())
        with self.lock:
            for x in notes:
                if x in self.held or any(o[1] == x for o in self._live_offs):
                    self._live_offs = [o for o in self._live_offs if o[1] != x]; self.key_off(x)
                self.key_on(x, vel)
                self._live_offs.append([gate, x])
        return notes

    def toggle_track_mute(self, n):
        """TRACK MUTE: pad n mutes / unmutes track n of the sequence"""
        tr = self.seq.tracks[(n - 1) % NTRACK]
        tr.mute = not tr.mute
        self.say(f"{tr.name}: {'muted' if tr.mute else 'on'}")
        return tr.mute

    def queue_seq(self, i):
        """NEXT SEQ: stopped = switch now; playing = switch when this sequence reaches its end (tap again to cancel)"""
        i %= NSEQ
        if not self.playing:
            self.select_seq(i); self.next_seq = None; self.say(f"sequence {i + 1:02d}"); return
        if i == self.cur_seq or self.next_seq == i:
            self.next_seq = None; self.say("next sequence: cancelled")
        else:
            self.next_seq = i; self.say(f"next: sequence {i + 1:02d} (at the end of this one)")

    # ---------- transport / sequencer ----------
    def frames_per_tick(self): return 60.0 / self.seq.bpm / PPQ * OUT_SR

    def _tick_pos(self):
        return self.pos

    def play(self, from_start=False):
        if self.playing and not from_start:
            return
        if from_start or self.pos >= self.seq.length: self.pos = 0.0
        if self.rec != "off" and self.count_in and self.pos == 0.0:
            self.pos = -float(self.count_in * self.seq.bar_ticks)
        if self.rec != "off": self.begin_edit()
        if self.rec == "rec": self._replace_pending = True
        if self.clock_send_on():                                     # MIDI clock master: start, or continue from here
            if self.pos <= 0: self.midi_out(b"\xfa")
            else:
                spp = int(self.pos // (PPQ // 4)); self.midi_out(bytes([0xF2, spp & 127, (spp >> 7) & 127])); self.midi_out(b"\xfb")
        self.playing = True
        self.song_rep = 0
        self._skip.clear()

    def stop(self):
        if self.pending_mute: self._apply_pending_mutes()
        if self.playing:
            self.playing = False
            if self.clock_send_on(): self.midi_out(b"\xfc")
            self.rep_pad = None
            self._skip.clear()
            self.save_project() if self.rec == "off" else None
            for inst in self.instruments.values():                   # silence hanging synth notes
                for n_ in range(128): inst.note(0, n_, 0, False)
            self._note_offs = []
            for o in self._live_offs: self.key_off(o[1])
            self._live_offs, self.next_seq = [], None
            if self.rec != "off": self.rec = "off"
        else:
            self.pos = 0.0; self.rep_pad = None                   # second press: back to the start

    def play_start(self):
        self.playing = False
        self.play(from_start=True)

    def toggle_play(self):
        self.stop() if self.playing else self.play()

    def set_rec(self, mode, start=False):
        """mode 'rec' | 'over'; pressing again turns it off. start=True also starts the transport."""
        self.rec = "off" if self.rec == mode else mode
        if self.rec != "off":
            if self.playing: self.begin_edit(); self._replace_pending = self.rec == "rec"
            elif start: self.play()
        self.say({"off": "record off", "rec": "RECORD (replaces)", "over": "OVERDUB"}[self.rec])

    def locate(self, tick):
        self.pos = float(max(0, min(self.seq.length - 1, tick)))

    @property
    def timing(self):
        """the sequencer's timing model follows the machine: MPC60 / MPC3000 = Linn timing, everything else MODERN
        (the MPC2000XL and SP-1200 timing are not worked out yet)"""
        if self.machine in ("MPC60", "MPC3000"): return "MPC60"
        return {"SP-1200": "SP", "ASR-10": "ASR"}.get(self.machine, "MODERN")

    @timing.setter
    def timing(self, v):
        if v == "MPC60": self.machine = "MPC60" if self.machine not in ("MPC60", "MPC3000") else self.machine
        elif self.machine in ("MPC60", "MPC3000"): self.machine = "MODERN"

    # ---------- Linn timing (MPC60 / MPC3000): worked out from their firmware, written as our own code ----------
    @staticmethod
    def linn_grid(g, swing):
        """(step, pair, swung) in ticks. Swing only exists for 1/8 and 1/16 (other values play straight); the second note of
        each pair sits at step x swing% / 50, rounded to the nearest tick (half up)."""
        pct = int(round(swing * 100)) if g in (48, 24) else 50
        pct = max(50, min(75, pct))
        return g, 2 * g, (g * pct + 25) // 50

    @classmethod
    def linn_shift_max(cls, g, swing):
        """'shift timing' may move the grid by up to half the gap after the swung note, less one tick"""
        step, pair, s = cls.linn_grid(g, swing)
        return max(0, (pair - s) // 2 - 1)

    @classmethod
    def linn_snap(cls, t, g, swing, shift=0):
        """the nearest swung grid point: the change-over sits halfway between neighbouring grid points (a tick exactly on
        it goes to the later point)"""
        step, pair, s = cls.linn_grid(g, swing)
        x = t - shift
        k = int(np.floor(x / float(pair)))
        r = x - k * pair
        b1 = s // 2
        q = 0 if r < b1 else (s if r < b1 + step else pair)
        return k * pair + q + shift

    @classmethod
    def linn_points(cls, t0, t1, g, swing, shift=0):
        """swung grid points in [t0, t1): where an MPC60 fires NOTE REPEAT"""
        step, pair, s = cls.linn_grid(g, swing)
        k = int(np.floor((t0 - shift) / float(pair))) - 1
        out = []
        while k * pair + shift < t1:
            for q in (0, s):
                t = k * pair + q + shift
                if t0 <= t < t1: out.append(t)
            k += 1
        return out

    # ---------- SP-1200 timing (firmware 1.04): 24 ticks a quarter, six swing steps, straight note repeat ----------
    @staticmethod
    def asr_snap(t, g):
        """ASR-10 QUANTIZE TRACK: to the nearest step; a note exactly half-way goes to the EARLIER step (its ROM routine
        compares the remainder with half the step and rounds down when it is not larger). No swing, no strength."""
        t = int(round(t)); q, r = divmod(t, g)
        return q * g if r <= g // 2 else (q + 1) * g

    @staticmethod
    def sp_swing_k(swing):
        """the nearest of the SP's six swing settings, as 0-5 (= 24ths of a pair the off-beat is late)"""
        return min(range(6), key=lambda k: abs(SP_SWINGS[k] / 100.0 - swing))

    @classmethod
    def sp_grid(cls, g, swing):
        """(step, pair, swung) in our ticks. Swing moves the second note of each 1/8 or 1/16 pair late by k/24 of the pair:
        12/24 = 50%, 13/24 = 54%, ... 17/24 = 71%"""
        k = cls.sp_swing_k(swing) if g in (48, 24) else 0
        return g, 2 * g, g + k * (2 * g) // 24

    @classmethod
    def sp_snap(cls, t, g, swing):
        """auto-correct: to the nearest point of the (swung) grid; with auto-correct off the SP still only has 24 ticks a
        quarter, so notes land on that (HiRes) grid"""
        if not g: g = 4
        if g < 24 or g % 24 and g not in (48, 96):                       # triplets, 1/32, HiRes: no swing
            return int(np.floor(t / float(g) + 0.5)) * g
        step, pair, s = cls.sp_grid(g, swing)
        k = int(np.floor(t / float(pair))); r = t - k * pair
        b1 = s / 2.0
        q = 0 if r < b1 else (s if r < (s + pair) / 2.0 else pair)
        return k * pair + q

    def shift_ticks(self, g=None):
        g = g or QUANT[self.qgrid][1] or 24
        m = self.linn_shift_max(g, self.seq.swing)
        return max(-m, min(m, self.tc_shift))

    def qtick(self, t):
        g = QUANT[self.qgrid][1]
        if g and self.timing == "MPC60": t = self.linn_snap(t, g, self.seq.swing, self.shift_ticks(g))   # on unless OFF
        elif self.timing == "SP": t = self.sp_snap(t, SP_CORRECT[self.sp_ac][1], self.seq.swing)           # always on its grid
        elif self.timing == "ASR": t = int(t)                       # ASR-10: recorded as played, on its 96-a-quarter clock
        elif self.rec_quant and g: t = round(t / g) * g
        else: t = round(t)
        n = self.seq.length
        return int(t) % n if n else 0

    def _record_event(self, idx, vel, tick=None):
        t = self.pos if tick is None else tick
        if t < 0: t = 0
        tick = self.qtick(t)
        tr = self.track
        with self.lock:
            self._put(tr, tick, idx, vel, self.note_len)
            self._skip[(tr.n, tick, idx)] = 1

    @staticmethod
    def _put(track, tick, pad, vel, dur):
        ev = track.events
        i = bisect.bisect_left(ev, (tick,))
        while i < len(ev) and ev[i][0] == tick:
            if ev[i][1] == pad: ev.pop(i); break
            i += 1
        bisect.insort(ev, (int(tick), int(pad), int(vel), int(dur)))

    # --- editing (all undoable via begin_edit) ---
    def _snap(self, si):
        """undo step: a sequence's notes, automation, length and time signature"""
        q = self.seqs[si]
        return (si, {"bars": q.bars, "num": q.num, "den": q.den,
                     "tracks": [(list(t.events), {k: [list(p) for p in v] for k, v in t.auto.items()}) for t in q.tracks]})

    def _restore(self, snap):
        si, st = snap
        q = self.seqs[si]
        with self.lock:
            q.bars, q.num, q.den = st["bars"], st["num"], st["den"]
            for t, (ev, au) in zip(q.tracks, st["tracks"]): t.events, t.auto = list(ev), {k: [list(p) for p in v] for k, v in au.items()}

    def begin_edit(self):
        self.undo_stack.append(self._snap(self.cur_seq)); del self.undo_stack[:-30]
        self.redo_stack.clear(); self._undone = False

    def undo(self):
        if not self.undo_stack:
            self.say("nothing to undo"); return False
        snap = self.undo_stack.pop()
        self.redo_stack.append(self._snap(snap[0]))
        self._restore(snap)
        self.say("undo"); return True

    def redo(self):
        if not self.redo_stack:
            self.say("nothing to redo"); return False
        snap = self.redo_stack.pop()
        self.undo_stack.append(self._snap(snap[0]))
        self._restore(snap)
        self.say("redo"); return True

    def undo_toggle(self):
        """The UNDO key: undo, press again to redo (like UNDO SEQ on an MPC)."""
        if not self._undone:
            if self.undo(): self._undone = True
            return self._undone
        if self.redo(): self._undone = False
        return True

    def add_note(self, tick, pad, vel=100, dur=None, track=None):
        tr = track or self.track
        with self.lock:
            self._put(tr, int(tick) % max(1, self.seq.length), pad, vel, dur or self.note_len)

    def find_note(self, tick, pad, tol=0, track=None):
        tr = track or self.track
        with self.lock:
            for ev in tr.events[bisect.bisect_left(tr.events, (tick - tol,)):]:
                if ev[0] > tick + tol: break
                if ev[1] == pad: return ev
        return None

    def remove_note(self, ev, track=None):
        tr = track or self.track
        with self.lock:
            if ev in tr.events: tr.events.remove(ev); return True
        return False

    def toggle_note(self, tick, pad, vel=100, dur=None):
        ev = self.find_note(tick, pad)
        if ev: self.remove_note(ev); return False
        self.add_note(tick, pad, vel, dur); return True

    def erase_pad_events(self, pad_idx, track=None):
        tr = track or self.track
        self.begin_edit()
        with self.lock: tr.events = [e for e in tr.events if e[1] != pad_idx]

    def clear_track(self, track=None):
        tr = track or self.track
        self.begin_edit()
        with self.lock: tr.events = []

    def clear_sequence(self):
        self.begin_edit()
        with self.lock:
            for t in self.seq.tracks: t.events = []

    def quantize_track(self, grid=None, strength=1.0, track=None, swing=0.5, all_tracks=False):
        """move notes towards the grid: strength 0-1 (1 = right onto it), swing 0.5-0.75 pushes every second grid
        step later (0.5 = straight, 0.66 = triplet feel), like an MPC's TIMING CORRECT"""
        g = grid if grid is not None else QUANT[self.qgrid][1]
        if not g:
            self.say("quantize is OFF"); return 0
        self.begin_edit()
        n = self.seq.length
        count = 0
        linn = self.timing == "MPC60"
        sh = self.shift_ticks(g) if linn else 0
        with self.lock:
            for tr in (self.seq.tracks if all_tracks else [track or self.track]):
                out = []
                for t, p, v, d in tr.events:
                    if linn: q = self.linn_snap(t, g, swing, sh)                 # MPC60 "Move Existing Notes"
                    elif self.timing == "SP": q = self.sp_snap(t, g, swing)
                    elif self.timing == "ASR": q = self.asr_snap(t, g)      # its QUANTIZE TRACK (no swing)
                    else:
                        k = int(round(t / float(g)))
                        q = k * g + (int(round((swing - 0.5) * 2 * g)) if k % 2 else 0)
                    nt = int(round(t + (q - t) * strength)) % n
                    out.append((nt, p, v, d))
                tr.events = []
                for ev in sorted(out): self._put(tr, *ev)
                count += len(out)
        self.say(f"quantized {count} notes")
        return count

    def nudge(self, ticks, track=None, all_tracks=False, note=None):
        """move notes earlier (-) or later (+) by some ticks (96 per beat); note = just that one (tick, pad, vel, len)"""
        n = self.seq.length
        self.begin_edit()
        with self.lock:
            if note is not None:
                tr = track or self.track
                if note in tr.events:
                    tr.events.remove(note)
                    moved = ((note[0] + ticks) % n,) + tuple(note[1:])
                    tr.events = sorted(tr.events + [moved])
                    return moved
                return None
            for tr in (self.seq.tracks if all_tracks else [track or self.track]):
                tr.events = sorted(((t + ticks) % n, p, v, d) for t, p, v, d in tr.events)
        self.say(f"notes moved {ticks:+d} ticks")

    def copy_bars(self, src_bar, dst_bar, nbars=1, track=None, times=1, merge=False, all_tracks=False, grow=False):
        """Copy nbars bars from src_bar to dst_bar (0-based), `times` times end to end. Replaces what is there (merge=False)
        or adds to it. all_tracks: every track of the sequence (with automation); grow: lengthen the sequence to fit."""
        sq = self.seq
        bt = sq.bar_ticks
        self.begin_edit()
        if grow: sq.bars = max(sq.bars, min(MAX_BARS, dst_bar + nbars * times))
        n = sq.length
        tracks = sq.tracks if all_tracks else [track or self.track]
        count = 0
        with self.lock:
            for tr in tracks:
                src = [e for e in tr.events if src_bar * bt <= e[0] < (src_bar + nbars) * bt]
                srca = {k: [p for p in v if src_bar * bt <= p[0] < (src_bar + nbars) * bt] for k, v in tr.auto.items()}
                for r in range(times):
                    d0 = (dst_bar + r * nbars) * bt
                    if not merge:
                        tr.events = [e for e in tr.events if not (d0 <= e[0] < d0 + nbars * bt)]
                        for k in tr.auto: tr.auto[k] = [p for p in tr.auto[k] if not (d0 <= p[0] < d0 + nbars * bt)]
                    for t, p, v, d in src:
                        nt = t - src_bar * bt + d0
                        if 0 <= nt < n: self._put(tr, nt, p, v, d); count += 1
                    for k, pts in srca.items():
                        tr.auto[k] = sorted(tr.auto[k] + [[p[0] - src_bar * bt + d0, p[1]] for p in pts if p[0] - src_bar * bt + d0 < n])
        return count

    def insert_bars(self, at_bar, nbars=1):
        """make room: everything from at_bar on moves later by nbars (the sequence gets longer)"""
        sq = self.seq
        room = MAX_BARS - sq.bars
        if room <= 0: self.say(f"a sequence holds {MAX_BARS} bars at most"); return 0
        nbars = max(1, min(int(nbars), room))
        self.begin_edit()
        bt, a = sq.bar_ticks, at_bar * sq.bar_ticks
        with self.lock:
            sq.bars += nbars
            for tr in sq.tracks:
                tr.events = sorted((t + nbars * bt if t >= a else t, p, v, d) for t, p, v, d in tr.events)
                for k in tr.auto: tr.auto[k] = [[p[0] + nbars * bt if p[0] >= a else p[0], p[1]] for p in tr.auto[k]]
        self.say(f"{nbars} bar{'s' if nbars > 1 else ''} inserted at bar {at_bar + 1}")
        return nbars

    def delete_bars(self, at_bar, nbars=1):
        """remove bars at_bar .. at_bar+nbars-1 from every track; what follows moves up (the sequence gets shorter)"""
        sq = self.seq
        nbars = max(1, min(int(nbars), sq.bars - at_bar, sq.bars - 1))
        if at_bar >= sq.bars or sq.bars <= 1: self.say("a sequence keeps at least one bar"); return 0
        self.begin_edit()
        bt = sq.bar_ticks
        a, b = at_bar * bt, (at_bar + nbars) * bt
        with self.lock:
            for tr in sq.tracks:
                tr.events = sorted((t - (b - a) if t >= b else t, p, v, d) for t, p, v, d in tr.events if not (a <= t < b))
                for k in tr.auto: tr.auto[k] = [[p[0] - (b - a) if p[0] >= b else p[0], p[1]] for p in tr.auto[k] if not (a <= p[0] < b)]
            sq.bars -= nbars
            if self.pos >= sq.length: self.pos = 0.0
        self.say(f"bars {at_bar + 1}-{at_bar + nbars} deleted")
        return nbars

    def set_timesig(self, num, den):
        """time signature of the sequence: notes keep their place in ticks, bars get longer or shorter"""
        num, den = max(1, min(16, int(num))), int(den) if int(den) in (2, 4, 8, 16) else 4
        self.begin_edit()
        with self.lock:
            self.seq.num, self.seq.den = num, den
            if self.pos >= self.seq.length: self.pos = 0.0
        self.say(f"time signature {num}/{den}")

    def copy_sequence(self, src, dst):
        """sequence src over sequence dst: everything (tracks, notes, automation, tempo, length)"""
        if src == dst: return
        a, b = self.seqs[src % NSEQ], self.seqs[dst % NSEQ]
        with self.lock:
            b.name = (a.name + " copy")[:16]
            b.bars, b.num, b.den, b.bpm, b.swing, b.loop = a.bars, a.num, a.den, a.bpm, a.swing, a.loop
            for ta, tb in zip(a.tracks, b.tracks): self._copy_track_into(ta, tb)
        self.say(f"sequence {src + 1:02d} copied to {dst + 1:02d}")

    def _copy_track_into(self, ta, tb, name=True):
        if name: tb.name = ta.name
        tb.prog, tb.mute, tb.solo, tb.vol, tb.pan = ta.prog, ta.mute, ta.solo, ta.vol, ta.pan
        tb.events = list(ta.events)
        tb.kind, tb.key_pad, tb.root, tb.midi_ch = ta.kind, ta.key_pad, ta.root, ta.midi_ch
        tb.plugin = ta.plugin
        inst = self.instruments.get(id(ta))
        tb.plugin_state = inst.state() if inst is not None else ta.plugin_state
        self.instruments.pop(id(tb), None)
        tb.auto = {k: [list(p) for p in v] for k, v in ta.auto.items()}

    def copy_track(self, src, dst):
        """track src over track dst in this sequence (notes, automation, what it plays)"""
        if src == dst: return
        self.begin_edit()
        with self.lock: self._copy_track_into(self.seq.tracks[src % NTRACK], self.seq.tracks[dst % NTRACK], name=False)
        self.seq.tracks[dst % NTRACK].name = (self.seq.tracks[src % NTRACK].name + "+")[:12]
        self.say(f"track {src + 1} copied to track {dst + 1}")

    def copy_pad(self, src_pad, dst_pad):
        """every setting and the sample of one pad onto another (its own insert effect too)"""
        if src_pad is dst_pad: return
        st = src_pad.state()
        with self.lock:
            dst_pad.src, dst_pad.start, dst_pad.end = src_pad.src, src_pad.start, src_pad.end
            self._load_pad(dst_pad, st)
            if not st.get("fx"): dst_pad.fx, dst_pad.fx_bypass = None, False
            self.pad_changed(dst_pad)
        self.say("pad copied")

    def set_bars(self, n):
        self.seq.bars = max(1, min(MAX_BARS, int(n)))
        if self.pos >= self.seq.length: self.pos = 0.0

    def select_seq(self, i):
        self.cur_seq = i % NSEQ
        self.pos = 0.0; self.undo_stack.clear(); self.redo_stack.clear()

    def set_swing(self, s):
        self.seq.swing = max(0.5, min(0.75, s))

    # --- song ---
    def song_add(self, seq=None, reps=1):
        self.song.append([self.cur_seq if seq is None else seq, reps])

    def song_play(self):
        self.song_mode, self.song_pos, self.song_rep = True, 0, 0
        self.cur_seq = self.song[0][0]; self.pos = 0.0
        self.playing = False; self.play(from_start=True)

    def _song_next(self):
        """Called when a sequence reaches its end in song mode. Returns True to keep playing."""
        self.song_rep += 1
        if self.song_rep >= max(1, self.song[self.song_pos][1]):
            self.song_rep = 0; self.song_pos += 1
            if self.song_pos >= len(self.song):
                self.song_mode = False; self.song_pos = 0
                return False
            self.cur_seq = self.song[self.song_pos][0]
        return True

    # --- erase / note repeat during playback ---
    def erase_hold(self, down, pad_idx=None):
        self.erasing, self.erase_pad = down, pad_idx
        if down and self.playing: self.begin_edit()

    def _swing_off(self, tick, sq):
        if self.timing in ("MPC60", "SP", "ASR"): return 0.0  # MPC60 / SP-1200: swing goes into the notes as they are recorded; ASR-10: none
        if sq.swing > 0.5 and tick % 48 == 24:
            return (sq.swing - 0.5) * 48.0
        return 0.0

    def _fire_events(self, sq, t0, t1, foff, tpf):
        """Schedule the events of every track with effective tick in [t0, t1)."""
        any_solo = any(t.solo for t in sq.tracks)
        solo_prog = {}
        maxoff = 12.0
        for tr in sq.tracks:
            if not tr.events: continue
            if self.erasing and tr is self.track:
                tr.events = [e for e in tr.events if not (t0 <= e[0] < t1 and (self.erase_pad is None or e[1] == self.erase_pad))]
            if tr.mute or (any_solo and not tr.solo): continue
            pr = self.programs[tr.prog]
            lo = bisect.bisect_left(tr.events, (int(t0 - maxoff),))
            for ev in tr.events[lo:]:
                t = ev[0]
                if t > t1: break
                eff = t + self._swing_off(t, sq)
                if not (t0 <= eff < t1): continue
                key = (tr.n, t, ev[1])
                if key in self._skip:
                    del self._skip[key]; continue
                delay = int(foff + (eff - t0) / tpf)
                if tr.kind == "plugin":                                        # VST3 instrument: note-on now, note-off later
                    inst = self.instrument(tr)
                    if inst is not None:
                        inst.note(delay, ev[1], ev[2], True)
                        self._note_offs.append([delay + int(ev[3] * self.frames_per_tick()), inst, ev[1]])
                    self.track_meter[tr.n] = max(self.track_meter[tr.n], ev[2] / 127.0 * tr.vol)
                if tr.midi_ch or tr.kind == "midi":                            # external instrument on MIDI out
                    ch = (tr.midi_ch or 1)
                    note = ev[1] if tr.kind in NOTE_KINDS else 36 + ev[1]
                    secs = delay / float(OUT_SR)
                    self.send_midi(bytes([0x90 | (ch - 1), note & 127, ev[2] & 127]), secs)
                    self.send_midi(bytes([0x80 | (ch - 1), note & 127, 0]), secs + ev[3] * self.frames_per_tick() / OUT_SR)
                if tr.kind in ("plugin", "midi"):
                    if tr.kind == "midi": self.track_meter[tr.n] = max(self.track_meter[tr.n], ev[2] / 127.0 * tr.vol)
                    continue
                if tr.kind == "keys":
                    pad = pr.pads[tr.key_pad]
                    self.trigger(pad, ev[2], delay, ev[3] * self.frames_per_tick(), tr, semi=ev[1] - tr.root, key=("seq", tr.n, t, ev[1]), hold=True)
                    self.track_meter[tr.n] = max(self.track_meter[tr.n], ev[2] / 127.0 * tr.vol)
                    continue
                pad = pr.pads[ev[1]]
                if tr.prog not in solo_prog: solo_prog[tr.prog] = any(p.solo for p in pr.pads)
                if solo_prog[tr.prog] and not pad.solo: continue
                self.trigger(pad, ev[2], delay, ev[3] * self.frames_per_tick(), tr)
                self.track_meter[tr.n] = max(self.track_meter[tr.n], ev[2] / 127.0 * tr.vol)

    def _fire_repeat(self, t0, t1, foff, tpf, record):
        if self.rep_pad is None or not self.rep_on: return
        g = self.rep_div
        if self.timing == "MPC60":                           # MPC60: repeats land on the swung grid
            ticks = self.linn_points(t0, t1, g, self.seq.swing, self.shift_ticks(g))
        elif self.timing == "SP":                            # SP-1200: straight, on the auto-correct step (its clock routine)
            g = SP_CORRECT[self.sp_ac][1] or g
            k = int(np.ceil(t0 / g - 1e-9)); ticks = []
            while k * g < t1: ticks.append(k * g); k += 1
        else:
            k = int(np.ceil(t0 / g - 1e-9)); ticks = []
            while k * g < t1: ticks.append(k * g); k += 1
        for t in ticks:
            pad = self.prog.pads[self.rep_pad]
            self.trigger(pad, self.rep_vel, int(foff + (t - t0) / tpf), g * self.frames_per_tick())
            if record and t >= 0:
                tt = int(t) % max(1, self.seq.length)
                self._put(self.track, tt, self.rep_pad, self.rep_vel, g); self._skip[(self.track.n, tt, self.rep_pad)] = 1

    def _click(self, accent, delay):
        self._clicks.append([CLICK_HI if accent else CLICK_LO, 0, int(delay)])

    def _advance(self, frames, L, R):
        tpf = self.seq.bpm * PPQ / 60.0 / OUT_SR          # ticks per frame
        t0, left, foff, guard = self.pos, float(frames), 0.0, 0
        while left > 0.5 and self.playing and guard < 6:
            guard += 1
            sq = self.seq
            n = sq.length
            seg_end = min(t0 + left * tpf, 0.0 if t0 < 0 else float(n))
            if self.pending_mute and t0 >= 0:                    # ON NEXT BAR mutes: stop at the bar line, switch, go on
                bt = sq.bar_ticks
                seg_end = min(seg_end, (np.floor(t0 / bt + 1e-9) + 1) * bt)
            if seg_end > t0:
                if t0 >= 0:
                    self._apply_automation(sq, t0)
                    self._fire_events(sq, t0, seg_end, foff, tpf)
                    self._fire_repeat(t0, seg_end, foff, tpf, self.rec != "off")
                if self.metro or t0 < 0:
                    bt = sq.beat_ticks
                    k = int(np.ceil(t0 / bt - 1e-9))
                    while k * bt < seg_end:
                        self._click(k % sq.num == 0, foff + (k * bt - t0) / tpf); k += 1
                used = (seg_end - t0) / tpf
                left -= used; foff += used; t0 = seg_end
                if self.pending_mute and t0 >= 0 and abs(t0 / sq.bar_ticks - round(t0 / sq.bar_ticks)) < 1e-6:
                    self._apply_pending_mutes(); guard -= 1
            if t0 >= n:                                      # end of the sequence
                self.pass_count += 1; self._skip.clear()
                if self.next_seq is not None and not self.song_mode:  # NEXT SEQ pad mode
                    self.cur_seq, self.next_seq = self.next_seq, None
                    self.undo_stack.clear(); self.redo_stack.clear()
                    t0 = 0.0; continue
                if self.song_mode:
                    if not self._song_next():
                        self.playing = False; t0 = 0.0; break
                    t0 = 0.0
                elif sq.loop:
                    t0 = 0.0
                else:
                    self.playing = False; self.rec = "off"; t0 = 0.0; break
        self.pos = t0

    # ---------- input recording (sampling) ----------
    def rec_toggle(self):
        if self.rec_state == "idle":
            if self.rec_src == "INPUT" and not self.has_input:
                self.say("no audio input found (RESAMPLE records the sampler's own output)"); return
            self.rec_buf, self.rec_len, self.rec_peaks, self._pre = [], 0, [], []
            self.rec_state = "armed"
            return
        was = self.rec_state
        self.rec_state = "idle"
        if not self.rec_buf:
            self.say("nothing recorded" if was == "rec" else "disarmed"); return
        x = np.concatenate(self.rec_buf)
        loud = np.where(np.abs(x) > 0.01)[0]
        if len(loud) == 0:
            self.say("nothing recorded"); return
        if self.rec_trim: x = x[max(0, loud[0] - int(self.rec_preroll * OUT_SR / 1000.0)):]
        pk = float(np.abs(x).max()) or 1.0
        if self.rec_norm: x = x * (0.95 / pk)
        n, base = 1, "resample" if self.rec_src == "RESAMPLE" else "rec"
        while self.source_by_name(f"{base}_{n:03d}"): n += 1
        src = self.add_source(f"{base}_{n:03d}", x.astype(np.float32), dirty=True)   # into the project's samples: on no pad
        self.last_take = src
        self.say(f"recorded {src.name} ({len(x) / OUT_SR:.2f} s): KEEP opens it in CHOP")

    def rec_keep(self):
        """KEEP: the take stays in the project's samples (returned, for CHOP)"""
        if self.last_take is None: self.say("no new take"); return None
        src, self.last_take = self.last_take, None
        self.say(f"{src.name} kept"); return src

    def rec_discard(self):
        """DISCARD: the take is gone from the project's samples (nothing else was touched)"""
        if self.last_take is None: self.say("no new take"); return
        src, self.last_take = self.last_take, None
        with self.lock:
            if self.sources and self.sources[-1] is src and not any(p.src is src for p in self.all_pads()):
                self.sources.pop()
        self.say("take discarded")

    def set_track_mute(self, tr, on):
        """mute / unmute a track and the tracks in its mute group; with MUTE > ON NEXT BAR while playing it happens on the
        next bar line"""
        group = [t for t in self.seq.tracks if t is tr or (tr.mgroup and t.mgroup == tr.mgroup)]
        for t in group:
            if self.mute_quant and self.playing: self.pending_mute[t.n] = on
            else: t.mute = on; self.pending_mute.pop(t.n, None)

    def _apply_pending_mutes(self):
        for n, on in self.pending_mute.items(): self.seq.tracks[n].mute = on
        self.pending_mute = {}

    def feed_input(self, indata):
        self.has_input = True
        g = 10 ** (self.in_gain_db / 20.0)
        two = indata.ndim > 1 and indata.shape[1] > 1
        l_ = (indata[:, 0] if indata.ndim > 1 else indata) * g
        r_ = indata[:, 1] * g if two else l_
        self.in_meter_lr = [max(float(np.abs(l_).max()) if len(l_) else 0.0, self.in_meter_lr[0] * 0.92),
                            max(float(np.abs(r_).max()) if len(r_) else 0.0, self.in_meter_lr[1] * 0.92)]
        self._in_block = (l_, r_)
        if self.rec_src != "INPUT": return
        x = {"1": l_, "2": r_}.get(self.rec_in, (l_ + r_) * 0.5 if two else l_)   # IN 1 + 2 mixed to mono, or one input
        self._feed_rec(np.asarray(x, np.float32))

    def _feed_rec(self, x):
        """the recorder: waits (armed) until the level passes the threshold, then keeps everything until REC is pressed again"""
        pk = float(np.abs(x).max()) if len(x) else 0.0
        self.in_meter = max(pk, self.in_meter * 0.92)
        if self.rec_state == "armed":
            self._pre.append(x.copy())
            keep = int(self.rec_preroll * OUT_SR / 1000.0) + len(x)
            while len(self._pre) > 1 and sum(len(b) for b in self._pre[1:]) >= keep: self._pre.pop(0)
            if pk >= self.rec_thresh:
                self.rec_state = "rec"
                self.rec_buf = self._pre[:-1]; self._pre = []                # the pre-roll, then this block
                self.rec_len = sum(len(b) for b in self.rec_buf)
        if self.rec_state == "rec":
            self.rec_buf.append(x.copy()); self.rec_len += len(x); self.rec_peaks.append(pk)
            if self.rec_max and self.rec_len >= self.rec_max * OUT_SR:
                self.rec_toggle()

    # ---------- non-destructive chop ----------
    MIN_GAP = int(0.01 * OUT_SR)

    def _clean(self, src):
        src.slices = None                               # a new detection: slices go back to sitting between markers
        src.chops = sorted({int(c) for c in src.chops if self.MIN_GAP <= c <= src.length - self.MIN_GAP})
        self.relink(src)

    def chop_equal(self, src, n):
        n = max(1, int(n))
        src.chops = [int(src.length * i / n) for i in range(1, n)]
        self._clean(src); return len(src.regions())

    def chop_beats(self, src, bpm, div=4, offset=0):
        """Markers on a beat grid: div 4 = quarter notes, 8 = eighths, 16 = sixteenths."""
        step = 60.0 / bpm * OUT_SR * 4.0 / div
        src.chops = [int(offset + k * step) for k in range(1, int(max(0, src.length - offset) / step) + 1)]
        self._clean(src); return len(src.regions())

    def detect_transients(self, src, sens=0.5):
        """Onset positions (sample indices) from a smoothed energy envelope. sens 0..1: higher = more markers."""
        x = np.abs(src.raw)
        if len(x) < 2000: return []
        hop = 128
        env = np.convolve(x, np.ones(256, np.float32) / 256, mode="same")[::hop]
        db = np.log(env + 1e-4)
        d = np.diff(db, prepend=db[0])
        peak = float(env.max())
        thr = 0.9 - 0.8 * sens                          # needed rise in log-energy
        gap = int(0.06 * OUT_SR / hop)
        out, last = [], -gap
        for i in range(1, len(d)):
            if d[i] > thr and env[i] > 0.04 * peak and i - last >= gap:
                j = i                                  # walk back to where the rise begins
                while j > 0 and d[j - 1] > 0.1 * thr and i - j < 12: j -= 1
                out.append(max(0, j) * hop); last = i
        return [p for p in out if p > self.MIN_GAP]

    def chop_transient(self, src, sens=0.5):
        src.chops = self.detect_transients(src, sens)
        self._clean(src); return len(src.regions())

    def _sync_chops(self, src):
        """explicit slices: keep the marker list as their starts (for anything that only reads markers)"""
        if src.slices: src.chops = sorted({int(x[0]) for x in src.slices[1:]})

    def slice_at(self, src, pos, prefer=None):
        """the slice under pos (the preferred one if slices overlap there), else the nearest one"""
        regs = src.regions()
        if prefer is not None and 0 <= prefer < len(regs) and regs[prefer][0] <= pos < regs[prefer][1]: return prefer
        for k, (a, b) in enumerate(regs):
            if a <= pos < b: return k
        return min(range(len(regs)), key=lambda k: min(abs(regs[k][0] - pos), abs(regs[k][1] - pos)))

    def add_marker(self, src, pos):
        """SPLIT: cut the slice under pos in two"""
        pos = int(pos)
        if not (self.MIN_GAP <= pos <= src.length - self.MIN_GAP): return False
        if src.slices:
            k = next((i for i, (a, b) in enumerate(src.slices) if a + self.MIN_GAP <= pos <= b - self.MIN_GAP), None)
            if k is None: return False
            a, b = src.slices[k]
            src.slices[k:k + 1] = [[a, pos], [pos, b]]
            self._sync_chops(src); self.relink(src); return True
        if any(abs(c - pos) < self.MIN_GAP for c in src.chops): return False
        bisect.insort(src.chops, pos)
        self.relink(src); return True

    def merge_slice(self, src, k):
        """MERGE: slice k and the one after it become one (the last slice merges into the one before)"""
        regs = src.regions()
        if len(regs) < 2: return None
        k = max(0, min(len(regs) - 2, int(k)))
        if src.slices:
            a, b = src.slices[k]; a2, b2 = src.slices[k + 1]
            src.slices[k:k + 2] = [[min(a, a2), max(b, b2)]]
            self._sync_chops(src)
        else: del src.chops[k]
        self.relink(src); return k

    def remove_marker(self, src, pos):
        if len(src.regions()) < 2: return False
        regs = src.regions()
        i = min(range(1, len(regs)), key=lambda k: abs(regs[k][0] - pos))          # the boundary nearest pos
        return self.merge_slice(src, i - 1) is not None

    def set_slice_edge(self, src, k, start=None, end=None):
        """move one slice's start or end on its own (the slices then keep their own start / end, as on an MPC);
        neighbours are left alone, so slices may leave gaps (trimmed silence) or overlap"""
        regs = src.regions()
        if not (0 <= k < len(regs)): return False
        if not src.slices: src.slices = [list(x) for x in regs]
        a, b = src.slices[k]
        if start is not None: a = int(max(0, min(b - self.MIN_GAP, start)))
        if end is not None: b = int(max(a + self.MIN_GAP, min(src.length, end)))
        src.slices[k] = [a, b]
        self._sync_chops(src); self.relink(src); return True

    def move_marker(self, src, i, pos):
        if src.slices:                                    # explicit slices: the marker is slice i+1's start
            return self.set_slice_edge(src, i + 1, start=pos)
        if not (0 <= i < len(src.chops)): return False
        lo = (src.chops[i - 1] if i else 0) + self.MIN_GAP
        hi = (src.chops[i + 1] if i + 1 < len(src.chops) else src.length) - self.MIN_GAP
        src.chops[i] = int(max(lo, min(hi, pos)))
        self.relink(src); return True

    def clear_markers(self, src):
        src.chops = []; src.slices = None; self.relink(src)

    def chop_to_pads(self, src, first_pad, program=None, bpm=None):
        """Point pads at the regions between markers. No audio is copied or altered; the pads follow later marker edits.
        bpm (BEATS chops): the loop's tempo, stored as each pad's WARP BPM so WARP keeps the slices in time."""
        pr = program or self.prog
        n = 0
        for k, (a, b) in enumerate(src.regions()):
            if first_pad + k >= 64: break
            pad = pr.pads[first_pad + k]
            pad.assign(src, a, b); pad.link = (src.id, k); n += 1
            if bpm: pad.warp_bpm = float(bpm)
        self.say(f"{n} chops on pads {first_pad + 1}-{first_pad + n}")
        return n

    def relink(self, src):
        regs = src.regions()
        for pad in self.all_pads():
            if pad.link and pad.link[0] == src.id and pad.src is src:
                k = pad.link[1]
                if k < len(regs):
                    if (pad.start, pad.end) != regs[k]:
                        pad.start, pad.end = regs[k]; self.pad_changed(pad)
                else: pad.link = None

    def slice_count(self, pad):
        return len(pad.src.regions()) if pad.src is not None else 0

    def set_slice(self, pad, k):
        """SLICE (as on an MPC): k = None = PAD (the pad keeps its own start / end), else play slice k of its sample,
        following that slice's markers"""
        if pad.src is None: return
        if k is None: pad.link = None
        else:
            regs = pad.src.regions()
            k = max(0, min(len(regs) - 1, int(k)))
            pad.start, pad.end = regs[k]; pad.link = (pad.src.id, k)
        self.pad_changed(pad)

    def set_region(self, pad, start=None, end=None):
        """move the pad's start / end. A pad on a slice moves that slice's marker - its neighbour (and every pad on
        it) follows, as on an MPC; SLICE: PAD edits only this pad. Returns None, or why it could not."""
        src = pad.src
        if src is None: return "no sample on this pad"
        if pad.link and pad.link[0] == src.id:
            k = pad.link[1]
            if start is not None:
                if k == 0: return "slice 1 starts at the sample's start - SLICE: PAD to trim it"
                self.move_marker(src, k - 1, start)
            if end is not None:
                if k >= len(src.chops): return "the last slice ends at the sample's end - SLICE: PAD to trim it"
                self.move_marker(src, k, end)
            return None
        gap = int(0.01 * OUT_SR)
        if start is not None: pad.start = int(max(0, min(pad.end - gap, start)))
        if end is not None: pad.end = int(max(pad.start + gap, min(src.length, end)))
        self.pad_changed(pad)
        return None

    # ---------- routing ----------
    def out_ok(self, code):
        if code <= 0 or self.bouncing: return False                   # a bounce gets every pad in its stereo mix
        if code <= 4: return code * 2 <= self.nout
        return code - 4 <= self.nout

    def cycle_out(self, pad, d=1):
        choices = [0] + [c for c in range(1, len(OUT_NAMES)) if self.out_ok(c)]
        i = choices.index(pad.out) if pad.out in choices else 0
        pad.out = choices[(i + d) % len(choices)]
        self.say(f"pad {pad.idx + 1} -> out {OUT_NAMES[pad.out]}")

    # ---------- audio callback ----------
    def render(self, frames, indata=None):
        if self.bouncing:                                            # TRACK OUT running: the outputs are silent meanwhile
            return np.zeros((frames, max(2, self.nout)), dtype=np.float32)
        out = self._render(frames, indata)
        if self.in_monitor and indata is not None and getattr(self, "_in_block", None) is not None and len(self._in_block[0]) == frames:
            out[:, 0] += self._in_block[0]; out[:, 1] += self._in_block[1]
        if self.dim: out *= 0.1                                      # what you hear only: resampling and TRACK OUT stay full level
        if self.monitor < 0.999: out *= self.monitor                   # MIXER > MASTER > MONITOR LEVEL (listening level only)
        return out

    def _render(self, frames, indata=None):
        t0 = time.perf_counter()
        if indata is not None:
            self.feed_input(indata)
        L = np.zeros(frames, dtype=np.float32)
        R = np.zeros(frames, dtype=np.float32)
        bpm0, clock0 = self.seq.bpm, self.beat_clock               # WARP voices are placed by the beat clock at this block's start
        bpb = bpm0 / 60.0 / OUT_SR                                 # beats per frame
        with self.lock:
            if self._live_offs:                                       # PERFORM notes end after their gate time
                keep = []
                for o in self._live_offs:
                    if o[0] < frames: self.key_off(o[1])
                    else: o[0] -= frames; keep.append(o)
                self._live_offs = keep
            if self.playing:
                if self.rec == "rec" and getattr(self, "_replace_pending", False) and self.pos >= 0:
                    self.track.events = []; self._replace_pending = False
                self._advance(frames, L, R)
            elif self.rep_on and self.rep_pad is not None:       # note repeat also works when stopped
                tpf = self.seq.bpm * PPQ / 60.0 / OUT_SR
                a = self.rep_pos; self.rep_pos += frames * tpf
                self._fire_repeat(a, self.rep_pos, 0.0, tpf, False)
            else:
                self.rep_pos = 0.0
            if self._clicks:
                keep = []
                for c in self._clicks:
                    arr, p, dl = c
                    if dl >= frames: c[2] -= frames; keep.append(c); continue
                    n = min(frames - dl, len(arr) - p)
                    L[dl:dl + n] += arr[p:p + n]; R[dl:dl + n] += arr[p:p + n]
                    c[1] += n; c[2] = 0
                    if c[1] < len(arr): keep.append(c)
                self._clicks = keep
            if self._tails:                                       # stolen voices fading out
                keep = []
                for t in self._tails:
                    tl, tr, p = t
                    k = min(frames, len(tl) - p)
                    L[:k] += tl[p:p + k]; R[:k] += tr[p:p + k]; t[2] += k
                    if t[2] < len(tl): keep.append(t)
                self._tails = keep
        padbuf = {}
        busbuf = {}                                                   # ASR-10 effect buses FX2 / DRY, per effect they feed
        self.all_pads()
        progbus = {pr.n: (np.zeros(frames, np.float32), np.zeros(frames, np.float32)) for pr in self.programs}   # = console strips
        with self.lock:
            self._warp_update(bpm0)
            for i in range(self.nv):
                d = self.v_data[i]
                if d is None: continue
                dl = self.v_delay[i]
                if dl >= frames:
                    self.v_delay[i] -= frames; continue
                n = frames - dl
                w = self.v_warp[i]
                if w is not None:                                 # WARP: position from the beat clock, speed from the tempo
                    sc_ = RATIO if self.v_lofi[i] else 1.0
                    self.v_rate[i] = sc_ * bpm0 / w[1]
                    self.v_pos[i] = max(0.0, (clock0 + dl * bpb - w[0]) * 60.0 * OUT_SR / w[1] * sc_)
                spv = self.v_sp[i]
                ovs = self.v_ov[i]
                if ovs is not None:                              # ASR-10: its sound chip's model (looping, TRANSWAV...)
                    s_ov, n_ok = self._ov_block(i, ovs, n)
                elif spv is not None:                            # SP-1200: the hardware model (sp1200hw / dsp/sp1200.c): its
                    prm_ = self.v_spp[i]; prm_[2] = SP_RING_K * self.sp_ring   # stepping, level DAC, hold, channel filter,
                    s_sp = SPH.render(d, int(self.v_end[i]), self.v_sps[i], prm_, spv[1], n)   # resampled band-limited
                    n_ok = len(s_sp)
                else:
                    idx = self.v_pos[i] + self.ramp[:n] * self.v_rate[i]
                if ovs is None and spv is None: n_ok = int(np.searchsorted(idx, self.v_end[i]))
                kill, stop = self.v_kill[i], False
                if kill >= 0 and kill <= n_ok:
                    n_ok, stop = kill, True
                if ovs is not None:
                    s = s_ov[:n_ok]
                elif spv is not None:
                    s = s_sp[:n_ok]
                else:
                    idx = idx[:n_ok]
                    i0 = idx.astype(np.int64)
                    fr = (idx - i0).astype(np.float32)
                    s = d[i0] * (1.0 - fr) + d[i0 + 1] * fr
                if kill >= 0 and n_ok:
                    s = s * np.clip((kill - np.arange(n_ok)) / float(FADE_FR), 0.0, 1.0).astype(np.float32)
                    self.v_kill[i] = kill - n_ok
                if self.v_fin[i] > 0 and n_ok:
                    s = s * np.clip((FADE_FR - self.v_fin[i] + np.arange(n_ok)) / float(FADE_FR), 0.0, 1.0).astype(np.float32)
                    self.v_fin[i] = max(0, self.v_fin[i] - n_ok)
                ev_ = self.v_env[i]
                if ev_ is not None and n_ok:                     # pad envelope and filter
                    a_fr, d_tau, fmode, cut, res, famt, ftau = ev_
                    t0_ = self.v_t[i]
                    tt = t0_ + self.ramp[:n_ok]
                    if spv is None:                                  # (SP-1200: its level DAC does this, in the model)
                        env = np.ones(n_ok, np.float64)
                        if a_fr > 0: env = np.minimum(1.0, tt / a_fr)
                        if d_tau > 0:
                            env = env * np.exp(-np.maximum(0.0, tt - a_fr) / d_tau)
                            if env[-1] < 1e-3: stop = True                   # decayed to silence: the voice ends here
                        s = (s * env).astype(np.float32)
                    if fmode:
                        c0 = cut + famt * np.exp(-t0_ / ftau) + 0.5 * self.mod; c1 = cut + famt * np.exp(-(t0_ + n_ok) / ftau) + 0.5 * self.mod
                        if ovs is not None: pass                                         # ASR-10: its own filter, in the chip model
                        elif self.v_asr[i]: s = self._asr_filter(i, s, fmode, c0, c1)
                        else: s = dspfast.svf(s, self.v_fst[i], self.cut_hz(c0), self.cut_hz(c1), res, fmode, OUT_SR)
                    self.v_t[i] = t0_ + n_ok
                pad = self.v_pad[i]
                if (pad.fx is not None and not pad.fx_bypass) or self.out_ok(pad.out):
                    if id(pad) not in padbuf: padbuf[id(pad)] = (pad, np.zeros(frames, np.float32), np.zeros(frames, np.float32))
                    bl, br = padbuf[id(pad)][1:]
                elif progbus:                                         # the pad's program has insert effects: into its bus
                    pr_ = self._pad_prog.get(id(pad))
                    bl, br = progbus[pr_.n] if (pr_ is not None and pr_.n in progbus) else (L, R)
                else:
                    bl, br = L, R
                if pad.a_bus:                                         # FX2 / DRY: into that bus of the ASR effect it reaches
                    tgt = self._bus_target(pad, progbus)
                    if tgt is not None:
                        if tgt not in busbuf: busbuf[tgt] = [[np.zeros(frames, np.float32), np.zeros(frames, np.float32)] for _ in range(2)]
                        bl, br = busbuf[tgt][pad.a_bus - 1]
                bl[dl:dl + n_ok] += s * self.v_gl[i]
                br[dl:dl + n_ok] += s * self.v_gr[i]
                if n_ok: pad.meter = max(pad.meter, float(np.abs(s).max()) * max(self.v_gl[i], self.v_gr[i]))
                self.v_delay[i] = 0
                if n_ok < n or stop:
                    self.v_data[i], self.v_pad[i], self.v_key[i], self.v_warp[i] = None, None, None, None
                    self.v_ov[i] = None
                else:
                    self.v_pos[i] += n * self.v_rate[i]
                    if spv is not None: self.v_spf[i] += n * SP_RATIO
        if self.instruments:                                          # VST3 instruments (PLUGIN tracks)
            with self.lock:
                keep = []
                for off in self._note_offs:
                    if off[0] < frames: off[1].note(off[0], off[2], 0, False)
                    else: off[0] -= frames; keep.append(off)
                self._note_offs = keep
            tracks = {id(t): t for t in self.seq.tracks}
            for tid, inst in list(self.instruments.items()):
                try: il, ir = inst.render(frames)
                except Exception: continue
                tr = tracks.get(tid)
                vol, pan = (tr.vol, tr.pan) if tr is not None else (0.8, 0.0)
                L += il * vol * min(1.0, 1.0 - pan); R += ir * vol * min(1.0, 1.0 + pan)
                if tr is not None:
                    pk = float(max(np.abs(il).max(), np.abs(ir).max())) * vol
                    self.track_meter[tr.n] = max(self.track_meter[tr.n], pk)
        zero = None
        routed = []
        for pad in [p for p in self.all_pads() if (p.fx is not None and not p.fx_bypass) or self.out_ok(p.out)]:
            has_fx = pad.fx is not None and not pad.fx_bypass
            direct = self.out_ok(pad.out)
            if id(pad) in padbuf: bl, br = padbuf[id(pad)][1:]
            elif has_fx:
                zero = zero if zero is not None else np.zeros(frames, np.float32)
                bl, br = zero.copy(), zero.copy()
            else: continue
            if has_fx: bl, br = self._run_fx(pad.fx, bl, br, pad, busbuf.get(("pad", id(pad))))
            if direct: routed.append((pad.out, bl, br))                # pads on OUT 3-8 skip the program inserts
            else:
                pr_ = self._pad_prog.get(id(pad))
                if pr_ is not None and pr_.n in progbus:
                    progbus[pr_.n][0][:] += bl; progbus[pr_.n][1][:] += br
                else: L += bl; R += br
        anysolo = any(pr.strip.solo for pr in self.programs) or any(rt.solo for rt in self.returns)
        snd = [[np.zeros(frames, np.float32), np.zeros(frames, np.float32)] for _ in range(2)]
        grp = [[np.zeros(frames, np.float32), np.zeros(frames, np.float32)] for _ in range(2)]
        self._grp = grp
        for prn, (bl, br) in progbus.items():                         # program inserts, in slot order (they run every block: tails ring)
            pr_ = self.programs[prn]
            for k in range(Program.NFX):
                if pr_.fx[k] is not None and not pr_.fx_bypass[k]:
                    bl, br = self._run_fx(pr_.fx[k], bl, br, FxSlot(pr_, k), busbuf.pop(("prog", prn), None))
                    bl = np.asarray(bl, dtype=np.float32); br = np.asarray(br, dtype=np.float32)
            self._strip_out(pr_.strip, bl, br, anysolo, snd, L, R, routed)
        for k, rt in enumerate(self.returns):                         # the effect returns: sends A / B through their inserts
            xl, xr = snd[k]
            for j in range(len(rt.fx)):
                if rt.fx[j] is not None and not rt.fx_bypass[j]:
                    xl, xr = self._run_fx(rt.fx[j], xl, xr, FxSlot(rt, j))
                    xl = np.asarray(xl, dtype=np.float32); xr = np.asarray(xr, dtype=np.float32)
            self._strip_out(rt, xl, xr, anysolo, None, L, R, routed)
        for k, g in enumerate(self.groups):                           # group buses: what was sent to 1-2 / 3-4
            self._strip_out(g, grp[k][0], grp[k][1], False, None, L, R, routed, group=True)
        if self.bouncing and self._bounce_raw:                       # a track-out stem: no master effect / filter / limiter
            out = np.zeros((frames, max(2, self.nout)), dtype=np.float32)
            out[:, 0], out[:, 1] = L, R
            self.beat_clock = clock0 + frames * bpb
            return out
        if self.master_fx is not None and not self.master_fx_bypass:
            L, R = self._run_fx(self.master_fx, L, R, "master", busbuf.get("master"))
            L = np.asarray(L, dtype=np.float32); R = np.asarray(R, dtype=np.float32)
        ms = self.master_strip
        if ms.fx[0] is not None and not ms.fx_bypass[0]:               # bus insert 2
            L, R = self._run_fx(ms.fx[0], L, R, FxSlot(ms, 0))
            L = np.asarray(L, dtype=np.float32); R = np.asarray(R, dtype=np.float32)
        L, R = ms.run_eq(L, R, dspfast.sos)
        if self.filt < 0.98:
            a = 0.02 + 0.98 * self.filt ** 2
            for ch, arr in enumerate((L, R)):
                st = np.array([self.lp[ch]], np.float32)
                arr[:] = dspfast.onepole(np.ascontiguousarray(arr, np.float32), st, a)
                self.lp[ch] = float(st[0])
        out = np.zeros((frames, max(2, self.nout)), dtype=np.float32)
        L = L * self.volume; R = R * self.volume
        g = self._limit(L, R, frames)                                  # many pads at once: turned down cleanly, not distorted
        if g is not None: L = L * g; R = R * g
        out[:, 0] = np.tanh(L * self.drive)                            # DRIVE still pushes into the soft clipper on purpose
        out[:, 1] = np.tanh(R * self.drive)
        self.master_meter = max(float(np.abs(out[:, :2]).max()), self.master_meter * 0.9)
        self.meter_l = max(float(np.abs(out[:, 0]).max()), self.meter_l * 0.9)
        self.meter_r = max(float(np.abs(out[:, 1]).max()), self.meter_r * 0.9)
        for code, bl, br in routed:
            bl = np.asarray(bl, dtype=np.float32); br = np.asarray(br, dtype=np.float32)
            if 1 <= code <= 4:
                c0 = (code - 1) * 2
                out[:, c0] += np.tanh(bl); out[:, c0 + 1] += np.tanh(br)
            else:
                out[:, code - 5] += np.tanh(0.5 * (bl + br))
        if routed: np.clip(out, -1.0, 1.0, out=out)
        if self.clock_mode == "SEND" and self.midi_out is not None and not self.bouncing: self._clock_out(clock0, frames, bpb)
        if self.rec_src == "RESAMPLE" and not self.bouncing:          # RESAMPLE: the main mix goes into the recorder
            self._feed_rec(0.5 * (out[:, 0] + out[:, 1]))
        self.beat_clock = clock0 + frames * bpb
        load = (time.perf_counter() - t0) / (frames / OUT_SR)
        self.cpu = 0.95 * self.cpu + 0.05 * load
        self._over = self._over + 1 if load > 1.0 else max(0, self._over - 1)
        if self._over > 12:
            self._over = 0
            hit = False
            for p in self.all_pads():
                if p.fx is not None and p.fx.kind == "vst3" and not p.fx_bypass: p.fx_bypass, hit = True, True
            if self.master_fx is not None and self.master_fx.kind == "vst3" and not self.master_fx_bypass:
                self.master_fx_bypass, hit = True, True
            if hit: self.say("CPU overload: VST3 bypassed")
        return out
