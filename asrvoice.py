"""
asrvoice.py - ASR-10 wavesample playback: the ES5506 chip's looping and the ASR-10 OS's sample modulation (TRANSWAV,
LOOP POS, START...), from dsp/otto.c, plus its modulation sources and a transwave maker.

What comes from the ASR-10 (read from its OS 1.5B ROM and OS 3.53 disk; none of it is included):
  - the wavesample's loop modes, the control word each sets, and what LOOP AND RELEASE does on release;
  - the eight MOD types and the code behind each (see dsp/otto.c), MOD AMT, and the 22 RANGE steps (2 MG ... 1);
  - the modulation source list, the LFO waves and the LFO rate steps (the values are computed here, not copied).
What is estimated: how often the OS updates a voice (VOICE_TICK_S), the scale of KBD, and ENV1's shape (the ASR's
envelopes have five stages; here it is attack / decay / sustain / release).
"""
import ctypes, os, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

LOOP_MODES = ("FORWARD-NO LOOP", "BACKWARD-NO LOOP", "LOOP FORWARD", "LOOP BIDIRECTION", "LOOP AND RELEASE")
MOD_TYPES = ("OFF", "LOOP POS", "START", "START+LP", "LOOPSTRT", "LOOP END", "LPSTRT-X", "TRANSWAV")
RANGES = ("2 MG", "1 MG", "512K", "256K", "128K", "64 K", "32 K", "16 K", "8 K", "4 K", "2 K", "1 K",
          "512", "256", "128", "64", "32", "16", "8", "4", "2", "1")      # samples a full modulation moves
MOD_SOURCES = ("LFO", "NOISE", "ENV1", "ENV2", "VEL", "KBD", "WHEEL", "PRESS", "OFF")   # the ASR's, those a pad has
FILTER_MODES = ("F1=2/LP F2=2/HP", "F1=3/LP F2=1/HP", "F1=2/LP F2=2/LP", "F1=3/LP F2=1/LP")   # the chip's LP3 / LP4 bits
BUSES = ("FX1", "FX2", "DRY")
ENV_MODES = ("NORMAL", "FINISH", "REPEAT")       # NORMAL: releases at note-off; FINISH: runs to the sustain first; REPEAT: cycles while held
VEL_CURVES = ("OFF", "VEL", "VEL1", "VEL2")       # how velocity moves the levels from SOFT to hard: none / straight / harder / softer
AMP_STAGES = ("ATTACK", "DECAY 1", "DECAY 2", "DECAY 3", "RELEASE")
AMP_LEVELS = ("INITIAL", "PEAK", "BREAK 1", "BREAK 2", "SUSTAIN")


def vel_curve(curve, vel):
    """0..1: how far velocity takes a level from its soft value to its hard one (VEL1 / VEL2 shapes estimated)"""
    x = max(0.0, min(1.0, vel / 127.0))
    return (1.0, x, x * x, x ** 0.5)[curve]


def amp_env(pad, vel, t0, n, sr, off):
    """the ASR-10's amp envelope (ENV3) for n frames from t0 s: five times (ATTACK, DECAY 1-3, RELEASE in ms), five levels
    (INITIAL, PEAK, BREAK 1, BREAK 2, SUSTAIN: 0-99, the hard-velocity levels), the soft-velocity levels at SOFT VEL % of
    those, and the VEL CURVE between them. Straight lines between the levels; level -> gain as (L / 99) ** 1.5 (estimated:
    the OS's level table was not found). off = note-off time in s (None = still held). Returns (gains, finished)."""
    tm = [max(0.0, x) / 1000.0 for x in pad.a_amp_t]
    c = vel_curve(pad.a_vcurve, vel)
    lv = [h * (pad.a_softvel / 100.0 + (1.0 - pad.a_softvel / 100.0) * c) / 99.0 for h in pad.a_amp_l]
    bt = np.cumsum([0.0] + tm[:4])                       # 0, end of attack, decay 1, decay 2, decay 3
    tot = bt[-1]
    t = t0 + np.arange(n) / float(sr)
    if off is not None and pad.a_emode == 1: off = max(off, tot)    # FINISH: the stages run to the sustain first
    def held(t):
        if pad.a_emode == 2 and tot > 0:                 # REPEAT: attack .. decay 3 over and over while held
            t = np.mod(t, tot)
        return np.interp(t, bt, lv) if tot > 0 else np.full_like(t, lv[4])
    g = held(t)
    done = False
    if off is not None:
        r = tm[4]
        g0 = float(held(np.array([off]))[0])
        rel = np.maximum(0.0, 1.0 - (t - off) / r) if r > 0 else np.zeros_like(t)
        g = np.where(t >= off, g0 * rel, g)
        done = bool(t[-1] >= off + r)
    return (np.clip(g, 0.0, 1.0) ** 1.5).astype(np.float32), done
