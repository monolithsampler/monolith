#!/usr/bin/env python3
"""studio_lcd_probe.py - try to put a picture on the MPC Studio (mk1)'s own screen.

Nobody has published how the mk1's screen is driven. The mk2's is known: the MPC software sends small PNG pictures as
SysEx, F0 47 7F 4A 04 ..., the screen cut into chunks. This sends a test picture (white, with a black frame and
MONOLITH across it) in that format a few ways - the mk2's own address, the mk1's model number (13), each on the Studio's
two USB-MIDI ports - and asks after each one whether the Studio's screen changed.

Only picture messages are sent (nothing that could start a firmware update), and after each test it checks that the
Studio still answers. Quit Monolith first (it holds the Studio):

    sudo python3 tools/studio_lcd_probe.py        (studio_usb.py sits beside it in tools/)
Saves studio_lcd_report.txt: send it back."""
import io, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb.core, usb.util
from PIL import Image, ImageDraw, ImageFont
from studio_usb import VID, PID, IFACE, EP_IN, EP_OUT, CIN_LEN, to_packets

lines = []
def log(s=""): print(s, flush=True); lines.append(s)

W, H = 160, 80                                         # the mk2's screen; the mk1's may differ - the picture is simple on purpose
CHUNKS = [(0, 0, 60, 60), (0, 60, 60, 80), (60, 0, 120, 60), (60, 60, 120, 80), (120, 0, 160, 60), (120, 60, 160, 80)]


def picture():
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, H - 1], outline=(0, 0, 0), width=3)
    d.rectangle([8, 30, W - 9, 50], fill=(0, 0, 0))
    try: f = ImageFont.truetype(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "Michroma-Regular.ttf"), 12)
    except OSError: f = ImageFont.load_default()
    d.text((W // 2, 40), "MONOLITH", font=f, fill=(255, 255, 255), anchor="mm")
    return im


def encode7(b):
    """8-bit bytes to 7-bit SysEx: a control byte (the high bits) before every 7 bytes - the mk2's scheme"""
    out = bytearray()
    for i in range(0, len(b), 7):
        g = bytearray(b[i:i + 7]); ctl = 0
        for j in range(len(g)):
            if g[j] >= 128: ctl |= 1 << j; g[j] -= 128
        out.append(ctl); out += g
    return bytes(out)


def chunk_msgs(dev_id, model):
    """the whole picture as the mk2's PNG-chunk SysEx messages, addressed to dev_id / model"""
    im = picture(); msgs = []
    for x0, y0, x1, y1 in CHUNKS:
        buf = io.BytesIO(); im.crop((x0, y0, x1, y1)).save(buf, "PNG"); png = buf.getvalue()
        enc = encode7(png)
        size = len(enc) + 8                                              # the whole message's length - 8, in 7-bit halves
        hdr = [0x47, dev_id, model, 0x04, (size >> 7) & 0x7F, size & 0x7F]
        n = len(png)
        if (n & 0xFF) >= 128: hdr += [0x20, 0x20]; n -= 128
        else: hdr += [0x00, 0x20]
        hdr += [x0, 0x00, y0, 0x00, n & 0xFF, (n >> 8) & 0x7F]          # PNG length, low byte first
        msgs.append(bytes([0xF0] + hdr) + enc + b"\xF7")
    return msgs


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

    def send(msg, cable):
        dev.write(EP_OUT, to_packets(msg, cable), timeout=2000)

    def alive():
        """the identity request still answered = the Studio is fine"""
        for _ in range(5):
            try: dev.read(EP_IN, 64, timeout=50)
            except usb.core.USBError: break
        send(bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]), 0)
        t0 = time.time()
        while time.time() - t0 < 1.5:
            try: data = bytes(dev.read(EP_IN, 64, timeout=200))
            except usb.core.USBError: continue
            if b"\x06\x02\x47" in data: return True
        return False

    log(f"MPC Studio screen probe  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log("Watch the Studio's screen. After each test, answer y (it changed), n (nothing), or describe what you see.\n")
    log(f"Studio answers before we start: {alive()}")
    tests = [("mk1 model 13, all-devices address, port 0", 0x7F, 0x13, 0),
             ("mk1 model 13, all-devices address, port 1", 0x7F, 0x13, 1),
             ("mk1 model 13, device 0 address, port 0", 0x00, 0x13, 0),
             ("mk1 model 13, device 0 address, port 1", 0x00, 0x13, 1),
             ("mk2 model 4A (as the mk2 gets it), port 0", 0x7F, 0x4A, 0),
             ("mk2 model 4A (as the mk2 gets it), port 1", 0x7F, 0x4A, 1)]
    for k, (name, dev_id, model, cable) in enumerate(tests, 1):
        input(f"\nTest {k}/{len(tests)}: {name}. Press Enter to send it ...")
        try:
            for m in chunk_msgs(dev_id, model): send(m, cable); time.sleep(0.02)
        except usb.core.USBError as ex:
            log(f"test {k} ({name}): send failed: {ex}"); continue
        time.sleep(0.5)
        ok = alive()
        ans = input("  Did the Studio's screen change? (y / n / describe): ").strip()
        log(f"test {k} ({name}): screen: {ans or 'n'}   Studio still answers: {ok}")
        if not ok:
            log("  the Studio stopped answering: stopping here (switch it off and on again)"); break
    usb.util.release_interface(dev, IFACE)
    open("studio_lcd_report.txt", "w").write("\n".join(lines) + "\n")
    print("\nsaved studio_lcd_report.txt - send it back")


if __name__ == "__main__":
    main()
