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


def _load(p):
    lib = ctypes.CDLL(p)
    lib.ss_render.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
                              ctypes.c_float, ctypes.c_int, ctypes.c_int]
    lib.ss_render.restype = ctypes.c_int
    return lib


_SO = os.path.join(HERE, "stretch", "libstretch.so")
for p in (_SO, "libstretch.so"):
    try: _lib = _load(p); break
    except OSError: _lib = None
if _lib is None and os.path.exists(os.path.join(HERE, "stretch", "build.sh")):
    # missing, or built for another machine (an x86 file copied onto the Pi): build it here, once (needs g++ and git)
    import subprocess, sys
    print("WARP: building the time-stretch library for this machine (once, about a minute)...", file=sys.stderr)
    try:
        if os.path.exists(_SO): os.replace(_SO, _SO + ".other")
        subprocess.run(["sh", os.path.join(HERE, "stretch", "build.sh")], check=True, capture_output=True, timeout=900)
        _lib = _load(_SO)
    except Exception as ex:
        print(f"WARP: could not build it ({ex}); using the simple fallback (pitch still follows SEMI / FINE)", file=sys.stderr)
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
    return _fallback(x, n_out, semis)


def _fallback(x, n_out, semis):
    """without the library: pitch by resampling, length by overlapping grains (rougher than Signalsmith, but the pitch
    follows SEMI / FINE and the length follows the tempo, as it should)"""
    if abs(semis) > 1e-3:
        r = 2.0 ** (semis / 12.0)                          # up: fewer samples (higher), then stretched back to n_out
        m = max(2, int(round(len(x) / r)))
        x = np.interp(np.linspace(0, len(x) - 1, m), np.arange(len(x)), x).astype(np.float32)
    if abs(len(x) - n_out) < 2:
        return np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)
    G, T = 2048, 400                                       # WSOLA: each grain starts where it best continues the last one
    H = G // 2
    win = np.hanning(G).astype(np.float32)
    ratio = len(x) / float(n_out)
    xp = np.concatenate([np.zeros(T, np.float32), x, np.zeros(G + 2 * T + H, np.float32)])
    out = np.zeros(n_out + G, np.float32); norm = np.zeros(n_out + G, np.float32)
    prev = None
    for o in range(0, n_out, H):
        i = int(o * ratio) + T
        if prev is None: best = i
        else:
            tpl = xp[prev + H:prev + H + G]
            seg = xp[i - T:i + T + G]
            if np.any(tpl):
                n_ = 1 << int(np.ceil(np.log2(len(seg) + G)))
                cc = np.fft.irfft(np.fft.rfft(seg, n_) * np.conj(np.fft.rfft(tpl, n_)), n_)[:2 * T + 1]
                best = i - T + int(np.argmax(cc))
            else: best = i
        out[o:o + G] += xp[best:best + G] * win; norm[o:o + G] += win
        prev = best
    out = out[:n_out] / np.maximum(norm[:n_out], 1e-3)
    return out.astype(np.float32)
