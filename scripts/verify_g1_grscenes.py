import sys

import isaacsim  # noqa: F401  (must precede internutopia so carb is importable)
from internutopia.core.config import Config, SimConfig
from internutopia.core.gym_env import Env
from internutopia.macros import gm
from internutopia_extension import import_extensions
from internutopia_extension.configs.robots.g1 import G1RobotCfg, move_by_speed_cfg
from internutopia_extension.configs.tasks import SingleInferenceTaskCfg

SCENE_ID = sys.argv[1] if len(sys.argv) > 1 else "MV7J6NIKTKJZ2AABAAAAADA8_usd"
SCENE_FILE = sys.argv[2] if len(sys.argv) > 2 else "start_result_navigation.usd"
STEPS = int(sys.argv[3]) if len(sys.argv) > 3 else 600

if SCENE_ID.startswith("/"):
    scene_path = SCENE_ID
else:
    scene_path = f"{gm.ASSET_PATH}/scenes/GRScenes-100/home_scenes/scenes/{SCENE_ID}/{SCENE_FILE}"
print("scene:", scene_path)

config = Config(
    simulator=SimConfig(
        physics_dt=1 / 240, rendering_dt=1 / 240, use_fabric=False, headless=True, webrtc=False
    ),
    task_configs=[
        SingleInferenceTaskCfg(
            scene_asset_path=scene_path,
            scene_scale=(0.01, 0.01, 0.01) if "GRScenes-100" in scene_path else (1.0, 1.0, 1.0),
            robots=[G1RobotCfg(position=(0.0, 0.0, 0.8), controllers=[move_by_speed_cfg])],
        ),
    ],
)

import_extensions()
env = Env(config)
obs, _ = env.reset()
for i in range(STEPS):
    obs, _, terminated, _, _ = env.step(action={move_by_speed_cfg.name: (0.5, 0.0, 0.0)})
    if i % 100 == 0:
        print(i, obs)
print("OK steps:", STEPS)
env.close()
