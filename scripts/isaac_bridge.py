import argparse
import base64
import gc
import heapq
import io
import json
import math
import os
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import isaacsim  # noqa: F401  (must precede internutopia so carb is importable)
import numpy as np
import yaml
from internutopia.core.config import Config, SimConfig
from internutopia.core.gym_env import Env
from internutopia.macros import gm
from internutopia_extension import import_extensions
from internutopia_extension.configs.robots.g1 import G1RobotCfg, move_by_speed_cfg
from internutopia.core.robot.articulation_action import ArticulationAction
from internutopia_extension.configs.tasks import SingleInferenceTaskCfg
from PIL import Image
from scipy.ndimage import distance_transform_edt

parser = argparse.ArgumentParser()
parser.add_argument("--scene", required=True, help="absolute path to the scene USD")
parser.add_argument("--map", required=True, help="map prefix (.yaml/.pgm/_places.json)")
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--radius", type=float, default=0.0, help="robot inflation radius in meters; 0 = auto from robot bbox")
parser.add_argument("--vx", type=float, default=0.4)
parser.add_argument("--headless", type=int, default=1)
args = parser.parse_args()

meta = yaml.safe_load(open(args.map + ".yaml"))
RES = meta["resolution"]
OX, OY = meta["origin"][:2]
GRID = np.array(Image.open(args.map + ".pgm"))
H, W = GRID.shape
FREE = GRID == 254
DIST = distance_transform_edt(FREE) * RES  # metres to nearest obstacle per cell
PLACES = json.load(open(args.map + "_places.json"))
INFLATED = np.zeros_like(FREE)          # filled by _build_costmap once radius is known
COST = np.ones(DIST.shape, dtype=float)  # soft traversal cost multiplier
BLOCKED_DYN = np.zeros_like(FREE)        # dynamic obstacles (e.g. opened fridge doors)


def blocked(cx, cy):
    return (not INFLATED[cy, cx]) or BLOCKED_DYN[cy, cx]


def _build_costmap(radius):
    global INFLATED, COST
    INFLATED = DIST >= radius
    margin = np.maximum(DIST - radius, 0.0)
    COST = np.where(INFLATED, 1.0 + 0.5 * np.exp(-margin / 0.35), 0.0)


def to_cell(x, y):
    return int(round((x - OX) / RES - 0.5)), int(round(H - 1 - (y - OY) / RES + 0.5))


def to_world(cx, cy):
    return OX + (cx + 0.5) * RES, OY + (H - 1 - cy + 0.5) * RES


def nearest_free(cell):
    cx, cy = cell
    if 0 <= cx < W and 0 <= cy < H and INFLATED[cy, cx]:
        return cell
    ys, xs = np.nonzero(INFLATED)
    i = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
    return int(xs[i]), int(ys[i])


def astar(start, goal):
    moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    openq = [(0.0, start)]
    g = {start: 0.0}
    prev = {}
    while openq:
        _, cur = heapq.heappop(openq)
        if cur == goal:
            path = [cur]
            while cur in prev:
                cur = prev[cur]
                path.append(cur)
            return path[::-1]
        for dx, dy, cost in moves:
            nx, ny = cur[0] + dx, cur[1] + dy
            if not (0 <= nx < W and 0 <= ny < H) or blocked(nx, ny):
                continue
            if dx and dy and not (INFLATED[cur[1], nx] and INFLATED[ny, cur[0]]):
                continue
            ng = g[cur] + cost * COST[ny, nx]
            if ng < g.get((nx, ny), 1e18):
                g[(nx, ny)] = ng
                prev[(nx, ny)] = cur
                h = math.hypot(goal[0] - nx, goal[1] - ny)
                heapq.heappush(openq, (ng + h, (nx, ny)))
    return None


def line_free(a, b):
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    for t in np.linspace(0.0, 1.0, n + 1):
        x = int(round(a[0] + (b[0] - a[0]) * t))
        y = int(round(a[1] + (b[1] - a[1]) * t))
        if blocked(x, y):
            return False
    return True


def simplify(path):
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not line_free(path[i], path[j]):
            j -= 1
        out.append(path[j])
        i = j
    return out


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


scene_cfg = SingleInferenceTaskCfg(
    scene_asset_path=args.scene,
    scene_scale=(0.01, 0.01, 0.01),
    robots=[G1RobotCfg(position=(0.0, 0.0, 0.8), controllers=[move_by_speed_cfg])],
)
config = Config(
    simulator=SimConfig(
        physics_dt=1 / 240, rendering_dt=1 / 240, use_fabric=False,
        headless=bool(args.headless), webrtc=False,
        rendering_interval=120,  # render every 120th step (~2/s); Replicator camera renders on demand
    ),
    task_configs=[scene_cfg],
)
import_extensions()
env = Env(config)
obs, _ = env.reset()
DT = 1 / 240


