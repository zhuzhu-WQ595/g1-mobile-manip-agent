from __future__ import annotations

import subprocess
from pathlib import Path

from ..permissions import split_command

from .schema import ToolHandler, schema


COMMAND_TOOL_SCHEMAS: list[dict[str, object]] = [
    schema("run_command", "Run a command from a strict whitelist.", {"command": {"type": "string"}}, ["command"]),
]


def run_command(command: str) -> str:
    args = list(split_command(command))
    completed = subprocess.run(
        args,
        cwd=Path.cwd(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
    )
    output = completed.stdout.strip()
    error = completed.stderr.strip()
    result = output if output else "(no stdout)"
    if error:
        result += f"\nstderr:\n{error}"
    return f"exit_code={completed.returncode}\n{result}"


COMMAND_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "run_command": run_command,
}
