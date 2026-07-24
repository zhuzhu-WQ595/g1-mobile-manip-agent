from __future__ import annotations

from ..plans import (
    create_plan,
    diagnose_blocked_step,
    execute_next_plan_step,
    execute_plan_step,
    list_plans,
    resolve_blocked_step,
    suggest_next_plan_step,
    update_plan_step,
)
from ..state.approval_store import approve_pending_action, list_pending_approvals, request_overwrite_file
from ..state.event_log import read_recent_events
from ..state.memory_store import clear_memory, load_memory, remember
from ..state.skill_store import list_skills, read_skill
from ..state.task_store import create_task, list_tasks, update_task

from .schema import ToolHandler, schema


STATE_TOOL_SCHEMAS: list[dict[str, object]] = [
    schema("remember_memory", "Save a short long-term memory note.", {"text": {"type": "string"}}, ["text"]),
    schema("read_memory", "Read current long-term memory.", {}, []),
    schema("clear_memory", "Clear long-term memory.", {}, []),
    schema(
        "create_task",
        "Create a task in the local task list.",
        {"title": {"type": "string"}, "detail": {"type": "string"}},
        ["title"],
    ),
    schema("list_tasks", "List local tasks.", {}, []),
    schema(
        "update_task",
        "Update a task status to pending, in_progress, or done.",
        {"task_id": {"type": "string"}, "status": {"type": "string"}},
        ["task_id", "status"],
    ),
    schema("list_skills", "List built-in skill notes.", {}, []),
    schema("read_skill", "Read one built-in skill note.", {"name": {"type": "string"}}, ["name"]),
    schema(
        "get_recent_tool_events",
        "Read recent tool event log entries. Use this when the user asks for recent tool calls, tool events, tool logs, or tool history.",
        {
            "limit": {
                "type": "integer",
                "description": "Maximum number of recent events to read. Defaults to 20.",
            }
        },
        [],
    ),
    schema(
        "request_overwrite_file",
        "Create a pending approval to overwrite a workspace file. This does not write the file until the user approves the returned approval ID.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    ),
    schema(
        "approve_pending_action",
        "Approve and execute a previously created pending action by approval ID.",
        {"approval_id": {"type": "string"}},
        ["approval_id"],
    ),
    schema("list_pending_approvals", "List pending approvals.", {}, []),
    schema(
        "create_plan",
        "Create a multi-step plan without executing it. Use this for planning complex tasks.",
        {
            "title": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short ordered steps.",
            },
        },
        ["title", "steps"],
    ),
    schema("list_plans", "List saved multi-step plans.", {}, []),
    schema(
        "update_plan_step",
        "Update one step status in a saved plan.",
        {
            "plan_id": {"type": "string"},
            "step_index": {"type": "integer"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "done", "blocked"]},
        },
        ["plan_id", "step_index", "status"],
    ),
    schema(
        "suggest_next_plan_step",
        "Suggest the next pending step for a saved plan and recommend a likely tool. This does not execute the step or change status.",
        {"plan_id": {"type": "string"}},
        ["plan_id"],
    ),
    schema(
        "execute_plan_step",
        "Execute one supported step from a saved plan, then mark that step done if execution succeeds. Supports simple known step types and summary steps based on previous results.",
        {"plan_id": {"type": "string"}, "step_index": {"type": "integer"}},
        ["plan_id", "step_index"],
    ),
    schema(
        "execute_next_plan_step",
        "Execute the first pending supported step from a saved plan, then mark that step done if execution succeeds. Supports summary steps based on previous results. Executes only one step.",
        {"plan_id": {"type": "string"}},
        ["plan_id"],
    ),
    schema(
        "resolve_blocked_step",
        "Resolve a blocked plan step with a user-provided result, then mark that step done. Do not invent the result.",
        {"plan_id": {"type": "string"}, "step_index": {"type": "integer"}, "result": {"type": "string"}},
        ["plan_id", "step_index", "result"],
    ),
    schema(
        "diagnose_blocked_step",
        "Diagnose why a blocked plan step failed and recommend the next fix. This writes the diagnosis back to the step but does not change status.",
        {"plan_id": {"type": "string"}, "step_index": {"type": "integer"}},
        ["plan_id", "step_index"],
    ),
]


STATE_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "remember_memory": remember,
    "read_memory": load_memory,
    "clear_memory": clear_memory,
    "create_task": create_task,
    "list_tasks": list_tasks,
    "update_task": update_task,
    "list_skills": list_skills,
    "read_skill": read_skill,
    "get_recent_tool_events": read_recent_events,
    "request_overwrite_file": request_overwrite_file,
    "approve_pending_action": approve_pending_action,
    "list_pending_approvals": list_pending_approvals,
    "create_plan": create_plan,
    "list_plans": list_plans,
    "update_plan_step": update_plan_step,
    "suggest_next_plan_step": suggest_next_plan_step,
    "execute_plan_step": execute_plan_step,
    "execute_next_plan_step": execute_next_plan_step,
    "resolve_blocked_step": resolve_blocked_step,
    "diagnose_blocked_step": diagnose_blocked_step,
}
