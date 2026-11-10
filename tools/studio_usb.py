#!/usr/bin/env python3
"""studio_usb.py - talk to the MPC Studio (mk1) directly over USB, no driver needed.

The Studio speaks the standard USB-MIDI packet format, but labels its interfaces 'vendor specific', so Linux's own
MIDI driver ignores it. This opens it with libusb and reads / writes the USB-MIDI packets on its bulk endpoints
(EP 0x82 in, EP 0x01 out). It has three virtual cables (ports): we print which cable every message comes in on.

One-time setup on the Pi:   sudo apt install python3-usb
Run:                        sudo python3 studio_usb.py        (60 s; hit pads, turn knobs, press every button)
                            sudo python3 studio_usb.py 120    (listen longer)
Sends only the standard MIDI identity request (F0 7E 7F 06 01 F7) once on each cable. Saves studio_usb_report.txt."""
import sys, time
try:
    import usb.core, usb.util
except ImportError:
    sys.exit("needs pyusb:  sudo apt install python3-usb")

VID, PID, IFACE, EP_IN, EP_OUT = 0x09E8, 0x0013, 1, 0x82, 0x01
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
lines = []


def log(s=""):
    print(s, flush=True); lines.append(s)


# USB-MIDI: 4-byte event packets. byte 0 = cable (high nibble) + code index (low nibble), then 3 MIDI bytes.
CIN_LEN = {0x2: 2, 0x3: 3, 0x4: 3, 0x5: 1, 0x6: 2, 0x7: 3, 0x8: 3, 0x9: 3, 0xA: 3, 0xB: 3, 0xC: 2, 0xD: 2, 0xE: 3, 0xF: 1}
NAMES = {0x80: "note off", 0x90: "note on", 0xA0: "pad pressure", 0xB0: "CC", 0xC0: "program", 0xD0: "chan pressure", 0xE0: "pitch bend"}


def to_packets(msg, cable):
    """MIDI bytes -> USB-MIDI packets (handles SysEx)"""
    out = bytearray()
    if msg[0] == 0xF0:
        i = 0
        while i < len(msg):
            chunk = msg[i:i + 3]; i += 3
            if chunk[-1] == 0xF7 or i >= len(msg): cin = {1: 0x5, 2: 0x6, 3: 0x7}[len(chunk)]
            else: cin = 0x4
            out += bytes([(cable << 4) | cin]) + bytes(chunk) + bytes(3 - len(chunk))
    else:
        out += bytes([(cable << 4) | (msg[0] >> 4)]) + bytes(msg) + bytes(3 - len(msg))
    return bytes(out)


def hexs(b): return " ".join(f"{x:02X}" for x in b)


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None: sys.exit("MPC Studio not found (is it switched on?)")
    log(f"MPC Studio USB  {time.strftime('%Y-%m-%d %H:%M:%S')}   bus {dev.bus} addr {dev.address}")
    for i in (0, 1):
        try:
            if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
        except (usb.core.USBError, NotImplementedError): pass
    try: dev.set_configuration()
    except usb.core.USBError as e: log(f"set_configuration: {e} (carrying on)")
    usb.util.claim_interface(dev, IFACE)
    sysex = {}

    def read(timeout_ms=100):
        try: data = bytes(dev.read(EP_IN, 64, timeout=timeout_ms))
        except usb.core.USBTimeoutError: return []
        except usb.core.USBError as e:
            if "timed out" in str(e).lower(): return []
            raise
        msgs = []
        for k in range(0, len(data) - 3, 4):
            h = data[k]; cable, cin = h >> 4, h & 15
            if h == 0: continue
            body = data[k + 1:k + 1 + CIN_LEN.get(cin, 3)]
            if cin == 0x4 or (cin in (0x5, 0x6, 0x7) and cable in sysex) or (cin in (0x5, 0x6, 0x7) and body and body[0] == 0xF0):
                buf = sysex.setdefault(cable, bytearray()); buf += body
                if cin != 0x4: msgs.append((cable, bytes(buf), f"SysEx {len(buf)} bytes")); del sysex[cable]
            else:
                st = body[0] if body else 0
                txt = NAMES.get(st & 0xF0, "") + (f" ch{(st & 15) + 1} " + " ".join(str(x) for x in body[1:]) if st < 0xF0 else "")
                msgs.append((cable, body, txt))
        return msgs

    for _ in range(5): read(50)                                     # drain anything waiting
    log("\n=== identity request on each cable ===")
    for cable in range(3):
        try: dev.write(EP_OUT, to_packets(bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]), cable), timeout=500)
        except usb.core.USBError as e: log(f"cable {cable}: write failed: {e}"); continue
        t0, got = time.time(), []
        while time.time() - t0 < 1.0: got += read(100)
        log(f"cable {cable}: " + ("; ".join(f"[cable {c}] {hexs(b)}" for c, b, _ in got) if got else "(no reply)"))
    log(f"\n=== listening {SECS:.0f} s: hit EVERY pad (soft and hard), turn and touch each knob, spin the data wheel both ways,")
    log("=== press EVERY button once (F1-F6, modes, banks, transport, arrows, -, +, NUMERIC, SHIFT, ...) ===")
    t0, seen = time.time(), {}
    while time.time() - t0 < SECS:
        for cable, body, txt in read(100):
            key = (cable, bytes(body[:2]) if body[:1] != b"\xF0" else bytes(body[:6]))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] <= 3: log(f"{time.time() - t0:6.2f}  cable {cable}  {hexs(body)[:96]:30s} {txt}")
    log(f"\n{len(seen)} distinct controls/messages seen")
    usb.util.release_interface(dev, IFACE)
    open("studio_usb_report.txt", "w").write("\n".join(lines) + "\n")
    print("\nsaved studio_usb_report.txt - send it back")


if __name__ == "__main__":
    main()
