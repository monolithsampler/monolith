"""
asrfx.py - the Ensoniq ASR-10's effects, run on an emulation of their effects chip (dsp/esp.c).

Nothing of the ASR-10 is part of Monolith. Put your own ASR-10 OS ROM files (the two 128 KB EPROM images of OS 1.5B,
any names) in firmware/asr10/ and this reads, at start-up, what the ROM holds for each effect:
  - its effects-chip program (instructions and starting register values) and its table for the chip's memory,
  - its parameters (names, ranges, value texts) and its four presets.
A parameter value becomes chip registers through the ROM's own 68000 routines, run on a 68000 emulation
(dsp/asr68k.c, the Musashi core); the OS entry points they call are answered here the way the OS answers them.
See EMULATION_NOTES.md.
"""
import ctypes, os, re, struct, subprocess, threading
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.join(HERE, "firmware", "asr10")
ROM_BASE = 0xF80000
ESP_RATES = {"30K": 15238090.0 / 512, "44K": 44100.0}

# ---------------------------------------------------------------------------------------------------------- the chip
_lib = None


def _open(name, src):
    """load dsp/<name>, building it first (dsp/build.sh) when it is missing, older than its source, or not for this
    computer"""
    so, src = os.path.join(HERE, "dsp", name), os.path.join(HERE, "dsp", src)
    def build():
        try: subprocess.run(["sh", os.path.join(HERE, "dsp", "build.sh")], check=True, capture_output=True, timeout=900)
        except Exception: pass
    if (not os.path.exists(so) or os.path.getmtime(so) < os.path.getmtime(src)) and os.path.exists(src): build()
    try: return ctypes.CDLL(so)
    except OSError:
        build()
        return ctypes.CDLL(so)


def _load_lib():
    global _lib
    if _lib is not None: return _lib
    lib = _open("libesp.so", "esp.c")
    V, I, U64, I32 = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint64, ctypes.c_int32
    lib.esp_new.restype = V
    lib.esp_free.argtypes = [V]; lib.esp_reset.argtypes = [V]; lib.esp_clear_dram.argtypes = [V]
    lib.esp_set_instr.argtypes = [V, I, U64]
    lib.esp_get_instr.argtypes = [V, I]; lib.esp_get_instr.restype = U64
    lib.esp_write_reg.argtypes = [V, I, I32]
    lib.esp_read_reg.argtypes = [V, I]; lib.esp_read_reg.restype = I32
    lib.esp_write_dram.argtypes = [V, I, I]
    lib.esp_read_dram.argtypes = [V, I]
    lib.esp_snapshot.argtypes = [V, ctypes.POINTER(I32), ctypes.POINTER(U64)]
    lib.esp_process.argtypes = [V, I, ctypes.POINTER(ctypes.c_int16), I, ctypes.POINTER(ctypes.c_int16)]
    _lib = lib
    return lib


class Esp:
    """one effects chip"""
    def __init__(self):
        self.lib = _load_lib()
        self.h = self.lib.esp_new()

    def __del__(self):
        try: self.lib.esp_free(self.h)
        except Exception: pass

    def reset(self): self.lib.esp_reset(self.h)
    def clear_memory(self): self.lib.esp_clear_dram(self.h)
    def set_instr(self, a, ins): self.lib.esp_set_instr(self.h, a, ins)
    def instr(self, a): return self.lib.esp_get_instr(self.h, a)
    def write(self, r, v): self.lib.esp_write_reg(self.h, r, int(v) & 0xffffff)
    def write_memory(self, a, words):
        for k, w in enumerate(words): self.lib.esp_write_dram(self.h, a + k, int(w))
    def read_memory(self, a): return self.lib.esp_read_dram(self.h, a)
    def read(self, r): return self.lib.esp_read_reg(self.h, r)

    def process(self, ser_in, in_mask):
        """ser_in: int16 array (n, 8) in register order SER0R, SER0L, SER1R, SER1L, SER2R, SER2L, SER3R, SER3L"""
        ser_in = np.ascontiguousarray(ser_in, np.int16)
        out = np.zeros_like(ser_in)
        P = ctypes.POINTER(ctypes.c_int16)
        self.lib.esp_process(self.h, len(ser_in), ser_in.ctypes.data_as(P), in_mask, out.ctypes.data_as(P))
        return out


