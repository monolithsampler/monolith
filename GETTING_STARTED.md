# Monolith: first test on the Pi 5

This guide takes a bare Raspberry Pi 5 to Monolith playing the demo kit from your MPK249, in about 45 minutes. Nothing in it has been run on a real Pi yet, so if a step fails, copy the last 15 lines it printed and send them to Claude.

## What you need

| Item | Notes |
| --- | --- |
| Raspberry Pi 5 (4 or 8 GB) | With the active cooler fitted if you have it |
| Official 5 V 5 A USB-C power supply (27 W) | A weaker supply limits the USB ports and can cause dropouts |
| microSD card, 32 GB or more | Plus a card reader for the Mac |
| Micro-HDMI to HDMI cable or adapter | The Pi 5 only has micro-HDMI ports |
| HDMI monitor | Any size; the UI keeps its 16:10 shape, so a 1920 x 1080 monitor shows thin black bars at the sides |
| USB mouse and USB keyboard | The mouse stands in for the touch screen |
| Sound Blaster PLAY! 3 | Headphones or powered speakers plugged into it; the Pi 5 has no headphone jack |
| Akai MPK249 and its USB cable | Pads, knobs and transport for the sampler |
| Your Mac | To flash the card and copy the files |
| `sampler-os-v7.zip` | The latest one Claude sent you (the whole project in one file, for copying to the Pi) |

## Step 1: Flash the SD card (on the Mac, 10 minutes)

Use Raspberry Pi OS Lite (64-bit): it has no desktop, so Monolith gets the whole screen.

1. Download and open **Raspberry Pi Imager** from raspberrypi.com/software.
2. Device: **Raspberry Pi 5**.
3. Operating system: **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (64-bit)**.
4. Storage: your microSD card.
5. When it offers OS customisation (older versions: **Edit Settings**), set:
    1. Hostname: `sampler`, so the Pi is reachable as `sampler.local`.
    2. Username and password: write them down. This guide uses `pi`; swap in yours wherever you see it.
    3. Wi-Fi name and password, and your country (AU).
    4. Time zone Australia/Brisbane, keyboard layout us.
    5. Services: turn on **SSH** with password login.
6. Write the card, wait for it to verify, then eject it.

## Step 2: Plug in and boot (5 minutes)

Connect everything before power, and plug the power supply in last.

1. microSD card into the slot under the Pi.
2. Monitor into **HDMI 0**, the micro-HDMI port next to the USB-C power socket.
3. Sound Blaster and MPK249 into the two **blue** USB 3 ports; keyboard and mouse into the black USB 2 ports.
4. Headphones or speakers into the Sound Blaster, volume low to start.
5. Power supply into the USB-C socket. The first boot takes a minute or two and may restart once.
6. At `sampler login:` type your username, then your password (nothing shows while you type it).

You now have a `pi@sampler:~ $` prompt. To type commands from the Mac instead, open Terminal there and run `ssh pi@sampler.local`.

## Step 3: Copy Monolith to the Pi (2 minutes)

The easiest way is over Wi-Fi from the Mac. In Terminal on the **Mac** (assuming the zip is in Downloads):

```
scp ~/Downloads/sampler-os-v7.zip pi@sampler.local:
```

Type `yes` if it asks about the fingerprint, then your Pi password.

No Wi-Fi? Copy the zip onto a USB stick, plug it into the Pi, and on the **Pi** run:

```
sudo mount /dev/sda1 /mnt
cp /mnt/sampler-os-v7.zip ~
sudo umount /mnt
```

Then, on the **Pi**, unpack it and go into the folder:

```
python3 -m zipfile -e sampler-os-v7.zip .
cd sampler-os-v7
```

## Step 4: Run the setup (about 10 minutes)

One command installs and checks everything. It needs the internet, and it's safe to run again if anything stops it.

```
bash setup.sh
```

What it does, in order:

1. Installs the packages Monolith needs (the slowest part; it asks for your password once).
2. Gives your user access to audio, the screen, MIDI and USB drives.
3. Builds the WARP time-stretch and the pad filters for the Pi.
4. Runs the self-test: all 661 checks should pass.
5. Runs the hardware check and speed test. It lists your audio devices (look for the Sound Blaster), MIDI devices (the MPK249), the mouse and the screen size.

If it ends with **"You were added to new groups"**, reboot, then log back in and go to the folder again:

```
sudo reboot
cd sampler-os-v7
```

A **FAIL** line in the hardware check means something to fix before starting. **warn** lines are usually fine for this test, such as "no touch screen" or "no serial ports".

## Step 5: Map the MPK249 (2 minutes)

This tells Monolith which MPK249 controls do what. Make sure the MPK249 is plugged in and powered, then run:

```
python3 tools/midi_setup.py
```

Set the MPK249 to a **Generic** preset first (preset 25 on yours), not a DAW preset like MPC Essentials. The tool first asks you to hit the 16 pads one at a time, from the bottom-left pad across and up, so any pad layout works. Then it asks for each knob and button. Move the one you want, or press Enter to skip. A layout that works well:

| Sampler control | MPK249 control |
| --- | --- |
| Pads 1-16 | All 16 pads in order, bottom-left first, bank A |
| Q1-Q4 | Knobs K1-K4 |
| Jog wheel | Knob K5 |
| F1-F4 | Switches S1-S4 |
| SHIFT, UNDO, NOTE REPEAT, TAP, BANK | Switches S5-S8, then any spare button |

You don't need to map these:

- **PLAY, STOP and REC** already work, because the MPK249's transport buttons send standard transport messages.
- **The keys** play the selected pad up and down the keyboard.
- **The mouse wheel** is a better jog wheel than a knob, because a knob stops at its ends.

