"""
sp1200_import.py - load Rossum SP-1200 projects (.sp12, firmware 1.04) into Monolith.

No format description is published. This layout was worked out from four real .sp12 files and the SP-1200 firmware
(Z80, "Main FW Rev 1.04"), which reads and writes the same memory. An .sp12 file is a snapshot of the SP's memory:

  0x0000-0x9110   Z80 RAM 0x6EF0-0xFFFF: sequencer memory
                    0x6F00 end of used sequence memory      0x6F04 100 x 2 bytes: where segment 00-99 starts
                    0x7194.. segments: 4-byte header (byte 1 = beats per bar, bytes 2-3 = length in ticks, 96 per beat),
                    then control bytes and events (see read_segment)
  0x9110-0x94E2   Z80 RAM 0x6B2C-0x6EFE: sound / pad settings
                    0x6B30 32 x 6 bytes pad names       0x6BF0 32 x 4 bytes: start, end (samples inside the pad's slot)
                    0x6C7E 32 x 10 bytes: pad record (byte 1, low 3 bits = memory slot 0-7)
  0x94E2-end      sample memory: 2^19 12-bit samples (20.1 s at 26.04 kHz), packed two per three bytes
                  (high byte, high byte, the two low nibbles), in 8 slots of 65,536 samples (2.5 s each)

Pad numbers (0-31) follow the file's order: D1-D8, C1-C8, B1-B8, A1-A8.
"""
import os, struct
import numpy as np

SP_RATE = 26040
RAM_SEQ, RAM_PAR = 0x6EF0, 0x6B2C
FILE_PAR, FILE_SND = 0x9110, 0x94E2
SLOT = 65536
NAMES = [b + str(i) for b in "DCBA" for i in range(1, 9)]


def _seq(ram): return ram - RAM_SEQ
def _par(ram): return ram - RAM_PAR + FILE_PAR


def is_sp12(path):
    return path.lower().endswith(".sp12") and os.path.getsize(path) == FILE_SND + 3 * (1 << 18)


def sample_memory(b):
    t = np.frombuffer(b, dtype=np.uint8, offset=FILE_SND).astype(np.int32).reshape(-1, 3)
    x = np.stack([(t[:, 0] << 4) | (t[:, 2] >> 4), (t[:, 1] << 4) | (t[:, 2] & 15)], 1).ravel()
    return (x - 2048).astype(np.float32) / 2048.0


def read_pads(b):
    pads = []
    for i in range(32):
        a, e = struct.unpack_from("<HH", b, _par(0x6BF0) + 4 * i)
        rec = b[_par(0x6C7E) + 10 * i:_par(0x6C7E) + 10 * i + 10]
        name = bytes(c & 0x7F for c in b[_par(0x6B30) + 6 * i:_par(0x6B30) + 6 * i + 6]).decode("ascii", "replace").strip()
        pads.append({"index": i, "label": NAMES[i], "name": name, "start": a, "end": e, "slot": rec[1] & 7,
                     "level_byte": rec[0], "flags": rec[1], "used": e != a and (e or a), "reverse": 0 < e < a})
    return pads


def read_segment(b, ptr):
    """one segment: {'beats', 'length', 'events': [(tick, pad 0-31, level 0-127, raw byte)]}"""
    o = _seq(ptr)
    hdr = b[o:o + 4]
    seg = {"flags": hdr[0], "beats": hdr[1] or 4, "length": hdr[2] | (hdr[3] << 8), "events": []}
    i, t, prev = o + 4, 0, 0x40
    end = _seq(struct.unpack_from("<H", b, 0x10)[0])
    while i < min(end, _seq(0x10000)):
        c = b[i]; i += 1
        if c & 1: break                                             # end of segment
        pos = c >> 2                                                # a clock that wraps every 64 ticks
        d = pos - prev
        t += 64 if d == 0 else d & 0x3F
        prev = pos
        if c & 2:                                                   # events at this time
            while i < end:
                e = b[i]; i += 1
                x = None
                if e & 0x40: x = b[i]; i += 1
                lvl = 127 if (x is None or x & 0xF0 == 0) else max(1, round((x >> 4) * 127 / 15))
                seg["events"].append((t, e & 0x1F, lvl, e))
                if e & 0x80: break
    if not seg["length"]: seg["length"] = t
    return seg


