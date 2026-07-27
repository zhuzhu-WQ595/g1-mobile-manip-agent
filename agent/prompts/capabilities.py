from __future__ import annotations

CAPABILITIES = [
    "Answer conceptual and architecture questions directly.",
    "Plan robot tasks and issue high-level robot commands through tools.",
    "Read robot status, move, rotate, stop, set wheel speed, speak, capture a frame, and execute short checked plans.",
    "Read, write, append, edit, create folders, and search files inside the workspace.",
    "Get workspace summary statistics with get_workspace_summary.",
    "Count files by extension with count_files_by_extension.",
    "Preview the first lines of a file with preview_file_head.",
    "Save experiment notes with save_experiment_note.",
    "Request approval before overwriting files with request_overwrite_file, then execute with approve_pending_action only after the user approves.",
    "Preview exact file edits with request_edit_file, then execute with approve_pending_action only after the user approves.",
    "Cancel pending approvals with cancel_pending_action without executing them.",
    "List approval history and inspect one approval with list_approval_history and get_approval_details.",
    "Create, inspect, suggest, execute one supported step, execute the next pending step, diagnose blocked steps, resolve blocked steps, and update multi-step plans with create_plan, list_plans, suggest_next_plan_step, execute_plan_step, execute_next_plan_step, diagnose_blocked_step, resolve_blocked_step, and update_plan_step.",
    "Link one ordered plan to a task with create_task_plan and inspect its progress with get_task_plan.",
    "Validate structured task-plan step mappings before execution with validate_task_plan.",
    "Save and read simple long-term memory.",
    "Create, inspect, start, complete, fail, retry, and cancel local tasks with validated lifecycle transitions.",
    "Read built-in skill notes.",
    "Read recent tool event logs with get_recent_tool_events.",
    "Run only a strict whitelist of safe commands.",
]
