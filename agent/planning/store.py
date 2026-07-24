from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_DIR = Path.cwd() / ".agent_state"
PLANS_FILE = STATE_DIR / "plans.json"
VALID_STEP_STATUS = {"pending", "in_progress", "done", "blocked"}


def load_plans() -> list[dict[str, Any]]:
    if not PLANS_FILE.exists():
        return []
    return json.loads(PLANS_FILE.read_text(encoding="utf-8", errors="replace") or "[]")


def save_plans(plans: list[dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_FILE.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
