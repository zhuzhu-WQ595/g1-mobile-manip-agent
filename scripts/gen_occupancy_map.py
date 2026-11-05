import argparse
import os

from isaacsim import SimulationApp

parser = argparse.ArgumentParser()
parser.add_argument("usd")
parser.add_argument("--out", default="maps/scene")
parser.add_argument("--res", type=float, default=0.05)
parser.add_argument("--zmin", type=float, default=0.15)
parser.add_argument("--zmax", type=float, default=1.5)
args = parser.parse_args()

app = SimulationApp({"headless": True})

import numpy as np  # noqa: E402
import yaml  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pxr import Usd, UsdGeom  # noqa: E402

stage = Usd.Stage.Open(args.usd)
mpu = UsdGeom.GetStageMetersPerUnit(stage)
up = UsdGeom.GetStageUpAxis(stage)
print("INFO upAxis", up, "metersPerUnit", mpu, flush=True)

cache = UsdGeom.XformCache(Usd.TimeCode.Default())
tris = []
n_mesh = 0
for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
    if not prim.IsA(UsdGeom.Mesh):
        continue
    if UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.invisible:
        continue
    mesh = UsdGeom.Mesh(prim)
    pts = mesh.GetPointsAttr().Get()
    counts = mesh.GetFaceVertexCountsAttr().Get()
    idx = mesh.GetFaceVertexIndicesAttr().Get()
    if not pts or not counts or not idx:
        continue
    m = np.array(cache.GetLocalToWorldTransform(prim))
    p = np.asarray(pts, dtype=np.float64)
    p = (np.c_[p, np.ones(len(p))] @ m)[:, :3] * mpu
    counts = np.asarray(counts)
    idx = np.asarray(idx)
    starts = np.r_[0, np.cumsum(counts)[:-1]]
    for k in range(3, counts.max() + 1):
        sel = starts[counts >= k]
        if len(sel) == 0:
            continue
        a, b, c = idx[sel], idx[sel + k - 2], idx[sel + k - 1]
        tris.append(np.stack([p[a], p[b], p[c]], axis=1))
    n_mesh += 1

tris = np.concatenate(tris, axis=0)
if up == "Y":
    tris = tris[:, :, [0, 2, 1]] * np.array([1, -1, 1])
print("INFO meshes", n_mesh, "triangles", len(tris), flush=True)

z = tris[:, :, 2]
keep = (z.min(axis=1) < args.zmax) & (z.max(axis=1) > args.zmin)
sel = tris[keep]
print("INFO kept triangles", len(sel), flush=True)

xy_all = tris[:, :, :2].reshape(-1, 2)
lo = np.percentile(xy_all, 0.5, axis=0) - 0.5
hi = np.percentile(xy_all, 99.5, axis=0) + 0.5
w = int(np.ceil((hi[0] - lo[0]) / args.res))
h = int(np.ceil((hi[1] - lo[1]) / args.res))
print("INFO grid", w, h, "origin", lo, flush=True)

img = Image.new("L", (w, h), 0)
draw = ImageDraw.Draw(img)
px = (sel[:, :, 0] - lo[0]) / args.res
py = h - 1 - (sel[:, :, 1] - lo[1]) / args.res
for t in range(len(sel)):
    draw.polygon([(px[t, 0], py[t, 0]), (px[t, 1], py[t, 1]), (px[t, 2], py[t, 2])], fill=255)

occ = np.array(img) > 0
floor = (tris[:, :, 2].max(axis=1) < args.zmin)
fx = (tris[floor][:, :, 0] - lo[0]) / args.res
fy = h - 1 - (tris[floor][:, :, 1] - lo[1]) / args.res
fimg = Image.new("L", (w, h), 0)
fd = ImageDraw.Draw(fimg)
for t in range(len(fx)):
    fd.polygon([(fx[t, 0], fy[t, 0]), (fx[t, 1], fy[t, 1]), (fx[t, 2], fy[t, 2])], fill=255)
has_floor = np.array(fimg) > 0

pgm = np.full((h, w), 205, dtype=np.uint8)
pgm[has_floor] = 254
pgm[occ] = 0

os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
Image.fromarray(pgm).save(args.out + ".pgm")
Image.fromarray(pgm).save(args.out + ".png")
with open(args.out + ".yaml", "w") as f:
    yaml.safe_dump(
        {
            "image": os.path.basename(args.out) + ".pgm",
            "resolution": args.res,
            "origin": [float(lo[0]), float(lo[1]), 0.0],
            "negate": 0,
            "occupied_thresh": 0.65,
            "free_thresh": 0.25,
        },
        f,
    )
print("INFO occupied%", round(100 * occ.mean(), 2), "free%", round(100 * (has_floor & ~occ).mean(), 2), flush=True)
print("INFO saved", args.out, flush=True)
app.close()
