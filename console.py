"""
console.py - the MIXER console: a channel strip per program, two effect returns and the master section.

Signal flow (the American console artboard, 'desk C'):
  pads -> pad insert -> PROGRAM STRIP: inserts 1-4 -> EQ (5 bands) -> fader + pan -> mute / solo
                                         -> sends A / B (post-fader) -> RETURN A / B (2 inserts, EQ, fader, pan)
                                         -> group: 1-2 or 3-4 (two stereo group buses, each with EQ / fader / mute), or MIX
  GROUP 1-2 / 3-4 -> the mix, or a direct output pair 3-4 / 5-6 / 7-8
  MIX -> MASTER: bus inserts 1-2 -> EQ -> master fader -> limiter -> outs 1-2 (DIM: monitoring only, -20 dB)

Everything here is plain numpy plus dspfast.sos (the biquads in C). A strip at its defaults (flat EQ, 0 dB, centre, no
sends, MIX) costs one multiply, so programs that do not use the console cost nothing extra.
"""
import math
import numpy as np

SR = 44100.0
OUTS = ("1-2", "3-4", "MIX")                           # where a strip goes: group bus 1-2, group bus 3-4, or straight to the mix
GROUP_OUTS = ("MIX", "3-4", "5-6", "7-8")               # where a group bus goes: the mix, or a direct output pair
OUT_CODE = {"MIX": 0, "3-4": 2, "5-6": 3, "7-8": 4}     # engine 'routed' codes (1-4 = stereo pairs 1-2 .. 7-8)
EQ_TYPES = ("HP", "LOW SHELF", "BELL", "HIGH SHELF", "BELL")
EQ_DEFAULT = [dict(on=False, type="HP", freq=80.0, gain=0.0, q=0.71, slope=12),
              dict(on=False, type="LOW SHELF", freq=200.0, gain=0.0, q=0.71),
              dict(on=False, type="BELL", freq=1000.0, gain=0.0, q=0.9),
              dict(on=False, type="HIGH SHELF", freq=7000.0, gain=0.0, q=0.71),
              dict(on=False, type="BELL", freq=3000.0, gain=0.0, q=1.0)]
FADER_MAX_DB = 10.0


def db(v): return 20.0 * math.log10(max(1e-6, v))
def undb(d): return 10.0 ** (d / 20.0)


def fader_to_gain(f):
    """fader position 0..1 -> gain. 0.75 = 0 dB, top = +10 dB, bottom = off (a console-style taper)"""
    if f <= 0.0005: return 0.0
    if f >= 0.75: return undb((f - 0.75) / 0.25 * FADER_MAX_DB)
    return undb(-60.0 * (1.0 - f / 0.75) ** 1.6)


def gain_to_fader(g):
    if g <= 0: return 0.0
    d = db(g)
    if d >= 0: return 0.75 + min(1.0, d / FADER_MAX_DB) * 0.25
    return 0.75 * (1.0 - min(1.0, (-d / 60.0)) ** (1 / 1.6))


def fader_label(g):
    if g <= 0: return "-inf"
    d = db(g)
    return f"{d:+.1f}".replace("+0.0", "0.0").replace("-0.0", "0.0")


# ---------------------------------------------------------------- EQ (RBJ cookbook biquads)
def _biquad(kind, f, gain_db, q):
    f = min(max(f, 10.0), SR * 0.45)
    A = 10 ** (gain_db / 40.0); w = 2 * math.pi * f / SR; cw, sw = math.cos(w), math.sin(w)
    al = sw / (2 * max(q, 0.1))
    if kind == "HP":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + al, -2 * cw, 1 - al]
    elif kind == "LP":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + al, -2 * cw, 1 - al]
    elif kind == "BELL":
        b = [1 + al * A, -2 * cw, 1 - al * A]; a = [1 + al / A, -2 * cw, 1 - al / A]
    else:
        sq = 2 * math.sqrt(A) * al
        if kind == "LOW SHELF":
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:                                            # HIGH SHELF
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    return [b[0] / a[0], b[1] / a[0], b[2] / a[0], a[1] / a[0], a[2] / a[0]]


