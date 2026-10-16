import cv2, numpy as np, sys, json
D = "C:/Users/James/AppData/Local/Temp/claude-chrome-screenshots-UEQ8x4/"
ref = cv2.imread(D + "screenshot-1792181305338-2.jpg"); tpl = ref[97 - 13:97 + 13, 425 - 14:425 + 14]
tex = cv2.imread(r"C:\Users\James\Desktop\Epic API\web\maps\raw-nitemare.jpg")
g = lambda im: cv2.createCLAHE(3.0, (8, 8)).apply(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))
sift = cv2.SIFT_create(6000); k2, d2 = sift.detectAndCompute(g(tex), None)
def run(name):
    shot = cv2.imread(D + name); h = shot.shape[0]
    s = shot.copy(); s[:, :296] = 0; s[:40] = 0; s[h - 80:, 480:1090] = 0; s[h - 230:, 1290:] = 0
    best = None
    for sc in (0.1, 0.14, 0.18, 0.22, 0.27, 0.33, 0.4, 0.5, 0.65, 0.8):
        im = cv2.resize(s, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
        k1, d1 = sift.detectAndCompute(g(im), None)
        if d1 is None or len(k1) < 12: continue
        m = cv2.BFMatcher().knnMatch(d1, d2, k=2); good = [a for a, b in m if a.distance < 0.85 * b.distance]
        if len(good) < 8: continue
        A = np.float32([k1[a.queryIdx].pt for a in good]) / sc; B = np.float32([k2[a.trainIdx].pt for a in good])
        M, inl = cv2.estimateAffinePartial2D(A, B, ransacReprojThreshold=4)
        if M is None: continue
        n = int(inl.sum())
        if best is None or n > best[0]: best = (n, M, sc, len(good))
    print(name, 'inliers', best[0], 'of', best[3], 'scale', best[1][0, 0])
    res = cv2.matchTemplate(shot, tpl, cv2.TM_CCOEFF_NORMED); ys, xs = np.where(res > 0.6); pts = []
    for y, x in sorted(zip(ys, xs), key=lambda p: -res[p[0], p[1]]):
        X, Y = int(x + 14), int(y + 13)
        if X < 300 or Y < 45 or (X > 1290 and Y > h - 230) or (480 < X < 1090 and Y > h - 80) or any((X - a) ** 2 + (Y - b) ** 2 < 18 ** 2 for a, b, _ in pts): continue
        pts.append((X, Y, float(res[y, x])))
    json.dump({"M": best[1].tolist(), "icons": pts, "h": h}, open(name + ".json", "w")); print(len(pts), 'icons')
for n in sys.argv[1:]: run(n)
