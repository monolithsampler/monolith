"""sp1200hw.py - the SP-1200's analog circuits, worked out from the component values in E-mu's service manual
(SP1200 MAIN schematic, doc SK103, 1987: page 14 "Input ADC", 15 "DACs and Demux", 16 "Dynamic Filters",
17 "Output Channels"; trims on manual pages 33-34), and the voice renderer that runs them (dsp/sp1200.c).

Run it (python3 sp1200hw.py [--plot out.png]) to print the responses. Op-amps are taken as ideal; parts at their
marked values (the real ones are 1 %, 5 % and 10 % parts, so any one unit differs a little). Only numpy is needed.
"""
import ctypes, math, os, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SP_SR = 20e6 / 768                 # the sample clock: 26,041.67 Hz
OS = 4                             # the hold is run at 4x that (as Yeh et al. 2007 model it)
FS4 = SP_SR * OS
K_, n_ = 1e3, 1e-9

# ---------------------------------------------------------------------------------------------------------------
# 1. input anti-alias filter (schematic p. 14): three two-integrator loops (summer -> lossy integrator -> integrator,
#    fed back to the summer); each loop's three outputs are summed, through weighted resistors, by the next loop's
#    summer (that sum places the notches); then a final summing amp with its own pole. 3 x 2 + 1 = 7th order, the
#    manual's "42 dB per octave". The result is an elliptic low-pass: -3 dB at ~13.2 kHz, ~1.5 dB passband ripple,
#    notches at ~16.5, 18.5 and 22.5 kHz, ~-63 dB beyond. All capacitors 1000 pF poly.
# ---------------------------------------------------------------------------------------------------------------
IN_PARTS = dict(R36=10.0*K_, R40=10.0*K_, R34=10.0*K_, R44=19.1*K_, R50=21.0*K_, C84=1*n_, R27=19.1*K_, C66=1*n_,
                R22=107*K_, R23=118*K_, R25=14.7*K_, R20=10.0*K_, R18=10.0*K_,
                R26=13.3*K_, R28=43.2*K_, C67=1*n_, R24=13.3*K_, C65=1*n_,
                R16=124*K_, R15=402*K_, R13=47.5*K_, R11=10.0*K_, R17=10.0*K_,
                R9=12.1*K_, R7=162*K_, C53=1*n_, R14=12.1*K_, C55=1*n_,
                R8=6.19*K_, R10=82.5*K_, R12=3.92*K_, R6=31.6*K_, C51=1*n_)


def input_filter(f, c=IN_PARTS):
    """complex response of the input filter at frequencies f (Hz), normalised to 0 dB at DC"""
    f = np.atleast_1d(np.asarray(f, float))
    out = np.empty(len(f), complex)
    S1, L1, I1, S2, L2, I2, S3, L3, I3, O = range(10)
    for q, fi in enumerate(np.concatenate(([0.0], f))):
        s = 2j * np.pi * max(fi, 1e-3)
        par = lambda R, C: R / (1 + s * R * C)
        integ = lambda C: 1 / (s * C)
        A = np.eye(10, dtype=complex); b = np.zeros(10, complex)    # each stage: out = -Zf * sum(Vin_i / R_i)
        A[S1, I1] = c["R40"] / c["R34"]; b[S1] = -c["R40"] / c["R36"]
        A[L1, S1] = par(c["R50"], c["C84"]) / c["R44"]
        A[I1, L1] = integ(c["C66"]) / c["R27"]
        for j, r in ((S1, "R22"), (L1, "R23"), (I1, "R25"), (I2, "R20")): A[S2, j] = c["R18"] / c[r]
        A[L2, S2] = par(c["R28"], c["C67"]) / c["R26"]
        A[I2, L2] = integ(c["C65"]) / c["R24"]
        for j, r in ((S2, "R16"), (L2, "R15"), (I2, "R13"), (I3, "R11")): A[S3, j] = c["R17"] / c[r]
        A[L3, S3] = par(c["R7"], c["C53"]) / c["R9"]
        A[I3, L3] = integ(c["C55"]) / c["R14"]
        for j, r in ((S3, "R8"), (L3, "R10"), (I3, "R12")): A[O, j] = par(c["R6"], c["C51"]) / c[r]
        v = np.linalg.solve(A, b)[O]
        if q == 0: h0 = v
        else: out[q - 1] = v / h0
    return out


