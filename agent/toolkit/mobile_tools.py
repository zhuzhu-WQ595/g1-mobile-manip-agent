from __future__ import annotations

import json
from typing import Any

from robot_runtime.isaac_sim import get_mobile_manip_backend

from ..robot.tools import _schema


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def slam_get_pose() -> str:
    return _dump(get_mobile_manip_backend().get_pose())


def nav_list_places() -> str:
    return _dump(get_mobile_manip_backend().list_places())


def nav_go_to_place(place: str) -> str:
    return _dump(get_mobile_manip_backend().navigate_to(place))


def vla_run_skill(instruction: str, timeout_s: float = 60.0) -> str:
    timeout = min(max(float(timeout_s), 1.0), 300.0)
    return _dump(get_mobile_manip_backend().run_vla(instruction, timeout))


def vision_verify(question: str = "") -> str:
    return _dump(get_mobile_manip_backend().verify_scene(question))


MOBILE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema("slam_get_pose", "Read the SLAM-localized robot pose, the named place it is at, and what it is holding.", {}, []),
    _schema("nav_list_places", "List named places (e.g. kitchen, home) known from the SLAM semantic map.", {}, []),
    _schema(
        "nav_go_to_place",
        "Navigate to a named place using SLAM localization and path planning. Blocks until arrival or failure.",
        {"place": {"type": "string", "description": "Place name from nav_list_places."}},
        ["place"],
    ),
    _schema(
        "vla_run_skill",
        "Run the VLA manipulation policy on one short English instruction, e.g. 'open the fridge door' or "
        "'pick up the apple'. Robot must already be near the target. One atomic skill per call.",
        {
            "instruction": {"type": "string"},
            "timeout_s": {"type": "number", "description": "Max seconds, default 60."},
        },
        ["instruction"],
    ),
    _schema(
        "vision_verify",
        "Capture the scene camera image and answer a visual question about the world, e.g. 'Is the robot holding the red apple?'. "
        "Uses a VLM when configured, otherwise an image-based heuristic. Use it to confirm a manipulation or task result.",
        {"question": {"type": "string", "description": "Question about the visible scene."}},
        [],
    ),
]


MOBILE_TOOL_HANDLERS: dict[str, Any] = {
    "slam_get_pose": slam_get_pose,
    "nav_list_places": nav_list_places,
    "nav_go_to_place": nav_go_to_place,
    "vla_run_skill": vla_run_skill,
    "vision_verify": vision_verify,
}
