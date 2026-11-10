#!/usr/bin/env python3
"""studio_probe.py - first contact with an Akai MPC Studio (mk1) on the Pi. Only reads, plus one standard MIDI
"identity request" per port (harmless: every MIDI device is meant to answer or ignore it). Nothing else is sent.

    python3 tools/studio_probe.py            # then hit pads, turn knobs, press buttons when it says so
    python3 tools/studio_probe.py 60         # listen for 60 s instead of 40

Writes studio_probe_report.txt next to where you run it: send that file back.
Uses only the standard library (raw ALSA MIDI files, like Monolith's midi.py)."""
import glob, os, re, select, subprocess, sys, time

VID, PID = "09e8", "0013"
LISTEN = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
OUT = os.path.abspath("studio_probe_report.txt")
log_lines = []


def log(s=""):
    print(s); log_lines.append(s)


def run(cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except Exception as e: return f"({' '.join(cmd)} failed: {e})"


def usb_section():
    log("=== USB ===")
    out = run(["lsusb"])
    hit = [l for l in out.splitlines() if f"{VID}:{PID}" in l.lower()]
    log("\n".join(hit) if hit else "MPC Studio (09e8:0013) NOT found by lsusb. Is it switched on and plugged in?")
    log(out.strip())
    v = run(["lsusb", "-v", "-d", f"{VID}:{PID}"])
    if v.strip():
        log("\n--- lsusb -v (descriptor) ---")
        log(v.strip())
        cls = re.findall(r"bInterfaceClass\s+(\d+)\s*(.*)", v)
        sub = re.findall(r"bInterfaceSubClass\s+(\d+)\s*(.*)", v)
        log("\ninterfaces: " + ", ".join(f"class {c} {n.strip()} / sub {s} {m.strip()}" for (c, n), (s, m) in zip(cls, sub)))
        if any(c == "1" and s == "3" for (c, _), (s, _) in zip(cls, sub)):
            log(">> It has a standard USB-MIDI (Audio / MIDI Streaming) interface: Linux should drive it with no extra driver.")
        elif any(c == "255" for c, _ in cls):
            log(">> Vendor-specific interface(s): Linux will need our own small USB driver (that's fine, just more work).")
    log()


def alsa_section():
    log("=== ALSA ===")
    for f in ("/proc/asound/cards",):
        try: log(open(f).read().strip())
        except OSError: pass
    log(run(["amidi", "-l"]).strip() or "(amidi -l: nothing)")
    log(run(["aconnect", "-l"]).strip())
    log()


def ports():
    out = []
    for dev in sorted(glob.glob("/dev/snd/midiC*D*")):
        m = re.match(r".*midiC(\d+)D(\d+)", dev)
        card, d = m.group(1), m.group(2)
        name = ""
        try: name = open(f"/proc/asound/card{card}/id").read().strip()
        except OSError: pass
        info = ""
        for p in glob.glob(f"/proc/asound/card{card}/midi{d}"):
            try: info = open(p).read().strip().replace("\n", " | ")
            except OSError: pass
        out.append((dev, name, info))
    return out


def hexs(b): return " ".join(f"{x:02X}" for x in b)


def identity(dev):
    try: fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e: return f"could not open: {e}"
    try:
        os.write(fd, bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]))
        got = b""; t0 = time.time()
        while time.time() - t0 < 1.5:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try: got += os.read(fd, 4096)
                except BlockingIOError: pass
        return hexs(got) if got else "(no reply)"
    finally: os.close(fd)


NAMES = {0x80: "note off", 0x90: "note on", 0xA0: "poly aftertouch", 0xB0: "CC", 0xC0: "program", 0xD0: "channel pressure", 0xE0: "pitch bend"}


def decode(buf, state):
    """split a byte stream into messages (running status, SysEx); returns (list of (bytes, text), leftover state)"""
    msgs = []
    for b in buf:
        if b == 0xF0: state["sx"] = [b]; continue
        if state.get("sx") is not None:
            state["sx"].append(b)
            if b == 0xF7: msgs.append((bytes(state["sx"]), f"SysEx ({len(state['sx'])} bytes)")); state["sx"] = None
            continue
        if b >= 0xF8: msgs.append((bytes([b]), "realtime")); continue
        if b & 0x80: state["st"], state["d"] = b, []; continue
        if state.get("st") is None: continue
        state["d"].append(b)
        st = state["st"]; need = 1 if (st & 0xF0) in (0xC0, 0xD0) else 2
        if len(state["d"]) == need:
            kind = NAMES.get(st & 0xF0, f"status {st:02X}")
            msgs.append((bytes([st] + state["d"]), f"{kind} ch{(st & 15) + 1} " + " ".join(str(x) for x in state["d"])))
            state["d"] = []
    return msgs


def listen(devs, secs):
    fds = {}
    for dev, name, _ in devs:
        try: fds[os.open(dev, os.O_RDONLY | os.O_NONBLOCK)] = (dev, name)
        except OSError as e: log(f"{dev}: could not open ({e})")
    if not fds: return
    log(f"=== listening {secs:.0f} s: hit EVERY pad (soft and hard), turn each Q-link and the SCROLL knob, touch the knobs, ===")
    log("=== spin the data wheel both ways, press EVERY button once (F1-F6, modes, transport, arrows, -, +, NUMERIC, ...) ===")
    st = {fd: {} for fd in fds}; t0 = time.time(); seen = {}
    while time.time() - t0 < secs:
        r, _, _ = select.select(list(fds), [], [], 0.2)
        for fd in r:
            try: data = os.read(fd, 4096)
            except BlockingIOError: continue
            for raw, text in decode(data, st[fd]):
                dev = fds[fd][0]
                key = (dev, raw[:2] if raw[0] != 0xF0 else raw[:6])
                seen[key] = seen.get(key, 0) + 1
                if seen[key] <= 3: log(f"{time.time() - t0:6.2f}  {os.path.basename(dev):12s} {hexs(raw)[:120]:40s} {text}")
    for fd in fds: os.close(fd)
    log(f"\n{len(seen)} distinct controls/messages seen")


def main():
    log(f"MPC Studio probe  {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    usb_section(); alsa_section()
    devs = ports()
    log("=== MIDI ports (raw ALSA) ===")
    if not devs: log("none: if lsusb found the Studio, it is not a standard USB-MIDI device (see the interfaces above).")
    for dev, name, info in devs: log(f"{dev}  card '{name}'  {info}")
    log()
    for dev, name, _ in devs:
        log(f"identity request -> {dev}: {identity(dev)}")
    log()
    studio = [p for p in devs if "studio" in (p[1] + p[2]).lower() or "mpc" in (p[1] + p[2]).lower() or "akai" in (p[1] + p[2]).lower()] or devs
    listen(studio, LISTEN)
    open(OUT, "w").write("\n".join(log_lines) + "\n")
    print(f"\nsaved {OUT} - send it back")


if __name__ == "__main__":
    main()
