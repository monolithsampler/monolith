/* akai.c - the sound chips of the Akai / Roger Linn MPCs, one voice at a time.

   L4003 (MPC60): 16 voices of 12-bit samples at a fixed 40 kHz. Pitch is a 4.12 step (0x1000 = 40 kHz); the sample
   at the integer address is played as it is (no interpolation between samples). Each sample then goes through the
   small recursive filter MAME's l4003.cpp takes from the MPC3000's own code for playing MPC60 sounds ("a pretty
   literal decompile of the assembly code in the MPC3000 which massages the MPC60 samples into 16 bits"), done here
   the same way, integer for integer. The 40 kHz result is brought to 44.1 kHz with a windowed-sinc resampler that stays flat
   to ~18.5 kHz; the real DAC's hold and its 18 kHz LC output filter are added after it (mpchw.py).

   L6028 (MPC3000, MPC2000 / 2000XL; the same chip in both): 32 voices of 16-bit samples at 44.1 kHz, 4.12 pitch
   (0x1000 = 44.1 kHz), 8-point windowed-sinc interpolation, and a two-pole low-pass in the Chamberlin form with a
   4-bit resonance (h = x - l - b + res * b / 16; b += f * h; l += f * b; f = cutoff / 32768). As MAME's
   l7a1045_l6028_dsp_a.cpp has it (R. Belmont, O. Galibert; BSD-3-Clause) - its interpolation coefficients are
   "textbook" there too: the chip's own were not recovered.

   Written for this project from those descriptions; no Akai code is included. Envelopes are done by the caller (both
   chips ramp the level in straight lines toward a target, which the caller reproduces exactly). */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define TAPS 48
#define PHASES 256
static float rs_tab[PHASES + 1][TAPS];             /* 40 kHz -> 44.1 kHz (L4003) */
static int32_t si_tab[4097][8];                     /* L6028's 8-point interpolator, 2.30 fixed point */
static int ready;

static void make_tables(void) {
    const double cut = 0.5 * 0.985, beta = 8.0;     /* transparent to ~18.5 kHz: the shaping above is the analog path (mpchw.py) */
    for (int p = 0; p <= PHASES; p++) {
        double fr = (double)p / PHASES, sum = 0;
        for (int k = 0; k < TAPS; k++) {
            double d = (k - (TAPS / 2 - 1)) - fr, x = d / (TAPS / 2.0), a = 1 - x * x;
            if (a < 0) a = 0;
            double t = beta * sqrt(a), i0 = 1, term = 1, i0b = 1, tb = 1;
            for (int j = 1; j < 30; j++) { term *= (t / 2) / j; i0 += term * term; tb *= (beta / 2) / j; i0b += tb * tb; }
            double s = fabs(d) < 1e-9 ? 2 * cut : sin(2 * M_PI * cut * d) / (M_PI * d);
            rs_tab[p][k] = (float)(s * i0 / i0b); sum += s * i0 / i0b;
        }
        for (int k = 0; k < TAPS; k++) rs_tab[p][k] /= (float)sum;
    }
    /* tap k (-3..4): sinc(f - k) * (1 + cos(pi (f - k) / 4)) / 2, normalised per phase */
    memset(si_tab, 0, sizeof si_tab);
    si_tab[0][3] = 1 << 30;
    for (int ph = 1; ph <= 4096; ph++) {
        double f = ph / 4096.0, w[8], tot = 0;
        for (int k = 0; k < 8; k++) {
            double d = f - (k - 3);
            double s = fabs(d) < 1e-12 ? 1.0 : sin(M_PI * d) / (M_PI * d);
            w[k] = s * (1 + cos(M_PI * d / 4)) / 2; tot += w[k];
        }
        for (int k = 0; k < 8; k++) si_tab[ph][k] = (int32_t)llround(w[k] / tot * (double)(1 << 30));
    }
    ready = 1;
}

typedef struct {
    int kind;                                       /* 0 = L4003 (MPC60), 1 = L6028 (MPC3000 / 2000XL) */
    const int16_t *mem; int n;
    int start, end, lstart;                         /* sample addresses; lstart < 0 = no loop */
    uint32_t pos, frac, step;
    int32_t filt;                                   /* L4003: the MPC3000's filter state */
    int64_t l, b;                                   /* L6028: the low-pass */
    int res;                                        /* L6028: resonance register 0-15 */
    double ph, rstep; float hist[TAPS]; int stopped_in;
    int ended, done;
} ak_t;

