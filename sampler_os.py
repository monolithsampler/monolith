#!/usr/bin/env python3
"""
Monolith - boots straight into the instrument. Run:
    python3 sampler_os.py --device 1               (real hardware: Arduino pads + LCD on /dev/fb0)
    python3 sampler_os.py --keys --png screen.png  (test on any computer: keyboard + screenshot file)
    python3 sampler_os.py --shots shots/           (write a PNG of every screen and exit)

Keyboard test mode:
    pads 1-16  z x c v / a s d f / q w e r / 1 2 3 4
    transport  space PLAY   . STOP   p PLAY START   = REC   , OVERDUB      0 SHIFT (toggle)
    screens    5 MAIN  6 SEQ  7 GRID  8 STEP  9 PROG  j SAMPLE  k CHOP  l MIXER  m FX  o SONG
    edit keys  - ERASE   \\ UNDO   / TAP   ; BANK   ' REPEAT      ! @ # $  = F1 F2 F3 F4
    Q-links    t/y  g/h  b/n  u/i  = knob 1-4 down/up
    D-pad      arrow keys     OK / jog press  Enter     jog wheel  [ and ]
Real hardware: touchscreen (evdev) and the D-pad / OK / jog encoder on the Pi's GPIO start automatically,
use --no-touch / --no-gpio to switch them off.
"""
import argparse, glob, json, os, shutil, sys, threading, time
import numpy as np
from PIL import Image
from engine import Engine, OUT_SR
from ui import Controls, Renderer, W, H
from uicore import TOP_H, SOFT_Y, Q_Y
SCROLL_T = 16                                                    # scroll bar thickness (UI px)
ZOOMS = [0.5, 0.6, 0.75, 0.85, 1.0, 1.25, 1.5, 2.0]               # plug-in window zoom steps
import inputs

HERE = os.path.dirname(os.path.abspath(__file__))


def fit_box(sw, sh, fit="auto"):
    """Where the 800x480 UI goes on a sw x sh screen: (x, y, w, h). 'stretch' fills the screen, 'letterbox' keeps the 5:3 shape,
    'auto' stretches when the screen is within 3 % of 5:3 (1024x600) and letterboxes otherwise (1280x800 -> 1280x768, 16 px bars)."""
    if fit == "auto":
        fit = "stretch" if abs((sw / float(sh)) / (W / float(H)) - 1) <= 0.03 else "letterbox"
    if fit == "stretch":
        return 0, 0, sw, sh
    k = min(sw / float(W), sh / float(H))
    w, h = int(W * k), int(H * k)
    return (sw - w) // 2, (sh - h) // 2, w, h


