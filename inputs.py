"""
inputs.py - touchscreen, directional arrows and jog wheel for Monolith.

Touchscreen : any Linux touchscreen that shows up as an evdev device (HDMI LCDs with USB touch, DSI, SPI TFTs).
D-pad+OK+jog: wired straight to the Pi's GPIO header (BCM numbers below), read with gpiozero.
Both feed the same Controls object the Arduino pads use.
"""
import threading, time

from uicore import W, H

# BCM GPIO numbers. Wire each switch between the pin and GND (internal pull-ups are used).
# GPIO 2-4 and 18-27 are kept free for the HiFiBerry DAC8x + ADC8x (audio data, clocks and their I2C).
PINS = {"up": 5, "down": 6, "left": 13, "right": 12, "ok": 16,  # D-pad + centre OK key
        "jog_a": 17, "jog_b": 10, "jog_push": 9,                 # jog encoder A, B and push switch (10 / 9 are SPI pins: leave SPI off)
        "song": 11}                                              # the SONG screen key (the Arduino's 24 key inputs are full)
DAC8X_PINS = {2, 3, 4} | set(range(18, 28))

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y, ABS_MT_X, ABS_MT_Y, ABS_MT_ID, BTN_TOUCH = 0, 1, 53, 54, 57, 330


class TouchMapper:
    """Turns raw evdev touch events into Controls.touch('down'|'move'|'up', x, y) calls on a 480x320 screen."""
    def __init__(self, ctl, xrange_, yrange_, swap=False, invx=False, invy=False, w=W, h=H, box=None):
        self.ctl, self.xr, self.yr = ctl, xrange_, yrange_
        self.swap, self.invx, self.invy, self.w, self.h = swap, invx, invy, w, h
        self.box = box                      # (x0, y0, x1, y1) fractions of the screen that hold the UI (letterbox mode)
        self.rx = self.ry = None
        self.active = self.touching = False
        self.last = None

    def event(self, etype, code, value):
        if etype == EV_ABS:
            if code in (ABS_X, ABS_MT_X): self.rx = value
            elif code in (ABS_Y, ABS_MT_Y): self.ry = value
            elif code == ABS_MT_ID: self.active = value >= 0
        elif etype == EV_KEY and code == BTN_TOUCH:
            self.active = bool(value)
        elif etype == EV_SYN and code == 0:
            self.flush()

    def pos(self):
        rx, ry, xr, yr = self.rx, self.ry, self.xr, self.yr
        if self.swap:
            rx, ry, xr, yr = ry, rx, yr, xr
        fx = (rx - xr[0]) / float(max(1, xr[1] - xr[0]))
        fy = (ry - yr[0]) / float(max(1, yr[1] - yr[0]))
        if self.invx: fx = 1.0 - fx
        if self.invy: fy = 1.0 - fy
        if self.box:
            fx = (fx - self.box[0]) / max(1e-6, self.box[2] - self.box[0])
            fy = (fy - self.box[1]) / max(1e-6, self.box[3] - self.box[1])
        return int(max(0.0, min(1.0, fx)) * (self.w - 1)), int(max(0.0, min(1.0, fy)) * (self.h - 1))

    def flush(self):
        if self.active and self.rx is not None and self.ry is not None:
            p = self.pos()
            if not self.touching:
                self.touching = True; self.last = p; self.ctl.touch("down", *p)
            elif p != self.last:
                self.last = p; self.ctl.touch("move", *p)
        elif self.touching and not self.active:
            self.touching = False
            self.ctl.touch("up", *(self.last or (0, 0)))
            self.rx = self.ry = None


EV_REL, REL_X, REL_Y, REL_WHEEL, BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 2, 0, 1, 8, 272, 273, 274


class MouseMapper:
    """A USB mouse as a finger, for testing on an ordinary HDMI monitor (no X11 needed):
    left button = touch (drag = slide), wheel = jog wheel, right button = SHIFT (held, like the SHIFT key).
    The pointer is kept in UI units; the main loop draws it (pointer_visible / pos)."""
    def __init__(self, ctl, speed=1.0, w=W, h=H):
        self.ctl, self.speed, self.w, self.h = ctl, speed, w, h
        self.x, self.y = w / 2.0, h / 2.0
        self.down = False
        self.moved = False
        self.seen = 0.0                                        # last time the mouse did anything (the pointer hides after a while)
        ctl.mouse = self

    def pos(self): return int(self.x), int(self.y)

    def pointer_visible(self, idle=6.0): return time.time() - self.seen < idle

    def event(self, etype, code, value):
        if etype == EV_REL:
            if code == REL_X: self.x = max(0.0, min(self.w - 1.0, self.x + value * self.speed)); self.moved = True
            elif code == REL_Y: self.y = max(0.0, min(self.h - 1.0, self.y + value * self.speed)); self.moved = True
            elif code == REL_WHEEL and value: self.ctl.jog(1 if value < 0 else -1)          # wheel down = jog right / value down
            self.seen = time.time()
        elif etype == EV_KEY:
            self.seen = time.time()
            if code == BTN_LEFT:
                self.down = bool(value)
                self.ctl.touch("down" if value else "up", *self.pos())
            elif code == BTN_RIGHT:
                self.ctl.shift = bool(value)
        elif etype == EV_SYN and code == 0 and self.moved:
            self.moved = False
            if self.down: self.ctl.touch("move", *self.pos())


