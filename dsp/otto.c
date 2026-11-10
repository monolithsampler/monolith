/*
 * otto.c - one ASR-10 voice: the ES5506 ("OTTO") sound chip's sample playback, and the ASR-10 OS's wavesample
 * modulation (LOOP POS, START, START+LP, LOOPSTRT, LOOP END, LPSTRT-X, TRANSWAV), as the OS drives the chip.
 *
 * The chip (after MAME's es5506.cpp, BSD licence, re-written here):
 *   - addresses are 21.11 fixed point; START keeps whole samples, END keeps 1/16 of a sample;
 *   - each output sample interpolates linearly between two samples with the 11-bit fraction;
 *   - control bits: STOP0, LEI (loop end ignore), LPE (loop), BLE (bidirectional / "trans-wave"), IRQE, DIR;
 *     LPE = loop forward, LPE|BLE = bidirectional, BLE alone = trans-wave: at END jump to START once (keeping the
 *     overshoot), set LEI and raise the interrupt.
 * The OS (OS 3.53 disk at 7EB0 and the ROM at F8D626-F8D91E, read for this):
 *   - addresses in a wavesample are 23.9 fixed point ("OS units"); the chip gets them shifted left 2;
 *   - every voice update computes MOD AMT (high byte of a word) x the source, and per mode moves the loop;
 *   - a loop move that must not click (LOOP POS, START+LP, TRANSWAV) writes the new START at once, then sets
 *     trans-wave + IRQE; the interrupt handler (F8D8F8) then writes the new END and turns plain looping back on. So
 *     the jump to the new window happens exactly at the end of the current pass through the loop.
 *   - while such a move is pending (IRQE still set), a new one is dropped; TRANSWAV has already noted the new frame
 *     number, so it is not retried until the frame changes again (as on the machine).
 *
 * Output: the chip's samples at its own rate, changed to 44.1 kHz with a 16-tap windowed sinc.
 * Build: dsp/build.sh
 */
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

#define CR_STOP0 0x0001
#define CR_LEI   0x0004
#define CR_LPE   0x0008
#define CR_BLE   0x0010
#define CR_IRQE  0x0020
#define CR_DIR   0x0040
#define CR_IRQ   0x0080

#define TAPS 16
#define PHASES 256

static float sinc_tab[PHASES + 1][TAPS];
static int sinc_ready;

static void make_sinc(void) {
    const double cut = 0.5 * 0.94, beta = 7.0;                  /* cycles per chip sample */
    for (int p = 0; p <= PHASES; p++) {
        double fr = (double)p / PHASES, sum = 0;
        for (int k = 0; k < TAPS; k++) {
            double d = (k - (TAPS / 2 - 1)) - fr, x = d / (TAPS / 2.0), w;
            double a = 1 - x * x; if (a < 0) a = 0;
            /* Kaiser window, I0 by series */
            double t = beta * sqrt(a), i0 = 1, term = 1, i0b = 1, tb = 1;
            for (int j = 1; j < 30; j++) { term *= (t / 2) / j; i0 += term * term; tb *= (beta / 2) / j; i0b += tb * tb; }
            w = i0 / i0b;
            double s = fabs(d) < 1e-9 ? 2 * cut : sin(2 * M_PI * cut * d) / (M_PI * d);
            sinc_tab[p][k] = (float)(s * w); sum += s * w;
        }
        for (int k = 0; k < TAPS; k++) sinc_tab[p][k] /= (float)sum;
    }
    sinc_ready = 1;
}

/* the ASR-10's exponential: 0x800 * 2^(x / 3072), x in 1/256 semitone, from a 1536-entry octave table (ROM F846CE,
   computed here), limited to +-6 octaves (ROM F8D490) */