# ---------------------------------------------------------------------------------------------------------- the ROM
def find_rom(folder=FW_DIR):
    """the 256 KB OS ROM from the user's files: two 128 KB EPROM images (high = even bytes, low = odd) or one merged
    image. Returns bytes or None."""
    if not os.path.isdir(folder): return None
    files = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, f))]
    for f in files:
        if os.path.getsize(f) == 0x40000:
            d = open(f, "rb").read()
            if d.find(b"PARAMETER") > 0: return d
    halves = [open(f, "rb").read() for f in files if os.path.getsize(f) == 0x20000]
    if len(halves) == 2:
        for hi, lo in (halves, halves[::-1]):
            r = bytearray(0x40000); r[0::2] = hi; r[1::2] = lo
            if r.find(b"PARAMETER") > 0: return bytes(r)
    return None


class Rom:
    def __init__(self, data):
        self.d = data

    def u8(self, a): return self.d[a - ROM_BASE]
    def u16(self, a): return struct.unpack(">H", self.d[a - ROM_BASE:a - ROM_BASE + 2])[0]
    def s16(self, a): return struct.unpack(">h", self.d[a - ROM_BASE:a - ROM_BASE + 2])[0]
    def u32(self, a): return struct.unpack(">I", self.d[a - ROM_BASE:a - ROM_BASE + 4])[0]
    def bytes(self, a, n): return self.d[a - ROM_BASE:a - ROM_BASE + n]

    def cstr(self, a, maxlen=40):
        b = self.bytes(a, maxlen); i = b.find(b"\0")
        return (b if i < 0 else b[:i]).decode("latin1")

    def table(self, a, n=128):
        return np.frombuffer(self.bytes(a, 2 * n), ">u2").astype(np.int64)


# ---------------------------------------------------------------------------------------------------------- effects
class Param:
    """one effect parameter. Types (byte 1 of its descriptor): 00/02 = 0..n, 01/03 = signed, 17 = a 16-bit value,
    0E = a choice from a list of texts, 1C = a modulation destination (one of the effect's parameters)"""
    def __init__(self, ident, ptype, r1, r2, off, name, actions, addr=0, choices=None, suffix=""):
        self.ident, self.ptype, self.off, self.name, self.actions, self.addr = ident, ptype, off, name, actions, addr
        self.word = ptype == 0x17
        self.signed = ptype in (0x01, 0x03)
        self.choices, self.suffix = choices, suffix
        sb = lambda v: v - 256 if v > 127 else v
        if choices: self.lo, self.hi = 0, len(choices) - 1
        elif self.word: self.lo, self.hi = 0, (r1 << 8) | r2
        elif self.signed: self.lo, self.hi = sb(r1), sb(r2)
        else: self.lo, self.hi = r1, r2

    def fmt(self, v):
        v = int(v)
        if self.choices: return self.choices[max(0, min(len(self.choices) - 1, v))].strip() + self.suffix
        return f"{v:+d}" if self.signed and v else f"{v}"

    def __repr__(self): return f"<{self.name} {self.lo}..{self.hi} @{self.off}>"


# the number of argument bytes each parameter action takes (a function of the bytes, for the variable ones)
def _arglen(kind, b):
    if kind in (0x01, 0x0b, 0x10, 0x14, 0x16, 0x19): return 1
    if kind in (0x02, 0x08, 0x0a, 0x0e, 0x0f, 0x11, 0x12, 0x17): return 2
    if kind in (0x07, 0x0c, 0x0d, 0x18): return 3
    if kind == 0x15: return 5
    if kind == 0x13: return 4
    if kind == 0x06: return 6 if b[3] else 3
    if kind in (0x03, 0x05):
        n = 2                                   # GPR, second GPR (0 = none)
        n += 1                                  # flag
        if b[2]: n += 3 + 3                     # GPR, min, max, then three GPRs
        return n
    return None


