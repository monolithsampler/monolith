"""
settingspage.py - MENU > SETTINGS: what used to be start-up flags (start.sh / sampler_os.py --options), on a page.

Settings belong to this Pi, not to a project: they live in ui.json beside the software. sampler_os.py reads them at
start-up (a flag typed on the command line still wins). Changes that need the sound or the controllers started again
(audio device, outputs, latency, voices, the Studio / MIDI on or off, the screen and touch) are saved at once but only
take effect on APPLY, which restarts Monolith (after asking to save). Everything else takes effect straight away.
"""
import os, time, json, socket, shutil

VERSION = "0.9.0"                                     # shown in ABOUT and written into bug-report logs
EDITION = "Studio edition"

SECTIONS = ["AUDIO", "CONTROLLERS", "DISPLAY + TOUCH", "GENERAL", "ABOUT"]

DEFAULTS = {"audio_out": "", "audio_in": "", "outs": 2, "latency": "0.016", "voices": 16,
            "studio_on": True, "studio_screen": True, "vel_curve": "SOFT", "midi_on": True, "jog_div": 1, "mouse_speed": 1.0,
            "fit": "auto", "touch_swap": False, "touch_invx": False, "touch_invy": False, "fps": 15,
            "start_machine": "LAST USED", "autosave": "OFF"}

# the pad velocity curves (Studio pads, MIDI pads, the panel): out = 127 * (in / 127) ** power
VEL_CURVES = {"SOFTER": 0.5, "SOFT": 0.72, "LINEAR": 1.0, "HARD": 1.4}

RESTART = {"audio_out", "audio_in", "outs", "latency", "voices", "studio_on", "midi_on", "fit", "touch_swap", "touch_invx",
           "touch_invy", "fps"}


def vel(curve, v):
    """a pad's velocity through the chosen curve (1-127 stays 1-127)"""
    if v <= 0: return 0
    p = VEL_CURVES.get(curve, 1.0)
    return max(1, min(127, int(round(127.0 * (v / 127.0) ** p))))


def audio_devices(kind="out"):
    """[(label, value)]: the sound cards sounddevice sees, by name (numbers change when cards come and go)"""
    out = [("AUTOMATIC (start.sh picks)", "")] if kind == "out" else [("SAME AS THE OUTPUT", "")]
    try:
        import sounddevice as sd
        key = "max_output_channels" if kind == "out" else "max_input_channels"
        seen = set()
        for d in sd.query_devices():
            n = d["name"].split(" (hw:")[0].strip()
            if d[key] > 0 and n not in seen: seen.add(n); out.append((n, n))
    except Exception: pass
    return out


class Row:
    def __init__(self, key, name, kind, options=None, new=False, info=None, action=None):
        self.key, self.name, self.kind, self.options, self.new, self.info, self.action = key, name, kind, options or [], new, info, action


def rows(c, sec):
    """the rows of one section. kind: seg (a row of keys), list (jog / arrows step through it), info, key (a button)"""
    e = c.e
    if sec == "AUDIO":
        return [Row("audio_out", "OUTPUT", "list", audio_devices("out")),
                Row("audio_in", "INPUT", "list", audio_devices("in")),
                Row("outs", "OUTPUTS", "seg", [("2", 2), ("4", 4), ("8", 8)]),
                Row("latency", "LATENCY", "seg", [("LOW 8 MS", "0.008"), ("NORMAL 16 MS", "0.016"), ("SAFE 32 MS", "0.032")]),
                Row("voices", "VOICES", "seg", [("16", 16), ("24", 24), ("32", 32)])]
    if sec == "CONTROLLERS":
        return [Row("studio_on", "MPC STUDIO", "seg", [("ON", True), ("OFF", False)]),
                Row("studio_screen", "STUDIO SCREEN", "seg", [("ON", True), ("OFF", False)]),
                Row("vel_curve", "PAD VELOCITY", "seg", [(k, k) for k in VEL_CURVES], new=True),
                Row("midi_on", "OTHER USB MIDI", "seg", [("ON", True), ("OFF", False)]),
                Row("jog_div", "JOG STEPS / CLICK", "seg", [("1", 1), ("2", 2), ("4", 4)]),
                Row("mouse_speed", "MOUSE SPEED", "seg", [("SLOW", 0.6), ("NORMAL", 1.0), ("FAST", 1.8)])]
    if sec == "DISPLAY + TOUCH":
        return [Row("fit", "SCREEN FIT", "seg", [("AUTO", "auto"), ("STRETCH", "stretch"), ("LETTERBOX", "letterbox")]),
                Row("touch_swap", "TOUCH: SWAP X / Y", "seg", [("OFF", False), ("ON", True)]),
                Row("touch_invx", "TOUCH: FLIP X", "seg", [("OFF", False), ("ON", True)]),
                Row("touch_invy", "TOUCH: FLIP Y", "seg", [("OFF", False), ("ON", True)]),
                Row("fps", "SCREEN RATE", "seg", [("10 FPS", 10), ("15 FPS", 15), ("20 FPS", 20)])]
    if sec == "GENERAL":
        return [Row("start_machine", "MACHINE AT START", "seg", [("LAST USED", "LAST USED"), ("MODERN", "MODERN"), ("PICK", "PICK")]),
                Row("autosave", "AUTOSAVE", "seg", [("OFF", "OFF"), ("EVERY 5 MIN", "5MIN"), ("ON STOP", "STOP")], new=True),
                Row("_metro", "METRONOME", "seg", [("OFF", False), ("ON", True)]),
                Row("_count_in", "COUNT-IN", "seg", [("OFF", 0), ("1 BAR", 1), ("2 BARS", 2)]),
                Row("_asr_keys", "ASR KEYS", "seg", [("CLASSIC", False), ("ASR KEYS", True)])]
    return [Row("", "VERSION", "info", info=lambda: f"Monolith {VERSION} ({EDITION})"),
            Row("", "THIS PI", "info", info=this_pi),
            Row("", "STORAGE", "info", info=lambda: storage(c)),
            Row("", "CPU / TEMP", "info", info=lambda: cpu_temp(c)),
            Row("", "BUG REPORT", "key", ["SAVE LOG TO USB"], action=lambda: save_log(c)),
            Row("", "LICENSE", "info", info=lambda: "MIT - see LICENSE")]