static uint32_t exp_tab(int x) {
    int16_t v = (int16_t)x;
    if (v < 0) {
        if (v < (int16_t)0xB800) v = (int16_t)0xB800;
        int sh = 0;
        do { sh++; v = (int16_t)(v + 0xC00); } while (v < 0);
        int k = (v & 0xFFFE) / 2;
        uint32_t t = (uint32_t)lround(2048.0 * pow(2.0, k / 1536.0));
        return t >> sh;
    } else {
        if (v > 0x4800) v = 0x4800;
        int sh = -1;
        do { sh++; v = (int16_t)(v - 0xC00); } while (v >= 0);
        int k = (0xC00 + v) / 2;                                   /* the index lands back in the same table */
        uint32_t t = (uint32_t)lround(2048.0 * pow(2.0, k / 1536.0));
        return t << sh;
    }
}

typedef struct {
    /* sample memory: 16-bit, at the chip's rate */
    const int16_t *mem; int32_t n;
    /* chip registers (21.11) */
    uint32_t accum, start, end, fc, cr;
    /* the OS's state for this voice */
    int cb;                           /* interrupt pending: 1 = F8D8F8 (write END, back to plain looping) */
    uint32_t pend_end;                /* ($c6,A4) */
    int loopmode;                     /* 0 FWD NO LOOP, 1 BACKWARD NO LOOP, 2 LOOP FWD, 3 BIDIRECTIONAL, 4 LOOP AND RELEASE */
    int mod, amt, range;              /* MOD (0-7), MOD AMT (-127..127), RANGE (0-21: shift) */
    int32_t ss, se, ls, le;           /* sample start/end, loop start/end, OS units (23.9) */
    int tw_cache;                     /* ($b8,A4): the TRANSWAV frame last applied (low byte) */
    int d82;                          /* 1 while a note starts: loop moves are written at once */
    uint32_t fc_base; int32_t pitch_x;/* pitch as set, and LPSTRT-X's added pitch (1/256 semitone) */
    /* control ticks and the source value */
    int32_t tick_len, tick_ctr;
    int16_t src;
    /* rate change to 44.1 kHz */
    double step, ph;                  /* chip samples per output sample; position between hist[7] and hist[8] */
    float hist[TAPS];
    int stopped_in;                   /* chip samples left before the history is all past the stop */
    /* the chip's 4-pole filter: poles 1-2 low-pass on K1; 3-4 by mode (0: HP/HP on K2, 1: LP K1 / HP K2,
       2: LP/LP on K2, 3: LP K1 / LP K2) - the ASR's F1=2/LP F2=2/HP, F1=3/LP F2=1/HP, F1=2/LP F2=2/LP, F1=3/LP F2=1/LP */
    int f_on, f_mode; int32_t k1, k2;
    int32_t o1n1, o2n1, o2n2, o3n1, o3n2, o4n1;
    int done;
} ov_t;

static int32_t prod_of(ov_t *v) { return (int32_t)(int16_t)((v->amt & 0xff) << 8) * (int32_t)v->src; }

static void set_fc(ov_t *v) {
    uint64_t f = (uint64_t)v->fc_base;
    if (v->pitch_x) f = f * exp_tab(v->pitch_x) / 0x800;
    if (f > 0x1ffff) f = 0x1ffff;
    v->fc = (uint32_t)f;
}

static void w_start(ov_t *v, int64_t os) { v->start = (uint32_t)(os << 2) & 0xfffff800u; }
static void w_end(ov_t *v, int64_t os)   { v->end = (uint32_t)(os << 2) & 0xffffff80u; }

/* LOOP POS / START+LP / TRANSWAV: move the loop window by off (OS units), in step with the loop (F8D68A) */
static void move_window(ov_t *v, int32_t off) {
    if (v->cr & CR_IRQE) return;                                    /* a move is still pending: dropped */
    off &= ~0x1FF;                                                  /* whole samples */
    int64_t d1 = (int64_t)v->ls + off, d2 = (int64_t)v->le + off, d3 = (int64_t)v->se - d2;
    if (d3 < 0) { d1 += d3; d2 += d3; }                             /* not past the sample's end */
    else if (d1 <= v->ss) { int64_t d4 = v->ss - d1; d1 += d4; d2 += d4; }   /* nor before its start */
    w_start(v, d1);
    if (v->loopmode == 3) { w_end(v, d2); return; }                 /* bidirectional: END at once */
    if (v->d82) { w_end(v, d2); return; }                           /* a note starting: at once */
    v->pend_end = (uint32_t)(d2 << 2);
    v->cr = (v->cr | CR_BLE | CR_IRQE) & ~(CR_LEI | CR_LPE);         /* trans-wave: jump at the end of this pass */
    v->cb = 1;
}

