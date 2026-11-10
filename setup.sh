#!/bin/bash
# setup.sh - sets up Monolith on a Raspberry Pi 5 (64-bit Raspberry Pi OS, Bookworm or later). Run it from the sampler folder:
#
#     bash setup.sh                                  # install, build, self-test, check the hardware (about 5 minutes)
#     bash setup.sh --service                        # ... and start Monolith at boot (start.sh finds the audio device itself)
#
# Options:
#   --service          start Monolith at boot (a systemd service for this user and this folder)
#   --audio NAME       a fixed audio device for the service: a number or part of its name (default: start.sh picks one)
#   --outs N           a fixed number of outputs for the service (default: start.sh picks 8 for the HiFiBerry DAC8x, else 2)
#   --panel            the Arduino panel is connected (leave it out while prototyping with a MIDI controller)
#   --x11              draw through X11 (needed for plug-in windows, or on a Pi with a desktop running)
#   --vst              also build the bundled VST3 host (about a minute; fetches Steinberg's SDK)
#   --skip-apt         do not install packages (already done)
# Safe to run again: each step only does what is still missing.
set -e
cd "$(dirname "$0")"
DIR=$(pwd)
ME=$(id -un)
SERVICE=0; AUDIO=""; OUTS=""; PANEL=0; X11=0; VST=0; APT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --service) SERVICE=1 ;;
    --audio) AUDIO="$2"; shift ;;
    --outs) OUTS="$2"; shift ;;
    --panel) PANEL=1 ;;
    --x11) X11=1 ;;
    --vst) VST=1 ;;
    --skip-apt) APT=0 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (try --help)"; exit 1 ;;
  esac
  shift
done
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

if [ "$(id -u)" = 0 ]; then echo "Run this as your normal user, not with sudo (it asks for sudo when it needs it)."; exit 1; fi
if [ "$(uname -m)" != "aarch64" ] && [ "$(uname -m)" != "x86_64" ]; then
  echo "This is a $(uname -m) system. Monolith needs the 64-bit Raspberry Pi OS: reflash with Raspberry Pi Imager."; exit 1
fi
grep -q "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null || echo "(not a Pi 5 - carrying on anyway)"

if [ $APT = 1 ]; then
  step "Installing packages (needs the internet; a few minutes the first time)"
  sudo apt-get update -q
  echo "Updating the system (also brings the kernel support the HiFiBerry ADC8x inputs need)"
  sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold
  sudo apt-get install -y -q libportaudio2 libsndfile1 g++ gcc git ffmpeg alsa-utils udisks2 exfatprogs ntfs-3g python3-pip
  # Python packages: from apt when this OS has them, otherwise from pip (e.g. python3-sounddevice is not packaged everywhere)
  PIP=()
  for pair in python3-numpy:numpy python3-scipy:scipy python3-sounddevice:sounddevice python3-serial:pyserial \
              python3-soundfile:soundfile python3-pil:pillow python3-evdev:evdev python3-gpiozero:gpiozero python3-lgpio:lgpio python3-usb:pyusb; do
    deb=${pair%%:*}; pipname=${pair#*:}
    if apt-cache show "$deb" >/dev/null 2>&1; then sudo apt-get install -y -q "$deb" || PIP+=("$pipname")
    else echo "$deb is not in this OS's packages: installing $pipname with pip"; PIP+=("$pipname"); fi
  done
  if [ ${#PIP[@]} -gt 0 ]; then
    pip3 install --user --break-system-packages "${PIP[@]}" || pip3 install --user "${PIP[@]}"
  fi
  if [ $X11 = 1 ] || [ $VST = 1 ]; then sudo apt-get install -y -q xserver-xorg xinit libx11-dev; fi
fi

step "Permissions"
for g in audio video input dialout gpio plugdev; do
  if getent group $g >/dev/null && ! id -nG "$ME" | grep -qw $g; then sudo usermod -aG $g "$ME"; NEWGROUPS=1; echo "added $ME to $g"; fi
done
if [ -f 50-sampler-udisks.rules ] && [ ! -f /etc/polkit-1/rules.d/50-sampler-udisks.rules ] && [ -d /etc/polkit-1/rules.d ]; then
  sudo cp 50-sampler-udisks.rules /etc/polkit-1/rules.d/ && echo "USB drives: mounting allowed"
fi
if [ ! -f /etc/udev/rules.d/99-mpc-studio.rules ]; then                     # the MPC Studio controller without root
  sudo cp tools/99-mpc-studio.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger && echo "MPC Studio: USB access allowed"
fi
echo "ok"

step "Building"
[ -f stretch/libstretch.so ] && echo "WARP time-stretch: already built" || (cd stretch && sh build.sh)
sh dsp/build.sh
if [ $VST = 1 ]; then [ -f vst3host/vst3host.so ] && echo "VST3 host: already built" || (cd vst3host && sh build.sh); fi

step "Samples"
if ls samples/*.wav >/dev/null 2>&1; then echo "samples/ has $(ls samples/*.wav | wc -l) sounds"; else python3 make_demo_samples.py; fi

step "Self-test (about a minute)"
if python3 test_ui.py > /tmp/sampler_selftest.log 2>&1; then tail -n 1 /tmp/sampler_selftest.log
else tail -n 15 /tmp/sampler_selftest.log; echo "SELF-TEST FAILED - the full log is in /tmp/sampler_selftest.log"; exit 1; fi

step "Hardware check and speed test (about a minute)"
python3 tools/pi_check.py --outs "${OUTS:-2}" || true

ARGS="--outs ${OUTS:-2}"
[ -n "$AUDIO" ] && ARGS="--device \"$AUDIO\" $ARGS"
[ $PANEL = 0 ] && ARGS="$ARGS --no-arduino"
if [ $X11 = 1 ]; then RUN="/usr/bin/xinit /usr/bin/python3 $DIR/sampler_os.py --x11 $ARGS -- :0 -nocursor"
elif [ -z "$AUDIO" ] && [ -z "$OUTS" ]; then RUN="/bin/bash $DIR/start.sh"     # finds the audio device (HiFiBerry first), panel and touch screen itself
else RUN="/usr/bin/python3 $DIR/sampler_os.py $ARGS"; fi

if [ $SERVICE = 1 ]; then
  step "Start at boot"
  sudo tee /etc/systemd/system/sampler-os.service >/dev/null <<EOF
# written by setup.sh - run it again to change this
[Unit]
Description=Monolith
After=sound.target

[Service]
User=$ME
SupplementaryGroups=video audio dialout input gpio plugdev
WorkingDirectory=$DIR
ExecStart=$RUN
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable sampler-os >/dev/null 2>&1
  echo "Monolith will start at boot:  $RUN"
  echo "Stop it: sudo systemctl stop sampler-os    Logs: journalctl -u sampler-os -f    Turn off: sudo systemctl disable sampler-os"
fi

step "Done"
[ -n "$NEWGROUPS" ] && echo "You were added to new groups: reboot (sudo reboot) before starting Monolith."
[ -f /var/run/reboot-required ] && echo "The system update needs a reboot (sudo reboot) before starting Monolith."
if [ $SERVICE = 1 ]; then echo "Reboot and it starts on its own."
else
  echo "Next:"
  echo "  1. map your MIDI controller (MPK249):   python3 tools/midi_setup.py"
  echo "  2. start Monolith:                     bash start.sh"
  echo "     (it finds a Sound Blaster / USB audio device, the touch screen and the Arduino panel by itself)"
  echo "  3. start it at boot when you are happy: bash setup.sh --skip-apt --service"
fi
