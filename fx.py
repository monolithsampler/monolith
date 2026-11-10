"""
fx.py - mixer insert effects.
  * built-in effects (Valve Drive, Filter, Tape Echo, Crush, Bus Comp) - numpy, work everywhere
  * VST3 plugins (Linux builds for your CPU), hosted through Spotify's `pedalboard` library if it is installed,
    or (preferred, and needed to show a plug-in's own interface) the small bundled host in vst3host/ (vst3host/build.sh)
Every effect has the same small interface so the mixer and UI don't care which kind it is.
"""
import ctypes, glob, os
import numpy as np

SR = 44100
HERE = os.path.dirname(os.path.abspath(__file__))
VST_DIRS = ["~/.vst3", "/usr/lib/vst3", "/usr/local/lib/vst3", "./plugins", os.path.join(HERE, "plugins")]
try:
    import pedalboard                      # pip install pedalboard  (64-bit OS needed on a Pi 3)
except Exception:
    pedalboard = None


def _load_host():
    """the bundled C++ VST3 host (vst3host/vst3host.so), used when pedalboard is not available"""
    path = os.path.join(HERE, "vst3host", "vst3host.so")
    if not os.path.exists(path): return None
    try: lib = ctypes.CDLL(path)
    except OSError: return None
    P, I, D, S = ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.c_char_p
    lib.vh_open.restype, lib.vh_open.argtypes = P, [S, D, I, S, I]
    lib.vh_name.restype, lib.vh_name.argtypes = S, [P]
    lib.vh_param_count.restype, lib.vh_param_count.argtypes = I, [P]
    lib.vh_param_title.argtypes = [P, I, S, I]
    lib.vh_param_string.argtypes = [P, I, S, I]
    lib.vh_get.restype, lib.vh_get.argtypes = D, [P, I]
    lib.vh_set.argtypes = [P, I, D]
    lib.vh_process.argtypes = [P, P, P, I]
    lib.vh_close.argtypes = [P]
    lib.vh_editor_open.restype, lib.vh_editor_open.argtypes = ctypes.c_ulong, [P, ctypes.c_ulong, I, I, ctypes.POINTER(I), ctypes.POINTER(I)]
    lib.vh_editor_idle.argtypes = [P]
    lib.vh_editor_close.argtypes = [P]
    lib.xs_open.restype, lib.xs_open.argtypes = ctypes.c_ulong, [I, I, I, I, S]
    lib.xs_screen_size.argtypes = [ctypes.POINTER(I), ctypes.POINTER(I)]
    lib.xs_put.argtypes = [P, I, I]
    lib.xs_event.argtypes = [ctypes.POINTER(I), ctypes.POINTER(I), ctypes.POINTER(I)]
    lib.xs_grab.argtypes = [P, I, I]
    lib.xs_child.restype, lib.xs_child.argtypes = ctypes.c_ulong, [I, I, I, I]
    lib.xs_destroy.argtypes = [ctypes.c_ulong]
    lib.xs_place.argtypes = [ctypes.c_ulong, I, I, I, I]
    lib.vh_editor_move.argtypes = [P, I, I]
    lib.vh_editor_scale.argtypes = [P, ctypes.c_float]
    lib.vh_is_instrument.restype, lib.vh_is_instrument.argtypes = I, [P]
    lib.vh_note.argtypes = [P, I, I, I, I]
    lib.vh_editor_size.argtypes = [P, ctypes.POINTER(I), ctypes.POINTER(I)]
    if hasattr(lib, "vh_midi_controller"):                             # (older builds of vst3host.so lack it: re-run build.sh)
        lib.vh_midi_controller.restype, lib.vh_midi_controller.argtypes = I, [P, I, D]
    return lib


HOST = _load_host()                       # preferred: it can also show the plug-in's own interface
HAVE_VST = pedalboard is not None or HOST is not None
VST_ENGINE = "vst3host" if HOST is not None else ("pedalboard" if pedalboard is not None else "none")


