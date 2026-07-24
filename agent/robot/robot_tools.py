from __future__ import annotations

import json
from typing import Any

from .robot_adapter import get_robot_adapter
from .robot_protocol import RobotCommand, result_text
from .robot_safety import validate_command, validate_plan


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


def _execute(action: str, params: dict[str, Any] | None = None) -> str:
    adapter = get_robot_adapter()
    command = RobotCommand(action, params or {})
    state = adapter.get_state()
    validate_command(command, state)
    return result_text(adapter.execute(command))


def robot_get_status() -> str:
    return _execute("get_status")


def robot_move(distance: float, direction: str = "forward", speed: float = 0.3) -> str:
    return _execute("move", {"distance": distance, "direction": direction, "speed": speed})


def robot_rotate(angle: float, speed: float = 0.3) -> str:
    return _execute("rotate", {"angle": angle, "speed": speed})


def robot_stop() -> str:
    return _execute("stop")


def robot_set_wheel_speed(left: float, right: float) -> str:
    return _execute("set_wheel_speed", {"left": left, "right": right})


def robot_speak(text: str) -> str:
    return _execute("speak", {"text": text})


def robot_capture_image() -> str:
    return _execute("capture_image")


def robot_execute_plan(steps: list[dict[str, Any]] | str) -> str:
    if isinstance(steps, str):
        steps = json.loads(steps)
    validate_plan(steps)
    outputs: list[str] = []
    for index, step in enumerate(steps, start=1):
        action = str(step.get("action", ""))
        params = dict(step.get("params", {}))
        try:
            outputs.append(f"step {index}: " + _execute(action, params))
        except Exception as exc:
            outputs.append(f"step {index}: error: {type(exc).__name__}: {exc}")
            outputs.append("plan stopped")
            break
    return "\n".join(outputs)


ROBOT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    _schema("robot_get_status", "Read robot state, battery, pose, obstacle distance, and stop state.", {}, []),
    _schema(
        "robot_move",
        "Move the robot forward or backward. Safety limits are enforced by the backend.",
        {
            "distance": {"type": "number", "description": "Distance in meters. Max single move is 1.0m."},
            "direction": {"type": "string", "enum": ["forward", "backward"]},
            "speed": {"type": "number", "description": "Normalized speed. Recommended 0.1-0.3; max 0.5."},
        },
        ["distance"],
    ),
    _schema(
        "robot_rotate",
        "Rotate the robot in place. Positive angle turns right, negative angle turns left.",
        {
            "angle": {"type": "number", "description": "Degrees. Max single rotation is 90 degrees."},
            "speed": {"type": "number", "description": "Normalized speed. Recommended 0.1-0.3; max 0.5."},
        },
        ["angle"],
    ),
    _schema("robot_stop", "Stop the robot immediately.", {}, []),
    _schema(
        "robot_set_wheel_speed",
        "Set differential-drive wheel speeds directly. Use only for low-level control.",
        {"left": {"type": "number"}, "right": {"type": "number"}},
        ["left", "right"],
    ),
    _schema("robot_speak", "Speak text through the robot speaker or simulator.", {"text": {"type": "string"}}, ["text"]),
    _schema("robot_capture_image", "Capture a camera frame or simulated frame reference.", {}, []),
    _schema(
        "robot_execute_plan",
        "Execute a short checked plan of robot steps. Each step has action and params.",
        {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"action": {"type": "string"}, "params": {"type": "object"}},
                    "required": ["action"],
                },
            }
        },
        ["steps"],
    ),
]


ROBOT_TOOL_HANDLERS: dict[str, Any] = {
    "robot_get_status": robot_get_status,
    "robot_move": robot_move,
    "robot_rotate": robot_rotate,
    "robot_stop": robot_stop,
    "robot_set_wheel_speed": robot_set_wheel_speed,
    "robot_speak": robot_speak,
    "robot_capture_image": robot_capture_image,
    "robot_execute_plan": robot_execute_plan,
}