ak_t *ak_new(int kind) {
    if (!ready) make_tables();
    ak_t *v = calloc(1, sizeof(ak_t)); v->kind = kind; v->done = 1; return v;
}
void ak_free(ak_t *v) { free(v); }

void ak_start(ak_t *v, const int16_t *mem, int n, int start, int end, int lstart, uint32_t step, double rstep) {
    int k = v->kind;
    memset(v, 0, sizeof *v);
    v->kind = k; v->mem = mem; v->n = n;
    v->start = start < 0 ? 0 : start; v->end = end > n ? n : end; v->lstart = lstart;
    if (v->lstart >= v->end) v->lstart = -1;
    v->step = step; v->rstep = rstep; v->stopped_in = -1;
    v->done = v->end <= v->start;
}
void ak_set_step(ak_t *v, uint32_t step) { v->step = step; }
void ak_set_res(ak_t *v, int res) { v->res = res < 0 ? 0 : res > 15 ? 15 : res; }
int ak_done(ak_t *v) { return v->done; }
uint32_t ak_pos(ak_t *v) { return v->pos; }

/* --- L4003 --- one 40 kHz sample, through the MPC3000's filter */
static int16_t l4003_sample(ak_t *v) {
    v->pos += v->frac >> 12; v->frac &= 0xfff;
    uint32_t a = v->start + v->pos;
    if (a >= (uint32_t)v->end) { v->ended = 1; a = v->end - 1; }
    int32_t sample = v->ended ? 0 : v->mem[a];
    v->frac += v->step;
    const int32_t temp = (int32_t)(((uint32_t)(uint16_t)sample << 16) | (uint16_t)v->filt) >> 8;
    const int32_t ns = temp + (int32_t)(((int64_t)v->filt * 0x9e227) >> 20);
    int32_t t2 = (int32_t)(((int64_t)ns * 0x5b708) >> 20) + (int32_t)(((int64_t)v->filt * 0x645d) >> 20);
    v->filt = ns;
    t2 = (t2 * 19) >> 4;
    const int32_t S = 0x7fff;
    if (t2 >= 0) return (uint32_t)t2 >= ((uint32_t)S << 8) ? (int16_t)(S - 1) : (int16_t)((t2 << 7) / S);
    return (t2 >> 8) <= -S ? (int16_t)-(S - 1) : (int16_t)((t2 << 7) / S);
}

/* --- L6028 --- one 44.1 kHz sample: 8-point interpolation, then the low-pass (f = cutoff register, < 0 = off) */
static inline int32_t rd(ak_t *v, int64_t a) {
    if (a >= v->end) {
        if (v->lstart < 0) return 0;
        a = v->lstart + (a - v->end) % (v->end - v->lstart);
    }
    if (a < v->start) return 0;
    return v->mem[a];
}

static int32_t l6028_sample(ak_t *v, int32_t f) {
    v->pos += v->frac >> 12; v->frac &= 0xfff;
    if ((int64_t)v->start + v->pos >= v->end) {
        if (v->lstart < 0) { v->ended = 1; return 0; }
        v->pos = v->lstart - v->start;               /* the loop: back to its start (the overshoot is dropped, as MAME) */
    }
    int64_t a = (int64_t)v->start + v->pos;
    const int32_t *c = si_tab[v->frac & 0xfff];
    int64_t acc = 0;
    if (!(v->frac & 0xfff)) acc = (int64_t)rd(v, a) << 30;
    else for (int k = 0; k < 8; k++) acc += (int64_t)rd(v, a + k - 3) * c[k];
    int32_t s = (int32_t)(acc < 0 ? -((-acc + (1LL << 29)) >> 30) : ((acc + (1LL << 29)) >> 30));
    v->frac += v->step;
    if (f < 0) return s;
    const int64_t h = (int64_t)s - v->l - v->b + (((int64_t)v->res * v->b) >> 4);
    v->b += ((int64_t)f * h) >> 15;
    v->l += ((int64_t)f * v->b) >> 15;
    const int64_t LIM = 1LL << 22;                  /* (a runaway resonance is held, not left to wrap) */
    if (v->b > LIM) v->b = LIM; else if (v->b < -LIM) v->b = -LIM;
    if (v->l > LIM) v->l = LIM; else if (v->l < -LIM) v->l = -LIM;
    return (int32_t)v->l;
}