class Effect:
    kind = "builtin"
    def __init__(self, name, params):
        self.name = name
        self.labels = [p[0] for p in params]
        self.vals = [float(p[1]) for p in params]
        self.ident = ("builtin", name)

    def n(self): return len(self.vals)
    def get(self, i): return self.vals[i]
    def set(self, i, f): self.vals[i] = float(min(1.0, max(0.0, f)))
    def fmt(self, i): return f"{self.vals[i] * 100:.0f}%"
    def process(self, L, R): return L, R

    def state(self):
        return {"kind": self.ident[0], "id": self.ident[1], "params": list(self.vals)}

    def load_state(self, d):
        for i, v in enumerate(d.get("params", [])[:self.n()]):
            self.set(i, v)


VALVES_V1 = [("12AX7", 100, "warm, most gain", (1.0, 0.5, 0.3, 0.2)), ("5751", 70, "smoother top", (0.8, 0.35, 0.2, 0.1)),
             ("12AT7", 60, "brighter, more headroom", (0.6, 0.3, 0.15, 0.1)), ("12AU7", 20, "clean, glassy", (0.4, 0.15, 0.1, 0.05)),
             ("EF86", 0, "gritty, mic-pre bite", (0.8, 1.0, 0.4, 0.3)), ("12AY7", 44, "soft, early breakup", (0.7, 0.4, 0.2, 0.1))]
VALVES_V2 = [("EL34", "crunchy, mid-forward"), ("6L6", "round, clean lows"), ("EL84", "chimey, early grit"), ("KT88", "big, tight headroom")]


class Drive(Effect):
    """VALVE DRIVE: a two-stage valve preamp. V1 (the preamp valve) sets gain and character, BIAS shifts it asymmetric (even
    harmonics), V2 (the power valve) rounds it off."""
    qmap = (0, 3, 1, 2)                                            # Q1-Q4 on the faceplate: DRIVE, BIAS, MIX, LEVEL
    def __init__(self):
        super().__init__("Drive", [("Drive", 0.3), ("Mix", 1.0), ("Level", 0.7), ("Bias", 0.4), ("V1", 0.0), ("V2", 0.0)])
        self.dc = [0.0, 0.0]; self.peak = 0.0
    def v1(self): return VALVES_V1[min(len(VALVES_V1) - 1, int(round(self.vals[4] * (len(VALVES_V1) - 1))))]
    def v2(self): return VALVES_V2[min(len(VALVES_V2) - 1, int(round(self.vals[5] * (len(VALVES_V2) - 1))))]
    def set_valve(self, which, i):
        n = len(VALVES_V1) if which == 1 else len(VALVES_V2)
        self.vals[4 if which == 1 else 5] = i / float(n - 1)
    def character(self): return self.v1()[2] + ("" if self.vals[3] < 0.55 else ", 2nd-heavy")
    def fmt(self, i):
        if i == 0: return f"{self.vals[0] * 10:.1f}"
        if i == 3: return "cold" if self.vals[3] < 0.25 else "cool" if self.vals[3] < 0.5 else "warm" if self.vals[3] < 0.75 else "hot"
        if i == 2: return f"{(self.vals[2] - 0.7) * 30:+.0f} dB"
        if i == 4: return self.v1()[0]
        if i == 5: return self.v2()[0]
        return super().fmt(i)
    def process(self, L, R):
        mu = max(15, self.v1()[1] or 80)
        g = 1 + self.vals[0] * 19 * (mu / 100.0) ** 0.5
        b = (self.vals[3] - 0.25) * 0.6
        g2 = {"EL34": 1.6, "6L6": 1.1, "EL84": 2.0, "KT88": 0.8}[self.v2()[0]]
        mix, lvl = self.vals[1], 10 ** ((self.vals[2] - 0.7) * 30 / 20.0)
        out = []
        for ch, x in enumerate((L, R)):
            y = np.tanh(x * g + b) - np.tanh(b)                     # stage 1: the preamp valve, biased
            y = np.tanh(y * g2) / np.tanh(g2)                         # stage 2: the power valve
            dc = self.dc[ch] + 0.001 * (float(np.mean(y)) - self.dc[ch]) * len(y) / 64.0
            self.dc[ch] = dc
            out.append((x * (1 - mix) + (y - dc) * mix) * lvl)
        self.peak = max(float(np.abs(out[0]).max()) if len(out[0]) else 0.0, self.peak * 0.9)
        return out[0], out[1]


