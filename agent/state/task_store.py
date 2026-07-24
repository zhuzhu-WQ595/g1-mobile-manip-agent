from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATE_DIR = Path.cwd() / ".agent_state"
TASKS_FILE = STATE_DIR / "tasks.json"
VALID_STATUS = {"pending", "in_progress", "done"}


def _load() -> list[dict[str, Any]]:
    if not TASKS_FILE.exists():
        return []
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def _save(tasks: list[dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def create_task(title: str, detail: str = "") -> str:
    tasks = _load()
    task = {
        "id": f"task_{int(time.time() * 1000)}",
        "title": title.strip(),
        "detail": detail.strip(),
        "status": "pending",
        "created_at": int(time.time()),
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
    tasks = _load()
    for task in tasks:
        if task["id"] == task_id:
            task["status"] = status
            _save(tasks)
            return f"Updated {task_id} to {status}"
    return f"Task not found: {task_id}"


def task_summary(limit: int = 10) -> str:
    tasks = _load()[-limit:]
    if not tasks:
        return ""
    return "\n".join(f"- {task['id']} [{task['status']}] {task['title']}" for task in tasks)
