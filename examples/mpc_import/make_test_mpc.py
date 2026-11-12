"""
Write a tiny MPC2000XL project (.SND, .APS, .ALL) byte by byte, for the importer's tests.
Only the fields the importer reads are filled in; everything else is zero, as on a fresh MPC.

    python3 examples/mpc_import/make_test_mpc.py /tmp/TESTMPC
"""
import os, struct, sys
import numpy as np


def _name(s, n=16, pad=b" "): return s.encode("ascii")[:n].ljust(n, pad)


def write_snd(path, name, data, rate=44100, level=100, tune=0, start=0, stereo=False):
    data = np.asarray(data, dtype=np.float32)
    frames = data.shape[0]
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    body = (np.concatenate([pcm[:, 0], pcm[:, 1]]) if stereo else pcm).tobytes()
    hdr = b"\x01\x04" + _name(name) + b"\x00" + bytes([level]) + struct.pack("<b", tune) + bytes([1 if stereo else 0])
    hdr += struct.pack("<IIII", start, frames, frames, 0) + b"\x00\x04" + struct.pack("<H", rate)
    assert len(hdr) == 42
    open(path, "wb").write(hdr + body)


def note_block(sound=None, mode=0, vel_lo=44, also1=0, vel_hi=88, also2=0, overlap=0, mute1=0, mute2=0, tune=0,
               attack=0, decay=5, decay_mode=0, cutoff=100, resonance=0, vel_level=100):
    snd = struct.pack("<H", 0xFFFF if sound is None else sound)
    return snd + struct.pack("<BBBBBBBBhBBBBBBBBBBBBBB", mode, vel_lo, also1, vel_hi, also2, overlap, mute1, mute2, tune,
                             attack, decay, decay_mode, cutoff, resonance, 0, 0, 0, vel_level, 0, 0, 0, 0, 0)


def program_body(name, notes, pads, mixers=None):
    """notes: {midi note: note_block kwargs}; pads: 64 notes (or -1); mixers: {note: (volume, pan)}"""
    b = b"\x00" * 5 + _name(name) + b"\x00" + b"\x00" * 9 + b"\x00" + b"\x00" * 5
    for n in range(35, 99): b += note_block(**notes.get(n, {}))
    b += b"\x00"
    for n in range(35, 99):
        vol, pan = (mixers or {}).get(n, (100, 50))
        b += bytes([0, vol, pan, 100, 0, 0])
    b += b"\x00" * 3 + bytes(p & 0xFF for p in pads) + b"\x00" * 200
    assert len(b) == 2353
    return b


def write_aps(path, sounds, programs, drums):
    """programs: {index: body bytes}; drums: program index for DRUM 1-4"""
    b = b"\x0a\x05" + struct.pack("<H", len(sounds)) + b"".join(_name(s) + b"\x00" for s in sounds)
    b += b"\x00\x00" + _name("TESTAPS") + b"\x00" + b"\x00" * 7 + b"\x00" + bytes(range(35, 99)) + b"\x00" * 7
    for d in range(4):
        b += b"".join(bytes([0, 100, 50, 100, 0, 0]) for _ in range(64)) + b"\x00\x00" + bytes([0, 0, 0, drums[d], 0, 0])
        b += b"\x00" * (4 if d < 3 else 1)
    for idx in sorted(programs): b += bytes([idx]) + programs[idx]
    b += b"\xff"
    open(path, "wb").write(b)


def _event(tick, track, note, dur, vel):
    v = tick | ((dur >> 10) & 0xF) << 20 | (track & 0x3F) << 24 | ((dur >> 8) & 0x3) << 30
    return struct.pack("<I", v) + bytes([note, dur & 0xFF, vel & 0x7F, 64])


