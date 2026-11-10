"""
mpc2_import.py - load MPC 2.x projects (MPC Live / One / X / Key / Software, saved as .xpj) into Monolith.

A project is NAME.xpj plus a NAME_[ProjectData] folder holding:
  *.xpm   programs (XML). Drum programs: 128 pads ("Instruments"), each with up to 4 sample layers, pad -> note map
  *.sxq   one sequence each: a Standard MIDI File (960 ticks per beat) whose notes are Akai meta events
  *.wav   the samples; MPC 2.x keeps slice (chop) points in a JSON "atem" chunk inside the WAV
  All Sequences & Songs.xal, Project Settings.xml, *.mcn (controller maps): not needed here

These layouts are not published by Akai. The XML programs are self-describing; the .sxq note records and the atem
chunk were worked out from real MPC 2.15 files (see README, section 9, for what is and is not certain).

Mapping (MPC 2.x -> Monolith):
  drum program pad 1-64 (banks A-D)  -> pad A01-D16 (pads in banks E-H are reported, not imported)
  layer 1 sample + its region        -> the pad's sample region: a slice of a chopped sample becomes a CHOP marker
                                        region the pad is linked to (non-destructive, as on the MPC)
  pad + layer tune (coarse + fine)   -> pad tune         level / pan -> pad level / pan (0.707946 = 0 dB)
  WARP on + its tempo                -> WARP on + WARP BPM     reverse -> REVERSE     attack -> fade in
  mute group                         -> choke group     simult targets -> resolved per recorded hit
  trigger mode one shot / note on    -> ONE SHOT / HOLD       filter                             -> the pad's own low-pass, cutoff and resonance (other filter types too)
  sequence tempo, bars, time signature, track names, notes (960 -> 96 ticks per beat)
"""
import json, os, struct
import xml.etree.ElementTree as ET
import numpy as np
from mpc_import import Report, backup_project

UNITY = 0.707946                 # an MPC 2.x level of 0 dB


# ================================================================== files
def find_project(path):
    """(xpj path, data folder) from an .xpj file, its data folder, or a folder holding one .xpj"""
    if os.path.isdir(path) and path.rstrip("/").endswith("_[ProjectData]"):
        xpj = path.rstrip("/")[:-len("_[ProjectData]")] + ".xpj"
        return (xpj if os.path.isfile(xpj) else None), path.rstrip("/")
    if os.path.isdir(path):
        xs = sorted(f for f in os.listdir(path) if f.lower().endswith(".xpj"))
        if not xs: return None, None
        path = os.path.join(path, xs[0])
    data = os.path.splitext(path)[0] + "_[ProjectData]"
    return path, (data if os.path.isdir(data) else None)


def read_xpj(path):
    t = ET.parse(path).getroot()
    v = t.find("Version")
    return {"bpm": float(t.findtext("BPM") or 120.0), "version": v.findtext("Application_Version") if v is not None else "",
            "files": [f.text for f in t.findall("FileList/File") if f.text]}


def wav_slices(path):
    """MPC 2.x slice data from a WAV's 'atem' chunk: {'default': (start, end), 'slices': [(start, end), ...]}"""
    out = {"default": None, "slices": []}
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF": return out
        f.read(8)
        while True:
            hd = f.read(8)
            if len(hd) < 8: break
            cid, n = hd[:4], struct.unpack("<I", hd[4:])[0]
            if cid == b"atem":
                try: j = json.loads(f.read(n).rstrip(b"\x00").decode("utf-8", "replace"))
                except ValueError: return out
                v = j.get("value0", {})
                d = v.get("defaultSlice")
                if d: out["default"] = (int(d.get("Start", 0)), int(d.get("End", 0)))
                for k in range(int(v.get("Num slices", 0))):
                    s = v.get(f"Slice {k}")
                    if s: out["slices"].append((int(s.get("Start", 0)), int(s.get("End", 0))))
                return out
            f.seek(n + (n & 1), 1)
    return out


def _f(el, tag, default=0.0):
    try: return float(el.findtext(tag))
    except (TypeError, ValueError): return default


def _b(el, tag): return (el.findtext(tag) or "").strip().lower() == "true"


