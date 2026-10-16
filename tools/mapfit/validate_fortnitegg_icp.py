import cv2, numpy as np, sys, json
# re-run registration quickly from cmp4 internals by importing its steps would be heavy; recompute here
D = "C:/Users/James/AppData/Local/Temp/claude-chrome-screenshots-UEQ8x4/"
ref = cv2.imread(D + "screenshot-1792181305338-2.jpg")
T = [ref[y - 13:y + 13, x - 14:x + 14] for x, y in [(425, 97), (480, 452), (751, 364), (1000, 522), (870, 350)]]
texf, sitesf, fit = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]); names = sys.argv[4:]
tex = cv2.imread(texf); n = tex.shape[0]
g = lambda im: cv2.createCLAHE(3.0, (8, 8)).apply(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))
sift = cv2.SIFT_create(6000); k2, d2 = sift.detectAndCompute(g(tex), None)
SD = json.load(open(sitesf)); S = [s for s in SD['sites'] if s['cls'] in ('chest', 'rare')]
site_tex = np.array([[((s['x'] - fit['cx']) / fit['L'] + .5) * n, ((s['y'] - fit['cy']) / fit['L'] + .5) * n] for s in S])
icons = []
for name in names:
    shot = cv2.imread(D + name); h = shot.shape[0]
    s = shot.copy(); s[:, :296] = 0; s[:45] = 0; s[h - 80:, 480:1090] = 0; s[h - 230:, 1290:] = 0
    best = None
    for sc in (0.18, 0.22, 0.27, 0.33, 0.4, 0.5, 0.65, 0.8):
        im = cv2.resize(s, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA); k1, d1 = sift.detectAndCompute(g(im), None)
        m = cv2.BFMatcher().knnMatch(d1, d2, k=2); good = [a for a, b in m if a.distance < 0.85 * b.distance]
        if len(good) < 8: continue
        A = np.float32([k1[a.queryIdx].pt for a in good]) / sc; B = np.float32([k2[a.trainIdx].pt for a in good])
        M, inl = cv2.estimateAffinePartial2D(A, B, ransacReprojThreshold=4)
        if M is not None and (best is None or inl.sum() > best[0]): best = (int(inl.sum()), M)
    M = best[1]
    cands = []
    r = cv2.matchTemplate(shot, T[0], cv2.TM_CCOEFF_NORMED); ys, xs = np.where(r > 0.6)
    for y, x in sorted(zip(ys, xs), key=lambda p: -r[p[0], p[1]]):
        X, Y = int(x + 14), int(y + 13)
        if X < 345 or Y < 85 or X > 1265 or Y > h - 105 or (X > 1290 and Y > h - 230): continue
        if any((X - a) ** 2 + (Y - b) ** 2 < 16 ** 2 for a, b in cands): continue
        cands.append((X, Y))
    icons += [M @ np.array([x, y, 1]) for x, y in cands]
icons = np.array(icons); mpt = fit['L'] * SD['view'][2] * 1100 / n; print('singles', len(icons), 'sites', len(site_tex))
cur = site_tex.copy()
for it in range(12):
    idx = [np.argmin(np.hypot(*(cur - i).T)) for i in icons]; dist = np.array([np.hypot(*(cur[j] - i)) for j, i in zip(idx, icons)]) * mpt
    ok = dist < 25
    M2, _ = cv2.estimateAffinePartial2D(cur[np.array(idx)[ok]].astype(np.float32), icons[ok].astype(np.float32), method=cv2.LMEDS)
    cur = (M2[:, :2] @ cur.T).T + M2[:, 2]
    print(it, ok.sum(), 'median %.1f m' % np.median(dist[ok]), 'scale %.4f rot %.2f deg shift' % (np.hypot(M2[0, 0], M2[0, 1]), np.degrees(np.arctan2(M2[1, 0], M2[0, 0]))), np.round(M2[:, 2], 1))
Mt, _ = cv2.estimateAffinePartial2D(site_tex.astype(np.float32), cur.astype(np.float32), method=cv2.LMEDS); print('total', Mt.tolist())
