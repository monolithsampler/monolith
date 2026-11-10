# Monolith - Studio edition (fork)

A fork of Monolith that uses an **Akai MPC Studio (mk1)** as the controller instead of the custom-built pad and key panel.
The standalone version (own controller, `make_stl.py`, `make_render.py`, keycaps, cheeks) is unchanged in `sampler-os-v7`.

**Status: concept.** Nothing here has been built or tested; there is no Studio driver yet. The display decision
(built-in folding screen, or no screen with HDMI out) waits until the software side is working.

## Form factor so far
- **Wedge base**, MPC-style (about 24 mm front, 68 mm rear): the Studio sits in a tray on top; the Pi 5 with the
  HiFiBerry DAC8x + ADC8x stack (about 45 mm) sits underneath in the tall rear half.
- **Padded palm rest** along the front, PHONES and LEVEL on its front face.
- **Rear panel:** 1/4" jacks, two 5-pin DIN MIDI sockets (wired to the Studio's TRS MIDI jacks), USB-C power, HDMI out.
- **Display, undecided:**
  - `option_fold_screen.png`: 12.1" 1280x800 touchscreen on one simple friction hinge at the rear corners; sits low behind the
    Studio, folds forward flat over it (covers the top two-thirds) for transport.
  - no built-in screen: the Studio's LCD as the main display, HDMI out (plus an optional USB touch monitor) for the full UI.
  - earlier ideas: `option_side_arms.png`, `option_wedge_palmrest.png`, `options_sketches.png`.

## MPC Studio (mk1) facts so far
- 284 W x 257 D x 18.5-22.6 H mm, 0.89 kg (Akai spec); knobs about 5 mm above the top.
- Rear, left to right seen from behind: power button (leave on), USB-B, MIDI IN, MIDI OUT (1/8" TRS). Bus powered.
- USB ID 09E8:0013 ("ACV1"). Windows driver by Ploytec, two MIDI ports, one hidden (probably the private port for LCD / lights).
- SysEx: Akai 47, model 13: `F0 47 00 13 <command> ...`; the firmware updater talks on the public port.
- Firmware: STM32 (Cortex-M), about 58 KB, unencrypted. Not included here.
- Blue backlit LCD (believed about 360 x 96, to confirm); six F-keys under it, like the MPC60 / 3000 / 2000XL soft keys.

## Next
1. On the Pi with the Studio plugged in: `lsusb -v -d 09e8:0013`, `amidi -l`, the identity request, `aseqdump`.
2. Studio driver: pads, Q-links, buttons, lights.
3. The Studio LCD showing the machine emulation screens, then a compact view for every page.
4. Then decide the display, and make the printable parts.
