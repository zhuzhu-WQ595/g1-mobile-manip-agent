from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .robot_protocol import RobotCommand, RobotState


@dataclass(frozen=True)
class SafetyLimits:
    max_single_move_m: float = 1.0
    max_single_rotate_deg: float = 90.0
    max_speed: float = 0.5
    max_wheel_speed: float = 0.6
    min_front_obstacle_m: float = 0.35
    min_battery_percent: float = 15.0
    max_plan_steps: int = 10


LIMITS = SafetyLimits()
ALLOWED_PLAN_ACTIONS = {"move", "rotate", "stop", "speak", "get_status"}


def _number(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc


def validate_command(command: RobotCommand, state: RobotState, limits: SafetyLimits = LIMITS) -> None:
    action = command.action
    params = command.params

    if action in {"get_status", "stop", "capture_image", "speak"}:
        return

    if state.battery_percent < limits.min_battery_percent:
        raise ValueError("Battery too low for motion; stop or recharge first")

    if action == "move":
        distance = abs(_number(params.get("distance"), "distance"))
        speed = abs(_number(params.get("speed", 0.3), "speed"))
        direction = str(params.get("direction", "forward"))
        if direction not in {"forward", "backward"}:
            raise ValueError("direction must be forward or backward")
        if distance <= 0:
            raise ValueError("distance must be greater than 0")
        if distance > limits.max_single_move_m:
            raise ValueError(f"single move exceeds safety limit: {distance}m > {limits.max_single_move_m}m")
        if speed > limits.max_speed:
            raise ValueError(f"speed exceeds safety limit: {speed} > {limits.max_speed}")
        if direction == "forward" and state.front_obstacle_m < limits.min_front_obstacle_m:
            raise ValueError("front obstacle is too close for forward movement")
        return

    if action == "rotate":
        angle = abs(_number(params.get("angle"), "angle"))
        speed = abs(_number(params.get("speed", 0.3), "speed"))
        if angle <= 0:
            raise ValueError("angle must be non-zero")
        if angle > limits.max_single_rotate_deg:
            raise ValueError(f"single rotation exceeds safety limit: {angle}deg > {limits.max_single_rotate_deg}deg")
        if speed > limits.max_speed:
            raise ValueError(f"speed exceeds safety limit: {speed} > {limits.max_speed}")
        return

    if action == "set_wheel_speed":
        left = abs(_number(params.get("left"), "left"))
        right = abs(_number(params.get("right"), "right"))
        if left > limits.max_wheel_speed or right > limits.max_wheel_speed:
            raise ValueError(f"wheel speed exceeds safety limit: {limits.max_wheel_speed}")
        return

    raise ValueError(f"unsupported robot action: {action}")


def validate_plan(steps: list[dict[str, Any]], limits: SafetyLimits = LIMITS) -> None:
    if len(steps) > limits.max_plan_steps:
        raise ValueError(f"plan has too many steps: {len(steps)} > {limits.max_plan_steps}")
    for index, step in enumerate(steps, start=1):
        action = str(step.get("action", ""))
        if action not in ALLOWED_PLAN_ACTIONS:
            raise ValueError(f"step {index} has unsupported action: {action}")