static void os_tick(ov_t *v) {
    int32_t p = prod_of(v);
    v->pitch_x = 0;
    switch (v->mod) {
    case 1: case 3: move_window(v, p >> v->range); break;          /* LOOP POS, START+LP */
    case 4: {                                                       /* LOOPSTRT (F8D78C): START at once */
        int64_t d1 = (int64_t)v->ls + (p >> v->range), d2 = (int64_t)v->le - 0x800;
        if (d1 > d2) d1 = d2; else if (d1 < v->ss) d1 = v->ss;
        w_start(v, d1); break; }
    case 5: {                                                       /* LOOP END (F8D7B0) */
        int64_t d1 = (int64_t)v->ls + 0x800, d2 = (int64_t)v->le + (p >> v->range);
        if (d2 > v->se) d2 = v->se; else if (d2 < d1) d2 = d1;
        uint32_t e = (uint32_t)(d2 << 2);
        if (v->accum > e) { v->pend_end = e; v->cr |= CR_IRQE; v->cb = 1; }   /* already past it */
        else w_end(v, d2);
        break; }
    case 6: {                                                       /* LPSTRT-X (F8D750): loop length and pitch */
        int16_t x = (int16_t)(p >> 16);
        v->pitch_x = x;
        uint32_t e = exp_tab(x) >> 1;
        uint32_t len = (uint32_t)(v->le - v->ls) >> 5, d2;
        if (len < 0xFFFF) d2 = ((len & 0xFFFF) * (e & 0xFFFF)) >> 5;
        else d2 = ((len >> 5) & 0xFFFF) * (e & 0xFFFF);
        w_start(v, (int64_t)v->le - d2);
        break; }
    case 7: {                                                       /* TRANSWAV (F8D660): whole loops */
        int16_t frame = (int16_t)((int16_t)(p >> 16) >> 7);
        if ((frame & 0xff) == v->tw_cache) break;
        v->tw_cache = frame & 0xff;
        uint32_t len = (uint32_t)(v->le - v->ls) >> 9;
        if (len > 0x7fff) len = 0x7fff;
        int32_t off = (int32_t)frame * (int32_t)(int16_t)len;
        move_window(v, off << 9);
        break; }
    default: break;
    }
    set_fc(v);
}

static void irq(ov_t *v) {                                          /* the OS's handler, at once */
    v->cr &= ~CR_IRQ;
    if (v->cb == 1) {
        v->end = v->pend_end & 0xffffff80u;
        v->cr = (v->cr & ~(CR_LEI | CR_BLE | CR_IRQE)) | CR_LPE;
        v->cb = 0;
    }
}

static inline int32_t rd(ov_t *v, uint32_t i) { return i < (uint32_t)v->n ? v->mem[i] : 0; }

/* MAME es5506.cpp apply_filters (K is 16 bits; the filter uses its top 12) */
static inline int32_t lp(int32_t x, int32_t k, int32_t prev) { return ((k >> 4) * (x - prev)) / 4096 + prev; }
static inline int32_t hp(int32_t x, int32_t k, int32_t prev_out, int32_t prev_in) { return x - prev_in + ((k >> 4) * prev_out) / 8192 + prev_out / 2; }

