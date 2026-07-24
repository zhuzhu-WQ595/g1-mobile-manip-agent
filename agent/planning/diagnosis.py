from __future__ import annotations

from typing import Any

from .store import load_plans, save_plans
from .summary import is_summary_step, previous_step_results


def diagnose_blocked_step(plan_id: str, step_index: int) -> str:
    plans = load_plans()
    for plan in plans:
        if plan.get("id") != plan_id:
            continue
        steps = plan.get("steps", [])
        for step in steps:
            if int(step.get("index", 0)) != int(step_index):
                continue
            if step.get("status") != "blocked":
                return f"Step is not blocked: {plan_id} step {step_index}"
            diagnosis = _diagnose_step(plan, step)
            step["diagnosis"] = diagnosis
            save_plans(plans)
            return diagnosis
        return f"Step not found: {plan_id} step {step_index}"
    return f"Plan not found: {plan_id}"


def _diagnose_step(plan: dict[str, Any], step: dict[str, Any]) -> str:
    content = str(step.get("content", ""))
    error = str(step.get("error") or "(no error recorded)")
    previous_results = previous_step_results(plan, int(step.get("index", 0)))
    cause, fix = _diagnosis_for_error(content, error)

    rows = [
        f"Diagnosis for {plan.get('id')} step {step.get('index')}: {content}",
        f"Status: {step.get('status')}",
        f"Error: {error}",
        "",
        "Likely cause:",
        cause,
        "",
        "Available previous results:",
        previous_results or "(no previous completed step results)",
        "",
        "Recommended fix:",
        fix,
        "",
        "Status was not changed.",
    ]
    return "\n".join(rows)


def _diagnosis_for_error(content: str, error: str) -> tuple[str, str]:
    summary_step = is_summary_step(content)
    if "missing previous step results" in error and summary_step:
        return (
            "The step is a summary step, but earlier completed steps do not have saved result fields to summarize.",
            "Re-run the prerequisite steps with execute_plan_step so their results are written back, then execute this summary step again.",
        )
    if "unsupported step type" in error and summary_step:
        return (
            "The plan executor reached a summary step that did not have usable previous results.",
            "Make sure earlier steps are done and have result fields, then execute this summary step again.",
        )
    if "unsupported step type" in error:
        return (
            "The step text does not match any currently supported automatic executor rule.",
            "Add a new executor rule for this step type, or keep it blocked and resolve it with a user-provided result.",
        )
    if "PermissionError" in error or "outside workspace" in error:
        return (
            "The tool request likely violated a workspace or command permission boundary.",
            "Keep the permission check in place, then change the plan step to use a workspace-relative path or an allowed command.",
        )
    if "ValueError" in error:
        return (
            "The tool received invalid arguments or an argument outside its supported range.",
            "Preserve the user's requested arguments, explain the limit, and ask for confirmation before retrying with corrected parameters.",
        )
    return (
        "The step failed, but the recorded error is not specific enough for an automatic fix.",
        "Inspect the step content, error text, and prior results, then add a targeted executor rule or ask the user for missing information.",
    )
