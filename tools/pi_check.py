#!/usr/bin/env python3
"""
pi_check.py - checks a Pi (or any Linux box) for Monolith, then measures how much of the CPU the engine needs.

    python3 tools/pi_check.py            # everything (about a minute)
    python3 tools/pi_check.py --quick    # skip the long stress test

What it reports:
  1. the machine: model, RAM, 64-bit OS, kernel, temperature, and whether the Pi has ever been short of power or throttled
  2. the parts it can see: audio devices, MIDI devices, touch screens, the framebuffer, serial ports (the Arduino)
  3. the build: WARP (stretch/libstretch.so), pad filters (dsp/libvoicefx.so), the VST3 host
  4. speed: how long the engine takes to make one audio block, playing the demo with every voice busy and the pad filters on,
     as a share of the time it has (under about 50 % is comfortable; over 80 % will crackle), and how long a screen frame takes.
Nothing is changed on the machine.
"""
import argparse, glob, os, platform, subprocess, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "
results = []


def say(tag, what, detail=""):
    results.append(tag)
    print(f"[{tag}] {what}" + (f": {detail}" if detail else ""))


def read(path, default=""):
    try: return open(path).read().strip().replace("\x00", "")
    except OSError: return default


def run(cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception: return ""


def machine():
    print("\n== Machine")
    model = read("/proc/device-tree/model", platform.node())
    say(OK if "Raspberry Pi 5" in model else WARN, "model", model or "unknown")
    try:
        kb = int([l for l in open("/proc/meminfo") if l.startswith("MemTotal")][0].split()[1])
        gb = kb / 1024 / 1024
        say(OK if gb >= 3.5 else WARN, "RAM", f"{gb:.1f} GB" + ("" if gb >= 3.5 else " (4 GB or more recommended)"))
    except Exception: say(WARN, "RAM", "could not read")
    arch = platform.machine()
    say(OK if arch in ("aarch64", "x86_64") else BAD, "OS", f"{arch}" + ("" if arch in ("aarch64", "x86_64") else " - install the 64-bit Raspberry Pi OS"))
    say(OK, "kernel", platform.release())
    py = sys.version.split()[0]
    say(OK if sys.version_info >= (3, 9) else BAD, "python", py)
    t = read("/sys/class/thermal/thermal_zone0/temp")
    if t:
        c = int(t) / 1000
        say(OK if c < 70 else WARN, "temperature", f"{c:.0f} C" + ("" if c < 70 else " - fit the active cooler"))
    thr = run(["vcgencmd", "get_throttled"])
    if thr:
        v = int(thr.split("=")[1], 16)
        if v == 0: say(OK, "power and throttling", "never short of power, never throttled")
        else:
            bits = {0: "UNDER-VOLTAGE NOW", 1: "speed capped now", 2: "throttled now", 3: "too hot now",
                    16: "under-voltage has happened", 17: "speed cap has happened", 18: "throttling has happened", 19: "too hot has happened"}
            say(BAD if v & 0x1 or v & 0x10000 else WARN, "power and throttling",
                ", ".join(n for b, n in bits.items() if v >> b & 1) + " - use the official 5 V 5 A supply")
    if "Raspberry Pi 5" in model:
        cur = run(["vcgencmd", "get_config", "usb_max_current_enable"])
        say(OK, "USB current", cur or "default (full current only with the official 5 A supply)")
    desk = any(os.path.exists(p) for p in glob.glob("/tmp/.X11-unix/X*")) or bool(run(["pgrep", "-x", "labwc"]) or run(["pgrep", "-x", "wayfire"]))
    if desk: say(WARN, "desktop", "a desktop is running: it owns the screen, so start Monolith with --x11, or use Raspberry Pi OS Lite")


def hifiberry():
    """the DAC8x (playback) and its ADC8x add-on (recording): the ADC8x needs a kernel from 2025 or later"""
    play, rec = run(["aplay", "-l"]).lower(), run(["arecord", "-l"]).lower()
    hat = read("/proc/device-tree/hat/product").lower()
    if "hifiberry" not in play and "dac8x" not in hat:
        if os.path.exists("/proc/device-tree/model") and "Raspberry Pi 5" in read("/proc/device-tree/model"):
            say(OK, "HiFiBerry DAC8x", "not fitted (fine with a USB audio device)")
        return
    if "hifiberry" not in play:
        say(BAD, "HiFiBerry DAC8x", "the board is fitted but has no sound card: add  dtoverlay=hifiberry-dac8x  to "
            "/boot/firmware/config.txt and reboot (see HiFiBerry's DAC8x guide)")
        return
    say(OK, "HiFiBerry DAC8x", "8 outputs found")
    if "hifiberry" in rec:
        say(OK, "HiFiBerry ADC8x", "inputs found (IN L / IN R = inputs 1 and 2)")
    else:
        say(WARN, "HiFiBerry ADC8x", "no inputs found. If the ADC8x is fitted: sudo apt update && sudo apt full-upgrade, reboot, "
            "and check it is pressed fully onto the DAC8x. Without it, recording needs a USB audio input")


def parts():
    print("\n== Parts it can see")
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        outs = [(i, d) for i, d in enumerate(devs) if d["max_output_channels"] > 0]
        ins = [(i, d) for i, d in enumerate(devs) if d["max_input_channels"] > 0]
        say(OK if outs else BAD, "audio outputs", "none" if not outs else "")
        for i, d in outs: print(f"         {i:>2}  {d['name']}  ({d['max_output_channels']} out)")
        say(OK if ins else WARN, "audio inputs", "none - recording needs an input (the USB dongle)" if not ins else "")
        for i, d in ins: print(f"         {i:>2}  {d['name']}  ({d['max_input_channels']} in)")
    except Exception as ex:
        say(BAD, "audio", f"sounddevice not working ({ex}) - run setup.sh")
    hifiberry()
    midi = sorted(glob.glob("/dev/snd/midiC*D*"))
    names = []
    for p in midi:
        card = os.path.basename(p)[5:].split("D")[0]
        names.append(read(f"/proc/asound/card{card}/id", "?") + " " + os.path.basename(p))
    say(OK if midi else WARN, "MIDI devices", ", ".join(names) if names else "none plugged in (fine)")
    touch, mice = [], []
    try:
        import evdev
        for p in evdev.list_devices():
            d = evdev.InputDevice(p)
            caps = d.capabilities()
            a = [x[0] if isinstance(x, tuple) else x for x in caps.get(evdev.ecodes.EV_ABS, [])]
            if (0 in a or 53 in a) and evdev.ecodes.EV_REL not in caps: touch.append(f"{d.name} ({p})")
            elif evdev.ecodes.EV_REL in caps and 272 in caps.get(evdev.ecodes.EV_KEY, []): mice.append(d.name)
    except ImportError:
        say(WARN, "touch screens", "python3-evdev missing - run setup.sh"); touch = None
    except Exception: touch = []
    if touch is not None: say(OK if touch else WARN, "touch screens", ", ".join(touch) if touch else "none found (plug the screen's TOUCH micro-USB into the Pi)")
    if mice: say(OK, "mouse", ", ".join(mice) + " (works as a finger: left click = touch, wheel = jog, hold right button = SHIFT)")
    fb = "/sys/class/graphics/fb0/virtual_size"
    if os.path.exists(fb):
        size = read(fb).replace(",", " x ")
        try: fw = int(size.split(" x ")[0])
        except ValueError: fw = 0
        if fw > 1920:
            say(WARN, "screen (fb0)", size + " - a 4K / big monitor makes every frame many times slower and the audio crackles. Run it at 1080p:\n"
                "         sudo sed -i '1 s/$/ video=HDMI-A-1:1920x1080@60/' /boot/firmware/cmdline.txt && sudo reboot")
        else:
            say(OK, "screen (fb0)", size + ("" if size.startswith("1280 x 800") else " (the 10.1 inch panel is 1280 x 800; other screens get black bars at the sides)"))
        if not os.access("/dev/fb0", os.W_OK): say(WARN, "screen access", "not allowed to draw on /dev/fb0: log out and in again after setup.sh (video group)")
    else:
        say(WARN, "screen (fb0)", "no framebuffer (no screen plugged in, or a headless boot)")
    ser = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    say(OK, "serial ports (Arduino)", ", ".join(ser) if ser else "none yet (fine until the panel is built)")
    groups = run(["id", "-nG"]).split()
    missing = [g for g in ("audio", "video", "input", "dialout", "gpio") if g not in groups]
    if missing: say(WARN, "groups", "not in " + ", ".join(missing) + " - setup.sh adds them; log out and in again")


def build():
    print("\n== Build")
    say(OK if os.path.exists(os.path.join(HERE, "stretch", "libstretch.so")) else WARN, "WARP time-stretch",
        "built" if os.path.exists(os.path.join(HERE, "stretch", "libstretch.so")) else "not built (cd stretch && sh build.sh)")
    try:
        import dspfast
        say(OK if dspfast.FAST else WARN, "pad filters in C", "built" if dspfast.FAST else "slow Python version (sh dsp/build.sh)")
    except Exception as ex: say(BAD, "pad filters", str(ex))
    vh = os.path.join(HERE, "vst3host", "vst3host.so")
    try:
        import pedalboard  # noqa
        say(OK, "plug-ins", "pedalboard installed")
    except Exception:
        say(OK if os.path.exists(vh) else WARN, "plug-ins", "bundled VST3 host built" if os.path.exists(vh) else "VST3 host not built (optional: cd vst3host && sh build.sh)")


def speed(quick, outs, block):
    print("\n== Speed")
    import numpy as np
    from engine import Engine, OUT_SR
    eng = Engine(HERE, nout=outs, app_dir=HERE, blank=False)
    if not eng.sources:
        say(BAD, "engine", "no samples: python3 make_demo_samples.py"); return
    budget = block / OUT_SR
    for _ in range(20): eng.render(block)                       # warm up (first-use allocations)

    def measure(secs, poke=None):
        times, n = [], int(secs * OUT_SR / block)
        for k in range(n):
            if poke: poke(k)
            t = time.perf_counter(); eng.render(block); times.append(time.perf_counter() - t)
        a = np.array(times) / budget * 100
        return a.mean(), np.percentile(a, 99), a.max()

    eng.play(from_start=True)
    m, p99, mx = measure(4 if quick else 10)
    tag = OK if p99 < 50 else WARN if p99 < 80 else BAD
    say(tag, f"demo song playing ({outs} outs, block {block})", f"average {m:.0f} %, 99 % of blocks under {p99:.0f} %, worst {mx:.0f} %")

    pads = [p for p in eng.all_pads() if not p.empty][:16] or []
    for p in pads: p.flt, p.cutoff, p.res = "LP", 0.45, 0.4  # the pad filters on: the heaviest per-voice work
    for p in pads: eng.pad_changed(p)

    def poke(k):                                                # keep every voice busy: a new hit every block
        if pads: eng.trigger(pads[k % len(pads)], 100 + k % 27)
    m, p99, mx = measure(4 if quick else 15, poke)
    tag = OK if p99 < 50 else WARN if p99 < 80 else BAD
    say(tag, f"stress: song + every voice busy + filters", f"average {m:.0f} %, 99 % under {p99:.0f} %, worst {mx:.0f} %")
    mach0 = eng.machine
    eng.machine = "SP-1200"                                    # its voices run the schematic model (dsp/sp1200.c)
    for p in pads: p.flt = "OFF"
    t_ = eng.warm_sp()                                         # (as switching machine on MAIN does)
    if t_: t_.join()
    m, p99, mx = measure(4 if quick else 10, poke)
    tag = OK if p99 < 50 else WARN if p99 < 80 else BAD
    try:
        import sp1200hw
        fast = sp1200hw.FAST
    except Exception:
        fast = False
    say(tag if fast else WARN, "stress: SP-1200 mode, all 8 channels busy" + ("" if fast else " (C library NOT built: dsp/build.sh)"),
        f"average {m:.0f} %, 99 % under {p99:.0f} %, worst {mx:.0f} %")
    eng.machine = mach0
    eng.stop()

    try:
        from ui import Controls, Renderer
        ctl = Controls(eng)
        ren = Renderer(ctl, 1.6)
        for _ in range(3): ren.frame()
        ts = []
        for mode in ("MAIN", "GRID", "PROG", "CHOP", "MIXER"):
            try: ctl.set_mode(mode)
            except Exception: continue
            for _ in range(5):
                t = time.perf_counter(); ren.frame(); ts.append(time.perf_counter() - t)
        fps = 1 / (sum(ts) / len(ts))
        say(OK if fps >= 20 else WARN, "screen frame (1280 x 800)", f"{1000 * sum(ts) / len(ts):.0f} ms, about {fps:.0f} frames a second max"
            + ("" if fps >= 20 else " - try --fps 15"))
    except Exception as ex:
        say(WARN, "screen frame", f"could not time ({ex})")
    print("         (under 50 % is comfortable; 50-80 % may crackle when the screen is busy - try --block 512; over 80 % will crackle)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--quick", action="store_true", help="short stress test")
    ap.add_argument("--outs", type=int, default=2, help="output channels to test with (8 for the DAC8x)")
    ap.add_argument("--block", type=int, default=256, help="audio block size (the default in sampler_os.py)")
    ap.add_argument("--no-speed", action="store_true", help="skip the speed test")
    a = ap.parse_args()
    machine(); parts(); build()
    if not a.no_speed: speed(a.quick, a.outs, a.block)
    bad, warn = results.count(BAD), results.count(WARN)
    print(f"\n{len(results)} checks: {bad} failed, {warn} warnings." + ("  Ready to run." if not bad else "  Fix the FAIL lines first."))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