class Filter(Effect):
    qmap = (0, 1, 2, 3)
    MODES = ("LP", "BP", "HP")
    def __init__(self):
        super().__init__("Filter", [("Cutoff", 0.7), ("Mode", 0.0), ("Mix", 1.0), ("Reso", 0.15)])
        self.st = [np.zeros(2, np.float32), np.zeros(2, np.float32)]
    def cutoff(self): return 80.0 * (16000.0 / 80.0) ** self.vals[0]
    def mode(self): return self.MODES[0 if self.vals[1] < 0.33 else 1 if self.vals[1] < 0.67 else 2]
    def fmt(self, i):
        if i == 0: f = self.cutoff(); return f"{f:.0f} Hz" if f < 1000 else f"{f / 1000:.1f} kHz"
        if i == 1: return self.mode()
        return super().fmt(i)
    def response(self, freqs):
        """magnitude in dB of the 2-pole filter at freqs (for the faceplate's display)"""
        f0, q = self.cutoff(), 0.5 + self.vals[3] * 6.0
        s = 1j * np.asarray(freqs, float) / f0
        den = s * s + s / q + 1
        num = {"LP": 1.0, "HP": s * s, "BP": s / q}[self.mode()]
        return 20 * np.log10(np.maximum(np.abs(num / den), 1e-6))
    def process(self, L, R):
        import dspfast
        f, mix, mode = self.cutoff(), self.vals[2], {"LP": 1, "HP": 2, "BP": 3}[self.mode()]
        out = []
        for ch, x in enumerate((L, R)):
            y = dspfast.svf(np.array(x, dtype=np.float32), self.st[ch], f, f, self.vals[3] * 0.9, mode, SR)
            out.append(x * (1 - mix) + y * mix)
        return out[0], out[1]


class Delay(Effect):
    """TAPE ECHO: a tape loop with a record head and three playback heads (at 1/2, 1 and 3/2 of the repeat rate); the MODE
    selector picks the heads, and the R modes add the spring-ish reverb of a dense tap cluster."""
    qmap = (0, 1, 2, 3)
    MODES = ("1", "2", "3", "1+2", "2+3", "1+3", "1+2+3", "R+1", "R+2", "R+3", "R+ALL", "REV")
    HEADS = (0.5, 1.0, 1.5)
    def __init__(self):
        super().__init__("Delay", [("Time", 0.35), ("Feedback", 0.4), ("Mix", 0.35), ("Mode", 1 / 11.0)])
        self.N = SR * 3
        self.buf = np.zeros((2, self.N), dtype=np.float32)
        self.wp = 0; self.peak = 0.0
    def mode(self): return self.MODES[min(len(self.MODES) - 1, int(round(self.vals[3] * (len(self.MODES) - 1))))]
    def heads(self):
        m = self.mode()
        if m == "REV": return []
        h = m.replace("R+", "")
        return [0, 1, 2] if h == "ALL" or h == "1+2+3" else [int(c) - 1 for c in h.split("+")]
    def fmt(self, i):
        if i == 0: return f"{self.ms():.0f} ms"
        if i == 3: return self.mode()
        return super().fmt(i)
    def ms(self): return 20.0 + self.vals[0] * 780.0
    def process(self, L, R):
        n = len(L)
        base = self.ms() / 1000.0 * SR
        ar = np.arange(n)
        wet = np.zeros((2, n), np.float32)
        hs = self.heads()
        for h in hs:
            d = max(int(base * self.HEADS[h]), n)
            wet += self.buf[:, (self.wp - d + ar) % self.N]
        if hs: wet /= (1.0 + 0.35 * (len(hs) - 1))
        fbk = wet.copy()
        if self.mode().startswith("R") :                            # reverb: a dense cluster of short taps, decaying
            rv = np.zeros((2, n), np.float32)
            for k, t in enumerate((1123, 1559, 2017, 2671, 3253, 3907, 4561, 5303)):
                rv += self.buf[:, (self.wp - max(t, n) + ar) % self.N] * (0.5 * 0.85 ** k)
            wet += rv * 0.6
        inp = np.stack([L, R])
        self.buf[:, (self.wp + ar) % self.N] = inp + fbk * (self.vals[1] * 0.92)
        self.wp = (self.wp + n) % self.N
        self.peak = max(float(np.abs(inp).max()) if n else 0.0, self.peak * 0.9)
        mix = self.vals[2]
        return L + wet[0] * mix, R + wet[1] * mix


