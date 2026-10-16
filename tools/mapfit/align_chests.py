import json, sys, os, urllib.request
import numpy as np
from PIL import Image, ImageFilter
B = "https://fn-game-analyzer.vercel.app"
win, raw, k0, L0, cx0, cy0 = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])
d = json.load(urllib.request.urlopen(B + "/api/drops/loot?window=" + win))
S = np.array([[s["x"], s["y"]] for s in d["sites"]]); print("sites", len(S))
im = Image.open(raw).convert("RGB").resize((1024, 1024), Image.LANCZOS)
a = np.asarray(im).astype(float)
r, g, b = a[..., 0], a[..., 1], a[..., 2]
mx, mn = a.max(-1), a.min(-1)
sat = (mx - mn) / (mx + 1)
gray = ((sat < 0.16) & (mx > 70)).astype(float)               # roofs, concrete, roads: where chests are placed
pimg = Image.fromarray((gray * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))
G = np.asarray(pimg).astype(float) / 255
G = np.rot90(G, k0)
n = G.shape[0]
def score(L, cx, cy):
    iu = (S[:, 0] - cx) / L + 0.5; iv = (S[:, 1] - cy) / L + 0.5
    ok = (iu >= 0) & (iu < 1) & (iv >= 0) & (iv < 1)
    v = G[np.clip((iv * n).astype(int), 0, n - 1), np.clip((iu * n).astype(int), 0, n - 1)] * ok
    return v.mean()
base = score(L0, cx0, cy0)
best = (base, (L0, cx0, cy0))
for L in np.arange(L0 - 0.12, L0 + 0.121, 0.01):
    for cx in np.arange(cx0 - 0.06, cx0 + 0.061, 0.004):
        for cy in np.arange(cy0 - 0.06, cy0 + 0.061, 0.004):
            s = score(L, cx, cy)
            if s > best[0]: best = (s, (L, cx, cy))
rng = np.random.default_rng(1); S0 = S.copy()
rand = []
for _ in range(20):
    S = rng.random(S0.shape); rand.append(score(*best[1]))
S = S0
print("gray share at start fit %.3f | best %.3f at L=%.3f cx=%.3f cy=%.3f | random points %.3f" % (base, best[0], *best[1], np.mean(rand)))
