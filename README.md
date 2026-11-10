# Monolith

**A sampler OS for the Raspberry Pi 5.** Play it from an Akai MPC Studio (mk1), a touch screen or any MIDI controller.
It has 16 pads, sequences with a track per program, non-destructive chopping, WARP time-stretch, a console mixer with
effects, and five machine voicings modelled on classic samplers (MPC60, MPC3000, MPC2000XL, SP-1200, ASR-10) next to its
own MODERN engine. It can also import MPC2000XL and MPC 2.x projects.

This is **v0.9, a public preview.** It runs, and it passes about 800 automated checks. It has been played on one Pi 5
with one MPC Studio. Expect rough edges, and please report what breaks (SETTINGS > SAVE LOG TO USB makes a log file to
attach to a bug report).

**Quick start** (on Raspberry Pi OS, 64-bit):
```
git clone https://github.com/<you>/monolith.git ~/monolith-studio
cd ~/monolith-studio
bash setup.sh
bash start.sh
```
`setup.sh` installs the packages and builds the audio engine; section 8 has the details.

**Machine badges:** each machine's MAIN panel can show a badge image. None are included here, because the original
logos belong to their makers. Without them, the machine's name is shown instead. To use your own images, put PNGs in
`badges/` (see `badges/README.md`).

**Also here:** a 3D-printable enclosure and hardware design (`make_stl.py`, `renders/`). It has been modelled and
geometry-checked, but not yet printed or built.

Akai, MPC, E-mu, SP-1200, Ensoniq and ASR-10 are trademarks of their owners. Monolith is an independent project, not
affiliated with or endorsed by them, and it includes none of their firmware, ROMs or sounds.

---

## Contents
1. What it is
2. Files
3. Parts to buy
4. Before you print: measure your parts
5. Printing
6. Wiring
7. Assembly
8. Software: install and run
9. Using it
10. Identity and branding
11. Examples
12. What was and was not tested
13. Third-party code and licences

---

## 1. What it is

**Hardware**
- **Size:** 331 mm between the cheeks (371 mm over them), about 302 mm front to back; the rear console stands about 98 mm tall.
- **Body:** a sloped wedge (7 degree panel) printed in two halves that each fit a 220 mm bed, joined by straps hidden under the lid.
- **Cheeks:** two plain wooden wedge boards, square corners, nothing on the outer faces, stained very dark (nearly black, the grain still showing). Each top edge is flat beside the palm rest (flush with its pad), then runs as a low rail 6 mm above the panel all the way back, so it never walls in the pads or the Q knobs. At the rear console it steps square up and finishes flush with the console's top.
- **Palm rest:** a padded vinyl rest across the front, MPC60 mk1 style: a printed core with a removable foam-and-vinyl pad. The headphone jack and its level knob sit on its front face.
- **Rear console:** a full-width block behind the panel. It holds the Pi 5 with an 8-output DAC HAT, the hinge rod, the screen's two hinge legs, a 2 x 12 LED VU meter, PWR / PLAY / REC lights and a nameplate-shaped badge pocket on its front face, left of the hinge. The back panel has 8 x 1/4 inch outputs, 2 x 1/4 inch inputs, USB-C power, Ethernet, USB-A, a power button and vent slots, all engraved to read from behind.
- **Screen:** a 10.1 inch 1280 x 800 IPS HDMI touch module in a 270 x 172 x 30 mm frame that folds shut over the keys and leans back up to 45 degrees. The UI fills the whole panel and is drawn at its full resolution. Only two thin cables cross the hinge: HDMI and one micro-USB for touch and power.
- **Controls:**
  - 16 MPC-style pads on piezo sensors, in 4 banks (A-D).
  - 29 Cherry MX-style switches with printed square caps, each with its name engraved. Front to back on the key panel:
    - **transport** (REC, OVERDUB, STOP, PLAY, PLAY START) as one tape-deck bar: wide 30.5 x 22 mm caps side by side with 1 mm joints, the bar's bottom edge in line with the bottom row of pads. Each cap is about 1.6u wide, which needs no stabiliser, but press near the middle; if the ends rock on your switches, print the caps slightly narrower (`TR_GAP`);
    - the **jog wheel** (left) and the **D-pad with OK** (right), sitting a little below centre between the transport row and the keys above, shifted left so the D-pad keeps clear of the Q knobs;
    - **SHIFT** (yellow, directly over the jog wheel) and the play keys NOTE REPEAT, ERASE, TAP, UNDO (no BANK key: SHIFT + F1-F4 picks bank A-D);
    - the **screen keys**, following the on-screen tabs (MAIN GRID LOAD MUTE PROG / SAMPLE CHOP MIXER FX SONG). **LOAD** is the file browser (SHIFT + LOAD: projects); there is no STEP key: press GRID again to go from the track grid to all tracks to STEP; SHIFT + MUTE opens the pad modes.
    - The upper key rows sit on a 22 mm grid, so their columns line up.
    - The **soft keys F1-F4** are in a row directly behind the pads, one over each pad column.
  - A jog wheel (a small encoder with a printed, weighted 50 mm wheel).
  - 4 Q-link knobs in a column down the right edge.
- **Electronics:** an Arduino Uno scans the pads (CD4067 multiplexer), the 4 knobs and 23 of the keys (three 74HC165 shift registers; input 18 is free), and drives the VU meter and lights. The D-pad, OK, jog and SONG key go straight to the Pi.

**Software (Monolith)**
- 1280 x 800 touch UI (an 800 x 500 layout drawn sharp at 1.6x, no upscaling) with ten screens: MAIN, GRID (the current track, or ALL TRACKS), STEP, MUTE, PROG, SAMPLE, CHOP, MIXER, FX, SONG, plus a MENU page (PROJECTS, BROWSE, EDIT, PAD MODES, MIDI, TRACK OUT, SONG, SAVE) and an on-screen keyboard for naming things.
- **MPC data model:** sources (audio) -> pads -> programs -> tracks -> sequences -> song. 8 drum programs of 64 pads, 16 sequences of 16 tracks, 96 ppq.
- **Projects:** as many as you like (new, open, save as), the last one opens at start-up; sequences, tracks, programs and samples can be renamed.
- **Sequencer:** automation lanes on GRID (track level / pan, program insert parameters), record / overdub, count-in, metronome, record quantize, swing, undo / redo (notes, automation, bars), erase while playing, note repeat, mute / solo, song mode.
- **Edit tools:** copy / insert / delete bars, time signature, quantize with strength and swing, nudge, copy sequence / track / pad.
- **Track types:** DRUM (a program's pads), KEYGROUP (one pad played chromatically), PLUGIN (a VST3 synth), MIDI (to external gear). Note tracks get a piano roll.
- **Non-destructive chop** by equal slices, beats, transients or by hand; chops stay linked to their markers.
- **WARP:** pads follow the sequence tempo while playing, even mid-note (Signalsmith Stretch).
- **SP-1200-style lo-fi:** 26.04 kHz / 12-bit per pad.
- **Pad envelope and filter:** attack, decay; low-pass / high-pass / band-pass with resonance, its own envelope and velocity (in C: `dsp/`).
- **Resampling:** record the sampler's own output onto a pad.
- **Machines:** MODERN, MPC60, MPC3000, MPC2000XL, SP-1200 or ASR-10 (tap MACHINE on MAIN, then the machine name to step on). MAIN's sequence panel becomes that machine's screen in its bezel: the MPC60 / MPC3000 blue 40 x 8 Play/Record screen, the MPC2000XL's grey graphic screen with its soft keys, the SP-1200's green 16 x 2. The arrows move the cursor between fields, the jog wheel changes them, a tap selects a field (tap again to step it), F1-F4 become the machine's soft keys (MPCs) and Q4 sets the timing correct note value. MPC60 and MPC3000 also bring their timing: swing goes into the notes as they are recorded, onto the swung grid, with shift timing, and note repeat swings (see `EMULATION_NOTES.md`). SP-1200 also brings its sound and timing, modelled from E-mu's service-manual schematic: its 7th-order input filter, 26.04 kHz / 12-bit sounds stepped through in whole semitones with no interpolation, its 32-step level DAC and decay ticks, the sample-and-hold's real output (with its images above 13 kHz), one voice per channel with the SSM2044 dynamic filters on 1-2 and the fixed 5th-order filters (7.9 / 9.6 / 11.6 / 13.1 kHz) on 3-6, its 24-a-quarter clock, six swing steps and straight note repeat; Q1-Q4 become Tune / Decay / Swing / RING (an older unit's hum on pitched sounds; F3 = Autocorrect), and on PROG each pad can be "sampled at" 33, 45 or 78 rpm and tuned back down for more grit. ASR-10 brings its blue-green fluorescent display (one page at a time), its timing (no swing; QUANTIZE TRACK on F3 with its ten values, half-way notes going earlier) and its sound (29.76 or 44.1 kHz, smooth interpolated pitch, a 4-pole filter with no resonance). With your own ASR-10 ROM files in `firmware/asr10/`, its 50 effects (reverbs, delays, chorus, pitch shift, distortion, guitar amps, compressor...) appear on the FX page in any machine mode, running the ROM's own effect programs and parameter routines. Its voices play on a model of its sound chip with the wavesample loops and sample modulation of its OS, including TRANSWAV (wavetable sweeps); PROG F3 makes a transwave from any pad. The MPCs bring their sound: the MPC60 on a model of its L4003 chip (12-bit, 40 kHz, no interpolation, its de-emphasis filter, no filter of its own), the MPC3000 and MPC2000XL on the L6028 (16-bit, 44.1 kHz, 8-point interpolation, a resonant two-pole low-pass). The 2000XL's timing is not checked yet.
- **Effects:** an insert per pad, 4 per program, one on the master: built-ins (Drive, Filter, Delay, Crush) or VST3 plug-ins, which can show their own window. A small bundled VST3 host is included.
- **FLATTEN PAD:** bakes a pad's processing into a new sample (undoable).
- **TRACK OUT:** every track plus the mix to WAV.
- **Pad modes:** 16 Levels, Perform (scales / chords), Track Mute, Next Sequence.
- **Q-link modes.**
- **File browser:** with USB drive mounting.
- **MPC import:** MPC2000XL folders (.SND sounds, .PGM / .APS programs, .ALL sequences and songs) and MPC 2.x projects (.xpj: drum programs with their chops, WARP and sequences), from a USB stick.
- **USB MIDI:** in and out with MIDI learn, MIDI clock (send or follow), pitch bend, mod wheel and aftertouch.
- 8-output routing per pad.

