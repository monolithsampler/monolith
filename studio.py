"""
studio.py - the Akai MPC Studio (mk1) as Monolith's controller: pads, Q-links, data wheel, cursor keys, F1-F6, mode
buttons and transport in, button and pad lights out.

The Studio (USB 09e8:0013) speaks standard USB-MIDI packets but labels its interfaces 'vendor specific', so Linux's MIDI
driver ignores it; this opens it with libusb (python3-usb) and reads / writes the packets itself. Everything is on
virtual cable 1 (cable 0 also answers SysEx, cable 2 is quiet: most likely the private port and the DIN jacks).
The map below was measured on a real unit (tools/studio_map.py); button lights = CC with the button's number, 127 on.

Needs:  sudo apt install python3-usb   and USB access (run as root, or the udev rule in tools/99-mpc-studio.rules).
Started by sampler_os.py when a Studio is plugged in (--no-studio to skip).
"""
import threading, time

VID, PID, IFACE, EP_IN, EP_OUT, CABLE = 0x09E8, 0x0013, 1, 0x82, 0x01, 1
CIN_LEN = {0x2: 2, 0x3: 3, 0x4: 3, 0x5: 1, 0x6: 2, 0x7: 3, 0x8: 3, 0x9: 3, 0xA: 3, 0xB: 3, 0xC: 2, 0xD: 2, 0xE: 3, 0xF: 1}

PAD_NOTES = (37, 36, 42, 82, 40, 38, 46, 44, 48, 47, 45, 43, 49, 55, 51, 53)      # pad 1 (bottom left) .. 16, channel 10
PAD_OF = {n: i + 1 for i, n in enumerate(PAD_NOTES)}

# buttons: (kind, number) -> name.  kind "n" = note on channel 1 (127 press, 0 release), "c" = CC (127 / 0)
BUTTONS = {("n", 12): "F1", ("n", 13): "F2", ("n", 14): "F3", ("n", 15): "F4", ("n", 33): "F5", ("n", 34): "F6",
           ("n", 35): "BANK A", ("n", 36): "BANK B", ("n", 37): "BANK C", ("n", 38): "BANK D", ("n", 112): "PAD ASSIGN",
           ("n", 39): "FULL LEVEL", ("n", 40): "16 LEVEL", ("n", 41): "STEP SEQ", ("n", 42): "NEXT SEQ", ("n", 43): "TRACK MUTE",
           ("n", 2): "PROG EDIT", ("n", 3): "PROG MIX", ("n", 5): "SEQ EDIT", ("n", 6): "SAMPLE EDIT", ("n", 8): "SONG",
           ("n", 44): "PROJECT", ("n", 45): "SEQ", ("n", 46): "PROG", ("n", 47): "SAMPLE", ("n", 48): "NO FILTER",
           ("n", 52): "MAIN", ("n", 111): "NUMERIC", ("n", 50): "BROWSER", ("n", 49): "SHIFT", ("n", 55): "DATA -", ("n", 54): "DATA +",
           ("n", 51): "WINDOW", ("n", 53): "TAP TEMPO", ("n", 67): "UNDO", ("n", 56): "UP", ("n", 57): "DOWN", ("n", 65): "LEFT",
           ("n", 66): "RIGHT", ("n", 113): "Q-LINK TRIGGER", ("n", 9): "ERASE", ("n", 11): "NOTE REPEAT",
           ("c", 115): "STEP <", ("c", 116): "STEP >", ("n", 70): "GO TO", ("n", 71): "BAR <", ("n", 72): "BAR >",
           ("c", 119): "REC", ("c", 114): "OVERDUB", ("c", 117): "STOP", ("c", 118): "PLAY", ("c", 113): "PLAY START"}
LIGHT_OF = {name: num for (kind, num), name in BUTTONS.items() if kind == "n"}   # light = CC with the button's note number
LIGHT_OF.update({"REC": 73, "OVERDUB": 80, "PLAY": 82})                          # transport lights have their own CCs (measured);
                                                                                   # STOP, PLAY START and STEP < > have no light
QLINK_TOUCH = {84: 0, 85: 1, 86: 2, 87: 3}
QLINK_CC = {16: 0, 17: 1, 18: 2, 19: 3}
CC_WHEEL, CC_SCROLL = 100, 101

# Studio button -> Monolith page, as close to the printed names as Monolith's pages allow
PAGES = {"MAIN": "MAIN", "PROG EDIT": "PROG", "PROG MIX": "MIXER", "SEQ EDIT": "GRID", "STEP SEQ": "STEP",
         "SAMPLE EDIT": "CHOP", "SONG": "SONG", "BROWSER": "BROWSE", "PROJECT": "PROJECTS", "SEQ": "SEQ", "PROG": "PROG",
         "SAMPLE": "PROG"}
