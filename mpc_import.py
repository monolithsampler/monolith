"""
mpc_import.py - load Akai MPC2000XL projects into Monolith.

What it reads (all little-endian, layouts from the open MPC2000XL format descriptions used by VMPC2000XL,
https://github.com/izzyreal/mpc2000xl_kaitai, checked against real files):
  .SND   one sample: 42-byte header (name, level, tune, stereo, start, end, loop, beats, rate) + 16-bit PCM
         (a stereo sound stores all of the left channel, then all of the right)
  .PGM   one drum program: sound names, 64 note parameter blocks (notes 35-98), 64 mixer strips, pad -> note map
  .APS   all programs + settings: up to 24 programs and which program each of DRUM 1-4 plays
  .ALL   all sequences + songs: 99 sequence slots, 64 tracks each, events at 96 ticks per quarter note
         (the same resolution as this sampler, so ticks copy straight across)

How it maps (MPC -> Monolith):
  sound                    -> a Source (mono mix of a stereo sound, resampled to 44.1 kHz if needed)
  program pad A01-D16      -> pad A01-D16 of a program, with the parameters of the note that pad plays
  note tune + sound tune   -> pad tune (semitones, 0.1 steps)        sound level -> pad gain
  mixer level / pan        -> pad level / pan                         voice overlap NOTE OFF -> HOLD
  attack / decay (END)     -> fade in / fade out (MPC curve: ms = value^2 / 2)
  decay mode START         -> the pad is cut to attack + decay, with that fade out
  filter (freq below 100)  -> the pad's low-pass filter: cutoff, resonance, filter envelope amount / decay, velocity > cutoff
  mute assign              -> choke groups (the sampler's groups cut both ways)
  SIMULT / VEL SW / DCY SW -> resolved per note while importing: each recorded hit becomes the pad(s) the MPC
                              would have played, so the beat sounds right (live pad playing does not switch)
  track on DRUM 1-4        -> a DRUM track playing the program that drum used (from the .APS)
  track on MIDI            -> a MIDI track (notes go to MIDI out)
  sequence tempo, bars, time signature (of the first bar), loop on/off, track names, mute, velocity %
  the first used song      -> the song

Limits: 16 tracks per sequence, 8 programs and 16 sequences (the rest are listed in the report), no sample loops,
no tempo-change events, no per-note tune/decay variations, no effects board (EB16) settings.
"""
import os, struct
import numpy as np

NOTE0 = 35                                   # MPC drum notes run 35-98: note parameter block k is note 35 + k
TICKS = 96


def _s(b):
    """MPC name bytes -> str (space / 0x00 / 0xFF padded)"""
    return bytes(x for x in b if x not in (0, 0xFF)).decode("ascii", "replace").rstrip()


def _key(name):
    return name.strip().upper()


def env_ms(v):
    """MPC2000XL envelope value 0-100 -> milliseconds (the hardware's square-law curve, 100 = 5 s)"""
    v = max(0, min(100, int(v)))
    return (v * v + 1) // 2


