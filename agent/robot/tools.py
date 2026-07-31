from __future__ import annotations

import json
from typing import Any

from contracts.robot import RobotCommand, RobotResult, result_text

from .client import get_robot_adapter
from .policy import validate_plan


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


def _execute_result(action: str, params: dict[str, Any] | None = None) -> RobotResult:
    adapter = get_robot_adapter()
    command = RobotCommand(action, params or {})
    return adapter.execute(command)


def _execute(action: str, params: dict[str, Any] | None = None) -> str:
    return _serialize_result(_execute_result(action, params), f"robot.robot_{action}")


def _serialize_result(result: RobotResult, capability: str) -> str:
    payload = result.to_dict()
    payload["execution_event"] = result.to_execution_event(capability).to_dict()
    return json.dumps(payload, ensure_ascii=False)


def robot_get_status() -> str:
    state = get_robot_adapter().get_state()
    return _serialize_result(RobotResult(True, "status read", state), "robot.robot_get_status")


def robot_move(distance: float, direction: str = "forward", speed: float = 0.3) -> str:
    return _execute("move", {"distance": distance, "direction": direction, "speed": speed})


def robot_rotate(angle: float, speed: float = 0.3) -> str:
    return _execute("rotate", {"angle": angle, "speed": speed})


def robot_stop() -> str:
    return _execute("stop")


def robot_get_action_status(action_id: str) -> str:
    return _serialize_result(
        get_robot_adapter().get_action(action_id),
        "robot.robot_get_action_status",
    )


def robot_cancel_action(action_id: str) -> str:
    return _serialize_result(
        get_robot_adapter().cancel_action(action_id),
        "robot.robot_cancel_action",
    )


def robot_emergency_stop() -> str:
    return _serialize_result(
        get_robot_adapter().emergency_stop(),
        "robot.robot_emergency_stop",
    )


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
            result = _execute_result(action, params)
            outputs.append(f"step {index}: " + result_text(result))
            if not result.ok:
                outputs.append("plan stopped")
                break
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
        "Rotate in place. Positive angles turn left (counterclockwise); negative angles turn right.",
        {
            "angle": {"type": "number", "description": "Degrees. Max single rotation is 90 degrees."},
            "speed": {"type": "number", "description": "Normalized speed. Recommended 0.1-0.3; max 0.5."},
        },
        ["angle"],
    ),
    _schema("robot_stop", "Stop the robot immediately.", {}, []),
    _schema(
        "robot_get_action_status",
        "Read the current status and feedback for a previously submitted robot action.",
        {"action_id": {"type": "string"}},
        ["action_id"],
    ),
    _schema(
        "robot_cancel_action",
        "Request cancellation of a running robot action.",
        {"action_id": {"type": "string"}},
        ["action_id"],
    ),
    _schema("robot_emergency_stop", "Latch the robot emergency stop immediately.", {}, []),
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
    "robot_get_action_status": robot_get_action_status,
    "robot_cancel_action": robot_cancel_action,
    "robot_emergency_stop": robot_emergency_stop,
    "robot_speak": robot_speak,
    "robot_capture_image": robot_capture_image,
    "robot_execute_plan": robot_execute_plan,
}
