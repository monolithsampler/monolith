"""mpchw.py - the analog side of the three MPCs, from Akai's service manuals: what happens to a sound on its way into
the machine (input filter, converter) and on its way out (DAC, reconstruction filter, output stage). The chips
themselves are in dsp/akai.c (mpcvoice.py); this is everything around them.

  MPC60 (service manual, parts list + ADC schematic): a 12-bit machine at a fixed 40 kHz. Its input and every output go
    through a Toko 258BLR-5326N LC low-pass module, listed as "FILTER LC 258BLR-5326N 18KHZ" - one before the ADC (a
    PCM77P in a successive-approximation loop), one on each of the 8 individual outs (voice board) and one on each of
    L, R and mix (ADC board). The DAC is a PCM54HP fed at 40 kHz with no oversampling, so the output is a zero-order
    hold (sinc droop: -1.0 dB at 10 kHz, -2.9 dB at 18 kHz) before the LC filter. Spec sheet: "20 Hz ~ 18 kHz".
    Not in the manual: the module's own curve. Modelled as a 7th-order elliptic (0.5 dB ripple to 18 kHz, -50 dB
    stopband), the usual build of these LC audio modules - very steep: -19 dB at 19 kHz, -40 dB at 20 kHz.
  MPC3000 (parts list; this manual has no schematics): an AK5328 delta-sigma ADC (its own digital anti-alias filter)
    and an SM5841 8x-oversampling digital filter in front of PCM69 18-bit DACs. So in and out are flat to 20 kHz with
    no hold droop: its analog path is close to transparent - what it sounds like is its chip.
  MPC2000XL (analog board schematic L6044801): an AK5340 delta-sigma ADC in (transparent), and out a PCM69AP-4 fed
    straight at 44.1 kHz - no oversampling filter anywhere on its boards - so a zero-order hold (-3.2 dB at 20 kHz),
    then: an I/V stage with 4.99K || 2200 pF (a pole at 14.5 kHz), a unity Sallen-Key (1.91K, 5.76K, 10 nF, 470 pF:
    22 kHz, Q ~2, which lifts some of that back), then the volume stage and a balanced driver (10K || 220 pF poles at
    72 kHz). Net: a gentle, real top-end roll-off that the 3000 does not have.
"""
import numpy as np

SR_OUT = 44100.0

# ---- MPC60: the Toko 18 kHz module (estimated curve, see above): analog zeros / poles in Hz, gain normalised at DC
_TZ = np.array([35509.039, 22981.072, 20482.715])
_TP = np.array([-6751.918 + 0j, -4613.295 + 11157.297j, -1824.633 + 16443.516j, -429.65 + 18077.405j])


def toko_18k(f):
    s = 2j * np.pi * np.asarray(f, float)
    num = np.ones_like(s); den = np.ones_like(s)
    for z in _TZ:
        w = 2 * np.pi * z
        num = num * (s * s + w * w) / (w * w)
    for p in _TP:
        q = 2 * np.pi * p
        if q.imag == 0: den = den * (1 - s / q)
        else: den = den * (1 - s / q) * (1 - s / np.conj(q))
    return num / den


def zoh(f, fs):
    """a DAC holding each value for one sample period (no oversampling): sinc droop and half a sample of delay"""
    f = np.asarray(f, float)
    return np.sinc(f / fs) * np.exp(-1j * np.pi * f / fs)


def xl_out(f):
    """MPC2000XL main outs after the DAC: I/V pole, Sallen-Key, two 72 kHz poles (values from its analog schematic)"""
    s = 2j * np.pi * np.asarray(f, float)
    iv = 1 / (1 + s * 4.99e3 * 2200e-12)
    R1, R2, C1, C2 = 1.91e3, 5.76e3, 10e-9, 470e-12          # C1 feedback, C2 to ground
    sk = 1 / (1 + s * C2 * (R1 + R2) + s * s * R1 * R2 * C1 * C2)
    hf = 1 / (1 + s * 10e3 * 220e-12) ** 2
    return iv * sk * hf


def response(machine, f, side="out"):
    """the analog path's response for a machine ('MPC60', 'MPC3000', 'MPC2000XL'): side 'in' (sampling) or 'out'"""
    if machine == "MPC60":
        return toko_18k(f) if side == "in" else zoh(f, 40000.0) * toko_18k(f)
    if machine == "MPC2000XL" and side == "out":
        return zoh(f, 44100.0) * xl_out(f)
    return np.ones(len(np.atleast_1d(f)), complex)


_FIR = {}


def fir(machine, side="out", sr=SR_OUT, ntap=63):
    """a response as a FIR at sr (its low-frequency delay taken out, so the sound stays on time); None if flat"""
    key = (machine, side, sr, ntap)
    if key in _FIR: return _FIR[key]
    if machine == "MPC3000" or (machine == "MPC2000XL" and side == "in"):
        _FIR[key] = None; return None
    nf = 4096
    f = np.fft.rfftfreq(nf, 1 / sr)
    h = response(machine, f, side)
    ph = np.unwrap(np.angle(response(machine, [200.0, 400.0], side)))
    d0 = round(-(ph[1] - ph[0]) / (2 * np.pi * 200.0) * sr)
    imp = np.fft.irfft(h * np.exp(2j * np.pi * f * d0 / sr), nf)
    half = ntap // 2
    taps = np.concatenate((imp[-half:], imp[:half + 1])) * np.kaiser(ntap, 5.0)
    _FIR[key] = (taps / taps.sum()).astype(np.float32)
    return _FIR[key]


