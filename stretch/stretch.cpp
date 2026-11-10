// stretch.cpp - a tiny C API around Signalsmith Stretch (MIT licence, https://github.com/Signalsmith-Audio/signalsmith-stretch)
// for the sampler's WARP: renders a whole pad region at a new length (and pitch) in one go. Loaded by warp.py with ctypes.
#include "signalsmith-stretch/signalsmith-stretch.h"
#include <vector>
#include <cstring>
#include <algorithm>

extern "C" {

// Stretch mono `in` (n_in samples) to exactly n_out samples, transposed by `semis` semitones.
// quality 0 = presetCheaper, 1 = presetDefault. Returns 1 on success.
int ss_render(const float *in, int n_in, float *out, int n_out, float semis, int sample_rate, int quality) {
    if (n_in <= 0 || n_out <= 0) return 0;
    signalsmith::stretch::SignalsmithStretch<float> st;
    if (quality) st.presetDefault(1, (float)sample_rate); else st.presetCheaper(1, (float)sample_rate);
    if (semis != 0.0f) st.setTransposeSemitones(semis, 8000.0f / sample_rate);
    double rate = (double)n_in / n_out;
    int need = st.outputSeekLength((float)rate) + st.blockSamples() + 1;
    if (n_in >= need) {
        const float *ins[1] = {in};
        float *outs[1] = {out};
        return st.exact(ins, n_in, outs, n_out) ? 1 : 0;
    }
    // too short for one analysis block (a short drum hit): pad with silence, then keep the start
    int pin = need, pout = (int)(need / rate) + 1;
    std::vector<float> a(pin, 0.0f), b(pout, 0.0f);
    std::memcpy(a.data(), in, sizeof(float) * n_in);
    const float *ins[1] = {a.data()};
    float *outs[1] = {b.data()};
    if (!st.exact(ins, pin, outs, pout)) return 0;
    std::memcpy(out, b.data(), sizeof(float) * std::min(n_out, pout));
    for (int i = pout; i < n_out; ++i) out[i] = 0.0f;
    return 1;
}

}
