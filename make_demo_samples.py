#!/usr/bin/env python3
"""Creates 16 synthetic drum/instrument samples in ./samples so you can test with no recording gear.
Replace any padNN.wav with your own 16-bit WAV (any length, mono or stereo) whenever you like."""
import os, wave
import numpy as np

SR = 44100
rng = np.random.default_rng(1)
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples"), exist_ok=True)


def t(sec): return np.arange(int(SR * sec)) / SR
def env(x, k): return np.exp(-x * k)
def noise(sec): return rng.uniform(-1, 1, int(SR * sec))
def hp(x): return np.diff(x, prepend=0)                       # crude high-pass
def sweep(x, f0, f1, k):                                      # sine with falling pitch
    f = f1 + (f0 - f1) * np.exp(-x * k)
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def kick(): x = t(0.45); return sweep(x, 160, 48, 22) * env(x, 7) * 1.0
def kick2(): x = t(0.3); return (sweep(x, 220, 60, 35) + 0.2 * noise(0.3) * env(x, 80)) * env(x, 10)
def snare(): x = t(0.25); return (0.6 * noise(0.25) * env(x, 16) + 0.5 * np.sin(2 * np.pi * 190 * x) * env(x, 25))
def snare2(): x = t(0.35); return (0.8 * noise(0.35) * env(x, 11) + 0.4 * np.sin(2 * np.pi * 160 * x) * env(x, 18))
def chat(): x = t(0.08); return hp(noise(0.08)) * env(x, 55)
def ohat(): x = t(0.35); return hp(noise(0.35)) * env(x, 9) * 0.8
def clap():
    x = t(0.3); y = np.zeros_like(x)
    for o in (0, 0.012, 0.024): y[int(o * SR):] += noise(0.3)[:len(x) - int(o * SR)] * env(x[:len(x) - int(o * SR)], 40)
    return y * 0.5 + 0.4 * noise(0.3) * env(x, 18)
def rim(): x = t(0.05); return np.sin(2 * np.pi * 1700 * x) * env(x, 90) + 0.3 * noise(0.05) * env(x, 120)
def tom(f): x = t(0.4); return sweep(x, f * 1.6, f, 14) * env(x, 7)
def cowbell(): x = t(0.4); return (np.sign(np.sin(2 * np.pi * 540 * x)) + np.sign(np.sin(2 * np.pi * 800 * x))) * 0.25 * env(x, 9)
def bass(f): x = t(0.6); return (np.sin(2 * np.pi * f * x) + 0.3 * np.sin(4 * np.pi * f * x)) * env(x, 5)
def stab():
    x = t(0.5); return sum(np.sign(np.sin(2 * np.pi * f * x)) for f in (261.6, 329.6, 392.0)) * 0.15 * env(x, 6)
def pluck(): x = t(0.4); return np.sin(2 * np.pi * 880 * x) * env(x, 12) + 0.3 * np.sin(2 * np.pi * 1760 * x) * env(x, 20)
def riser(): x = t(0.8); return hp(noise(0.8)) * (x / 0.8) ** 2 * env(x, 1.5) * 0.7


sounds = [kick, snare, chat, ohat, clap, rim, lambda: tom(90), lambda: tom(140), cowbell,
          lambda: bass(65.4), lambda: bass(98.0), stab, pluck, riser, kick2, snare2]
for i, fn in enumerate(sounds, 1):
    y = fn(); y = y / (np.max(np.abs(y)) or 1) * 0.9
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples", f"pad{i:02d}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((y * 32767).astype("<i2").tobytes())
# a 2-bar drum break at 90 BPM, made from the same sounds, to try the CHOP screen on
def place(buf, snd, at, g):
    a = int(at * SR); n = min(len(snd), len(buf) - a)
    if n > 0: buf[a:a + n] += snd[:n] * g
beat = 60.0 / 90.0
brk = np.zeros(int(SR * beat * 8))
k_, s_, h_, o_ = kick(), snare(), chat(), ohat()
for bar in range(2):
    b0 = bar * 4 * beat
    for st in (0, 7, 10) + ((14,) if bar else ()): place(brk, k_, b0 + st * beat / 4, 0.9)
    for st in (4, 12): place(brk, s_, b0 + st * beat / 4, 0.8)
    for st in range(0, 16, 2): place(brk, h_, b0 + st * beat / 4, 0.35 if st % 4 else 0.5)
    place(brk, o_, b0 + 15 * beat / 4, 0.35)
brk = brk / np.max(np.abs(brk)) * 0.9
with wave.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples", "break.wav"), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((brk * 32767).astype("<i2").tobytes())
print("wrote 16 samples + break.wav (2-bar loop, 90 BPM) to ./samples")