class Crush(Effect):
    """CRUSH: fewer bits and a lower sample rate - the rates of the classic machines"""
    qmap = (0, 1, 2, 3)
    RATES = ((44100, "44.1k", "CD"), (40000, "40k", "MPC60"), (31250, "31.25k", "ASR-10"), (26040, "26.04k", "SP-1200"),
             (22050, "22k", ""), (11025, "11k", ""))
    def __init__(self):
        super().__init__("Crush", [("Rate", 0.6), ("Bits", 0.43), ("Mix", 1.0)])
        self.ph = 0.0; self.last = [0.0, 0.0]
    def rate_i(self): return min(len(self.RATES) - 1, int(round(self.vals[0] * (len(self.RATES) - 1))))
    def rate(self): return self.RATES[self.rate_i()][0]
    def bits(self): return int(round(2 + self.vals[1] * 14))
    def fmt(self, i):
        if i == 0: return self.RATES[self.rate_i()][1]
        if i == 1: return f"{self.bits()} bit"
        return super().fmt(i)
    def process(self, L, R):
        n = len(L); ratio = self.rate() / float(SR)
        step = np.floor(self.ph + np.arange(n) * ratio)                # the target-rate sample each output sample falls in
        first = np.concatenate(([step[0] != np.floor(self.ph - ratio)], step[1:] != step[:-1]))
        self.ph = (self.ph + n * ratio) % 1.0
        lv = 2.0 ** (self.bits() - 1); mix = self.vals[2]
        out = []
        for ch, x in enumerate((L, R)):
            idx = np.maximum.accumulate(np.where(first, np.arange(n), -1))
            held = np.where(idx >= 0, x[np.maximum(idx, 0)], self.last[ch])
            if n: self.last[ch] = float(held[-1])
            y = np.round(held * lv) / lv
            out.append(x * (1 - mix) + y * mix)
        return out[0], out[1]


