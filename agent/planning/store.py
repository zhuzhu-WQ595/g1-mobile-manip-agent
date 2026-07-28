from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_DIR = Path.cwd() / ".agent_state"
PLANS_FILE = STATE_DIR / "plans.json"
VALID_STEP_STATUS = {"pending", "in_progress", "done", "blocked"}

PLAN_ALIASES = {
    "current",
    "current plan",
    "latest",
    "latest plan",
    "last",
    "last plan",
    "recent",
    "recent plan",
    "当前计划",
    "当前",
    "最新计划",
    "最新",
    "最近计划",
    "最近",
    "刚才的计划",
    "刚才那个计划",
    "上一个计划",
}


def load_plans() -> list[dict[str, Any]]:
    if not PLANS_FILE.exists():
        return []
    return json.loads(PLANS_FILE.read_text(encoding="utf-8", errors="replace") or "[]")


def save_plans(plans: list[dict[str, Any]]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_FILE.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_plan_ref(plan_ref: str) -> str:
    value = plan_ref.strip().strip("<>").lower()
    if value not in PLAN_ALIASES:
        return value

    plans = load_plans()
    if not plans:
        return value

    active = [
        plan
        for plan in plans
        if any(step.get("status") in {"pending", "blocked"} for step in plan.get("steps", []))
    ]
    candidates = active or plans
    _, current = max(
        enumerate(candidates),
        key=lambda item: (_plan_timestamp(item[1]), item[0]),
    )
    return str(current["id"])


def _plan_timestamp(plan: dict[str, Any]) -> int:
    values = [int(plan.get("created_at") or 0)]
    for step in plan.get("steps", []):
        values.append(int(step.get("completed_at") or step.get("blocked_at") or 0))
    return max(values)