class Effect:
    def __init__(self, rom, s):
        self.rom, self.s = rom, s
        self.name = rom.bytes(s + 10, 24)[0::2].decode("latin1").strip()
        self.length = rom.u32(s + 0x22)
        e = s + rom.u16(s + 0x26)
        if rom.u8(e) != 0x45 and rom.u8(e - 2) == 0x45: e -= 2
        self.eblock = e
        self.code = rom.u32(s + 0x28)
        self.modcode = rom.u16(s + 0x2c)
        self.preset_offs = [rom.u16(s + 0x2e + 2 * k) for k in range(4)]
        pt = s + rom.u16(s + 0x38)
        self.ptable = next((a for a in (pt, pt + 2, pt - 2) if rom.u16(a) == 0x000E), pt)
        self.program, self.gpr_init, self.reg_init, self.n_instr = self._program()
        self.dst_base = 0
        self.params = self._params()
        self.preset_names = self._preset_names()

    def _program(self):
        """the 'E' block: groups of [type, count, first register] - 1: GPR + instruction pairs, 2: instructions,
        3: GPR values, 4: (register, value) pairs; 0xFF ends (the ROM's loader at F973F0)"""
        r, e = self.rom, self.eblock
        n_instr = r.u8(e + 6)
        p = e + 8
        prog, gprs, regs = {}, {}, []
        while True:
            t = r.u8(p); p += 1
            if t == 0xFF or t == 0 or t > 4: break
            cnt, reg = r.u8(p), r.u8(p + 1); p += 2
            for k in range(cnt):
                if t == 1:
                    gprs[reg + k] = int.from_bytes(r.bytes(p, 3), "big"); prog[reg + k] = int.from_bytes(r.bytes(p + 3, 6), "big"); p += 9
                elif t == 2:
                    prog[reg + k] = int.from_bytes(r.bytes(p, 6), "big"); p += 6
                elif t == 3:
                    gprs[reg + k] = int.from_bytes(r.bytes(p, 3), "big"); p += 3
                else:
                    rr = r.u8(p); regs.append((rr, int.from_bytes(r.bytes(p + 1, 3), "big"))); p += 4
        return prog, gprs, regs, n_instr

    def _params(self):
        """the parameters, in the order the effect lists them (a table of descriptor offsets just before the parameter
        header). Each descriptor: id, type, range (2 bytes), offset of its value in a preset, name offset, then its
        actions (kind + arguments, ending with 0) - which the ROM's own routines carry out (apply_params)."""
        r, s = self.rom, self.s
        lst = s + r.u16(s + 0x36)
        offs = []
        a = lst
        while a < self.ptable and len(offs) < 48:
            offs.append(r.u16(a)); a += 2
        out, prev = [], ""
        for o in offs[1:]:
            p = s + o
            if not (s < p < s + self.length): continue
            ident, ptype, r1, r2, off, nameo = r.u8(p), r.u8(p + 1), r.u8(p + 2), r.u8(p + 3), r.u16(p + 4), r.u16(p + 6)
            raw = self._name_at(nameo)
            parts = re.split(r"[\x00-\x1f\x7f-\xff]", raw)
            nm = parts[0].rstrip()
            suffix = parts[1] if len(parts) > 1 and parts[1] and parts[1].isprintable() else ""
            short = nm.startswith(" ") or not nm             # shown beside the one before it ("BASS FC" / " GAIN")
            if short:
                w = nm.strip()
                nm = (prev.rsplit(" ", 1)[0] + " " + w) if (w and " " in prev) else (w or (prev + " AMT"))
            else:
                prev = nm
            choices = None
            t = s + ((r1 << 8) | r2)
            try:
                if ptype == 0x0E:                           # [u32 text address (or offset in the effect)][width][count]
                    ptr, width, count = r.u32(t), r.u8(t + 4), r.u8(t + 5)
                    ptr = ptr & 0xffffff if ptr >= ROM_BASE else s + ptr
                    choices = [r.bytes(ptr + k * width, width).decode("latin1") for k in range(count)]
                elif ptype == 0x1C:                         # [u16 count][u16 name offsets]
                    choices = [r.cstr(s + r.u16(t + 2 + 2 * k)) for k in range(r.u16(t))]
                if choices is not None and not all(c.strip() and c.isprintable() for c in choices): choices = None
            except Exception:
                choices = None
            out.append(Param(ident, ptype, r1, r2, off, nm, [(r.u8(p + 8), b"")], p, choices, suffix))
            out[-1].short = short
        # the modulation destination list holds the full names the ASR-10 uses for the parameters ("ER LEV2"): use them
        dst = next((q.choices for q in out if q.ptype == 0x1C and q.choices), None)
        if dst:
            names = [d.strip() for d in dst]
            o = next((k for k, q in enumerate(out) if q.name == names[0]), None)
            if o is not None and o + len(names) <= len(out):
                self.dst_base = o
                for k, full in enumerate(names):
                    q = out[o + k]
                    if q.short or full.split(" ")[0] == q.name.split(" ")[0]: q.name = full
        return out

    def _name_at(self, o):
        """a parameter name: the offset is from the section start (some sections count from 2 bytes later)"""
        for a in (self.s + o, self.s + o + 2):
            if self.rom.u8(a - 1) == 0 and 32 <= self.rom.u8(a) < 127: return self.rom.cstr(a)
        return self.rom.cstr(self.s + o)

    def _preset_names(self):
        """the four preset names: fixed-width fields "1 NAME", "2 NAME"... (17 or 18 characters each), kept just before
        the preset values in later effects, after the parameter table in earlier ones"""
        d = self.rom.d
        lo, hi = self.s - ROM_BASE, self.s + self.length - ROM_BASE
        first = self.s + min(self.preset_offs) - ROM_BASE
        for start in (first - 72, first - 68, self.ptable - ROM_BASE):
            i = d.find(b"1 ", max(lo, start), hi)
            while 0 < i < hi:
                for w in (17, 18, 16, 19):
                    if all(d[i + k * w:i + k * w + 1] == str(k + 1).encode() for k in range(4)):
                        names = [d[i + k * w + 1:i + (k + 1) * w].decode("latin1").strip() for k in range(4)]
                        if all(n and all(32 <= ord(c) < 127 for c in n) for n in names): return names
                i = d.find(b"1 ", i + 1, hi)
        return []

    def preset(self, k):
        """the preset's parameter values as {param index: value}"""
        base = self.s + self.preset_offs[k]
        vals = {}
        for i, pr in enumerate(self.params):
            if pr.word: vals[i] = self.rom.s16(base + pr.off) if False else self.rom.u16(base + pr.off)
            else:
                v = self.rom.u8(base + pr.off)
                vals[i] = v - 256 if (pr.signed and v > 127) else v
        return vals

    def table(self):
        """the table the OS writes into the chip's memory before the effect runs (a waveshaping curve etc.): ROM
        field s+28: 0 = none, 8000+k = shared table k (a pointer list at FB57DA), else an offset in the section.
        A table is [u16 length in bytes][u16 start word address][16-bit words] (the OS's routine at F977DC)."""
        a = self.rom.u16(self.s + 0x28)
        if not a: return None
        p = self.rom.u32(0xFB57DA + ((a << 2) & 0xffff)) & 0xffffff if a & 0x8000 else self.s + a
        n, start = self.rom.u16(p), self.rom.u16(p + 2)
        words = np.frombuffer(self.rom.bytes(p + 4, n), ">i2").astype(np.int32)
        return start, words

    def fmt(self, i, values):
        """a parameter's value as the ASR-10 shows it. A modulation range (MIN1 / MAX1...) is in the units of the
        parameter it modulates (stored as a word: a byte parameter's value sits in the high byte)."""
        p = self.params[i]
        v = int(values.get(i, 0))
        m = re.fullmatch(r"(MIN|MAX)(\d)", p.name)
        if m:
            d = next((k for k, q in enumerate(self.params) if q.name == "DST" + m.group(2)), None)
            if d is not None:
                t = self.dst_base + int(values.get(d, 0))
                if 0 <= t < len(self.params):
                    q = self.params[t]
                    if q.word: return q.fmt(v)
                    b = (v >> 8) & 0xff
                    return q.fmt(b - 256 if (q.signed and b > 127) else b)
        return p.fmt(v)

    def rate(self):
        return "44K" if ("44K" in self.name or any(k == 0x18 for p in self.params for k, _ in p.actions)) else "30K"


