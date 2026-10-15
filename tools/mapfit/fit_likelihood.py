import json, os, sys, urllib.request
import numpy as np
from PIL import Image
B = "https://fn-game-analyzer.vercel.app"
W, path = sys.argv[1], sys.argv[2]
g = json.load(urllib.request.urlopen(B + "/api/drops/grid?window=" + W + "&top=1000"))
S = g["size"]
P = np.array([[((i % S) + 0.5) / S, ((i // S) + 0.5) / S, c] for i, c in g["all"]], float)
def land_mask(path, size=256):
    im = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    a = np.asarray(im).astype(int); r, g_, b = a[..., 0], a[..., 1], a[..., 2]
    return (~(((b > r + 25) & (b > g_ - 5)) | ((b > 100) & (r < 60) & (g_ < 120)))).astype(float)
M0 = land_mask(path)
def orient(m, k):
    m = np.rot90(m, k % 4); return m[:, ::-1] if k >= 4 else m
n = 256; eps = 0.02
def score(M, L, cx, cy):
    iu = (P[:, 0] - cx) / L + 0.5; iv = (P[:, 1] - cy) / L + 0.5
    ok = (iu >= 0) & (iu < 1) & (iv >= 0) & (iv < 1)
    m = M[np.clip((iv * n).astype(int), 0, n - 1), np.clip((iu * n).astype(int), 0, n - 1)] * ok
    area = M.mean() * L * L  # land area in frame units
    p = (m + eps) / (area + eps * 1.0)
    return float((P[:, 2] * np.log(p)).sum() / P[:, 2].sum()), float((m * P[:, 2]).sum() / P[:, 2].sum())
best = (-9, None); per = {}
for k in range(8):
    M = orient(M0, k)
    for L in np.arange(0.9, 3.0, 0.1):
        for cx in np.arange(0.0, 1.01, 0.05):
            for cy in np.arange(0.0, 1.01, 0.05):
                s, on = score(M, L, cx, cy)
                per[k] = max(per.get(k, -9), s)
                if s > best[0]: best = (s, (k, L, cx, cy, on))
print({k: round(v, 3) for k, v in per.items()}); print("coarse", best)
k, L, cx, cy, _ = best[1]; M = orient(M0, k); b2 = best
for L2 in np.arange(L - 0.1, L + 0.101, 0.02):
    for cx2 in np.arange(cx - 0.05, cx + 0.051, 0.01):
        for cy2 in np.arange(cy - 0.05, cy + 0.051, 0.01):
            s, on = score(M, L2, cx2, cy2)
            if s > b2[0]: b2 = (s, (k, L2, cx2, cy2, on))
print("fine", b2)
json.dump({"k": int(b2[1][0]), "L": float(b2[1][1]), "cx": float(b2[1][2]), "cy": float(b2[1][3]), "on_land": b2[1][4]}, open(os.environ["TEMP"] + "/maps/fit_pb.json", "w"))
