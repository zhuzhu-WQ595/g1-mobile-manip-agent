from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path.cwd().resolve()

ALLOWED_COMMANDS = {
    ("python", "--version"),
    ("python", "-m", "pytest"),
    ("python", "-m", "pytest", "-q"),
}

PATH_TOOLS = {
    "list_files",
    "read_file",
    "write_file",
    "append_file",
    "create_folder",
    "search_files",
    "preview_file_head",
    "request_overwrite_file",
    "request_edit_file",
}

SAFE_STATE_TOOLS = {
    "remember_memory",
    "read_memory",
    "clear_memory",
    "create_task",
    "list_tasks",
    "get_task_details",
    "start_task",
    "complete_task",
    "fail_task",
    "retry_task",
    "cancel_task",
    "update_task",
    "list_skills",
    "read_skill",
    "get_recent_tool_events",
    "get_workspace_summary",
    "count_files_by_extension",
    "save_experiment_note",
    "approve_pending_action",
    "cancel_pending_action",
    "list_pending_approvals",
    "list_approval_history",
    "get_approval_details",
    "create_plan",
    "create_task_plan",
    "get_task_plan",
    "validate_task_plan",
    "run_task_cycle",
    "list_plans",
    "update_plan_step",
    "suggest_next_plan_step",
    "execute_plan_step",
    "execute_next_plan_step",
    "resolve_blocked_step",
    "diagnose_blocked_step",
}

# Stop, status, cancellation, and sensing stay available without motion authorization.
SAFE_ROBOT_TOOLS = {
    "robot_stop",
    "robot_emergency_stop",
    "robot_get_status",
    "robot_get_action_status",
    "robot_cancel_action",
    "robot_speak",
    "robot_capture_image",
    "duck_stop",
    "slam_get_pose",
    "nav_list_places",
    "vision_verify",
}

MOTION_ROBOT_TOOLS = {
    "nav_go_to_place",
    "vla_run_skill",
    "robot_move",
    "robot_rotate",
    "robot_execute_plan",
    "duck_walk",
    "duck_sit",
    "duck_kick",
    "duck_roulade",
    "duck_ground_pick",
    "duck_head",
    "duck_body_pose",
}

REMOTE_SERVICE_TOOLS = {"invoke_remote_service"}
PERCEPTION_TOOLS = {"perception_observe", "perception_check_path"}


def resolve_workspace_path(path: str) -> Path:
    candidate = (WORKSPACE_ROOT / path).resolve()
    try:
        candidate.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise PermissionError(f"Path is outside workspace: {path}") from exc
    return candidate


def split_command(command: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(command, posix=False))
    except ValueError as exc:
        raise PermissionError(f"Cannot parse command: {command}") from exc


def check_tool_call(name: str, arguments: dict[str, Any]) -> None:
    if name in PATH_TOOLS:
        resolve_workspace_path(str(arguments.get("path", ".")))
        return

    if name in SAFE_STATE_TOOLS:
        return

    if name in SAFE_ROBOT_TOOLS:
        return

    if name in MOTION_ROBOT_TOOLS:
        mode = os.environ.get("ROBOT_MODE", "simulated").strip().lower()
        motion_enabled = os.environ.get("ROBOT_ALLOW_MOTION", "").strip().lower() in {"1", "true", "yes"}
        if mode == "simulated" or motion_enabled:
            return
        raise PermissionError(
            "Real robot motion is disabled. An operator must set ROBOT_ALLOW_MOTION=1 after the gateway is ready."
        )

    if name in REMOTE_SERVICE_TOOLS:
        service = str(arguments.get("service", "")).strip()
        operation = str(arguments.get("operation", "")).strip()
        payload = arguments.get("payload", {})
        if not service or "://" in service:
            raise PermissionError("Remote calls require a configured symbolic service name")
        if not operation:
            raise PermissionError("Remote calls require an operation name")
        if not isinstance(payload, dict):
            raise PermissionError("Remote service payload must be an object")
        return

    if name in PERCEPTION_TOOLS:
        if name == "perception_check_path":
            direction = str(arguments.get("direction", ""))
            distance = float(arguments.get("distance", 0.0))
            if direction not in {"forward", "backward"}:
                raise PermissionError("Perception path direction must be forward or backward")
            if distance <= 0 or distance > 5.0:
                raise PermissionError("Perception path distance must be greater than 0 and at most 5 meters")
        return

    if name in {"robot_set_wheel_speed", "robot_set_speed"}:
        raise PermissionError("Direct low-level robot control is not available to the Agent")

    if name == "run_command":
        command = split_command(str(arguments.get("command", "")))
        if command not in ALLOWED_COMMANDS:
            allowed = ", ".join(" ".join(cmd) for cmd in sorted(ALLOWED_COMMANDS))
            raise PermissionError(
                f"Command not allowed: {' '.join(command)}. Allowed: {allowed}"
            )
        return

    raise PermissionError(f"Unknown tool: {name}")