# ---------------------------------------------------------------------------------------------------------------
# 2. fixed output filters, channels 3-6 (p. 17): an RC pole loading a Sallen-Key stage (3rd order), then a unity-gain
#    Sallen-Key (2nd order) = 5th order. Every channel: C 4700 pF, Sallen-Key feedback caps 0.01 uF, ground caps
#    1000 pF; the resistors get a step smaller (brighter) from channel 3 to 6: -3 dB at ~7.9, 9.6, 11.6, 13.1 kHz.
# ---------------------------------------------------------------------------------------------------------------
OUT_PARTS = {   # SP channel: RC, SK1 a, SK1 b, SK2 a, SK2 b
    3: (7.5*K_, 3.6*K_, 6.2*K_, 6.2*K_, 6.2*K_),     # R81 R88 R110 R95 R122
    4: (6.2*K_, 3.0*K_, 5.1*K_, 5.1*K_, 5.1*K_),     # R80 R87 R109 R94 R121
    5: (5.1*K_, 2.4*K_, 4.3*K_, 4.3*K_, 4.3*K_),     # R79 R86 R108 R93 R120
    6: (4.3*K_, 2.2*K_, 3.9*K_, 3.9*K_, 3.9*K_),     # R78 R85 R107 R92 R119
}
C_RC, C_FB, C_GND = 4700e-12, 0.01e-6, 1000e-12
_P = np.polynomial.Polynomial


def out_filter_den(ch):
    """denominator of a fixed output filter as a polynomial in s (the numerator is 1)"""
    R1, R2, R3, Ra, Rb = OUT_PARTS[ch]
    s = _P([0, 1])
    Vc = _P([1])                                          # section 1, solved back from its output
    Vb = Vc * (1 + s * R3 * C_GND)
    Va = R2 * (Vb * (1 / R2 + 1 / R3 + s * C_FB) - Vc * (1 / R3 + s * C_FB))
    Vin = R1 * (Va * (1 / R1 + s * C_RC + 1 / R2) - Vb / R2)
    return Vin * (1 + s * C_GND * (Ra + Rb) + s * s * Ra * Rb * C_FB * C_GND)


def out_filter(f, ch):
    s = 2j * np.pi * np.asarray(f, float)
    return 1.0 / out_filter_den(ch)(s)


def _bilinear_sos(den, fs, fw):
    """all-pole analog filter 1/den(s) -> digital sections [b0 b1 b2 a1 a2] at fs (prewarped at fw), DC gain 1"""
    kw = 2 * np.pi * fw / math.tan(np.pi * fw / fs)
    poles = np.roots(den.coef[::-1])
    zp = (kw + poles) / (kw - poles)                       # s -> z
    zp = sorted(zp, key=lambda z: (abs(z.imag) < 1e-9, -abs(z.imag)))
    secs, used = [], [False] * len(zp)
    for i, z in enumerate(zp):
        if used[i]: continue
        used[i] = True
        if abs(z.imag) > 1e-9:
            j = next(j for j in range(len(zp)) if not used[j] and abs(zp[j] - z.conjugate()) < 1e-6)
            used[j] = True
            a1, a2 = -2 * z.real, abs(z) ** 2
            g = (1 + a1 + a2) / 4.0
            secs.append([g, 2 * g, g, a1, a2])
        else:
            a1 = -z.real
            g = (1 + a1) / 2.0
            secs.append([g, g, 0.0, a1, 0.0])
    return np.array(secs, float)


