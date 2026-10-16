import cv2, numpy as np, sys, json
D = "C:/Users/James/AppData/Local/Temp/claude-chrome-screenshots-UEQ8x4/"
ref = cv2.imread(D + "screenshot-1792181305338-2.jpg")
T = [ref[y - 13:y + 13, x - 14:x + 14] for x, y in [(425, 97), (480, 452), (751, 364), (1000, 522), (870, 350)]]; W = [1, 2, 3, 3, 2]
texf, sitesf, fit = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]); names = sys.argv[4:]
tex = cv2.imread(texf); n = tex.shape[0]
g = lambda im: cv2.createCLAHE(3.0, (8, 8)).apply(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))
sift = cv2.SIFT_create(6000); k2, d2 = sift.detectAndCompute(g(tex), None)
SD = json.load(open(sitesf)); S = [s for s in SD['sites'] if s['cls'] in ('chest', 'rare')]
allP, allI, tot = [], [], []
for name in names:
    shot = cv2.imread(D + name); h = shot.shape[0]
    s = shot.copy(); s[:, :296] = 0; s[:45] = 0; s[h - 80:, 480:1090] = 0; s[h - 230:, 1290:] = 0
    best = None
    for sc in (0.1, 0.14, 0.18, 0.22, 0.27, 0.33, 0.4, 0.5, 0.65, 0.8, 1.0):
        im = cv2.resize(s, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA); k1, d1 = sift.detectAndCompute(g(im), None)
        if d1 is None or len(k1) < 12: continue
        m = cv2.BFMatcher().knnMatch(d1, d2, k=2); good = [a for a, b in m if a.distance < 0.85 * b.distance]
        if len(good) < 8: continue
        A = np.float32([k1[a.queryIdx].pt for a in good]) / sc; B = np.float32([k2[a.trainIdx].pt for a in good])
        M, inl = cv2.estimateAffinePartial2D(A, B, ransacReprojThreshold=4)
        if M is not None and (best is None or inl.sum() > best[0]): best = (int(inl.sum()), M, len(good))
    if best is None or best[0] < 25: print(name, 'registration failed', best and best[0]); continue
    M = best[1]; Mi = cv2.invertAffineTransform(M); print(name, 'inliers', best[0], 'scale %.3f rot %.2f deg' % (np.hypot(M[0, 0], M[0, 1]), np.degrees(np.arctan2(M[1, 0], M[0, 0]))))
    cands = []
    for k, t in enumerate(T):
        r = cv2.matchTemplate(shot, t, cv2.TM_CCOEFF_NORMED); ys, xs = np.where(r > 0.55)
        cands += [(float(r[y, x]), int(x + 14), int(y + 13), W[k]) for y, x in zip(ys, xs)]
    pts = []
    for s_, X, Y, w in sorted(cands, reverse=True):
        if X < 345 or Y < 85 or X > 1265 or Y > h - 105 or (X > 1290 and Y > h - 230): continue
        if any((X - a) ** 2 + (Y - b) ** 2 < 16 ** 2 for a, b, _ in pts): continue
        pts.append((X, Y, w))
    mk = np.array([(x, y) for x, y, _ in pts]); wt = np.array([w for _, _, w in pts])
    P = []
    for s_ in S:
        u = ((s_['x'] - fit['cx']) / fit['L'] + .5) * n; vv = ((s_['y'] - fit['cy']) / fit['L'] + .5) * n
        x, y = Mi @ np.array([u, vv, 1])
        if 345 < x < 1265 and 85 < y < h - 105: P.append((x, y))
    P = np.array(P); mpp = np.hypot(M[0, 0], M[0, 1]) * fit['L'] * SD['view'][2] * 1100 / n
    singles = mk[wt == 1]
    off = np.array([P[np.argmin(np.hypot(*(P - i).T))] - i for i in singles]); r0 = np.hypot(*off.T) * mpp; near = r0 < 25
    med = np.median(off[near], 0) if near.sum() else np.zeros(2)
    res = np.hypot(*(off[near] - med).T) * mpp if near.sum() else np.array([0.])
    far = [p for p in P if np.min(np.hypot(*(mk - p).T)) > 30]
    nomine = [(m.tolist(), int(w)) for m, w in zip(mk, wt) if np.min(np.hypot(*(P - m).T)) > 30]
    print('  markers', len(mk), 'weight', wt.sum(), 'ours', len(P), '| singles', len(singles), 'offset m', np.round(med * mpp, 1), 'resid med %.1f p90 %.1f' % (np.median(res), np.percentile(res, 90)))
    print('  ours w/o marker within 30px:', len(far), '| markers w/o ours:', len(nomine), nomine)
    out = shot.copy()
    for x, y in P: cv2.circle(out, (int(x), int(y)), 9, (0, 0, 255), 2)
    for (x, y) in mk: cv2.circle(out, (int(x), int(y)), 17, (0, 255, 0), 1)
    for p in far: cv2.circle(out, (int(p[0]), int(p[1])), 14, (0, 255, 255), 3)
    cv2.imwrite(name + ".cmp4.jpg", out)