class Comp(Effect):
    """BUS COMP: a feed-forward bus compressor - THRESHOLD, RATIO (2 4 8 12 20 ALL), ATTACK, RELEASE (top = AUTO), MAKEUP,
    and a high-pass on the detector (SC HPF) so the low end does not pump it."""
    qmap = (0, 1, 2, 4)
    RATIOS = (2, 4, 8, 12, 20, 100)
    def __init__(self):
        super().__init__("Comp", [("Threshold", 0.65), ("Ratio", 0.2), ("Attack", 0.5), ("Release", 1.0), ("Makeup", 0.3), ("SC HPF", 1.0)])
        self.env = 0.0; self.gr = 0.0; self.hist = []; self.hp = [0.0, 0.0]
    def thr(self): return -40 + self.vals[0] * 40
    def ratio(self): return self.RATIOS[min(5, int(round(self.vals[1] * 5)))]
    def att_ms(self): return 0.1 * 1000 ** self.vals[2]
    def rel_ms(self): return None if self.vals[3] > 0.97 else 50 + self.vals[3] * 950
    def makeup(self): return self.vals[4] * 12
    def fmt(self, i):
        if i == 0: return f"{self.thr():.0f} dB"
        if i == 1: return "ALL" if self.ratio() == 100 else f"{self.ratio()}:1"
        if i == 2: return f"{self.att_ms():.1f} ms" if self.att_ms() < 10 else f"{self.att_ms():.0f} ms"
        if i == 3: return "AUTO" if self.rel_ms() is None else f"{self.rel_ms():.0f} ms"
        if i == 4: return f"+{self.makeup():.0f} dB"
        if i == 5: return "ON" if self.vals[5] > 0.5 else "OFF"
        return super().fmt(i)
    def curve(self, x_db):
        t, r = self.thr(), self.ratio()
        x = np.asarray(x_db, float)
        return np.where(x > t, t + (x - t) / r, x) + self.makeup()
    def process(self, L, R):
        n = len(L)
        if not n: return L, R
        det = 0.5 * (np.abs(L) + np.abs(R))
        if self.vals[5] > 0.5:                                          # SC HPF: the detector ignores the lows (~100 Hz)
            m = (L + R) * 0.5; a = 1 - np.exp(-2 * np.pi * 100 / SR)
            lp = self.hp[0] + np.cumsum(np.full(n, 0.0))                 # (block approximation of a one-pole low-pass)
            lpv = self.hp[0] + (float(np.mean(m)) - self.hp[0]) * min(1.0, a * n)
            self.hp[0] = lpv; det = np.abs(m - lpv)
        pk = float(np.max(det))
        lvl = 20 * np.log10(max(pk, 1e-6))
        over = max(0.0, lvl - self.thr()); target = over - over / self.ratio()
        dt = n / SR * 1000.0
        rel = self.rel_ms() or (80 + 400 * min(1.0, self.gr / 12.0))   # AUTO: slower release after heavy compression
        k = 1 - np.exp(-dt / (self.att_ms() if target > self.gr else rel))
        g0 = self.gr; self.gr = g0 + (target - g0) * k
        gains = 10 ** ((-np.linspace(g0, self.gr, n) + self.makeup()) / 20.0)
        self.hist.append(self.gr)
        if len(self.hist) > 600: del self.hist[:len(self.hist) - 600]
        return (L * gains).astype(np.float32), (R * gains).astype(np.float32)


BUILTINS = {"Drive": Drive, "Filter": Filter, "Delay": Delay, "Crush": Crush, "Comp": Comp}


