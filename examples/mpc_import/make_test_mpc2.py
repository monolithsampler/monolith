"""
Write a tiny MPC 2.x project (TEST.xpj + TEST_[ProjectData]/ with WAVs, a drum .xpm and .sxq sequences) for the
importer's tests, in the same shapes MPC 2.15 writes.

    python3 examples/mpc_import/make_test_mpc2.py /tmp/TEST2
"""
import json, os, struct, sys
import numpy as np


def write_wav(path, x, sr=44100, bits=16, slices=None, default=None):
    """stereo or mono WAV, 16 or 24 bit, with an MPC 'atem' slice chunk when slices are given"""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1: x = x[:, None]
    ch = x.shape[1]
    q = np.clip(x, -1, 1)
    if bits == 16: data = (q * 32767).astype("<i2").tobytes()
    else:
        v = (q * 8388607).astype(np.int32).reshape(-1)
        data = np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], axis=1).astype(np.uint8).tobytes()
    fmt = struct.pack("<HHIIHH", 1, ch, sr, sr * ch * bits // 8, ch * bits // 8, bits)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if slices is not None or default is not None:
        v0 = {"defaultSlice": {"Start": (default or (0, len(x)))[0], "End": (default or (0, len(x)))[1]},
              "numBars": 2, "Num slices": len(slices or [])}
        for k, (a, b) in enumerate(slices or []): v0[f"Slice {k}"] = {"Start": a, "End": b, "LoopStart": a}
        j = json.dumps({"version": 1, "value0": v0}, indent=4).encode()
        if len(j) & 1: j += b"\x00"
        chunks += b"atem" + struct.pack("<I", len(j)) + j
    chunks += b"data" + struct.pack("<I", len(data)) + data
    open(path, "wb").write(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)


def instrument(n, sample=None, slice_index=128, volume=0.707946, pan=0.5, coarse=0, fine=0, layer_coarse=0,
               warp=False, warp_bpm=120.0, mute_group=0, simult=(), trigger=0, attack=0.0, direction=0):
    lay = ""
    for k in range(1, 5):
        name = sample if (k == 1 and sample) else ""
        lay += f"""          <Layer number="{k}">
            <Active>True</Active><Volume>1.000000</Volume><Pan>0.500000</Pan><Pitch>{layer_coarse}.000000</Pitch>
            <TuneCoarse>{layer_coarse if name else 0}</TuneCoarse><TuneFine>0</TuneFine><VelStart>0</VelStart><VelEnd>127</VelEnd>
            <SampleStart>0</SampleStart><SampleEnd>0</SampleEnd><SampleName>{name}</SampleName><SampleFile></SampleFile>
            <SliceIndex>{slice_index}</SliceIndex><Direction>{direction}</Direction><SliceStart>0</SliceStart><SliceEnd>0</SliceEnd>
          </Layer>
"""
    st = "".join(f"<SimultTarget{k}>{(list(simult) + [0, 0, 0, 0])[k - 1]}</SimultTarget{k}>" for k in range(1, 5))
    return f"""      <Instrument number="{n}">
        <Volume>{volume:.6f}</Volume><Pan>{pan:.6f}</Pan><FilterType>2</FilterType><Cutoff>1.000000</Cutoff><Resonance>0.000000</Resonance>
        <VolumeAttack>{attack:.6f}</VolumeAttack><VolumeDecay>0.047244</VolumeDecay><VolumeSustain>1.000000</VolumeSustain>
        <VelocitySensitivity>1.000000</VelocitySensitivity><TuneCoarse>{coarse}</TuneCoarse><TuneFine>{fine}</TuneFine>
        <MuteGroup>{mute_group}</MuteGroup><MuteTarget1>0</MuteTarget1><MuteTarget2>0</MuteTarget2><MuteTarget3>0</MuteTarget3><MuteTarget4>0</MuteTarget4>
        {st}<TriggerMode>{trigger}</TriggerMode><WarpTempo>{warp_bpm:.6f}</WarpTempo><WarpEnable>{"True" if warp else "False"}</WarpEnable>
        <Layers>
{lay}        </Layers>
      </Instrument>
"""


def write_xpm(path, name, inst, kind="Drum"):
    ins = "".join(instrument(n, **inst.get(n, {})) for n in range(1, 129)) if kind == "Drum" else ""
    pads = "".join(f'      <PadNote number="{n}"><Note>{35 + n}</Note></PadNote>\n' for n in range(1, 129))
    open(path, "w", encoding="utf-8", newline="\r\n").write(f"""<?xml version="1.0" encoding="UTF-8"?>

<MPCVObject>
  <Version><File_Version>2.1</File_Version><Application>MPC-V</Application><Application_Version>2.15.1.1</Application_Version></Version>
  <Program type="{kind}">
    <ProgramName>{name}</ProgramName>
    <Volume>0.707946</Volume><Pan>0.500000</Pan><TuneCoarse>0</TuneCoarse><TuneFine>0</TuneFine>
    <Instruments>
{ins}    </Instruments>
    <PadNoteMap>
{pads}    </PadNoteMap>
  </Program>
</MPCVObject>
""")


def _vlq(n):
    out = [n & 0x7F]; n >>= 7
    while n: out.insert(0, (n & 0x7F) | 0x80); n >>= 7
    return bytes(out)


def _meta(dt, typ, data): return _vlq(dt) + bytes([0xFF, typ]) + _vlq(len(data)) + data


def _track(events):
    body = b"".join(events) + _meta(0, 0x2F, b"")
    return b"MTrk" + struct.pack(">I", len(body)) + body


def write_sxq(path, name, bpm, bars, tracks):
    """tracks: [(track name, program name, [(tick960, note, velocity)])]"""
    us = int(round(60e6 / bpm))
    t0 = [_meta(0, 0x7F, b"Ga\n\x00\x06" + b"\x00" * 14), _meta(0, 0x03, name.encode() + b"\x00"), _meta(0, 0x59, b"\x00\x00"),
          _meta(0, 0x51, us.to_bytes(3, "big")), _meta(0, 0x7F, b"Ga\x00\x00" + struct.pack("<H", bars) + b"\x01\x00" + struct.pack("<H", bars + 1) + b"\x01\x00\x00\x00\x00"),
          _meta(0, 0x58, b"\x04\x02\x01\x04")]
    trk = [_track(t0)]
    for ti, (tname, prog, evs) in enumerate(tracks):
        setup = b"Ga\x10\x02" + bytes([ti]) + b"\x00\x00\tAll Ports\x00\x03OSX\x00" + b"1" * 128 + b"\x06\x00d\x00\x00\x00\x00\x00\x10\x7f@" + bytes([len(prog)]) + prog.encode()
        ev = [_meta(0, 0x03, tname.encode() + b"\x00"), _meta(0, 0x7F, setup), _meta(0, 0x70, b"\x00")]
        last = 0
        for tick, note, vel in sorted(evs):
            ev.append(_meta(tick - last, 0x7F, b"Ga\x11\x02" + bytes([note, vel]) + b"\x00\x00\x00" + struct.pack("<I", 960) + b"\x00" * 6 + b"d"))
            last = tick
        trk.append(_track(ev))
    trk.append(_track([_meta(0, 0x7F, b"Ga\x13" + bytes([len(prog) + 2, 0]) + prog.encode() + b"\x00\x00") for _, prog, _ in tracks[:1]]))
    open(path, "wb").write(b"MThd" + struct.pack(">IHHH", 6, 1, len(trk), 960) + b"".join(trk))


def make(folder):
    os.makedirs(folder, exist_ok=True)
    data = os.path.join(folder, "TEST_[ProjectData]")
    os.makedirs(data, exist_ok=True)
    t = np.arange(8820) / 44100.0
    kick = 0.9 * np.sin(2 * np.pi * 55 * t) * np.exp(-t * 25)
    write_wav(os.path.join(data, "Kick.WAV"), np.stack([kick, kick], 1), bits=24, default=(0, len(kick)))
    loop = np.random.default_rng(3).uniform(-0.3, 0.3, 48000).astype(np.float32)
    write_wav(os.path.join(data, "Break.WAV"), loop, sr=48000, slices=[(0, 12000), (12000, 24000), (24000, 36000), (36000, 48000)],
              default=(0, 48000))
    write_xpm(os.path.join(data, "Kit.Drum.xpm"), "Kit", {
        1: dict(sample="Kick", coarse=-2, fine=50, volume=0.707946 * 0.5, pan=0.25, mute_group=1, simult=(4,)),
        2: dict(sample="Break", slice_index=0, warp=True, warp_bpm=90.0, mute_group=1),
        3: dict(sample="Break", slice_index=1, warp=True, warp_bpm=90.0, attack=0.2, direction=1),
        4: dict(sample="Break", slice_index=3, trigger=1, layer_coarse=3),
        70: dict(sample="Kick")})
    write_xpm(os.path.join(data, "Audio 001.Audio.xpm"), "Audio 001", {}, kind="Audio")
    write_sxq(os.path.join(data, "1.sxq"), "Verse", 92.0, 2, [("Drums", "Kit", [(0, 36, 100), (960, 37, 80), (1920, 38, 127), (2880, 105, 90)]),
                                                               ("Vox", "Audio 001", [])])
    write_sxq(os.path.join(data, "2.sxq"), "Hook", 92.0, 1, [("Drums", "Kit", [(0, 39, 64)])])
    open(os.path.join(folder, "TEST.xpj"), "w", encoding="utf-8", newline="\r\n").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n\n<Project>\n  <Version><Application_Version>2.15.1.1</Application_Version></Version>\n'
        '  <BPM>92.000000</BPM>\n  <FileList><File>./TEST_[ProjectData]/1.sxq</File></FileList>\n</Project>\n')
    return os.path.join(folder, "TEST.xpj")


if __name__ == "__main__":
    print(make(sys.argv[1] if len(sys.argv) > 1 else "TEST2"))