def sos_response(sos, f, fs):
    z = np.exp(-2j * np.pi * np.asarray(f, float) / fs)
    h = np.ones(len(z), complex)
    for b0, b1, b2, a1, a2 in sos: h *= (b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z)
    return h


def cutoff_3db(hfun, lo=300.0, hi=40000.0):
    f = np.geomspace(lo, hi, 6000)
    return float(f[np.argmax(20 * np.log10(np.abs(hfun(f))) < -3.0)])


OUT_SOS = {ch: _bilinear_sos(out_filter_den(ch), 2 * FS4, 10000.0) for ch in OUT_PARTS}   # run at 8x: within 0.25 dB of
#                                                                     the analog response to 13 kHz (each 4x value twice)

# ---------------------------------------------------------------------------------------------------------------
# 3. dynamic filters, channels 1-2 (p. 16): an SSM2044 4-pole low-pass. Its Q pin is left at minimum (TP12 / TP10
#    bridge it to +15 V only to make it oscillate for tuning). The FREQ pin sits on R118 390R, fed by R112 39K from
#    -15 V, R104 220K from the tuning trimmer, and R125 15K from C111 10 uF, which R135 30K charges toward +15 V. On a
#    hit the processor pulls GAIN1 (GAIN2) low - the same lines that set the sampling input's gain - and through D9 and
#    R98 100R that empties C111: the FREQ pin swings ~112 mV negative (the SSM2044 tracks ~18 mV per octave, the data
#    sheet's +-90 mV = 1000:1), i.e. ~6.2 octaves up, then C111 recharges with tau = 10 uF x (30K || 15.39K) = 0.10 s
#    and the filter closes again, exponentially in octaves. Factory trim: at rest it is tuned to 1.0 kHz (manual
#    p. 33-34: bridge the test points, tune the oscillation to 1 kHz); "by ear" the trim is set to taste.
#    Not on the schematic: how long the processor holds GAIN low (taken as long enough to empty C111).
#    After it: TL084 gain stage (R124 15K / R141 3.3K, x5.5) with C142 470 pF across R124: a shelf from ~23 kHz.
# ---------------------------------------------------------------------------------------------------------------
DYN_PARTS = dict(R135=30e3, R125=15e3, R118=390.0, C111=10e-6, VD=0.65, VCC=15.0, MV_OCT=0.018)


def dyn_numbers(d=DYN_PARTS):
    rl = d["R125"] + d["R118"]
    v_rest = d["VCC"] * rl / (d["R135"] + rl)
    tau = d["C111"] * d["R135"] * rl / (d["R135"] + rl)
    swing = (v_rest - d["VD"]) * d["R118"] / rl
    return dict(v_rest=v_rest, tau=tau, swing_mV=swing * 1e3, octaves=swing / d["MV_OCT"])


_DYN = dyn_numbers()
DYN_REST = 1000.0                  # Hz at rest (the factory trim)
DYN_OCT = _DYN["octaves"]          # ~6.2 octaves up on a hit
DYN_TAU = _DYN["tau"]              # ~0.10 s


def _shelf():
    tau = 15e3 * 470e-12; g = 1 + 15e3 / 3.3e3              # (g + s tau) / (g (1 + s tau)), normalised to 1 at DC
    kw = 2 * FS4
    b0, b1 = (g + kw * tau) / g, (g - kw * tau) / g
    a0, a1 = 1 + kw * tau, 1 - kw * tau
    return b0 / a0, b1 / a0, a1 / a0


SHELF = _shelf()

# ---------------------------------------------------------------------------------------------------------------
# 4. level: an AD7523 8-bit multiplying DAC after the 12-bit sample DAC, fed from a 74S288 32 x 8 log PROM (p. 8:
#    five address bits). So 32 levels; the PROM's contents are not in the manual - taken as even steps down to the
#    8-bit DAC's floor (1/255 = -48 dB): ~1.5 dB per step.
# ---------------------------------------------------------------------------------------------------------------
LEVEL_STEP_DB = 48.0 / 31.0
TICK = 0.0012288 * SP_SR           # the decay steps once per 1.2288 ms housekeeping tick = 32 sample frames

