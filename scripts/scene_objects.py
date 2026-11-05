import json
import sys

from isaacsim import SimulationApp

scene_dir = sys.argv[1]
out = sys.argv[2]

app = SimulationApp({"headless": True})

from pxr import Usd, UsdGeom  # noqa: E402

stage = Usd.Stage.Open(f"{scene_dir}/start_result_navigation.usd")
mpu = UsdGeom.GetStageMetersPerUnit(stage)
root_names = [c.GetName() for c in stage.GetPseudoRoot().GetChildren()]
print("INFO roots", root_names, flush=True)
interactive = json.load(open(f"{scene_dir}/interactive_obj_list.json"))
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"], useExtentsHint=False)

records = []
for kind, paths in interactive.items():
    for p in paths:
        prim = stage.GetPrimAtPath(p)
        if not prim.IsValid():
            alt = "/" + root_names[0] + p[len("/Root"):] if p.startswith("/Root") else p
            prim = stage.GetPrimAtPath(alt)
        if not prim.IsValid():
            continue
        r = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        lo, hi = r.GetMin() * mpu, r.GetMax() * mpu
        records.append(
            {
                "kind": kind,
                "category": p.split("/")[-2],
                "path": str(prim.GetPath()),
                "min": [round(float(v), 3) for v in lo],
                "max": [round(float(v), 3) for v in hi],
                "center": [round(float((a + b) / 2), 3) for a, b in zip(lo, hi)],
            }
        )

json.dump(records, open(out, "w"), indent=1, ensure_ascii=False)
print("INFO objects", len(records), "of", sum(len(v) for v in interactive.values()), flush=True)
app.close()
