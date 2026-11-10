/* voicefx.c - small DSP helpers for the sampler, called through ctypes (dspfast.py).
   svf_block: a TPT state-variable filter (Zavalishin) on one block of a mono voice, the cutoff gliding from f0 to f1 Hz.
   onepole_block: the master low-pass (replaces a per-sample Python loop).                                          */
#include <math.h>

void svf_block(float *x, int n, float *st, float f0, float f1, float res, int mode, float sr)
{
    /* mode 1 = low-pass, 2 = high-pass, 3 = band-pass. res 0..1. st[2] = filter state (kept between blocks). */
    float ic1 = st[0], ic2 = st[1];
    float k = 2.0f - 1.94f * (res < 0 ? 0 : (res > 1 ? 1 : res));
    float lf0 = logf(f0), lf1 = logf(f1);
    for (int i = 0; i < n; i++) {
        float f = expf(lf0 + (lf1 - lf0) * (n > 1 ? (float)i / (float)(n - 1) : 0.0f));
        if (f > 0.45f * sr) f = 0.45f * sr;
        float g = tanf(3.14159265f * f / sr);
        float a1 = 1.0f / (1.0f + g * (g + k)), a2 = g * a1, a3 = g * a2;
        float v3 = x[i] - ic2;
        float v1 = a1 * ic1 + a2 * v3;
        float v2 = ic2 + a2 * ic1 + a3 * v3;
        ic1 = 2.0f * v1 - ic1;
        ic2 = 2.0f * v2 - ic2;
        x[i] = mode == 1 ? v2 : (mode == 2 ? x[i] - k * v1 - v2 : v1);
    }
    if (!isfinite(ic1) || !isfinite(ic2)) { ic1 = 0; ic2 = 0; }
    st[0] = ic1; st[1] = ic2;
}

void onepole_block(float *x, int n, float *y, float a)
{
    float s = *y;
    for (int i = 0; i < n; i++) { s += a * (x[i] - s); x[i] = s; }
    *y = s;
}

void sos_block(float *x, int n, const double *sos, int nsec, float *st)
{
    /* a cascade of biquads [b0 b1 b2 a1 a2] (transposed direct form II), in place; st = 2 floats per section */
    for (int q = 0; q < nsec; q++) {
        const double *c = sos + 5 * q;
        double z0 = st[2 * q], z1 = st[2 * q + 1];
        for (int i = 0; i < n; i++) {
            double v = x[i], w = c[0] * v + z0;
            z0 = c[1] * v - c[3] * w + z1;
            z1 = c[2] * v - c[4] * w;
            x[i] = (float)w;
        }
        st[2 * q] = (float)z0; st[2 * q + 1] = (float)z1;
    }
}