# ---------------------------------------------------------------------------------------------------------------
# the resampler from the 4x rate to the output: windowed sinc, -6 dB at 21 kHz
# ---------------------------------------------------------------------------------------------------------------
NTAP, NPH, RS_FC = 96, 4096, 21000.0
SP_STATE = 32 + 256


def _kernel():
    half = NTAP // 2
    ph = np.arange(NPH + 1)[:, None] / NPH
    x = ph + half - 1 - np.arange(NTAP)[None, :]            # distance (4x samples) from the output point to each tap
    fc = RS_FC / FS4
    w = np.kaiser(2 * 4096 + 1, 8.0)
    wi = np.interp(x / (half + 1) * 4096 + 4096, np.arange(len(w)), w, left=0, right=0)
    return (2 * fc * np.sinc(2 * fc * x) * wi).astype(np.float32)


KERNEL = _kernel()

# ---------------------------------------------------------------------------------------------------------------
# sampling in: the input filter at the sound's own speed, then the converter sampling the (band-limited) signal
# ---------------------------------------------------------------------------------------------------------------
_FIR = {}


def input_fir(sr, speed=1.0, ntap=255):
    """FIR (at sr) with the input filter's response for a sound played into it 'speed' times faster"""
    key = (sr, speed, ntap)
    if key not in _FIR:
        nf = 4096
        f = np.fft.rfftfreq(nf, 1.0 / sr)
        h = input_filter(f * speed)
        gd = -np.angle(input_filter([200.0 * speed])[0]) / (2 * np.pi * 200.0)   # the filter's delay at low frequencies
        d0 = round(gd * sr)                                                        # (removed: the sound stays on time)
        imp = np.fft.irfft(h * np.exp(2j * np.pi * f * d0 / sr), nf)
        half = ntap // 2
        fir = np.concatenate((imp[-half:], imp[:half + 1])) * np.kaiser(ntap, 6.0)
        _FIR[key] = (fir / fir.sum()).astype(np.float32)
    return _FIR[key]


_SA = {}


def sample_at(x, sr_in, positions, half=16, nph=2048):
    """band-limited (Kaiser-windowed sinc, 2 x half taps) values of x (at sr_in) at fractional sample positions"""
    if (half, nph) not in _SA:
        d = np.arange(nph + 1)[:, None] / nph - np.arange(-half + 1, half + 1)[None, :]
        r = np.clip(d / (half + 1), -1, 1)
        w = np.i0(8.0 * np.sqrt(1 - r * r)) / np.i0(8.0)                       # Kaiser, beta 8
        _SA[(half, nph)] = (np.sinc(d) * w).astype(np.float32)
    tab = _SA[(half, nph)]
    x = np.asarray(x, np.float32)
    xp = np.concatenate((np.zeros(half, np.float32), x, np.zeros(half + 1, np.float32)))
    positions = np.asarray(positions, np.float64)
    out = np.empty(len(positions), np.float32)
    taps = np.arange(-half + 1, half + 1) + half
    for a in range(0, len(positions), 8192):
        p = positions[a:a + 8192]
        i0 = np.floor(p).astype(np.int64)
        ph = np.rint((p - i0) * nph).astype(np.int64)
        idx = np.minimum(i0[:, None] + taps[None, :], len(xp) - 1)
        out[a:a + 8192] = np.einsum("ij,ij->i", xp[idx], tab[ph])
    return out


# ---------------------------------------------------------------------------------------------------------------
# the voice renderer (C, with a slow pure-Python copy if it cannot be built)
# ---------------------------------------------------------------------------------------------------------------
_lib = None


