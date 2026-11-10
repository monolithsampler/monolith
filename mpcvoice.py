"""
mpcvoice.py - the MPCs' own voices: the MPC60's L4003 chip and the MPC3000 / MPC2000XL's L6028 chip (dsp/akai.c), with
their envelopes, filter envelope and velocity settings as the machines' program pages offer them.

What is from the hardware (via MAME's l4003.cpp and l7a1045_l6028_dsp_a.cpp, BSD-3-Clause, used as a reference; no
code copied): the MPC60's 12-bit words at a fixed 40 kHz, played without interpolation and through the filter the
MPC3000's code uses on MPC60 sounds (a de-emphasis: so the words are pre-emphasised here when made - inferred); the L6028's 44.1 kHz 16-bit playback, 8-point interpolation, two-pole low-pass
with 16 resonance steps; both chips' envelopes, which ramp the level (and the L6028's cutoff) in straight lines.
What the program pages have (from the machines' firmware text, nothing copied): MPC60 - attack, fadeout, vel>start,
vel>attack, vel>vol; MPC3000 - attack, decay, decay mode, soft start, vel>volume, vel>cutoff, frequency, resonance,
filter envelope amount; MPC2000XL - the same plus velo>attack, velo>start, velo>pitch, filter attack / decay.
What is estimated (the OS code that turns settings into chip registers was not traced): the cutoff scale (0-100 ->
30 Hz .. the top of the filter), how ms become ramp rates (exactly the time asked), and the 12-bit words being
left-justified in the chip's 16-bit reads.
"""
import ctypes, os, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MPC60_SR = 35.84e6 / 896                          # 40,000 Hz: the L4003's clock / 896
L6028_SR = 44100.0
CHIPS = {"MPC60": 0, "MPC3000": 1, "MPC2000XL": 1}
DCY_MODES = ("END", "START")                      # decay from the note's end (or the sound's) / from its start
_lib = None


def _load():
    global _lib
    if _lib is not None: return _lib
    so, src = os.path.join(HERE, "dsp", "libakai.so"), os.path.join(HERE, "dsp", "akai.c")
    def build():
        try: subprocess.run(["sh", os.path.join(HERE, "dsp", "build.sh")], check=True, capture_output=True, timeout=900)
        except Exception: pass
    if (not os.path.exists(so) or os.path.getmtime(so) < os.path.getmtime(src)) and os.path.exists(src): build()
    try: lib = ctypes.CDLL(so)
    except OSError:
        build(); lib = ctypes.CDLL(so)
    V, I, D, U, P16, PF = ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_float)
    lib.ak_new.restype = V; lib.ak_new.argtypes = [I]
    lib.ak_free.argtypes = [V]
    lib.ak_start.argtypes = [V, P16, I, I, I, I, U, D]
    lib.ak_set_step.argtypes = [V, U]
    lib.ak_set_res.argtypes = [V, I]
    lib.ak_done.argtypes = [V]; lib.ak_done.restype = I
    lib.ak_pos.argtypes = [V]; lib.ak_pos.restype = U
    lib.ak_render.argtypes = [V, PF, I, I, I]; lib.ak_render.restype = I
    lib.ak_l4003_filter.argtypes = [P16, P16, I]
    lib.ak_l4003_preemph.argtypes = [PF, I]
    _lib = lib
    return lib


def mpc60_words(x, sr=44100.0):
    """a sound as the MPC60 holds it: 40 kHz, pre-emphasised (see dsp/akai.c), 12 bits in the top of a 16-bit word.
    Like setting the record level, a sound whose lifted treble would clip is brought down to fit; the returned gain puts
    the level back on playback. Returns (words, gain)."""
    import sp1200hw                                   # the converter samples the (already filtered) signal: band-limited,
    x = np.asarray(x, np.float32)                     # not a straight-line interpolation (that dulled the top ~1.6 dB at 10 kHz)
    y = sp1200hw.sample_at(x, sr, np.arange(int(len(x) * MPC60_SR / sr)) * (sr / MPC60_SR)) if sr != MPC60_SR else np.array(x, np.float32)
    y = np.ascontiguousarray(y, np.float32).copy()
    _load().ak_l4003_preemph(y.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(y))
    pk = float(np.abs(y).max()) if len(y) else 0.0
    g = 1.0 / pk if pk > 1.0 else 1.0
    w = (np.round(np.clip(y * g, -1.0, 2047 / 2048.0) * 2048.0).astype(np.int16) << 4).astype(np.int16)
    return w, 1.0 / g


def l6028_words(x):
    return np.round(np.clip(np.asarray(x, np.float32), -1.0, 32767 / 32768.0) * 32768.0).astype(np.int16)