def eq_sections(bands):
    secs = []
    for k, b in enumerate(bands):
        if not b.get("on"): continue
        t = b["type"]
        if t == "HP":
            n = 2 if b.get("slope", 12) >= 24 else 1
            for _ in range(n): secs.append(_biquad("HP", b["freq"], 0.0, 0.71))
        elif abs(b.get("gain", 0.0)) > 0.05:
            secs.append(_biquad(t, b["freq"], b["gain"], b.get("q", 0.71)))
    return secs


def eq_response(bands, freqs):
    """the EQ's magnitude in dB at freqs (for the curve on screen)"""
    z = np.exp(-2j * np.pi * np.asarray(freqs, float) / SR); h = np.ones(len(z), complex)
    for b0, b1, b2, a1, a2 in eq_sections(bands):
        h *= (b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-6))


def eq_active(bands): return any(b.get("on") for b in bands)


class Strip:
    """one console channel: a program strip, a return, or the master. fx / fx_bypass are slot lists (engine.FxSlot works on
    them like on a program's inserts)."""
    def __init__(self, name, nfx=0):
        self.name = name
        self.fx, self.fx_bypass = [None] * nfx, [False] * nfx
        self.level, self.pan = 1.0, 0.0                    # gain (1 = 0 dB), pan -1..1
        self.mute = self.solo = False
        self.sends = [0.0, 0.0]                            # A, B: 0..1 (post-fader)
        self.out = "MIX"
        self.eq = [dict(b) for b in EQ_DEFAULT]
        self.eq_on = True
        self.eq_gain = 0.0                                 # the EQ's OUTPUT gain, dB (-12 .. +12)
        self.meter = [0.0, 0.0]                            # peak L, R (decays in the UI)
        self._st, self._key = None, None

    # ---- save / load
    def state(self):
        return {"level": self.level, "pan": self.pan, "mute": self.mute, "solo": self.solo, "sends": list(self.sends),
                "out": self.out, "eq": self.eq, "eq_on": self.eq_on, "eq_gain": self.eq_gain}

    def load(self, d):
        if not d: return
        self.level = float(d.get("level", 1.0)); self.pan = float(d.get("pan", 0.0))
        self.mute, self.solo = bool(d.get("mute", False)), bool(d.get("solo", False))
        self.sends = [float(x) for x in (d.get("sends") or [0.0, 0.0])][:2] + [0.0] * max(0, 2 - len(d.get("sends") or []))
        self.out = d.get("out", "MIX") if d.get("out", "MIX") in OUTS + GROUP_OUTS else "MIX"
        eq = d.get("eq")
        if eq and len(eq) == 5: self.eq = [dict(EQ_DEFAULT[k], **b) for k, b in enumerate(eq)]
        self.eq_on = bool(d.get("eq_on", True))
        self.eq_gain = float(d.get("eq_gain", 0.0))

    def is_default(self):
        return (abs(self.level - 1.0) < 1e-6 and abs(self.pan) < 1e-6 and not self.mute and not any(self.sends)
                and self.out == "MIX" and not (self.eq_on and (eq_active(self.eq) or abs(self.eq_gain) > 1e-6)))

    # ---- audio
    def run_eq(self, L, R, sos):
        if not self.eq_on: return L, R
        if abs(self.eq_gain) > 1e-6:                       # OUTPUT: after the bands
            g = undb(self.eq_gain)
            L, R = self._run_bands(L, R, sos)
            return L * g, R * g
        return self._run_bands(L, R, sos)

    def _run_bands(self, L, R, sos):
        if not eq_active(self.eq): return L, R
        key = repr(self.eq)
        if key != self._key:
            secs = eq_sections(self.eq)
            self._secs, self._key = secs, key
            if self._st is None or len(self._st[0]) != 2 * len(secs):
                self._st = [np.zeros(2 * len(secs), np.float32), np.zeros(2 * len(secs), np.float32)]
        if not self._secs: return L, R
        L = sos(np.array(L, np.float32), self._secs, self._st[0]); R = sos(np.array(R, np.float32), self._secs, self._st[1])
        return L, R

    def gains(self):
        """level and pan as left / right gains (constant power, centre = unity per side)"""
        g = self.level
        p = max(-1.0, min(1.0, self.pan))
        return g * min(1.0, 1.0 - p), g * min(1.0, 1.0 + p)

    def meter_in(self, L, R):
        if len(L):
            self.meter[0] = max(self.meter[0], float(np.abs(L).max())); self.meter[1] = max(self.meter[1], float(np.abs(R).max()))
