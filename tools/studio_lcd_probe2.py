#!/usr/bin/env python3
"""studio_lcd_probe2.py - round 2: how the MPC Studio (mk1)'s screen takes its pixels.

Round 1 found the address: F0 47 7F 13 04 ... on port 0 drew a few pixels (the mk2's message, read as raw dots, not a
PNG picture). This sends simple known patterns - solid blocks, stripes, moved to another place - so where and how they
land shows how the screen is laid out. Only screen messages are sent.

TAKE A PHOTO of the Studio's screen after each test (your phone is fine) and describe it: where it appeared, how wide,
how tall, solid or stripes. Send the photos with the report.

    sudo python3 tools/studio_lcd_probe2.py      (quit Monolith first; studio_usb.py and studio_lcd_probe.py beside it)
Saves studio_lcd_report2.txt."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb.core, usb.util
from studio_usb import VID, PID, IFACE, EP_IN, EP_OUT, to_packets
from studio_lcd_probe import encode7

lines = []
def log(s=""): print(s, flush=True); lines.append(s)


def msg(x, y, data, packed=True, flags=(0x00, 0x20)):
    """one screen message: the round-1 header with raw dots instead of a PNG. packed: 8-bit bytes sent with the control
    byte every 7 (as the mk2's pictures); not packed: 7-bit bytes as they are"""
    body = encode7(bytes(data)) if packed else bytes(b & 0x7F for b in data)
    n = len(data)
    size = len(body) + 8                                                 # as round 1 (which drew): the mk2's header layout
    hdr = [0x47, 0x7F, 0x13, 0x04, (size >> 7) & 0x7F, size & 0x7F]
    if (n & 0xFF) >= 128: hdr += [0x20, 0x20]; n -= 128
    else: hdr += list(flags)
    hdr += [x & 0x7F, 0x00, y & 0x7F, 0x00, n & 0xFF, (n >> 8) & 0x7F]
    return bytes([0xF0] + hdr) + body + b"\xF7"


TESTS = [
    ("clear: 1024 bytes of 00 at the top left (does the screen go blank?)", lambda: msg(0, 0, [0x00] * 1024)),
    ("solid: 64 bytes of FF at the top left", lambda: msg(0, 0, [0xFF] * 64)),
    ("solid: 256 bytes of FF at the top left (4 x more)", lambda: msg(0, 0, [0xFF] * 256)),
    ("the same 64 bytes moved down: y = 16", lambda: msg(0, 16, [0xFF] * 64)),
    ("the same 64 bytes moved right: x = 100", lambda: msg(100, 0, [0xFF] * 64)),
    ("stripes: 256 bytes of AA (10101010) at y = 32", lambda: msg(0, 32, [0xAA] * 256)),
    ("stripes: 256 bytes of F0 (11110000) at y = 48", lambda: msg(0, 48, [0xF0] * 256)),
    ("not packed: 128 bytes of 7F at y = 64", lambda: msg(0, 64, [0x7F] * 128, packed=False)),
    ("big clear: 4096 bytes of 00 from the top left", lambda: msg(0, 0, [0x00] * 4096)),
]


def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None: sys.exit("MPC Studio not found (switched on? Monolith quit?)")
    for i in (0, 1):
        try:
            if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
        except Exception: pass
    try: dev.set_configuration()
    except Exception: pass
    try: usb.util.claim_interface(dev, IFACE)
    except usb.core.USBError: sys.exit("the Studio is busy - quit Monolith first")

    def send(m): dev.write(EP_OUT, to_packets(m, 0), timeout=3000)

    def alive():
        for _ in range(5):
            try: dev.read(EP_IN, 64, timeout=50)
            except usb.core.USBError: break
        send(bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]))
        t0 = time.time()
        while time.time() - t0 < 1.5:
            try: data = bytes(dev.read(EP_IN, 64, timeout=200))
            except usb.core.USBError: continue
            if b"\x06\x02\x47" in data: return True
        return False

    log(f"MPC Studio screen probe, round 2  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("After each test: photo of the screen, then describe it (where, how wide / tall, solid or stripes). Enter = no change.\n")
    for k, (name, make) in enumerate(TESTS, 1):
        while True:
            input(f"\nTest {k}/{len(TESTS)}: {name}. Enter to send ...")
            try: send(make())
            except usb.core.USBError as ex: log(f"test {k}: send failed: {ex}"); break
            time.sleep(0.4)
            ok = alive()
            ans = input("  What changed? (describe; 'r' = send it again): ").strip()
            if ans.lower() == "r": continue
            log(f"test {k} ({name}): {ans or 'no change'}   Studio still answers: {ok}")
            break
        if not ok:
            log("  the Studio stopped answering: stopping (switch it off and on)"); break
    usb.util.release_interface(dev, IFACE)
    open("studio_lcd_report2.txt", "w").write("\n".join(lines) + "\n")
    print("\nsaved studio_lcd_report2.txt - send it back with the photos")


if __name__ == "__main__":
    main()