class ASR10Effect(Effect):
    """one of the Ensoniq ASR-10's effects, read from the user's own ROM (firmware/asr10/) and run on an emulation of its
    effects chip (asrfx.py, dsp/esp.c), at the chip's own rate. Parameters: the effect's preset, its own parameters (as
    the ASR-10 names and shows them), the bus the sound goes in on, and four modulation sources."""
    kind = "asr10"
    BUSES = ("FX1", "FX2", "DRY")
    CONTROLS = (("WHEEL", "WHEEL"), ("PEDAL", "PEDAL"), ("PRESSURE", "PRESS"), ("XCTRL", "XCTRL"))

    def __init__(self, name):
        import asrfx
        self.asrfx = asrfx
        lib = asrfx.library()
        if name not in lib: raise RuntimeError("ASR-10 effects need your ASR-10 ROM files in firmware/asr10/")
        self.fxdef = fx = lib[name]
        self.name, self.ident = f"{name}  (ASR-10)", ("asr10", name)
        self.preset, self.bus = 0, 0
        self.values = dict(fx.preset(0)) if fx.preset_names else {i: p.lo for i, p in enumerate(fx.params)}
        self.ctl = {k: 0 for _, k in self.CONTROLS}
        self.labels = ["PRESET"] + [p.name for p in fx.params] + ["INPUT BUS"] + [l for l, _ in self.CONTROLS]
        self.np = len(fx.params)
        self.run_ = asrfx.Running(fx, 0, self.values)
        rate = asrfx.ESP_RATES[fx.rate()]
        self.rs = None if abs(rate - SR) < 1 else (asrfx.Resampler(SR, rate), asrfx.Resampler(rate, SR))
        self.fifo = np.zeros((64 if self.rs else 0, 2))            # absorbs the rate change's uneven block sizes

    def n(self): return len(self.labels)

    def _range(self, i):
        if i == 0: return 0, max(0, len(self.fxdef.preset_names) - 1)
        if i <= self.np: p = self.fxdef.params[i - 1]; return p.lo, p.hi
        if i == self.np + 1: return 0, len(self.BUSES) - 1
        return 0, 127

    def _raw(self, i):
        if i == 0: return self.preset
        if i <= self.np: return self.values.get(i - 1, 0)
        if i == self.np + 1: return self.bus
        return self.ctl[self.CONTROLS[i - self.np - 2][1]]

    def get(self, i):
        lo, hi = self._range(i)
        return 0.0 if hi == lo else (self._raw(i) - lo) / float(hi - lo)

    def set(self, i, f):
        lo, hi = self._range(i)
        self.set_raw(i, int(round(lo + min(1.0, max(0.0, float(f))) * (hi - lo))))

    def set_raw(self, i, v):
        if v == self._raw(i): return
        if i == 0:                                                  # a preset: all its values, as on the machine
            if not self.fxdef.preset_names: return
            self.preset = v
            self.values = dict(self.fxdef.preset(v))
            st = self.asrfx.FxState(self.fxdef, v, self.values, self.run_.esp)
            st.controllers = dict(self.run_.state.controllers)
            self.run_.state, self.run_.preset, self.run_.values = st, v, dict(self.values)
            self.run_.apply()
        elif i <= self.np:
            self.values[i - 1] = v
            self.run_.set(i - 1, v)
        elif i == self.np + 1: self.bus = v
        else:
            k = self.CONTROLS[i - self.np - 2][1]
            self.ctl[k] = v
            self.run_.controller(k, v)

    def fmt(self, i):
        if i == 0: return self.fxdef.preset_names[self.preset][:16] if self.fxdef.preset_names else "-"
        if i <= self.np: return self.fxdef.fmt(i - 1, self.values)[:12]
        if i == self.np + 1: return self.BUSES[self.bus]
        return str(self._raw(i))

    def process(self, L, R):
        """a plain mix: in on INPUT BUS"""
        x = np.stack([np.asarray(L, np.float64), np.asarray(R, np.float64)], 1)
        buses = [np.zeros_like(x), np.zeros_like(x), np.zeros_like(x)]; buses[self.bus] = x
        return self._run(len(L), buses)

    def process_buses(self, L1, R1, L2, R2, L3, R3):
        """the ASR-10's own routing: each sound picked its bus (FX1, FX2, DRY) - as on the machine"""
        st = lambda a, b: np.stack([np.asarray(a, np.float64), np.asarray(b, np.float64)], 1)
        return self._run(len(L1), [st(L1, R1), st(L2, R2), st(L3, R3)])

    def _run(self, n, buses):
        if self.rs:
            if not hasattr(self, "rs_in"): self.rs_in = [self.asrfx.Resampler(SR, self.asrfx.ESP_RATES[self.fxdef.rate()]) for _ in range(3)]
            buses = [self.rs_in[k].process(b) for k, b in enumerate(buses)]   # all three every block: they stay in step
        y = self.run_.run(buses[0], buses[1], buses[2])
        if self.rs: y = self.rs[1].process(y)
        self.fifo = np.concatenate([self.fifo, y]) if len(self.fifo) else y
        if len(self.fifo) < n: self.fifo = np.concatenate([np.zeros((n - len(self.fifo), 2)), self.fifo])
        out, self.fifo = self.fifo[:n], self.fifo[n:]
        return out[:, 0].astype(np.float32), out[:, 1].astype(np.float32)

    def state(self):
        return {"kind": "asr10", "id": self.ident[1], "preset": self.preset, "bus": self.bus, "ctl": dict(self.ctl),
                "values": {str(k): int(v) for k, v in self.values.items()}, "params": [self.get(i) for i in range(self.n())]}

    def load_state(self, d):
        if "values" in d:
            if self.fxdef.preset_names: self.set_raw(0, int(d.get("preset", 0)))
            for k, v in d["values"].items():
                if int(k) < self.np: self.values[int(k)] = int(v); self.run_.state.set_value(int(k), int(v))
            self.run_.values = dict(self.values); self.run_.apply()
            self.bus = int(d.get("bus", 0)) % len(self.BUSES)
            for k, v in d.get("ctl", {}).items():
                if k in self.ctl: self.ctl[k] = int(v); self.run_.controller(k, int(v))
        else: super().load_state(d)


