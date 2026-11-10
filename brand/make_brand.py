#!/usr/bin/env python3
"""brand/make_brand.py - turns a logo into everything the sampler uses for its identity. Nothing is branded until you run it.

  1. Put the logo here as brand/logo.png: white (or any colour) on a transparent background, or dark on a white background.
     If it has small lettering under a mark, leave a clear gap between them: the badge then uses the mark only.
  2. Optional: brand/key_mark.png, a small symbol (white on transparent) to engrave on the SHIFT keycap above its name.
  3. python3 brand/make_brand.py && python3 make_stl.py && python3 make_artwork.py

Writes: logo_mask.png (start-up screen), badge_mask.png (logo_badge.stl for the console pocket), logo.svg / badge.svg (traced
vectors for stickers and console_artwork.svg). Delete them (and logo.png) to go back to an unbranded build."""
import os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
COLOR = "#e8e8f0"                        # colour of the traced vectors (the badge artwork); change to taste


def load_mask(path):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or "transparency" in im.info:
        a = np.array(im.convert("RGBA"))[..., 3]
        if a.min() < 128: return a > 128                          # real transparency: the opaque part is the logo
    g = np.array(im.convert("L")).astype(float)
    return g < 128 if g.mean() > 128 else g > 128                 # dark on light, or light on dark


def crop(m):
    ys, xs = np.nonzero(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def badge_part(full):
    """the mark without the lettering under it: everything above the last clear horizontal gap in the lower half"""
    rows = [r for r in range(len(full) // 2, len(full)) if not full[r].any()]
    return crop(full[:rows[0]]) if rows else full


def svg(mask, path, fill, scale=4):
    import cv2
    im = Image.fromarray((mask * 255).astype(np.uint8)).resize((mask.shape[1] * scale, mask.shape[0] * scale), Image.LANCZOS)
    cs, _ = cv2.findContours((np.array(im) > 127).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    d = []
    for c in cs:
        c = cv2.approxPolyDP(c, 0.8, True)[:, 0, :] / float(scale)
        if len(c) >= 3: d.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in c) + " Z")
    h, w = mask.shape
    open(path, "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
                          f'<path fill="{fill}" fill-rule="evenodd" d="{" ".join(d)}"/></svg>\n')


if __name__ == "__main__":
    src = os.path.join(HERE, "logo.png")
    if not os.path.exists(src): raise SystemExit("put your logo in brand/logo.png first (see the top of this file)")
    full = crop(load_mask(src)); badge = badge_part(full)
    for name, mk in (("logo_mask", full), ("badge_mask", badge)):
        Image.fromarray((mk * 255).astype(np.uint8)).save(os.path.join(HERE, name + ".png"))
    svg(full, os.path.join(HERE, "logo.svg"), COLOR); svg(badge, os.path.join(HERE, "badge.svg"), COLOR)
    print("brand files written to", HERE)