def _load():
    global _lib
    so, src = os.path.join(HERE, "dsp", "libsp1200.so"), os.path.join(HERE, "dsp", "sp1200.c")
    if (not os.path.exists(so) or os.path.getmtime(so) < os.path.getmtime(src)) and os.path.exists(src):
        try: subprocess.run(["cc", "-O3", "-ffast-math", "-fPIC", "-shared", "-o", so, src, "-lm"], check=True, capture_output=True, timeout=120)
        except Exception: pass
    try:
        lib = ctypes.CDLL(so)
        D, F, I = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_float), ctypes.c_int
        lib.sp_voice.argtypes = [F, I, D, D, D, I, F, I, I, F, I]
        lib.sp_voice.restype = I
        _lib = lib if lib.sp_state_size() == SP_STATE else None
    except OSError:
        _lib = None


_load()
FAST = _lib is not None
_SOS_FLAT = {ch: np.ascontiguousarray(OUT_SOS[ch].ravel()) for ch in OUT_SOS}
_NONE = np.zeros(5)


def new_state():
    st = np.zeros(SP_STATE)
    st[3] = -1.0
    return st


def params(step, ring_step, ring_amt, ch, attack_sp=0.0, decay_tau_sp=0.0, out_sr=44100.0, rest_hz=DYN_REST, res=0.0):
    kind = 1 if ch <= 2 else (2 if ch <= 6 else 0)
    return np.array([step, ring_step, ring_amt, kind, attack_sp, decay_tau_sp, TICK, rest_hz, DYN_OCT, DYN_TAU * SP_SR,
                     FS4, FS4 / out_sr, SHELF[0], SHELF[1], SHELF[2], LEVEL_STEP_DB, res], float)


def render(d, dend, st, prm, ch, n):
    """n output frames of an SP voice (fewer once its sound has ended); st and prm from new_state() / params()"""
    out = np.zeros(n, np.float32)
    sos = _SOS_FLAT.get(ch, _NONE)
    nsec = len(sos) // 5 if ch in _SOS_FLAT else 0
    if _lib is not None:
        _fp = lambda a, t: a.ctypes.data_as(ctypes.POINTER(t))
        got = _lib.sp_voice(_fp(d, ctypes.c_float), int(dend), _fp(st, ctypes.c_double), _fp(prm, ctypes.c_double),
                            _fp(sos, ctypes.c_double), nsec, _fp(KERNEL, ctypes.c_float), NTAP, NPH,
                            _fp(out, ctypes.c_float), n)
        return out[:got]
    return out[:_render_py(d, dend, st, prm, sos, nsec, out, n)]


