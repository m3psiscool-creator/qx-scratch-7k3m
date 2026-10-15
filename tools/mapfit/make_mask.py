"""Writes the land/water outline that goes with a map picture (web/maps/<name>.mask.json).

The site checks the real landings of a tournament against this outline before it shows the picture: if too many teams
"landed in the sea", the picture is the wrong map and is hidden. Usage: make_mask.py web/maps/nitemare-island.jpg"""
import json
import os
import sys

import numpy as np
from PIL import Image

SIZE = 256
src = sys.argv[1]
im = Image.open(src).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR)
a = np.asarray(im).astype(int)
r, g, b = a[..., 0], a[..., 1], a[..., 2]
water = ((b > r + 25) & (b > g - 5)) | ((b > 100) & (r < 60) & (g < 120))
land = ~water
out = os.path.splitext(src)[0] + ".mask.json"
json.dump({"size": SIZE, "rows": ["".join("1" if v else "0" for v in row) for row in land]}, open(out, "w"))
print(out, "land share of the picture: %.2f" % land.mean())