def step(vx=0.0, vy=0.0, wz=0.0):
    global obs, POSE_BIAS
    _arm_tick()
    obs, _, _, _, _ = env.step(action={move_by_speed_cfg.name: (vx, vy, wz)})
    if NAV_DRIFT > 0:
        POSE_BIAS += np.random.normal(0.0, NAV_DRIFT, 3) * math.sqrt(DT)
    update_held()
    _update_cam()
    _maybe_record()
    return obs


def _raw_pose():
    p = obs["position"]
    q = obs["orientation"]
    yaw = math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2))
    return float(p[0]), float(p[1]), float(p[2]), yaw


# Simulated SLAM error injected into pose(): every consumer (planner, tracker,
# camera, reach checks) sees the estimated pose like a real localizer would.
# ISAAC_NAV_NOISE = per-query jitter std (m); ISAAC_NAV_DRIFT = random-walk
# drift rate (m per sqrt(sim-second)) that accumulates while the sim steps.
NAV_NOISE = float(os.environ.get("ISAAC_NAV_NOISE", "0.0"))
NAV_DRIFT = float(os.environ.get("ISAAC_NAV_DRIFT", "0.0"))
POSE_BIAS = np.zeros(3)  # dx, dy, dyaw accumulated drift


def pose():
    x, y, z, yaw = _raw_pose()
    if NAV_NOISE > 0 or NAV_DRIFT > 0:
        jx, jy, jyaw = np.random.normal(0.0, NAV_NOISE, 3) if NAV_NOISE > 0 else (0.0, 0.0, 0.0)
        return x + POSE_BIAS[0] + jx, y + POSE_BIAS[1] + jy, z, wrap(yaw + POSE_BIAS[2] + jyaw)
    return x, y, z, yaw


def pose_dict():
    x, y, z, yaw = pose()
    out = {"x": round(x, 3), "y": round(y, 3), "yaw_deg": round(math.degrees(yaw), 1)}
    if NAV_NOISE > 0 or NAV_DRIFT > 0:
        tx, ty, _, tyaw = _raw_pose()
        out["true"] = {"x": round(tx, 3), "y": round(ty, 3), "yaw_deg": round(math.degrees(tyaw), 1)}
    return out


def at_place():
    x, y, _, _ = pose()
    for name, p in PLACES.items():
        if math.hypot(x - p["x"], y - p["y"]) < 0.5:
            return name
    return None


def do_pose():
    return {"ok": True, "message": "pose read", "pose": pose_dict(), "at_place": at_place(), "holding": SKILL["holding"]}


def do_places():
    return {
        "ok": True,
        "message": "semantic places",
        "places": {k: {"x": v["x"], "y": v["y"], "yaw_deg": v["yaw_deg"], "note": v.get("note", "")} for k, v in PLACES.items()},
    }


def _plan_to(goal_pose):
    x, y, _, _ = pose()
    start = nearest_free(to_cell(x, y))
    goal = nearest_free(to_cell(goal_pose["x"], goal_pose["y"]))
    path = astar(start, goal)
    if path is None:
        return None
    way = [to_world(*c) for c in simplify(path)][1:]
    way.append((goal_pose["x"], goal_pose["y"]))
    return way


def _track(way, t0, budget):
    """Follow waypoints. Returns (status, elapsed_sim_t)."""
    t = t0
    last_check = (pose()[0], pose()[1], t)
    for i, (wx, wy) in enumerate(way):
        tol = 0.15 if i == len(way) - 1 else 0.3
        while True:
            x, y, z, yaw = pose()
            if z < 0.45:
                return "fell", t
            dist = math.hypot(wx - x, wy - y)
            if dist < tol:
                break
            err = wrap(math.atan2(wy - y, wx - x) - yaw)
            wz = float(np.clip(1.2 * err, -0.8, 0.8))
            vx = args.vx * max(0.0, 1.0 - abs(err) / 0.9) if abs(err) < 0.9 else 0.0
            cx, cy = to_cell(x, y)
            clearance = float(DIST[cy, cx]) if 0 <= cx < W and 0 <= cy < H else 0.3
            vx *= min(1.0, max(0.35, clearance / 0.5))  # slow down near obstacles
            step(vx, 0.0, wz)
            t += DT
            if t - last_check[2] > 12.0:
                if math.hypot(x - last_check[0], y - last_check[1]) < 0.15:
                    return "stuck", t
                last_check = (x, y, t)
            if t > budget:
                return "timeout", t
    return "ok", t