static int32_t chip_filter(ov_t *v, int32_t s) {
    s = lp(s, v->k1, v->o1n1); v->o1n1 = s;
    s = lp(s, v->k1, v->o2n1); v->o2n2 = v->o2n1; v->o2n1 = s;
    switch (v->f_mode & 3) {
    case 0: s = hp(s, v->k2, v->o3n1, v->o2n2); v->o3n2 = v->o3n1; v->o3n1 = s;
            s = hp(s, v->k2, v->o4n1, v->o3n2); v->o4n1 = s; break;
    case 1: s = lp(s, v->k1, v->o3n1); v->o3n2 = v->o3n1; v->o3n1 = s;
            s = hp(s, v->k2, v->o4n1, v->o3n2); v->o4n1 = s; break;
    case 2: s = lp(s, v->k2, v->o3n1); v->o3n2 = v->o3n1; v->o3n1 = s;
            s = lp(s, v->k2, v->o4n1); v->o4n1 = s; break;
    default: s = lp(s, v->k1, v->o3n1); v->o3n2 = v->o3n1; v->o3n1 = s;
             s = lp(s, v->k2, v->o4n1); v->o4n1 = s; break;
    }
    return s;
}

/* one chip sample */
static float chip_sample(ov_t *v) {
    if (v->cr & CR_STOP0) return 0.0f;
    uint32_t a = v->accum;
    int32_t s1 = rd(v, a >> 11), s2 = rd(v, (a >> 11) + 1);
    uint32_t fr = a & 0x7ff;
    int32_t val = (s1 * (int32_t)(2048 - fr) + s2 * (int32_t)fr) >> 11;
    if (!(v->cr & CR_DIR)) {
        a = a + v->fc;
        if (a > v->end && !(v->cr & CR_LEI)) {
            if (v->cr & CR_IRQE) v->cr |= CR_IRQ;
            switch (v->cr & (CR_LPE | CR_BLE)) {
            case 0: v->cr |= CR_STOP0; break;
            case CR_LPE: a = v->start + (a - v->end); break;
            case CR_BLE: a = v->start + (a - v->end); v->cr = (v->cr & ~(CR_LPE | CR_BLE)) | CR_LEI; break;
            default: a = v->end - (a - v->end); v->cr ^= CR_DIR; break;
            }
        }
    } else {
        a = a - v->fc;
        if (a < v->start && !(v->cr & CR_LEI)) {
            if (v->cr & CR_IRQE) v->cr |= CR_IRQ;
            switch (v->cr & (CR_LPE | CR_BLE)) {
            case 0: v->cr |= CR_STOP0; break;
            case CR_LPE: a = v->end - (v->start - a); break;
            case CR_BLE: a = v->end - (v->start - a); v->cr = (v->cr & ~(CR_LPE | CR_BLE)) | CR_LEI; break;
            default: a = v->start + (v->start - a); v->cr ^= CR_DIR; break;
            }
        }
    }
    v->accum = a;
    if (v->cr & CR_IRQ) irq(v);
    if (--v->tick_ctr <= 0) { v->tick_ctr = v->tick_len; os_tick(v); }
    if (v->f_on) val = chip_filter(v, val);
    return (float)val / 32768.0f;
}

/* ---------- host interface ---------- */
ov_t *ov_new(void) { if (!sinc_ready) make_sinc(); return (ov_t *)calloc(1, sizeof(ov_t)); }
void ov_free(ov_t *v) { free(v); }

/* start a note. mem: n samples at the chip's rate. ss..ls..le..se in OS units (23.9). fc: 6.11 pitch (2048 = as
   recorded). step: chip samples per output sample. tick: chip samples between voice updates. src: the source value
   at the start (-32768..32767). */