If a control doesn't respond, run `python3 tools/midi_setup.py --monitor` and move it. Each line it prints is a message from the controller; Ctrl+C stops it.

## Step 6: Start Monolith

Run this on the Pi's own keyboard, so the keyboard shortcuts below work:

```
bash start.sh
```

It finds the Sound Blaster and the mouse by itself, and later the touch screen and the Arduino panel too. The logo shows, then the MAIN screen. While it runs, its messages go to `/tmp/sampler.log` instead of over the picture. **Ctrl+C** stops it and saves the project.

**Mouse**

- **Left click:** tap.
- **Click and drag:** slide faders, knobs and notes.
- **Wheel:** jog wheel.
- **Hold the right button:** SHIFT.
- The pointer hides when you leave the mouse alone.

**Keyboard**

| Keys | Do |
| --- | --- |
| `5` `6` `7` `8` `9` | MAIN, GRID, MUTE, STEP, PROG screens |
| `j` `k` `l` `m` `o` | SAMPLE, CHOP, MIXER, FX, SONG screens |
| `!` `@` `#` `$` (Shift + 1-4) | F1-F4 soft keys |
| Arrows, Enter, `[` `]` | D-pad, OK, jog |
| `z x c v` / `a s d f` / `q w e r` / `1 2 3 4` | Pads 1-16, bottom row first |
| Space, `.`, `p` | PLAY, STOP, PLAY START |
| `=`, `,` | REC, OVERDUB |
| `\`, `0` | UNDO, SHIFT on/off |

Useful extras for `start.sh`:

- `--block 512` if you hear crackles.
- `--fps 25` for a smoother pointer, if the speed test shows room.
- `--mouse-speed 0.6` or `1.5` if the pointer moves too fast or too slow.

## Step 7: First things to try

Work down this list, and note anything that sounds wrong, feels slow or is awkward to reach.

- [ ] **Pads:** hit the MPK249 pads soft and hard. Does the demo kit play, and does the volume follow how hard you hit? Do the MPK's pad banks B-D reach the sampler's banks B-D?
- [ ] **Playback:** press PLAY on the MPK249. The demo sequence should play cleanly; STOP stops it.
- [ ] **Busy screens:** while it plays, flick through GRID, PROG, MIXER and FX. Any crackles or dropouts?
- [ ] **Recording:** press REC, then PLAY, and play pads over the loop. Then try OVERDUB and UNDO.
- [ ] **GRID:** click to add notes, drag to move them, and scroll with the wheel.
- [ ] **Knobs:** on PROG, turn K1-K4 to change the selected pad's sound (tune, filter and so on).
- [ ] **Keys:** play the MPK249 keyboard; the selected pad plays chromatically.
- [ ] **Sampling:** on SAMPLE, record from a mic plugged into the Sound Blaster. Its input is mic level, so turn line sources (phone, mixer) right down.
- [ ] **Make a beat:** spend 10 minutes making something from scratch. This is the real test: what slowed you down?

## Troubleshooting

| Problem | Try |
| --- | --- |
| `sampler.local` not found from the Mac | Wait two minutes after boot. Otherwise run `hostname -I` on the Pi and use that address instead, e.g. `ssh pi@192.168.1.20` |
| setup.sh stops during "Installing packages" | Check the Pi is online (`ping -c 3 google.com`), then run `bash setup.sh` again |
| Self-test failed | Send Claude the last 15 lines it printed; the full log is in `/tmp/sampler_selftest.log` |
| "Permission denied" on `/dev/fb0` or the screen stays as text | Reboot once after setup (the new groups only apply after logging in again) |
| No sound | Check the Sound Blaster is listed by `aplay -l`. Test it with `speaker-test -D plughw:CARD=S3 -c 2 -t wav`, or name it explicitly with `AUDIO="Sound Blaster" bash start.sh` |
| Crackles, and the hardware check says the screen is 3840 x 2160 (a 4K monitor) | Run the monitor at 1080p: `sudo sed -i '1 s/$/ video=HDMI-A-1:1920x1080@60/' /boot/firmware/cmdline.txt`, then `sudo reboot` |
| Crackles or dropouts | `bash start.sh --block 512`; check the speed test with `python3 tools/pi_check.py` |
| Pads or knobs do nothing | `python3 tools/midi_setup.py --monitor` while you move them; if nothing prints, unplug and replug the MPK249 |
| Under-voltage warning in the hardware check | Use the official 5 V 5 A supply |
| Screen frozen or Monolith crashed | Press Ctrl+C, then look at `tail -n 30 /tmp/sampler.log` and send it to Claude |
| Keyboard typing doesn't show after quitting | Type `reset` and press Enter |

The Sound Blaster's card name in the `speaker-test` line is a guess: use the name `aplay -l` shows after `card N:`.

## After the test

Send Claude these results; they decide what to fix before you build the case:

1. The **Speed** lines from `python3 tools/pi_check.py`, the most important result.
2. Whether you heard crackles, and on which screen or doing what.
3. Your notes from Step 7, especially anything awkward while making a beat.
4. Any errors: the last 30 lines of `/tmp/sampler.log`.

**Start at boot (optional):** once it works, this makes Monolith start by itself every time the Pi powers on:

```
bash setup.sh --skip-apt --service
```

- **Stop it** for a session: `sudo systemctl stop sampler-os`.
- **Turn it off for good:** `sudo systemctl disable sampler-os`.
- **Logs:** `journalctl -u sampler-os -f`.

The keyboard shortcuts only work when you start it by hand. When it starts at boot, use the mouse and the MPK249.
