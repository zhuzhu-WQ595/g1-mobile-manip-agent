from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..permissions import split_command

from .schema import ToolHandler, schema


COMMAND_TOOL_SCHEMAS: list[dict[str, object]] = [
    schema("run_command", "Run a command from a strict whitelist.", {"command": {"type": "string"}}, ["command"]),
]


def run_command(command: str) -> str:
    args = list(split_command(command))
    # The whitelist spells the interpreter as "python", but that name is not an
    # executable on every system. Run the interpreter that hosts the agent.
    if args and args[0] == "python":
        args[0] = sys.executable
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