def _bilinear(zeros, poles, fs, fw):
    """analog zeros / poles (rad/s; zeros may be fewer) -> digital sections [b0 b1 b2 a1 a2], prewarped at fw, DC gain 1"""
    kw = 2 * np.pi * fw / np.tan(np.pi * fw / fs)
    zd = [(kw + z) / (kw - z) for z in zeros] + [-1.0 + 0j] * (len(poles) - len(zeros))
    pd = [(kw + p) / (kw - p) for p in poles]
    def pairs(r):
        r = list(r); out = []
        while r:
            z = r.pop(0)
            if abs(np.imag(z)) > 1e-9:
                j = min(range(len(r)), key=lambda i: abs(r[i] - np.conj(z))); c = r.pop(j); out.append((z, c))
            else:
                j = next((i for i in range(len(r)) if abs(np.imag(r[i])) <= 1e-9), None)
                out.append((z, r.pop(j)) if j is not None else (z, None))
        return out
    zp, pp = pairs(sorted(zd, key=lambda z: -abs(np.imag(z)))), pairs(sorted(pd, key=lambda z: -abs(np.imag(z))))
    secs = []
    for k, (p1, p2) in enumerate(pp):
        z1, z2 = zp[k] if k < len(zp) else (-1.0, None)
        if p2 is None:
            b = np.real([1, -z1, 0]); a = np.real([1, -p1, 0])
        else:
            b = np.real(np.poly([z1, z2 if z2 is not None else -1.0])); a = np.real(np.poly([p1, p2]))
        g = a.sum() / b.sum()
        secs.append([b[0] * g, b[1] * g, b[2] * g, a[1], a[2]])
    return np.array(secs, float)


def _zoh_fir(fdac, sr=SR_OUT, ntap=7, fmax=20000.0):
    """a short symmetric FIR with the hold's sinc droop up to fmax (least squares)"""
    f = np.linspace(0, fmax, 400); want = np.sinc(f / fdac)
    half = ntap // 2
    A = np.stack([np.ones_like(f)] + [2 * np.cos(2 * np.pi * f * k / sr) for k in range(1, half + 1)], 1)
    c = np.linalg.lstsq(A, want, rcond=None)[0]
    h = np.concatenate((c[:0:-1], c)); return (h / h.sum()).astype(np.float32)


_STAGE = {}


def stage(machine):
    """(sections at 44.1 kHz, droop FIR) of a machine's output path, or None if it is flat (MPC3000)"""
    if machine not in _STAGE: _STAGE[machine] = _stage(machine)
    return _STAGE[machine]


def _stage(machine):
    if machine == "MPC60":
        z = [2j * np.pi * x for x in _TZ] + [-2j * np.pi * x for x in _TZ]
        p = [2 * np.pi * x for x in _TP] + [2 * np.pi * np.conj(x) for x in _TP if x.imag != 0]
        return _bilinear(z, p, SR_OUT, 18000.0), _zoh_fir(40000.0, ntap=11, fmax=18000.0)
    if machine == "MPC2000XL":                       # smooth all the way up (its Sallen-Key sits at 22 kHz, right at our
        return np.zeros((0, 5)), fir("MPC2000XL")    # Nyquist): a FIR of the exact analog curve, hold included

    return None


def stage_response(machine, f):
    st = stage(machine)
    z = np.exp(-2j * np.pi * np.asarray(f, float) / SR_OUT); h = np.ones(len(z), complex)
    if st is None: return h
    for b0, b1, b2, a1, a2 in st[0]: h *= (b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z)
    fir_ = st[1]; half = len(fir_) // 2
    h *= sum(fir_[k] * z ** (k - half) for k in range(len(fir_)))
    return h


class OutStage:
    """one voice's output path, streaming (state kept between blocks)"""
    def __init__(self, machine):
        import dspfast
        self.df = dspfast
        self.sos, self.fir = stage(machine)
        self.st = np.zeros(2 * len(self.sos), np.float32)
        self.z = np.zeros(len(self.fir) - 1, np.float32)

    def process(self, x):
        x = np.asarray(x, np.float32)
        if not len(x): return x
        buf = np.concatenate((self.z, x)); self.z = buf[-(len(self.fir) - 1):].copy()
        y = np.convolve(buf, self.fir, "valid").astype(np.float32)
        return self.df.sos(y, self.sos, self.st) if len(self.sos) else y


if __name__ == "__main__":
    f = np.array([1000, 5000, 10000, 13000, 15000, 18000, 19000, 20000])
    for m in ("MPC60", "MPC3000", "MPC2000XL"):
        print(m, "analog:", " ".join("%dk %+.1f" % (a / 1000, 20 * np.log10(abs(b))) for a, b in zip(f, response(m, f))))
        print(" " * len(m), "model: ", " ".join("%dk %+.1f" % (a / 1000, 20 * np.log10(abs(b))) for a, b in zip(f, stage_response(m, f))))
