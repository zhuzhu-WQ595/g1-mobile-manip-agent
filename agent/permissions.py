from __future__ import annotations

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
    "update_task",
    "list_skills",
    "read_skill",
    "get_recent_tool_events",
    "get_workspace_summary",
    "count_files_by_extension",
    "save_experiment_note",
    "approve_pending_action",
    "list_pending_approvals",
    "create_plan",
    "list_plans",
    "update_plan_step",
    "suggest_next_plan_step",
    "execute_plan_step",
    "execute_next_plan_step",
    "resolve_blocked_step",
    "diagnose_blocked_step",
}

# Robot tools – all allowed (hardware access is behind the controller abstraction)
ROBOT_TOOLS = {
    "robot_move",
    "robot_rotate",
    "robot_stop",
    "robot_get_status",
    "robot_set_wheel_speed",
    "robot_set_speed",
    "robot_speak",
    "robot_capture_image",
    "robot_execute_plan",
}


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

    if name in ROBOT_TOOLS:
        return  # robot tools pass through robot_safety before adapter execution

    if name == "run_command":
        command = split_command(str(arguments.get("command", "")))
        if command not in ALLOWED_COMMANDS:
            allowed = ", ".join(" ".join(cmd) for cmd in sorted(ALLOWED_COMMANDS))
            raise PermissionError(
                f"Command not allowed: {' '.join(command)}. Allowed: {allowed}"
            )
        return

    raise PermissionError(f"Unknown tool: {name}")
