"""dspfast.py - the per-voice filter and the master low-pass in C (dsp/libvoicefx.so, built by dsp/build.sh or on first
import if a C compiler is there), with a plain-Python fallback so everything still works without it (slower)."""
import ctypes, os, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(HERE, "dsp", "libvoicefx.so")
_lib = None


def _load():
    global _lib
    src = os.path.join(HERE, "dsp", "voicefx.c")
    if (not os.path.exists(_LIB) or os.path.getmtime(_LIB) < os.path.getmtime(src)) and os.path.exists(src):
        try: subprocess.run(["sh", os.path.join(HERE, "dsp", "build.sh")], check=True, capture_output=True, timeout=900)
        except Exception: pass
    try:
        lib = ctypes.CDLL(_LIB)
        F, I, P = ctypes.c_float, ctypes.c_int, ctypes.POINTER(ctypes.c_float)
        lib.svf_block.argtypes = [P, I, P, F, F, F, I, F]
        lib.onepole_block.argtypes = [P, I, P, F]
        lib.sos_block.argtypes = [P, I, ctypes.POINTER(ctypes.c_double), I, P]
        _lib = lib
    except OSError:
        _lib = None


_load()
FAST = _lib is not None
_fp = lambda a: a.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def svf(x, state, f0, f1, res, mode, sr):
    """filter x (float32, in place) with a state-variable filter; state = float32[2]; mode 1 LP, 2 HP, 3 BP"""
    x = np.ascontiguousarray(x, dtype=np.float32)
    if _lib is not None:
        _lib.svf_block(_fp(x), len(x), _fp(state), float(f0), float(f1), float(res), int(mode), float(sr))
        return x
    import math
    ic1, ic2 = float(state[0]), float(state[1])
    k = 2.0 - 1.94 * min(1.0, max(0.0, res))
    n = len(x)
    out = x.tolist()
    l0, l1 = math.log(f0), math.log(f1)
    for i in range(n):
        f = min(0.45 * sr, math.exp(l0 + (l1 - l0) * (i / (n - 1) if n > 1 else 0)))
        g = math.tan(math.pi * f / sr)
        a1 = 1.0 / (1.0 + g * (g + k)); a2 = g * a1; a3 = g * a2
        v3 = out[i] - ic2; v1 = a1 * ic1 + a2 * v3; v2 = ic2 + a2 * ic1 + a3 * v3
        ic1, ic2 = 2 * v1 - ic1, 2 * v2 - ic2
        out[i] = v2 if mode == 1 else (out[i] - k * v1 - v2 if mode == 2 else v1)
    state[0], state[1] = ic1, ic2
    x[:] = out
    return x


def onepole(x, ystate, a):
    """in-place one-pole low-pass; ystate = float32[1]"""
    if _lib is not None:
        x = np.ascontiguousarray(x, dtype=np.float32)
        _lib.onepole_block(_fp(x), len(x), _fp(ystate), float(a))
        return x
    y, out = float(ystate[0]), x.tolist()
    for k in range(len(out)):
        y += a * (out[k] - y); out[k] = y
    x[:] = out; ystate[0] = y
    return x


def sos(x, sections, state):
    """filter x (float32, in place) through biquad sections [[b0 b1 b2 a1 a2], ...]; state = float32[2 * sections]"""
    x = np.ascontiguousarray(x, dtype=np.float32)
    c = np.ascontiguousarray(np.asarray(sections, np.float64).ravel())
    if _lib is not None:
        _lib.sos_block(_fp(x), len(x), c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), len(c) // 5, _fp(state))
        return x
    for q in range(len(c) // 5):
        b0, b1, b2, a1, a2 = c[5 * q:5 * q + 5]; z0, z1 = float(state[2 * q]), float(state[2 * q + 1])
        out = x.tolist()
        for i, v in enumerate(out):
            w = b0 * v + z0; z0 = b1 * v - a1 * w + z1; z1 = b2 * v - a2 * w; out[i] = w
        x[:] = out; state[2 * q], state[2 * q + 1] = z0, z1
    return x