def load_effects(rom):
    """every effect in the ROM, in its order (name -> Effect)"""
    d = rom.d
    out, i = {}, 0
    while True:
        i = d.find(b"\x02\x88\x00\x00\x00", i)
        if i < 0: break
        s = ROM_BASE + i - 4
        if d[i - 4:i - 2] == b"\x00\x00" and d[i + 6] >= 0x20:
            try:
                fx = Effect(rom, s)
                if fx.name and fx.program: out[fx.name] = fx
            except Exception:
                pass
        i += 6
    return out


# ---------------------------------------------------------------------------------------------------------- the 68000
# Where the OS keeps the routine for each kind of parameter action (the table sits in the OS disk's RAM image; these
# are its entries: ROM addresses of the routines). Kind 4 points into RAM code that is not in the ROM; kind 0 ends a list.
HANDLERS = {0x01: 0xF9787C, 0x02: 0xF978F4, 0x03: 0xF9792C, 0x05: 0xF97922, 0x06: 0xF97982, 0x07: 0xF979CC,
            0x08: 0xF978B0, 0x09: 0xF97A0A, 0x0A: 0xF97A2C, 0x0B: 0xF97A4E, 0x0C: 0xF97A66, 0x0D: 0xF97A74,
            0x0E: 0xF978C6, 0x0F: 0xF978DE, 0x10: 0xF97A86, 0x11: 0xF97AAE, 0x12: 0xF97AA0, 0x13: 0xF97AF0,
            0x14: 0xF97B10, 0x15: 0xF979F4, 0x16: 0xF9788A, 0x17: 0xF978E4, 0x18: 0xF979E0, 0x19: 0xF9789C,
            0x1A: 0xFB78BE, 0x1B: 0xFB78C4, 0x1C: 0xFB792C, 0x1D: 0xFB799C}
