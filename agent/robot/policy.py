from __future__ import annotations

from typing import Any


ALLOWED_PLAN_ACTIONS = {"move", "rotate", "stop", "speak", "capture_image"}
MOTION_TOOLS = {
    "robot_move",
    "robot_rotate",
    "robot_execute_plan",
    "duck_walk",
    "duck_kick",
    "duck_roulade",
    "duck_ground_pick",
}
PERCEPTION_TOOLS = {"perception_observe", "perception_check_path"}


def validate_plan(steps: list[dict[str, Any]]) -> None:
    if not steps:
        raise ValueError("robot plan cannot be empty")
    if len(steps) > 20:
        raise ValueError("robot plan cannot contain more than 20 steps")
    for index, step in enumerate(steps, start=1):
        action = str(step.get("action", ""))
        if action not in ALLOWED_PLAN_ACTIONS:
            raise ValueError(f"step {index} has unsupported action: {action}")


def check_motion_against_latest_perception(
    tool_name: str,
    arguments: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    if tool_name not in MOTION_TOOLS:
        return
    latest_index = next(
        (index for index in range(len(events) - 1, -1, -1) if events[index].get("tool") in PERCEPTION_TOOLS),
        None,
    )
    if latest_index is None:
        return
    latest = events[latest_index]
    if any(event.get("tool") in MOTION_TOOLS for event in events[latest_index + 1 :]):
        raise PermissionError("Robot motion blocked because a new perception check is required after motion")
    if latest.get("status") != "succeeded":
        raise PermissionError("Robot motion blocked because the latest perception request failed")
    observation = latest.get("observation")
    if not isinstance(observation, dict):
        raise PermissionError("Robot motion blocked because perception returned no structured observation")
    if observation.get("path_clear") is not True:
        raise PermissionError("Robot motion blocked because perception did not confirm a clear path")
    if latest.get("tool") == "perception_check_path":
        if tool_name != "robot_move":
            raise PermissionError("Robot motion blocked because the path check does not cover this action")
        assessed = latest.get("arguments", {})
        assessed_direction = str(assessed.get("direction", ""))
        assessed_distance = float(assessed.get("distance", 0.0))
        requested_direction = str(arguments.get("direction", "forward"))
        requested_distance = float(arguments.get("distance", 0.0))
        if requested_direction != assessed_direction or requested_distance > assessed_distance:
            raise PermissionError(
                "Robot motion blocked because the requested path exceeds the latest perception check"
            )