def _unstick():
    """Back up then spin, to get out of a wedge against furniture."""
    for _ in range(int(0.8 / DT)):
        step(-0.12, 0.0, 0.0)
    for _ in range(int(1.6 / DT)):
        step(0.0, 0.0, 0.6)


def do_navigate(place, max_sim_s=240.0):
    key = str(place).strip().lower()
    if key not in PLACES:
        return {"ok": False, "error": "unknown_place", "message": f"unknown place: {place}", "known": sorted(PLACES)}
    goal_pose = PLACES[key]
    x, y, z, _ = pose()
    if z < 0.45:
        return {"ok": False, "error": "robot_fell", "message": "robot has fallen", "pose": pose_dict()}
    t, replans = 0.0, 0
    while True:
        way = _plan_to(goal_pose)
        if way is None:
            return {"ok": False, "error": "no_path", "message": f"no path to {key}", "pose": pose_dict()}
        status, t = _track(way, t, max_sim_s)
        if status == "ok":
            break
        if status == "fell":
            return {"ok": False, "error": "robot_fell", "message": "robot fell while navigating", "pose": pose_dict()}
        if status == "timeout":
            return {"ok": False, "error": "timeout", "message": "navigation timed out", "pose": pose_dict()}
        replans += 1
        if replans > 3:
            return {"ok": False, "error": "stuck", "message": "robot made no progress after replans", "pose": pose_dict()}
        _unstick()
        t += 2.4
    target_yaw = math.radians(goal_pose["yaw_deg"])
    for _ in range(int(6.0 / DT)):
        err = wrap(target_yaw - pose()[3])
        if abs(err) < math.radians(8):
            break
        step(0.0, 0.0, float(np.clip(1.2 * err, -0.8, 0.8)))
    for _ in range(60):
        step()
    return {"ok": True, "message": f"arrived at {key}", "pose": pose_dict(), "at_place": at_place(), "sim_time_s": round(t, 1), "replans": replans}


import omni.usd  # noqa: E402
from pxr import Gf, Sdf, Usd, UsdGeom  # noqa: E402

STAGE = omni.usd.get_context().get_stage()
MPU = UsdGeom.GetStageMetersPerUnit(STAGE)

CAM_XF = None
CAM_ANNOT = None
CAM2_XF = None
CAM2_ANNOT = None
try:
    import omni.replicator.core as rep
    from pxr import UsdLux
    from scipy.spatial.transform import Rotation as _Rot

    cam_prim = UsdGeom.Camera.Define(STAGE, "/World/VerifyCam").GetPrim()
    CAM_XF = UsdGeom.Xformable(cam_prim)
    CAM_T = CAM_XF.AddTranslateOp()
    CAM_O = CAM_XF.AddOrientOp()
    if not STAGE.GetPrimAtPath("/World/VerifyLight"):
        light = UsdLux.DistantLight.Define(STAGE, "/World/VerifyLight")
        light.CreateIntensityAttr(3000.0)
    _rp = rep.create.render_product("/World/VerifyCam", (640, 480))
    CAM_ANNOT = rep.AnnotatorRegistry.get_annotator("rgb")
    CAM_ANNOT.attach([_rp])
    # Wide follow cam: elevated 3/4 view of the whole robot + surroundings
    cam2_prim = UsdGeom.Camera.Define(STAGE, "/World/WideCam").GetPrim()
    CAM2_XF = UsdGeom.Xformable(cam2_prim)
    CAM2_T = CAM2_XF.AddTranslateOp()
    CAM2_O = CAM2_XF.AddOrientOp()
    _rp2 = rep.create.render_product("/World/WideCam", (640, 480))
    CAM2_ANNOT = rep.AnnotatorRegistry.get_annotator("rgb")
    CAM2_ANNOT.attach([_rp2])
except Exception as exc:  # noqa: BLE001
    CAM_XF = None
    CAM_ANNOT = None
    CAM2_XF = None
    CAM2_ANNOT = None
    print(f"camera init failed: {exc}", flush=True)