class Framebuffer:
    """Draws straight to /dev/fb0 (works for SPI TFTs and HDMI screens, no desktop needed).
    A 1024x600 or 1280x800 screen gets the 800x480 UI scaled up to fit."""
    def __init__(self, dev="/dev/fb0", fit="auto"):
        base = "/sys/class/graphics/" + os.path.basename(dev)
        self.w, self.h = (int(v) for v in open(base + "/virtual_size").read().strip().split(","))
        self.f = open(dev, "r+b", buffering=0)
        self._base = base
        self._console_off()
        if int(open(base + "/bits_per_pixel").read()) == 16: self._try_32()
        self.bpp = int(open(base + "/bits_per_pixel").read())
        self.stride = int(open(base + "/stride").read())
        if self.bpp == 16:
            print("screen: the framebuffer is 16-bit, so greys are dithered. For true colour, run once:  "
                  "sudo python3 tools/screen32.py  (then reboot)")
        self.box = fit_box(self.w, self.h, fit)
        if self.w > 1920:
            print(f"warning: the screen is {self.w} x {self.h}: every frame is slow at that size and the audio may crackle. "
                  "Run the monitor at 1080p (see tools/pi_check.py)")

    def _try_32(self):
        """ask the framebuffer for 32-bit colour (16-bit makes greys band into pink / green / blue). Many drivers allow it;
        the Pi's KMS framebuffer only takes it from the boot line (tools/screen32.py sets that)"""
        import fcntl, struct
        try:
            buf = bytearray(160)
            fcntl.ioctl(self.f, 0x4600, buf)                    # FBIOGET_VSCREENINFO
            struct.pack_into("I", buf, 24, 32)                  # bits_per_pixel
            for off, (o, l) in zip((32, 44, 56, 68), ((16, 8), (8, 8), (0, 8), (24, 0))):   # red green blue transp
                struct.pack_into("III", buf, off, o, l, 0)
            fcntl.ioctl(self.f, 0x4601, buf)                    # FBIOPUT_VSCREENINFO
        except Exception: pass

    def _console_off(self):
        """the Linux text console shares this framebuffer: its blinking cursor (a small block) and any kernel message would
        draw over Monolith. Put the console in graphics mode (it stops drawing) and hide its cursor; undone on exit."""
        import fcntl, atexit
        for tty in ("/dev/tty0", "/dev/tty1"):
            try:
                fd = os.open(tty, os.O_RDWR)
                os.write(fd, b"\033[?25l")                       # cursor off
                try:
                    fcntl.ioctl(fd, 0x4B3A, 1)                  # KDSETMODE KD_GRAPHICS: the console stops drawing
                    atexit.register(lambda fd=fd: (fcntl.ioctl(fd, 0x4B3A, 0), os.write(fd, b"\033[?25h")))
                except Exception: pass
                break
            except OSError: continue
        try:
            with open("/sys/class/graphics/fbcon/cursor_blink", "w") as f_: f_.write("0")
        except OSError: pass

    def frac_box(self):
        x, y, w, h = self.box
        return x / float(self.w), y / float(self.h), (x + w) / float(self.w), (y + h) / float(self.h)

    def _map(self):
        """the framebuffer memory as a numpy array (rows x stride bytes): each frame is one copy into it, no file writes"""
        import mmap
        self._mm = mmap.mmap(self.f.fileno(), self.stride * self.h, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self.mem = np.frombuffer(self._mm, np.uint8).reshape(self.h, self.stride)
        self.mem[:] = 0                                          # black bars, once

    STRIP = 64                                                    # rows converted at a time (see show)

    def show(self, img, mouse=None):
        """copies the frame into screen memory in strips of 64 rows: one big conversion would hold Python for 10-30 ms
        on a Pi, longer than an audio block (5.8 ms), and the audio thread would miss its turn (a dropout)"""
        x, y, w, h = self.box
        if img.size != (w, h):
            img = img.resize((w, h), Image.BICUBIC if w > img.size[0] else Image.LANCZOS)
        if getattr(self, "mem", None) is None:
            try: self._map()
            except Exception: self.mem = False                  # no mmap (unusual drivers): fall back to writes
        b = self.bpp // 8
        if getattr(self, "clean", None) is None or self.clean.shape != (h, w * b):
            self.clean = np.zeros((h, w * b), np.uint8)
        ptr = self._pointer_patch(img, mouse) if self.mem is not False else None   # drawn into its strip: no flicker
        changed = []
        if getattr(self, "_raw", None) is None or len(self._raw) != (h + self.STRIP - 1) // self.STRIP: self._raw = [None] * ((h + self.STRIP - 1) // self.STRIP)
        for k, r0 in enumerate(range(0, h, self.STRIP)):          # strip by strip (the audio gets turns between)
            r1 = min(h, r0 + self.STRIP)
            part = img.crop((0, r0, w, r1))
            raw = part.tobytes()
            pp_hit = self._pp is not None if hasattr(self, "_pp") else False
            if raw == self._raw[k] and ptr is None and not pp_hit: continue      # unchanged: no conversion, no copy
            self._raw[k] = raw
            self.clean[r0:r1] = self._px(part, r0); changed.append((r0, r1))
        if self.mem is not False and changed:
            for r0, r1 in changed:                               # (memory copies only: quick)
                self.mem[y + r0:y + r1, x * b:(x + w) * b] = self.clean[r0:r1]
                if ptr is not None:
                    (px0, py0), pp = ptr
                    a0, a1 = max(r0, py0), min(r1, py0 + pp.shape[0])
                    if a1 > a0: self.mem[y + a0:y + a1, (x + px0) * b:(x + px0) * b + pp.shape[1]] = pp[a0 - py0:a1 - py0]

        self.clean_img = img                                      # the frame without the pointer: pointer() redraws over it
        self._pp = ptr[0] if ptr is not None else None
        if self.mem is False:
            if not hasattr(self, "_buf"): self._buf = np.zeros((self.h, self.stride), np.uint8)
            self._buf[y:y + h, x * b:(x + w) * b] = self.clean
            self.f.seek(0); self.f.write(self._buf.tobytes())


    def _px(self, img, row0=0):
        if self.bpp == 32: return np.frombuffer(img.tobytes("raw", "BGRX"), np.uint8).reshape(img.size[1], img.size[0] * 4)
        # 16-bit: green has one bit more than red and blue, so a plain cut tints greys pink / green in bands. All three
        # are cut to the same 32 steps (green's extra bit copied), so greys stay grey. (32-bit, tools/screen32.py, is
        # the real fix; this costs no more than the plain conversion did.)
        q = np.asarray(img) >> 3
        q16 = q.astype(np.uint16)
        g = q16[..., 1]
        v = (q16[..., 0] << 11) | (g << 6) | ((g >> 4) << 5) | q16[..., 2]
        return v.astype("<u2").view(np.uint8).reshape(img.size[1], img.size[0] * 2)

    def _pointer_patch(self, img, mouse):
        """((x, y), pixels) of the pointer drawn over this frame, or None when it is hidden"""
        if mouse is None or not mouse.pointer_visible(): return None
        bx, by, bw, bh = self.box
        scale = bw / float(W)
        x0, y0 = int(mouse.x * scale), int(mouse.y * scale)
        pw, ph = int(inputs.POINTER_SIZE[0] * scale * 1.2) + 2, int(inputs.POINTER_SIZE[1] * scale * 1.0) + 2
        x1, y1 = min(bw, x0 + pw), min(bh, y0 + ph)
        if x1 <= x0 or y1 <= y0: return None
        patch = img.crop((x0, y0, x1, y1))
        inputs.draw_pointer(patch, mouse, scale, origin=(x0, y0))
        return (x0, y0), self._px(patch)

    def pointer(self, mouse, scale):
        """moves the mouse pointer straight in screen memory, 60 times a second, without redrawing the UI: only the small
        patch it leaves and the patch it enters are rewritten, so the pointer stays smooth however slow a full frame is"""
        if getattr(self, "mem", None) is None or self.mem is False or getattr(self, "clean", None) is None: return
        vis = mouse is not None and mouse.pointer_visible()
        pos = (int(mouse.x * scale), int(mouse.y * scale)) if vis else None
        if pos == self._pp: return
        bx, by, bw, bh = self.box
        b = self.bpp // 8
        pw, ph = int(inputs.POINTER_SIZE[0] * scale * 1.2) + 2, int(inputs.POINTER_SIZE[1] * scale * 1.0) + 2
        if self._pp:                                             # put back what was under the old pointer
            x0, y0 = self._pp; x1, y1 = min(bw, x0 + pw), min(bh, y0 + ph)
            if x1 > x0 and y1 > y0: self.mem[by + y0:by + y1, (bx + x0) * b:(bx + x1) * b] = self.clean[y0:y1, x0 * b:x1 * b]
        self._pp = pos
        if pos:
            x0, y0 = pos; x1, y1 = min(bw, x0 + pw), min(bh, y0 + ph)
            if x1 <= x0 or y1 <= y0: return
            patch = self.clean_img.crop((x0, y0, x1, y1))
            inputs.draw_pointer(patch, mouse, scale, origin=(x0, y0))
            self.mem[by + y0:by + y1, (bx + x0) * b:(bx + x1) * b] = self._px(patch)


class XScreen:
    """The sampler's screen as an X11 window (use --x11). Needed to show a VST3 plug-in's own window inside the UI.
    Run a bare X server (no desktop): e.g.  xinit ./sampler_os.py --x11 ... -- :0  (see README). Touch comes from X."""
    def __init__(self, fit="auto"):
        import ctypes, fx
        self.ct, self.lib = ctypes, fx.HOST
        if self.lib is None: raise RuntimeError("vst3host/vst3host.so is not built (cd vst3host && ./build.sh)")
        w, h = ctypes.c_int(0), ctypes.c_int(0)
        if not self.lib.xs_screen_size(ctypes.byref(w), ctypes.byref(h)): raise RuntimeError("no X display (is DISPLAY set?)")
        self.w, self.h = w.value, h.value
        self.box = fit_box(self.w, self.h, fit)
        self.win = self.lib.xs_open(self.w, self.h, 0, 0, b"sampler")
        self.editor = None                                            # (effect, window, w, h)

    def show(self, img):
        x, y, w, h = self.box
        if img.size != (self.w, self.h):
            scaled = img if img.size == (w, h) else img.resize((w, h), Image.BICUBIC if w > img.size[0] else Image.LANCZOS)
            full = Image.new("RGB", (self.w, self.h), (0, 0, 0)); full.paste(scaled, (x, y)); img = full
        a = np.asarray(img)
        bgrx = np.zeros((self.h, self.w, 4), np.uint8)
        bgrx[..., 0], bgrx[..., 1], bgrx[..., 2] = a[..., 2], a[..., 1], a[..., 0]
        self._buf = np.ascontiguousarray(bgrx)
        self.lib.xs_put(self._buf.ctypes.data, self.w, self.h)

    def grab(self):
        buf = np.zeros((self.h, self.w, 4), np.uint8)
        self.lib.xs_grab(buf.ctypes.data, self.w, self.h)
        return Image.fromarray(buf[..., [2, 1, 0]].copy())

    def to_ui(self, px, py):
        x, y, w, h = self.box
        return (px - x) * W / float(w), (py - y) * H / float(h)

    def _layout(self, ew, eh):
        """where the plug-in window goes: between the top bar and the Q-link strip; scroll bars when it is too big"""
        bx, by, bw, bh = self.box
        kx, ky = bw / float(W), bh / float(H)
        ax, ay, aw, ah = bx, by + int(round(TOP_H * ky)), bw, int(round((Q_Y - 2 - TOP_H) * ky))
        tx, ty = int(round(SCROLL_T * kx)), int(round(SCROLL_T * ky))
        hb = vb = False
        for _ in range(2):
            vb = eh > ah - (ty if hb else 0)
            hb = ew > aw - (tx if vb else 0)
        vw = (aw - (tx if vb else 0)) if hb else ew
        vh = (ah - (ty if hb else 0)) if vb else eh
        vx = ax if hb else ax + (aw - (tx if vb else 0) - ew) // 2
        return vx, ay, vw, vh, hb, vb, kx, ky

    def _apply(self, ctl, ew, eh):
        """(re)place the viewport for a plug-in window of ew x eh pixels and publish its geometry to the UI"""
        vx, vy, vw, vh, hb, vb, kx, ky = self._layout(ew, eh)
        self.lib.xs_place(self.editor["view"], vx, vy, vw, vh)
        bx, by = self.box[0], self.box[1]
        old = ctl.editor_view or {}
        ctl.editor_view = {"x": (vx - bx) / kx, "y": (vy - by) / ky, "w": vw / kx, "h": vh / ky,
                           "cw": ew / kx, "ch": eh / ky, "sx": 0.0, "sy": 0.0, "hbar": hb, "vbar": vb,
                           "name": self.editor["fx"].name, "px": (ew, eh), "zoom": self.editor["zoom"],
                           "can_zoom": self.editor["can_zoom"]}
        ctl.editor_scroll_to(old.get("sx", 0.0), old.get("sy", 0.0))
        self.editor["at"] = None

    def fit_zoom(self):
        """the biggest zoom at which the whole plug-in window fits (between 50 % and 100 %)"""
        bx, by, bw, bh = self.box
        aw, ah = bw, int(round((Q_Y - 2 - TOP_H) * bh / float(H)))
        w1, h1 = self.editor["base"]
        return max(0.5, min(1.0, aw / float(w1), ah / float(h1)))

    def _zoom(self, ctl, z):
        ed = self.editor
        if not ed["can_zoom"]: ctl.say("this plug-in cannot be zoomed"); return
        z = max(ZOOMS[0], min(ZOOMS[-1], z))
        if not ed["fx"].scale_editor(z): ed["can_zoom"] = False; ctl.say("this plug-in cannot be zoomed"); return
        for _ in range(10): ed["fx"].editor_idle(); time.sleep(0.005)
        ed["zoom"] = z
        ctl.editor_zooms[ed["fx"].path] = z
        size = ed["fx"].editor_size() or ed["base"]
        self._apply(ctl, *size)

    def pump(self, ctl):
        """touch / mouse from X -> Controls.touch; open / close / zoom / scroll / idle the plug-in window"""
        ct = self.ct
        k, x, y = ct.c_int(0), ct.c_int(0), ct.c_int(0)
        while self.lib.xs_event(ct.byref(k), ct.byref(x), ct.byref(y)):
            ux, uy = self.to_ui(x.value, y.value)
            ctl.touch({1: "down", 2: "move", 3: "up"}[k.value], ux, uy)
        cur = ctl.editor_obj
        req = ctl.editor_req; ctl.editor_req = None
        if self.editor and (req == "close" or self.editor["fx"] is not cur or ctl.mode != self.editor["mode"]
                            or (ctl.mode == "FX" and ctl.e.get_fx(ctl.fx_tgt()) is not cur)):
            self.editor["fx"].close_editor(); self.lib.xs_destroy(self.editor["view"])
            self.editor = None; ctl.editor_fx = None; ctl.editor_view = None; ctl.editor_obj = None
        if req == "open" and self.editor is None and cur is not None and hasattr(cur, "open_editor"):
            view = self.lib.xs_child(0, 0, 1, 1)                        # the viewport: clips and scrolls the plug-in window
            r = cur.open_editor(view, 0, 0)
            if r:
                for _ in range(20): cur.editor_idle(); time.sleep(0.01)     # let the plug-in finish opening before zooming
                can = cur.scale_editor(1.0)                            # the plug-in may remember an older zoom: reset it
                for _ in range(5): cur.editor_idle()
                base = cur.editor_size() or (r[1], r[2])
                self.editor = {"fx": cur, "view": view, "at": None, "base": base, "zoom": 1.0, "can_zoom": can, "mode": ctl.mode}
                ctl.editor_fx = cur; ctl.editor_view = None
                self._apply(ctl, *base)
                z = ctl.editor_zooms.get(cur.path)                     # last zoom used for this plug-in, else fit it on screen
                if z is None: z = self.fit_zoom()
                if abs(z - 1.0) > 1e-3: self._zoom(ctl, z)
            else:
                self.lib.xs_destroy(view); ctl.say("this plug-in has no window of its own")
        if self.editor and isinstance(req, tuple) and req[0] == "zoom":
            z = self.editor["zoom"]
            if req[1] == "fit": z = self.fit_zoom()
            elif req[1] == "in": z = next((s for s in ZOOMS if s > z + 1e-3), ZOOMS[-1])
            elif req[1] == "out": z = next((s for s in reversed(ZOOMS) if s < z - 1e-3), ZOOMS[0])
            else: z = float(req[1])
            self._zoom(ctl, z)
        if self.editor:
            v = ctl.editor_view
            at = (-int(round(v["sx"] * self.box[2] / float(W))), -int(round(v["sy"] * self.box[3] / float(H))))
            if at != self.editor["at"]:
                self.editor["fx"].move_editor(*at); self.editor["at"] = at
            self.editor["fx"].editor_idle()


LIGHTS = {"port": None, "ser": None}            # the Arduino's serial port, shared with the light-sending thread


def lights_thread(e, fps=20):
    last = None
    while True:
        time.sleep(1.0 / fps)
        ser = LIGHTS["ser"]
        if ser is None: continue
        data, last2 = lights_frame(e, last)
        if not data: continue
        try: ser.write(data); last = last2
        except Exception: LIGHTS["ser"] = None; last = None


def handle_line(c, line):
    p = line.strip().split(",")
    try:
        if p[0] == "P": c.pad_hit(int(p[1]), c.vel_in(int(p[2])))   # through SETTINGS > PAD VELOCITY
        elif p[0] == "K": c.knob(int(p[1]), int(p[2]))
        elif p[0] == "B": c.button(int(p[1]), p[2] == "1")      # B,<0-23>,<1|0>
    except (ValueError, IndexError):
        pass


def lights_frame(e, last=None):
    """Bytes for the Arduino's rear light strip: 'V,<left 0-255>,<right 0-255>' (VU meter) and 'S,<bits>' (bit0 playing, bit1 recording).
    Returns (bytes, state); pass the previous state back so nothing is sent when nothing changed."""
    lv = lambda m: int(255 * min(1.0, m) ** 0.5)                  # square root: the bar moves visibly at low levels
    state = (lv(e.meter_l) // 8 * 8, lv(e.meter_r) // 8 * 8, int(e.playing) | (2 if e.rec != "off" else 0))
    if state == last: return b"", state
    return f"V,{state[0]},{state[1]}\nS,{state[2]}\n".encode(), state


def serial_thread(c, port):
    import serial
    while True:
        try:
            with serial.Serial(port, 115200, timeout=1) as ser:
                c.e.say("controller connected")
                if port == LIGHTS["port"] or LIGHTS["port"] is None:
                    LIGHTS["ser"] = ser
                while True:
                    handle_line(c, ser.readline().decode(errors="ignore"))
        except Exception as ex:
            c.e.say("controller: retrying")
            time.sleep(2)


def keyboard_thread(c):
    import termios, tty
    from uicore import BTN
    pads = {ch: i + 1 for i, ch in enumerate("zxcvasdfqwer1234")}
    qk = {"t": (0, -1), "y": (0, 1), "g": (1, -1), "h": (1, 1), "b": (2, -1), "n": (2, 1), "u": (3, -1), "i": (3, 1)}
    keys = {" ": "PLAY", ".": "STOP", "p": "PLAYSTART", "=": "REC", ",": "OVERDUB", "5": "MAIN", "6": "GRID", "7": "MUTE", "8": "STEP",
            "9": "PROG", "j": "SAMPLE", "k": "CHOP", "l": "MIXER", "m": "FX", "\\": "UNDO", "/": "TAP", ";": "BANK", "'": "REPEAT",
            "!": "F1", "@": "F2", "#": "F3", "$": "F4"}
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    arrows = {"A": "up", "B": "down", "C": "right", "D": "left"}
    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq[-1:] in arrows: c.nav(arrows[seq[-1]])
            elif ch == "[": c.jog(-1)
            elif ch == "]": c.jog(1)
            elif ch in "\r\n": c.ok()
            elif ch in pads: c.pad_hit(pads[ch], 100)
            elif ch in qk: c.nudge(qk[ch][0], qk[ch][1] * 0.04)
            elif ch == "-": c.button(BTN["ERASE"], True); c.button(BTN["ERASE"], False)
            elif ch == "0": c.shift = not c.shift
            elif ch == "o": c.set_mode("SONG")
            elif ch in keys: c.button(BTN[keys[ch]], True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def make_shots(eng, ctl, ren, folder):
    """Render every screen to PNG (also handy for checking the UI without hardware)."""
    from PIL import Image
    folder = os.path.abspath(folder)                                 # plug-ins may change the working directory
    os.makedirs(folder, exist_ok=True)
    eng.save_project = lambda: None                                  # screenshots must not touch project.json
    seq = eng.seq
    t = seq.tracks[5]; t.name = "Bass"; t.prog = 0
    for bar in range(2):
        for st, pad in ((0, 9), (6, 9), (8, 10), (12, 9)): eng._put(t, bar * 384 + st * 24, pad, 100, 48)
    t = seq.tracks[6]; t.name = "Stabs"
    for bar in range(2):
        for st, pad in ((2, 11), (10, 12)): eng._put(t, bar * 384 + st * 24, pad, 90, 24)
    seq.tracks[4].mute = False
    eng.cur_track = 0
    eng.play()
    for _ in range(int(OUT_SR * 1.7 / 256)): eng.render(256)
    names = ["00_splash"]
    from screens import splash
    splash("loading samples and project...", 0.6).save(os.path.join(folder, "00_splash.png"))
    def snap(name, mode, shift=False):
        ctl.set_mode(mode); ctl.shift = shift; eng.msg_time = 0
        ren.frame().save(os.path.join(folder, name + ".png")); names.append(name)
    eng.say("pad A03 selected"); eng.select_pad(0, 2)
    for _ in range(2): eng.pad_hit(1, 110); eng.render(256)
    snap("01_main", "MAIN")
    snap("02_seq", "SEQ")
    for k in (3, 5): eng.seq.tracks[k].mute = True
    eng.seq.tracks[1].solo = False; eng.next_seq = 1 if eng.playing else None
    snap("02c_mute", "MUTE")
    for k in (3, 5): eng.seq.tracks[k].mute = False
    eng.next_seq = None
    ctl.g_tick, ctl.g_lane = 96, 1
    eng.stop(); eng.pos = 0.0; eng.cur_track = 2; eng.select_pad(0, 2)
    ctl.g_lane = 2; ctl.g_tick = 96
    snap("03_grid", "GRID")
    snap("04_step", "STEP")
    eng.select_pad(0, 0); eng.pad_hit(1, 120); eng.render(2048)
    snap("05_program", "PROG")
    brk0 = eng.source_by_name("break")
    if brk0 is not None:                                              # a WARP pad: the 90 bpm break following a 104 bpm sequence
        eng.select_pad(3, 15); wpd = eng.pad; wpd.assign(brk0); bpm_was = eng.seq.bpm
        eng.set_warp(wpd, True); eng.seq.bpm = 104.0; ctl.prog_row = 15
        eng.trigger(wpd, 110)
        for _ in range(int(OUT_SR * 0.8 / 256)): eng.render(256); time.sleep(0.002)
        snap("05b_program_warp", "PROG")
        eng.seq.bpm = bpm_was; ctl.prog_row = 3; eng.select_pad(0, 0)
        with eng.lock:
            for k_ in range(eng.nv): eng.v_data[k_] = None
    eng.has_input, eng.in_meter, eng.rec_state, eng.rec_len = True, 0.55, "rec", int(OUT_SR * 1.6)
    eng.rec_peaks = [abs(np.sin(i / 9.0)) * np.exp(-i / 220.0) for i in range(380)]
    snap("06_sample", "SAMPLE")
    eng.rec_state = "idle"
    eng.cur_track = 4; eng.select_pad(0, 0)                           # the break track / program, chopped by transients
    brk = eng.source_by_name("break")
    if brk is not None:
        eng.chop_transient(brk, 0.25); eng.chop_to_pads(brk, 0, eng.programs[1])
        ctl.chop_mode = 1; ctl.chop_cursor = brk.chops[2] if len(brk.chops) > 2 else 0; ctl.chop_sel = 2
    eng.msg_time = 0
    snap("07_chop", "CHOP")
    eng.cur_track = 0; eng.select_pad(0, 0)
    eng.nout = 8; eng.programs[0].pads[4].out = 2; eng.programs[0].pads[6].out = 7; eng.programs[0].pads[2].out = 1
    eng.programs[0].pads[3].mute = True; eng.programs[0].pads[5].vol = 0.5; eng.programs[0].pads[2].pan = -0.5
    for n in (1, 2, 3): eng.pad_hit(n, 100)
    eng.render(512)
    snap("08_mixer", "MIXER")
    ctl.mix_page = 1; eng.seq.tracks[1].mute = True; eng.seq.tracks[2].solo = False
    snap("08b_tracks", "MIXER"); ctl.mix_page = 0
    import fx as fxlib
    eng.select_pad(0, 0); ctl.fx_target = 0; eng.set_fx(eng.programs[0].pads[0], "builtin", "Delay")
    eng.programs[0].pads[0].fx.set(0, 0.45); eng.programs[0].pads[0].fx.set(2, 0.5)
    ctl.fx_items = [('', '', '- none -')] + fxlib.discover()             # only effects that really exist on this machine
    ctl.set_mode("FX"); ctl.fx_set_target(0); ctl.armed = [True] * 4; eng.cpu = 0.18
    snap("09_fx", "FX")
    vsts = [it for it in ctl.fx_items if it[0] == "vst3"]
    if vsts:                                                           # a real third-party VST3 on the master bus, playing the beat
        import time as _t
        ctl.set_mode("FX"); ctl.fx_set_target(64)
        eng.set_fx("master", "vst3", vsts[0][1])
        mfx = eng.master_fx
        want = {"Drive": 0.7, "Detune": 0.55, "Mix": 1.0, "Bitcrush On": 1.0, "Threshold": 0.55}
        for i, nm in enumerate(mfx.names):
            if nm in want: mfx.set(i, want[nm])
        page = next((i // 4 for i, nm in enumerate(mfx.names) if nm == "Detune"), 0)
        ctl.fx_page = page; ctl.fx_cursor_to_loaded()
        eng.play(); t0 = _t.time(); n = int(OUT_SR * 1.0 / 256)
        for _ in range(n): eng.render(256)
        eng.cpu = (_t.time() - t0) / 1.0                               # real time used to render 1 s of audio here (not on a Pi)
        ctl.armed = [True] * 4; eng.msg_time = 0
        ren.frame().save(os.path.join(folder, "09b_vst.png")); names.append("09b_vst")
        if os.environ.get("DISPLAY") and fxlib.HOST is not None:          # the maker's own window, embedded in the sampler screen
            try:
                xs = XScreen("stretch")
                ctl.toggle_editor(); xs.pump(ctl)
                t1 = _t.time(); k = 0
                while _t.time() - t1 < 2.0:
                    eng.render(256); xs.pump(ctl); _t.sleep(0.01); k += 1
                    if k % 6 == 0: eng.msg_time = 0; xs.show(ren.frame())
                eng.msg_time = 0; xs.show(ren.frame()); xs.pump(ctl); _t.sleep(0.3); xs.pump(ctl)
                xs.grab().resize(ren.img.size, Image.LANCZOS).save(os.path.join(folder, "09c_plugin_window.png")); names.append("09c_plugin_window")
                ctl.editor_req = ("zoom", 0.75); xs.pump(ctl)
                for _ in range(60): eng.render(256); xs.pump(ctl); _t.sleep(0.01)
                eng.msg_time = 0; xs.show(ren.frame()); xs.pump(ctl); _t.sleep(0.3); xs.pump(ctl)
                xs.grab().resize(ren.img.size, Image.LANCZOS).save(os.path.join(folder, "09e_plugin_zoom75.png"))
                ctl.editor_req = "close"; xs.pump(ctl)
                if xs.w < 760:                                         # small screen: zoomed in, the window gets scroll bars
                    ctl.editor_zooms[mfx.path] = 1.0
                    ctl.toggle_editor(); xs.pump(ctl)
                    for _ in range(60): eng.render(256); xs.pump(ctl); _t.sleep(0.01)
                    ctl.editor_scroll(160, 40)
                    for _ in range(60): eng.render(256); xs.pump(ctl); _t.sleep(0.01)
                    eng.msg_time = 0; xs.show(ren.frame()); xs.pump(ctl); _t.sleep(0.3); xs.pump(ctl)
                    xs.grab().save(os.path.join(folder, "09d_plugin_scroll.png"))
                    ctl.editor_req = "close"; xs.pump(ctl)
            except Exception as ex:
                print("plug-in window shot skipped:", ex)
        eng.stop(); eng.stop(); eng.set_fx("master")
        from engine import FxSlot                                     # the same plug-in as a PROGRAM insert (slot 2), Delay in slot 1
        eng.set_fx(FxSlot(eng.programs[0], 0), "builtin", "Delay"); eng.set_fx(FxSlot(eng.programs[0], 1), "vst3", vsts[0][1])
        ctl.set_mode("FX"); ctl.fx_set_target(66); ctl.armed = [True] * 4
        eng.play()
        for _ in range(int(OUT_SR * 0.5 / 256)): eng.render(256)
        snap("09g_program_insert", "FX")
        eng.stop(); eng.stop(); eng.set_fx(FxSlot(eng.programs[0], 0)); eng.set_fx(FxSlot(eng.programs[0], 1)); ctl.fx_set_target(0)
    kt = eng.seq.tracks[8]; kt.name, kt.kind, kt.key_pad, kt.root = "Keys", "keys", 11, 60     # a KEYS track: chords + a line
    for bar in range(2):
        for st, chord in ((0, (57, 60, 64)), (8, (53, 57, 60))):
            for n_ in chord: eng._put(kt, bar * 384 + st * 24, n_, 92, 168)
        for st, n_ in ((0, 69), (3, 67), (6, 64), (10, 65), (12, 64), (14, 62)): eng._put(kt, bar * 384 + st * 24, n_, 110, 36)
    eng.cur_track = 8; ctl.g_lanes = 16; ctl.g_lane = 64; ctl.k_top = 74; ctl.g_bars = 2; ctl.g_off = 0
    eng.held = {64: (None, 100)}
    snap("03b_piano_roll", "GRID")
    eng.held = {}; ctl.g_lanes = 8
    insts = fxlib.discover_instruments()
    pt = eng.seq.tracks[9]
    if insts and eng.set_track_kind(pt, "plugin", insts[0][0]):        # a PLUGIN track: a real VST3 synth (e.g. Dexed) plays the line
        pt.events = [ev for ev in kt.events if ev[1] >= 62]
        eng.cur_track = 9; ctl.g_lanes = 16; ctl.k_top = 74
        eng.play()
        for _ in range(int(OUT_SR * 0.6 / 256)): eng.render(256)
        snap("03c_plugin_track", "GRID")
        ctl.set_mode("SEQ"); ctl.track_setup = 9; ctl.ts_tab = None; eng.msg_time = 0
        ren.frame().save(os.path.join(folder, "02b_track_setup.png")); names.append("02b_track_setup")
        if os.environ.get("DISPLAY") and fxlib.HOST is not None:          # the synth's own window
            try:
                import time as _t
                xs = XScreen("stretch")
                ctl.track_setup = None; ctl.toggle_editor(eng.instrument(pt), "TRACK 10"); xs.pump(ctl)
                t1 = _t.time(); k = 0
                while _t.time() - t1 < 2.0:
                    eng.render(256); xs.pump(ctl); _t.sleep(0.01); k += 1
                    if k % 6 == 0: eng.msg_time = 0; xs.show(ren.frame())
                eng.msg_time = 0; xs.show(ren.frame()); xs.pump(ctl); _t.sleep(0.3); xs.pump(ctl)
                xs.grab().resize(ren.img.size, Image.LANCZOS).save(os.path.join(folder, "09f_synth_window.png")); names.append("09f_synth_window")
                ctl.editor_req = "close"; xs.pump(ctl)
            except Exception as ex:
                print("synth window shot skipped:", ex)
        eng.stop(); eng.stop(); ctl.track_setup = None
    else:
        ctl.set_mode("SEQ"); ctl.track_setup = 8; ctl.ts_tab = None; eng.msg_time = 0
        ren.frame().save(os.path.join(folder, "02b_track_setup.png")); names.append("02b_track_setup"); ctl.track_setup = None
    ctl.g_lanes = 8
    # pad modes: PERFORM on the KEYS track, 16 LEVELS, TRACK MUTE on MAIN with the Q-links on PROJECT
    eng.cur_track = 8; eng.perf_scale, eng.perf_root, eng.perf_oct, eng.perf_chord = 2, 9, 4, 1
    ctl.set_mode("PADS"); ctl.set_pad_mode("PERFORM"); ctl.pads_row = 3
    for n_ in (1, 6): ctl.pad_hit(n_, 100)
    eng.render(256); snap("13_pads_perform", "PADS")
    eng.select_pad(0, 0); ctl.set_pad_mode("16 LEVELS"); ctl.pads_row = 1; ctl.pad_flash = {}
    ctl.pad_hit(12, 100); eng.render(256); snap("13b_pads_levels", "PADS")
    eng.cur_track = 0; ctl.pad_flash = {}; ctl.set_pad_mode("TRACK MUTE"); eng.seq.tracks[1].mute = True; ctl.qlink_mode = "PROJECT"
    snap("13c_main_track_mute", "MAIN")
    for t_ in eng.seq.tracks: t_.mute = False
    eng.pad_mode = "NORMAL"; ctl.qlink_mode = "SCREEN"
    eng.cur_track = 0
    ctl.br_dir = eng.sample_dir; ctl.set_mode("BROWSE"); ctl.br_refresh()
    ctl.br_cur = min(3, len(ctl.br_items) - 1); ctl.br_open(); eng.stop_preview()
    snap("14_browse", "BROWSE")
    import json as _json, tempfile as _tf
    usb_mp = _tf.mkdtemp(prefix="shots_usb_")                         # a pretend USB stick (no drive in this sandbox)
    fake = {"blockdevices": [
        {"name": "/dev/sda", "type": "disk", "tran": "usb", "rm": True, "size": "29.8G", "children": [
            {"name": "/dev/sda1", "type": "part", "label": "BEATS", "fstype": "exfat", "mountpoint": usb_mp, "size": "29.8G"}]},
        {"name": "/dev/sdb", "type": "disk", "tran": "usb", "rm": True, "size": "1.8T", "children": [
            {"name": "/dev/sdb1", "type": "part", "label": "SAMPLES SSD", "fstype": "ext4", "mountpoint": None, "size": "1.8T"}]}]}
    ctl._run = lambda cmd: (True, _json.dumps(fake)) if cmd[0] == "lsblk" else (False, "")
    ctl.br_dir = None; ctl.br_refresh(); ctl.br_cur = next(i for i, it in enumerate(ctl.br_items) if it[1] == usb_mp)
    snap("14b_browse_usb", "BROWSE")
    eng.select_pad(0, 2); p3 = eng.pad; p3.tune, p3.reverse = -5, True; eng.set_fx(p3, "builtin", "Delay")
    eng.flatten_pad(p3); ctl.prog_row = 0
    snap("05c_program_flattened", "PROG")
    eng.unflatten_pad(p3); eng.set_fx(p3); p3.tune, p3.reverse = 0, False
    ctl.set_mode("EXPORT"); ctl.ex_dest = 1
    ctl.start_track_out(wait=True); eng.msg_time = 0
    snap("15_track_out", "EXPORT")
    ctl._run = None; ctl._drives = []
    shutil.rmtree(usb_mp, ignore_errors=True)
    class _IO: names = {"/dev/snd/midiC1D0": "MPK249 1D0", "/dev/snd/midiC1D1": "MPK249 1D1"}
    ctl.midi_io = _IO(); ctl.midi_seen = time.time()
    ctl.midi_map.learned = {"Q1": ["cc", 1, 22], "Q2": ["cc", 1, 23], "Q3": ["cc", 1, 24], "Q4": ["cc", 1, 25],
                            "F1": ["cc", 1, 32], "F2": ["cc", 1, 33], "UNDO": ["cc", 1, 36], "SHIFT": ["cc", 1, 39]}
    eng.seq.tracks[8].midi_ch = 0; eng.seq.tracks[10].midi_ch = 2
    ctl.midi_row = 5; ctl.midi_learn = "JOG"
    snap("12_midi", "MIDI")
    ctl.midi_learn = None; ctl.midi_io = None; ctl.midi_map.learned = {}
    eng.song = [[0, 2], [1, 1], [0, 1]]
    ctl.song_cur = 1
    snap("10_song", "SONG")
    snap("11_shift_help", "MAIN", True)
    ctl.shift = False
    snap("16_menu", "MENU")
    snap("17_projects", "PROJECTS")
    ctl.ed_open("COPY BARS"); eng.msg_time = 0
    ren.frame().save(os.path.join(folder, "18_edit.png")); names.append("18_edit")
    ctl.set_mode("GRID"); ctl.rename_seq(); ctl.kbd["text"] = "Verse 2"; ctl.kbd["row"], ctl.kbd["col"] = 2, 3; eng.msg_time = 0
    ren.frame().save(os.path.join(folder, "19_naming.png")); names.append("19_naming"); ctl.kbd = None
    eng.select_pad(0, 0); p0 = eng.pad; p0.flt, p0.cutoff, p0.res, p0.decay, p0.f_env, p0.f_dec = "LP", 0.62, 0.35, 280, 0.25, 180
    ctl.set_mode("PROG"); ctl.set_prog_tab(2); ctl.prog_row = 19; eng.msg_time = 0
    ren.frame().save(os.path.join(folder, "05d_program_env_filter.png")); names.append("05d_program_env_filter")
    p0.flt, p0.decay, p0.f_env, p0.res, p0.cutoff = "OFF", 0, 0.0, 0.0, 1.0
    eng.rec_src = "RESAMPLE"; snap("06b_resample", "SAMPLE"); eng.rec_src = "INPUT"
    cols, rows, tw, th = 2, (len(names) + 1) // 2, 400, 400 * H // W
    sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
    for i, n in enumerate(names):
        im = Image.open(os.path.join(folder, n + ".png")).resize((tw, th), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(os.path.join(folder, "ui_screens.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", action="store_true", help="keyboard test mode instead of the Arduino")
    ap.add_argument("--port"); ap.add_argument("--port2", help="optional micro:bit serial port")
    ap.add_argument("--device", help="audio device number, or 'in,out' (see python3 -m sounddevice)")
    ap.add_argument("--block", type=int, default=256)
    ap.add_argument("--voices", type=int, default=16, help="simultaneous sample voices (a Pi 5 copes with 32)")
    ap.add_argument("--outs", type=int, default=2, help="analogue output channels on the sound card (8 for a DAC8x-style card)")
    ap.add_argument("--in-device", help="separate audio INPUT device (number or name) when the output card has no inputs")
    ap.add_argument("--fb", default="/dev/fb0")
    ap.add_argument("--no-midi", action="store_true", help="do not look for USB MIDI keyboards / controllers")
    ap.add_argument("--no-studio", action="store_true", help="do not look for an Akai MPC Studio (mk1) controller")
    ap.add_argument("--no-arduino", action="store_true", help="prototype without the Arduino (touchscreen + MIDI controller only)")
    ap.add_argument("--x11", action="store_true", help="draw into an X11 window instead of /dev/fb0 (needed for VST3 plug-in windows)")
    ap.add_argument("--png", help="write the screen to this PNG file instead of /dev/fb0")
    ap.add_argument("--shots", help="write a PNG of every screen to this folder and exit")
    ap.add_argument("--fps", type=float, default=15)
    ap.add_argument("--latency", default="0.016", help="audio buffering in seconds (default 0.016), or low / high; more = fewer dropouts but more delay")
    ap.add_argument("--ui-share", type=float, default=0.35, help="most of the time the screen may take (0.35 = 35 %%); the rest is kept for the audio")
    ap.add_argument("--touch", default="auto", help="touchscreen device (/dev/input/eventN) or 'auto'")
    ap.add_argument("--no-touch", action="store_true"); ap.add_argument("--no-gpio", action="store_true")
    ap.add_argument("--no-mouse", action="store_true", help="ignore USB mice (a mouse works as a finger: left click = touch, wheel = jog, hold right = SHIFT)")
    ap.add_argument("--mouse-speed", type=float, default=1.0, help="mouse pointer speed")
    ap.add_argument("--touch-swap", action="store_true", help="swap touch X and Y")
    ap.add_argument("--fit", choices=["auto", "stretch", "letterbox"], default="auto",
                    help="how the 800x480 UI fills the screen: auto (stretch if within 3%% of 5:3 like 1024x600, else keep 5:3 with "
                         "black bars, e.g. 1280x800 -> 1280x768), stretch, or letterbox")
    ap.add_argument("--scale", type=float, default=0, help="draw the UI this many times 800x480 (default: the screen's own size, "
                    "1.6 on a 1280x800 panel; with --shots, 1 unless given)")
    ap.add_argument("--touch-invx", action="store_true"); ap.add_argument("--touch-invy", action="store_true")
    ap.add_argument("--jog-div", type=int, default=1, help="encoder steps per jog click (try 2 or 4 if one click jumps several values)")
    a = ap.parse_args()
    import settingspage as SETP                                     # MENU > SETTINGS (ui.json): used where no flag was typed
    if not a.shots and not a.png:
        sys.stdout = SETP.Tee(sys.stdout); sys.stderr = SETP.Tee(sys.stderr)   # also into logs/monolith.log (bug reports)
        print(f"---- Monolith {SETP.VERSION} starting {time.strftime('%Y-%m-%d %H:%M:%S')}  args: {' '.join(sys.argv[1:])}")
    try: _st = json.load(open(os.path.join(HERE, "ui.json")))
    except Exception: _st = {}
    _df = ap.parse_args([])
    def _from(key, attr, conv=lambda v: v):
        if key in _st and _st[key] not in ("", None) and getattr(a, attr) == getattr(_df, attr): setattr(a, attr, conv(_st[key]))
    _from("audio_out", "device"); _from("audio_in", "in_device"); _from("outs", "outs", int); _from("latency", "latency", str)
    _from("voices", "voices", int); _from("fit", "fit"); _from("touch_swap", "touch_swap", bool); _from("touch_invx", "touch_invx", bool)
    _from("touch_invy", "touch_invy", bool); _from("jog_div", "jog_div", int); _from("mouse_speed", "mouse_speed", float)
    _from("fps", "fps", float)
    if _st.get("studio_on") is False and not a.no_studio: a.no_studio = True
    if _st.get("midi_on") is False and not a.no_midi: a.no_midi = True

    from screens import splash
    fb = None
    if not a.shots:                                                # the screen first, so the logo shows while samples load
        if a.x11:
            fb = XScreen(a.fit); a.no_touch = True                     # X delivers the touches (also to plug-in windows)
        elif not a.png:
            try: fb = Framebuffer(a.fb, a.fit)
            except Exception as ex: print("no framebuffer:", ex, "- use --png screen.png to see the UI")
    t_splash = time.time()
    def show_splash(text, prog):
        img = splash(text, prog, a.scale or ((fb.box[2] / float(W)) if fb else 1.0))
        if fb: fb.show(img)
        if a.png: img.save(a.png)
    show_splash("loading samples and project...", 0.2)
    start = HERE if a.shots else (Engine.last_project(HERE) or HERE)    # the project that was open last time (shots: the demo)
    eng = Engine(start, nout=a.outs, nvoices=a.voices, app_dir=HERE)
    if not eng.sources and start == HERE:
        raise SystemExit("No samples found. Run: python3 make_demo_samples.py")
    ctl = Controls(eng)
    sm = ctl.settings.get("start_machine", "LAST USED")             # SETTINGS: MACHINE AT START
    if sm == "MODERN": eng.machine = "MODERN"
    elif sm == "PICK" and not a.shots: ctl.open_picker()
    scale = a.scale or ((fb.box[2] / float(W)) if fb else 1.0)     # draw at the panel's real size: sharp text, no upscaling
    ren = Renderer(ctl, 1.0 if a.shots and not a.scale else scale)
    if a.shots:
        make_shots(eng, ctl, ren, a.shots); print("screens written to", a.shots); return
    import skin, screens as _scr                                   # every page's parts made now, not while a beat plays
    if not skin.load_cache(ren.scale):
        show_splash("preparing screens (first start after an update)...", 0.3)
        _scr.prewarm(eng, ren.scale, progress=lambda f: show_splash(f"preparing screens... {int(f * 100)}%", 0.3 + 0.45 * f))
        skin.save_cache(ren.scale)
    show_splash(f"{len(eng.sources)} samples loaded - starting audio...", 0.8)

    import sounddevice as sd
    dev = None
    if a.device:
        dev = tuple(int(v) if v.isdigit() else v for v in str(a.device).split(","))
        dev = dev[0] if len(dev) == 1 else dev
    in_stream = None
    lat = float(a.latency) if a.latency.replace(".", "", 1).isdigit() else a.latency
    XRUNS = {"n": 0}                                                # audio dropouts (the sound card ran dry): reported in the log

    def _status(s):
        if s and (s.output_underflow or s.input_overflow): XRUNS["n"] += 1

    def cb_out(o, f, t, s):
        _status(s); o[:] = eng.render(f)

    def cb_duplex(i, o, f, t, s):
        _status(s); o[:] = eng.render(f, i)

    try:
        if a.in_device:                                            # output card has no inputs: record from another device
            ind = int(a.in_device) if a.in_device.isdigit() else a.in_device
            in_stream = sd.InputStream(samplerate=OUT_SR, blocksize=a.block, channels=1, device=ind, latency=lat,
                                       callback=lambda i, f, t, s: eng.feed_input(i))
            stream = sd.OutputStream(samplerate=OUT_SR, blocksize=a.block, channels=a.outs, device=dev, latency=lat, callback=cb_out)
        else:
            stream, err = None, None
            for ich in (2, 1):                                     # IN L + IN R (mixed to mono when recording), else one input
                try:
                    stream = sd.Stream(samplerate=OUT_SR, blocksize=a.block, channels=(ich, a.outs), device=dev, latency=lat,
                                       callback=cb_duplex)
                    break
                except Exception as ex: err = ex
            if stream is None: raise err
    except Exception as ex:                                        # no input device: play-only
        print("no audio input (", ex, ") - recording disabled")
        stream = sd.OutputStream(samplerate=OUT_SR, blocksize=a.block, channels=a.outs, device=dev, latency=lat, callback=cb_out)
    ctl.xruns = XRUNS
    try:
        lo = stream.latency[1] if isinstance(stream.latency, (tuple, list)) else stream.latency
        print(f"audio: {stream.device} at {OUT_SR} Hz, block {a.block}, output latency {lo * 1000:.1f} ms")
        dv = stream.device[1] if isinstance(stream.device, (tuple, list)) else stream.device
        try: dname = sd.query_devices(dv)["name"].split(" (hw:")[0]
        except Exception: dname = str(dv)
        ctl.audio_now = f"{dname}  -  {OUT_SR / 1000:g} kHz  -  {lo * 1000:.0f} ms  -  {a.outs} outs"
    except Exception: pass
    RESTART = {"go": False}
    ctl.restart_fn = lambda: RESTART.__setitem__("go", True)       # SETTINGS > APPLY: leave the loop, then start again
    show_splash("ready", 1.0)
    time.sleep(max(0.0, 1.5 - (time.time() - t_splash)))         # the logo stays up at least 1.5 s
    if not a.no_midi:
        import midi
        midi.MidiIO(ctl, ctl.midi_map).start()
    STUDIO = None
    if not a.no_studio:                                            # Akai MPC Studio (mk1) as the controller, if plugged in
        import studio
        STUDIO = studio.start(ctl)
    if a.keys: threading.Thread(target=keyboard_thread, args=(ctl,), daemon=True).start()
    elif not a.no_arduino:
        port = a.port or next(iter(sorted(glob.glob("/dev/ttyACM*"))), "/dev/ttyACM0")
        LIGHTS["port"] = port
        threading.Thread(target=serial_thread, args=(ctl, port), daemon=True).start()
        threading.Thread(target=lights_thread, args=(eng,), daemon=True).start()
    if a.port2: threading.Thread(target=serial_thread, args=(ctl, a.port2), daemon=True).start()
    if not a.no_mouse and not a.x11 and not a.shots:                # X11 has its own pointer
        threading.Thread(target=inputs.mouse_thread, args=(ctl, a.mouse_speed), daemon=True).start()   # (sets ctl.mouse_mapper)
    if not a.no_touch and not a.keys:
        threading.Thread(target=inputs.touch_thread, args=(ctl, a.touch), daemon=True,
                         kwargs=dict(swap=a.touch_swap, invx=a.touch_invx, invy=a.touch_invy,
                                     box=fb.frac_box() if fb else None)).start()
    if not a.no_gpio and not a.keys and not a.no_arduino:
        try: inputs.gpio_start(ctl, jog_div=a.jog_div)
        except Exception as ex: print("no GPIO (D-pad/OK/jog disabled):", ex)

    if in_stream: in_stream.start()
    with stream:
        try:
            nxt = 0.0
            sys.setswitchinterval(0.002)                             # the audio thread gets Python's attention sooner (default 5 ms)
            import gc
            gc.collect(); gc.freeze()                                # everything loaded so far is never scanned again
            gc.disable()                                             # no surprise full collections mid-beat: small ones below
            gc_t = time.time()
            while True:
                if a.x11: fb.pump(ctl)                                   # 60 Hz: touch, plug-in window timers and events
                now = time.time()
                if now >= nxt:
                    t0 = time.perf_counter()
                    img = ren.frame()
                    fast_ptr = isinstance(fb, Framebuffer)              # the framebuffer moves the pointer by itself (below)
                    if not fast_ptr: inputs.draw_pointer(img, getattr(ctl, "mouse", None), ren.img.size[0] / float(W))
                    if fast_ptr: fb.show(img, getattr(ctl, "mouse", None))
                    elif fb: fb.show(img)
                    if a.png: img.save(a.png)
                    cost = time.perf_counter() - t0
                    ctl.frame_ms = cost * 1000.0
                    # the screen may use at most --ui-share of the time: a slow Pi draws fewer frames instead of starving the audio
                    nxt = now + max(1.0 / a.fps, cost / max(0.05, a.ui_share))
                if XRUNS["n"] != XRUNS.get("shown", 0) and now - XRUNS.get("t", 0) > 5:
                    print(f"audio dropouts: {XRUNS['n']} so far ({XRUNS['n'] - XRUNS.get('shown', 0)} in the last few seconds)")
                    XRUNS["shown"], XRUNS["t"] = XRUNS["n"], now
                if RESTART["go"]: break
                if time.time() - gc_t > 0.5:                         # young objects only: well under a millisecond
                    gc.collect(0); gc_t = time.time()
                    if not eng.playing and time.time() - XRUNS.get("full", 0) > 60:
                        gc.collect(1); XRUNS["full"] = time.time()   # the bigger clean-up only while stopped
                mouse = getattr(ctl, "mouse", None)
                if isinstance(fb, Framebuffer) and mouse is not None:
                    fb.pointer(mouse, fb.box[2] / float(W))          # cheap: a few hundred bytes, every loop
                wait = max(0.001, nxt - time.time())
                time.sleep(min(wait, 1.0 / 60) if (a.x11 or mouse is not None) else wait)
        except KeyboardInterrupt:
            eng.save_project(); print("bye"); return
    if RESTART["go"]:                                                # the sound is stopped (the stream is closed): start again
        print("restarting to apply the settings..."); sys.stdout.flush()
        if in_stream:
            try: in_stream.close()
            except Exception: pass
        if STUDIO is not None and getattr(STUDIO, "dev", None) is not None:   # hand the Studio's USB back before starting again
            try:
                import usb.util
                d_ = STUDIO.dev; STUDIO.dev = None; usb.util.dispose_resources(d_)
            except Exception: pass
        os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    main()