SHIFT_PAGES = {"SAMPLE EDIT": "SAMPLE", "PROG MIX": "FX", "TRACK MUTE": "MUTE", "SEQ EDIT": "SONG"}   # SHIFT + key (printed above it)
HELD = {"SHIFT": "SHIFT", "ERASE": "ERASE", "NOTE REPEAT": "REPEAT"}              # Monolith keys that care about release
TAPS = {"UNDO": "UNDO", "TAP TEMPO": "TAP", "REC": "REC", "OVERDUB": "OVERDUB", "STOP": "STOP", "PLAY": "PLAY", "PLAY START": "PLAYSTART"}


def packets(msg, cable=CABLE):
    """MIDI bytes -> USB-MIDI 4-byte packets (SysEx included)"""
    msg = bytes(msg); out = bytearray()
    if msg[0] == 0xF0:
        for i in range(0, len(msg), 3):
            ch = msg[i:i + 3]
            cin = 0x4 if (i + 3 < len(msg)) else {1: 0x5, 2: 0x6, 3: 0x7}[len(ch)]
            out += bytes([(cable << 4) | cin]) + ch + bytes(3 - len(ch))
    else:
        out += bytes([(cable << 4) | (msg[0] >> 4)]) + msg + bytes(3 - len(msg))
    return bytes(out)


