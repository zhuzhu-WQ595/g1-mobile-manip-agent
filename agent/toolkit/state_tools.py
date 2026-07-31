from __future__ import annotations

from ..planning import (
    create_plan,
    create_task_plan,
    diagnose_blocked_step,
    execute_next_plan_step,
    execute_plan_step,
    get_task_plan,
    list_plans,
    resolve_blocked_step,
    run_task_cycle,
    suggest_next_plan_step,
    update_plan_step,
    validate_task_plan,
)
from ..state.approval_store import (
    approve_pending_action,
    cancel_pending_action,
    get_approval_details,
    list_approval_history,
    list_pending_approvals,
    request_edit_file,
    request_overwrite_file,
)
from ..state.event_log import read_recent_events
from ..state.memory_store import clear_memory, load_memory, remember
from ..state.skill_store import list_skills, read_skill
from ..state.task_store import (
    cancel_task,
    complete_task,
    create_task,
    fail_task,
    get_task_details,
    list_tasks,
    retry_task,
    start_task,
    update_task,
)

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
        "get_task_details",
        "Get the status, timestamps, result, and failure or cancellation details for one task.",
        {"task_id": {"type": "string"}},
        ["task_id"],
    ),
    schema("start_task", "Start a pending task.", {"task_id": {"type": "string"}}, ["task_id"]),
    schema(
        "complete_task",
        "Complete an in-progress task and optionally save its result.",
        {"task_id": {"type": "string"}, "result": {"type": "string"}},
        ["task_id"],
    ),
    schema(
        "fail_task",
        "Mark an in-progress task as failed and save the failure reason.",
        {"task_id": {"type": "string"}, "error": {"type": "string"}},
        ["task_id", "error"],
    ),
    schema("retry_task", "Retry a failed task.", {"task_id": {"type": "string"}}, ["task_id"]),
    schema(
        "cancel_task",
        "Cancel a pending, in-progress, or failed task and optionally save the reason.",
        {"task_id": {"type": "string"}, "reason": {"type": "string"}},
        ["task_id"],
    ),
    schema(
        "update_task",
        "Compatibility entry for a validated task status transition. Prefer the explicit lifecycle tools.",
        {
            "task_id": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "in_progress", "done", "failed", "cancelled"]},
        },
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
        "request_edit_file",
        "Preview an exact text replacement as a diff and create a pending approval. This does not edit the file until the user approves the returned approval ID.",
        {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        ["path", "old_text", "new_text"],
    ),
    schema(
        "approve_pending_action",
        "Approve and execute a previously created pending action by approval ID.",
        {"approval_id": {"type": "string"}},
        ["approval_id"],
    ),
    schema(
        "cancel_pending_action",
        "Cancel a pending action by approval ID without executing it.",
        {"approval_id": {"type": "string"}},
        ["approval_id"],
    ),
    schema("list_pending_approvals", "List pending approvals.", {}, []),
    schema(
        "list_approval_history",
        "List recent approval records, including pending, approved, and cancelled actions.",
        {
            "limit": {
                "type": "integer",
                "description": "Maximum number of recent approval records. Defaults to 10 and must be between 1 and 100.",
            }
        },
        [],
    ),
    schema(
        "get_approval_details",
        "Get status, timestamps, result, and saved change details for one approval ID.",
        {"approval_id": {"type": "string"}},
        ["approval_id"],
    ),
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
    schema(
        "create_task_plan",
        "Create and link an ordered plan for an existing non-terminal task without executing any steps.",
        {
            "task_id": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short ordered steps.",
            },
        },
        ["task_id", "steps"],
    ),
    schema(
        "get_task_plan",
        "Show the linked plan and current step progress for one task.",
        {"task_id": {"type": "string"}},
        ["task_id"],
    ),
    schema(
        "validate_task_plan",
        "Validate the linked plan before execution and show each step's mapped tool, arguments, or manual handling requirement.",
        {"task_id": {"type": "string"}},
        ["task_id"],
    ),
    schema(
        "run_task_cycle",
        "Run a complete task lifecycle for natural-language requests that ask to plan and execute a whole task. It creates a task, creates and validates a linked plan, starts the task, executes all supported plan steps in order, then completes or fails the task.",
        {
            "title": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional ordered plan steps. When omitted, conservative default steps are generated from the title.",
            },
            "detail": {"type": "string"},
            "max_steps": {
                "type": "integer",
                "description": "Maximum number of plan steps to execute. Defaults to 10.",
            },
        },
        ["title"],
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
    "get_task_details": get_task_details,
    "start_task": start_task,
    "complete_task": complete_task,
    "fail_task": fail_task,
    "retry_task": retry_task,
    "cancel_task": cancel_task,
    "update_task": update_task,
    "list_skills": list_skills,
    "read_skill": read_skill,
    "get_recent_tool_events": read_recent_events,
    "request_overwrite_file": request_overwrite_file,
    "request_edit_file": request_edit_file,
    "approve_pending_action": approve_pending_action,
    "cancel_pending_action": cancel_pending_action,
    "list_pending_approvals": list_pending_approvals,
    "list_approval_history": list_approval_history,
    "get_approval_details": get_approval_details,
    "create_plan": create_plan,
    "create_task_plan": create_task_plan,
    "get_task_plan": get_task_plan,
    "validate_task_plan": validate_task_plan,
    "run_task_cycle": run_task_cycle,
    "list_plans": list_plans,
    "update_plan_step": update_plan_step,
    "suggest_next_plan_step": suggest_next_plan_step,
    "execute_plan_step": execute_plan_step,
    "execute_next_plan_step": execute_next_plan_step,
    "resolve_blocked_step": resolve_blocked_step,
    "diagnose_blocked_step": diagnose_blocked_step,
}