RAM_FX = 0x10000                  # where the effect's data is copied (the routines read and change it there)
RAM_FLAG_ON = 0x0008              # the OS's "effects on" byte the routines test
RAM_SCRATCH = 0x1488              # a work area some routines are handed (A4)

_cpu = None
CPU_LOCK = threading.RLock()       # one 68000 serves every loaded effect (UI edits and the audio thread's ticks)


class Cpu:
    """the 68000 that runs the ROM's parameter routines (dsp/asr68k.c on the Musashi core)"""
    def __init__(self, rom):
        lib = _open("libasr68k.so", "asr68k.c")
        P8, I, U = ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_uint
        lib.asr68k_init.argtypes = [ctypes.c_char_p, I, ctypes.POINTER(U), I]
        lib.asr68k_poke.argtypes = [I, ctypes.c_char_p, I]
        lib.asr68k_peek.argtypes = [I, P8, I]
        lib.asr68k_set_mirror.argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_uint64)]
        lib.asr68k_call.argtypes = [U, ctypes.POINTER(U), I]
        lib.asr68k_result.argtypes = [I, ctypes.POINTER(I), ctypes.POINTER(I), ctypes.POINTER(ctypes.c_int64)]
        lib.asr68k_stop_pc.restype = U
        table = (U * 30)(*[HANDLERS.get(k, 0) for k in range(30)])
        if lib.asr68k_init(rom.d, len(rom.d), table, 30) != 0: raise RuntimeError("not an ASR-10 ROM image")
        self.lib, self.rom = lib, rom
        self.gpr = (ctypes.c_int32 * 0xc0)()
        self.instr = (ctypes.c_uint64 * 160)()

    def poke(self, a, data): self.lib.asr68k_poke(a, bytes(data), len(data))

    def peek(self, a, n):
        buf = (ctypes.c_uint8 * n)()
        self.lib.asr68k_peek(a, buf, n)
        return bytes(buf)

    def mirror_chip(self, esp):
        """the routines see the chip as it is now"""
        esp.lib.esp_snapshot(esp.h, self.gpr, self.instr)
        self.lib.asr68k_set_mirror(self.gpr, self.instr)

    def mirror(self, gpr, instr):
        for k in range(0xc0): self.gpr[k] = gpr.get(k, 0)
        for k in range(160): self.instr[k] = instr.get(k, 0)
        self.lib.asr68k_set_mirror(self.gpr, self.instr)

    def call(self, pc, regs):
        """regs: list of 15 (D0-D7, A0-A6). Returns (writes, regs after, finished)"""
        r = (ctypes.c_uint * 15)(*[int(v) & 0xffffffff for v in regs])
        n = self.lib.asr68k_call(pc, r, 200000)
        done = n >= 0
        if n < 0: n = -1 - n
        out = []
        k, g, v = ctypes.c_int(), ctypes.c_int(), ctypes.c_int64()
        for i in range(n):
            self.lib.asr68k_result(i, ctypes.byref(k), ctypes.byref(g), ctypes.byref(v))
            out.append((k.value, g.value, v.value))
        return out, list(r), done


