from __future__ import annotations

from typing import Any

from .formatter import result_preview


def previous_step_results(plan: dict[str, Any], step_index: int) -> str:
    rows = []
    for item in plan.get("steps", []):
        if int(item.get("index", 0)) >= step_index:
            continue
        if item.get("status") != "done" or not item.get("result"):
            continue
        rows.append(f"- Step {item.get('index')} {item.get('content')}: {result_preview(str(item.get('result')), 200)}")
    return "\n".join(rows)


def summarize_previous_results(plan: dict[str, Any], step_index: int) -> str | None:
    rows = []
    for item in plan.get("steps", []):
        if int(item.get("index", 0)) >= step_index:
            continue
        if item.get("status") != "done" or not item.get("result"):
            continue
        rows.append(f"- Step {item.get('index')} {item.get('content')}: {result_preview(str(item.get('result')), 240)}")
    if not rows:
        return None
    return "\n".join(["Summary from previous completed steps:", *rows])


def is_summary_step(content: str) -> bool:
    lowered = content.lower()
    return any(token in lowered for token in ("summary", "summarize")) or any(
        token in content for token in ("\u6c47\u603b", "\u603b\u7ed3")
    )