def read_project(path):
    b = open(path, "rb").read()
    if len(b) != FILE_SND + 3 * (1 << 18): raise ValueError("not a Rossum SP-1200 .sp12 project")
    segs = {}
    for n in range(100):
        ptr = struct.unpack_from("<H", b, _seq(0x6F04) + 2 * n)[0]
        if 0x7194 <= ptr < 0xFFFF:
            try: segs[n] = read_segment(b, ptr)
            except IndexError: pass
    return {"pads": read_pads(b), "segments": segs, "memory": sample_memory(b)}


def describe(path):
    p = read_project(path)
    return f"SP-1200: {len(p['segments'])} seq, {sum(1 for x in p['pads'] if x['used'])} pads with sounds"


def import_project(E, path, report=None, backup=True):
    """Replace the engine's project with a Rossum SP-1200 project. Returns a Report."""
    from engine import OUT_SR, NPROG, NSEQ, NTRACK, resample, Program, Sequence
    from mpc_import import Report, backup_project
    rep = report or Report()
    p = read_project(path)
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
        mem = p["memory"]
        r = OUT_SR / float(SP_RATE)
        srcs = {}
        for pd in p["pads"]:                                        # one source per memory slot a pad plays from
            if pd["used"] and pd["slot"] not in srcs:
                k = pd["slot"]
                srcs[k] = E.add_source(f"SP_slot{k + 1}", resample(mem[k * SLOT:(k + 1) * SLOT], SP_RATE, OUT_SR), dirty=True)
        rep.add(f"{len(srcs)} sample slots")
        pr = E.programs[0]; pr.name = os.path.splitext(os.path.basename(path))[0][:16]
        for pd in p["pads"]:
            if not pd["used"]: continue
            bank, num = "DCBA".index(pd["label"][0]), int(pd["label"][1])
            pad = pr.pads[(3 - bank) * 16 + (num - 1)]                # SP bank A pads 1-8 -> A01-A08, B -> B01-B08 ...
            s = srcs[pd["slot"]]
            lo, hi = sorted((pd["start"], pd["end"]))                # end before start: a reversed sound
            a, e = int(lo * r), min(int(hi * r), s.length)
            pad.assign(s, a, max(a + 2, e))
            pad.reverse = pd["reverse"]
            pad.lofi_on = True                                       # it is SP-1200 audio: keep the 12-bit / 26 kHz sound
            pad.vel_mpc = 100
        rep.add(f"program 1: {pr.name} ({sum(1 for x in pr.pads if not x.empty)} pads)")
        padmap = {i: (3 - "DCBA".index(NAMES[i][0])) * 16 + int(NAMES[i][1]) - 1 for i in range(32)}
        segs = sorted(p["segments"].items())
        for si, (n, sg) in enumerate(segs[:NSEQ]):
            S = E.seqs[si]
            S.name = f"Segment {n:02d}"
            S.num, S.den = max(1, sg["beats"]), 4
            S.bars = max(1, -(-sg["length"] // S.bar_ticks))
            S.bpm, S.swing, S.loop = 90.0, 0.5, True
            T = S.tracks[0]; T.name, T.prog = "SP-1200", 0
            out, silent = [], 0
            for t, pad_i, lvl, raw in sg["events"]:
                i = padmap[pad_i]
                if pr.pads[i].empty: silent += 1; continue
                if t < S.length: out.append((t, i, lvl, 24))
            T.events = sorted(set(out))
            if silent: rep.skip(f"{S.name}: {silent} hits on pads without a sound")
            rep.add(f"sequence {si + 1}: {S.name}  {S.num}/4  {S.bars} bars  {len(T.events)} notes")
        for n, _ in segs[NSEQ:]: rep.skip(f"segment {n:02d} (only {NSEQ} sequences)")
        E.song = [[i, 1] for i in range(min(len(segs), NSEQ))] or [[0, 1]]
        rep.skip("tempo is not stored in the .sp12 file as far as is known: sequences are set to 90 bpm")
        rep.skip("per-pad tune, decay and level, songs and swing are not read yet")
    E.save_project()
    E.say("SP-1200 project imported")
    return rep
