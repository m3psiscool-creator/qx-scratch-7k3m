"""Warps a real map picture into the site's 0-1 coordinate frame, using the fit found by fit_map.py / the BR fit.

Usage: render_picture.py <source image> <out jpg> <orientation k> <L> <cx> <cy> [size]
orientation 0-3 = rotations by 90 degrees, 4-7 = the same after a mirror; L, cx, cy come from the fit.
Then run make_mask.py on the output and add the map to drops.MAPS."""
import os
import sys

import numpy as np
from PIL import Image

src, out, k, L, cx, cy = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])
OUT = int(sys.argv[7]) if len(sys.argv) > 7 else 1600
a = np.asarray(Image.open(src).convert("RGB"))
a = np.rot90(a, k % 4)
if k >= 4:
    a = a[:, ::-1]
im = Image.fromarray(np.ascontiguousarray(a))
S = im.size[0]
sx = S / (L * OUT); tx = (0.5 - cx / L) * S
sy = S / (L * OUT); ty = (0.5 - cy / L) * S
res = im.transform((OUT, OUT), Image.AFFINE, (sx, 0, tx, 0, sy, ty), resample=Image.BICUBIC, fillcolor=(10, 60, 130))
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
res.save(out, quality=82, optimize=True)
print(out, os.path.getsize(out))