def _render_py(d, dend, st, prm, sos, nsec, out, n):
    """the same as dsp/sp1200.c, line for line (slow: only used if the C library cannot be built)"""
    step, rstep, ramt, kind = prm[0], prm[1], prm[2], int(prm[3])
    att, dtau, tick = prm[4], prm[5], max(1.0, prm[6])
    frest, doct, dyntau, fs4, adv = prm[7], prm[8], prm[9], prm[10], prm[11]
    sb0, sb1, sa1, lstep, kres = prm[12], prm[13], prm[14], prm[15], prm[16]
    h = st[32:32 + 128].view(np.float32); R = 256; half = NTAP // 2
    k, made, pos, endp = int(st[0]), int(st[1]), st[2], st[3]
    j = 0
    while j < n:
        if endp >= 0 and pos >= endp: break
        need = int(math.floor(pos)) + half + 1
        while made < need:
            x = 0.0
            idx = int(math.floor(k * step))
            if endp < 0 and (idx >= dend or st[17] > 0): endp = float(made)
            if endp < 0:
                x = float(d[idx])
                if ramt > 0:
                    e = math.floor((k + 1) * rstep) - math.floor(k * rstep) - rstep
                    st[16] += 0.004 * (x * x - st[16]); st[15] += 0.515 * (e - st[15]); st[18] += 0.515 * (st[15] - st[18])
                    st[19] += 0.515 * (st[18] - st[19])
                    x += st[19] * math.sqrt(max(0.0, st[16])) * 1.4 * ramt
                tt = math.floor(k / tick) * tick; env = 1.0
                if att > 0: env = min(1.0, tt / att)
                if dtau > 0: env *= math.exp(-max(0.0, tt - att) / dtau)
                if lstep > 0:
                    if env <= 0: g = 0.0
                    else:
                        q = math.floor(-20 * math.log10(env) / lstep + 0.5)
                        g = 0.0 if q >= 31 else 10 ** (-q * lstep / 20)
                else: g = env
                if dtau > 0 and tt > att and g <= 0: st[17] = 1
                x *= g
            cg = 0.0
            if kind == 1:
                fc = min(0.45 * fs4, frest * 2 ** (doct * math.exp(-k / dyntau)))
                gg = math.tan(math.pi * fc / fs4); cg = gg / (1 + gg)
            for _ in range(4):
                y = x
                if kind == 1:
                    u = y - kres * st[7]
                    for p in range(4):
                        v = (u - st[4 + p]) * cg; o = v + st[4 + p]; st[4 + p] = o + v; u = o
                    w = sb0 * u + st[8]; st[8] = sb1 * u - sa1 * w; y = w
                elif kind == 2:
                  for _r in range(2):
                    y = x
                    for q in range(nsec):
                        b0, b1, b2, a1, a2 = sos[5 * q:5 * q + 5]
                        w = b0 * y + st[9 + 2 * q]
                        st[9 + 2 * q] = b1 * y - a1 * w + st[10 + 2 * q]; st[10 + 2 * q] = b2 * y - a2 * w; y = w
                h[made & (R - 1)] = y; made += 1
            k += 1
        c0 = int(math.floor(pos)); ph = int((pos - c0) * NPH + 0.5)
        kv = KERNEL[ph]
        m = np.arange(c0 - half + 1, c0 - half + 1 + NTAP)
        hv = np.where(m >= 0, h[m & (R - 1)], 0.0)
        out[j] = float((kv * hv).sum()); pos += adv; j += 1
    st[0], st[1], st[2], st[3] = k, made, pos, endp
    return j


if __name__ == "__main__":
    f = [10000, 12000, 13020, 14000, 15000, 18000, 22050]
    print("input filter: -3 dB at %.0f Hz;" % cutoff_3db(input_filter),
          ", ".join("%d Hz %.1f dB" % (a, 20 * np.log10(abs(b))) for a, b in zip(f, input_filter(f))))
    for ch in OUT_PARTS:
        ff = np.array([1000, 5000, 10000, 13000, 15000])
        err = np.abs(20 * np.log10(np.abs(sos_response(OUT_SOS[ch], ff, 2 * FS4) / out_filter(ff, ch)))).max()
        print("out ch %d: -3 dB at %.0f Hz (digital vs analog within %.2f dB)" % (ch, cutoff_3db(lambda q: out_filter(q, ch)), err))
    print("dynamic:", {k: round(v, 4) for k, v in _DYN.items()}, "C library:", FAST)
    if "--plot" in sys.argv:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        ff = np.geomspace(100, 50000, 2000)
        plt.figure(figsize=(9, 5))
        plt.semilogx(ff, 20 * np.log10(np.abs(input_filter(ff))), label="input anti-alias (7th order elliptic)")
        for ch in OUT_PARTS: plt.semilogx(ff, 20 * np.log10(np.abs(out_filter(ff, ch))), label="output ch %d" % ch)
        plt.axvline(SP_SR / 2, ls=":", c="k"); plt.ylim(-90, 6); plt.grid(True, which="both", alpha=.3); plt.legend()
        plt.xlabel("Hz"); plt.ylabel("dB"); plt.savefig(sys.argv[sys.argv.index("--plot") + 1], dpi=110)
