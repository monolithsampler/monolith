#!/bin/bash
# start.sh - starts Monolith with whatever is plugged in:
#   audio:  the HiFiBerry DAC8x (8 outputs, inputs from the ADC8x), else a Sound Blaster (e.g. PLAY! 3) or another USB audio
#           device, else the default output
#   panel:  the Arduino panel if it is connected (/dev/ttyACM*), otherwise MIDI controllers + touch screen only
#   touch:  the touch screen if there is one; with no touch screen and a keyboard on this terminal, keyboard test mode
#   mouse:  a USB mouse always works as a finger (left click = touch, wheel = jog, hold right button = SHIFT)
# Anything you add is passed on, e.g.   bash start.sh --block 512      or      AUDIO=3 OUTS=2 bash start.sh
cd "$(dirname "$0")"
ARGS=()
PICK=$(python3 -c '
try:
    import sounddevice as sd
    outs = [(i, d["name"], d["max_output_channels"]) for i, d in enumerate(sd.query_devices()) if d["max_output_channels"] > 0]
    for key in ("hifiberry", "sound blaster", "usb"):          # the HAT first, then a Sound Blaster, then any USB audio device
        hit = [(i, c) for i, n, c in outs if key in n.lower()]
        if hit:
            i, c = hit[0]; print(i, 8 if key == "hifiberry" and c >= 8 else 2); break
except Exception:
    pass
')
# a sound card chosen in SETTINGS (ui.json) wins over the guess above: then Monolith picks it itself
CHOSEN=$(python3 -c 'import json
try: print(json.load(open("ui.json")).get("audio_out", ""))
except Exception: print("")' 2>/dev/null)
if [ -n "$CHOSEN" ] && [ -z "$AUDIO" ]; then PICK=""; fi
DEV=${AUDIO:-${PICK% *}}
OUTS=${OUTS:-$([ -n "$PICK" ] && echo "${PICK#* }" || echo "")}
[ -n "$DEV" ] && ARGS+=(--device "$DEV")
[ -n "$OUTS" ] && ARGS+=(--outs "$OUTS")
ls /dev/ttyACM* >/dev/null 2>&1 || ARGS+=(--no-arduino)
TOUCH=$(python3 -c "
try:
    import evdev
    def touch(c):
        a = [x[0] if isinstance(x, tuple) else x for x in c.get(evdev.ecodes.EV_ABS, [])]
        return (0 in a or 53 in a) and evdev.ecodes.EV_REL not in c      # absolute X, and not a mouse
    print(any(touch(evdev.InputDevice(p).capabilities()) for p in evdev.list_devices()))
except Exception: print(False)")
if [ "$TOUCH" != "True" ] && [ -t 0 ]; then ARGS+=(--keys); echo "no touch screen: mouse + keyboard (5-9 = screens, z-4 = pads, space = PLAY)"; fi
echo "python3 sampler_os.py ${ARGS[*]} $*"
case "$(tty 2>/dev/null)" in
  /dev/tty[0-9]*)                                   # on the Pi's own screen: hide the text cursor and keep messages off the picture
    setterm --cursor off 2>/dev/null
    echo "messages go to /tmp/sampler.log (Ctrl+C stops Monolith)"
    python3 sampler_os.py "${ARGS[@]}" "$@" >>/tmp/sampler.log 2>&1
    stty sane 2>/dev/null; setterm --cursor on 2>/dev/null; clear; tail -n 5 /tmp/sampler.log ;;
  *) python3 sampler_os.py "${ARGS[@]}" "$@"; [ -t 0 ] && stty sane ;;      # keyboard mode leaves the terminal raw
esac