def get(c, key):
    e = c.e
    if key == "_metro": return e.metro
    if key == "_count_in": return e.count_in
    if key == "_asr_keys": return c.asr_keys
    return c.settings.get(key, DEFAULTS.get(key))


def put(c, key, value):
    """set a setting: saved at once; live ones act now, restart ones light APPLY"""
    e = c.e
    if key == "_metro": e.metro = bool(value); return
    if key == "_count_in": e.count_in = int(value); return
    if key == "_asr_keys":
        if c.asr_keys != bool(value): c.toggle_asr_keys()
        return
    if c.settings.get(key) == value: return
    c.settings[key] = value
    c._save_ui_setting(key, value)
    if key in RESTART: c.set_pending = True
    elif key == "mouse_speed" and c.mouse_mapper is not None: c.mouse_mapper.speed = float(value)
    elif key == "vel_curve": c.say(f"pad velocity: {value.lower()} (hit a pad to try it)")


def step(c, row, n):
    """change a row by n steps (jog, arrows); lists and keys wrap at the ends"""
    if row.kind not in ("seg", "list") or not row.options: return
    vals = [v for _, v in row.options]
    cur = get(c, row.key)
    k = vals.index(cur) if cur in vals else 0
    k = (k + (1 if n > 0 else -1)) % len(vals) if row.kind == "list" else max(0, min(len(vals) - 1, k + (1 if n > 0 else -1)))
    put(c, row.key, vals[k])


# ------------------------------------------------------------------ ABOUT
def this_pi():
    host = socket.gethostname()
    ip = "no network"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(0.2)
        s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close()             # (nothing is sent)
    except Exception: pass
    return f"{host}.local  -  {ip}  (for scp / ssh)"


def storage(c):
    try:
        free = shutil.disk_usage(c.e.app_dir).free / 1e9
        n = len(c.e.list_projects())
    except Exception: return "-"
    usb = [lab for lab, _, mp, _ in (c.usb_drives() if hasattr(c, "usb_drives") else []) if mp]
    return f"{free:.1f} GB free  -  {n} project{'s' if n != 1 else ''}" + (f"  -  USB: {usb[0]}" if usb else "")


def cpu_temp(c):
    t = "-"
    try: t = f"{int(open('/sys/class/thermal/thermal_zone0/temp').read()) / 1000:.0f} C"
    except Exception: pass
    audio = f"{getattr(c.e, 'cpu', 0.0) * 100:.0f} %"
    scr = f"{getattr(c, 'frame_ms', 0.0):.0f} ms a frame"
    return f"audio {audio}  -  screen {scr}  -  {t}"


LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "monolith.log")


def save_log(c):
    """SAVE LOG TO USB: monolith-log.txt on the first mounted USB drive (or in logs/ when there is none): the version,
    this Pi, the settings, the audio, then the end of the log (messages and errors)"""
    lines = [f"Monolith {VERSION} ({EDITION})  -  {time.strftime('%Y-%m-%d %H:%M:%S')}", this_pi(), cpu_temp(c),
             f"audio now: {c.audio_now or '-'}", f"audio dropouts: {(c.xruns or {}).get('n', 0)}",
             f"machine: {c.e.machine}   project: {c.e.project_name}", "settings: " + json.dumps(c.settings, sort_keys=True), "",
             "---- the end of the log ----"]
    try: lines += open(LOG, errors="replace").read().splitlines()[-600:]
    except Exception: lines.append("(no log yet)")
    usb = [mp for _, _, mp, _ in (c.usb_drives() if hasattr(c, "usb_drives") else []) if mp]
    dest = os.path.join(usb[0] if usb else os.path.dirname(LOG), "monolith-log.txt")
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as f: f.write("\n".join(lines) + "\n")
        try: os.sync()
        except Exception: pass
        c.say(("log saved to the USB drive: " if usb else "no USB drive: log saved in logs/ ") + "monolith-log.txt")
    except Exception as ex: c.say(f"could not save the log: {ex}")
    return dest


class Tee:
    """everything printed (messages and errors) also goes to logs/monolith.log, kept to about 1 MB"""
    def __init__(self, stream, path=LOG, cap=1_000_000):
        self.stream, self.path, self.cap = stream, path, cap
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            if os.path.getsize(path) > cap: os.replace(path, path + ".1")
        except OSError: pass
        self.f = open(path, "a", buffering=1)

    def write(self, s):
        try: self.stream.write(s)
        except Exception: pass
        try:
            if s.strip(): self.f.write(s if s.endswith("\n") else s)
            else: self.f.write(s)
        except Exception: pass
        return len(s)

    def flush(self):
        for f in (self.stream, self.f):
            try: f.flush()
            except Exception: pass

    def isatty(self): return False
