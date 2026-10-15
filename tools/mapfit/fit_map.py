import json, os, sys, glob, urllib.request
import numpy as np
from PIL import Image, ImageDraw

T = os.environ["TEMP"]
name = sys.argv[1]
info = json.load(open(T + "/maps/info_drop.json"))
base = info["map"]["base"]; N = info["map"].get("base_size", 128)
D = np.zeros((N, N))
for k, n in base.items():
    D[int(k) // N, int(k) % N] = n
G = 128
Dm = (D > np.percentile(D[D > 0], 15)).astype(float)

def land_mask(path, size=512):
    im = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    a = np.asarray(im).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    water = (b > r + 25) & (b > g - 5) | ((b > 100) & (r < 60) & (g < 120))
    return (~water).astype(float)

def orient(m, k):
    m = np.rot90(m, k % 4)
    return m[:, ::-1] if k >= 4 else m

path = glob.glob(T + "/maps/File_" + name + "*.png")[0]
M0 = land_mask(path)
yy, xx = np.mgrid[0:G, 0:G]
q = (np.stack([xx, yy], -1) + 0.5) / G
best = (0, None)
for k in range(8):
    M = orient(M0, k); S = M.shape[0]
    for L in np.arange(1.0, 2.2, 0.02):
        for cx in np.arange(0.3, 0.71, 0.02):
            for cy in np.arange(0.3, 0.71, 0.02):
                iu = (q[..., 0] - cx) / L + 0.5; iv = (q[..., 1] - cy) / L + 0.5
                ok = (iu >= 0) & (iu < 1) & (iv >= 0) & (iv < 1)
                s = M[np.clip((iv * S).astype(int), 0, S - 1), np.clip((iu * S).astype(int), 0, S - 1)] * ok
                inter = (s * Dm).sum(); un = ((s + Dm) > 0).sum()
                iou = inter / un
                if iou > best[0]: best = (iou, (k, L, cx, cy))
print("best", best)
k, L, cx, cy = best[1]
im = Image.open(path).convert("RGB").resize((1024, 1024))
im = Image.fromarray(orient(np.asarray(im), k)).convert("RGBA")
ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
for kk, n in base.items():
    pass
# landing counts (all) from the API
g = json.load(urllib.request.urlopen("https://fn-game-analyzer.vercel.app/api/drops/grid?window=S42_ReloadCashCup_DuosZB_Event5Round1_NAC&top=1000"))
S = g["size"]
mx = max(c for _, c in g["all"])
for idx, c in g["all"]:
    u = ((idx % S) + 0.5) / S; v = ((idx // S) + 0.5) / S
    px = ((u - cx) / L + 0.5) * 1024; py = ((v - cy) / L + 0.5) * 1024
    r = 4 + 10 * (c / mx) ** 0.5
    d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 40, 40, int(70 + 150 * (c / mx) ** 0.5)))
Image.alpha_composite(im, ov).convert("RGB").save(T + "/maps/overlay_" + name[:6] + ".png")
json.dump({"name": name, "orient": k, "L": L, "cx": cx, "cy": cy}, open(T + "/maps/fit_" + name[:6] + ".json", "w"))