def mouse_thread(ctl, speed=1.0):
    """finds a USB mouse (plugged in now or later) and feeds it to MouseMapper"""
    from evdev import InputDevice, ecodes, list_devices
    m = MouseMapper(ctl, speed)
    ctl.mouse_mapper = m                                            # SETTINGS > MOUSE SPEED changes m.speed live
    while True:
        try:
            dev = None
            for p in list_devices():
                d = InputDevice(p)
                caps = d.capabilities()
                if ecodes.EV_REL in caps and REL_X in caps[ecodes.EV_REL] and BTN_LEFT in caps.get(ecodes.EV_KEY, []):
                    dev = d; break
            if dev is None:
                time.sleep(3); continue
            ctl.e.say("mouse: " + dev.name[:28])
            m.seen = time.time()
            for ev in dev.read_loop():
                m.event(ev.type, ev.code, ev.value)
        except Exception as ex:
            print("mouse:", ex); time.sleep(3)


POINTER_SIZE = (16, 24)                                     # the arrow's bounding box in layout units (with its outline)


def draw_pointer(img, mouse, scale, origin=(0, 0)):
    """an arrow pointer on the finished frame (img is scale x the 800 x 500 UI, or a patch of it starting at origin)"""
    if mouse is None or not mouse.pointer_visible(): return
    from PIL import ImageDraw
    x, y = mouse.x * scale - origin[0], mouse.y * scale - origin[1]
    k = scale * 1.15
    pts = [(0, 0), (0, 17), (4.5, 13), (7.5, 20), (10.5, 18.8), (7.5, 12), (13, 12)]
    poly = [(x + px * k, y + py * k) for px, py in pts]
    d = ImageDraw.Draw(img)
    d.polygon(poly, fill=(255, 255, 255), outline=(0, 0, 0))
    d.line(poly + [poly[0]], fill=(0, 0, 0), width=max(1, int(round(scale))))


def touch_thread(ctl, path="auto", **opts):
    from evdev import InputDevice, ecodes, list_devices
    while True:
        try:
            dev = None
            if path != "auto":
                dev = InputDevice(path)
            else:
                for p in list_devices():
                    d = InputDevice(p)
                    caps = d.capabilities()
                    if ecodes.EV_ABS in caps and ecodes.EV_KEY in caps:
                        codes = [c[0] if isinstance(c, tuple) else c for c in caps[ecodes.EV_ABS]]
                        if ABS_X in codes or ABS_MT_X in codes:
                            dev = d; break
            if dev is None:
                time.sleep(3); continue
            info = dict(dev.capabilities(absinfo=True)[ecodes.EV_ABS])
            xi = info.get(ABS_MT_X) or info.get(ABS_X); yi = info.get(ABS_MT_Y) or info.get(ABS_Y)
            m = TouchMapper(ctl, (xi.min, xi.max), (yi.min, yi.max), **opts)
            ctl.e.say("touchscreen: " + dev.name[:24])
            for ev in dev.read_loop():
                m.event(ev.type, ev.code, ev.value)
        except Exception as ex:
            print("touch:", ex); time.sleep(3)


def gpio_start(ctl, pins=None, jog_div=1, factory=None):
    """Wire arrows + jog encoder to Controls. `factory` lets tests inject fake Button/RotaryEncoder classes."""
    pins = pins or PINS
    if factory is None:
        from gpiozero import Button, RotaryEncoder
    else:
        Button, RotaryEncoder = factory
    keep = []
    for name in ("up", "down", "left", "right"):
        b = Button(pins[name], pull_up=True, bounce_time=0.02, hold_time=0.4, hold_repeat=True)
        b.when_pressed = lambda n=name: ctl.nav(n)
        b.when_held = lambda n=name: ctl.nav(n)
        keep.append(b)
    okb = Button(pins["ok"], pull_up=True, bounce_time=0.02)
    okb.when_pressed = lambda: ctl.ok()
    keep.append(okb)
    if "song" in pins:
        sb = Button(pins["song"], pull_up=True, bounce_time=0.02)
        sb.when_pressed = lambda: ctl.set_mode("SONG")
        keep.append(sb)
    push = Button(pins["jog_push"], pull_up=True, bounce_time=0.02)
    push.when_pressed = lambda: ctl.jog_press()
    enc = RotaryEncoder(pins["jog_a"], pins["jog_b"], max_steps=0)
    acc = {"n": 0}
    def turned(direction):
        acc["n"] += direction
        if abs(acc["n"]) >= jog_div:
            ctl.jog(1 if acc["n"] > 0 else -1); acc["n"] = 0
    enc.when_rotated_clockwise = lambda: turned(1)
    enc.when_rotated_counter_clockwise = lambda: turned(-1)
    keep += [push, enc]
    return keep