def write_all(path, seqs, songs=(), master_tempo=120.0):
    """seqs: {slot: dict(name, tempo, bars, tracks={n: dict(name, bus, device, velocity, on)}, events=[(tick, track, note, dur, vel)])}"""
    b = bytearray(14406)
    b[:16] = b"MPC2KXL ALL 1.00"
    struct.pack_into("<H", b, 1812, int(master_tempo * 10)); b[1814] = 1
    b[1840], b[1841] = 127, 64                          # metronome accent / normal velocity (must be 1-127)
    for slot, sq in seqs.items():
        b[2064 + 18 * slot:2064 + 18 * slot + 16] = _name(sq["name"])
        struct.pack_into("<H", b, 2064 + 18 * slot + 16, 641 + len(sq["events"]) // 2)
    for i in range(20):
        o = 3846 + 528 * i
        b[o:o + 16] = _name(f"Song{i + 1:02d}")
        for k in range(250): b[o + 16 + 2 * k] = 0xFF
    for i, (name, steps) in enumerate(songs):
        o = 3846 + 528 * i
        b[o:o + 16] = _name(name)
        for k, (sq, rep) in enumerate(steps): b[o + 16 + 2 * k], b[o + 17 + 2 * k] = sq, rep
        b[o + 518] = 1
    for slot in sorted(seqs):
        sq = seqs[slot]
        h = bytearray(10240)
        h[:16] = _name(sq["name"])
        struct.pack_into("<H", h, 16, 641); h[18] = slot + 1
        struct.pack_into("<H", h, 22, int(round(sq["tempo"] * 10)))
        struct.pack_into("<H", h, 26, sq["bars"])
        last = sq["bars"] * 384
        struct.pack_into("<I", h, 28, last); struct.pack_into("<I", h, 64, last)
        struct.pack_into("<HH", h, 48, 0, 0xFFFF); h[52] = 1
        for t in range(64):
            info = sq["tracks"].get(t, {})
            h[384 + 16 * t:384 + 16 * t + 16] = _name(info.get("name", f"Track-{t + 1:02d}"))
            h[384 + 1024 + t] = info.get("device", 0)
            h[384 + 1088 + t] = info.get("bus", 1)
            h[384 + 1216 + t] = info.get("velocity", 100)
            h[384 + 1280 + t] = (1 if t in sq["tracks"] else 0) | (2 if info.get("on", True) else 0)
        for i in range(sq["bars"]):
            h[5379 + 4 * i] = 96; v = (i + 1) * 384
            h[5380 + 4 * i:5383 + 4 * i] = bytes([v & 0xFF, (v >> 8) & 0xFF, v >> 16])
        ev = b"".join(_event(*e) for e in sorted(sq["events"]))
        term = b"\xff" * 8 * (2 if len(sq["events"]) % 2 == 0 else 1)
        b += h + ev + term
    open(path, "wb").write(bytes(b))


def make(folder):
    os.makedirs(folder, exist_ok=True)
    t = np.arange(4410) / 44100.0
    kick = 0.9 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 30)
    write_snd(os.path.join(folder, "KICK.SND"), "kick", kick)
    th = np.arange(2205) / 22050.0
    hat = (np.random.default_rng(1).uniform(-0.5, 0.5, (len(th), 2)) * np.exp(-th * 40)[:, None])
    write_snd(os.path.join(folder, "HAT.SND"), "hat", hat, rate=22050, tune=10, start=100, stereo=True)
    sounds = ["kick", "hat", "missing"]
    pads = [-1] * 64
    pads[0], pads[1], pads[2], pads[3], pads[4], pads[63] = 37, 36, 46, 42, 44, 37      # pad 64 repeats note 37: a spare pad
    kit = program_body("KIT", {37: dict(sound=0, tune=-25, decay=20),
                               36: dict(sound=1, mute1=46), 46: dict(sound=1, overlap=2, decay_mode=1, attack=10, decay=30),
                               42: dict(sound=1, mode=1, also1=37),
                               44: dict(sound=0, mode=2, vel_lo=64, also1=45, vel_hi=127), 45: dict(sound=1, cutoff=40),
                               70: dict(sound=0), 71: dict(sound=2)},
                       pads, mixers={37: (80, 25)})
    empty = program_body("EMPTY", {}, list(range(35, 99)))
    write_aps(os.path.join(folder, "ALL_PGMS.APS"), sounds, {0: empty, 1: kit}, drums=[1, 0, 0, 0])
    beat = {"name": "BEAT", "tempo": 93.5, "bars": 2,
            "tracks": {0: {"name": "Drums", "bus": 1}, 1: {"name": "Keys", "bus": 0, "device": 2},
                       2: {"name": "Soft", "bus": 1, "velocity": 50}, 3: {"name": "Off", "bus": 1, "on": False}},
            "events": [(0, 0, 37, 24, 100), (96, 0, 42, 24, 100), (192, 0, 44, 24, 30), (288, 0, 44, 24, 100),
                       (384, 0, 70, 24, 100), (0, 1, 60, 96, 90), (0, 2, 37, 24, 100), (480, 3, 36, 24, 100)]}
    fill = {"name": "FILL", "tempo": 100.0, "bars": 1, "tracks": {0: {"name": "Drums", "bus": 1}},
            "events": [(0, 0, 36, 24, 127), (192, 0, 37, 24, 127)]}
    write_all(os.path.join(folder, "ALL_SEQS.ALL"), {0: beat, 2: fill}, songs=[("SONG A", [(0, 2), (2, 1)])])
    return folder


if __name__ == "__main__":
    print(make(sys.argv[1] if len(sys.argv) > 1 else "TESTMPC"))
