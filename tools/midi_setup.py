#!/usr/bin/env python3
"""
midi_setup.py - maps a MIDI controller (e.g. an Akai MPK249) to the sampler from the terminal, before Monolith starts.
It asks you to move each control in turn and saves the result to midi.json (the same file the MIDI page uses).

    python3 tools/midi_setup.py              # step through the controls; press Enter to skip one
    python3 tools/midi_setup.py --monitor    # just show what the controller sends (Ctrl+C to stop)

Stop Monolith first (sudo systemctl stop sampler-os) - only one program can read the controller at a time.
"""
import argparse, glob, os, select, sys, termios, time, tty
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from midi import MidiMap, Parser, MidiIO

STEPS = [  # target, what to do, kind wanted
    ("Q1", "Sampler knob Q1 (the sampler's 1st knob): turn a knob, e.g. K1 on an MPK249", "cc"),
    ("Q2", "Sampler knob Q2: turn a knob, e.g. K2", "cc"),
    ("Q3", "Sampler knob Q3: turn a knob, e.g. K3", "cc"), ("Q4", "Sampler knob Q4: turn a knob, e.g. K4", "cc"),
    ("JOG", "JOG wheel (scrolls lists and values): turn a knob, e.g. K5", "cc"),
    ("F1", "Soft key F1 (under the screen): press a button, e.g. S1 under the MPK249's faders", "any"),
    ("F2", "Soft key F2: press a button, e.g. S2", "any"),
    ("F3", "Soft key F3: press a button, e.g. S3", "any"), ("F4", "Soft key F4 (BACK): press a button, e.g. S4", "any"),
    ("SHIFT", "SHIFT: press a button, e.g. S5", "any"), ("UNDO", "UNDO: press a button, e.g. S6", "any"),
    ("NOTE REPEAT", "NOTE REPEAT: press a button, e.g. S7", "any"), ("TAP", "TAP tempo: press a button, e.g. S8", "any"),
    ("BANK", "Pad BANK: press any spare button", "any"),
]


def open_devices():
    fds = {}
    for p in sorted(glob.glob("/dev/snd/midiC*D*")):
        try: fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = (p, Parser())
        except OSError as ex: print("cannot open", p, ex)
    return fds


def messages(fds, timeout):
    r, _, _ = select.select(list(fds), [], [], timeout)
    for fd in r:
        try: data = os.read(fd, 256)
        except OSError: continue
        for m in fds[fd][1].feed(data):
            if m[0] < 0xF8: yield fds[fd][0], m


def describe(m):
    st = m[0]
    if st == 0xF0: return "SysEx / MMC " + " ".join(f"{b:02X}" for b in m)
    k, ch = st & 0xF0, (st & 0x0F) + 1
    names = {0x80: "note off", 0x90: "note on", 0xA0: "poly pressure", 0xB0: "CC", 0xC0: "program", 0xD0: "pressure", 0xE0: "pitch bend"}
    return f"{names.get(k, hex(st))} ch {ch} " + " ".join(str(b) for b in m[1:])


def key_pressed():
    return select.select([sys.stdin], [], [], 0)[0] and sys.stdin.read(1)


