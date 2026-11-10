"""
warp.py - time-stretch / pitch-shift for WARP pads (pads that follow the sequence tempo, like an MPC's warp).

render(x, n_out, semis) stretches a mono float32 region to exactly n_out samples, transposed by `semis`, with
Signalsmith Stretch (MIT, built by stretch/build.sh into stretch/libstretch.so). Without the library it falls back
to plain resampling: the timing still follows the tempo but the pitch changes with it (like tape), and ENGINE says so.
"""
import ctypes, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_lib = None
for p in (os.path.join(HERE, "stretch", "libstretch.so"), "libstretch.so"):
    try:
        _lib = ctypes.CDLL(p)
        _lib.ss_render.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
                                   ctypes.c_float, ctypes.c_int, ctypes.c_int]
        _lib.ss_render.restype = ctypes.c_int
        break
    except OSError:
        _lib = None
ENGINE = "signalsmith" if _lib is not None else "resample"
QUALITY = 1                                    # 1 = Signalsmith presetDefault, 0 = presetCheaper (about half the CPU)


def render(x, n_out, semis=0.0, sr=44100):
    x = np.ascontiguousarray(x, dtype=np.float32)
    n_out = max(1, int(n_out))
    if len(x) < 2: return np.zeros(n_out, np.float32)
    if _lib is not None:
        out = np.zeros(n_out, np.float32)
        ok = _lib.ss_render(x.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(x),
                            out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), n_out, float(semis), int(sr), QUALITY)
        if ok and np.isfinite(out).all(): return out
    return np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)