def read_xpm(path):
    """a drum program: {'name', 'type', 'volume', 'pan', 'tune', 'pads': {pad 1-128: {...}}, 'notes': {pad: note}}"""
    pr = ET.parse(path).getroot().find("Program")
    p = {"name": pr.findtext("ProgramName") or os.path.basename(path).split(".")[0], "type": pr.get("type", ""),
         "volume": _f(pr, "Volume", UNITY), "pan": _f(pr, "Pan", 0.5),
         "tune": _f(pr, "TuneCoarse") + _f(pr, "TuneFine") / 100.0, "pads": {}, "notes": {}}
    for m in pr.findall("PadNoteMap/PadNote"):
        try: p["notes"][int(m.get("number"))] = int(m.findtext("Note"))
        except (TypeError, ValueError): pass
    if p["type"] != "Drum": return p
    for ins in pr.findall("Instruments/Instrument"):
        n = int(ins.get("number", 0))
        layers = []
        for L in ins.findall("Layers/Layer"):
            name = (L.findtext("SampleName") or "").strip()
            if not name or not _b(L, "Active"): continue
            layers.append({"sample": name, "volume": _f(L, "Volume", 1.0), "pan": _f(L, "Pan", 0.5),
                           "tune": _f(L, "TuneCoarse") + _f(L, "TuneFine") / 100.0,
                           "vel": (int(_f(L, "VelStart", 0)), int(_f(L, "VelEnd", 127))),
                           "slice": int(_f(L, "SliceIndex", 128)), "slice_start": int(_f(L, "SliceStart")),
                           "slice_end": int(_f(L, "SliceEnd")), "reverse": int(_f(L, "Direction")) == 1})
        if not layers: continue
        p["pads"][n] = {"layers": layers, "volume": _f(ins, "Volume", UNITY), "pan": _f(ins, "Pan", 0.5),
                        "tune": _f(ins, "TuneCoarse") + _f(ins, "TuneFine") / 100.0,
                        "attack": _f(ins, "VolumeAttack"), "decay": _f(ins, "VolumeDecay"), "sustain": _f(ins, "VolumeSustain", 1.0),
                        "cutoff": _f(ins, "Cutoff", 1.0), "resonance": _f(ins, "Resonance"), "filter": int(_f(ins, "FilterType", 2)),
                        "mute_group": int(_f(ins, "MuteGroup")), "mute_targets": [int(_f(ins, f"MuteTarget{k}")) for k in range(1, 5)],
                        "simult": [int(_f(ins, f"SimultTarget{k}")) for k in range(1, 5)],
                        "trigger": int(_f(ins, "TriggerMode")), "warp": _b(ins, "WarpEnable"), "warp_bpm": _f(ins, "WarpTempo"),
                        "vel_sens": _f(ins, "VelocitySensitivity", 1.0), "mute": _b(ins, "Mute")}
    return p


def _vlq(b, i):
    v = 0
    while True:
        c = b[i]; i += 1; v = (v << 7) | (c & 0x7F)
        if c < 0x80: return v, i