def l4003_filter(words):
    """the MPC60 filter alone (for tests)"""
    lib = _load()
    w = np.ascontiguousarray(words, np.int16); out = np.zeros_like(w)
    P = ctypes.POINTER(ctypes.c_int16)
    lib.ak_l4003_filter(w.ctypes.data_as(P), out.ctypes.data_as(P), len(w))
    return out


def cutoff_reg(v):
    """FREQ 0-100 as the L6028's cutoff register (f / 32768 = 2 sin(pi fc / fs)); 30 Hz .. 9.5 kHz, where the two-pole
    is still stable with no resonance (k^2 + 2k < 4). 100 = the filter off (estimated: how the OS opens it fully)"""
    v = float(v)
    if v >= 100: return -1
    fc = 30.0 * (9500.0 / 30.0) ** (max(0.0, v) / 100.0)
    return int(round(32768 * 2 * np.sin(np.pi * fc / L6028_SR)))


class Voice:
    """one sounding MPC voice"""
    def __init__(self, kind):
        self.lib = _load()
        self.kind = kind
        self.h = self.lib.ak_new(kind)
        self.mem = None

    def __del__(self):
        try: self.lib.ak_free(self.h)
        except Exception: pass

    def start(self, mem, start, end, lstart, ratio, out_sr=44100.0):
        """mem: int16 words; ratio = the pitch (1 = as recorded) -> the chip's 4.12 step (at most 16x)"""
        self.mem = np.ascontiguousarray(mem, np.int16)
        chip_sr = MPC60_SR if self.kind == 0 else L6028_SR
        self.lib.ak_start(self.h, self.mem.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), len(self.mem), int(start), int(end),
                          int(lstart), self.step(ratio), chip_sr / out_sr)

    @staticmethod
    def step(ratio): return int(min(0xffff, max(1, round(ratio * 4096))))
    def set_step(self, ratio): self.lib.ak_set_step(self.h, self.step(ratio))
    def set_res(self, r): self.lib.ak_set_res(self.h, int(r))
    def done(self): return bool(self.lib.ak_done(self.h))
    def pos(self): return int(self.lib.ak_pos(self.h))

    def render(self, n, f0=-1, f1=-1):
        out = np.zeros(n, np.float32)
        k = self.lib.ak_render(self.h, out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), n, int(f0), int(f1))
        return out, k


def ramp(t, pts):
    """straight lines through (time, level) points, held after the last (the chips' envelopes)"""
    ts, ls = zip(*pts)
    return np.interp(t, ts, ls)


def amp_env(pad, vel, t, off, end_t, mpc60):
    """the level for times t (s): ATTACK (longer when soft: VEL>ATTACK), then DECAY - from the start (START mode) or
    at the end (END: from note-off, or so a one-shot fades out exactly at its end; the MPC60's FADEOUT works so). In
    START mode a note-off still ends the sound, in a few ms. Returns (gains, finished)."""
    soft = 1.0 - vel / 127.0
    a = max(0.0, pad.attack + pad.m_vatk * soft) / 1000.0
    d = max(0.0, pad.decay) / 1000.0
    mode = 0 if mpc60 else pad.m_dmode
    def held(t):
        g = np.minimum(1.0, t / a) if a > 0 else np.ones_like(t)
        if mode == 1 and d > 0: g = g * np.clip(1.0 - (t - a) / d, 0.0, 1.0)     # START: down from the top of the attack
        return g
    g = held(t)
    fin = mode == 1 and d > 0 and bool(t[-1] >= a + d)
    t_dec, dd = None, 0.003
    if off is not None: t_dec, dd = off, (d if (mode == 0 and d > 0) else 0.003)
    elif mode == 0 and d > 0 and end_t is not None: t_dec, dd = max(0.0, end_t - d), d   # END: fade out to the sound's end
    if t_dec is not None:
        g0 = float(held(np.array([t_dec]))[0])
        g = np.where(t >= t_dec, g0 * np.clip(1.0 - (t - t_dec) / dd, 0.0, 1.0), g)
        fin = fin or bool(t[-1] >= t_dec + dd)
    return g.astype(np.float32), fin


def cutoff_at(pad, vel, t):
    """the L6028's cutoff (FREQ units) across t: FREQ, less VEL>FREQ when soft, plus the filter envelope (FILTER ENV
    amount, its ATTACK then DECAY in straight lines)"""
    base = pad.cutoff * 100.0 - 50.0 * pad.f_vel * (1.0 - vel / 127.0)
    a, d = max(0.0, pad.f_atk) / 1000.0, max(0.001, pad.f_dec / 1000.0)
    env = ramp(t, [(0.0, 0.0 if a > 0 else 1.0), (a, 1.0), (a + d, 0.0)])
    return np.clip(base + 100.0 * pad.f_env * env, 0.0, 100.0)
