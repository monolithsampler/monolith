#!/usr/bin/env python3
"""studio_lights.py - find how the MPC Studio's transport lights (REC, OVER DUB, PLAY, ...) are switched on.

Their buttons send CCs 113-119, but a CC with the same number does not light them. This tries other messages in groups
and asks you each time whether a transport light came on, narrowing it down (about 15 questions, y / n + Enter).

    sudo python3 studio_lights.py        (keep studio_usb.py in the same folder)
Saves studio_lights_report.txt: send it back."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb.core, usb.util
from studio_usb import VID, PID, IFACE, EP_OUT, to_packets

lines = []
def log(s=""): print(s, flush=True); lines.append(s)

dev = usb.core.find(idVendor=VID, idProduct=PID)
if dev is None: sys.exit("MPC Studio not found")
for i in (0, 1):
    try:
        if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
    except Exception: pass
try: dev.set_configuration()
except Exception: pass
usb.util.claim_interface(dev, IFACE)


def send(msg, cable=1):
    dev.write(EP_OUT, to_packets(bytes(msg), cable), timeout=500)


def light(kind, ch, nums, val, on=True, cable=1):
    for n in nums:
        st = (0xB0 if kind == "cc" else 0x90) | ch
        send([st, n, val if on else 0], cable)


def ask(q):
    a = input(q + " (y/n): ").strip().lower()
    return a.startswith("y")


def search(kind, ch, val, cable=1):
    """bisect the numbers 0-127 for one that lights a transport light; returns the numbers found"""
    cands = list(range(128))
    light(kind, ch, cands, val, True, cable); time.sleep(0.3)
    hit = ask(f"  {kind} ch{ch + 1} value {val} cable {cable}, ALL numbers on now: is any of REC / OVER DUB / STOP / PLAY / PLAY START lit?")
    light(kind, ch, cands, val, False, cable)
    if not hit: return []
    while len(cands) > 1:
        half = cands[:len(cands) // 2]
        light(kind, ch, half, val, True, cable); time.sleep(0.3)
        lit = ask(f"    numbers {half[0]}-{half[-1]} on: any transport light lit?")
        light(kind, ch, half, val, False, cable)
        cands = half if lit else cands[len(cands) // 2:]
    return cands


def search_excl(excl):
    cands = [n for n in range(128) if n not in excl]
    light("cc", 0, cands, 127, True); time.sleep(0.3)
    hit = ask("  ALL remaining CCs on now: is any transport light lit (other than ones already found)?")
    light("cc", 0, cands, 127, False)
    if not hit: return None
    while len(cands) > 1:
        half = cands[:len(cands) // 2]
        light("cc", 0, half, 127, True); time.sleep(0.3)
        lit = ask(f"    CCs {half[0]}-{half[-1]} on: is a transport light (not already found) lit?")
        light("cc", 0, half, 127, False)
        cands = half if lit else cands[len(cands) // 2:]
    return cands[0]


log(f"MPC Studio transport-light search 2  {time.strftime('%Y-%m-%d %H:%M:%S')}")
log("REC is CC 73. Watch only OVER DUB, STOP, PLAY and PLAY START now (and ignore REC).\n")
found = {73: "REC"}
while True:
    n = search_excl(set(found))
    if n is None: break
    light("cc", 0, [n], 127, True); time.sleep(0.2)
    name = input(f"  CC {n} is on: which transport light is it? (OD / STOP / PLAY / START): ").strip()
    light("cc", 0, [n], 127, False)
    found[n] = name; log(f"CC {n}: {name}")
    if len(found) >= 5: break
log("\nfound: " + ", ".join(f"CC {k} = {v}" for k, v in sorted(found.items())))
usb.util.release_interface(dev, IFACE)
open("studio_lights_report.txt", "w").write("\n".join(lines) + "\n")
print("\nsaved studio_lights_report.txt - send it back")
