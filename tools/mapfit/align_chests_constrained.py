import json, sys, urllib.request
import numpy as np
from PIL import Image, ImageFilter
B = "https://fn-game-analyzer.vercel.app"
wins, raw, L0, cx0, cy0 = sys.argv[1].split(","), sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
need = float(sys.argv[6])
S = np.array([[s["x"], s["y"]] for s in json.load(urllib.request.urlopen(B + "/api/drops/loot?window=" + wins[0]))["sites"]])
rows = []
for w in wins:
    g = json.load(urllib.request.urlopen(B + "/api/drops/grid?window=" + w + "&top=1000")); n0 = g["size"]
    rows += [((i % n0 + .5) / n0, (i // n0 + .5) / n0, c) for i, c in g["all"]]
P = np.array(rows)
im = Image.open(raw).convert("RGB").resize((1024, 1024), Image.LANCZOS)
a = np.asarray(im).astype(float); mx, mn = a.max(-1), a.min(-1); sat = (mx - mn) / (mx + 1)
G = np.asarray(Image.fromarray((((sat < 0.16) & (mx > 70)) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3))).astype(float) / 255
r, g_, b_ = a[..., 0], a[..., 1], a[..., 2]
water = (((b_ > r + 25) & (b_ > g_ - 5)) | ((b_ > 100) & (r < 60) & (g_ < 120)))
Mk = np.asarray(Image.fromarray(((~water) * 255).astype("uint8")).resize((256, 256), Image.BILINEAR)) > 127
n = 1024
def struct(L, cx, cy):
    iu = (S[:, 0] - cx) / L + .5; iv = (S[:, 1] - cy) / L + .5; ok = (iu >= 0) & (iu < 1) & (iv >= 0) & (iv < 1)
    return (G[np.clip((iv * n).astype(int), 0, n - 1), np.clip((iu * n).astype(int), 0, n - 1)] * ok).mean()
def land(L, cx, cy):
    iu = (P[:, 0] - cx) / L + .5; iv = (P[:, 1] - cy) / L + .5; ok = (iu >= 0) & (iu < 1) & (iv >= 0) & (iv < 1)
    return (Mk[np.clip((iv * 256).astype(int), 0, 255), np.clip((iu * 256).astype(int), 0, 255)] * ok * P[:, 2]).sum() / P[:, 2].sum()
best = None
for L in np.arange(L0 - 0.08, L0 + 0.081, 0.01):
    for cx in np.arange(cx0 - 0.05, cx0 + 0.051, 0.005):
        for cy in np.arange(cy0 - 0.05, cy0 + 0.051, 0.005):
            ld = land(L, cx, cy)
            if ld < need: continue
            s = struct(L, cx, cy)
            if best is None or s > best[0]: best = (s, ld, L, cx, cy)
print("start struct %.3f land %.3f" % (struct(L0, cx0, cy0), land(L0, cx0, cy0)))
print("best under land>=%.2f: struct %.3f land %.3f L=%.3f cx=%.3f cy=%.3f" % ((need,) + best))
