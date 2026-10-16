"""Land/water outline for a map picture whose buildings are bluish (the wiki renders): the sea is the blue region connected to the
picture's border, everything else (islands, lakes, canals inside) counts as land. Usage: make_mask_sea.py web/maps/raw-surfcity2.jpg"""
import json
import os
import sys

import cv2
import numpy as np

SIZE = 256
src = sys.argv[1]
im = cv2.imread(src)
hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
blue = ((hsv[..., 0] >= 98) & (hsv[..., 0] <= 130) & (hsv[..., 1] > 110)).astype(np.uint8)
n, lab = cv2.connectedComponents(blue)
border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
sea = np.isin(lab, list(border)).astype(np.uint8)
sea = cv2.morphologyEx(sea, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
land = 1 - sea
land = cv2.morphologyEx(land, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))          # specks of foam
small = cv2.resize(land.astype(np.float32), (SIZE, SIZE), interpolation=cv2.INTER_AREA) > 0.5
out = os.path.splitext(src)[0] + ".mask.json"
json.dump({"size": SIZE, "rows": ["".join("1" if v else "0" for v in row) for row in small]}, open(out, "w"))
print(out, "land share of the picture: %.2f" % small.mean())
cv2.imwrite(os.path.splitext(src)[0] + ".mask-preview.png", (small * 255).astype(np.uint8))
