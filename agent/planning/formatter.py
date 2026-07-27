from __future__ import annotations

from typing import Any

from .step_mapping import describe_step_mapping


def format_plan(plan: dict[str, Any]) -> str:
    rows = [f"{plan['id']}: {plan['title']}"]
    if plan.get("task_id"):
        rows.append(f"  linked task: {plan['task_id']}")
    for step in plan.get("steps", []):
        rows.append(f"  {step['index']}. [{step['status']}] {step['content']}")
        rows.append(f"     executor: {describe_step_mapping(step)}")
        if step.get("result"):
            rows.append(f"     result: {result_preview(str(step['result']))}")
        if step.get("error"):
            rows.append(f"     error: {step['error']}")
        if step.get("diagnosis"):
            rows.append(f"     diagnosis: {result_preview(str(step['diagnosis']))}")
    return "\n".join(rows)


def format_plan_progress(plan: dict[str, Any]) -> str:
    steps = plan.get("steps", [])
    total = len(steps)
    done = sum(step.get("status") == "done" for step in steps)
    blocked = sum(step.get("status") == "blocked" for step in steps)
    return f"Progress: {done}/{total} done, {blocked} blocked"


def result_preview(result: str, limit: int = 120) -> str:
    compact = " ".join(result.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
