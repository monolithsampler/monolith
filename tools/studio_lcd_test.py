#!/usr/bin/env python3
"""studio_lcd_test.py - draw a test picture on the MPC Studio (mk1)'s own screen (Monolith not running).

The format comes from the Studio's firmware (see studio_screen.py): 360 x 96 dots, 4 grey levels, one row per message.
It draws MONOLITH in big letters, the four grey levels as bars, and a frame round the edge, then exits.

    sudo python3 tools/studio_lcd_test.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
from PIL import Image
import usb.core, usb.util
from studio_usb import VID, PID, IFACE, EP_OUT, to_packets
import studio_screen as S

a = np.zeros((S.H, S.W), np.uint8)
a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = 255
S.text(a, (S.W - S.tw("MONOLITH", 4)) // 2, 8, "MONOLITH", 4, 255)
S.text(a, (S.W - S.tw("MPC STUDIO SCREEN TEST")) // 2, 50, "MPC STUDIO SCREEN TEST", 1, 255)
for i, lv in enumerate((0, 85, 170, 255)):
    a[66:90, 30 + i * 78:30 + i * 78 + 66] = lv
    S.text(a, 30 + i * 78 + 2, 68, str(i), 1, 255 if lv < 128 else 0)
rows = S.pack(Image.fromarray(a))

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
for y, r in enumerate(rows): dev.write(EP_OUT, to_packets(S.row_msg(y, r), 0), timeout=2000)
usb.util.release_interface(dev, IFACE)
print("sent 96 rows: the Studio's screen should show MONOLITH, a test line and four grey bars (0 = off .. 3 = brightest)")
