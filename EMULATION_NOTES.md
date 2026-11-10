# Emulation notes

How the classic machines behave, worked out by reading their firmware, written in our own words. Monolith
reimplements the behaviour from these notes; no firmware code or data is copied into the project, and the firmware
images themselves are never part of it.

Status: **MPC60 / MPC3000 timing: done. Main screens for MPC60, MPC3000, MPC2000XL and SP-1200: done** (MAIN > MACHINE).
SP-1200: timing, sound and workflow done (see its section). ASR-10: timing, sound and display done (see its section).
Next: MPC60 / MPC3000 sound, then the 2000XL.

---

## MPC60 (v2.14) and MPC3000 (3.16): timing correct, swing, note repeat

Source: MPC60 v2.14 EPROMs (four 64 KB chips = two 16-bit pairs, 256 KB of 8086-family code at C0000-FFFFF, running the
KADAK AMX real-time kernel) and the MPC3000 3.16 disk OS (a DOS-style program file). The MPC3000 uses the same table and
the same arithmetic for the swung grid; the screen is the same with "Swing%" where the MPC60 says "Shuffle(%)".

### Resolution
96 ticks per quarter note (the same as Monolith).

### Note values ("Timing Correct / Step Size" screen)
| Note value | Step (ticks) |
|---|---|
| OFF (shown as 1/384) | 1 |
| 1/8 | 48 |
| 1/8 triplet | 32 |
| 1/16 | 24 |
| 1/16 triplet | 16 |
| 1/32 | 12 |
| 1/32 triplet | 8 |

### The swung grid
- The grid works in **pairs of steps** (pair = 2 x step).
- The first note of each pair sits at the start of the pair. The second sits at
  **step x swing% / 50, rounded to the nearest tick (half up)**. Swing runs from 50% (straight) to 75%.
  - 1/16 at 50% -> tick 24 of 48, at 54% -> 26, at 66% -> 32 (triplet feel), at 75% -> 36.
  - 1/8 at 66% -> tick 63 of 96.
- **Swing only exists for 1/8 and 1/16.** Choosing any other note value sets swing back to 50%.

### Timing correct (quantise)
- Each note goes to the **nearest grid point of the swung grid**: the change-over between two grid points sits halfway
  between them (at swung/2 and swung/2 + step within each pair, rounded down). A tick exactly on a change-over goes to
  the later point.
  - Example, 1/16 at 66%: ticks 0-15 -> 0, 16-39 -> 32, 40-47 -> 48.
- It happens **when the note is recorded**: the swing is written into the sequence. Playback does not add swing
  again, so changing swing affects new notes only. "Move Existing Notes" applies the same rule to what is already
  recorded (in Monolith: EDIT > QUANTISE).
  - The firmware keeps the recorded notes as a stream of time differences and writes held notes out at each grid point.
    Part of that path runs from code copied into RAM at start-up, so the record-time behaviour is inferred from the
    counters and the help text rather than read line by line.

### Shift timing
- Moves the whole grid **earlier or later** by a number of ticks.
- Largest shift = half the gap after the swung note, less one tick: (pair - swung) / 2 - 1.
  - 1/16 straight: 11 ticks. 1/16 at 66%: 7 ticks.

### Note repeat
- Repeats fire on the **swung grid points**: both notes of every pair, using the same note value, swing and shift as
  timing correct. So note repeat swings on an MPC60, which is a large part of its feel.

### How the firmware runs it (for reference)
- A setup routine turns the note value and swing into three numbers (step, pair, swung position) whenever the timing
  correct screen changes.
- The sequencer's per-tick routine keeps two counters: one through each step and one through each pair. The pair
  counter marks the grid points (0 and the swung position); the step counter is offset so that it rolls over at the
  half-way change-overs. When playback starts mid-sequence, both counters are re-synchronised from the position and the
  shift.

### In Monolith
Choosing MPC60 or MPC3000 as the machine (MACHINE on MAIN, or EDIT > QUANTISE > MACHINE; saved with the project) switches
the sequencer to this timing. With it:
- Recording is timing-corrected onto the swung grid whenever the note value is not OFF (as on the MPC60; Q4 on MAIN sets
  it), with the shift.
- Playback adds no swing of its own.
- QUANTISE moves existing notes the MPC60 way.
- Note repeat swings.
- MAIN shows "MPC60 swing nn%".
TIMING = MODERN keeps Monolith's own behaviour (live, non-destructive swing on 16th off-beats).

---

## Main screens (machines.py, lcd.py)
Laid out from photos of the real screens and filled from Monolith: MPC60 / MPC3000 Play/Record (40 x 8, blue),
MPC2000XL main screen (graphic, here 41 x 7 characters with the F1-F6 soft keys), SP-1200 (16 x 2, green). Fields are
edited the way the machines do it: cursor with the arrows, data wheel = jog.

## Not yet done
- **MPC2000XL**: different code (Akai Japan); its timing has not been checked yet. Its tick table is the same.
- **MPC output stages**: the chips are modelled (below); the analogue outputs need reference recordings to match.