def pad_place(n):
    """where pad n sits on a 4 x 4 grid, numbered from the bottom-left like the sampler (and an MPC)"""
    row = ["bottom row", "2nd row from the bottom", "3rd row from the bottom", "top row"][(n - 1) // 4]
    col = ["left", "2nd from the left", "3rd from the left", "right"][(n - 1) % 4]
    return f"{row}, {col}"


def learn_pads(fds, mp):
    """hit the 16 pads in order: any controller layout works. Enter after pad 1 = the old way (pad 1 + the notes after it)."""
    print("PADS: hit each pad once, in order (pad bank A on the controller). Enter = stop early, s = skip the pads.")
    got = []
    while len(got) < 16:
        n = len(got) + 1
        print(f"  Pad {n:>2} ({pad_place(n)}) ... ", end="", flush=True)
        for _ in messages(fds, 0.05): pass
        hit = None
        while hit is None:
            k = key_pressed()
            if k in ("\n", "\r", "s", "q"): break
            for p, m in messages(fds, 0.05):
                if m[0] & 0xF0 == 0x90 and m[2] > 0:
                    c = ((m[0] & 0x0F) + 1, m[1])
                    if list(c) in got: print(f"\n    (that pad is already pad {got.index(list(c)) + 1}: hit pad {n}) ... ", end="", flush=True); continue
                    hit = list(c); break
        if hit is None:
            print("stopped" if got else "skipped"); break
        got.append(hit); print(f"note {hit[1]}, channel {hit[0]}")
        time.sleep(0.15)
    if len(got) == 16: mp.set_pads(got)
    elif got:                                                    # only some: pad 1 sets channel + first note, the rest follow it
        mp.set_pads([]); mp.pad_ch, mp.pad_base = got[0]
    return len(got)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", action="store_true")
    a = ap.parse_args()
    fds = open_devices()
    if not fds: sys.exit("No MIDI devices found. Plug in the controller (and stop Monolith if it is running).")
    print("MIDI devices:", ", ".join(MidiIO.device_name(p) for p, _ in fds.values()))
    if a.monitor:
        print("Move anything on the controller (Ctrl+C to stop)")
        try:
            while True:
                for p, m in messages(fds, 0.5): print(f"{os.path.basename(p):>12}  {describe(m)}")
        except KeyboardInterrupt: return
    mp = MidiMap(os.path.join(HERE, "midi.json"))
    print("\nThe names in capitals are the sampler's own controls (Q1-Q4 are its four knobs). For each one, move the control on\n"
          "your controller that should do that job. Enter = skip (keep what is set), q = stop and save.\n"
          "Tip: buttons on the MPK249 work best set to MOMENTARY in its edit mode (latching buttons also work).\n")
    old = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    try:
        npads = learn_pads(fds, mp)
        print()
        for target, prompt, want in STEPS:
            cur = mp.learned.get(target)
            print(f"{prompt}" + (f"   [now: {cur[0]} {cur[2]} ch {cur[1]}]" if cur else "") + " ... ", end="", flush=True)
            for _ in messages(fds, 0.05): pass                   # drop anything already queued
            got, quit_ = None, False
            while got is None:
                k = key_pressed()
                if k in ("\n", "\r"): break
                if k == "q": quit_ = True; break
                for p, m in messages(fds, 0.05):
                    kind, ch = m[0] & 0xF0, (m[0] & 0x0F) + 1
                    if kind == 0x90 and m[2] > 0 and want in ("note", "any"): got = ("note", ch, m[1]); break
                    if kind == 0xB0 and want in ("cc", "any") and (want == "cc" or m[2] > 0): got = ("cc", ch, m[1]); break
                    if m[0] == 0xF0: print("\n  (that sent MMC transport - PLAY / STOP / REC already work that way, no setup needed) ", end="")
            if quit_: print("stopped"); break
            if got is None: print("skipped"); continue
            kind, ch, num = got
            for t in [t for t, v in mp.learned.items() if v == [kind, ch, num]]: del mp.learned[t]
            mp.learned[target] = [kind, ch, num]
            print(f"{'CC' if kind == 'cc' else 'note'} {num}, channel {ch}")
            time.sleep(0.4)                                       # let a knob finish moving before the next step
            for _ in messages(fds, 0.2): pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
    mp.save()
    if mp.pad_list: print(f"\nSaved to {mp.path}. All 16 pads learned; the controller's pad banks B-D reach banks B-D when they shift the notes by 16.")
    else: print(f"\nSaved to {mp.path}. Pads: channel {mp.pad_ch}, pad 1 = note {mp.pad_base}, the other pads the notes after it.")
    print("Keys on any other channel play the current pad chromatically; PLAY / STOP / REC work through MMC.")


if __name__ == "__main__":
    main()