def _update_cam():
    """Keep the verification camera just behind the robot, aimed at the carry point."""
    if CAM_XF is None:
        return
    x, y, _, yaw = pose()
    pos = np.array([x - 0.75 * math.cos(yaw), y - 0.75 * math.sin(yaw), 1.65])
    tgt = np.array([x + 0.28 * math.cos(yaw), y + 0.28 * math.sin(yaw), 0.9])
    f = tgt - pos
    f = f / np.linalg.norm(f)
    zc = -f
    xc = np.cross([0.0, 0.0, 1.0], zc)
    n = np.linalg.norm(xc)
    if n < 1e-6:
        return
    xc = xc / n
    yc = np.cross(zc, xc)
    q = _Rot.from_matrix(np.column_stack([xc, yc, zc])).as_quat()
    CAM_T.Set(Gf.Vec3d(*(pos / MPU)))
    CAM_O.Set(Gf.Quatf(q[3], Gf.Vec3f(q[0], q[1], q[2])))
    _update_cam2()


def _update_cam2():
    """Wide 3/4 follow view: 2.2m behind, 1.1m right, 2.0m up, aimed at chest."""
    if CAM2_XF is None:
        return
    x, y, _, yaw = pose()
    pos = np.array([
        x - 2.2 * math.cos(yaw) + 1.1 * math.sin(yaw),
        y - 2.2 * math.sin(yaw) - 1.1 * math.cos(yaw),
        2.0,
    ])
    tgt = np.array([x, y, 0.85])
    f = tgt - pos
    f = f / np.linalg.norm(f)
    zc = -f
    xc = np.cross([0.0, 0.0, 1.0], zc)
    n = np.linalg.norm(xc)
    if n < 1e-6:
        return
    xc = xc / n
    yc = np.cross(zc, xc)
    q = _Rot.from_matrix(np.column_stack([xc, yc, zc])).as_quat()
    CAM2_T.Set(Gf.Vec3d(*(pos / MPU)))
    CAM2_O.Set(Gf.Quatf(q[3], Gf.Vec3f(q[0], q[1], q[2])))


FRIDGE_FRONT = (3.73, -4.77)
REACH_M = 1.2
HINGES = {"Group_356": ((3.389, -4.77), 100.0), "Group_361": ((4.075, -4.77), -100.0)}
APPLE_REST = (3.73, -5.0, 1.21)
CARRY_OFFSET = (0.28, 0.0, 0.95)
TABLE_TARGET = (3.30, -1.92, 0.80)  # dining-table surface, next to the pot
PRIMS = {}
SKILL = {"fridge_open": False, "holding": None, "door_angle": 0.0}


def _find_fridge_groups():
    found = {}
    scene = STAGE.GetPrimAtPath("/World/env_0/scene")
    for prim in Usd.PrimRange(scene, Usd.TraverseInstanceProxies()):
        path = prim.GetPath().pathString
        if "/refrigerator/" in path and path.endswith(tuple("/Instance/" + g for g in HINGES)):
            found[path.rsplit("/", 1)[-1]] = prim
    return found


def _setup_scripted_world():
    cache = UsdGeom.XformCache()
    for name, prim in _find_fridge_groups().items():
        PRIMS[name] = {
            "prim": prim,
            "W0": cache.GetLocalToWorldTransform(prim),
            "parent_inv": cache.GetLocalToWorldTransform(prim.GetParent()).GetInverse(),
        }
    apple = UsdGeom.Sphere.Define(STAGE, Sdf.Path("/World/Apple"))
    apple.GetRadiusAttr().Set(0.04 / MPU)
    apple.GetDisplayColorAttr().Set([Gf.Vec3f(0.85, 0.05, 0.05)])
    PRIMS["apple"] = apple.GetPrim()
    _place_apple(APPLE_REST)
    print("SCRIPTED_WORLD doors=", sorted(k for k in PRIMS if k.startswith("Group")), flush=True)


def _place_apple(p):
    xf = UsdGeom.Xformable(PRIMS["apple"])
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(p[0] / MPU, p[1] / MPU, p[2] / MPU))


def _set_door_angle(name, angle_deg):
    info = PRIMS[name]
    (px, py), _ = HINGES[name]
    pivot = Gf.Vec3d(px / MPU, py / MPU, 0.0)
    rot = Gf.Matrix4d(1.0)
    rot.SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), angle_deg))
    t_in = Gf.Matrix4d(1.0)
    t_in.SetTranslate(-pivot)
    t_out = Gf.Matrix4d(1.0)
    t_out.SetTranslate(pivot)
    local = info["W0"] * (t_in * rot * t_out) * info["parent_inv"]
    ops = UsdGeom.Xformable(info["prim"]).GetOrderedXformOps()
    trans_op = next(o for o in ops if o.GetOpType() == UsdGeom.XformOp.TypeTranslate)
    orient_op = next(o for o in ops if o.GetOpType() == UsdGeom.XformOp.TypeOrient)
    t = local.ExtractTranslation()
    q = local.RemoveScaleShear().ExtractRotationQuat()
    if trans_op.GetPrecision() == UsdGeom.XformOp.PrecisionFloat:
        trans_op.Set(Gf.Vec3f(t))
    else:
        trans_op.Set(Gf.Vec3d(t))
    if orient_op.GetPrecision() == UsdGeom.XformOp.PrecisionFloat:
        orient_op.Set(Gf.Quatf(q))
    else:
        orient_op.Set(Gf.Quatd(q))


