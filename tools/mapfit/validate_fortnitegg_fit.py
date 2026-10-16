import cv2, numpy as np, sys, json
S = json.load(open('sites.json'))['sites']
fit = {"L": 1.2165, "cx": 0.4121, "cy": 0.4834}
site_tex = np.array([[((s['x'] - fit['cx']) / fit['L'] + .5) * 1280, ((s['y'] - fit['cy']) / fit['L'] + .5) * 1280] for s in S if s['cls'] in ('chest', 'rare')])
pairs = []
tiles = [("screenshot-1792181481417-6.jpg.json", 330, 1280), ("screenshot-1792181481419-9.jpg.json", 330, 1280), ("t1.json", 330, 1290)]
for name, x0, x1 in tiles:
    d = json.load(open(name)); M = np.array(d["M"]); h = d.get("h", 772)
    for x, y, _ in d["icons"]:
        if not (x0 < x < x1 and 70 < y < h - 90): continue
        ti = M @ np.array([x, y, 1]); pairs.append((ti, name))
icons = np.array([p[0] for p in pairs])
mpt = 1.58 * 1100 / 1280
# iterative closest point similarity fit: sites -> icons
T = np.eye(3)[:2]
cur = site_tex.copy()
for it in range(8):
    idx = [np.argmin(np.hypot(*(cur - i).T)) for i in icons]
    dist = np.array([np.hypot(*(cur[j] - i)) for j, i in zip(idx, icons)]) * mpt
    ok = dist < 10
    A = cur[np.array(idx)[ok]]; B = icons[ok]
    M2, _ = cv2.estimateAffinePartial2D(A.astype(np.float32), B.astype(np.float32), method=cv2.LMEDS)
    cur = (M2[:, :2] @ cur.T).T + M2[:, 2]
    print(it, 'pairs', ok.sum(), 'median dist m %.2f' % np.median(dist[ok]), 'scale %.4f' % np.hypot(M2[0, 0], M2[0, 1]), 'shift tex px', np.round(M2[:, 2], 2))
# total transform from original sites to cur
A = site_tex.astype(np.float32); Mt, _ = cv2.estimateAffinePartial2D(A, cur.astype(np.float32), method=cv2.LMEDS)
print('total', np.round(Mt, 4).tolist())