def asr10_effects():
    """the ASR-10 effects in the user's ROM (empty without one)"""
    try:
        import asrfx
        return list(asrfx.library().keys())
    except Exception:
        return []


class VST3Effect(Effect):
    kind = "vst3"
    def open_editor(self, parent=0, x=0, y=0): return None       # pedalboard cannot embed the plug-in window: build vst3host for that
    def __init__(self, path):
        if not HAVE_VST:
            raise RuntimeError("pedalboard is not installed (pip install pedalboard)")
        self.plugin = pedalboard.load_plugin(path)
        self.path = path
        self.name = os.path.basename(path.rstrip("/")).replace(".vst3", "")
        self.names = list(self.plugin.parameters.keys())[:64]
        self.labels = self.names
        self.ident = ("vst3", path)

    def n(self): return len(self.names)
    def _p(self, i): return self.plugin.parameters[self.names[i]]
    def get(self, i):
        try: return float(self._p(i).raw_value)
        except Exception: return 0.0
    def set(self, i, f):
        try: self._p(i).raw_value = float(min(1.0, max(0.0, f)))
        except Exception: pass
    def fmt(self, i):
        try: return str(self._p(i).string_value)[:12]
        except Exception: return f"{self.get(i) * 100:.0f}%"

    def process(self, L, R):
        out = self.plugin(np.stack([L, R]).astype(np.float32), SR, buffer_size=max(len(L), 128), reset=False)
        return out[0], out[1]

    def state(self):
        return {"kind": "vst3", "id": self.path, "params": [self.get(i) for i in range(self.n())],
                "names": list(self.names)}

    def load_state(self, d):
        saved = dict(zip(d.get("names", []), d.get("params", [])))
        for i, nm in enumerate(self.names):
            if nm in saved: self.set(i, saved[nm])


class HostedVST3(Effect):
    """A VST3 effect run by the bundled vst3host library (same interface as VST3Effect)."""
    kind = "vst3"
    BLOCK = 512
    def __init__(self, path):
        if HOST is None: raise RuntimeError("no VST3 host: pip install pedalboard, or run vst3host/build.sh")
        err = ctypes.create_string_buffer(256)
        self.h = HOST.vh_open(path.encode(), float(SR), self.BLOCK, err, 256)
        if not self.h: raise RuntimeError(err.value.decode(errors="replace") or "could not load " + path)
        self.path = path
        self.name = HOST.vh_name(self.h).decode(errors="replace") or os.path.basename(path).replace(".vst3", "")
        buf = ctypes.create_string_buffer(128)
        self.names = []
        for i in range(min(64, HOST.vh_param_count(self.h))):
            HOST.vh_param_title(self.h, i, buf, 128); self.names.append(buf.value.decode(errors="replace"))
        self.labels = self.names
        self.ident = ("vst3", path)
        self._buf = buf
        self.instrument = bool(HOST.vh_is_instrument(self.h))

    # --- instruments: notes in, audio out ---
    def note(self, offset, pitch, vel, on):
        """queue a note for the next render(): offset in samples from the start of that block"""
        HOST.vh_note(self.h, int(offset), int(pitch), int(vel), 1 if on else 0)

    def controller(self, number, value):
        """MIDI controller to the instrument: 0-127 CC (1 = mod wheel), 128 aftertouch, 129 pitch bend; value 0-1 (bend: 0.5 = centre).
        Returns False when the plug-in does not map that controller."""
        if not hasattr(HOST, "vh_midi_controller"): return False
        return bool(HOST.vh_midi_controller(self.h, int(number), float(value)))

    def render(self, frames):
        l = np.zeros(frames, np.float32); r = np.zeros(frames, np.float32)
        HOST.vh_process(self.h, l.ctypes.data, r.ctypes.data, frames)
        return l, r

    def n(self): return len(self.names)
    def get(self, i): return float(HOST.vh_get(self.h, i))
    def set(self, i, f): HOST.vh_set(self.h, i, float(min(1.0, max(0.0, f))))
    def fmt(self, i):
        if HOST.vh_param_string(self.h, i, self._buf, 128): return self._buf.value.decode(errors="replace")[:12]
        return f"{self.get(i) * 100:.0f}%"

    # --- the maker's own interface (needs an X11 display: DISPLAY must be set) ---
    def open_editor(self, parent=0, x=0, y=0):
        """Shows the plug-in's own window. Returns (window id, width, height) or None if it has none / no X display."""
        if not os.environ.get("DISPLAY"): return None
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        win = HOST.vh_editor_open(self.h, parent, x, y, ctypes.byref(w), ctypes.byref(h))
        return (win, w.value, h.value) if win else None
    def editor_idle(self): HOST.vh_editor_idle(self.h)
    def move_editor(self, x, y): HOST.vh_editor_move(self.h, int(x), int(y))
    def scale_editor(self, factor): return bool(HOST.vh_editor_scale(self.h, float(factor)))
    def editor_size(self):
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        return (w.value, h.value) if HOST.vh_editor_size(self.h, ctypes.byref(w), ctypes.byref(h)) else None
    def close_editor(self): HOST.vh_editor_close(self.h)

    def process(self, L, R):
        l = np.ascontiguousarray(L, dtype=np.float32).copy(); r = np.ascontiguousarray(R, dtype=np.float32).copy()
        HOST.vh_process(self.h, l.ctypes.data, r.ctypes.data, len(l))
        return l, r

    def state(self):
        return {"kind": "vst3", "id": self.path, "params": [self.get(i) for i in range(self.n())], "names": list(self.names)}

    def load_state(self, d):
        saved = dict(zip(d.get("names", []), d.get("params", [])))
        for i, nm in enumerate(self.names):
            if nm in saved: self.set(i, saved[nm])

    def __del__(self):
        try:
            if HOST is not None and self.h: HOST.vh_close(self.h); self.h = None
        except Exception: pass