def _mark_door_obstacle(opened):
    """Project the current door bbox into the dynamic-obstacle layer."""
    global BLOCKED_DYN
    BLOCKED_DYN = np.zeros_like(FREE)
    if not opened:
        return
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    for name in HINGES:
        if name not in PRIMS:
            continue
        r = cache.ComputeWorldBound(PRIMS[name]["prim"]).ComputeAlignedRange()
        mn, mx = r.GetMin(), r.GetMax()
        cells = [to_cell(mn[0] * MPU, mn[1] * MPU), to_cell(mx[0] * MPU, mx[1] * MPU)]
        x0, x1 = sorted(c[0] for c in cells)
        y0, y1 = sorted(c[1] for c in cells)
        for cx in range(max(0, x0 - 1), min(W, x1 + 2)):
            for cy in range(max(0, y0 - 1), min(H, y1 + 2)):
                BLOCKED_DYN[cy, cx] = True


def _animate_doors(opening, frames=90):
    start = SKILL["door_angle"]
    end = 1.0 if opening else 0.0
    for i in range(1, frames + 1):
        s = start + (end - start) * i / frames
        for name, (_, full) in HINGES.items():
            if name in PRIMS:
                _set_door_angle(name, full * s)
        step()
    SKILL["door_angle"] = end
    SKILL["fridge_open"] = opening
    _mark_door_obstacle(opening)


def _carry_point():
    x, y, z, yaw = pose()
    return (
        x + CARRY_OFFSET[0] * math.cos(yaw),
        y + CARRY_OFFSET[0] * math.sin(yaw),
        z - 0.8 + CARRY_OFFSET[2],
    )


def update_held():
    if SKILL["holding"] == "apple" and "apple" in PRIMS:
        _place_apple(_carry_point())


def _near(pt):
    x, y, _, _ = pose()
    return math.hypot(x - pt[0], y - pt[1]) <= REACH_M


def _near_fridge():
    x, y, _, _ = pose()
    return math.hypot(x - FRIDGE_FRONT[0], y - FRIDGE_FRONT[1]) < REACH_M


# --- scripted arm animation ----------------------------------------------
_ART = None
ARM_DOFS = {}
ARM_TARGET = None  # dof_name -> target position, held every step while set


def _art():
    """Lazy handle to the G1 articulation (task -> robot -> articulation)."""
    global _ART
    if _ART is None:
        try:
            task = next(iter(env.runner.current_tasks.values()))
            robot = next(iter(task.robots.values()))
            _ART = robot.articulation
        except Exception:  # noqa: BLE001
            _ART = False
    return _ART if _ART is not False else None


def _arm_dof(name):
    if name not in ARM_DOFS:
        art = _art()
        try:
            ARM_DOFS[name] = art.get_dof_index(name) if art is not None else -1
        except Exception:  # noqa: BLE001
            ARM_DOFS[name] = -1
    return ARM_DOFS[name] if ARM_DOFS[name] >= 0 else None


def _arm_tick():
    """Drive arm dofs ~12%/step toward ARM_TARGET via PD position targets."""
    if not ARM_TARGET:
        return
    art = _art()
    if art is None:
        return
    names, idx = [], []
    for n in ARM_TARGET:
        i = _arm_dof(n)
        if i is not None:
            names.append(n)
            idx.append(i)
    if not idx:
        return
    try:
        cur = np.asarray(art.get_joint_positions(joint_indices=idx), dtype=np.float64)
        tgt = np.array([ARM_TARGET[n] for n in names])
        nxt = cur + (tgt - cur) * 0.12
        art.apply_action(ArticulationAction(joint_positions=nxt, joint_indices=np.array(idx)))
    except Exception:  # noqa: BLE001
        pass


def _arm_go(target, settle_steps=40):
    """Set a new arm target and let the sim run settle_steps frames."""
    global ARM_TARGET
    ARM_TARGET = dict(target) if target else None
    for _ in range(settle_steps):
        step()


