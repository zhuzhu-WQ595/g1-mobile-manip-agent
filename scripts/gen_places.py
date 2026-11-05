import json
import math
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

map_prefix = sys.argv[1] if len(sys.argv) > 1 else "maps/MWBGLK_Q8"
clearance = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35

import yaml  # noqa: E402

meta = yaml.safe_load(open(map_prefix + ".yaml"))
res = meta["resolution"]
ox, oy = meta["origin"][:2]
grid = np.array(Image.open(map_prefix + ".pgm"))
H, W = grid.shape
free = grid == 254
dist = distance_transform_edt(free) * res
objs = json.load(open(map_prefix + "_objects.json"))


def to_cell(x, y):
    return int((x - ox) / res), int(H - 1 - (y - oy) / res)


def to_world(cx, cy):
    return ox + (cx + 0.5) * res, oy + (H - 1 - cy + 0.5) * res


def find(cat, idx=0):
    items = [o for o in objs if o["category"] == cat]
    return items[idx]["center"] if len(items) > idx else None


def stand_pose(target, reach=0.7):
    tx, ty = target[0], target[1]
    best = None
    ys, xs = np.nonzero(dist >= clearance)
    for cx, cy in zip(xs, ys):
        wx, wy = to_world(cx, cy)
        d = math.hypot(wx - tx, wy - ty)
        score = abs(d - reach)
        if best is None or score < best[0]:
            best = (score, wx, wy)
    _, wx, wy = best
    yaw = math.degrees(math.atan2(ty - wy, tx - wx))
    return {"x": round(wx, 2), "y": round(wy, 2), "yaw_deg": round(yaw, 1)}


targets = {
    "kitchen": ("refrigerator", 0, "fridge front, kitchen"),
    "stove": ("hearth", 0, "stove area in kitchen"),
    "dining_table": ("pot", 0, "dining table area"),
    "living_room": ("teatable", 0, "living room, tea table"),
    "tv": ("tvstand", 0, "TV area in living room"),
    "bedroom_1": ("nightstand", 0, "bedroom 1 (west)"),
    "bedroom_2": ("nightstand", 2, "bedroom 2"),
    "study": ("desk", 0, "study with desk"),
    "bathroom": ("toilet", 1, "bathroom, west"),
    "balcony": ("washingmachine", 0, "balcony with washing machines"),
}

places = {"home": {"x": 0.0, "y": 0.0, "yaw_deg": 0.0, "note": "G1 spawn, corridor"}}
for name, (cat, idx, note) in targets.items():
    c = find(cat, idx)
    if c is None:
        continue
    pose = stand_pose(c)
    pose["note"] = note
    pose["target"] = {"x": c[0], "y": c[1]}
    places[name] = pose
    cx, cy = to_cell(pose["x"], pose["y"])
    pose["clearance_m"] = round(float(dist[cy, cx]), 2)

hx, hy = to_cell(0.0, 0.0)
places["home"]["clearance_m"] = round(float(dist[hy, hx]), 2)
places["home"]["free"] = bool(free[hy, hx])

json.dump(places, open(map_prefix + "_places.json", "w"), indent=1, ensure_ascii=False)
for k, v in places.items():
    print(k, v)
