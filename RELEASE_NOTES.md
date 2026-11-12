# Monolith v0.9: public preview

The first public release of Monolith, a sampler OS for the Raspberry Pi 5.

## What's in it
- 16 pads in 4 banks with 64 pads per program. Sequences have 16 tracks, and each track plays its own program.
  You get GRID, STEP and SONG modes, plus MUTE with mute groups.
- **Sampling and chopping, the MPC way.** Recordings go into the project rather than onto a pad. CHOP detects slices
  by transient, equal division or beat, or you can cut by hand. Each slice's start and end can be trimmed on its own,
  and CONVERT turns the slices into a new program on an empty track, ready to record. Nothing is ever cut from the
  original sample.
- **GRID editing:** DRAW, SELECT (drag a box around notes) and ERASE tools; move, nudge, lengthen and set velocity on
  the selection from the screen or the Q-links; mute and solo each pad's row.
- **MAIN works like an MPC:** the arrows put a cursor on SEQUENCE, BARS, TRACK, PROGRAM, SWING, Q and BPM; the wheel
  changes it. The MPC Studio's own screen shows the same fields.
- **PROG pages drawn as a panel:** knobs, LED keys, display windows. SAMPLE is a wave view with a beat ruler, START /
  END flags and the warp controls (sample BPM with x2 / /2 / AUTO, stretch).
- **WARP:** pads follow the sequence tempo, pitch independent of speed.
- **Five machine voicings** next to the MODERN engine: MPC60, MPC3000, MPC2000XL, SP-1200 and ASR-10. The ASR-10's
  own effects need your own ROM files.
- **A console mixer** with channel EQ, tape echo, valve drive, filter, crush and bus compression. VST3 instruments and
  effects are supported too.
- **Imports:** MPC2000XL (.SND, .PGM, .APS, .ALL) and MPC 2.x (.xpj).
- **Controllers:** the Akai MPC Studio (mk1) is fully mapped, including its screen. Monolith also works with a touch
  screen, a keyboard, or any MIDI controller via MIDI learn.
- **SETTINGS page:** audio devices, velocity curve, autosave, and a log file for bug reports.

## Known limits
- Tested on one Pi 5 with one MPC Studio. Other setups haven't been tried yet.
- Samples are mono: stereo files and recordings are mixed down to one channel.
- 8 programs and 16 sequences per project; one sample per pad (no layers).
- Pads have no sends of their own; sends and EQ are per program.
- The amp envelope has attack and decay only (no sustain or release).
- Timing resolution is 96 ticks per beat.
- MPC import replaces the current project rather than merging into it.
- The 3D-printed enclosure hasn't been printed or built yet.
- Machine badges aren't included (see `badges/README.md`).

## Install
```
git clone https://github.com/monolithsampler/monolith.git ~/monolith-studio
cd ~/monolith-studio
bash setup.sh
bash start.sh
```