def _arm_pose(pre, sp, sr, el, wp=0.0):
    """Build a single-arm pose dict; roll sign mirrored per side."""
    d = {
        f"{pre}_shoulder_pitch_joint": sp,
        f"{pre}_shoulder_roll_joint": sr,
        f"{pre}_elbow_joint": el,
        f"{pre}_wrist_pitch_joint": wp,
    }
    return {n: v for n, v in d.items() if _arm_dof(n) is not None}


POSE_REACH_R = _arm_pose("right", -1.05, -0.30, -0.40)   # right arm forward
POSE_REACH_LR = {**_arm_pose("left", -0.90, 0.20, -0.40),
                 **_arm_pose("right", -0.90, -0.20, -0.40)}  # both arms forward
POSE_CARRY = {**_arm_pose("left", -0.55, 0.15, -1.15),
              **_arm_pose("right", -0.55, -0.15, -1.15)}   # both forearms up, carry
POSE_LOW = {**_arm_pose("left", -0.40, 0.10, -0.85),
            **_arm_pose("right", -0.40, -0.10, -0.85)}   # both arms lowered to table
POSE_NEUTRAL = {**_arm_pose("left", 0.0, 0.0, 0.0),
                **_arm_pose("right", 0.0, 0.0, 0.0)}     # arms hang
# finger/hand dofs if the articulation exposes them — curled on grasp
GRIP_CURL = {n: 0.9 for n in ("left_hand_index_0_joint", "left_hand_index_1_joint",
                              "right_hand_index_0_joint", "right_hand_index_1_joint",
                              "left_hand_thumb_0_joint", "left_hand_thumb_1_joint",
                              "right_hand_thumb_0_joint", "right_hand_thumb_1_joint")
             if _arm_dof(n) is not None}
GRIP_OPEN = {n: 0.0 for n in GRIP_CURL}


def do_vla(instruction, timeout_s=60.0):
    text = str(instruction).lower()
    if not PRIMS.get("apple"):
        return {"ok": False, "error": "world_not_ready", "message": "scripted world is not initialised"}
    if "fridge" in text and ("open" in text or "close" in text):
        opening = "open" in text
        if not _near_fridge():
            return {"ok": False, "error": "target_not_reachable", "message": "fridge is not within reach; navigate to kitchen first"}
        if opening == SKILL["fridge_open"]:
            return {"ok": True, "message": "fridge already " + ("open" if opening else "closed")}
        _arm_go(POSE_REACH_R, 45)          # reach toward the door
        _animate_doors(opening)            # arm stays extended during swing
        _arm_go(POSE_NEUTRAL, 40)          # retract
        ARM_TARGET or _arm_go(None)
        return {"ok": True, "message": "fridge opened" if opening else "fridge closed", "scripted": True}
    if "apple" in text and any(k in text for k in ("pick", "grasp", "take", "grab")):
        if SKILL["holding"] == "apple":
            return {"ok": True, "message": "already holding apple", "holding": "apple"}
        if not _near_fridge():
            return {"ok": False, "error": "target_not_reachable", "message": "apple is not within reach"}
        if not SKILL["fridge_open"]:
            return {"ok": False, "error": "occluded", "message": "apple is inside a closed fridge"}
        a = APPLE_REST
        c = _carry_point()
        _arm_go({**POSE_REACH_LR, **GRIP_OPEN}, 45)      # both arms into the fridge
        for i in range(1, 61):
            s = i / 60.0
            _place_apple(tuple(a[k] + (c[k] - a[k]) * s for k in range(3)))
            step()
        SKILL["holding"] = "apple"
        update_held()
        _arm_go({**POSE_CARRY, **GRIP_CURL}, 40)         # lift to carry, keep holding pose
        return {"ok": True, "message": "apple grasped", "holding": "apple", "scripted": True}
    if "apple" in text and any(k in text for k in ("place", "put", "set down", "lay", "leave")):
        if SKILL["holding"] != "apple":
            return {"ok": False, "error": "not_holding", "message": "not holding the apple"}
        if not _near(TABLE_TARGET):
            return {"ok": False, "error": "target_not_reachable", "message": "dining table is not within reach"}
        a = _carry_point()
        _arm_go({**POSE_LOW, **GRIP_CURL}, 40)           # lower toward the table
        for i in range(1, 61):
            s = i / 60.0
            step()
            # write after step() so update_held() cannot snap the apple back to the carry point
            _place_apple(tuple(a[k] + (TABLE_TARGET[k] - a[k]) * s for k in range(3)))
        SKILL["holding"] = None
        _arm_go(POSE_NEUTRAL, 40)                        # release and retract
        _arm_go(None)
        return {"ok": True, "message": "apple placed on dining table", "scripted": True}
    return {
        "ok": False,
        "error": "unsupported_instruction",
        "message": f"scripted skills cover: open/close fridge, pick apple, place apple on dining table. Got: {instruction}",
    }


