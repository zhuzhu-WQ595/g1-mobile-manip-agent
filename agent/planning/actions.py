from __future__ import annotations

import time

from .formatter import format_plan
from .store import VALID_STEP_STATUS, load_plans, save_plans


def create_plan(title: str, steps: list[str] | str) -> str:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("title is required")
    if isinstance(steps, str):
        raw_steps = [step.strip() for step in steps.split(";")]
    else:
        raw_steps = [str(step).strip() for step in steps]
    clean_steps = [step for step in raw_steps if step]
    if not clean_steps:
        raise ValueError("at least one step is required")

    plans = load_plans()
    plan = {
        "id": f"plan_{int(time.time() * 1000)}",
        "title": clean_title,
        "steps": [
            {"index": index, "content": step, "status": "pending"}
            for index, step in enumerate(clean_steps, start=1)
        ],
        "created_at": int(time.time()),
    }
    plans.append(plan)
    save_plans(plans)
    return format_plan(plan)


def list_plans() -> str:
    plans = load_plans()
    if not plans:
        return "(no plans)"
    return "\n\n".join(format_plan(plan) for plan in plans)


def update_plan_step(plan_id: str, step_index: int, status: str) -> str:
    if status not in VALID_STEP_STATUS:
        return f"Invalid status: {status}. Use one of: {', '.join(sorted(VALID_STEP_STATUS))}"
    plans = load_plans()
    for plan in plans:
        if plan.get("id") != plan_id:
            continue
        for step in plan.get("steps", []):
            if int(step.get("index", 0)) == int(step_index):
                step["status"] = status
                if status != "done":
                    step.pop("result", None)
                    step.pop("completed_at", None)
                if status != "blocked":
                    step.pop("error", None)
                    step.pop("blocked_at", None)
                    step.pop("diagnosis", None)
                save_plans(plans)
                return format_plan(plan)
        return f"Step not found: {plan_id} step {step_index}"
    return f"Plan not found: {plan_id}"


def resolve_blocked_step(plan_id: str, step_index: int, result: str) -> str:
    clean_result = result.strip()
    if not clean_result:
        raise ValueError("result is required")

    plans = load_plans()
    for plan in plans:
        if plan.get("id") != plan_id:
            continue
        for step in plan.get("steps", []):
            if int(step.get("index", 0)) != int(step_index):
                continue
            if step.get("status") != "blocked":
                return f"Step is not blocked: {plan_id} step {step_index}"
            step["status"] = "done"
            step["result"] = clean_result
            step["completed_at"] = int(time.time())
            step.pop("error", None)
            step.pop("blocked_at", None)
            step.pop("diagnosis", None)
            save_plans(plans)
            return format_plan(plan)
        return f"Step not found: {plan_id} step {step_index}"
    return f"Plan not found: {plan_id}"