LFO_WAVES = ("TRIANGLE", "SINE/TRI", "SINE", "POS-SINE", "POS-TRI", "SAWTOOTH", "SQUARE")
VOICE_TICK_S = 0.010        # how often the OS updates a voice's modulation: NOT found in the ROM (estimated)


def _lfo_step(k):
    """LFO RATE 0-99: cycles per voice update (the ROM's table: 0.003 per step from 20 to 95, a curve below, four
    fast steps above)"""
    low = (39, 41, 44, 46, 49, 52, 56, 60, 66, 71, 79, 87, 98, 112, 131, 157, 197, 262, 393, 786)
    if k < 20: return low[k] / 65536.0
    if k <= 95: return (k - 15) * 0.003
    return (0.25, 0.375, 0.5, 0.6256)[k - 96]


def lfo_wave(w, ph):
    """the seven LFO waves, -127..127 (unipolar ones 0..127), phase 0..1"""
    x = (ph % 1.0)
    tri = 127.0 * (1.0 - abs(((x + 0.25) % 1.0) * 4.0 - 2.0))
    sin = 127.0 * np.sin(2 * np.pi * x)
    if w == 0: return tri
    if w == 1: return 0.5 * (tri + sin)
    if w == 2: return sin
    if w == 3: return 64.0 + 63.0 * np.sin(2 * np.pi * x)
    if w == 4: return 64.0 + 0.5 * tri
    if w == 5: return -128.0 + 256.0 * x
    return 127.0 if x < 0.5 else 0.0


def cutoff_k(v, rate):
    """CUTOFF 0-150 as the chip's 16-bit filter constant K: v sweeps 15 Hz to half the chip's rate exponentially
    (the ASR's own table was not found: estimated); K = 1 - e^(-2 pi f / rate) for its one-pole stages. For the
    high-pass poles a bigger K is a LOWER cut-off, as on the chip - so 150 is open in every mode."""
    v = max(0.0, min(150.0, float(v)))
    f = 15.0 * (0.5 * rate / 15.0) ** (v / 150.0)
    return int(round(65535 * (1.0 - np.exp(-2 * np.pi * min(f, 0.5 * rate) / rate))))


UNITS_PER_SEMI = 150.0 / (np.log2(0.5 * 29761.9 / 15.0) * 12.0)    # cutoff units in a semitone (KBD AMT 127 = tracks the pitch)


_lib = None


def _load():
    global _lib
    if _lib is not None: return _lib
    so, src = os.path.join(HERE, "dsp", "libotto.so"), os.path.join(HERE, "dsp", "otto.c")
    def build():
        try: subprocess.run(["sh", os.path.join(HERE, "dsp", "build.sh")], check=True, capture_output=True, timeout=900)
        except Exception: pass
    if (not os.path.exists(so) or os.path.getmtime(so) < os.path.getmtime(src)) and os.path.exists(src): build()
    try: lib = ctypes.CDLL(so)
    except OSError:
        build(); lib = ctypes.CDLL(so)
    V, I, D, P16, PF = ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_float)
    lib.ov_new.restype = V
    lib.ov_free.argtypes = [V]
    lib.ov_start.argtypes = [V, P16, I, I, I, I, I, I, I, I, I, I, D, I, I]
    lib.ov_set.argtypes = [V, I, I]
    lib.ov_filter.argtypes = [V, I, I, I, I]
    lib.ov_release.argtypes = [V]
    lib.ov_done.argtypes = [V]
    lib.ov_render.argtypes = [V, PF, I]; lib.ov_render.restype = I
    lib.ov_regs.argtypes = [V, ctypes.POINTER(ctypes.c_uint32)]
    _lib = lib
    return lib


