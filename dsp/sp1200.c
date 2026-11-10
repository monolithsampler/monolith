/* sp1200.c - one SP-1200 voice, from its sample memory to our 44.1 kHz output, the way the hardware does it:

   1. the sample clock (26,041.67 Hz) steps through the sound in whole samples: frame k plays sample floor(k x step),
      repeating or dropping samples to change pitch (no interpolation);
   2. the level DAC scales it: an 8-bit multiplying DAC fed from a 32-entry log PROM, so level (velocity, decay) moves
      in coarse steps, and the decay only steps once per 1.2288 ms tick (32 sample frames);
   3. the demultiplexer's sample-and-hold keeps each value until the next frame: a zero-order hold. Here it is run at
      4x the sample rate (each value repeated four times), so the hold's images above 13 kHz exist as on the real outputs;
   4. the channel's analog filter, at that 4x rate: an SSM2044 4-pole low-pass that every hit opens and that then closes
      (channels 1-2), a fixed 5th-order low-pass (3-6, from the schematic's parts; run at 8x), or nothing (7-8);
   5. a band-limited resample to the output rate - as if the real output were recorded at 44.1 kHz. Nothing that is not
      in the SP's own output folds back.

   The numbers and their sources are in sp1200hw.py and SP1200_NOTES.md. Built with dsp/build.sh. */
#include <math.h>

#define RING 256                    /* history of 4x-rate samples kept for the resampler (power of two) */
#define ST_RING 32                  /* where that history starts in the state array */
#define SP_STATE (ST_RING + RING)   /* doubles of state per voice (sp1200hw.SP_STATE must match) */

/* state: [0] next SP frame  [1] 4x samples made  [2] next output position (in 4x samples)  [3] 4x sample where the
   sound ended (-1: playing)  [4..7] SSM2044 ladder  [8] output-stage shelf  [9..14] fixed filter (3 sections x 2)
   [15] [18] [19] RING tone  [16] level follower (for RING)  [17] 1 = decay reached silence  [ST_RING..] the 4x history */

static double level_step(double env, double step_db)
{
    /* the level PROM: 32 levels, step_db apart; the lowest one is silence */
    if (step_db <= 0) return env;
    if (env <= 0) return 0;
    double q = floor(-20.0 * log10(env) / step_db + 0.5);
    if (q >= 31) return 0;
    return pow(10.0, -q * step_db / 20.0);
}

/* prm: [0] step  [1] the pad's own step (RING)  [2] RING amount  [3] channel kind 0 none / 1 dynamic / 2 fixed
        [4] attack (SP frames)  [5] decay tau (SP frames, 0 none)  [6] decay tick (SP frames)  [7] dynamic: rest Hz
        [8] dynamic: octaves a hit opens it  [9] dynamic: closing tau (SP frames)  [10] 4x rate (Hz)
        [11] 4x samples per output frame  [12..14] output-stage shelf b0 b1 a1  [15] level step (dB, 0 = smooth)
        [16] SSM2044 resonance k (0 = its minimum)
   sos: nsec sections of b0 b1 b2 a1 a2 (fixed filter, at the 4x rate). kern: (nph + 1) x ntap resampler table.
   Returns the output frames written (fewer than n once the sound has ended). */
