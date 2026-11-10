#!/usr/bin/env python3
"""studio_map.py (v3) - name every control on the MPC Studio (mk1), then test its button lights.

Part 1: it asks for one control at a time ("press F1"); press it and it records what that control sends.
        Can't find a control or it does nothing? Press Enter on the keyboard (over SSH) to skip it.
Part 2: it tries to light each button it learned, one by one, three different ways; watch the Studio and
        note which way (A, B or C) made the lights come on.

    sudo python3 studio_map.py            (keep studio_usb.py in the same folder)
Saves studio_map.json + studio_map_report.txt: send both back."""
import json, os, select, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb.core, usb.util
from studio_usb import VID, PID, IFACE, EP_IN, EP_OUT, CIN_LEN, to_packets, hexs

CABLE = 1
CONTROLS = (["F1", "F2", "F3", "F4", "F5", "F6",
             "PAD BANK A", "PAD BANK B", "PAD BANK C", "PAD BANK D", "PAD ASSIGN",
             "FULL LEVEL", "16 LEVEL", "STEP SEQ", "NEXT SEQ", "TRACK MUTE",
             "PROG EDIT", "PROG MIX", "SEQ EDIT", "SAMPLE EDIT", "SONG",
             "PROJECT", "SEQ", "PROG", "SAMPLE", "NO FILTER",
             "MAIN", "NUMERIC", "BROWSER", "SHIFT", "DATA -", "DATA +", "WINDOW", "TAP TEMPO", "UNDO",
             "CURSOR UP", "CURSOR DOWN", "CURSOR LEFT", "CURSOR RIGHT",
             "Q-LINK TRIGGER", "ERASE", "NOTE REPEAT",
             "STEP <", "STEP >", "GO TO", "BAR <", "BAR >",
             "REC", "OVER DUB", "STOP", "PLAY", "PLAY START"]
            + ["turn the DATA WHEEL clockwise", "turn the DATA WHEEL anticlockwise",
               "turn the SCROLL knob clockwise", "turn the SCROLL knob anticlockwise"]
            + [f"just TOUCH Q-LINK {k} (don't turn it; top knob under SCROLL = 1)" for k in (1, 2, 3, 4)]
            + [f"turn Q-LINK {k} clockwise" for k in (1, 2, 3, 4)]
            + [f"turn Q-LINK {k} anticlockwise" for k in (1, 2, 3, 4)])
TOUCH_NOTES = (84, 85, 86, 87)                    # Q-link touch sensors (learned in the first run)

lines = []
def log(s=""): print(s, flush=True); lines.append(s)


class Studio:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None: sys.exit("MPC Studio not found (is it switched on?)")
        for i in (0, 1):
            try:
                if self.dev.is_kernel_driver_active(i): self.dev.detach_kernel_driver(i)
            except (usb.core.USBError, NotImplementedError): pass
        try: self.dev.set_configuration()
        except usb.core.USBError: pass
        usb.util.claim_interface(self.dev, IFACE)
        self.sx = {}

    def read(self, ms=50):
        try: data = bytes(self.dev.read(EP_IN, 64, timeout=ms))
        except usb.core.USBError: return []
        out = []
        for k in range(0, len(data) - 3, 4):
            h = data[k]
            if not h: continue
            cable, cin = h >> 4, h & 15
            body = data[k + 1:k + 1 + CIN_LEN.get(cin, 3)]
            if cin in (0x4, 0x5, 0x6, 0x7):
                b = self.sx.setdefault(cable, bytearray()); b += body
                if cin != 0x4: out.append((cable, bytes(b))); del self.sx[cable]
            else: out.append((cable, bytes(body)))
        return out

    def send(self, msg, cable=CABLE):
        self.dev.write(EP_OUT, to_packets(bytes(msg), cable), timeout=500)


def enter_pressed():
    return bool(select.select([sys.stdin], [], [], 0)[0]) and sys.stdin.readline() is not None