class Voice:
    """one sounding ASR-10 voice"""
    def __init__(self):
        self.lib = _load()
        self.h = self.lib.ov_new()
        self.mem = None

    def __del__(self):
        try: self.lib.ov_free(self.h)
        except Exception: pass

    def start(self, mem, ss, se, ls, le, loopmode, mod, amt, rng, fc, step, tick, src):
        """mem: int16 at the chip's rate. ss/se/ls/le: OS units (sample x 512). fc: 2048 = as recorded."""
        self.mem = np.ascontiguousarray(mem, np.int16)
        self.lib.ov_start(self.h, self.mem.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), len(self.mem),
                          int(ss), int(se), int(ls), int(le), int(loopmode), int(mod), int(amt), int(rng), int(fc),
                          float(step), int(tick), int(src))

    def set(self, fc, src): self.lib.ov_set(self.h, int(fc), int(src))
    def filter(self, on, mode, k1, k2): self.lib.ov_filter(self.h, int(on), int(mode), int(k1), int(k2))
    def release(self): self.lib.ov_release(self.h)
    def done(self): return bool(self.lib.ov_done(self.h))

    def render(self, n):
        out = np.zeros(n, np.float32)
        k = self.lib.ov_render(self.h, out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), n)
        return out, k

    def regs(self):
        r = (ctypes.c_uint32 * 6)()
        self.lib.ov_regs(self.h, r)
        return dict(zip(("accum", "start", "end", "cr", "fc", "tw"), list(r)))


# ---------------------------------------------------------------------------------------------- modulation sources
class Sources:
    """a voice's modulation sources, -32768..32767 (unipolar ones 0..32767), as the OS keeps them"""
    def __init__(self, pad, vel, key, seed=1):
        self.pad, self.vel, self.key = pad, vel, key
        self.rnd = np.random.default_rng(seed)
        self.noise, self.next_noise = 0, 0.0
        self.rel_t = None                      # seconds into the release (ENV1), None = held

    def value(self, kind, t, wheel=0.0):
        p = self.pad
        if kind == "OFF": return 0
        if kind == "VEL": return int(self.vel * 258)                          # 0..32766
        if kind == "KBD": return int(max(-32768, min(32767, (self.key - 60) * 512)))   # estimated scale
        if kind in ("WHEEL", "PRESS"): return int(max(0.0, min(1.0, wheel)) * 32767)
        if kind == "NOISE":                                                   # a new random value at NOISE RATE (LFO RATE)
            if t >= self.next_noise:
                self.noise = int(self.rnd.integers(-32768, 32768))
                self.next_noise = t + VOICE_TICK_S / max(1e-3, _lfo_step(p.a_lfo_rate) * 4)
            return self.noise
        if kind == "LFO":
            cyc = _lfo_step(p.a_lfo_rate) / VOICE_TICK_S                        # Hz
            dl = p.a_lfo_delay / 99.0 * 4.0                                      # depth ramps in over the delay (s)
            depth = p.a_lfo_depth / 127.0 * (min(1.0, t / dl) if dl > 0 else 1.0)
            return int(lfo_wave(p.a_lfo_wave, t * cyc) / 128.0 * depth * 32767)
        if kind == "ENV2":                                                    # the pad's amp envelope shape
            a, d = p.attack / 1000.0, p.decay / 1000.0
            v = min(1.0, t / a) if a > 0 else 1.0
            if d > 0: v *= float(np.exp(-max(0.0, t - a) / (d / 4.0)))
            return int(v * 32767)
        # ENV1: attack / decay to sustain / release
        a, d, s, r = p.a_env1[0] / 1000.0, p.a_env1[1] / 1000.0, p.a_env1[2], p.a_env1[3] / 1000.0
        if t < a: v = t / a
        elif d > 0 and t < a + d: v = 1.0 - (1.0 - s) * (t - a) / d
        else: v = s
        if self.rel_t is not None:
            v = v * max(0.0, 1.0 - (t - self.rel_t) / r) if r > 0 else 0.0
        return int(max(0.0, min(1.0, v)) * 32767)


