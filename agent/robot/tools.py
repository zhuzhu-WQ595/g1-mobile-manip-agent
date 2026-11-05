from __future__ import annotations

import json
import time
from typing import Any

from contracts.robot import ActionStatus, RobotCommand, RobotResult, result_text

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


def _execute_and_wait(action: str, params: dict[str, Any], timeout: float = 60.0) -> str:
    result = _execute_result(action, params)
    if not result.ok:
        return _serialize_result(result, f"robot.robot_{action}")
    action_id = result.action_id
    if not action_id:
        return _serialize_result(result, f"robot.robot_{action}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.3)
        latest = get_robot_adapter().get_action(action_id)
        status = getattr(latest, "status", "")
        if status in (ActionStatus.SUCCEEDED, ActionStatus.FAILED, ActionStatus.CANCELLED):
            return _serialize_result(latest, f"robot.robot_{action}")
    return _serialize_result(result, f"robot.robot_{action}")


def robot_move(distance: float, direction: str = "forward", speed: float = 0.2) -> str:
    adapter = get_robot_adapter()
    before = adapter.get_state()
    result = _execute_and_wait("move", {"distance": distance, "direction": direction, "speed": speed})
    after = adapter.get_state()
    import math as _math
    dx = after.x - before.x
    dy = after.y - before.y
    actual_dist = _math.sqrt(dx * dx + dy * dy)
    expected_dist = abs(distance)
    print(f"  [verify] move: expected {expected_dist}m, actual {actual_dist:.3f}m, before=({before.x:.2f},{before.y:.2f}) after=({after.x:.2f},{after.y:.2f})")
    if actual_dist < expected_dist * 0.5:
        try:
            payload = json.loads(result)
            payload["ok"] = False
            payload["status"] = ActionStatus.FAILED.value
            payload["error"] = "obstacle_detected"
            payload["message"] = f"robot only moved {actual_dist:.3f}m out of {expected_dist}m; likely hit an obstacle"
            if isinstance(payload.get("state"), dict):
                payload["state"] = after.to_dict()
            return json.dumps(payload, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def robot_rotate(angle: float, speed: float = 0.3) -> str:
    return _execute_and_wait("rotate", {"angle": angle, "speed": speed})


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


def duck_walk(vx: float, vy: float = 0.0, vtheta: float = 0.0) -> str:
    """Walk the MicroDuck at the given velocities."""
    return _execute("walk", {"vx": vx, "vy": vy, "vtheta": vtheta})


def duck_stop() -> str:
    """Stop the MicroDuck (zero all velocity commands)."""
    return _execute("stop")


def duck_sit() -> str:
    """Toggle sit/stand on the MicroDuck."""
    return _execute("sit")


def duck_kick(foot: str = "left") -> str:
    """Kick a ball with the specified foot."""
    return _execute("kick", {"foot": foot})


def duck_roulade() -> str:
    """Trigger a roulade (forward roll)."""
    return _execute("roulade")


def duck_ground_pick() -> str:
    """Trigger a ground pick cycle."""
    return _execute("ground_pick")


def duck_head(neck_pitch: float = 0.0, head_pitch: float = 0.0, head_yaw: float = 0.0, head_roll: float = 0.0) -> str:
    """Set head pose offsets."""
    return _execute("head", {
        "neck_pitch": neck_pitch,
        "head_pitch": head_pitch,
        "head_yaw": head_yaw,
        "head_roll": head_roll,
    })


def duck_body_pose(z: float = 0.0, pitch: float = 0.0, roll: float = 0.0) -> str:
    """Set body pose offsets (z in meters, pitch/roll in radians)."""
    return _execute("body_pose", {"z": z, "pitch": pitch, "roll": roll})


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
    _schema(
        "duck_walk",
        "Walk the MicroDuck robot at given velocities. vx=forward, vy=lateral, vtheta=turn rate.",
        {
            "vx": {"type": "number", "description": "Forward velocity in m/s. Range -0.3 to 0.3."},
            "vy": {"type": "number", "description": "Lateral velocity in m/s. Range -0.2 to 0.2."},
            "vtheta": {"type": "number", "description": "Angular velocity in rad/s. Range -1.5 to 1.5."},
        },
        ["vx"],
    ),
    _schema("duck_stop", "Stop the MicroDuck robot (zero all velocity commands).", {}, []),
    _schema("duck_sit", "Toggle sit/stand posture on the MicroDuck robot.", {}, []),
    _schema(
        "duck_kick",
        "Kick a ball with the MicroDuck robot.",
        {"foot": {"type": "string", "enum": ["left", "right"], "description": "Which foot to kick with."}},
        [],
    ),
    _schema("duck_roulade", "Trigger a roulade (forward roll) on the MicroDuck robot.", {}, []),
    _schema("duck_ground_pick", "Trigger a ground pick cycle on the MicroDuck robot.", {}, []),
    _schema(
        "duck_head",
        "Set head pose offsets on the MicroDuck robot.",
        {
            "neck_pitch": {"type": "number", "description": "Neck pitch offset."},
            "head_pitch": {"type": "number", "description": "Head pitch offset."},
            "head_yaw": {"type": "number", "description": "Head yaw offset."},
            "head_roll": {"type": "number", "description": "Head roll offset."},
        },
        [],
    ),
    _schema(
        "duck_body_pose",
        "Set body pose offsets on the MicroDuck robot (z in meters, pitch/roll in radians).",
        {
            "z": {"type": "number", "description": "Body height offset in meters."},
            "pitch": {"type": "number", "description": "Body pitch offset in radians."},
            "roll": {"type": "number", "description": "Body roll offset in radians."},
        },
        [],
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
    "duck_walk": duck_walk,
    "duck_stop": duck_stop,
    "duck_sit": duck_sit,
    "duck_kick": duck_kick,
    "duck_roulade": duck_roulade,
    "duck_ground_pick": duck_ground_pick,
    "duck_head": duck_head,
    "duck_body_pose": duck_body_pose,
}
