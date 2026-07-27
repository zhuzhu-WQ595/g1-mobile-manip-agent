from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATE_DIR = Path.cwd() / ".agent_state"
TASKS_FILE = STATE_DIR / "tasks.json"
VALID_STATUS = {"pending", "in_progress", "done", "failed", "cancelled"}
VALID_TRANSITIONS = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"done", "failed", "cancelled"},
    "failed": {"in_progress", "cancelled"},
    "done": set(),
    "cancelled": set(),
}


def _load() -> list[dict[str, Any]]:
    if not TASKS_FILE.exists():
        return []
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def _save(tasks: list[dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_task_id(tasks: list[dict[str, Any]]) -> str:
    value = int(time.time() * 1000)
    existing_ids = {str(task.get("id", "")) for task in tasks}
    while f"task_{value}" in existing_ids:
        value += 1
    return f"task_{value}"


def _find_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    return next((task for task in tasks if task.get("id") == task_id), None)


def create_task(title: str, detail: str = "") -> str:
    title = title.strip()
    if not title:
        return "Task title cannot be empty"

    tasks = _load()
    now = int(time.time())
    task = {
        "id": _next_task_id(tasks),
        "title": title,
        "detail": detail.strip(),
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    tasks.append(task)
    _save(tasks)
    return f"Created {task['id']}: {task['title']}"


def list_tasks() -> str:
    tasks = _load()
    if not tasks:
        return "(no tasks)"
    return "\n".join(f"{task['id']} [{task['status']}] {task['title']}" for task in tasks)


def update_task(task_id: str, status: str) -> str:
    if status not in VALID_STATUS:
        return f"Invalid status: {status}. Use one of: {', '.join(sorted(VALID_STATUS))}"
    return _transition_task(task_id, status)


def start_task(task_id: str) -> str:
    return _transition_task(task_id, "in_progress")


def complete_task(task_id: str, result: str = "") -> str:
    return _transition_task(task_id, "done", result=result.strip())


def fail_task(task_id: str, error: str) -> str:
    error = error.strip()
    if not error:
        return "Task failure reason cannot be empty"
    return _transition_task(task_id, "failed", error=error)


def retry_task(task_id: str) -> str:
    return _transition_task(task_id, "in_progress")


def cancel_task(task_id: str, reason: str = "") -> str:
    return _transition_task(task_id, "cancelled", reason=reason.strip())


def _transition_task(task_id: str, status: str, **fields: str) -> str:
    tasks = _load()
    task = _find_task(tasks, task_id)
    if task is None:
        return f"Task not found: {task_id}"

    current = str(task.get("status", "pending"))
    if status == current:
        return f"Task {task_id} is already {status}"
    if status not in VALID_TRANSITIONS.get(current, set()):
        return f"Cannot move {task_id} from {current} to {status}"
    if status == "failed" and not fields.get("error"):
        return "Task failure reason cannot be empty"

    now = int(time.time())
    task["status"] = status
    task["updated_at"] = now

    if status == "in_progress":
        if current == "failed":
            task["retried_at"] = now
            if task.get("error"):
                task["last_error"] = task.pop("error")
            task.pop("failed_at", None)
        else:
            task["started_at"] = now
    elif status == "done":
        task["completed_at"] = now
        if fields.get("result"):
            task["result"] = fields["result"]
    elif status == "failed":
        task["failed_at"] = now
        task["error"] = fields["error"]
    elif status == "cancelled":
        task["cancelled_at"] = now
        if fields.get("reason"):
            task["cancel_reason"] = fields["reason"]

    _save(tasks)
    return f"Updated {task_id} from {current} to {status}"


def get_task_details(task_id: str) -> str:
    task = _find_task(_load(), task_id)
    if task is None:
        return f"Task not found: {task_id}"

    labels = [
        ("ID", "id"),
        ("Title", "title"),
        ("Detail", "detail"),
        ("Status", "status"),
        ("Created", "created_at"),
        ("Updated", "updated_at"),
        ("Started", "started_at"),
        ("Retried", "retried_at"),
        ("Completed", "completed_at"),
        ("Failed", "failed_at"),
        ("Cancelled", "cancelled_at"),
        ("Result", "result"),
        ("Error", "error"),
        ("Last error", "last_error"),
        ("Cancel reason", "cancel_reason"),
    ]
    return "\n".join(f"{label}: {task[key]}" for label, key in labels if task.get(key) not in {None, ""})


def task_summary(limit: int = 10) -> str:
    tasks = _load()[-limit:]
    if not tasks:
        return ""
    return "\n".join(f"- {task['id']} [{task['status']}] {task['title']}" for task in tasks)