/* n output samples at 44.1 kHz; f0 -> f1 = the L6028's cutoff register across the block (< 0 = filter off).
   Returns how many were made before the sound ended. */
int ak_render(ak_t *v, float *out, int n, int f0, int f1) {
    if (v->done) { memset(out, 0, n * sizeof(float)); return 0; }
    if (v->kind == 1) {
        for (int i = 0; i < n; i++) {
            int f = f0 < 0 ? -1 : f0 + (int)((int64_t)(f1 - f0) * i / (n > 1 ? n : 1));
            int32_t s = l6028_sample(v, f);
            if (v->ended) { memset(out + i, 0, (n - i) * sizeof(float)); v->done = 1; return i; }
            out[i] = s / 32768.0f;
        }
        return n;
    }
    for (int i = 0; i < n; i++) {
        while (v->ph >= 1.0) {
            memmove(v->hist, v->hist + 1, (TAPS - 1) * sizeof(float));
            v->hist[TAPS - 1] = l4003_sample(v) / 32768.0f;
            v->ph -= 1.0;
            if (v->ended) {
                if (v->stopped_in < 0) v->stopped_in = TAPS;
                else if (--v->stopped_in <= 0) { memset(out + i, 0, (n - i) * sizeof(float)); v->done = 1; return i; }
            }
        }
        double fp = v->ph * PHASES; int p = (int)fp; float t = (float)(fp - p);
        const float *a = rs_tab[p], *b = rs_tab[p + 1];
        float acc = 0;
        for (int k = 0; k < TAPS; k++) acc += v->hist[k] * (a[k] + t * (b[k] - a[k]));
        out[i] = acc;
        v->ph += v->rstep;
    }
    return n;
}

/* for tests: run the L4003's filter alone over 12-bit words (as 16-bit, left-justified) */
void ak_l4003_filter(const int16_t *in, int16_t *out, int n) {
    ak_t v; memset(&v, 0, sizeof v);
    for (int i = 0; i < n; i++) {
        int32_t sample = in[i];
        const int32_t temp = (int32_t)(((uint32_t)(uint16_t)sample << 16) | (uint16_t)v.filt) >> 8;
        const int32_t ns = temp + (int32_t)(((int64_t)v.filt * 0x9e227) >> 20);
        int32_t t2 = (int32_t)(((int64_t)ns * 0x5b708) >> 20) + (int32_t)(((int64_t)v.filt * 0x645d) >> 20);
        v.filt = ns; t2 = (t2 * 19) >> 4;
        const int32_t S = 0x7fff;
        out[i] = t2 >= 0 ? ((uint32_t)t2 >= ((uint32_t)S << 8) ? S - 1 : (t2 << 7) / S) : ((t2 >> 8) <= -S ? -(S - 1) : (t2 << 7) / S);
    }
}

/* the other half: the pre-emphasis the L4003's filter undoes (its exact inverse, in floating point). The MPC3000 needs
   1/3 more memory to load an MPC60 sound and runs this filter on it, so the MPC60's words carry the treble lift of a
   pre-emphasis made when sampling (an inference: the MPC60's input stage was not traced). Here it is applied when a
   sound becomes MPC60 words, so the chip's filter gives back a flat sound with its 12-bit hiss pushed down in the
   treble - and loud treble runs out of headroom first, as it would going into the real converter. */
void ak_l4003_preemph(float *x, int n) {
    const double p = 0x9e227 / 1048576.0, a0 = 0x5b708 / 1048576.0, a1 = 0x645d / 1048576.0, G = 19.0 / 16.0;
    double xp = 0, yp = 0;
    for (int i = 0; i < n; i++) {
        double y = (x[i] - p * xp) / (G * a0) - (a1 / a0) * yp;
        xp = x[i]; yp = y; x[i] = (float)y;
    }
}
