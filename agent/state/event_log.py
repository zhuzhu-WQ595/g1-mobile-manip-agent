from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path.cwd() / ".agent_state"
HOOK_LOG = STATE_DIR / "tool_events.jsonl"


def record_tool_event(event: dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        with HOOK_LOG.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        return


def read_recent_events(limit: int = 20) -> str:
    try:
        event_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer between 1 and 100") from exc
    if event_limit < 1 or event_limit > 100:
        raise ValueError("limit must be between 1 and 100")

    if not HOOK_LOG.exists():
        return "Recent tool events:\n(no tool events)"

    lines = HOOK_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-event_limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append(
                {
                    "time": "(invalid)",
                    "tool": "(invalid)",
                    "status": "failed",
                    "arguments": {},
                    "result": line,
                }
            )

    rows = [
        "Recent tool events:",
        "",
        "| # | Time | Tool | Status | Arguments | Result |",
        "|---|------|------|--------|-----------|--------|",
    ]
    for index, event in enumerate(reversed(events), start=1):
        rows.append(
            "| {index} | {time} | `{tool}` | {status} | `{arguments}` | {result} |".format(
                index=index,
                time=_cell(str(event.get("time", ""))),
                tool=_cell(str(event.get("tool", ""))),
                status=_cell(str(event.get("status", ""))),
                arguments=_cell(json.dumps(event.get("arguments", {}), ensure_ascii=False, sort_keys=True)),
                result=_cell(_result_preview(str(event.get("result", "")))),
            )
        )
    return "\n".join(rows)


def _result_preview(result: str, limit: int = 120) -> str:
    compact = " ".join(result.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