# ================================================================== .SND
def read_snd(path, header_only=False):
    with open(path, "rb") as f: b = f.read() if not header_only else f.read(42)
    if len(b) < 42 or b[0] != 0x01 or b[1] not in (0x01, 0x02, 0x03, 0x04):
        raise ValueError("not an MPC2000/2000XL sound")
    level, tune, stereo = b[19], struct.unpack("<b", b[20:21])[0], b[21] & 1
    start, end, frames, loop_frames = struct.unpack("<IIII", b[22:38])
    snd = {"name": _s(b[2:18]) or os.path.splitext(os.path.basename(path))[0], "level": level, "tune": tune,
           "stereo": bool(stereo), "start": start, "end": end, "frames": frames, "loop_frames": loop_frames,
           "loop": bool(b[38] & 1), "beats": b[39], "rate": struct.unpack("<H", b[40:42])[0] or 44100, "path": path}
    if header_only: return snd
    n = frames * (2 if stereo else 1)
    pcm = np.frombuffer(b, dtype="<i2", count=min(n, (len(b) - 42) // 2), offset=42).astype(np.float32) / 32768.0
    if stereo:
        half = len(pcm) // 2
        pcm = 0.5 * (pcm[:half] + pcm[half:2 * half])
    snd["data"] = pcm
    return snd


# ================================================================== .PGM / .APS
NOTE_FIELDS = ("mode", "vel_lo", "also1", "vel_hi", "also2", "overlap", "mute1", "mute2", "tune", "attack", "decay",
               "decay_mode", "cutoff", "resonance", "fenv_attack", "fenv_decay", "fenv_amount", "vel_level",
               "vel_attack", "vel_start", "vel_cutoff", "slider", "vel_pitch")
MODES = ("NORMAL", "SIMULT", "VEL SW", "DCY SW")


def _notes(b, o, wide):
    """64 note parameter blocks; wide = the .APS layout (16-bit sound index)"""
    out = []
    for k in range(64):
        if wide: snd = struct.unpack_from("<H", b, o)[0]; o += 2; snd = None if snd == 0xFFFF else snd
        else: snd = b[o]; o += 1; snd = None if snd == 0xFF else snd
        v = struct.unpack_from("<BBBBBBBBhBBBBBBBBBBBBBB", b, o); o += 24
        d = dict(zip(NOTE_FIELDS, v)); d["sound"] = snd; d["note"] = NOTE0 + k
        out.append(d)
    return out, o


def _mixers(b, o):
    out = []
    for k in range(64):
        fxo, vol, pan, ivol, outp, send = b[o:o + 6]; o += 6
        out.append({"fx": fxo, "volume": vol, "pan": pan, "indiv": ivol, "output": outp, "send": send})
    return out, o


def _sound_names(b, o):
    n = struct.unpack_from("<H", b, o)[0]; o += 2
    names = [_s(b[o + 17 * i:o + 17 * i + 16]) for i in range(n)]
    return names, o + 17 * n


def _program_tail(b, o, wide):
    name = _s(b[o:o + 16]); o += 17
    o += 9 + 1 + 5                                      # slider, program change, unknown
    notes, o = _notes(b, o, wide)
    o += 1
    mixers, o = _mixers(b, o)
    o += 3
    pads = [x if x < 128 else x - 256 for x in b[o:o + 64]]; o += 64
    o += 200                                            # effects board (EB16) block: not reverse engineered
    return {"name": name, "notes": notes, "mixers": mixers, "pads": pads}, o


def read_pgm(path):
    b = open(path, "rb").read()
    if b[:2] != b"\x07\x04": raise ValueError("not an MPC2000XL program")
    names, o = _sound_names(b, 2)
    o += 2
    p, o = _program_tail(b, o, False)
    p["sounds"] = names                                 # sound index -> name, local to this file
    return p


def read_aps(path):
    b = open(path, "rb").read()
    if b[:2] != b"\x0a\x05": raise ValueError("not an MPC2000XL all-programs file")
    names, o = _sound_names(b, 2)
    o += 2
    aps = {"name": _s(b[o:o + 16]), "sounds": names}; o += 17
    g = b[o:o + 7]; o += 7
    aps["mix_from_drum"] = bool(g[2] & 1)              # stereo mix source: 0 = program, 1 = drum
    o += 1
    aps["master_pads"] = list(b[o:o + 64]); o += 64
    o += 7
    drums = []
    for d in range(4):
        mixers, o = _mixers(b, o)
        o += 2
        drums.append({"mixers": mixers, "program": b[o + 3]}); o += 6
        o += 4 if d < 3 else 1
    aps["drums"] = drums
    progs = {}
    while o < len(b):
        idx = b[o]; o += 1
        if idx > 23: break
        o += 5
        p, o = _program_tail(b, o, True)
        p["sounds"] = names
        progs[idx] = p
    aps["programs"] = progs
    return aps


# ================================================================== .ALL
ALL_MAGIC = b"MPC2KXL ALL 1.00"
SEQ_START, SEQ_HEADER = 14406, 10240                 # first sequence record; sequence header length (events follow)


def _events(b, o):
    """sequence events from o until the terminator; returns (list, end offset)"""
    ev = []
    while o + 8 <= len(b):
        v = struct.unpack_from("<I", b, o)[0]
        tick = v & 0xFFFFF
        if tick == 0xFFFFF: o += 8; break
        track, kind = (v >> 24) & 0x3F, b[o + 4]
        if kind <= 0x7F:
            dur = (((v >> 20) & 0xF) << 10) + (((v >> 30) & 0x3) << 8) + b[o + 5]
            ev.append({"tick": tick, "track": track, "note": kind, "dur": dur, "vel": b[o + 6] & 0x7F,
                       "var_type": ((b[o + 6] >> 7) << 1) | (b[o + 7] >> 7), "var": b[o + 7] & 0x7F})
            o += 8
        elif kind == 0xF0:                              # system exclusive: 3 segments, or 4 when it is a mixer event
            mixer = b[o + 8:o + 10] == b"\xF0\x47"
            if mixer: ev.append({"tick": tick, "track": track, "mixer": (b[o + 13], b[o + 14], b[o + 15])})
            o += 32 if mixer else 24
        else:
            ev.append({"tick": tick, "track": track, "other": kind, "data": (b[o + 5], b[o + 6])})
            o += 8
    return ev, o


def _sequence(b, s):
    seq = {"name": (_s(b[s:s + 8]) + _s(b[s + 8:s + 16])).strip()}
    seq["tempo"] = struct.unpack_from("<H", b, s + 22)[0] / 10.0
    nbars = struct.unpack_from("<H", b, s + 26)[0]
    seq["last_tick"] = struct.unpack_from("<I", b, s + 28)[0] & 0xFFFFFF
    seq["loop_start"], seq["loop_end"] = struct.unpack_from("<HH", b, s + 48)
    seq["loop"] = bool(b[s + 52] & 1)
    t = s + 384
    seq["tracks"] = [{"name": _s(b[t + 16 * i:t + 16 * i + 16]), "device": b[t + 1024 + i], "bus": b[t + 1088 + i],
                      "pgm_change": b[t + 1152 + i], "velocity": b[t + 1216 + i] or 100,
                      "used": bool(b[t + 1280 + i] & 1), "on": bool(b[t + 1280 + i] & 2)} for i in range(64)]
    bars, first = [], 0
    for i in range(min(nbars, 999)):
        o = s + 5379 + 4 * i
        tpb = b[o] or 96
        last = b[o + 1] | (b[o + 2] << 8) | (b[o + 3] << 16)
        bars.append({"num": max(1, (last - first) // tpb), "den": max(1, 4 * 96 // tpb), "ticks": last - first})
        first = last
    seq["bars"] = bars
    seq["events"], end = _events(b, s + SEQ_HEADER)
    return seq, end


def read_all(path):
    b = open(path, "rb").read()
    if b[:16] != ALL_MAGIC: raise ValueError("not an MPC2000XL ALL file")
    a = {"master_tempo": struct.unpack_from("<H", b, 1812)[0] / 10.0, "tempo_from_seq": bool(b[1814] & 1)}
    metas = [(_s(b[2064 + 18 * i:2064 + 18 * i + 16]), struct.unpack_from("<H", b, 2064 + 18 * i + 16)[0]) for i in range(99)]
    used_slots = [i for i, (_, n) in enumerate(metas) if n]
    songs = []
    for i in range(20):
        o = 3846 + 528 * i
        steps = []
        for k in range(250):
            sq, rep = b[o + 16 + 2 * k], b[o + 17 + 2 * k]
            if sq == 0xFF: break
            steps.append((sq, max(1, rep)))
        if b[o + 518] & 1 and steps:
            songs.append({"name": _s(b[o:o + 16]), "steps": steps, "loop": bool(b[o + 521] & 1)})
    a["songs"] = songs
    seqs, o = {}, SEQ_START
    while o + 8 <= len(b):
        if b[o:o + 8] == b"\xFF" * 8: o += 8; continue      # an extra terminator segment (layout padding)
        sq, o = _sequence(b, o)
        slot = used_slots[len(seqs)] if len(seqs) < len(used_slots) else len(seqs)
        sq["slot"] = slot
        seqs[slot] = sq
    a["sequences"] = seqs
    return a


# ================================================================== a project folder
def scan(folder):
    """what an MPC folder holds: {'all': path, 'aps': path, 'pgm': [paths], 'snd': {NAME: path}, 'wav': {NAME: path}}"""
    found = {"all": None, "aps": None, "pgm": [], "snd": {}, "wav": {}}
    for f in sorted(os.listdir(folder), key=str.lower):
        p, ext = os.path.join(folder, f), os.path.splitext(f)[1].lower()
        if f.startswith(".") or not os.path.isfile(p): continue
        if ext == ".all" and found["all"] is None: found["all"] = p
        elif ext == ".aps" and found["aps"] is None: found["aps"] = p
        elif ext == ".pgm": found["pgm"].append(p)
        elif ext == ".snd":
            try: found["snd"].setdefault(_key(read_snd(p, header_only=True)["name"]), p)
            except (ValueError, OSError): pass
            found["snd"].setdefault(_key(os.path.splitext(f)[0]), p)
        elif ext == ".wav": found["wav"].setdefault(_key(os.path.splitext(f)[0]), p)
    return found


def is_mpc_file(name):
    return os.path.splitext(name)[1].lower() in (".all", ".aps", ".pgm")


def describe(folder):
    """one line for the browser: what importing this folder would bring in"""
    f = scan(folder)
    parts = []
    if f["all"]:
        try: parts.append(f"{len(read_all(f['all'])['sequences'])} seq")
        except Exception: parts.append("ALL (unreadable)")
    if f["aps"]:
        try: parts.append(f"{len(read_aps(f['aps'])['programs'])} pgm")
        except Exception: parts.append("APS (unreadable)")
    elif f["pgm"]: parts.append(f"{len(f['pgm'])} pgm")
    parts.append(f"{len(f['snd']) and len(set(f['snd'].values()))} snd")
    return "MPC2000XL: " + ", ".join(parts)


# ================================================================== import into an engine
class Report:
    def __init__(self): self.lines, self.warn, self.backup = [], [], None
    def add(self, s): self.lines.append(s)
    def skip(self, s): self.warn.append(s)
    def text(self): return "\n".join(self.lines + (["", "Not imported:"] + ["  " + w for w in self.warn] if self.warn else []))


def _pad_from_note(E, pad, note, mixer, src, snd, rep, label):
    """set one sampler pad from an MPC note parameter block + mixer strip + sound"""
    from engine import Pad
    owner = pad.owner
    pad.__init__(pad.idx); pad.owner = owner                         # back to defaults first (still in its program)
    if src is None: return
    s0 = max(0, min(int(snd.get("start", 0) * src.ratio), src.length - 2))
    e0 = int(snd.get("end", 0) * src.ratio) or src.length
    pad.assign(src, s0, max(s0 + 2, min(e0, src.length)))
    pad.lofi_on = False                                              # MPC2000XL sounds are 16-bit 44.1 kHz: no SP-1200 colour
    pad.tune = round((note["tune"] + snd.get("tune", 0)) / 10.0, 1)
    lvl = snd.get("level", 100)
    pad.gain_db = round(20 * np.log10(max(lvl, 1) / 100.0), 2) if lvl != 100 else 0.0
    pad.vol = max(0.0, min(1.0, mixer["volume"] / 100.0))
    pad.pan = max(-1.0, min(1.0, (mixer["pan"] - 50) / 50.0))
    pad.mode = "HOLD" if note["overlap"] == 2 else "ONE"
    pad.vel_mpc = note["vel_level"]                                  # the MPC's own velocity -> level response
    pad.fade_in = env_ms(note["attack"]) if note["attack"] else 0
    if note["decay_mode"] == 1:                                      # START: the sound dies away after attack + decay
        keep = int((env_ms(note["attack"]) + env_ms(note["decay"])) * 44.1)
        if keep < pad.end - pad.start: pad.end = pad.start + max(keep, 64)
        pad.fade_out = env_ms(note["decay"])
    else:                                                            # END: a fade over the last part of the sound
        pad.fade_out = env_ms(note["decay"]) if note["decay"] else 0
    if note["cutoff"] < 100 or note["fenv_amount"]:                # the MPC2000XL's 2-pole low-pass -> the pad's own filter
        pad.flt = "LP"
        pad.cutoff = max(0.0, min(1.0, note["cutoff"] / 100.0))
        pad.res = max(0.0, min(1.0, note["resonance"] / 15.0))
        pad.f_env = max(0.0, min(1.0, note["fenv_amount"] / 100.0))
        pad.f_dec = max(10, env_ms(note["fenv_decay"])) if note["fenv_decay"] else 300
        pad.f_vel = max(0.0, min(1.0, note["vel_cutoff"] / 100.0))


def backup_project(E):
    """move the current project (project.json + samples/*.wav) into backups/before-mpc-<date-time>/, so an import
    never mixes old samples into the new project and nothing is ever lost (delete old backups yourself)"""
    import shutil, time
    try: E.save_project()                                            # unsaved changes are part of what we keep
    except Exception: pass
    base = os.path.join(E.dir, "backups", "before-mpc-" + time.strftime("%Y%m%d-%H%M%S"))
    bdir, k = base, 2
    while os.path.exists(bdir): bdir, k = f"{base}-{k}", k + 1
    os.makedirs(os.path.join(bdir, "samples"), exist_ok=True)
    if os.path.exists(E.project_file): shutil.copyfile(E.project_file, os.path.join(bdir, "project.json"))
    for f in os.listdir(E.sample_dir):
        if f.lower().endswith(".wav"): shutil.move(os.path.join(E.sample_dir, f), os.path.join(bdir, "samples", f))
    for s in E.sources: s.dirty = False
    return bdir


def import_folder(E, folder, report=None, backup=True):
    """Replace the engine's project with the MPC2000XL project in `folder`. Returns a Report.
    The previous project is moved to backups/before-mpc-<date-time>/ in the project folder (copy it back to undo)."""
    from engine import Source, OUT_SR, NPROG, NSEQ, NTRACK, resample, Program, Sequence
    rep = report or Report()
    found = scan(folder)
    if not (found["all"] or found["aps"] or found["pgm"] or found["snd"]):
        raise ValueError("no MPC2000XL files here")
    allf = read_all(found["all"]) if found["all"] else None
    aps = read_aps(found["aps"]) if found["aps"] else None
    pgms = [] if aps else [read_pgm(p) for p in found["pgm"]]

    # ---- which MPC programs become our 8 (the ones the drums play first)
    if aps:
        mpc_progs = aps["programs"]
        order = [d["program"] for d in aps["drums"] if d["program"] in mpc_progs]
        order = list(dict.fromkeys(order + sorted(mpc_progs)))
    else:
        mpc_progs = dict(enumerate(pgms)); order = list(mpc_progs)
    keep = order[:NPROG]
    for i in order[NPROG:]: rep.skip(f"program {i + 1} '{mpc_progs[i]['name']}' (only {NPROG} programs)")
    prog_map = {m: k for k, m in enumerate(keep)}

    rep.backup = backup_project(E) if backup else None

    with E.lock:
        if E.playing: E.stop()
        # ---- fresh project
        E.sources = []
        E.programs = [Program(i) for i in range(NPROG)]
        E.seqs = [Sequence(i) for i in range(NSEQ)]
        E.song, E.cur_seq, E.cur_track, E.bank, E.sel = [[0, 1]], 0, 0, 0, 0
        E._allpads = None
        E.v_data = [None] * E.nv
        E.warp_cache.clear()

        # ---- sounds (only those a kept program uses, plus loose sounds when there is no program at all)
        wanted = []
        for m in keep:
            p = mpc_progs[m]
            for n in p["notes"]:
                if n["sound"] is not None and n["sound"] < len(p["sounds"]): wanted.append(p["sounds"][n["sound"]])
        if not keep: wanted = [os.path.splitext(os.path.basename(v))[0] for v in found["snd"].values()]
        srcs, snds = {}, {}
        for name in dict.fromkeys(wanted):
            k = _key(name)
            if k in srcs: continue
            path = found["snd"].get(k) or found["wav"].get(k)
            if path is None: rep.skip(f"sound '{name}' (file not in the folder)"); srcs[k] = None; continue
            try:
                if path.lower().endswith(".snd"):
                    sd = read_snd(path); raw, sr = sd["data"], sd["rate"]
                else:
                    from engine import load_wav
                    raw, sr = load_wav(path); sd = {"level": 100, "tune": 0, "start": 0, "end": len(raw)}
            except Exception as ex:
                rep.skip(f"sound '{name}': {str(ex)[:50]}"); srcs[k] = None; continue
            x = resample(raw, sr, OUT_SR) if sr != OUT_SR else raw
            base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:24] or "sound"
            nm, j = base, 2
            while E.source_by_name(nm) is not None: nm, j = f"{base}_{j}", j + 1
            s = E.add_source(nm, x, dirty=True)
            s.ratio = OUT_SR / float(sr)
            srcs[k], snds[k] = s, sd
        rep.add(f"{sum(1 for s in srcs.values() if s)} sounds")

        # ---- programs: pad i gets the note that MPC pad i plays; notes no pad plays go on spare pads
        note_pad = {}                                                    # (our program, MPC note) -> our pad index
        for m in keep:
            k = prog_map[m]; p = mpc_progs[m]; pr = E.programs[k]
            pr.name = (p["name"] or f"MPC {m + 1}")[:16]
            mix = aps["drums"][[d["program"] for d in aps["drums"]].index(m)]["mixers"] \
                if aps and aps["mix_from_drum"] and m in [d["program"] for d in aps["drums"]] else p["mixers"]
            spare, seen = [], set()
            for i, n in enumerate(p["pads"]):
                if n < NOTE0 or n > NOTE0 + 63 or n in seen: spare.append(i); continue
                seen.add(n); note_pad[(k, n)] = i
            for n in range(NOTE0, NOTE0 + 64):                           # sounds on notes no pad plays
                if n not in seen and p["notes"][n - NOTE0]["sound"] is not None and spare:
                    note_pad[(k, n)] = spare.pop(0); seen.add(n)
            for (kk, n), i in note_pad.items():
                if kk != k: continue
                nt = p["notes"][n - NOTE0]
                name = p["sounds"][nt["sound"]] if nt["sound"] is not None and nt["sound"] < len(p["sounds"]) else None
                src = srcs.get(_key(name)) if name else None
                _pad_from_note(E, pr.pads[i], nt, mix[n - NOTE0], src, snds.get(_key(name), {}) if name else {}, rep,
                               f"{pr.name} note {n}")
            # mute assign -> choke groups: a note and the notes that cut it share a group
            for g, members in enumerate(mute_groups(p, [n for (kk, n) in note_pad if kk == k]), 1):
                for n in members: pr.pads[note_pad[(k, n)]].choke = g
            for pad in pr.pads:
                if not pad.empty: pad.build()
            used = sum(1 for pad in pr.pads if not pad.empty)
            rep.add(f"program {k + 1}: {pr.name} ({used} pads)")

        # ---- sequences
        drum_prog = {}
        for d in range(4):
            m = aps["drums"][d]["program"] if aps else 0
            drum_prog[d + 1] = prog_map.get(m, 0)
        seq_map = {}
        if allf:
            slots = sorted(allf["sequences"])
            for slot in slots[NSEQ:]: rep.skip(f"sequence {slot + 1} '{allf['sequences'][slot]['name']}' (only {NSEQ} sequences)")
            for si, slot in enumerate(slots[:NSEQ]):
                ms, sq = allf["sequences"][slot], E.seqs[si]
                seq_map[slot] = si
                sq.name = (ms["name"] or f"Seq {slot + 1}")[:16]
                sq.bpm = ms["tempo"] if (allf["tempo_from_seq"] or not allf["master_tempo"]) and ms["tempo"] else (allf["master_tempo"] or 120.0)
                b0 = ms["bars"][0] if ms["bars"] else {"num": 4, "den": 4}
                sq.num, sq.den = b0["num"], b0["den"] if b0["den"] in (2, 4, 8, 16) else 4
                if any((b["num"], b["den"]) != (b0["num"], b0["den"]) for b in ms["bars"]):
                    rep.skip(f"{sq.name}: time signature changes (all bars use {sq.num}/{sq.den})")
                sq.bars = max(1, -(-ms["last_tick"] // sq.bar_ticks)) if ms["last_tick"] else max(1, len(ms["bars"]))
                sq.swing, sq.loop = 0.5, ms["loop"]
                if ms["loop"] and ms["loop_start"] not in (0,): rep.skip(f"{sq.name}: loop starts at bar {ms['loop_start'] + 1} (loops the whole sequence)")
                tracks_with = sorted({e["track"] for e in ms["events"]})
                for t in tracks_with[NTRACK:]: rep.skip(f"{sq.name}: track {t + 1} (only {NTRACK} tracks)")
                lost_var = lost_other = unmapped = 0
                for ti, mt in enumerate(tracks_with[:NTRACK]):
                    T, info = sq.tracks[ti], ms["tracks"][mt]
                    T.name = (info["name"] or f"Track {mt + 1:02d}")[:16]
                    T.mute = not info["on"]
                    vr = info["velocity"] / 100.0
                    evs = [e for e in ms["events"] if e["track"] == mt]
                    lost_other += sum(1 for e in evs if "note" not in e)
                    notes = [e for e in evs if "note" in e]
                    if info["bus"] == 0:                                   # MIDI track
                        T.kind = "midi"
                        T.midi_ch = ((info["device"] - 1) % 16) + 1 if info["device"] else 1
                        T.events = sorted((e["tick"], e["note"], max(1, min(127, int(round(e["vel"] * vr)))), max(1, e["dur"])) for e in notes)
                        continue
                    pk = drum_prog.get(info["bus"], 0); T.prog = pk
                    p = mpc_progs[keep[pk]] if keep else None
                    out = []
                    for e in notes:
                        vel = max(1, min(127, int(round(e["vel"] * vr))))
                        if e["var_type"] != 0 or e["var"] != 64: lost_var += 1
                        for n in _resolve(p, e, vel):
                            i = note_pad.get((pk, n))
                            if i is None: unmapped += 1; continue
                            out.append((e["tick"], i, vel, max(1, e["dur"])))
                    T.events = sorted(set(out))
                if lost_var: rep.skip(f"{sq.name}: {lost_var} note variations (tune/decay/attack/filter per hit)")
                if lost_other: rep.skip(f"{sq.name}: {lost_other} controller / pitch bend / mixer events")
                if unmapped: rep.skip(f"{sq.name}: {unmapped} hits on notes with no pad")
                rep.add(f"sequence {si + 1}: {sq.name}  {sq.bpm:g} bpm  {sq.bars} bars  {len(tracks_with[:NTRACK])} tracks  "
                        f"{sum(len(t.events) for t in sq.tracks)} notes")
            if allf["songs"]:
                s0 = allf["songs"][0]
                E.song = [[seq_map[sq], rep_] for sq, rep_ in s0["steps"] if sq in seq_map] or [[0, 1]]
                rep.add(f"song: {s0['name']} ({len(E.song)} steps)")
                for s in allf["songs"][1:]: rep.skip(f"song '{s['name']}' (one song)")
        else:
            T = E.seqs[0].tracks[0]; T.prog = 0
    E.save_project()
    E.say("MPC project imported")
    return rep


def mute_groups(p, notes):
    """MPC mute assign (note X is cut when note A or B plays) -> lists of notes that should share a choke group"""
    notes = set(notes)
    parent = {n: n for n in notes}
    def find(x):
        while parent[x] != x: x = parent[x]
        return x
    for n in notes:
        nt = p["notes"][n - NOTE0]
        for mn in (nt["mute1"], nt["mute2"]):
            if mn in notes and mn != n: parent[find(n)] = find(mn)
    groups = {}
    for n in sorted(notes): groups.setdefault(find(n), []).append(n)
    return [g for g in groups.values() if len(g) > 1]


def _resolve(p, e, vel):
    """the MPC notes a recorded hit really plays, after SIMULT / VEL SW / DCY SW"""
    n = e["note"]
    if p is None or not (NOTE0 <= n <= NOTE0 + 63): return [n]
    nt = p["notes"][n - NOTE0]
    a1, a2 = nt["also1"], nt["also2"]
    ok = lambda x: NOTE0 <= x <= NOTE0 + 63
    if nt["mode"] == 1:                                                # SIMULT: up to 3 notes at once
        return [n] + [x for x in (a1, a2) if ok(x) and x != n]
    if nt["mode"] in (2, 3):                                           # VEL SW / DCY SW: switch above the thresholds
        v = vel if nt["mode"] == 2 else (e["var"] if e["var_type"] == 1 and e["var"] != 64 else nt["decay"])
        if ok(a2) and v > nt["vel_hi"]: return [a2]
        if ok(a1) and v > nt["vel_lo"]: return [a1]
    return [n]