---

## 2. Files

**Program**
| File | What it is |
|---|---|
| `sampler_os.py` | start the sampler (screen, audio, inputs); `--shots` writes a PNG of every screen |
| `engine.py` | audio engine and sequencer |
| `ui.py`, `screens.py`, `uicore.py` | controls and the screens (800 x 500 layout units, drawn at the panel's own resolution) |
| `skin.py` | the look: raised keys, sunk wells, plates, glass, knobs, LEDs, tracked labels, the dot-matrix readouts. Each part is drawn once at 3x and scaled down (smooth edges), then cached, so a frame only pastes them (about 8-13 ms a frame at 1280 x 800 here; not yet timed on the Pi). The accent colour follows the machine |
| `fx.py`, `vst3host/` | effects, VST3 loading; `vst3host/build.sh` builds the bundled VST3 host |
| `warp.py`, `stretch/` | WARP time-stretch; `stretch/build.sh` builds Signalsmith Stretch |
| `midi.py` | USB MIDI in / out, MIDI learn, MMC, clock, pitch bend, mod wheel |
| `dspfast.py`, `dsp/` | the pad filters and the master filter in C; `dsp/build.sh` builds it (the sampler also builds it on first start; without a C compiler it falls back to slower Python) |
| `mpcvoice.py`, `dsp/akai.c` | the MPCs' voices: the MPC60's L4003 (12-bit, 40 kHz) and the MPC3000 / 2000XL's L6028 (interpolation, resonant low-pass), their envelopes and velocity settings |
| `asrvoice.py`, `dsp/otto.c` | an ASR-10 voice: its ES5506 sound chip's looping and the OS's sample modulation (TRANSWAV, LOOP POS...), its LFO / ENV1, and the transwave maker |
| `asrfx.py`, `dsp/esp.c`, `dsp/asr68k.c`, `dsp/m68k/`, `firmware/asr10/` | the ASR-10's effects, read from your own ASR-10 ROM (put it in `firmware/asr10/`): its effects chip in C, and a 68000 that runs the ROM's parameter routines (see `EMULATION_NOTES.md`) |
| `mpc_import.py` | reads MPC2000XL .SND / .PGM / .APS / .ALL files and imports a project (section 9) |
| `sp1200_import.py`, `SP1200_NOTES.md` | Rossum SP-1200 .sp12 reader: parked, not in the UI (see the notes) |
| `EMULATION_NOTES.md` | how the MPC60 / MPC3000 time and swing notes, worked out from their firmware |
| `machines.py`, `lcd.py` | the machines' main screens (text, fields, soft keys) and the dot-matrix LCD drawing (public-domain X11 6x9 font baked in) |
| `mpc2_import.py` | reads MPC 2.x projects (.xpj, .xpm, .sxq, slices inside the WAVs) and imports them (section 9) |
| `inputs.py` | touch screen and the Pi's GPIO keys / jog |
| `sampler_controller.ino` | Arduino firmware: pads, knobs, 24 keys, VU meter and lights |
| `sampler-os.service` | starts the sampler at boot |
| `50-sampler-udisks.rules` | lets the sampler mount and eject USB drives without a desktop |
| `make_demo_samples.py`, `samples/` | the demo kit and a 2-bar break |
| `test_ui.py` | the self-test (795 checks) |

**Printable parts (STL, mm)**
| File | Print | Notes |
|---|---|---|
| `pad_test_coupon.stl` | 1, **first** | one pad opening: check your pads fit |
| `controller_base_left.stl`, `controller_base_right.stl` | 1 each | body floor and walls (158 / 173 mm wide) |
| `controller_lid_left.stl`, `controller_lid_right.stl` | 1 each | top panel with the MX plate, pad and knob holes; exported smooth side down |
| `join_strap.stl` | 10 | 2 on the base, 2 under the lid, 2 in the console, 1 under the palm rest, 3 inside the display tray |
| `rear_console_left.stl`, `rear_console_right.stl` | 1 each | console with back panel, Pi standoffs and badge pocket; front face down |
| `palmrest_left.stl`, `palmrest_right.stl` | 1 each | palm rest core, exported top down |
| `frame_bezel_left.stl`, `frame_bezel_right.stl` | 1 each | display bezel, front face down (135 x 172 mm each). Glue the seam; 4 screws beside it pull both halves onto posts in the tray |
| `frame_tray_left.stl`, `frame_tray_right.stl` | 1 each | display tray, open side up, supports under the hinge ear. Cut 34 mm from the bezel seam; joined by 3 join straps inside (M3 x 8 + nuts) and glue |
| `hinge_spacer.stl` | 2 | sleeves on the hinge rod |
| `keycaps_all.stl` | 1 plate | all 29 caps, engraved, face down (167 x 124 mm: the transport caps in their own row) |
| `jog_wheel.stl` | 1 | weighted 50 mm jog wheel, top down |
| `keycaps/keycap_<name>.stl` | spares | one cap per file, to reprint a single key |
| `keycap_transport.stl`, `keycap_small.stl`, `keycap_arrow.stl` | spares | blank caps |
| `pad_cap.stl` | optional | printed pads, only if you have no MPC pads |
| `controller_base_full.stl`, `controller_lid_full.stl` | optional | one-piece body for a 340 mm bed |
| `cheek_reference.stl` | no | the wooden cheek, for pictures |

**Drawings and pictures**
| File | What it is |
|---|---|
| `cheek_template.svg` | 1:1 cutting template for the wooden cheeks (8 straight cuts including one inside corner at the console step, hole positions) |
| `panel_artwork.svg` | 1:1 top panel: key, pad, knob and jog cut-outs |
| `console_artwork.svg` | 1:1 console front face (lights, VU windows, badge pocket) and back panel |
| `wiring_diagram.svg` | system diagram, multiplexer, pads, 74HC165 chain, panel layout, side view, Pi GPIO table |
| `renders/` | renders of the device |
| `make_stl.py`, `chk7.py`, `make_artwork.py`, `make_diagram.py`, `make_render.py` | regenerate all of the above after changing the numbers at the top of `make_stl.py`; `chk7.py` checks the geometry |
| `brand/make_brand.py` | turns a logo into the badge, start-up screen and artwork (section 10) |
| `examples/` | MPC import test projects and a command-line import (section 11) |

---

## 3. Parts to buy

Prices change and parts vary between sellers: check the sizes in section 4 against what you actually buy.

**Brain and audio**
- Raspberry Pi 5 (4 or 8 GB) with the active cooler, a 5 V 5 A USB-C supply (the official 27 W one) and a 32 GB+ microSD card
- audio: **HiFiBerry DAC8x** (8 outputs, Pi 5 only) + **HiFiBerry ADC8x add-on** (8 inputs, plugs onto the DAC8x). One sound card, one clock: recordings stay locked to playback. The Studio DAC8x is **not** an option: HiFiBerry confirms the ADC8x only works with the standard DAC8x. Both boards have 3.5 mm stereo jacks (the DAC8x: four, channels 1/2, 3/4, 5/6, 7/8; check the ADC8x when it arrives); line level, up to 2.1 V RMS
- 10.1 inch 1280 x 800 IPS HDMI touch module, GT911 USB touch, 5 V micro-USB (the one chosen: 239.4 x 157.4 x 12.3 mm, about 5.3 W, HDMI and two micro-USB sockets on the back). Plug its touch & power socket into a Pi USB port: about 1.1 A, inside the 1.6 A the Pi 5 allows on its USB ports with the official 5 A supply. If the screen browns out or flickers, feed its power-only socket from the 5 V supply instead. A 1024 x 600 7 inch screen still works (set `DISP_*` and `FR_*` back)
- a right-angle micro-USB lead, and a right-angle or flat FPC HDMI plug for the screen end: 11.7 mm of space is behind the module, and the tray floor is open behind its sockets
- a small 5 V stereo headphone amplifier board with a 9 mm volume pot (e.g. TPA6132 / PAM8908 based)

**Jacks, ports, cables**
- 8 x mono (TS) female 1/4 inch panel jacks for the outputs, 2 for the inputs, 1 x stereo 1/4 inch jack for headphones (holes 9.8 mm; metal jacks with a threaded bushing long enough for the 3 mm wall + nut)
- 3 x 3.5 mm stereo male-to-male leads, about 30 cm, cut in half (5 of the 6 halves are used): right-angle plugs if you can get them, as the console is only 30 mm deep inside
- panel-mount extension leads, about 20-30 cm: USB-C female to male (power in), RJ45 coupler with lead, USB-A female to male
- a right-angle USB-C plug (the Pi's power socket points down)
- a thin micro-HDMI to HDMI lead (a flat FPC-style lead flexes best) and a thin USB lead, about 40 cm each, for the screen
- a 12 mm momentary push button and a 2-pin lead to the Pi 5's J2 power-button header
- a 10-wire ribbon cable (body to Pi: up, down, left, right, OK, jog A, jog B, jog push, SONG, ground) and hookup wire

**Controls**
- 16 MPC-style pad rubbers, 16 piezo discs, 16 x 1 M resistors, 16 x 5.1 V zener diodes, thin foam
- Arduino Uno (with its USB lead) and a CD4067 16-channel multiplexer breakout
- 3 x 74HC165 (DIP-16), 3 x 9-pin 10 k bussed resistor networks (or 24 x 10 k), 3 x 100 nF, perfboard about 76 x 32 mm
- 29 x Cherry MX-compatible plate-mount switches (silent tactile is a good start; buy a cheap switch tester to choose)
- 4 x 10 k linear pots with 7 mm bushings and knobs (Q-links)
- jog: a 7 mm-bushing rotary encoder with push switch and a 6 mm D shaft, 15-20 mm long (generic EC11; a Bourns PEC11R or Alps EC11 feels better), plus 3 x M16 flat washers for the printed wheel
- lights: 26 WS2812B pixels cut from a 100 LED/m strip (2 x 12 for the VU meter, 2 for PLAY / REC), a 330 ohm resistor and a 470 uF capacitor for the strip, a green 5 mm LED and 330 ohm for POWER, diffuser tape; the Adafruit NeoPixel library

**Wood and hardware**
- 2 hardwood boards, 20 x 100 x 305 mm (the cheeks); an open-grained wood such as oak or ash shows its grain best under the dark stain
- black or ebony wood stain, and a clear oil or hard-wax finish (the grain shows through a stain, not through paint)
- M8 threaded rod, 354 mm; 2 M8 nyloc nuts, 4 M8 washers, 2 M8 wave (spring) washers, a little epoxy
- screws: 9 x M3 x 10 (lid), 14 x M3 x 8 (straps), 6 x M3 x 8 (panel-mount leads), 4 x M3 x 12 bolts + nuts (palm rest), 4 x M2.5 x 6 (Pi), and about 14 wood screws (3.5 x 16 mm) into the cheeks (per side: 4 from the body, 2 from the console, 1 from the palm rest)

**Palm rest pad**
- 3 mm hardboard 329 x 57 mm, 10 mm high-density upholstery foam, black vinyl about 380 x 110 mm, contact adhesive, 4 hook-and-loop pads

**Filament:** PLA, all body parts in one black: base, lid, rear console, palm rest core and the screen frame (bezel and tray), so the screen enclosure matches the body.

---

## 4. Before you print: measure your parts

Nothing is guaranteed to fit until you check. Change the CONFIG numbers at the top of `make_stl.py`, run `python3 make_stl.py`,
then `python3 chk7.py` to re-check the geometry.
1. **Pads:** `PITCH` (centre to centre) and `HOLE` (opening). Print `pad_test_coupon.stl` first.
2. **MX switches:** `MX_HOLE` 14.2 and `MX_RECESS` 15.8 are the usual values. The lid is 3 mm thick: a 1.5 mm recess on top, and a 1.5 mm plate underneath that the switch clips into. Print one key position as a test and push a switch in before printing the lid.
3. **Keycaps:** the MX stem socket is a 4.1 x 1.44 mm cross with print tolerance. Print one cap and test it on a switch. The caps are flat, square and skirtless, not Cherry-profile caps.
4. **Knobs and jog:** `POT_D` (7.5 for 7 mm bushings), `JOG_D` (7.4 for a 7 mm encoder bushing), `JOG_WHEEL_D` (50). The jog wheel's bore is a 6 mm D shaft.
5. **Display:** `DISP_BOARD` 239.4 x 157.4 mm and `DISP_T` 12.3 mm are the listing's figures; `DISP_WINDOW` (221 x 140) is the 216.6 x 135.4 active area plus about 2 mm each side. Measure the black border on all four sides: if the picture is off-centre on the glass, set `DISP_WIN_OFF`. `DISP_PORTS` is where the floor opens behind the sockets: check it against yours.
6. **Display depth:** `FR_T` 30 mm leaves 11.7 mm between the module's back and the tray floor for the plugs; four rests with 1 mm foam tape hold the module against the bezel. If your plugs are taller, raise `FR_T` and re-run `chk7.py` (at 30 mm the frame still folds flat and leans back to 45 degrees).
7. **Pi stack and back panel:** `PI_ORIGIN`, `PI_STAND`, `RISER_D`. The console is 30 mm deep inside: a 5 mm standoff, the Pi and the HAT must fit, with the HAT's tallest parts under about 10 mm. `JACK_D` and the `PORTS` window sizes depend on the jacks and leads you buy.
8. **Cheeks:** `CHEEK_T` is the timber thickness (20 mm). The template and rod length follow it.

---

## 5. Printing

PLA, 0.2 mm layers, 3 walls, 15 % infill. Exceptions:
- **Keycaps:** 0.12-0.16 mm layers, face down, no supports. To make the legends readable, rub a paint pen or coloured wax over the face and wipe it off: the colour stays in the engraved letters.
- **Rear console:** front face down, supports inside and under the sloped top.
- **Frame tray:** open side up, with supports under the two hinge ears.
- **Palm rest core:** top down, as exported.
- **Jog wheel:** top down.

The largest pieces are 158 x 206 mm and 173 x 206 mm, so everything fits a 220 mm bed.

---

## 6. Wiring

See `wiring_diagram.svg`.
- **Pads:** each piezo, with a 1 M resistor and a 5.1 V zener across it, goes into the CD4067 (I0-I15 = pads 1-16). CD4067: A-D on D6-D9, COM to A0, INH to GND.
- **Knobs:** the wipers go to A1-A4, the outer legs to 5 V and GND.
- **Keys:** each key switches its 74HC165 input to GND, with a 10 k pull-up to 5 V. Chain the three chips: SH/LD of all three to D2, CLK of all three to D3, QH of chip 1 to D4. Chip 1 = keys 0-7, chip 2 = 8-15, chip 3 = 16-23; inputs A-H are pins 11, 12, 13, 14, 3, 4, 5, 6. Put 100 nF across each chip's supply.
- **Lights:** WS2812 data on D5 through 330 ohm, 470 uF across the strip. Pixels 0-11 are VU left, 12-23 VU right, 24 PLAY, 25 REC. The POWER LED is a plain LED on 5 V.
- **To the Pi** (switch to GND, no resistors): up GPIO 5, down 6, left 13, right 12, OK 16, jog A 17, jog B 10, jog push 9, SONG 11. None of these touch GPIO 2-4 or 18-27, which are kept free for the DAC8x and ADC8x. Keep SPI disabled.
- **Audio jacks:** cut each 3.5 mm lead in half and solder the cut end to two mono 1/4 inch jacks: **tip** to the tip lug of the odd jack (OUT 1, 3, 5, 7 or IN L), **ring** to the tip lug of the even jack (OUT 2, 4, 6, 8 or IN R), **sleeve** to the sleeve lugs of both. Plug the four output leads into the DAC8x (1/2, 3/4, 5/6, 7/8) and one lead into the ADC8x's first input pair. The case is plastic, so all grounds meet only at the HiFiBerry: add no other ground wires (no hum loops). Zip-tie the leads to the console so cables plugged in at the back cannot pull the 3.5 mm plugs out.
- **Headphones:** the amp's input comes from OUT 1/2 (solder its wires to the OUT 1 and OUT 2 jack lugs), its 5 V from the Pi's 5 V pin. Its jack and pot sit on the palm rest's front face, and the leads run into the body through the 12 mm hole.
- **Power button:** to the Pi 5's J2 header. Press to start, press again for a clean shut-down.
- **Upload** `sampler_controller.ino` (Adafruit NeoPixel library needed).

**Key map** (Arduino button number = shift-register position; numbers are wiring order, not panel position)
| # | Key | # | Key | # | Key |
|---|---|---|---|---|---|
| 0 | REC | 8 | LOAD | 16 | UNDO |
| 1 | OVERDUB | 9 | PROG | 17 | TAP |
| 2 | STOP | 10 | SAMPLE | 18 | (free: no BANK key) |
| 3 | PLAY | 11 | CHOP | 19 | NOTE REPEAT |
| 4 | PLAY START | 12 | MIXER | 20-23 | F1 F2 F3 F4 |
| 5 | MAIN | 13 | FX | | |
| 6 | GRID | 14 | SHIFT | | |
| 7 | MUTE | 15 | ERASE | | |

**Serial protocol** (115200 baud, one line per event):
- Arduino to Pi: `P,<pad 1-16>,<velocity>`, `K,<knob 0-3>,<0-127>`, `B,<button 0-23>,<1|0>`.
- Pi to Arduino, about 20 times a second: `V,<left 0-255>,<right 0-255>` (VU meter) and `S,<bits>` (bit 0 PLAY, bit 1 REC).

---

## 7. Assembly

1. **Body:** join the two base halves with 2 straps on the base posts and the two lid halves with 2 straps screwed up into the lid bosses from below (M3 x 8). Nothing shows on top.
2. **Keys and controls:** push the 29 MX switches into the lid from the top (they clip into the lower 1.5 mm) and wire them underneath. Fit the pads over their piezos and foam, the 4 pots, and the jog encoder. The 74HC165 board sits on the floor under the keys (foam tape); the Arduino sits on its posts behind the pads. Glue 3 M16 washers into the jog wheel's underside and push it onto the encoder shaft.
3. **Palm rest:** bolt the two core halves to the body's front wall (4 x M3 x 12, nuts inside the body; do this before the lid goes on) and join them with a strap underneath. Fit the headphone jack and level pot in its front face. For the pad: glue the foam onto the hardboard, wrap the vinyl round and glue it underneath with contact adhesive, then stick it onto the core with hook-and-loop pads. It lifts off for cleaning or recovering.
4. **Electronics in the console:** screw the Pi 5 (with its cooler and the DAC HAT) to the 4 standoffs on the inside of the back wall, parts facing forward. Fit the 10 jacks, the power button and the 3 panel-mount leads in the back wall. Plug the audio leads into the DAC8x and ADC8x (section 6). Fit the WS2812 strip and LEDs behind the front face. The Arduino's USB lead and the GPIO ribbon come from the body through the opening in the console's front wall.
5. **Console and screen:** join the console halves with 2 straps inside and stand it against the body's back wall. The screen frame's HDMI and USB leads leave through the bottom of the tray and dip through the cable slot in the console's top; leave slack so they can flex from closed to leaning back.
6. **Cheeks and hinge:**
   - Cut the cheeks from `cheek_template.svg`: straight cuts only. The step up to the console is an inside corner: drill a small relief hole in the corner first, or finish the cut with a hand saw or jigsaw.
   - Drill the 8.2 mm rod hole **12 mm deep into each INNER face, not through** (use a depth stop; clamp the cheeks inner faces together to mark the same spot). Only 3.4 mm of wood is left above the hole, so use a hardwood and drill carefully.
   - Drill the 3 mm pilot holes from the inner face, 17 mm deep.
   - Finish before fitting: sand to 180 grit, wipe on the black / ebony stain (two coats if the grain looks too light), let it dry, then 2 coats of oil or hard wax. Test on an offcut first: end grain soaks up more and goes darker.
   - Epoxy the rod into one cheek so it cannot turn.
   - On the rod, for each hinge ear: sleeve, ear, washer, M8 wave (spring) washer, washer, nyloc nut. Tighten the nuts until the screen holds its angle. The 10.1 inch screen and frame weigh about 0.6 kg: the spring washers keep the grip as the printed ears bed in.
   - Push the second cheek on and screw both cheeks on from the inside: 4 screws from the body, 2 from the console and 1 from the palm rest, per side.
   - Nothing shows on the outer faces.

The screen folds shut over the keys and leans back up to 45 degrees (`chk7.py` checks the clearance at every angle in that range).

---

## 8. Software: install and run

**Testing with a USB audio device and a MIDI keyboard (no panel yet):** follow `GETTING_STARTED.md`.

**Quick start on the Pi:** flash 64-bit Raspberry Pi OS (Lite is enough) with Raspberry Pi Imager, copy this folder to the Pi, then:
```
bash setup.sh                     # installs, builds, runs the self-test, checks the hardware and measures the CPU headroom
python3 tools/midi_setup.py       # map a MIDI controller (pads, knobs, buttons) from the terminal
bash start.sh                     # starts with whatever is plugged in (USB audio, touch screen, the panel if connected)
bash setup.sh --skip-apt --service                                                  # later: start at boot
```
A USB mouse works as a finger on any HDMI monitor (left click = tap, drag = slide, wheel = jog, hold the right button = SHIFT), so the
touch screen is not needed to try it. `python3 tools/pi_check.py` repeats the hardware check and speed test on its own (power problems, audio / MIDI / touch devices,
the screen size, and how much of each audio block the engine uses). The Pi 5 has no headphone jack: until the DAC HAT is fitted,
use a USB audio interface (or HDMI audio, if the screen or monitor has speakers).

**By hand**, the same steps:
```
sudo apt install -y python3-numpy python3-sounddevice python3-serial python3-soundfile python3-pil python3-evdev \
                    python3-gpiozero python3-lgpio libportaudio2 g++ git
cd stretch && sh build.sh && cd ..          # WARP time-stretch (about 10 s; fetches pinned Signalsmith sources)
sh dsp/build.sh                             # pad filters (a second)
python3 make_demo_samples.py                # the demo kit, if samples/ is empty
python3 test_ui.py                          # the self-test
python3 sampler_os.py --device hifiberry --outs 8   # bash start.sh does this by itself when it finds the HiFiBerry
```
Find the device numbers with `python3 -m sounddevice`.

**Start at boot:** edit the user, paths and `--device` in `sampler-os.service`, then:
```
sudo cp sampler-os.service /etc/systemd/system/ && sudo systemctl enable --now sampler-os
```

**VST3 plug-ins** (optional): put Linux ARM64 VST3 builds in `~/.vst3` or `plugins/`. `fx.py` uses the `pedalboard` package if
installed, otherwise the bundled host: `cd vst3host && sh build.sh` (about a minute). Windows / macOS-only plug-ins cannot load.

**Plug-in windows** (a plug-in's own interface on the touch screen) need X11 instead of the raw framebuffer:
```
sudo apt install -y xserver-xorg xinit libx11-dev
cd vst3host && sh build.sh && cd ..
xinit /usr/bin/python3 ./sampler_os.py --x11 --device <dac> --outs 8 -- :0 -nocursor
```
(Use the same `xinit` line in the service file if you want this at boot.)

**USB drives** (nothing mounts them automatically without a desktop):
```
sudo apt install -y udisks2 exfatprogs ntfs-3g
sudo cp 50-sampler-udisks.rules /etc/polkit-1/rules.d/ && sudo usermod -aG plugdev $USER && sudo reboot
```
Without udisks the sampler falls back to `sudo -n mount`. Always eject (F1 on BROWSE's places list) before unplugging.

**Options** for `sampler_os.py`:
| Option | Does |
|---|---|
| `--device N` / `--in-device N` | audio device (or `in,out`) / a separate input device |
| `--outs 8` | output channels (8 for the DAC8x). Recording takes inputs 1 and 2 (IN L / IN R), mixed to mono |
| `--voices N`, `--block N` | polyphony (default 16), audio block size (default 256) |
| `--latency S` | audio buffering in seconds (default 0.016): raise it (0.025) if the log shows `audio dropouts`, lower it for less delay |
| `--ui-share F` | most of the time the screen may take (default 0.35); the rest is kept for the audio |
| `--x11` | draw in an X11 window (needed for plug-in windows) |
| `--fit auto\|stretch\|letterbox` | how the 16:10 UI fills the screen. `auto` (default) fills it when the screen is within 3 % of 16:10 (1280 x 800 fills exactly) and otherwise keeps the shape with black bars (a 1024 x 600 screen gets 960 x 600) |
| `--scale N` | draw the UI N times 800 x 500. Default: the screen's own size (1.6 on 1280 x 800), so text is drawn sharp at the panel's resolution |
| `--no-arduino`, `--no-midi`, `--no-gpio`, `--no-touch` | run without those parts |
| `--port`, `--port2` | Arduino serial port, an optional second controller |
| `--touch`, `--touch-swap`, `--touch-invx`, `--touch-invy` | touch device and axis fixes |
| `--jog-div N` | encoder steps per jog step (try 2 or 4) |
| `--keys`, `--png file` | keyboard test mode; write the screen to a PNG instead of the display |
| `--shots folder` | write a PNG of every screen and exit |

**Keyboard test mode** (on any computer: `python3 sampler_os.py --keys --png /tmp/screen.png`):
- **Pads:** `z x c v / a s d f / q w e r / 1 2 3 4`
- **Transport:** space PLAY, `.` STOP, `p` PLAY START, `=` REC, `,` OVERDUB
- **Screens:** `5 6 7 8 9` MAIN GRID MUTE STEP PROG; `j k l m o` SAMPLE CHOP MIXER FX SONG
- **Play keys:** `\` UNDO, `/` TAP, `;` BANK, `'` NOTE REPEAT, `-` ERASE, `0` SHIFT
- **Soft keys and navigation:** `! @ # $` F1-F4, arrows, Enter = OK, `[ ]` jog

**Prototype before the case exists:** a Pi 5, the touch screen, any audio output (the HAT or a USB interface) and a USB MIDI
controller (e.g. an Akai MPK249) are enough. Run `python3 sampler_os.py --no-arduino --device <n> --outs 2`. Then set it up:
1. Open the MIDI page (MIDI > on MAIN) and learn PADS (hit pad 1), Q1-Q4 and JOG to knobs, and F1-F4, SHIFT and UNDO to buttons.
2. The controller's transport works through MMC without learning.
3. Everything the hardware panel does is also on the touch screen.

---

## 9. Using it

**The panel**
- **Tabs:** the screen keys open the ten screens; SONG has its own key.
- **F1-F4:** run whatever the soft-key row on screen shows. How a label looks tells you what the key does:
  - a plain word is an action (SAVE, DELETE NOTE);
  - a word with a light is a switch, the light green when on (METRONOME, REVERSE);
  - a small name over a value is a setting that steps on each press (SNAP / 1/16, ZOOM / 2 BARS);
  - a word with an arrow goes to another page (CHOP >); BACK is always F4 on pages you come back from (MENU, PROJECTS, BROWSE, MIDI, PAD MODES, TRACK OUT, SONG);
  - a lit, orange key is the page's main action (DO IT, OK).
- **Pop-ups and questions** (EDIT, the machine picker, the keyboard, IMPORT, the valve case, the effect list, the plug-in window, "save changes?"): **F1 cancels or closes, F4 confirms**. OK answers with F4 too.
- **MENU** (the MENU tab at the end of the top bar; also SHIFT + MAIN, F4 on MAIN, or F5 on the MPC Studio): PROJECTS, BROWSE, EDIT, PAD MODES, MIDI, TRACK OUT, SONG and SAVE, the pages without a key of their own.
- **D-pad and OK:** the arrows move around the screen; OK does or opens the highlighted thing (it never plays a sound: the pads do that). On MAIN, OK opens the selected pad in PROG.
- **Jog:** changes the highlighted value (on lists it moves the cursor). **SHIFT + jog = fine steps**, everywhere; spin the wheel quickly for big steps.
- **Recording and chopping (the MPC way):** a recording goes into the project's samples, not onto a pad. KEEP opens it
  in CHOP; DISCARD removes it. CHOP works on its own sample: `<` `>` beside the name (or SHIFT + left / right) step through
  the project's samples, newest first. BROWSE with "to CHOP" loads a file the same way. Nothing goes on a pad until **F4
  CONVERT**: NEW PROGRAM (the slices on A01.. of an empty program, WARP at the loop's tempo), TO PADS (this program, from
  the selected pad) or NEW SAMPLES (each slice its own sample). The pads keep pointing at the original sample, so moving a
  slice's start or end later moves them too.
- **Editing slices:** pads 1-16 (or left / right) play and select slices; tap one on the waveform to do the same. Q2 START and
  Q3 END move the selected slice's edges on their own (drag the yellow S / E handles on the touch screen), so you can trim
  silence off a slice; parts no slice plays are shaded. A turn moves an edge across the visible window, so zoom in
  (up / down or Q4) for finer moves, and hold SHIFT for finer still. F2 SPLIT cuts the selected slice at the dotted cursor
  (the jog wheel moves it), F3 MERGE joins it with the next. Running a detection again (Q1, DETECT) starts the slices afresh.
- **Into the beat:** NEW PROGRAM puts the new program on the current track if it is empty, otherwise on the first empty
  track of the sequence, and selects it: press REC and play the pads. Every track plays its own program: MAIN shows it as
  a PGM chip on each track row (P01, P02 ...); tap the chip for the next program that has sounds.
- **SETTINGS** (MENU > SETTINGS, the last tile): this Pi's settings, kept in `ui.json` beside the software (not in a project):
  - AUDIO: output and input device, outputs, latency, voices; CONTROLLERS: MPC Studio and its screen, PAD VELOCITY (how hard
    you must hit: SOFTER / SOFT / LINEAR / HARD; SOFT is the default, closer to an MPC), other USB MIDI, jog steps per click,
    mouse speed; DISPLAY + TOUCH: screen fit, touch direction, screen rate; GENERAL: the machine at start, AUTOSAVE (off /
    every 5 minutes / on stop - only ever while stopped), metronome, count-in, ASR KEYS; ABOUT: version, this Pi's address,
    storage, CPU, SAVE LOG TO USB (monolith-log.txt for bug reports) and the license.
  - Audio, controller on / off and screen changes need a restart: F3 APPLY (it asks to save first). The rest act at once.
  - A flag typed on the command line still wins over a setting; once a sound card is chosen here, start.sh stops guessing one.
  - Everything Monolith prints also goes to `logs/monolith.log` (about 1 MB kept).
- **Saving:** an amber disk in the top bar means there are unsaved changes. Save with SHIFT + PLAY or MENU > SAVE. Opening or starting another project asks SAVE / DON'T SAVE / CANCEL when there are changes.
- **Q1-Q4:** change the four values shown in the strip at the bottom. A yellow arrow means a knob has not yet caught up with the value ("turn to pick up").
- **The top bar:** a transport pill (tap: play / stop) and the BPM (tap: tap tempo).
- **Hold SHIFT** a moment (without touching anything else) to see the SHIFT combinations:

| SHIFT + | Does | SHIFT + | Does |
|---|---|---|---|
| PLAY | save project | STOP | all notes off |
| REC | count-in off / 1 / 2 bars | OVERDUB | metronome |
| ERASE | solo pad | UNDO | redo |
| TAP | quantize track | F1-F4 | pad bank A-D |
| NOTE REPEAT | repeat rate | GRID | SONG screen |
| MIXER | FX screen | pads | select without playing |
| jog | fine steps | OK (on FX) | bypass the effect |
| MAIN | MENU | PROG | BROWSE files |
| MUTE | PAD MODES | jog push | Q-link mode |
| SAMPLE | TRACK OUT | LOAD | PROJECTS |

**On the MPC Studio (mk1)** the keys do what their printed names say, as far as Monolith's pages allow:

| Studio key | Monolith | Studio key | Monolith |
|---|---|---|---|
| MAIN | MAIN | F1-F4 | the soft keys |
| PROG EDIT | PROG (all settings) | F5 | MENU |
| PROG MIX | MIXER (SHIFT: FX) | F6 | BACK |
| SEQ EDIT | GRID (SHIFT: SONG) | WINDOW | OK |
| SAMPLE EDIT | CHOP (SHIFT: SAMPLE RECORD) | DATA - / + and the wheel | jog (SHIFT: fine steps) |
| PROJECT | PROJECTS | BANK A-D | pad bank |
| SEQ | GRID, all tracks | 16 LEVEL, NEXT SEQ, TRACK MUTE | pad modes (press again: normal); SHIFT + TRACK MUTE: the MUTE page |
| PROG | PROG (front panel) | FULL LEVEL | every hit at full velocity |
| SAMPLE | PROG's sample list | PAD ASSIGN | PAD MODES page |
| SONG | SONG | Q-LINK TRIGGER, SCROLL | Q-link mode |
| BROWSER | BROWSE | NUMERIC | machine picker (no number entry yet) |
| STEP SEQ | STEP | NO FILTER | BROWSE: every file / audio only |
| GO TO, BAR < >, STEP < > | move the playhead | transport, UNDO, TAP TEMPO, ERASE, NOTE REPEAT | as on the panel |

On the ASR-10's MAIN, **ASR KEYS** (on the rail, beside CHANGE MACHINE) switches to the ASR's own modes and pages: F1-F3 =
LOAD / COMMAND / EDIT, the page keys on the touch screen, the jog as its data slider, F4 = ENTER, and a question = F1 NO /
F4 YES (see EMULATION_NOTES.md, "ASR KEYS"). Switched off, the classic ASR screen is back.

Holding the Studio's SHIFT shows its own list. SHIFT + F1-F4 does not change bank on the Studio (it has BANK keys).

**Recording and sequencing**
- **Recording:** pick a track on GRID (the < > by its name), press REC (replace) or OVERDUB, play pads. Count-in, metronome and record quantize are on MAIN.
- **Transport:** STOP twice goes back to the start. UNDO toggles undo / redo.
- **Erase while playing:** hold ERASE and hit a pad to erase that pad's notes as the playhead passes.
- **Note repeat:** latches a repeating pad. Hit it again to stop; piezo pads cannot sense release.
- **GRID** opens on the current track, like an MPC's grid view: a drum grid (pads as rows) or a piano roll. Tap to add, drag to move, DELETE removes; zoom 1-8 bars, snap.
  - **The header** is the same in both views: sequence < >, track < > with its type (tap it to change what the track plays), bars - / +, LOOP, the lane chip, and ALL TRACKS.
  - **ALL TRACKS** (the chip, or press GRID again) shows every track of the sequence with mute / solo and its notes. Tap a track to select it; tap it again, press OK or F4 EDIT TRACK to edit it. GRID again goes back.
- **STEP** is a 16-step row per pad.
- **MUTE** is for playing live: 16 track tiles laid out like the pads. Tap a tile or hit pad n to mute track n (F2 SOLO MODE makes them solo instead); F1 UNMUTE ALL, F3 UNSOLO ALL. The right half picks the next sequence: tap it and it switches at the end of the one playing (straight away when stopped); F4 cancels.
- **GRID bottom lane (the LANE chip in the header):** OFF (the default: the notes get the whole height), VEL (velocity bars) or AUTO (automation).
  - **What can be automated, per track:** track level, track pan, and every parameter of the effects in the track's program inserts (a filter sweep, a delay mix, drive...). Tap the lane's label to pick one.
  - **Drawing:** drag in the lane; points snap to the grid and the sound follows straight lines between them. CLEAR empties the lane shown.
  - **Recording:** with REC or OVERDUB on and the sequence playing, turning a Q-link writes it: Track vol / Track pan (Q-link mode TRACK, or GRID's ALL TRACKS view), or an insert's parameters on the FX page with a PROGRAM INS slot chosen. Moving the knob replaces what was there; letting go hands control back to the lane.
  - **Playback:** automation is followed every 256 samples (about 6 ms), and notes that are already sounding follow level and pan changes too. It is part of the sequence's tracks, so it is saved, bounced by TRACK OUT and played in song mode. Not yet: undo for automation edits, copying it with COPY BARS, and pad-level parameters.
- **SONG:** chains sequences with repeat counts.

**Track types** (the type button next to the track name on GRID, or on each ALL TRACKS row)
- DRUM: a program's 64 pads.
- KEYGROUP: one pad played up and down the keyboard; set which key plays it at its own pitch.
- PLUGIN: a VST3 synth (Dexed and Surge XT can be built for the Pi). PLUG-IN WINDOW shows its own interface with `--x11`.
- MIDI: notes to external gear on a channel.

Note tracks switch freely between each other. A drum track with hits must be cleared before it becomes a note track.

**Projects and names** (MENU > PROJECTS)
- **NEW** starts an empty project, **SAVE AS** copies the open one (samples and all) and carries on in the copy, **OPEN** (or tap a project twice) opens one. If the open project has unsaved changes, it asks first (SAVE / DON'T SAVE / CANCEL). The last project opens at start-up.
- **Where:** the software's own folder is the DEMO project; the others are in `projects/<name>/` next to it, each with its own `samples/` and `project.json`.
- **Names:** tap the sequence or track name in GRID's header, or the program name on PROG, and type on the on-screen keyboard (D-pad and OK work too; F1 CANCEL, F4 OK). Samples: RENAME in PROG's sample list (the file is renamed at the next save).
- **DELETE UNUSED SAMPLES** (on PROJECTS, tap twice) removes samples no pad plays; their files go at the next save.

**Edit tools** (MENU > EDIT, or F1 on GRID's ALL TRACKS)
- COPY BARS (to another place, or end to end several times, replacing or adding, one track or all), INSERT BARS, DELETE BARS, TIME SIGNATURE, QUANTIZE (grid, strength, swing), NUDGE (in ticks, 96 to a beat), COPY SEQUENCE, COPY TRACK, COPY PAD, FLATTEN PAD.
- Pick one on the left, set it up with - / + (or the D-pad and jog), then DO IT (F4 or OK); F1 CLOSE goes back. UNDO takes it back.
- **One note:** in GRID, SHIFT + left / right nudges the note under the cursor by one tick.

**Programs and pads (PROG)**, laid out like an MPC 2.x program edit: GLOBAL / SAMPLES / ENVELOPES / EFFECTS (on the ASR-10 also LFO and MODULATION):
- **Waveform:** the whole sample with the pad's region lit and the sample's chop markers. Drag the green START / red END lines; ZOOM shows the region close up, SNAP puts the edges on zero crossings.
- **GLOBAL:** level, pan, gain, ONE SHOT / HOLD, choke group (pads in the same group of the same program cut each other; other programs are never cut) and output; then, under a heading naming the machine, its own sound options:
  - **SOUND:** AS MACHINE, or MODERN / MPC60 / MPC3000 / MPC2000XL / SP-1200 / ASR-10 for this program only (an ASR-10 transwave bass in an SP-1200 project). Timing and MAIN's screen stay with the machine.
  - **SP-1200:** SAMPLED AT (33 / 45 / 78 rpm), CHANNEL (which output filter: AUTO or 1-8), DECAY (its 0-31) and RING.
  - **ASR-10** (two pages, the button on the heading): RATE, FX BUS (FX1 / FX2 / DRY into an ASR effect), FILTER (its four modes), CUTOFF F1 / F2, KBD AMT F1 / F2, the filter envelope and MAKE TRANSWAVE; plus the LFO and MODULATION tabs, and ENVELOPES becomes its five-stage amp envelope (times, levels, SOFT VEL, VEL CURVE, ENV MODE, with the shape drawn).
  - **MPC60:** VEL > LEVEL, VEL > ATTACK, VEL > START (DECAY reads FADEOUT; it has no filter). **MPC3000:** DECAY MODE (END / START), VEL > LEVEL, VEL > START (soft start), VEL > CUTOFF. **MPC2000XL:** those plus VEL > ATTACK, VEL > PITCH and the filter envelope's attack.
  - **MODERN:** LO-FI (an SP flavour).
- **SAMPLES:** the sample (tap to pick), SLICE, start, end, SEMI, FINE (cents), WARP, its BPM, STRETCH, reverse and fades. Q1-Q4 are START, END, FINE (STRETCH when WARP is on) and SEMI.
  - **SLICE** (as on an MPC): a pad cut from a chopped sample plays one of its slices. Moving that pad's start or end moves the slice's marker, so the next slice (and every pad on it) follows. SLICE: PAD gives the pad its own start and end instead.
  - **STRETCH** (WARP): the length as a % of the region at its BPM; 200% = half-time.
  - **Live:** a note already sounding follows edits - start / end / reverse (trimmed past where it is, it fades out), SEMI and FINE; WARP notes cross-fade onto the new render as soon as it is ready.
- **ENVELOPES:** attack, decay (off = the sound plays out), filter (off, low-pass, high-pass, band-pass), cutoff, resonance, filter envelope (how far it opens or closes at the hit) and its decay, and velocity > cutoff (soft hits darker). On this tab Q1-Q4 are attack, decay, cutoff and resonance. FLATTEN does not bake the envelope and filter in.
- **EFFECTS:** the pad's insert effect (tap to load one on the FX page), bypass, and its first six parameters; Q1-Q4 are the first four.
- **Sample choice:** OK on SAMPLE opens the sample list, with BROWSE FILES for USB drives and RENAME.
- **Banks:** SHIFT + F1-F4 picks bank A-D (or tap A-D on screen). The next program is PRG + on PROG.

**Chop**
- **Getting a sample:** record on SAMPLE (threshold, ARM REC), or pick one.
- **Choosing the cuts:** on CHOP pick EQUAL / TRANSIENT / BEATS / MANUAL, then SPLIT, MERGE and trim each slice's start and end.
- **Sending to pads:** TO PADS puts the slices on the bank's pads. They stay linked to the markers, and the sample file is never changed.
- **Tempo:** BEATS chops carry the loop's tempo for WARP.

**WARP**
- **Turning it on:** WARP on PROG makes a pad last the same number of beats at any tempo (WARP BPM is the tempo it was played at; it's guessed from the length).
- **Tempo changes:** it follows tempo changes immediately, even during a note. A fresh stretch is made in the background and cross-faded in.
- **TUNE** on a warped pad changes pitch only.

**FLATTEN PAD** (FLATTEN on PROG, or MENU > EDIT > FLATTEN PAD)
- **What it bakes:** the pad's region, fades, reverse, normalise, tune, warp, lo-fi, gain and its own insert effect (with tail), into a new sample. Those settings then reset.
- **What it leaves alone:** program and master effects are not baked in.
- **Undo:** UNFLATTEN brings the old sample and settings back.

**Pad modes** (SHIFT + MUTE, PADS on MAIN, or MENU > PAD MODES). These work on every screen and on a MIDI controller's pads:
- **16 LEVELS:** the selected pad at 16 velocities or 16 tunings.
- **PERFORM:** scale notes or chords on the track's instrument (key, octave, 9 scales, single / triad / 7th, note length).
- **TRACK MUTE:** pads 1-16 mute tracks 1-16 on any screen (the MUTE page does this too, with the tiles on screen).
- **NEXT SEQ:** pads pick the next sequence. It switches at the end of the playing one.

**Q-link modes** (the Q pill at the bottom right, or SHIFT + jog push)
- **SCREEN:** follows the screen.
- **PROJECT:** volume, tempo, swing, filter.
- **PAD:** the selected pad's tune, level, pan, gain.
- **TRACK:** volume and pan, plus a plug-in track's first two synth parameters.

**Effects (FX)**
- **Where it goes:** pick PAD, PROGRAM 1-4 or MASTER at the top (F4 steps through them), then LOAD an effect.
- **Q1-Q4:** control its parameters, a page at a time.
- **Program inserts:** act on everything the program plays.
- **VST3 effects:** PLUG-IN WINDOW opens the plug-in's own interface (X11 mode). It zooms 50-200 % and scrolls if it is too big.

**Mixer:** PADS and TRACKS pages with level, pan, mute, solo and output (MIX or OUT 1-8). Pads sent to OUT 3-8 skip the program inserts.

**Files and USB (BROWSE: SHIFT + PROG, or MENU > BROWSE)**
- **Places:** the project's samples, USB drives and home.
- **Tap a file:** hear it. Tap it again (or F3) to load it onto the selected pad. It is copied into the project when you save. MPC .SND sounds work like WAVs.
- **USB drives:** an unmounted drive says "tap to mount". F1 ejects the drive under the cursor.

**Importing an MPC2000XL project (BROWSE)**
- **How:** copy the MPC folder (the .ALL, .APS or .PGM files and their .SND sounds, all in one folder) to a USB stick, open it in BROWSE and tap the .ALL, .APS or .PGM file (they show an orange MPC tag). The first tap says what is in the folder; tap again (or F3, IMPORT MPC) to import.
- **It replaces the current project.** The old one is saved first and moved to `backups/before-mpc-<date-time>/` in the project folder; copy its `project.json` and `samples/` back to undo. Every import makes a new backup, nothing is deleted.
- **What comes across:**
  - **Sounds:** each sound the programs use, with its start / end, level and tune. Stereo sounds become mono (the engine is mono per pad, panned by the mixer); other sample rates are converted to 44.1 kHz.
  - **Programs:** pad A01-D16 keeps what that MPC pad played: sound, tune (in 0.1 semitone steps, shown as e.g. -2.5 st), mixer level and pan, attack and decay (on the MPC's own curve), voice overlap NOTE OFF as HOLD, mute assign as choke groups, the MPC's velocity response, and a Filter insert where the MPC filter was closed down. Lo-fi is off (the MPC2000XL is 16-bit 44.1 kHz). Notes that had a sound but no pad go on spare pads.
  - **Programs used first:** the programs DRUM 1-4 play (from the .APS) become programs 1-4, then the rest.
  - **Sequences:** name, tempo, length, time signature, loop on / off, track names, track on / off (as mute), track velocity %, and every note at the same tick (both use 96 ticks per beat). Drum tracks play the program their DRUM bus used; MIDI tracks stay MIDI on their channel.
  - **SIMULT, VEL SW and DCY SW** are worked out for each recorded hit, so the beat plays the pads the MPC would have played.
  - **Song:** the first used song.
- **What does not come across** (it is listed in `mpc_import_report.txt` after each import): sample loops, tempo changes inside a sequence, time signature changes (every bar uses the first bar's), loops that start after bar 1, per-hit note variations (tune / decay / attack / filter from the slider), pitch bend / controller / mixer automation events, filter resonance, the effects board (EB16), program change and MIDI settings, songs after the first, and anything over the sampler's limits: 16 tracks per sequence, 8 programs, 16 sequences.
- **Live playing** after the import does not switch sounds by velocity (SIMULT / VEL SW only apply to the imported sequences), and a mute group cuts both ways (the MPC can make it one-way).
- **From a computer:** `python3 examples/mpc_import/import_and_bounce.py MPC_FOLDER out` (or `PROJECT.xpj out` for MPC 2.x) imports into a new project in `out/project/` and writes `out/sequences.wav`, every sequence played twice, as a listening check.

**Importing an MPC 2.x project (MPC Live / One / X / Key / MPC Software, tried with OS 2.15)**
- **How:** copy the project (`NAME.xpj` and its `NAME_[ProjectData]` folder, side by side) to a USB stick, open the folder in BROWSE and tap `NAME.xpj`, then tap again (or F3). Backups and the report work as for the MPC2000XL.
- **What comes across:**
  - **Drum programs** (the ones the sequences play first, up to 8): pads 1-64 (banks A-D) with their sample, region, tune (coarse + fine, pad + layer), level (the MPC's 0 dB is 100 %), pan, reverse, attack as a fade in, mute group as a choke group, one shot / note-on trigger as ONE SHOT / HOLD, velocity sensitivity, and a Filter insert where the filter was turned down.
  - **Chops:** a pad that plays a slice of a chopped sample becomes a pad linked to a CHOP marker region of that sample, exactly as if you had chopped it here: the slices come from the chop data MPC 2.x stores inside the WAV.
  - **WARP:** pads with warp on keep it, with the MPC's original tempo as WARP BPM, so they follow the sequence tempo the same way.
  - **Samples:** only those the imported programs use; 24-bit WAVs and other sample rates are fine; stereo becomes mono.
  - **Sequences:** name, tempo, length in bars, time signature, track names, the program each track plays, and every note (960 ticks per beat on the MPC become 96 here: timing is kept to within a tenth of a tick). Simult targets play too.
  - **Song:** MPC 2.x songs are not read yet, so the song is every sequence once, in order.
- **What does not come across** (listed in `mpc_import_report.txt`): keygroup, clip, audio, plugin and MIDI programs (and so audio tracks and synth tracks), pads in banks E-H, layers 2-4 (velocity layers), filter resonance and envelope shapes other than attack, the MPC's insert effects, automation, per-note probability and note variations, tempo changes, songs, and anything over 16 tracks / 8 programs / 16 sequences.
- **How sure:** the XML programs describe themselves, but Akai does not publish the .sxq sequence or WAV slice formats. They were worked out from one real 2.15 project: note number, velocity, tempo, bars, time signature and slices are certain; the note length field is a best guess (it only matters for HOLD pads).

**Resampling:** on SAMPLE, pick RESAMPLE instead of INPUT, arm, and play: the sampler records its own main output (after the master effect) onto the selected pad as `resample_NNN`, starting when the level passes the threshold.

**TRACK OUT** (SHIFT + SAMPLE, or MENU > TRACK OUT)
- **What it writes:** every ticked track to its own WAV (32-bit float, 44.1 kHz), plus the mix, all the same length.
- **Options:** the sequence or the whole song, with a tail of 0-10 s, to the project's `exports/` or a USB drive.
- **Stems:** taken before the master effect and limiter.
- **While it runs:** faster than real time, and the outputs are silent until it finishes.

**MIDI** (USB, class-compliant, plug in any time)
- **Pads:** the controller's pads (channel 10, notes 36-99) play the sampler's pads.
- **Keys:** other channels play the track's instrument, and record with note lengths.
- **MIDI page:**
  - learn knobs and buttons (Q1-Q4, JOG, transport, F-keys, SHIFT, ERASE, UNDO, NOTE REPEAT, TAP, BANK (bank up, for a controller button), LOAD, PAD MODE, Q-LINK MODE);
  - set the keys channel;
  - give any track a MIDI out channel;
  - CLOCK: OFF, SEND (24 clocks a beat, start / continue / stop and song position, so drum machines and DAWs follow) or FOLLOW (an outside clock sets the tempo and starts and stops it; it follows the tempo, it does not lock to the other machine's exact beat);
  - BEND: the pitch bend range (2, 7, 12 or 24 semitones).
- **Wheels:** pitch bend bends notes held on the keys (KEYGROUP tracks) and goes to a PLUGIN track's synth (if the plug-in maps it) and to the track's MIDI channel. The mod wheel (CC 1) and aftertouch open the filter of pads that have one, and go to the synth and the MIDI channel too.
- **Without learning:** MMC and MIDI Start / Stop work.
- **The MIDI setup** (learned controls, clock, bend) belongs to the machine, not a project: it is in `midi.json` next to the software.

**Rear console lights:** the VU meter shows the master output (green, yellow, red). PLAY and REC light with the transport, and POWER is on whenever the Arduino has power.

---

## 10. Identity and branding

The logo is MONOLITH set wide, its I drawn as an orange slab standing taller than the rest (`brand/make_logo.py` draws it;
`--sheet` shows the other two concepts, the slab mark with the wordmark and the slab alone). It is on the start-up screen,
on MODERN's MAIN panel and on the console badge. To change it:
1. Put a logo in `brand/logo.png` (white on transparent, or dark on white), or edit and run `python3 brand/make_logo.py`.
2. Run `python3 brand/make_brand.py && python3 make_stl.py && python3 make_artwork.py`.

That gives you:
- `logo_badge.stl`, which drops flush into the 54 x 22 mm pocket on the console front. Print it face up and change filament at 1.0 mm for two colours.
- The logo on the start-up screen.
- The badge 1:1 in `console_artwork.svg`, to print as a sticker instead.
- Traced vector copies in `brand/`.

A small symbol in `brand/key_mark.png` is engraved above SHIFT on its keycap. Small lettering under a mark is left off the badge
automatically, because it is too fine to print. Keep the logo's finest lines and gaps above about 0.5 mm at badge size.

---

## 11. Examples

- `examples/mpc_import/`: makes small MPC2000XL and MPC 2.x test projects, and imports and bounces one from a computer
  (`python3 examples/mpc_import/import_and_bounce.py MPC_FOLDER out`).
- Demo beats and a demo video are coming in a later release.

---

## 12. What was and was not tested

**Tested, in a sandbox with no hardware** (`python3 test_ui.py`: 795 checks pass):
- **PROG as an MPC program edit:** SLICE (a slice's edge moves its marker and the next slice follows; SLICE: PAD frees the pad), the first slice's start, Q-links, ZOOM, FINE in cents, STRETCH, and notes that are sounding following edits (trims, tune, WARP renders).
- **Engine and sequencer:** timing, record / overdub / undo, swing, mute / solo, ONE SHOT / HOLD, choke, song mode, 8-output routing.
- **Chop:** the source is never changed, linked pads follow their markers, and projects reload.
- **Track types:** DRUM, KEYGROUP, PLUGIN with a real VST3 synth (Dexed) and MIDI out.
- **WARP:** exact lengths, tempo changes mid-note without clicks, pitch kept.
- **FLATTEN, TRACK OUT and program inserts.**
- **Pad modes and Q-link modes.**
- **The browser:** including USB mount / eject with a pretend `lsblk` / udisks.
- **MPC2000XL import:** the parsers were checked field by field against VMPC2000XL's own reference parsers on a real MPC2000XL project (3 sequences, 6 programs, 47 sounds: every note event, track, note parameter, mixer strip and pad assignment matched). The self-test builds a small MPC project byte by byte and checks the whole import: pads, tunings, chokes, envelopes, filter, SIMULT, VEL SW, MIDI tracks, song, backups and the browser.
- **MIDI:** byte streams and a pretend MIDI device; clock out (24 a beat inside the audio blocks, start / continue / stop), following an outside clock's tempo, pitch bend, mod wheel and aftertouch.
- **Projects, naming, EDIT tools, pad envelope and filter, resampling, the MENU page and the F-key grammar:** each has its own checks (files on disk, undo, audio measured before and after).
- **The UI:** touch on every screen, all 24 hardware button numbers and the light messages, screen scaling.
- **GPIO:** pins tested with stand-in buttons.
- **ASR-10 wavesamples:** the chip model's loop modes, TRANSWAV's jump at the loop's end (phase kept, the pending-move quirk), LOOP POS / START / LOOP AND RELEASE / bidirectional, MAKE TRANSWAVE, its sweep and saving.
- **ASR-10 effects:** the effects chip's skip timing, the 68000 entry points and action-list runner, and the rate change are checked without a ROM; with the ROM (not shipped), all 50 effects load, sound from an impulse and a sine, and follow WHEEL modulation.
- **A third-party VST3 effect (NINE50):** loading, parameters, audio, saved state and its own window on a virtual X server.
- **Geometry** (`chk7.py`): halves add up to the whole; no key, pad, knob or screw overlaps; nothing is cut by the print split; the screen clears everything from closed to 45 degrees back.
- **Parts:** the printed parts fit a 220 mm bed.

**Not tested / unproven**
- **Nothing has been printed, built or wired.** MX plate cut-outs, keycap stems, engraved legends (strokes about 0.5 mm), the rear console, the hinge ears and sleeves, the palm rest, the jog wheel and the cheeks are modelled only.
- **The software has never run on a real Pi 5, DAC HAT, touch screen or Arduino.** Audio latency, polyphony limits, CPU load and Pi 5 cooling in the closed console are unknown.
- **WARP render speed on a Pi:** about 45 ms per 5 s loop on the test machine; slower on a Pi, so after a big tempo jump the brief off-pitch moment lasts longer. Stretches beyond about 0.75x-1.5x sound smeared.
- **Firmware:** the Arduino firmware was not compiled or run on hardware.
- **Plug-in windows:** touching the controls inside one is not proven (simulated clicks did not register on the virtual X server).
- **USB drives:** the real udisks / polkit setup and writing to a real stick are untested.
- **MIDI controllers:** an MPK249's factory mappings were not checked, which is why everything is learnable.
- **MIDI clock with real gear:** sending clock is timed from the audio thread, so its jitter depends on the Pi's audio buffer; FOLLOW sets the tempo but does not lock the beat to the other machine. Pitch bend / mod wheel reach a VST3 synth only if the plug-in maps them (most do).
- **Assumed sizes:** the display size and depth, the Pi + HAT stack in the 30 mm console, the jack and port cut-outs, and the pad, knob and jog sizes are all assumptions until measured (section 4).
- **Other open questions:** whether the screen cables survive repeated folding, and whether the unit tips back with the screen leaning back.
- **Smaller limitations:**
  - piezo pads cannot sense release, so note repeat latches and Perform notes have a set length;
  - 16 LEVELS in TUNE does not record each hit's pitch;
  - the transient chopper is simple, so expect to nudge markers.
- **MPC import against a real MPC:** nobody has compared an imported beat with the same beat playing on an MPC2000XL or an MPC 2.x unit. MPC 2.x import was tried on one project from OS 2.15.1; other OS versions may write things differently. The envelope and filter mappings are approximations (imported filters now use the pad's own resonant 2-pole filter, but the cutoff and resonance scales are estimates, not measured against an MPC, and MPC 2.x filter types other than the low-pass play as a low-pass), and only MPC2000XL files were tried: MPC2000 (non-XL) files were not tried, and MPC60 / 3000 files are not read.
- **ASR-10 voices against a real ASR-10:** not compared; how often its OS updates a voice's modulation (here 10 ms) was not found, so sweep and LFO speeds are estimates.
- **ASR-10 effects against a real ASR-10:** not compared with the machine or recordings of it; levels, the modulation tick rate and the converters are unconfirmed. Each effect takes about 7-15% of one core here (more on a Pi).
- **Renders:** software drawings, not photographs.
- **The demo project** mutes the break track on purpose.

---

## 13. Third-party code and licences

- **Signalsmith Stretch and Signalsmith Linear** (MIT): fetched at pinned versions by `stretch/build.sh`, not included here.
- **Steinberg VST3 SDK:** fetched by `vst3host/build.sh`, not included. Read Steinberg's licence before distributing builds.
- **NINE50** (AGPL-3.0) and **Dexed** (GPL-3.0): used for testing only, not included.
- **Fonts:** Inter (bundled in `fonts/`, SIL Open Font License, `fonts/LICENSE-Inter.txt`); DejaVu as the fallback.
- **SP-1200 file layout:** worked out here from real .sp12 projects and the SP-1200 firmware (which was disassembled for this only; none of it is included).
- **MPC 2.x file layouts:** worked out here from a real OS 2.15 project; no Akai or third-party code is used.
- **MPC2000XL file layouts:** taken from the format descriptions in izzyreal's VMPC2000XL project ([mpc2000xl_kaitai](https://github.com/izzyreal/mpc2000xl_kaitai), [mpc](https://github.com/izzyreal/mpc); the mpc code is GPL-3.0, the format descriptions state no licence). `mpc_import.py` is new code written from those descriptions; no VMPC code is included. The MPC2000XL firmware was not used.
- **Musashi 68000 core** (Karl Stenerud, MIT): included in `dsp/m68k/` with its licence, to run the ASR-10 ROM's parameter routines.
- **MAME's L4003 and L6028 descriptions** (l4003.cpp, l7a1045_l6028_dsp_a.cpp, BSD-3-Clause): the reference for `dsp/akai.c` (new code).
- **MAME's ES5506 description** (es5506.cpp, BSD-3-Clause): the reference for the chip part of `dsp/otto.c` (new code).
- **MAME's ES5510 description** (es5510.cpp, BSD-3-Clause): used as the reference for `dsp/esp.c`, which is new code (with one timing correction, see `EMULATION_NOTES.md`).
- **Ensoniq ASR-10 ROM and OS disk:** read for this only; none of it is included. The effects need your own ROM files.
- **This project's own licence:** MIT (see `LICENSE`), for the software and the hardware files.
