from __future__ import annotations

from typing import Any, Callable

from ..permissions import check_tool_call
from ..state.approval_store import request_edit_file, request_overwrite_file
from ..toolkit.command_tools import run_command
from ..toolkit.experiment_tools import save_experiment_note
from ..toolkit.file_tools import list_files, preview_file_head, read_file, search_files
from ..toolkit.workspace_tools import count_files_by_extension, get_workspace_summary

PlanToolHandler = Callable[..., str]


PLAN_TOOL_HANDLERS: dict[str, PlanToolHandler] = {
    "read_file": read_file,
    "list_files": list_files,
    "search_files": search_files,
    "preview_file_head": preview_file_head,
    "count_files_by_extension": count_files_by_extension,
    "get_workspace_summary": get_workspace_summary,
    "run_command": run_command,
    "save_experiment_note": save_experiment_note,
    "request_edit_file": request_edit_file,
    "request_overwrite_file": request_overwrite_file,
}


def execute_plan_tool(name: str, arguments: dict[str, Any]) -> str | None:
    handler = PLAN_TOOL_HANDLERS.get(name)
    if handler is None:
        return None
    check_tool_call(name, arguments)
    return handler(**arguments)


def plan_tool_names() -> set[str]:
    return set(PLAN_TOOL_HANDLERS)