## MPC sound (MPC60: the L4003 chip; MPC3000 and MPC2000XL: the L6028 chip) - dsp/akai.c, mpcvoice.py
Sources: MAME's l4003.cpp and l7a1045_l6028_dsp_a.cpp (BSD licence; R. Belmont, O. Galibert and others) for the chips,
re-written here in C; the three machines' firmware for the program pages (text only); Akai's MPC60, MPC3000 and
MPC2000XL service manuals for the analog paths around the chips.
- **MPC60 (L4003):** 16 voices of 12-bit words at a fixed 40 kHz (35.84 MHz / 896). Pitch is a 4.12 step; the word at
  the integer address is played as it is - no interpolation, so pitched-up sounds alias as on the machine. Each word
  goes through a small recursive filter, done integer for integer as MAME has it ("a pretty literal decompile of the
  assembly code in the MPC3000 which massages the MPC60 samples into 16 bits"). That filter is a de-emphasis: flat at
  1 kHz, -10 dB at 10 kHz. The MPC3000 also needs a third more memory to load an MPC60 sound. **Inference (not traced in
  the MPC60's input stage):** the MPC60 pre-emphasised its sounds when sampling them, as a noise trick for 12 bits. So
  here a sound becomes MPC60 words through the exact inverse filter, then 12 bits; the chip's filter gives back a flat
  sound, its 12-bit hiss ~15 dB lower in the treble than in the mids, and loud treble is the first thing to run out of
  headroom (a sound that would clip is brought down to fit, as setting the record level would). 40 kHz -> 44.1 kHz by
  windowed sinc (the DAC's analogue filter's job). Envelope: straight-line ramps (the chip's). No filter.
- **MPC3000 / MPC2000XL (L6028):** the same chip in both (MAME: "the actual sound generation is identical"): 32 voices,
  16-bit at 44.1 kHz, 4.12 pitch, 8-point windowed-sinc interpolation (MAME's coefficients are textbook; the chip's own
  were not recovered), and a two-pole low-pass in Chamberlin form with 16 resonance steps (RESONANCE 0-100% = 0-15).
  The level and the cutoff move in straight lines toward targets.
- **The analog side (Akai's service manuals; `mpchw.py`):** the chips above are only half of each machine's sound.
  - **MPC60** (manual: parts list + ADC schematic): its input and every output go through a Toko 258BLR-5326N LC
    low-pass, listed as "FILTER LC 258BLR-5326N 18KHZ" - one before the ADC (a PCM77P in a successive-approximation
    loop), one on each of the 8 individual outs, one each on L, R and mix. The PCM54HP DAC is fed at 40 kHz with no
    oversampling, so the output is a held (zero-order) signal: sinc droop, -2.9 dB at 18 kHz. Spec sheet: 20 Hz - 18 kHz,
    "12 bit sample resolution with special non-linear format for reduced noise" (consistent with the emphasis above).
    Modelled: the 18 kHz filter on the way in (255-tap FIR of its curve), band-limited sampling at 40 kHz (it used to
    be a straight-line interpolation, which dulled the top by ~1.6 dB at 10 kHz), a transparent 40 -> 44.1 kHz
    resampler, then the hold's droop and the 18 kHz filter on the way out. *Estimated:* the Toko module's own curve -
    taken as a 7th-order elliptic (0.5 dB ripple to 18 kHz, -50 dB stop): -19 dB at 19 kHz, -40 dB at 20 kHz.
  - **MPC3000** (parts list only - this manual has no schematics): an AK5328 delta-sigma ADC (its own digital
    anti-alias filter) in; out, an SM5841 8x-oversampling digital filter in front of PCM69AP 18-bit DACs. Flat in and
    out to 20 kHz with no hold droop, so nothing is added: its sound is its chip and its filter.
  - **MPC2000XL** (analog board schematic L6044801): an AK5340 delta-sigma ADC in (transparent); out, a PCM69AP-4 fed
    straight at 44.1 kHz - no oversampling filter on any of its boards - so a held output (-3.2 dB at 20 kHz), then an
    I/V stage with 4.99K || 2200 pF (a pole at 14.5 kHz), a unity Sallen-Key (1.91K, 5.76K, 10 nF, 470 pF: 22 kHz,
    Q ~2, which lifts some of that back) and two 72 kHz poles (the volume stage and the balanced driver). Net: -1 dB at
    10 kHz, -2 dB at 19-20 kHz - a gentle top-end roll-off the MPC3000 does not have. Modelled as a 63-tap FIR of the
    exact curve, per voice.
  - Same chip, so the MPC3000 and MPC2000XL differ only here (and in their programs' options): on a sound played near
    its own pitch they are close, as the real ones are.
- **Program pages (firmware text):** MPC60 - Attack, Fadeout, Vel>start, Vel>attack, Vel>vol. MPC3000 - Attack, Decay,
  Dcy md, Sft st (soft start), Volume, Cutoff, Frequency, Vel>Freq, Reson, filter envelope Amount. MPC2000XL - Attack,
  Decay, Dcy md, Freq, Reson, Velo>Attack / Start / Level, filter Attack / Decay / Amount, Velo>Freq, Velo>>Pitch.
- **Estimated:** the cutoff scale (FREQ 0-100: 30 Hz to 9.5 kHz, the most the two-pole stays stable with no
  resonance; 100 = off), ms -> ramp rates (exactly the time asked), DECAY MODE END (from note-off; a one-shot fades into
  its own end), the 12-bit words left-justified in the chip's 16-bit reads, and VEL > PITCH's scale.

---

## SP-1200 (Rossum reissue firmware 1.04, Z80) plus published hardware details

Sources: the 1.04 firmware (read for the values and routines named below); **E-mu's SP-1200 service manual (1987) and its
main-board schematic (doc SK103)** for the audio hardware: the input filter, converters, level DAC, sample-and-holds and
every output filter, worked out from their component values in `sp1200hw.py`; D. T. Yeh, J. Nolting and J. O. Smith,
"Physical and Behavioral Circuit Modeling of the SP-12 Sampler", Proc. ICMC 2007 (CCRMA) - for how to model the hold (4x oversampled zero-order hold, then resample) and the SSM2044 (a ladder with an
exponential cutoff sweep per hit); the libmd12 project's description of the audio path (MIT licence,
github.com/Mudb0y/libmd12); Sound On Sound's 1987 review.

### Timing (from the firmware)
- **24 ticks per quarter note.** The auto-correct table (at 0x09D1) holds the step of each setting in those ticks:
  Off, 1/4 = 24, 1/4t = 16, 1/8 = 12, 1/8t = 8, 1/16 = 6, 1/16t = 4, 1/32 = 3, 1/32t = 2, HiRes = 1.
  So the finest the SP can place a note is a 96th of a whole note (4 of our 96-per-quarter ticks). In SP-1200 mode
  every recorded note lands on that grid, even with auto-correct off.
- **Six swing settings: 50, 54, 58, 63, 67, 71%** (the table follows the "Swing:" prompt). They are exactly 12/24 to
  17/24: the second note of each pair is late by 0-5 twenty-fourths of the pair. On 16ths: 24, 26, 28, 30, 32, 34 ticks
  out of 48 (ours).
- **Swing belongs to the segment**: it is kept in the top half of a byte in each segment's header, with the time
  signature in the bottom half.
- **Note repeat is straight**: the clock interrupt counts down the auto-correct step and, at each grid point, retriggers
  every pad being held. Nothing in that path swings.
- *Inferred, not traced line by line:* auto-correct goes to the nearest grid point, and swing applies to 1/8 and 1/16,
  like the MPC60 (both Linn and E-mu machines of the time worked this way). To be confirmed against a real unit.

### Sound (the voice: `sp1200hw.py` + `dsp/sp1200.c`)
The signal path, in the order the hardware runs it. Numbers in brackets are schematic page / parts.
- **In: a 7th-order elliptic low-pass** (p. 14: three two-integrator loops whose outputs are summed through weighted
  resistors to place notches, then a summing amp with a pole; all 1000 pF). Worked out from its 30-odd parts: ~1.5 dB
  passband ripple, -3 dB at ~13.2 kHz, notches near 16.5, 18.5 and 22.5 kHz, ~-63 dB beyond. Its edge sits just above
  the 13.02 kHz Nyquist, so content between ~13 and 14.5 kHz still folds back a little - as Yeh et al. heard on the SP-12.
  Then an LF398 sample-and-hold and a 12-bit successive-approximation converter (LM311 comparator, 74HCT504, the main DAC):
  **26,041.67 Hz, 12-bit, truncating.** Here: the filter's exact response as a 255-tap FIR (at the sound's own speed for
  45 / 78 rpm), then the filtered signal sampled band-limited at the SP's instants, then floor to 12 bits.
- **Pitch: whole semitones from -16 to +12.** The firmware's pitch table (at 0x224E) gives, per semitone, a step through
  the sample of (byte + 1) / 128; round(128 x 2^(n/12)) / 128 reproduces all 29 entries exactly. The step drops or
  repeats samples **with no interpolation**: the SP's grit.
- **Level: an 8-bit multiplying DAC (AD7523) after the 12-bit one**, fed through a 74S288 log PROM with five address bits
  (p. 8): 32 levels. Velocity and decay move in those steps; since the level is applied after the 12-bit DAC, quiet notes
  do not lose bits. The PROM's contents are not in the manual: taken as even steps to the 8-bit floor (~1.55 dB each).
- **Decay** steps once every 1.2288 ms (the firmware's housekeeping tick = exactly 32 sample frames), down that table;
  when it reaches the bottom the voice ends.
- **The hold** (p. 15): a 4051 demultiplexer charges a 4700 pF poly capacitor per channel, buffered by a TL084: each value
  is held until the next frame - a zero-order hold, with its sinc droop (-2.2 dB at 10 kHz) and its images above 13 kHz.
  Here, as in Yeh et al.: each value repeated 4x at 104.17 kHz, the channel's filter run at that rate, then a 96-tap
  windowed-sinc resample to 44.1 kHz (-6 dB at 21 kHz). The previous model stepped on the 44.1 kHz grid, which jittered
  every hold by up to a sample and folded images that are really above 22 kHz back into the audio; that is gone.
- **8 voices, one per output channel**: pad n of a bank plays on channel n; a new hit on a channel cuts the one before.
- **Output filters** (p. 16-17):
  - channels 1-2: an **SSM2044** 4-pole low-pass (caps 3 x 0.01 uF + 820 pF; input through a 33K / 200R divider; Q pin at
    minimum). Its FREQ pin sits on 390R, fed from -15 V (39K), the tuning trimmer (220K) and a 10 uF capacitor (15K) that
    30K charges toward +15 V. On every hit the processor pulls GAIN1 / GAIN2 low (the same lines that set the sampling
    input's gain) and empties that capacitor through a diode: the pin swings ~112 mV, ~6.2 octaves up at the SSM2044's
    ~18 mV per octave, and the filter then closes exponentially (in octaves) with tau = 10 uF x (30K || 15.4K) = 0.10 s,
    back to its rest frequency. The factory trim (manual p. 33-34) tunes the rest frequency to **1.0 kHz**. So: wide
    open for the first ~50 ms, ~5 kHz at 100 ms, ~1.4 kHz at 250 ms. Then a x5.5 TL084 stage whose 470 pF gives a gentle
    shelf from ~23 kHz. Modelled as a zero-delay 4-pole ladder at 4x (Yeh et al. model it as a Moog ladder).
  - channels 3-6: **fixed 5th-order low-passes** (an RC pole loading a Sallen-Key, then a second Sallen-Key), the same
    capacitors on each, resistors a step smaller each channel: **-3 dB at 7.95, 9.64, 11.56 and 13.11 kHz.** Run as
    bilinear sections at 8x (within 0.35 dB of the analog response up to 15 kHz).
  - channels 7-8: unfiltered: the hold's images up to ~22 kHz are in the output (8 kHz gives an 18.04 kHz image ~7 dB down).
  The old guesses (14 -> 2.6 kHz on 1-2; 6.5 / 9.5 kHz on 3-6) were replaced by these.
- **Not on the schematic, so estimated**: how long the processor holds GAIN low (taken as long enough to empty the
  capacitor - a shorter pulse would open it less); the log PROM's contents; component tolerances (5-10 %: any one unit's
  filters sit a little higher or lower, and the 1-2 trim is set "by ear" on many units).
- CPU: the voice costs ~0.4 % of one core here (C); on the Pi 5 expect roughly 1-1.5 % per sounding SP voice.

### RPM: "sampled at" 45 or 78 (PROG > SAMPLED AT, F3 on PROG)
The SP's memory trick: sample the record at a faster speed, then tune the pad back down. The sound arrives higher, so the
SP's fixed ~13.2 kHz input filter takes away more of it, and it is held in fewer samples; played back down, every sample is
repeated more often, so the stepping and its images get louder. The SP tunes in whole semitones, so each speed is the
nearest whole number up and the pad plays at the original pitch: 45 rpm = 5 st (really 44.5), 78 rpm = 15 st (really 79.3).
Its -16 st floor still applies: at 78 a pad can go only 1 st further down (as on the real machine). Only in SP-1200 mode.

### RING (Q4 on MAIN, 0-100%, starts at 75%) - a model, not from the firmware
Some older SP-1200s hum or whine when sounds are pitched. Monolith models one likely cause: stepping through a sound at
anything but its own speed advances unevenly (a sample repeated now and then when tuned down, skipped when tuned up), at a
rate set by the tuning alone, and a worn output stage lets that unevenness through. RING mixes the error of each step back
in, at the level of the sound. It follows the pad's own tuning (and rpm), not the note: a melody played from a KEYS track keeps one ring
under it, as a fixed hum would. -1 st gives a whine at ~1.4 kHz, a sound at 78 rpm a ~400 Hz buzz and its harmonics; at the sound's own pitch (and at +12) the steps are even and there is no ring. Its strength is set by ear
(`SP_RING_K` in engine.py); a recording of a ringing unit would let it be matched.

### In Monolith (machine = SP-1200)
- MAIN shows its 16 x 2 display: "Seg nn" and the tempo; the second line shows auto-correct and swing (editable with the
  cursor and the jog wheel) and the SP's prompts when something changes.
- Q1-Q4 on MAIN: Tune (whole semitones, -16..+12), Decay (0-31), Swing (its six settings), RING. F3: Autocorrect (its ten).
- PROG: the LO-FI row becomes SAMPLED AT (33 / 45 / 78 rpm); F3 on PROG steps it. Under the GLOBAL heading: CHANNEL
  (AUTO = pad n -> channel n, or 1-8: which output filter a pad goes through - 1-2 dynamic, 3-6 fixed, 7-8 none) and
  DECAY (its 0-31 setting; 31 = the sound plays out).
- The pads play through the SP voice path above (WARP pads keep their own playback).

### Still to do
- Check against recordings of a real unit (a sine sweep through each output, as Yeh et al. did, would confirm the filters
  and the 1-2 sweep; a decaying tone would give the log PROM's steps).
- The decay curve: the pairs table before the pitch table at 0x2230 looks like it; not yet decoded.
- The mix amp and the input preamp's gain stages are taken as clean.

---

## Ensoniq ASR-10 (OS 1.5B ROM, OS disk 3.53) plus its sound chip

Sources:
- The OS 1.5B ROM: two 128 KB EPROMs, high and low bytes, 68000 code at F80000-FBFFFF. Read for the tables and routines
  named below.
- The OS 3.53 disk: a 196 KB extension loaded into RAM. It adds audio tracks, SCSI, backup and Akai / Roland import,
  and some effects. It calls into the ROM about 1,300 times; the sequencer and sound engine live in the ROM.
- MAME's description of the ES5506 ("OTTO") sound chip (BSD licence), for how the chip pitches and filters.
- The Music Technology review (Jan 1993) and Wikipedia, for the structure and specifications.

### Timing (from the ROM)
- **96 ticks per quarter note**, the same as Monolith. Notes are recorded as played, on that clock.
- **No swing anywhere.** No swing setting exists in the ROM, unlike the MPCs and the SP.
- **Quantize is an edit, QUANTIZE TRACK TO 1/x**, one of the track edits alongside TRANSPOSE, SHIFT TRACK BY CLOCKS,
  SCALE EVENT, MERGE TWO TRACKS, FILTER EVENT and EVENT EDIT TRACK.
  - Its values come from a 10-entry table at F84076, in 96ths of a quarter note: 1/4, 1/6, 1/8, 1/12, 1/16, 1/24, 1/32,
    1/48, 1/64 and 1/96. The triplet values have their own names (1/6, 1/12, 1/24, 1/48).
  - The routine (at F93C04) divides each note's time by the step and compares the remainder with half the step. It
    rounds down unless the remainder is larger, so **a note exactly half-way goes to the EARLIER step.** The MPC60
    sends it to the later one.
  - It always quantizes fully: there is no strength setting. Monolith keeps its own STRENGTH row as an extra.
- *Inferred:* quantize happens only as this edit, not while recording. The table has a single user in the ROM.

### Sound
- **The system rate is 29,761.9 Hz with 31 voices, or 44.1 kHz with 23.** The ROM prints "29.7619 KHZ" and
  "44.1000 KHZ"; the OS disk prints "23VOICE 44K".
  - 29,761.9 Hz is a 15.238 MHz chip clock / (16 x 32 voice slots).
  - Sounds are held at that rate, in 16 bits.
- **Pitch is interpolated**, in fine steps, with no stepping. This is the opposite of the SP-1200, and why the ASR
  sounds smooth when pitched.
- **The filter has four one-pole stages and no resonance.**
  - Poles 1 and 2 are always low-pass, on cutoff 1.
  - Poles 3 and 4 are low-pass or high-pass, on cutoff 2: 3LP/1LP, 2LP/2LP, 3LP/1HP or 2LP/2HP.
  - The ROM's "two filters per voice" are those two cutoffs.
  - In Monolith a pad's filter maps onto it:
    - LP = 3LP/1LP with both cutoffs together (24 dB);
    - HP = 2LP/2HP with the low-pass open (12 dB);
    - BP = 2LP/2HP with the cutoffs an octave either side;
    - RESONANCE does nothing, as on the machine.
  - Under PROG > GLOBAL's ASR-10 heading the chip's own controls replace that mapping for ASR sounds: FILTER (its four
    modes, in the ROM's order: F1=2/LP F2=2/HP, F1=3/LP F2=1/HP, F1=2/LP F2=2/LP, F1=3/LP F2=1/LP), CUTOFF F1 / F2 (0-150,
    150 = open) and KBD AMT F1 / F2. As on the chip, a high-pass pole's bigger K is a lower cut-off, so 150 is open in
    every mode. The cutoff scale is estimated (15 Hz .. half the rate), the ROM's table was not found.
- **FX BUS** (per pad): FX1, FX2 or DRY - which of the ASR effect's inputs a pad feeds (its own insert, else its
  program's first, else the master). FX1 / FX2 go in at the effect's BUS 1 / BUS 2 mixes; DRY passes it by.
- **Amp envelope (ENV3), on PROG > ENVELOPES for ASR sounds:** five times (ATTACK, DECAY 1-3, RELEASE) and five levels
  (INITIAL, PEAK, BREAK 1, BREAK 2, SUSTAIN, 0-99), SOFT VEL (the soft-velocity levels as % of the hard ones), VEL
  CURVE (OFF / VEL / VEL1 / VEL2) and ENV MODE (NORMAL; FINISH runs to the sustain first; REPEAT cycles while held) -
  the parameters the ROM's table lists. Straight lines between levels; level -> gain as (L / 99)^1.5, and the VEL1 /
  VEL2 shapes (x^2, sqrt x), are estimated. Velocity works through these levels (not the generic velocity curve).
- **Effects:** the 50 effects in the ROM run as on the machine; see "Effects" below.

### Effects (ES5510 "ESP" chip, run from your ROM)
Sources: the OS 1.5B ROM (the effects library at F9AE2E-FBB5D0, the chip loader, the parameter routines); the OS 3.53
disk (the OS's RAM entry points and its modulation caller); MAME's es5510.cpp (BSD licence) as the reference for the
chip, re-written here in C (dsp/esp.c) and checked against a line-by-line Python copy of MAME, bit for bit.

**What is emulated, and how**
- **The chip:** 160 48-bit instructions per sample, 24-bit registers, a 48-bit multiply-accumulator, 16-bit delay
  memory, with its three-stage pipeline (a multiply lands one instruction later, a memory read two).
- **The programs are the ROM's own.** Each effect's section holds its instructions and starting registers (an "E" block
  the ROM's loader at F973F0 reads), an optional table for the chip's memory (a waveshaping curve, uploaded by F977DC),
  its parameters and its four presets. Nothing is re-created by hand.
- **The parameters are turned into chip values by the ROM's own 68000 routines,** run on a 68000 emulation (the Musashi
  core, MIT licence, in dsp/m68k/): each parameter lists its actions (an action kind + arguments), and the OS runs them
  through its table of routines. The routines call the OS through entry points at FF8000-FF8047 (register write,
  instruction read and write, table upload, the action-list runner at FF801E and the generic modulation engine at
  ROM FB7788); Monolith answers those the same way. So a value moves exactly the registers it moves on the machine.
- **The chip state the OS sets** (found in the ROM): at power-on (F97346) every instruction and register is all ones,
  memory size 0xFF, delay length 0xFFFFFF, delay base 0xF00 and SIGREG all ones (products shifted by one). Before each
  effect (F97744, F973E0): delay length 0xFFFF00, memory cleared, registers 0-8F cleared. After loading, register 7F
  (the effects master level) is faded up to full (F9760C). The loader's last step (F975C0) moves an END at 3A to 3B.
- **I/O:** the ASR's buses go in on serial inputs 0 (FX1 / BUS1), 2 (FX2 / BUS2) and 3 (DRY / BUS3); the output is
  serial 1.
- **Modulation:** the ASR's controllers (WHEEL, PBEND, PRESS, PEDAL, XCTRL, KBD, VEL, KEYDN, SUSTN, FSW-L, PATCH) sit
  in a table the routines read (ROM table FB63D6: source -> offset from $1488). Each control tick the effect's
  modulation routine moves a modulated value toward its target and re-applies it, as the OS does (disk OS 69E6).
- **Rate:** 29,761.9 Hz (44.1 kHz for 44KHZ DELAYS and 44KHZ REVERB). Monolith changes rate on the way in and out
  with a 32-tap Kaiser-windowed sinc (flat to about 13 kHz; the chip's own Nyquist is 14.9 kHz).
- **Names and values** are the ROM's: preset names, parameter names (the full ones from each effect's modulation
  destination list, e.g. "ER LEV2"), and value texts from its lists ("100 MSEC", "4/1", "15 K"). A modulation MIN /
  MAX shows in the units of the parameter it moves.

**A correction to MAME (worked out from the ROM's programs)**
- **A skippable instruction tests the flags and the condition mask as the instruction just before it left them.** MAME
  tests before that instruction's result lands. The ROM's programs settle it: 32 places set the flags in the
  instruction right before a skip (e.g. "ADD ZERO,g60" then a skippable MOV), and 20 write the condition mask (CMR)
  there. With MAME's timing VCF+DISTORT was silent, the compressor and guitar amps faded to nothing and PHASER+DDL
  ran away; with this change they all behave.

**Checked here (no ASR-10 to compare against)**
- All 50 effects load from the ROM and give sound from an impulse and from a sine; none runs away or stays silent.
- WHEEL modulation changes the effects whose presets use it (e.g. CHORUS+REVRB "WHEEL-MIX CHORUS").
- Not compared with a real ASR-10, nor with recordings of one: levels and the exact sound are unconfirmed.

**Not modelled**
- The control tick rate: the OS runs modulation from a timer whose rate was not found; Monolith uses 128 samples
  (about 4.3 ms).
- The ASR's converters and analog stages, and its 16-bit bus mixing before the chip.
- The OS disk's extra effects (the disk adds some; only the ROM's 50 are read).

### Wavesamples: loops, sample modulation and TRANSWAV (the ES5506 chip and the OS that drives it)
Sources: the OS 1.5B ROM (the wavesample parameter table at F82A9C with its 6-bit packed choice lists, the voice
routines at F8D626-F8D91E, release at F8CA72), the OS 3.53 disk (note-on at 7B1A and the modulation dispatcher at
7EB0; the disk's low part loads 0x800 above its file offset), the 68302's on-chip RAM routines the OS copies from
the disk (FC6000: chip register reads and writes), and MAME's es5506.cpp (BSD licence) for the chip, re-written in C
(dsp/otto.c).

**The chip (ES5506 "OTTO")**
- Addresses are 21.11 fixed point. START keeps whole samples, END 1/16 of a sample; each output sample is a linear
  interpolation with the 11-bit fraction. FC (pitch) is 6.11: 2048 plays as recorded.
- A loop runs from START to END, and END maps onto START: playing on past END lands at START plus the overshoot, so a
  cycle of F samples is START = s, END = s + F.
- Control bits: LPE = loop, LPE + BLE = bidirectional, BLE alone = "trans-wave": at END jump to START once, set LEI
  (ignore END) and raise the interrupt.

**The wavesample (the ASR's names)**
- LOOP: FORWARD-NO LOOP, BACKWARD-NO LOOP, LOOP FORWARD, LOOP BIDIRECTION, LOOP AND RELEASE (control words 00, 40,
  08, 18, 08). On release, LOOP AND RELEASE sets END to the sample's end and clears LPE (F8CA72): the sound plays out.
- MOD: OFF, LOOP POS, START, START+LP, LOOPSTRT, LOOP END, LPSTRT-X, TRANSWAV. MOD SRC: the voice's sources
  (LFO, NOISE, ENV1, ENV2, PR+VL, VEL 1, VEL, VEL 2, KBD, PITCH, WHEEL, PEDAL, XCTRL, PRESS, WL+PR, OFF).
  MOD AMT -127..127. RANGE 2 MG .. 1 (22 steps): how many samples a full modulation moves.
- Addresses in a wavesample are 23.9 fixed point (a sample = 512); the chip gets them shifted left 2.

**What each MOD does, per voice update** (amount = MOD AMT x 256 x the source, a 32-bit product)
- START (note-on only): the note begins amount >> RANGE later, kept inside the sound.
- LOOP POS / START+LP: the loop window moves by amount >> RANGE, in whole samples, kept inside the sample. START+LP
  (and TRANSWAV) also start the note at the loop.
- TRANSWAV: frame = (amount >> 16) >> 7 (so MOD AMT 64 and a full source reach frame 63); the window moves by
  frame x the loop's length. Only a changed frame is applied.
- LOOPSTRT: loop start moves (no closer than 4 samples to the end), written at once.
- LOOP END: loop end moves (no closer than 4 samples to the start); if the voice is already past it, the change waits
  for the next pass.
- LPSTRT-X: x = amount >> 16 (1/256 semitone); the loop becomes 2^(x/3072) times as long (its start moves, its end
  stays) and the pitch rises by x - so the loop's own pitch stays put while more or less of the sound is in it. The
  exponential is the ROM's 1536-entry octave table (0x800 x 2^(k/1536), checked equal here).
- **No clicks:** LOOP POS, START+LP and TRANSWAV write the new START, then put the chip in trans-wave mode with the
  interrupt on. The voice finishes its pass through the old loop and jumps into the new one with its phase kept; the
  interrupt handler (F8D8F8) then writes the new END and turns plain looping back on.
- **A quirk kept:** while such a move is waiting, the next is dropped. TRANSWAV has already noted the new frame
  number, so it is not retried until the frame changes again.
- Bidirectional loops get the new window at once.

**In Monolith (machine = ASR-10)**
- Every ASR-10 voice now plays on this model of the chip, at its rate (29,761.9 Hz or 44.1 kHz), and is changed to
  44.1 kHz with a 16-tap windowed sinc.
- **PROG > LOOP / MOD:** LOOP, LOOP START, LOOP END and LOOP POS (moves the loop, keeping its length; shown as length
  and pitch), then MOD, MOD SRC, MOD AMT and RANGE.
- **PROG > LFO / ENV1:** the LFO's wave (its seven: TRIANGLE, SINE/TRI, SINE, POS-SINE, POS-TRI, SAWTOOTH, SQUARE),
  RATE 0-99 (the ROM's steps), DEPTH and DELAY; ENV1 attack / decay / sustain / release.
- **F3 on PROG = MAKE TRANSWAVE:** 64 single cycles are taken evenly through the pad's sound (its pitch found by YIN,
  each cycle started on a rising zero crossing and stretched to exactly one period at the ASR's rate), joined into a
  new sample held at the ASR's rate. The pad then loops the first cycle and TRANSWAV moves through them with ENV1 (a
  1.5 s sweep). Any source, amount or loop can be set after. Played from a KEYS track it is a wavetable synth.
- A looping sound sounds while its note is held (a pad hit with no length: 1 s).
- The transwave's own 29.76 kHz copy is saved in samples/asr/ beside the 44.1 kHz one.
- Mod sources here: LFO, NOISE, ENV1, ENV2 (the pad's amp envelope), VEL, KBD, WHEEL and PRESS (both the MIDI mod
  wheel / aftertouch), OFF.

**Not found / estimated**
- **How often the OS updates a voice.** Its voice task runs in the OS's own scheduler (a 1 ms tick from the 68302's
  timer 2), so the rate depends on load. Monolith uses 10 ms, which puts LFO RATE 99 near 60 Hz.
- ENV1 is attack / decay / sustain / release here; the ASR's envelopes have more stages.
- KBD's scale (here 512 per key from C4) and the sources' exact scaling are not confirmed. The LFO's waves are
  computed, close to the ROM's tables.
- The chip's own volume ramps and its filter are not on this path; the pad's envelope and the ASR filter model run
  after it, as before.

### How it organises a project (differently from an MPC)
- **Wavesample** -> **Layer** -> **Instrument**:
  - an instrument holds up to 127 wavesamples in up to 8 layers;
  - the two patch-select buttons switch which layers sound;
  - 8 instruments are in memory at once, each with its own effect and MIDI settings.
- **Sequences and songs:**
  - 16 tracks per sequence: 1-8 play the instruments in locations 1-8, and 9-16 are MIDI only;
  - up to 80 sequences, at 96 ticks a quarter;
  - one song, made of steps that each play a sequence a number of times (REP);
  - "SONG + ALL SEQS" is saved as one file.
- **Bank file:**
  - a template recording which instrument sits in which location, plus mix, routing, effects and optionally the song;
  - it holds no audio, so its instrument files must be on the disk beside it;
  - loading a bank loads those files.
- Monolith's projects already hold everything in one place. On MAIN the ASR display names things the ASR way:
  TRK n INST n for a track's program.

### In Monolith (machine = ASR-10)
- **MAIN shows its blue-green fluorescent display**, one line of 20 characters with its lit words above. It shows one
  page at a time:
  - SEQ (with BAR and BEAT while playing);
  - TRK / INST;
  - QUANTIZE TO;
  - TEMPO;
  - RATE.
  The arrows step through the pages and the jog wheel changes the page shown. Messages take over the line for a moment,
  as on the machine.
- **Controls:**
  - Q1-Q4: Volume, Tempo, Rate (29.8k / 44.1k) and Quantize (its ten values);
  - F3: QUANTIZE TRACK, as an edit that UNDO can take back;
  - EDIT > QUANTISE: uses its values and its half-way rule, with no swing.
- **Sound:** pads play through the ASR voice path above. WARP pads keep their own playback.
- **Effects:** with your ROM files in firmware/asr10/, the FX page lists the ASR-10's effects ("ASR-10  HALL REVERB"...)
  for any pad, program insert or the master, in every machine mode. Q-links: PRESET, the effect's own parameters,
  INPUT BUS (FX1 / FX2 / DRY) and four modulation sources (WHEEL, PEDAL, PRESSURE, XCTRL, 0-127).

### ASR KEYS (the ASR-10's own way of working, a switch on MAIN's rail)
From the Musician's Manual (section 1). Off by default: the classic ASR screen above stays as it was.
- **Modes and pages:** F1-F3 = LOAD / COMMAND / EDIT. The fourteen page keys sit on MAIN where the track list was, laid out
  as on the panel (Instrument, Seq Song, Sys MIDI, Effects; 1-9 Env 1, Env 2, Env 3, Pitch, Filters, Amp, LFO, Wave, Layer;
  0 Track). A page key = that page; pressed again = its next screen. Never more than two presses to anything.
- **Data entry:** left / right = the next parameter or command, up / down and the jog = its value (SHIFT = fine).
  ENTER-YES = F4 or OK; on a question (QUANTIZE TO=, TO TRACK=, ERASE TRACK 01?) the soft keys become F1 NO / F4 YES.
  CANCEL-NO on the touch screen also puts the last-edited parameter back, as the ASR's does. UNDO stays the project's undo.
- **Q1-Q4:** the page's four main parameters (the ASR has one slider; Monolith adds these).
- **The display:** 22 characters; the mode word boxed top left, the page word(s), STOP / PLAY / REC / ODUB top right
  (flashing for count-in and standby). Only lit words are drawn: the manual does not list the full set of unlit ones.
- **The Studio's screen:** the same display, the ensoniq logo, the page's Q-links and the L / R output meters (MAIN's OUT
  meter makes room for the keys).
- **What is on the pages:** the PROG rows, under the ASR's names - EDIT: Env 1, Env 3 (amp: the five times and levels,
  soft velocity, curve, mode), Pitch, Filters (mode, cutoff F1 / F2, keyboard amounts), Amp, LFO, Wave (start / end, loop,
  modulation), Effects (bus, effect), Sys MIDI (rate), Instrument, Seq Song (tempo, loop, bars), Track (mix, pan, status).
  COMMAND: Wave (TRUNCATE WAVESAMPLE - a trimmed copy, the old sample stays until DELETE UNUSED SAMPLES - NORMALIZE GAIN,
  TIME COMPRESS/EXPAND, CREATE TRANSWAVE), Track (QUANTIZE, COPY, ERASE, SHIFT BY CLOCKS), Seq Song (COPY / ERASE SEQUENCE,
  EDIT SONG STEPS), Instrument (SAVE BANK = save the project). LOAD: the instruments and sequences in memory, and the disk
  (BROWSE).
- **Not there (the page says NOT IN MONOLITH YET):** Env 2 (a filter envelope of the ASR's kind), Layer, pitch tables,
  the ASR's MIDI system settings, the loop commands (cross-fade, synthesized loop).
- **Not checked against a real ASR-10:** how each parameter's line is laid out, and which page words light for some pages
  (MIDI, FX, TRACK).

### Still to do
- **Rate, envelope and LFO tables:** a 160-entry exponential table at F86A32 is probably one of them, but nothing points
  to it directly, so its job is unconfirmed.
- **Layers / patch select, banks, and reading ASR / EPS disk images into projects:** the file formats are documented
  publicly; disk images would be needed to test against.