void ov_start(ov_t *v, const int16_t *mem, int n, int ss, int se, int ls, int le, int loopmode, int mod, int amt,
              int range, int fc, double step, int tick, int src) {
    static const uint16_t ctl[5] = {0x00, 0x40, 0x08, 0x18, 0x08};  /* per loop mode (OS disk table) */
    memset(v, 0, sizeof *v);
    v->mem = mem; v->n = n;
    v->ss = ss; v->se = se; v->ls = ls; v->le = le;
    v->loopmode = loopmode < 0 || loopmode > 4 ? 0 : loopmode;
    v->mod = mod; v->amt = amt; v->range = range < 0 ? 0 : (range > 31 ? 31 : range);
    v->fc_base = (uint32_t)(fc < 0 ? 0 : fc); v->src = (int16_t)src;
    v->step = step; v->tick_len = tick < 1 ? 1 : tick; v->tick_ctr = v->tick_len;
    v->cr = ctl[v->loopmode];
    int64_t acc, st, en;
    if (v->loopmode == 0) { acc = ss; en = se; st = ss; }
    else if (v->loopmode == 1) { acc = se; st = ss; en = se; }
    else { acc = ss; en = le; st = ls; }
    v->tw_cache = 0xff;
    if (mod == 2) {                                                 /* START: where the note begins */
        acc += prod_of(v) >> v->range;
        if (acc < 0) acc = 0; else if (acc > en) acc = en;
    }
    w_start(v, st); w_end(v, en); v->accum = (uint32_t)(acc << 2);
    v->d82 = 1; os_tick(v); v->d82 = 0;                              /* the first update, written at once */
    if (mod == 7 || mod == 3) v->accum = v->start;                  /* TRANSWAV, START+LP: begin in the loop */
    set_fc(v);
    v->ph = 0.0; v->stopped_in = -1;
}

void ov_filter(ov_t *v, int on, int mode, int k1, int k2) {
    v->f_on = on; v->f_mode = mode;
    v->k1 = k1 < 0 ? 0 : (k1 > 0xffff ? 0xffff : k1); v->k2 = k2 < 0 ? 0 : (k2 > 0xffff ? 0xffff : k2);
}

void ov_set(ov_t *v, int fc, int src) { v->fc_base = (uint32_t)(fc < 0 ? 0 : fc); v->src = (int16_t)src; set_fc(v); }

void ov_release(ov_t *v) {                                          /* LOOP AND RELEASE: play on to the sample end */
    if (v->loopmode == 4) { w_end(v, v->se); v->cr &= ~CR_LPE; }
}

int ov_done(ov_t *v) { return v->done; }

/* render n output samples (44.1 kHz or the chip rate when step = 1). Returns how many were made before the voice
   ended (the rest are zero). */
int ov_render(ov_t *v, float *out, int n) {
    if (v->done) { memset(out, 0, n * sizeof(float)); return 0; }
    if (v->step == 1.0) {
        for (int i = 0; i < n; i++) {
            if (v->cr & CR_STOP0) { memset(out + i, 0, (n - i) * sizeof(float)); v->done = 1; return i; }
            out[i] = chip_sample(v);
        }
        return n;
    }
    for (int i = 0; i < n; i++) {
        while (v->ph >= 1.0) {                                     /* next chip sample into the history */
            memmove(v->hist, v->hist + 1, (TAPS - 1) * sizeof(float));
            v->hist[TAPS - 1] = chip_sample(v);
            v->ph -= 1.0;
            if (v->cr & CR_STOP0) {
                if (v->stopped_in < 0) v->stopped_in = TAPS;
                else if (--v->stopped_in <= 0) { memset(out + i, 0, (n - i) * sizeof(float)); v->done = 1; return i; }
            }
        }
        double fp = v->ph * PHASES; int p = (int)fp; float t = (float)(fp - p);
        const float *a = sinc_tab[p], *b = sinc_tab[p + 1];
        float acc = 0;
        for (int k = 0; k < TAPS; k++) acc += v->hist[k] * (a[k] + t * (b[k] - a[k]));
        out[i] = acc;
        v->ph += v->step;
    }
    return n;
}

/* for tests: the chip's registers */
void ov_regs(ov_t *v, uint32_t *r) { r[0] = v->accum; r[1] = v->start; r[2] = v->end; r[3] = v->cr; r[4] = v->fc; r[5] = v->tw_cache; }