# ---------------------------------------------------------------------------------------------- transwaves
def detect_period(x, sr, lo=30.0, hi=1500.0):
    """the fundamental's period in samples: YIN's cumulative-mean difference on the loudest stretch of the sound,
    first dip under 0.15 (else the deepest), refined to a fraction of a sample"""
    x = np.asarray(x, np.float64)
    w = min(len(x), int(sr * 0.2))
    if w < 64: return sr / 220.0
    hop = max(1, w // 4)
    starts = range(0, max(1, len(x) - w), hop)
    k0 = max(starts, key=lambda k: float(np.sum(x[k:k + w] ** 2)))            # the loudest window
    seg = x[k0:k0 + w] - x[k0:k0 + w].mean()
    tmax = min(int(sr / lo), w // 2)
    tmin = max(2, int(sr / hi))
    if tmax <= tmin + 2: return sr / 220.0
    W = w - tmax - 2
    if W < 32: W = w // 2
    d = np.empty(tmax + 2)
    for t in range(tmax + 2):                                                 # difference over a fixed window
        a = seg[:W]; b = seg[t:t + W]
        if len(b) < W: d[t] = d[t - 1]; continue
        d[t] = np.sum((a - b) ** 2)
    cm = np.ones_like(d)
    cs = np.cumsum(d[1:])
    cm[1:] = d[1:] * np.arange(1, len(d)) / np.maximum(cs, 1e-12)
    cand = [t for t in range(tmin, tmax) if cm[t] < 0.15 and cm[t] <= cm[t - 1] and cm[t] <= cm[t + 1]]
    t = cand[0] if cand else tmin + int(np.argmin(cm[tmin:tmax]))
    if 1 <= t < len(cm) - 1:
        den = cm[t - 1] - 2 * cm[t] + cm[t + 1]
        if den != 0: return float(t + 0.5 * (cm[t - 1] - cm[t + 1]) / den)
    return float(t)


def make_transwave(x, sr, chip_rate, frames=64, frame_len=None):
    """an Ensoniq-style transwave from a sound: `frames` single cycles taken evenly through it, each started on a
    rising zero crossing and stretched to exactly frame_len samples at the chip's rate (default: one period of the
    sound's own pitch), joined end to end. Returns (int16 at chip_rate, frame_len, period found in input samples)."""
    x = np.asarray(x, np.float64)
    per = detect_period(x, sr)
    if frame_len is None: frame_len = int(round(per * chip_rate / sr))
    frame_len = int(max(16, min(4096, frame_len)))
    n = len(x)
    out = []
    env = np.convolve(np.abs(x), np.ones(int(per) + 1) / (int(per) + 1), mode="same")
    live = np.flatnonzero(env > 0.1 * env.max()) if env.max() > 0 else np.arange(n)
    a0, a1 = int(live[0]), int(min(live[-1], n - per * 2 - 2))           # where the sound is (not its silent tail)
    if a1 <= a0: a0, a1 = 0, max(1, int(n - per * 2 - 2))
    for k in range(frames):
        c = a0 + k * (a1 - a0) / max(1, frames - 1)
        i = int(c)
        w = x[i:i + int(per * 2) + 2]
        zc = np.flatnonzero((w[:-1] <= 0) & (w[1:] > 0))                       # rising zero crossings
        if len(zc):
            j = zc[0]; p0 = i + j + (-x[i + j]) / (x[i + j + 1] - x[i + j] + 1e-12)
        else:
            p0 = float(i)
        pos = p0 + np.arange(frame_len) * (per / frame_len)                     # one period, frame_len points
        cyc = np.interp(pos, np.arange(n), x)
        cyc = cyc - cyc.mean()
        out.append(cyc)
    y = np.concatenate(out)
    pk = np.abs(y).max()
    if pk > 0: y = y * (0.95 / pk)
    return np.round(y * 32767).astype(np.int16), frame_len, per