def plugin_is_instrument(path):
    """from the bundle's moduleinfo.json (no loading needed); unknown -> False"""
    try:
        txt = open(os.path.join(path, "Contents", "Resources", "moduleinfo.json"), encoding="utf-8", errors="replace").read()
        i = txt.find('"Category": "Audio Module Class"')
        sub = txt[i:i + 600] if i >= 0 else txt
        j = sub.find('"Sub Categories"')
        return j >= 0 and "Instrument" in sub[j:sub.find("]", j)]
    except OSError:
        return False


def discover_instruments():
    """[(path, name)] of the VST3 instruments found (synths, samplers) - for PLUGIN tracks"""
    out, seen = [], set()
    if HOST is None: return out
    for d in VST_DIRS:
        for p in sorted(glob.glob(os.path.join(os.path.expanduser(d), "**", "*.vst3"), recursive=True)):
            if p not in seen and not p.endswith("/Contents") and plugin_is_instrument(p):
                seen.add(p); out.append((p, os.path.basename(p).replace(".vst3", "")))
    return out


def create_instrument(path):
    if HOST is None: raise RuntimeError("VST3 instruments need vst3host (cd vst3host && ./build.sh)")
    return HostedVST3(path)


def discover():
    """list of (kind, ident, display name): built-ins first, then every .vst3 effect found (instruments are listed separately)."""
    items = [("builtin", n, n) for n in BUILTINS]
    items += [("asr10", n, "ASR-10  " + n) for n in asr10_effects()]
    if HAVE_VST:
        seen = set()
        for d in VST_DIRS:
            for p in sorted(glob.glob(os.path.join(os.path.expanduser(d), "**", "*.vst3"), recursive=True)):
                if p not in seen and not p.endswith("/Contents") and not plugin_is_instrument(p):
                    seen.add(p); items.append(("vst3", p, "VST3  " + os.path.basename(p).replace(".vst3", "")))
    return items


def create(kind, ident):
    if kind == "builtin":
        return BUILTINS[ident]()
    if kind == "asr10":
        return ASR10Effect(ident)
    return HostedVST3(ident) if HOST is not None else VST3Effect(ident)


def from_state(d):
    fx = create(d.get("kind", "builtin"), d["id"])
    fx.load_state(d)
    return fx
