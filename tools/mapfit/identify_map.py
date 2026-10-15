import json, os, sys, glob, urllib.request
import numpy as np
from PIL import Image

T = os.environ["TEMP"]
W = sys.argv[1]
g = json.load(urllib.request.urlopen("https://fn-game-analyzer.vercel.app/api/drops/grid?window=" + W + "&top=1000"))
S = g["size"]
pts = np.array([[((i % S) + 0.5) / S, ((i // S) + 0.5) / S, c] for i, c in g["all"]])
print(W, "landing cells", len(pts), "total", int(pts[:, 2].sum()))

def land_mask(path, size=512):
    im = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    a = np.asarray(im).astype(int)
    r, g_, b = a[..., 0], a[..., 1], a[..., 2]
    water = (b > r + 25) & (b > g_ - 5) | ((b > 100) & (r < 60) & (g_ < 120))
    return (~water).astype(float)

def orient(m, k):
    m = np.rot90(m, k % 4)
    return m[:, ::-1] if k >= 4 else m

fixed = None
if len(sys.argv) > 2:
    fixed = tuple(float(x) for x in sys.argv[2].split(","))   # L,cx,cy
for path in sorted(glob.glob(T + "/maps/File_*.png")):
    M0 = land_mask(path)
    best = (0, None)
    ks = range(8)
    for k in ks:
        M = orient(M0, k); n = M.shape[0]
        Ls = [fixed[0]] if fixed else np.arange(1.0, 2.2, 0.08)
        cxs = [fixed[1]] if fixed else np.arange(0.36, 0.65, 0.04)
        cys = [fixed[2]] if fixed else np.arange(0.36, 0.65, 0.04)
        for L in Ls:
            for cx in cxs:
                for cy in cys:
                    iu = (pts[:, 0] - cx) / L + 0.5; iv = (pts[:, 1] - cy) / L + 0.5
                    ok = (iu >= 0) & (iu < 1) & (iv >= 0) & (iv < 1)
                    s = M[np.clip((iv * n).astype(int), 0, n - 1), np.clip((iu * n).astype(int), 0, n - 1)] * ok
                    sc = (s * pts[:, 2]).sum() / pts[:, 2].sum()
                    if sc > best[0]: best = (sc, (k, round(L, 2), round(cx, 2), round(cy, 2)))
    print(os.path.basename(path)[:34].ljust(34), "landings on land %.3f" % best[0], best[1])
