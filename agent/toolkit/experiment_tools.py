from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..permissions import resolve_workspace_path

from .schema import ToolHandler, schema


EXPERIMENT_TOOL_SCHEMAS: list[dict[str, object]] = [
    schema(
        "save_experiment_note",
        "Append an experiment note to notes/experiment_log.md. Use this when the user asks to save, record, or log an experiment result.",
        {"note": {"type": "string", "description": "Experiment note text to append."}},
        ["note"],
    ),
]


def save_experiment_note(note: str) -> str:
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("note is required")

    log_path = resolve_workspace_path("notes/experiment_log.md")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    entry = f"## {timestamp}\n{clean_note}\n\n"
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write(entry)
    return f"Saved experiment note to {log_path.relative_to(Path.cwd())}"


EXPERIMENT_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "save_experiment_note": save_experiment_note,
}