def learn(st):
    found = {}
    log("PART 1: press each control when asked (Enter on the keyboard = skip)\n")
    for name in CONTROLS:
        while st.read(30): pass                                   # drain
        print(f"  -> {name} ... ", end="", flush=True)
        got, t_first = [], None
        while True:
            if enter_pressed(): break
            for cable, body in st.read(50):
                if not body or body[0] >= 0xF0 or (body[0] & 0xF0) in (0x80, 0xA0): continue       # releases, pad pressure
                if (body[0] & 0xF0) == 0x90 and body[2] == 0: continue                             # button release
                if (body[0] & 0x0F) == 9 and (body[0] & 0xF0) == 0x90: continue                    # pads (ch10)
                if name.startswith("turn") and (body[0] & 0xF0) != 0xB0: continue           # turning: only the knob's CC counts, not the touch
                if name.startswith("just TOUCH") and (body[0] & 0xF0) != 0x90: continue     # touching: only the touch note counts
                got.append((cable, body)); t_first = t_first or time.time()
            if t_first and time.time() - t_first > 0.6: break
        if not got:
            log(f"{name:45s} (skipped)"); continue
        cable, body = got[0]
        kind = {0x90: "note", 0xB0: "cc"}.get(body[0] & 0xF0, f"{body[0]:02X}")
        vals = sorted({b[2] for c, b in got if len(b) > 2})
        found[name] = {"cable": cable, "kind": kind, "ch": (body[0] & 15) + 1, "num": body[1], "values": vals}
        log(f"{name:45s} cable {cable}  {kind} {body[1]:3d} ch{(body[0] & 15) + 1}   values {vals[:8]}")
        time.sleep(0.25)
    return found


def lights(st, found):
    log("\nPART 2: lighting each button in turn, three ways. Watch the Studio.")
    buttons = [(n, v) for n, v in found.items() if not n.startswith(("turn", "just"))]
    methods = {"A": lambda n, on: st.send([0xB0, n, 0x7F if on else 0]),           # CC same number (MPC Studio mk2 style)
               "B": lambda n, on: st.send([0x90, n, 0x7F if on else 0]),           # note on, same number
               "C": lambda n, on: st.send([0xB0, n, 0x02 if on else 0])}           # CC value 2 = 'full' on later Akai units
    log("(buttons that send a CC are lit with that CC number in every method)")
    for m, fn in methods.items():
        input(f"\n  Method {m}: press Enter, then watch which buttons light ... ")
        for name, v in buttons:
            print(f"    {name}", flush=True)
            f = fn if v["kind"] == "note" else methods["A"] if m != "C" else methods["C"]
            try: f(v["num"], True); time.sleep(0.35); f(v["num"], False)
            except usb.core.USBError as e: log(f"    write failed: {e}"); break
        ans = input(f"  Method {m}: did buttons light up? (y = all, s = some, n = none; add names if some): ")
        log(f"method {m} ({'CC 127' if m == 'A' else 'note 127' if m == 'B' else 'CC 2'}): {ans}")
    input("\n  Pads: press Enter, then watch the pads ... ")
    for note in (37, 36, 42, 82, 40, 38, 46, 44, 48, 47, 45, 43, 49, 55, 51, 53):
        for msg in ([0x99, note, 0x7F], [0xB9, note, 0x7F]):
            st.send(msg); time.sleep(0.12)
        st.send([0x89, note, 0]); st.send([0xB9, note, 0])
    log("pads lit by note/CC on ch10: " + input("  did the pads light? (y / n / describe): "))


def main():
    st = Studio()
    log(f"MPC Studio control map v3  {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    found = learn(st)
    json.dump(found, open("studio_map.json", "w"), indent=1)
    try: lights(st, found)
    except (KeyboardInterrupt, EOFError): log("light test stopped")
    usb.util.release_interface(st.dev, IFACE)
    open("studio_map_report.txt", "w").write("\n".join(lines) + "\n")
    print("\nsaved studio_map.json and studio_map_report.txt - send both back")


if __name__ == "__main__":
    main()
