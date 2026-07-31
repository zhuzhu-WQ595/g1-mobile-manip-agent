from __future__ import annotations

from pathlib import Path
from typing import Any

from .prompts import SYSTEM_PROMPT
from .state.memory_store import load_memory
from .state.skill_store import list_skills
from .state.task_store import task_summary


def workspace_summary(max_items: int = 20) -> str:
    root = Path.cwd()
    rows: list[str] = []
    for item in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name in {".venv", "__pycache__"}:
            continue
        kind = "dir" if item.is_dir() else "file"
        rows.append(f"- {kind}: {item.name}")
        if len(rows) >= max_items:
            break
    return "\n".join(rows)


def build_system_prompt(messages: list[dict[str, Any]]) -> str:
    sections = [SYSTEM_PROMPT.strip()]

    memory = load_memory()
    if memory:
        sections.append("Long-term memory:\n" + memory)

    tasks = task_summary()
    if tasks:
        sections.append("Current tasks:\n" + tasks)

    sections.append("Available skills:\n" + list_skills())
    sections.append("Workspace summary:\n" + workspace_summary())

    return "\n\n".join(sections)
