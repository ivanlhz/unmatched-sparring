"""Aligns the snap points of a TTS Custom_Board with the circles of the map image."""
import json, sys
import cv2, numpy as np
from scipy.optimize import linear_sum_assignment

save, guid, img_path, out = sys.argv[1:5]
d = json.load(open(save, encoding="utf-8"))
board = next(o for o in d["ObjectStates"] if o["GUID"] == guid)
pts = np.array([(s["Position"]["x"], s["Position"]["z"]) for s in board["AttachedSnapPoints"]])

img = cv2.imread(img_path)
H, W = img.shape[:2]
gray = cv2.medianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 7)
r0 = int(W * 65 / 1400)
circ = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.5, minDist=r0 * 1.6,
                        param1=120, param2=60, minRadius=int(r0 * .8), maxRadius=int(r0 * 1.25))
g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
def outline_dark(x, y, r):
    ang = np.linspace(0, 2 * np.pi, 180, endpoint=False)
    v = [min(g[int(np.clip(y + rr * np.sin(a), 0, H - 1)), int(np.clip(x + rr * np.cos(a), 0, W - 1))]
             for rr in (r - 4, r, r + 4)) for a in ang]
    return np.mean(np.array(v) < 70)
# real spaces: uniform radius and black outline; logos, tokens and decoration are left out
keep = [(x, y) for x, y, r in circ[0] if r <= r0 * 1.065 and outline_dark(x, y, r) > 0.6]
centers = np.array(keep)
print("circles detected:", len(centers), "snaps:", len(pts))

# Tries the 8 orientations (signs and axis swap), normalizes mean and scale,
# and refines with ICP + Hungarian assignment. Keeps the one with the smallest error.
def icp(P0):
    P = P0
    for _ in range(40):
        dist = np.linalg.norm(P[:, None] - centers[None], axis=2)
        _, nn = linear_sum_assignment(dist)
        tgt = centers[nn]
        A = np.c_[pts, np.ones(len(pts))]
        M, *_ = np.linalg.lstsq(A, tgt, rcond=None)
        P = A @ M
    return P, tgt, M, np.linalg.norm(P - tgt, axis=1).mean()

best = None
cm, cs = centers.mean(0), centers.std(0)
for swap in (False, True):
    for sx in (1, -1):
        for sz in (1, -1):
            q = pts[:, ::-1] if swap else pts
            q = (q - q.mean(0)) / q.std(0) * np.array([sx, sz])
            res = icp(q * cs + cm)
            if best is None or res[3] < best[3]:
                best = res
P, tgt, M, _ = best
err = np.linalg.norm(P - tgt, axis=1)
print("mean error px:", err.mean().round(1), "max:", err.max().round(1))

vis = img.copy()
for (cx, cy) in centers:
    cv2.circle(vis, (int(cx), int(cy)), 18, (0, 255, 0), -1)
for i, (x, y) in enumerate(P):
    cv2.circle(vis, (int(x), int(y)), 40, (255, 255, 255), -1)
    cv2.putText(vis, str(i), (int(x) - 30, int(y) + 18), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
cv2.imwrite(out, cv2.resize(vis, (1400, int(H * 1400 / W))))
json.dump({"guid": guid, "pixel": P.round(1).tolist(), "M": M.tolist(), "img": [W, H]},
          open(out.rsplit(".", 1)[0] + ".json", "w"), indent=1)