def cpu(rom):
    global _cpu
    if _cpu is None or _cpu.rom is not rom: _cpu = Cpu(rom)
    return _cpu


RAM_FX_PTR = 0x0E92               # where the OS keeps the address of the loaded effect (some routines read it)
# the controllers the effects' modulation reads (ROM table FB63D6: source -> offset from A4 = $1488). Values are words,
# 0..0x7F00 (a 7-bit controller value in the high byte).
MOD_SOURCES = ("WHEEL", "PBEND", "PRESS", "PEDAL", "XCTRL", "KBD", "VEL", "KEYDN", "SUSTN", "FSW-L", "PATCH", "OFF")
MOD_OFFSET = {"WHEEL": 0x0a, "PBEND": 0x08, "PRESS": 0x16, "PEDAL": 0x10, "XCTRL": 0x0e, "KBD": 0x1a, "VEL": 0x18,
              "KEYDN": 0x1c, "SUSTN": 0x14, "FSW-L": 0x1e, "PATCH": 0x0c}


class FxState:
    """what the OS keeps for a loaded effect: its data copy in RAM (the routines and the modulation change the values
    there), and the chip it drives (read back by the routines, as on the machine)"""
    def __init__(self, fx, preset, values, esp=None):
        self.fx, self.preset, self.esp = fx, preset & 3, esp
        ram = bytearray(fx.rom.bytes(fx.s, min(fx.length, 0x8000)))
        ram[0x63] = self.preset
        base = fx.preset_offs[self.preset]
        for i, p in enumerate(fx.params):                    # the values go into the preset's slots
            v = int(values.get(i, 0))
            if p.word: ram[base + p.off:base + p.off + 2] = struct.pack(">H", v & 0xffff)
            else: ram[base + p.off] = v & 0xff
        self.ram = ram
        self.controllers = {}

    def set_value(self, i, v):
        p = self.fx.params[i]; o = self.fx.preset_offs[self.preset] + p.off
        if p.word: self.ram[o:o + 2] = struct.pack(">H", int(v) & 0xffff)
        else: self.ram[o] = int(v) & 0xff

    def value(self, i):
        p = self.fx.params[i]; o = self.fx.preset_offs[self.preset] + p.off
        if p.word: return struct.unpack(">H", self.ram[o:o + 2])[0]
        v = self.ram[o]
        return v - 256 if (p.signed and v > 127) else v


def _enter(c, st, fx_on=True):
    """put an effect's state into the 68000's memory before running its routines"""
    c.poke(RAM_FX, st.ram)
    c.poke(RAM_FLAG_ON, [1 if fx_on else 0])
    c.poke(RAM_FX_PTR, struct.pack(">I", RAM_FX))
    ctl = bytearray(0x20)
    for name, v in st.controllers.items():
        o = MOD_OFFSET.get(name)
        if o is not None: ctl[o:o + 2] = struct.pack(">H", max(0, min(0x7f00, int(v))))
    c.poke(RAM_SCRATCH, ctl)
    if st.esp is not None: c.mirror_chip(st.esp)            # the routines see the chip as it is now
    else:
        c.mirror(st.fx.gpr_init, st.fx.program)


def _leave(c, st):
    st.ram = bytearray(c.peek(RAM_FX, len(st.ram)))


def apply_params(fx, values=None, preset=0, fx_on=True, state=None):
    """run the ROM's routines for every parameter of the effect (as the OS does when an effect is loaded or edited);
    returns [(kind, register / address, value)] in order: kind 1 = chip register write, 2 = instruction write,
    3 = an OS call that is not answered (logged)"""
    with CPU_LOCK:
        return _apply_params(fx, values, preset, fx_on, state)


