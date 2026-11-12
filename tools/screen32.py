"""screen32.py - make the Pi's screen 32-bit colour (run once with sudo, then reboot).

The Pi's framebuffer starts in 16-bit colour, where grey gradients band into pink, green and blue (Monolith dithers to
hide it, but 32-bit is the real fix). The KMS driver only takes the colour depth from the boot line, so this adds
    video=<connector>:<width>x<height>M-32
to cmdline.txt for the connected screen, at the mode it is running now. A copy of cmdline.txt is kept next to it
(cmdline.txt.monolith-backup); to undo, copy that back and reboot.

    sudo python3 tools/screen32.py          show what it will do and do it
    sudo python3 tools/screen32.py --undo   put the backup back
"""
import glob, os, re, shutil, sys

CMD = next((p for p in ("/boot/firmware/cmdline.txt", "/boot/cmdline.txt") if os.path.exists(p)), None)


def screen():
    for st in sorted(glob.glob("/sys/class/drm/card*-*/status")):
        if open(st).read().strip() != "connected": continue
        d = os.path.dirname(st)
        conn = re.sub(r"^card\d+-", "", os.path.basename(d))
        modes = [m.strip() for m in open(os.path.join(d, "modes")).read().split() if m.strip()]
        if modes: return conn, modes[0]
    return None, None


def main():
    if CMD is None: sys.exit("no cmdline.txt found (/boot/firmware or /boot): is this a Raspberry Pi?")
    bak = CMD + ".monolith-backup"
    if "--undo" in sys.argv:
        if not os.path.exists(bak): sys.exit("no backup to put back")
        shutil.copy(bak, CMD); print("cmdline.txt restored - reboot to finish"); return
    bpp = open("/sys/class/graphics/fb0/bits_per_pixel").read().strip() if os.path.exists("/sys/class/graphics/fb0") else "?"
    conn, mode = screen()
    if conn is None: sys.exit("no connected screen found under /sys/class/drm")
    line = open(CMD).read().strip()
    new = " ".join(w for w in line.split() if not w.startswith(f"video={conn}:")) + f" video={conn}:{mode}M-32"
    print(f"screen: {conn} at {mode}, now {bpp}-bit")
    print(f"cmdline.txt gets: video={conn}:{mode}M-32")
    if os.geteuid() != 0: sys.exit("run it with sudo to write the change")
    if not os.path.exists(bak): shutil.copy(CMD, bak)
    with open(CMD, "w") as f: f.write(new + "\n")
    print(f"done (backup: {bak}) - reboot, then Monolith runs in 32-bit colour")


if __name__ == "__main__":
    main()
