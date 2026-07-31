from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_goal_report(result: dict[str, Any], output: str | None = None) -> Path:
    path = Path(output) if output else Path.cwd() / ".agent_state" / "goal_runs" / f"{result['run_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