def read_sxq(path):
    """a sequence: name, tempo, bars, time signature, tracks [{'name', 'program', 'events': [(tick960, note, vel, len960)]}]"""
    b = open(path, "rb").read()
    if b[:4] != b"MThd": raise ValueError("not an MPC sequence")
    ntr, div = struct.unpack(">HH", b[10:14])
    seq = {"name": os.path.splitext(os.path.basename(path))[0], "tempo": 120.0, "bars": 0, "num": 4, "den": 4,
           "ppq": div or 960, "tracks": []}
    i = 8 + struct.unpack(">I", b[4:8])[0]
    for t in range(ntr):
        if b[i:i + 4] != b"MTrk": break
        n = struct.unpack(">I", b[i + 4:i + 8])[0]; d = b[i + 8:i + 8 + n]; i += 8 + n
        j = tick = 0; rs = None
        tr = {"name": "", "program": None, "events": [], "midi": 0}
        while j < len(d):
            dt, j = _vlq(d, j); tick += dt
            st = d[j]
            if st == 0xFF:
                typ = d[j + 1]; ln, k = _vlq(d, j + 2); data = d[k:k + ln]; j = k + ln
                if typ == 0x03: tr["name"] = data.rstrip(b"\x00").decode("latin-1")
                elif typ == 0x51 and ln == 3 and t == 0: seq["tempo"] = round(60e6 / int.from_bytes(data, "big"), 3)
                elif typ == 0x58 and ln >= 2 and t == 0: seq["num"], seq["den"] = data[0], 2 ** data[1]
                elif typ == 0x7F and data[:2] == b"Ga":
                    kind = data[2]
                    if kind == 0x00 and t == 0 and len(data) >= 7: seq["bars"] = data[4] | (data[5] << 8)
                    elif kind == 0x10 and len(data) > 12:              # track setup: ends with the program's name
                        tr["program"] = _tail_string(data)
                    elif kind == 0x11 and len(data) >= 13:             # a note: note, velocity, ..., length
                        ln_ = struct.unpack("<I", data[9:13])[0]
                        tr["events"].append((tick, data[4], data[5], ln_))
            elif st in (0xF0, 0xF7):
                ln, k = _vlq(d, j + 1); j = k + ln
            else:                                                       # plain MIDI events (not written by MPC 2.15)
                if st & 0x80: rs = st; j += 1
                if rs is None: break
                nb = 1 if (rs & 0xF0) in (0xC0, 0xD0) else 2
                if (rs & 0xF0) == 0x90 and d[j + 1] > 0: tr["events"].append((tick, d[j], d[j + 1], seq["ppq"] // 4)); tr["midi"] += 1
                j += nb
        if t == 0: seq["name"] = tr["name"] or seq["name"]
        elif tr["name"] or tr["events"]: seq["tracks"].append(tr)
    return seq


def _tail_string(data):
    """the length-prefixed text at the very end of a record (the program a track plays)"""
    for n in range(min(len(data) - 1, 64), 0, -1):
        if data[-n - 1] == n and all(32 <= c < 127 for c in data[-n:]): return data[-n:].decode("latin-1")
    return None


def describe(path):
    xpj, data = find_project(path)
    if not data: return "MPC 2.x project: its _[ProjectData] folder is missing"
    fs = os.listdir(data)
    nseq = sum(1 for f in fs if f.lower().endswith(".sxq"))
    nprog = sum(1 for f in fs if f.lower().endswith(".drum.xpm"))
    nwav = sum(1 for f in fs if f.lower().endswith(".wav"))
    return f"MPC 2.x: {nseq} seq, {nprog} drum pgm, {nwav} wav"


# ================================================================== import
def import_project(E, path, report=None, backup=True):
    """Replace the engine's project with an MPC 2.x project (.xpj or its folder). Returns a Report."""
    from engine import OUT_SR, NPROG, NSEQ, NTRACK, PPQ, resample, load_wav, Program, Sequence
    rep = report or Report()
    xpj, data = find_project(path)
    if not data: raise ValueError("no MPC 2.x project (.xpj with its _[ProjectData] folder) here")
    proj = read_xpj(xpj) if xpj else {"bpm": 120.0, "version": ""}
    files = os.listdir(data)
    progs = {}
    for f in sorted(files, key=str.lower):
        if f.lower().endswith(".xpm"):
            try: p = read_xpm(os.path.join(data, f))
            except ET.ParseError as ex: rep.skip(f"{f}: {ex}"); continue
            if p["type"] == "Drum": progs[p["name"]] = p
            else: rep.skip(f"{p['type'] or 'other'} program '{p['name']}' (only drum programs are imported)")
    seqfiles = sorted((f for f in files if f.lower().endswith(".sxq")), key=lambda f: (len(f), f.lower()))
    seqs = []
    for f in seqfiles:
        try: seqs.append(read_sxq(os.path.join(data, f)))
        except (ValueError, IndexError, struct.error) as ex: rep.skip(f"{f}: {str(ex)[:40]}")
    used = []
    for sq in seqs:
        for tr in sq["tracks"]:
            if tr["program"] in progs and tr["events"] and tr["program"] not in used: used.append(tr["program"])
    order = used + [n for n in progs if n not in used]
    keep = order[:NPROG]
    for n in order[NPROG:]: rep.skip(f"program '{n}' (only {NPROG} programs)")
    prog_map = {n: k for k, n in enumerate(keep)}
    wavs = {os.path.splitext(f)[0].upper(): os.path.join(data, f) for f in files if f.lower().endswith(".wav")}

    if backup: rep.backup = backup_project(E)
    with E.lock:
        if E.playing: E.stop()
        E.sources = []
        E.programs = [Program(i) for i in range(NPROG)]
        E.seqs = [Sequence(i) for i in range(NSEQ)]
        E.song, E.cur_seq, E.cur_track, E.bank, E.sel = [[0, 1]], 0, 0, 0, 0
        E._allpads = None
        E.v_data = [None] * E.nv
        E.warp_cache.clear()

        # ---- samples: each one a kept program uses, loaded once; MPC slices become CHOP markers
        need = {}
        for n in keep:
            for pad, pd in progs[n]["pads"].items():
                if pad <= 64: need.setdefault(pd["layers"][0]["sample"].upper(), []).append(pd["layers"][0])
        srcs = {}
        for key, layers in need.items():
            path_ = wavs.get(key)
            if path_ is None: rep.skip(f"sample '{layers[0]['sample']}' (file not in the project folder)"); continue
            try: raw, sr = load_wav(path_)
            except Exception as ex: rep.skip(f"sample '{layers[0]['sample']}': {str(ex)[:40]}"); continue
            r = OUT_SR / float(sr)
            x = resample(raw, sr, OUT_SR) if sr != OUT_SR else raw
            base = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in layers[0]["sample"])[:24] or "sample"
            nm, j = base, 2
            while E.source_by_name(nm) is not None: nm, j = f"{base}_{j}", j + 1
            s = E.add_source(nm, x, dirty=True)
            info = wav_slices(path_)
            s.mpc_slices = [(int(a * r), int(b * r)) for a, b in info["slices"]]
            s.mpc_default = tuple(int(v * r) for v in info["default"]) if info["default"] else None
            s.ratio = r
            used_slices = sorted({L["slice"] for L in layers if L["slice"] < 128})
            if used_slices and s.mpc_slices:                         # markers at every edge of the slices the pads use
                edges = sorted({e for k in used_slices if k < len(s.mpc_slices) for e in s.mpc_slices[k]} - {0, s.length})
                s.chops = [e for e in edges if 0 < e < s.length]
            srcs[key] = s
        rep.add(f"{len(srcs)} samples")

        # ---- programs
        pad_of = {}                                                      # (program index, note) -> pad index
        for n in keep:
            k = prog_map[n]; p = progs[n]; pr = E.programs[k]
            pr.name = n[:16]
            pv = p["volume"] / UNITY
            for padno, pd in sorted(p["pads"].items()):
                if padno > 64: rep.skip(f"{n}: pad {padno} (banks E-H: only A-D, 64 pads)"); continue
                i = padno - 1
                note = p["notes"].get(padno, 35 + padno)
                pad_of[(k, note)] = i
                L = pd["layers"][0]
                if len(pd["layers"]) > 1: rep.skip(f"{n}: pad {padno} layers 2-{len(pd['layers'])} (one sample per pad)")
                s = srcs.get(L["sample"].upper())
                if s is None: continue
                pad = pr.pads[i]
                a, b = _region(s, L)
                pad.assign(s, a, b)
                if s.chops and (a in [0] + s.chops) and (b in s.chops + [s.length]):
                    edges = [0] + s.chops + [s.length]
                    ia = edges.index(a)
                    if edges[ia + 1] == b: pad.link = (s.id, ia)        # follows the CHOP marker, like a pad you chopped here
                pad.lofi_on = False
                pad.tune = round(p["tune"] + pd["tune"] + L["tune"], 2)
                g = pv * (pd["volume"] / UNITY) * L["volume"]
                pad.vol = max(0.0, min(1.0, g))
                pad.gain_db = round(20 * np.log10(g), 2) if g > 1.0 else 0.0
                pad.pan = max(-1.0, min(1.0, (pd["pan"] - 0.5) * 2 + (L["pan"] - 0.5) * 2 + (p["pan"] - 0.5) * 2))
                pad.reverse = L["reverse"]
                pad.mode = "HOLD" if pd["trigger"] != 0 else "ONE"
                pad.vel_mpc = int(round(max(0.0, min(1.0, pd["vel_sens"])) * 100))
                if pd["attack"] > 0.001: pad.fade_in = int((pd["attack"] * 100) ** 2 / 2)
                pad.mute = pd["mute"]
                if pd["warp"] and pd["warp_bpm"] > 20:
                    pad.warp, pad.warp_bpm = True, round(pd["warp_bpm"], 3)
                if pd["cutoff"] < 0.995 and pd["filter"] not in (0, 2):  # (the MPC 2.x filter-type numbers are not known here:
                    pad.flt = "LP"                                       #  every type is played as a resonant low-pass)
                    pad.cutoff, pad.res = max(0.0, min(1.0, pd["cutoff"])), max(0.0, min(1.0, pd["resonance"]))
                    rep.skip(f"{n}: pad {padno} filter type {pd['filter']} played as a low-pass")
            groups = {}
            for padno, pd in p["pads"].items():
                if padno <= 64 and pd["mute_group"]: groups.setdefault(pd["mute_group"], []).append(padno - 1)
            for padno, pd in p["pads"].items():                       # mute targets: a pad and the pads it cuts share a group
                tg = [t - 1 for t in pd["mute_targets"] if 0 < t <= 64]
                if padno <= 64 and tg: groups.setdefault(("t", padno), []).extend([padno - 1] + tg)
            for g, (gid, members) in enumerate(sorted(groups.items(), key=str), 1):
                for i in members: pr.pads[i].choke = g
            for pad in pr.pads:
                if not pad.empty: pad.build()
            rep.add(f"program {k + 1}: {pr.name} ({sum(1 for x in pr.pads if not x.empty)} pads)")

        # ---- sequences
        for si, sq in enumerate(seqs[:NSEQ]):
            S = E.seqs[si]
            S.name = sq["name"][:16]
            S.bpm = sq["tempo"] or proj["bpm"]
            S.num, S.den = sq["num"], (sq["den"] if sq["den"] in (2, 4, 8, 16) else 4)
            scale = PPQ / float(sq["ppq"])
            last = max([e[0] for tr in sq["tracks"] for e in tr["events"]] + [0])
            S.bars = max(1, sq["bars"] or -(-int(last * scale + 1) // S.bar_ticks))
            S.swing, S.loop = 0.5, True
            tracks = [tr for tr in sq["tracks"] if tr["events"]]
            for tr in tracks[NTRACK:]: rep.skip(f"{S.name}: track '{tr['name']}' (only {NTRACK} tracks)")
            for ti, tr in enumerate(tracks[:NTRACK]):
                T = S.tracks[ti]
                T.name = (tr["name"] or f"Track {ti + 1:02d}")[:16]
                k = prog_map.get(tr["program"])
                if k is None:
                    rep.skip(f"{S.name}: track '{T.name}' plays '{tr['program']}' (not a drum program that was imported)")
                    T.events = []; continue
                T.prog = k
                p = progs[tr["program"]]
                out, lost = [], 0
                for tick, note, vel, ln in tr["events"]:
                    padno = pad_of.get((k, note))
                    if padno is None: lost += 1; continue
                    t96 = int(round(tick * scale))
                    if t96 >= S.length: continue
                    dur = max(1, min(int(round(ln * scale)), S.length - t96))
                    targets = [padno] + [t - 1 for t in p["pads"].get(padno + 1, {}).get("simult", []) if 0 < t <= 64]
                    for i in targets: out.append((t96, i, max(1, min(127, vel)), dur))
                T.events = sorted(set(out))
                if lost: rep.skip(f"{S.name}: {lost} notes on '{T.name}' with no pad in A-D")
            rep.add(f"sequence {si + 1}: {S.name}  {S.bpm:g} bpm  {S.bars} bars  {len(tracks[:NTRACK])} tracks  "
                    f"{sum(len(t.events) for t in S.tracks)} notes")
        for sq in seqs[NSEQ:]: rep.skip(f"sequence '{sq['name']}' (only {NSEQ} sequences)")
        E.song = [[i, 1] for i in range(min(len(seqs), NSEQ))] or [[0, 1]]
        if seqs: rep.add("song: every sequence once, in order (MPC 2.x songs are not read yet)")
    E.save_project()
    E.say("MPC project imported")
    return rep


def _region(s, L):
    """(start, end) of a layer's sample region in the 44.1 kHz source"""
    k = L["slice"]
    if k < 128 and k < len(s.mpc_slices): a, b = s.mpc_slices[k]
    elif k == 129 and L["slice_end"] > L["slice_start"]: a, b = int(L["slice_start"] * s.ratio), int(L["slice_end"] * s.ratio)
    elif s.mpc_default and s.mpc_default[1] > s.mpc_default[0]: a, b = s.mpc_default
    else: a, b = 0, s.length
    a = max(0, min(a, s.length - 2)); b = max(a + 2, min(b, s.length))
    return a, b