int sp_voice(const float *d, int dend, double *st, const double *prm, const double *sos, int nsec,
             const float *kern, int ntap, int nph, float *out, int n)
{
    const double step = prm[0], rstep = prm[1], ramt = prm[2];
    const int kind = (int)prm[3];
    const double att = prm[4], dtau = prm[5], tick = prm[6] > 0 ? prm[6] : 1;
    const double frest = prm[7], doct = prm[8], dyntau = prm[9], fs4 = prm[10], adv = prm[11];
    const double sb0 = prm[12], sb1 = prm[13], sa1 = prm[14], lstep = prm[15], kres = prm[16];
    float *hf = (float *)(st + ST_RING);                              /* the 4x history, as floats (RING of them) */
    long k = (long)st[0], made = (long)st[1];
    double pos = st[2], endp = st[3];
    const int half = ntap / 2;
    int j;
    for (j = 0; j < n; j++) {
        if (endp >= 0 && pos >= endp) break;                         /* the sound (and its hold) is over */
        long need = (long)floor(pos) + half + 1;                      /* make 4x samples up to the kernel's far end */
        while (made < need) {
            double x = 0.0, g = 0.0;
            long idx = (long)floor((double)k * step);
            if (endp < 0 && (idx >= dend || st[17] > 0)) endp = (double)made;
            if (endp < 0) {
                x = d[idx];
                if (ramt > 0) {                                       /* RING: the uneven steps' error, at the sound's level */
                    double e = floor((double)(k + 1) * rstep) - floor((double)k * rstep) - rstep;
                    st[16] += 0.004 * (x * x - st[16]);
                    st[15] += 0.515 * (e - st[15]);                   /* softened: three poles at ~3 kHz, so the */
                    st[18] += 0.515 * (st[15] - st[18]);              /* pattern's fast part (up to 13 kHz) stays down */
                    st[19] += 0.515 * (st[18] - st[19]);
                    x += st[19] * sqrt(st[16] > 0 ? st[16] : 0) * 1.4 * ramt;
                }
                double tt = floor((double)k / tick) * tick, env = 1.0;
                if (att > 0) env = tt / att < 1.0 ? tt / att : 1.0;
                if (dtau > 0) env *= exp(-(tt > att ? tt - att : 0) / dtau);
                g = level_step(env, lstep);
                if (dtau > 0 && tt > att && g <= 0) st[17] = 1;       /* decayed to silence: the voice ends */
                x *= g;
            }
            double cg = 0;
            if (kind == 1) {                                          /* SSM2044 cutoff for this frame */
                double fc = frest * pow(2.0, doct * exp(-(double)k / dyntau));
                if (fc > 0.45 * fs4) fc = 0.45 * fs4;
                double gg = tan(M_PI * fc / fs4);
                cg = gg / (1.0 + gg);
            }
            for (int r = 0; r < 4; r++) {                             /* the hold: four 4x samples of the same value */
                double y = x;
                if (kind == 1) {                                      /* 4-pole ladder (zero-delay one-poles) */
                    double *s = st + 4;
                    double fb = kres * s[3];                          /* resonance from the last stage's state (1-sample) */
                    double u = y - fb;
                    for (int p = 0; p < 4; p++) {
                        double v = (u - s[p]) * cg;
                        double o = v + s[p];
                        s[p] = o + v;
                        u = o;
                    }
                    y = u;
                    double w = sb0 * y + st[8];                       /* the TL084 gain stage's top-end shelf */
                    st[8] = sb1 * y - sa1 * w;
                    y = w;
                } else if (kind == 2) {
                    for (int r2 = 0; r2 < 2; r2++) {                  /* designed for 8x: run twice per 4x value */
                        y = x;
                        for (int q = 0; q < nsec; q++) {              /* transposed direct form II */
                            const double *c = sos + 5 * q;
                            double *z = st + 9 + 2 * q;
                            double w = c[0] * y + z[0];
                            z[0] = c[1] * y - c[3] * w + z[1];
                            z[1] = c[2] * y - c[4] * w;
                            y = w;
                        }
                    }
                }
                hf[made & (RING - 1)] = (float)y;
                made++;
            }
            k++;
        }
        /* band-limited resample: the kernel centred on pos, at the nearest of its nph phases (1/4096 of a 4x sample:
           ~2 ns, far below the 12-bit floor) */
        long c0 = (long)floor(pos);
        int ph = (int)((pos - (double)c0) * nph + 0.5);
        const float *k0 = kern + (long)ph * ntap;
        float acc = 0;
        long m0 = c0 - half + 1;                                      /* taps: samples m0 .. m0 + ntap - 1 */
        if (m0 >= 0) {
            int b0 = (int)(m0 & (RING - 1));
            int t1 = RING - b0 < ntap ? RING - b0 : ntap;             /* the history wraps at most once */
            for (int t = 0; t < t1; t++) acc += k0[t] * hf[b0 + t];
            for (int t = t1; t < ntap; t++) acc += k0[t] * hf[t - t1];
        } else {
            for (int t = 0; t < ntap; t++) { long m = m0 + t; if (m >= 0) acc += k0[t] * hf[m & (RING - 1)]; }
        }
        out[j] = (float)acc;
        pos += adv;
    }
    st[0] = (double)k; st[1] = (double)made; st[2] = pos; st[3] = endp;
    return j;
}

int sp_state_size(void) { return SP_STATE; }