class Studio:
    """reader thread (controls -> Controls) + light refresher; quietly does nothing if there is no Studio or no pyusb"""
    def __init__(self, ctl):
        self.ctl, self.e = ctl, ctl.e
        self.dev, self.lock = None, threading.Lock()
        self.lit, self.scroll_prev, self.q_prev = {}, None, [None] * 4
        self.q_log = 0
        self.q_abs, self.q_rel, self.q_rep = False, False, [0] * 4
        self.pad_lit = {}
        self.full_level = False
        self._jog_acc = 0
        self._screen_blank = False
        import studio_screen
        self.screen = studio_screen.Screen()

    # ---------- USB ----------
    def open(self):
        try:
            import usb.core, usb.util
        except ImportError:
            print("MPC Studio: python3-usb not installed (sudo apt install python3-usb)"); return False
        self.usb = usb
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is None: return False
        for i in (0, 1):
            try:
                if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
            except Exception: pass
        try: dev.set_configuration()
        except Exception: pass
        try: usb.util.claim_interface(dev, IFACE)
        except Exception as ex:
            print("MPC Studio: no access (run as root, or install tools/99-mpc-studio.rules):", ex); return False
        self.dev, self.lit, self.pad_lit = dev, {}, {}
        self.screen.reset()                                                 # (re)connected: draw the whole screen again
        print("MPC Studio connected"); self.ctl.studio_seen = True
        return True

    def send(self, msg):
        if self.dev is None: return
        try:
            with self.lock: self.dev.write(EP_OUT, packets(msg), timeout=200)
        except Exception: pass

    def send_screen(self, msg):
        """the screen listens on USB-MIDI port 0 (the controls and lights are on port 1)"""
        if self.dev is None: return
        try:
            with self.lock: self.dev.write(EP_OUT, packets(msg, 0), timeout=500)
        except Exception: pass

    def screen_loop(self):
        """the Studio's own screen, about 12 times a second; only changed rows go over USB"""
        while True:
            time.sleep(0.08)
            if self.dev is None: continue
            if not self.ctl.settings.get("studio_screen", True):                 # SETTINGS: STUDIO SCREEN off - blank it once
                if not self._screen_blank:
                    try:
                        import studio_screen as _ss
                        for y in range(_ss.H): self.send_screen(_ss.row_msg(y, [0] * (_ss.W // 3)))   # (3 dots a byte)
                    except Exception: pass
                    self._screen_blank = True
                continue
            if self._screen_blank: self.screen.reset(); self._screen_blank = False
            try: self.screen.update(self.ctl, self.send_screen)
            except Exception as ex:
                print("MPC Studio screen:", ex); time.sleep(2)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        threading.Thread(target=self.lights_loop, daemon=True).start()
        threading.Thread(target=self.screen_loop, daemon=True).start()
        return self

    def run(self):
        while True:
            if self.dev is None:
                if not self.open(): time.sleep(2.0); continue
            try: data = bytes(self.dev.read(EP_IN, 64, timeout=100))
            except Exception as ex:
                if "timed out" in str(ex).lower() or "timeout" in type(ex).__name__.lower(): continue
                print("MPC Studio disconnected:", ex); self.dev = None; self.ctl.studio_seen = False; continue
            for k in range(0, len(data) - 3, 4):
                h = data[k]
                if not h or h >> 4 != CABLE: continue
                body = data[k + 1:k + 1 + CIN_LEN.get(h & 15, 3)]
                try: self.handle(body)
                except Exception as ex: print("MPC Studio:", ex)

    # ---------- controls in ----------
    def handle(self, m):
        c, e = self.ctl, self.e
        st = m[0]; kind, ch = st & 0xF0, (st & 15) + 1
        c.midi_seen = time.time()
        if ch == 10:                                                         # pads
            pad = PAD_OF.get(m[1])
            if pad is None: return
            if kind == 0x90 and m[2] > 0:
                vel = 127 if self.full_level else c.vel_in(m[2])             # FULL LEVEL: every hit at full velocity; else PAD VELOCITY
                c.pad_hit(pad, vel); self.flash(pad, vel)
            elif kind == 0xA0: e.mod_wheel(m[2] / 127.0, 128)                  # pressure -> like aftertouch (filter sweep)
            elif kind == 0x80 or (kind == 0x90 and m[2] == 0):
                if hasattr(c, "pad_release"): c.pad_release(pad)
            return
        if kind == 0xB0 and m[1] in QLINK_CC:                                # Q-links: endless, used as relative
            i = QLINK_CC[m[1]]
            v = m[2]
            if self.q_log < 40:                                           # the first raw values go in the log (for checking)
                self.q_log += 1; print(f"studio q-link {i + 1}: {v}")
            steps = self.q_steps(i, v)
            if steps:
                fine = bool(getattr(c, "shift", False))                    # SHIFT = fine, as everywhere
                if fine: c.shift_used = True
                c.nudge(i, steps / 127.0 * (0.15 if fine else 1.0))
            return
        if kind == 0xB0 and m[1] == CC_WHEEL:
            self._jog_acc += 1 if m[2] < 64 else -1                         # SETTINGS: JOG STEPS / CLICK
            dv = max(1, int(c.settings.get("jog_div", 1)))
            if abs(self._jog_acc) >= dv:
                c.jog(1 if self._jog_acc > 0 else -1, fast=True); self._jog_acc = 0
            return
        if kind == 0xB0 and m[1] == CC_SCROLL:                               # SCROLL: Q-link page
            prev = self.scroll_prev; self.scroll_prev = m[2]
            if prev is not None and m[2] != prev: c.cycle_qlink(1 if m[2] > prev else -1)
            return
        if kind == 0x90 and m[1] in QLINK_TOUCH: return                      # touch: (later: show which Q-link)
        if kind == 0x80 or kind == 0x90: name, down = BUTTONS.get(("n", m[1])), kind == 0x90 and m[2] > 0
        elif kind == 0xB0: name, down = BUTTONS.get(("c", m[1])), m[2] >= 64
        else: return
        if name: self.button(name, down)

    def q_steps(self, i, v):
        """how far a Q-link moved. The Studio sends the knob's position (0-127): the change from the last position is the
        move, so a parameter follows the knob gradually from wherever it is (no jump to the knob's position). Turning on
        at either end (127 again, or 0 again) keeps going one step at a time, so a value is never stuck short of its range.
        If a knob turns out to send steps instead (the same small value over and over, 1-7 up / 121-127 down, never a
        mid-range number), it is read as steps."""
        prev = self.q_prev[i]; self.q_prev[i] = v
        if 12 <= v <= 116: self.q_abs = True
        if not self.q_abs:
            self.q_rep[i] = self.q_rep[i] + 1 if v == prev else 0
            if self.q_rep[i] >= 3 and (v <= 7 or v >= 121): self.q_rel = True
            if self.q_rel: return v if v < 64 else v - 128
        if prev is None: return 0
        if v == prev:
            return 1 if v == 127 else (-1 if v == 0 else 0)
        return v - prev

    def button(self, name, down):
        c, e = self.ctl, self.e
        from uicore import BTN
        if name in HELD:
            c.button(BTN[HELD[name]], down)
            if name == "SHIFT": c.shift_studio = down                      # (the legend shows the Studio's keys; F1-F4 stay soft keys)
            return
        if not down: return
        if c.shift: c.shift_used = True
        if name in TAPS: c.button_name(TAPS[name]); return
        if c.shift and name in SHIFT_PAGES: c.set_mode(SHIFT_PAGES[name]); return
        if name in PAGES:
            c.set_mode(PAGES[name])
            if name in ("PROG", "PROG EDIT"): c.prog_front, c.picking = False, False   # the program's pages (one layout)
            if name == "SAMPLE": c.prog_front = False; c.picking, c.pick_cur = True, (e.pad.src.id if e.pad.src else 0)   # the sample list
            return
        if name.startswith("F") and name[1:].isdigit():
            i = int(name[1:]) - 1
            if c.mode == "MAIN" and e.machine != "MODERN":                   # the machine's own soft keys
                import machines
                scr = machines.screen(e, e.machine, c.lcd_cur)
                if scr is not None and any(f[0] == "soft%d" % i for f in scr.fields): c.lcd_tap("soft%d" % i); return
            if i < 4: c.soft(i)
            elif i == 4: c.set_mode("MENU")                                 # F5: MENU (projects, MIDI, track out...)
            else: c.go_back()                                               # F6: BACK
            return
        if name.startswith("BANK "):
            b = "ABCD".index(name[-1]); e.bank = b; c.say(f"bank {name[-1]}"); return
        if name in ("UP", "DOWN", "LEFT", "RIGHT"): c.nav(name.lower()); return
        if name == "DATA +": c.jog(1); return
        if name == "DATA -": c.jog(-1); return
        if name == "TRACK MUTE": c.set_pad_mode("NORMAL" if e.pad_mode == "TRACK MUTE" else "TRACK MUTE"); return   # a pad mode, like 16 LEVEL
        if name == "NO FILTER":                                             # the browser's file filter
            if c.mode == "BROWSE":
                c.br_filter = "AUDIO" if c.br_filter == "ALL" else "ALL"; c.br_refresh()
                c.say("showing every file" if c.br_filter == "ALL" else "showing audio files only")
            return
        if name == "WINDOW": c.ok(); return
        if name == "16 LEVEL": c.set_pad_mode("NORMAL" if e.pad_mode == "16 LEVELS" else "16 LEVELS"); return
        if name == "NEXT SEQ": c.set_pad_mode("NORMAL" if e.pad_mode == "NEXT SEQ" else "NEXT SEQ"); return
        if name == "PAD ASSIGN": c.set_mode("PADS"); return
        if name == "Q-LINK TRIGGER": c.cycle_qlink(); return
        if name == "FULL LEVEL": self.full_level = not self.full_level; c.say("FULL LEVEL " + ("on" if self.full_level else "off")); return
        if name in ("BAR <", "BAR >"):
            sq = e.seq; bar = int(max(0, e.pos) // sq.bar_ticks) + (1 if name == "BAR >" else -1)
            e.locate(max(0, min(sq.bars - 1, bar)) * sq.bar_ticks); return
        if name in ("STEP <", "STEP >"):
            step = e.seq.bar_ticks // 16
            e.locate(max(0, (int(max(0, e.pos)) // step + (1 if name == "STEP >" else -1)) * step)); return
        if name == "GO TO": e.locate(0); return
        if name == "NUMERIC":                                               # (no number entry yet) NUMERIC: the machine picker
            if c.mpick is None: c.open_picker()
            else: c.close_picker()
            return

    # ---------- lights out ----------
    def flash(self, pad, vel):
        self.send([0x99, PAD_NOTES[pad - 1], max(1, vel)]); self.pad_lit[pad] = time.time()

    def wanted(self):
        c, e = self.ctl, self.e
        page_of = {v: k for k, v in PAGES.items()}
        on = {page_of.get(c.mode)}
        if c.mode == "SEQ": on.add("SEQ EDIT")
        if e.playing: on.add("PLAY")
        if e.playing and getattr(e, "rec", None) == "rec": on.add("REC")
        if e.playing and getattr(e, "rec", None) == "over": on.add("OVERDUB")
        if c.shift: on.add("SHIFT")
        if getattr(c, "erase_down", False): on.add("ERASE")
        if getattr(e, "rep_on", False): on.add("NOTE REPEAT")
        if e.pad_mode == "16 LEVELS": on.add("16 LEVEL")
        if e.pad_mode == "NEXT SEQ": on.add("NEXT SEQ")
        if e.pad_mode == "TRACK MUTE" or c.mode == "MUTE": on.add("TRACK MUTE")
        if self.full_level: on.add("FULL LEVEL")
        on.add("BANK " + "ABCD"[e.bank % 4])
        return on

    def lights_loop(self):
        while True:
            time.sleep(0.05)
            if self.dev is None: continue
            try: on = self.wanted()
            except Exception: continue
            for name, num in LIGHT_OF.items():
                v = 127 if name in on else 0
                if self.lit.get(name) != v: self.send([0xB0, num, v]); self.lit[name] = v
            now = time.time()
            for pad, t in list(self.pad_lit.items()):                        # pads: short flash after a hit
                if now - t > 0.12: self.send([0x89, PAD_NOTES[pad - 1], 0]); del self.pad_lit[pad]


def start(ctl):
    return Studio(ctl).start()