def _apply_params(fx, values, preset, fx_on, state):
    c = cpu(fx.rom)
    st = state or FxState(fx, preset, values or {})
    _enter(c, st, fx_on)
    base = RAM_FX + fx.preset_offs[st.preset]
    writes = []
    for i, p in enumerate(fx.params):
        a2 = p.addr + 8
        while True:
            kind = fx.rom.u8(a2); a2 += 1
            if kind == 0: break
            h = HANDLERS.get(kind)
            if h is None: writes.append((3, -kind, i)); break
            regs = [0] * 8 + [0, RAM_FX, a2, 0, RAM_SCRATCH, base, base + p.off]
            out, after, done = c.call(h, regs)
            writes += out
            if not done: writes.append((3, -1000 - kind, i)); break
            if kind == 0x09 or c.lib.asr68k_stop_pc() == 0xFF8202: break        # inline code: the rest of the list
            a2 = after[10] & 0xffffff
    writes += _mod_call(c, fx, base)
    _leave(c, st)
    return writes


def _mod_call(c, fx, base):
    mod = fx.rom.u16(fx.s + 0x2c)
    if not mod: return []
    # the effect's modulation routine, as the OS calls it each control tick (disk OS 69E6): A1 = the effect,
    # A5 = the preset's values, A4 = the controllers
    out, after, done = c.call(RAM_FX + mod, [0] * 8 + [0, RAM_FX, 0, 0, RAM_SCRATCH, base, 0])
    return out


def mod_tick(state, fx_on=True):
    """one control tick: the effect's modulation routine moves modulated values toward their targets and re-applies
    them; returns the chip writes"""
    fx = state.fx
    if not fx.rom.u16(fx.s + 0x2c): return []
    with CPU_LOCK:
        c = cpu(fx.rom)
        _enter(c, state, fx_on)
        out = _mod_call(c, fx, RAM_FX + fx.preset_offs[state.preset])
        _leave(c, state)
    return out


# ---------------------------------------------------------------------------------------------------------- a running effect
SER = {"BUS1": (0, 1), "BUS2": (4, 5), "BUS3": (6, 7), "OUT": (2, 3)}    # (R, L) indices into SER0R..SER3L
IN_MASK = 0b11110011


CONTROL_TICK = 128   # samples between modulation updates. The OS runs them from a timer whose rate is not yet
                     # confirmed from the ROM; 128 samples at 29.76 kHz is about 4.3 ms.


class Running:
    """an effect loaded into a chip, with its parameters applied"""
    def __init__(self, fx, preset=0, values=None):
        self.fx, self.esp = fx, Esp()
        self.values = dict(fx.preset(preset)) if (values is None and fx.preset_names) else dict(values or {})
        self.preset = preset
        self.state = FxState(fx, preset, self.values, self.esp)
        self.phase = 0
        self.load()

    def load(self):
        e, fx = self.esp, self.fx
        e.reset()
        # what the OS does to the chip at power-on (ROM F97346): every instruction and GPR 0-9F set to all ones,
        # SIGREG all ones (so products are shifted by 1, not 2), memory size, delay length and base
        for a in range(160): e.set_instr(a, 0xffffffffffff)
        for r in range(0xa0): e.write(r, 0xffffff)
        e.write(0xf4, 0x0000ff); e.write(0xf5, 0xffffff); e.write(0xf8, 0x000f00); e.write(0xf9, 0xffffff)
        # and before each effect (F97744, F973E0): delay length, memory cleared, GPR 0-8F cleared
        e.write(0xf5, 0xffff00); e.clear_memory()
        for r in range(0x90): e.write(r, 0)
        for a, ins in fx.program.items(): e.set_instr(a, ins)
        for r, v in fx.gpr_init.items(): e.write(r, v)
        tbl = fx.table()
        for r, v in fx.reg_init: e.write(r, v)
        ins = fx.program.get(0x3a)
        if ins is not None and ((ins >> 12) & 0xf) == 0xf:           # the loader's last step (F975C0): END moves to 0x3B
            e.set_instr(0x3a, (ins & ~(0xffff << 16) & ~(0xf0 << 8)) | (0xffff << 16) | (((ins >> 8) & 0x9f) << 8))
            e.set_instr(0x3b, (0xffffffff << 16) | (0xf0 << 8) | (ins & 0xff))
        if tbl is not None: e.write_memory(*tbl)                     # then its table goes into the chip's memory
        self.apply()
        e.write(0x7f, 0x7fffff)          # the effects master level: the OS fades it up after loading (ROM F9760C)

    def _do(self, writes):
        for k, r, v in writes:
            if k == 1: self.esp.write(r, v)
            elif k == 2: self.esp.set_instr(r, v)

    def apply(self):
        self._do(apply_params(self.fx, preset=self.preset, state=self.state))

    def set(self, i, v):
        """change a parameter (as editing it on the machine: its routines run)"""
        self.values[i] = v
        self.state.set_value(i, v)
        self.apply()

    def controller(self, name, value):
        """a modulation source, 0..127 (WHEEL, PEDAL, PRESS, XCTRL, VEL, KBD, KEYDN, SUSTN, FSW-L, PBEND, PATCH)"""
        self.state.controllers[name] = int(value) << 8

    def run(self, bus1, bus2=None, bus3=None):
        """inputs: (n, 2) float arrays -1..1 at the effect's rate; returns (n, 2) float"""
        n = len(bus1)
        ser = np.zeros((n, 8), np.int16)
        for name, x in (("BUS1", bus1), ("BUS2", bus2), ("BUS3", bus3)):
            if x is None: continue
            q = np.clip(np.round(np.asarray(x) * 32767.0), -32768, 32767).astype(np.int16)
            ser[:, SER[name][1]], ser[:, SER[name][0]] = q[:, 0], q[:, 1]
        out = np.zeros_like(ser)
        has_mod = bool(self.fx.rom.u16(self.fx.s + 0x2c))
        i = 0
        while i < n:
            if has_mod and self.phase == 0: self._do(mod_tick(self.state))
            k = min(n - i, CONTROL_TICK - self.phase) if has_mod else n - i
            out[i:i + k] = self.esp.process(ser[i:i + k], IN_MASK)
            i += k
            self.phase = (self.phase + k) % CONTROL_TICK if has_mod else 0
        return np.stack([out[:, SER["OUT"][1]], out[:, SER["OUT"][0]]], 1).astype(np.float32) / 32768.0