def do_camera():
    if CAM_ANNOT is None:
        return {"ok": False, "error": "camera_unavailable", "message": "scene camera not initialised"}
    _update_cam()
    for _ in range(6):
        step()
    try:
        rep.orchestrator.step(rt_subframes=1, delta_time=0.0, pause_timeline=False)
    except TypeError:
        # older orchestrator without pause_timeline kwarg: step then resume timeline
        try:
            rep.orchestrator.step()
        except Exception as exc:  # noqa: BLE001
            print(f"rep step failed: {exc}", flush=True)
        try:
            import omni.timeline

            omni.timeline.get_timeline_interface().play()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        print(f"rep step failed: {exc}", flush=True)
    rgba = np.asarray(CAM_ANNOT.get_data())
    if rgba.size == 0:
        return {"ok": False, "error": "empty_frame", "message": "camera returned no frame", "dbg_is_render": bool(env.is_render)}
    rgb = rgba[..., :3]
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb * 255.0, 0, 255).astype(np.uint8) if float(rgb.max()) <= 1.0 else rgb.astype(np.uint8)
    dbg = {"min": int(rgb.min()), "max": int(rgb.max()), "mean": round(float(rgb.mean()), 2)}
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return {
        "ok": True,
        "message": "scene image captured",
        "dbg": dbg,
        "png_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "pose": pose_dict(),
        "at_place": at_place(),
        "holding": SKILL["holding"],
        "fridge_open": SKILL["fridge_open"],
    }


# --- MP4 recorder: periodic Replicator snapshots -> ffmpeg encode ----------
# Lighter than the GUI viewport or webrtc stream: renders at ~fps in the sim
# loop, buffers JPEGs on disk, encodes once on stop.
REC = {"on": False, "dir": "/tmp/isaac_frames", "idx": 0, "last": 0.0, "fps": 4.0}
REC_VIDEO = "/tmp/isaac_rec.mp4"


def _to_rgb(rgba):
    if rgba.size == 0:
        return None
    rgb = rgba[..., :3]
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb * 255.0, 0, 255).astype(np.uint8) if float(rgb.max()) <= 1.0 else rgb.astype(np.uint8)
    return rgb


def _render_frame_rgbs():
    """One orchestrator step, then read both camera annotators."""
    if CAM_ANNOT is None:
        return None, None
    try:
        rep.orchestrator.step(rt_subframes=1, delta_time=0.0, pause_timeline=False)
    except Exception:  # noqa: BLE001
        try:
            rep.orchestrator.step()
        except Exception:  # noqa: BLE001
            return None, None
    rgb_a = _to_rgb(np.asarray(CAM_ANNOT.get_data()))
    rgb_b = _to_rgb(np.asarray(CAM2_ANNOT.get_data())) if CAM2_ANNOT is not None else None
    return rgb_a, rgb_b


def _maybe_record():
    if not REC["on"]:
        return
    now = time.time()
    if now - REC["last"] < 1.0 / REC["fps"]:
        return
    REC["last"] = now
    rgb_a, rgb_b = _render_frame_rgbs()
    if rgb_a is None:
        return
    Image.fromarray(rgb_a).save(os.path.join(REC["dir"], f"f_{REC['idx']:05d}_a.jpg"), format="JPEG", quality=80)
    if rgb_b is not None:
        Image.fromarray(rgb_b).save(os.path.join(REC["dir"], f"f_{REC['idx']:05d}_b.jpg"), format="JPEG", quality=80)
    REC["idx"] += 1


