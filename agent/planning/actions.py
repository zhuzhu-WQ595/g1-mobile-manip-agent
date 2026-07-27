from __future__ import annotations

import time

from ..state.task_store import attach_plan_to_task, get_task_record, resolve_task_ref
from .formatter import format_plan, format_plan_progress
from .step_mapping import describe_step_mapping, map_plan_step
from .store import VALID_STEP_STATUS, load_plans, save_plans


def create_plan(title: str, steps: list[str] | str) -> str:
    plan = _build_plan(title, steps)
    plans = load_plans()
    plans.append(plan)
    save_plans(plans)
    return format_plan(plan)


def create_task_plan(task_id: str, steps: list[str] | str) -> str:
    task_id = resolve_task_ref(task_id)
    task = get_task_record(task_id)
    if task is None:
        return f"Task not found: {task_id}"
    if task.get("status") in {"done", "cancelled"}:
        return f"Cannot create a plan for {task_id} while it is {task.get('status')}"
    if task.get("plan_id"):
        return f"Task {task_id} is already linked to {task['plan_id']}"

    plan = _build_plan(str(task.get("title", task_id)), steps, task_id=task_id)
    plans = load_plans()
    plans.append(plan)
    save_plans(plans)
    linked = attach_plan_to_task(task_id, str(plan["id"]))
    return "\n".join([format_plan(plan), format_plan_progress(plan), linked])


def get_task_plan(task_id: str) -> str:
    task_id = resolve_task_ref(task_id)
    task = get_task_record(task_id)
    if task is None:
        return f"Task not found: {task_id}"
    plan_id = task.get("plan_id")
    if not plan_id:
        return f"Task {task_id} has no linked plan"
    plan = next((item for item in load_plans() if item.get("id") == plan_id), None)
    if plan is None:
        return f"Linked plan not found: {plan_id}"
    return "\n".join([format_plan(plan), format_plan_progress(plan)])


def validate_task_plan(task_id: str) -> str:
    task_id = resolve_task_ref(task_id)
    task = get_task_record(task_id)
    if task is None:
        return f"Task not found: {task_id}"
    plan_id = task.get("plan_id")
    if not plan_id:
        return f"Task {task_id} has no linked plan"
    plan = next((item for item in load_plans() if item.get("id") == plan_id), None)
    if plan is None:
        return f"Linked plan not found: {plan_id}"

    steps = plan.get("steps", [])
    automatic = sum(
        (step.get("executor") or map_plan_step(str(step.get("content", "")))).get("mode") != "manual"
        for step in steps
    )
    rows = [
        f"Plan validation: {plan_id}",
        f"Linked task: {task_id}",
        f"Automatic steps: {automatic}/{len(steps)}",
    ]
    rows.extend(
        f"{step.get('index')}. {describe_step_mapping(step)}"
        for step in steps
    )
    return "\n".join(rows)


def _build_plan(title: str, steps: list[str] | str, task_id: str | None = None) -> dict[str, object]:
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

    plan = {
        "id": f"plan_{int(time.time() * 1000)}",
        "title": clean_title,
        "steps": [
            {
                "index": index,
                "content": step,
                "status": "pending",
                "executor": map_plan_step(step),
            }
            for index, step in enumerate(clean_steps, start=1)
        ],
        "created_at": int(time.time()),
    }
    if task_id:
        plan["task_id"] = task_id
    return plan


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