# ---------------------------------------------------------------------------------------------------------- rate change
class Resampler:
    """streaming band-limited rate change (Kaiser-windowed sinc, 32 taps, 1024 phases), for 44.1 kHz <-> the chip's
    29.76 kHz. Output length follows the rate exactly over time (a block may give one sample more or less)."""
    PHASES = 1024

    def __init__(self, fin, fout, taps=32, channels=2, beta=7.0):
        self.step = fin / float(fout)
        self.taps = taps
        h = taps // 2
        cut = 0.5 * min(1.0, fout / fin) * 0.94                      # cycles per input sample
        frac = np.arange(self.PHASES + 1) / float(self.PHASES)
        d = np.arange(-h + 1, h + 1)[None, :] - frac[:, None]
        win = np.i0(beta * np.sqrt(np.clip(1 - (d / h) ** 2, 0, 1))) / np.i0(beta)
        self.table = (2 * cut * np.sinc(2 * cut * d) * win).astype(np.float64)
        self.k = np.arange(-h + 1, h + 1)
        self.hist = np.zeros((taps, channels))
        self.t = float(h)                                            # position of the next output in hist + input

    def process(self, x):
        x = np.asarray(x, dtype=np.float64)
        buf = np.concatenate([self.hist, x])
        h = self.taps // 2
        last = len(buf) - h                                          # an output needs h samples after it
        if self.t >= last:
            self.hist = buf[-self.taps:]; self.t -= len(buf) - self.taps
            return np.zeros((0, buf.shape[1]))
        pos = np.arange(self.t, last, self.step)
        base = np.floor(pos).astype(np.int64)
        w = self.table[np.rint((pos - base) * self.PHASES).astype(np.int64)]
        y = np.einsum("nk,nkc->nc", w, buf[base[:, None] + self.k[None, :]])
        self.t = pos[-1] + self.step - (len(buf) - self.taps)
        self.hist = buf[-self.taps:]
        return y


# ---------------------------------------------------------------------------------------------------------- the library
SYSTEM = ("31 VOICE 30K", "23 VOICE 44K", "DMA TEST")     # the OS's own chip set-ups, not effects
_library = None


def library(folder=None):
    """{name: Effect} for the user's ROM (cached), or {} when there is none"""
    global _library
    if _library is None:
        data = find_rom(folder or FW_DIR)
        _library = {} if data is None else {n: f for n, f in load_effects(Rom(data)).items() if n not in SYSTEM}
    return _library
