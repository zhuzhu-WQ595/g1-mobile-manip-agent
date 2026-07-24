from __future__ import annotations

from typing import Any


def format_plan(plan: dict[str, Any]) -> str:
    rows = [f"{plan['id']}: {plan['title']}"]
    for step in plan.get("steps", []):
        rows.append(f"  {step['index']}. [{step['status']}] {step['content']}")
        if step.get("result"):
            rows.append(f"     result: {result_preview(str(step['result']))}")
        if step.get("error"):
            rows.append(f"     error: {step['error']}")
        if step.get("diagnosis"):
            rows.append(f"     diagnosis: {result_preview(str(step['diagnosis']))}")
    return "\n".join(rows)


def result_preview(result: str, limit: int = 120) -> str:
    compact = " ".join(result.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