def do_record(cmd, fps=4.0):
    if cmd == "start":
        os.makedirs(REC["dir"], exist_ok=True)
        for f in os.listdir(REC["dir"]):
            os.remove(os.path.join(REC["dir"], f))
        REC.update({"on": True, "idx": 0, "last": 0.0, "fps": float(fps) if fps else 4.0})
        return {"ok": True, "message": "recording started", "fps": REC["fps"], "dir": REC["dir"]}
    if cmd == "stop":
        REC["on"] = False
        n = REC["idx"]
        if n == 0:
            return {"ok": False, "error": "no_frames"}
        if os.path.exists(os.path.join(REC["dir"], "f_00000_b.jpg")):
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", str(REC["fps"]), "-i", os.path.join(REC["dir"], "f_%05d_a.jpg"),
                "-framerate", str(REC["fps"]), "-i", os.path.join(REC["dir"], "f_%05d_b.jpg"),
                "-filter_complex", "hstack", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                REC_VIDEO,
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error", "-framerate", str(REC["fps"]),
                "-i", os.path.join(REC["dir"], "f_%05d_a.jpg"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", REC_VIDEO,
            ]
        rc = subprocess.call(cmd)
        if rc != 0 or not os.path.exists(REC_VIDEO):
            return {"ok": False, "error": "ffmpeg_failed", "rc": rc}
        return {"ok": True, "message": "video encoded", "frames": n, "video": REC_VIDEO,
                "size_mb": round(os.path.getsize(REC_VIDEO) / 1048576, 2)}
    return {"ok": False, "error": "unknown_cmd"}


def do_world():
    out = {"ok": True, "message": "world state", "fridge_open": SKILL["fridge_open"], "holding": SKILL["holding"]}
    scene = STAGE.GetPrimAtPath("/World/env_0/scene")
    sm = UsdGeom.XformCache().GetLocalToWorldTransform(scene)
    out["stage_mpu"] = MPU
    out["scene_diag"] = [round(sm[i][i], 4) for i in range(3)]
    out["scene_origin"] = [round(v, 3) for v in sm.ExtractTranslation()]
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    for name in HINGES:
        if name in PRIMS:
            r = cache.ComputeWorldBound(PRIMS[name]["prim"]).ComputeAlignedRange()
            out[name] = {"min": [round(v * MPU, 3) for v in r.GetMin()], "max": [round(v * MPU, 3) for v in r.GetMax()]}
    t = UsdGeom.Xformable(PRIMS["apple"]).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
    out["apple"] = [round(v * MPU, 3) for v in t]
    return out


JOBS = queue.Queue()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _run(self, fn, *a):
        done = threading.Event()
        box = {}
        JOBS.put((fn, a, done, box))
        done.wait()
        self._send(200, box["result"])

    def do_GET(self):
        if self.path == "/view":
            try:
                body = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cam_view.html"), "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self._send(404, {"ok": False, "error": "viewer_missing"})
        elif self.path == "/pose":
            self._run(do_pose)
        elif self.path == "/places":
            self._run(do_places)
        elif self.path == "/world":
            self._run(do_world)
        elif self.path == "/camera":
            self._run(do_camera)
        elif self.path == "/video":
            try:
                body = open(REC_VIDEO, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self._send(404, {"ok": False, "error": "no_video"})
        else:
            self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/navigate":
            self._run(do_navigate, data.get("place", ""))
        elif self.path == "/vla":
            self._run(do_vla, data.get("instruction", ""), float(data.get("timeout_s", 60.0)))
        elif self.path == "/record":
            self._run(do_record, data.get("cmd", ""), float(data.get("fps", 4.0)))
        else:
            self._send(404, {"ok": False, "error": "not_found"})

    def log_message(self, *a):
        pass


def _measure_robot_radius():
    try:
        cands = [(len(p.GetPath().pathString), p) for p in STAGE.Traverse() if "g1" in p.GetName().lower()]
        if not cands:
            return 0.25
        prim = min(cands, key=lambda c: c[0])[1]
        r = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_]).ComputeWorldBound(prim).ComputeAlignedRange()
        mn, mx = r.GetMin(), r.GetMax()
        half = max(mx[0] - mn[0], mx[1] - mn[1]) * MPU / 2.0
        return float(min(max(half + 0.05, 0.20), 0.40))
    except Exception as exc:
        print(f"radius measure failed: {exc}", flush=True)
        return 0.25


RADIUS = args.radius if args.radius > 0 else _measure_robot_radius()
_build_costmap(RADIUS)
print(f"COSTMAP robot_radius={RADIUS:.3f}m", flush=True)
_setup_scripted_world()
server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(f"BRIDGE_READY http://127.0.0.1:{args.port} places={sorted(PLACES)}", flush=True)

# Freeze all startup objects out of GC tracking: cyclic-GC traversals over the
# USD/Omni object graph can segfault natively with no Python traceback.
gc.freeze()

while env.simulation_app.is_running():
    try:
        fn, a, done, box = JOBS.get_nowait()
    except queue.Empty:
        step()
        _maybe_record()
        continue
    try:
        box["result"] = fn(*a)
    except Exception as exc:
        box["result"] = {"ok": False, "error": "bridge_exception", "message": str(exc)}
    done.set()

server.shutdown()
env.close()
