import os, sys, glob
import numpy as np
from PIL import Image

T = os.environ["TEMP"]
src = glob.glob(T + "/maps/File_Nitemare*.png")[0]
k, L, cx, cy = 1, 1.56, 0.50, 0.54
OUT = 1600
im = Image.open(src).convert("RGB")
a = np.asarray(im)
a = np.rot90(a, k % 4)
if k >= 4:
    a = a[:, ::-1]
im = Image.fromarray(np.ascontiguousarray(a))
S = im.size[0]
sx = S / (L * OUT); tx = (0.5 - cx / L) * S
sy = S / (L * OUT); ty = (0.5 - cy / L) * S
out = im.transform((OUT, OUT), Image.AFFINE, (sx, 0, tx, 0, sy, ty), resample=Image.BICUBIC, fillcolor=(22, 78, 140))
os.makedirs(sys.argv[1], exist_ok=True)
out.save(os.path.join(sys.argv[1], "nitemare-island.jpg"), quality=82, optimize=True)
print(os.path.getsize(os.path.join(sys.argv[1], "nitemare-island.jpg")))
