#!/bin/sh
# builds libsp1200.so (the SP-1200 voice: sp1200hw.py), libakai.so (the MPC60's L4003 and the MPC3000 / 2000XL's L6028 voice chips), libvoicefx.so (pad filters, master filter), libesp.so (the ASR-10 effects chip), libotto.so (an ASR-10
# voice: its sound chip's looping and the OS's sample modulation) and libasr68k.so (a 68000, the
# Musashi core in m68k/, MIT licence, that runs the ASR-10 ROM's own effect-parameter routines; about 15 s).
# sampler_os.py also builds them on first start if cc is there.
cd "$(dirname "$0")" && cc -O3 -ffast-math -fPIC -shared -o libsp1200.so sp1200.c -lm && echo "built dsp/libsp1200.so" \
  && cc -O2 -ffast-math -fPIC -shared -o libvoicefx.so voicefx.c -lm && echo "built dsp/libvoicefx.so" \
  && cc -O2 -fPIC -shared -o libesp.so esp.c && echo "built dsp/libesp.so" \
  && cc -O2 -fPIC -shared -o libotto.so otto.c -lm && echo "built dsp/libotto.so" \
  && cc -O2 -fPIC -shared -o libakai.so akai.c -lm && echo "built dsp/libakai.so" \
  && cc -O2 -fPIC -shared -o libasr68k.so asr68k.c m68k/m68kcpu.c m68k/m68kops.c m68k/softfloat/softfloat.c -lm \
  && echo "built dsp/libasr68k.so"
