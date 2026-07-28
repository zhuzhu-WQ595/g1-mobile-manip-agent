from __future__ import annotations

import re
from typing import Any

from ..state.task_store import complete_task, create_task, fail_task, get_task_record, start_task
from .actions import create_task_plan, validate_task_plan
from .executor import execute_next_plan_step
from .formatter import format_plan_progress, result_preview
from .step_mapping import describe_step_mapping
from .store import load_plans


def run_task_cycle(title: str, steps: list[str] | str | None = None, detail: str = "", max_steps: int = 10) -> str:
    clean_title = title.strip()
    if not clean_title:
        return "Task title cannot be empty"

    planned_steps = _normalize_steps(steps) or _default_steps(clean_title)
    trace: list[dict[str, str]] = []

    created = create_task(clean_title, detail)
    _add_trace(trace, "create_task", "create task", "ok", created)
    task_id = _extract_id(created, "task")
    if task_id is None:
        return _cycle_report(clean_title, None, None, trace, "failed", created)

    planned = create_task_plan(task_id, planned_steps)
    _add_trace(trace, "create_task_plan", "create linked plan", "ok", planned)
    plan_id = _extract_id(planned, "plan")
    if plan_id is None:
        return _cycle_report(clean_title, task_id, None, trace, "failed", planned)

    validation = validate_task_plan(task_id)
    _add_trace(trace, "validate_task_plan", "validate linked plan", "ok", validation)

    started = start_task(task_id)
    _add_trace(trace, "start_task", "start task", "ok", started)
    if "from pending to in_progress" not in started:
        return _cycle_report(clean_title, task_id, plan_id, trace, "failed", started)

    executed_count = 0
    for _ in range(max_steps):
        plan = _get_plan(plan_id)
        if plan is None:
            failure = fail_task(task_id, f"Linked plan disappeared: {plan_id}")
            _add_trace(trace, "fail_task", "mark task failed", "error", f"Plan not found: {plan_id}\n{failure}")
            return _cycle_report(clean_title, task_id, plan_id, trace, "failed", failure)
        pending = [step for step in plan.get("steps", []) if step.get("status") == "pending"]
        blocked = [step for step in plan.get("steps", []) if step.get("status") == "blocked"]
        if blocked:
            error = str(blocked[0].get("error") or "plan step blocked")
            failure = fail_task(task_id, error)
            _add_trace(trace, "fail_task", "mark task failed", "error", f"{format_plan_progress(plan)}\n{failure}")
            return _cycle_report(clean_title, task_id, plan_id, trace, "failed", failure)
        if not pending:
            break

        step = pending[0]
        output = execute_next_plan_step(plan_id)
        executed_count += 1
        _add_trace(
            trace,
            _step_tool_name(step),
            f"execute step {step.get('index')}: {step.get('content')}",
            _step_status(plan_id, int(step.get("index", 0))),
            output,
        )
        if "Updated status to blocked" in output or "not supported for automatic execution" in output:
            failure = fail_task(task_id, _blocked_reason(plan_id))
            _add_trace(trace, "fail_task", "mark task failed", "error", failure)
            return _cycle_report(clean_title, task_id, plan_id, trace, "failed", failure)
    else:
        failure = fail_task(task_id, f"Task cycle stopped after {max_steps} plan steps")
        _add_trace(trace, "fail_task", "mark task failed", "error", failure)
        return _cycle_report(clean_title, task_id, plan_id, trace, "failed", failure)

    plan = _get_plan(plan_id)
    if plan is None:
        failure = fail_task(task_id, f"Linked plan disappeared: {plan_id}")
        _add_trace(trace, "fail_task", "mark task failed", "error", failure)
        return _cycle_report(clean_title, task_id, plan_id, trace, "failed", failure)

    blocked = [step for step in plan.get("steps", []) if step.get("status") == "blocked"]
    pending = [step for step in plan.get("steps", []) if step.get("status") == "pending"]
    if blocked or pending:
        reason = _blocked_reason(plan_id) if blocked else "plan still has pending steps"
        failure = fail_task(task_id, reason)
        _add_trace(trace, "fail_task", "mark task failed", "error", failure)
        return _cycle_report(clean_title, task_id, plan_id, trace, "failed", failure)

    result = _cycle_result(plan)
    completed = complete_task(task_id, result)
    _add_trace(trace, "complete_task", "complete task", "ok", completed)
    return _cycle_report(clean_title, task_id, plan_id, trace, "done", result)


def _normalize_steps(steps: list[str] | str | None) -> list[str]:
    if steps is None:
        return []
    if isinstance(steps, str):
        raw_steps = re.split(r"[;\n]+", steps)
    else:
        raw_steps = [str(step) for step in steps]
    return [step.strip() for step in raw_steps if step.strip()]


def _default_steps(title: str) -> list[str]:
    lowered = title.lower()
    if any(token in lowered for token in ("test", "pytest")) or any(token in title for token in ("测试", "验证")):
        return ["run pytest", "summarize results"]
    if any(token in lowered for token in ("project", "workspace", "structure")) or any(
        token in title for token in ("项目", "结构", "工作区")
    ):
        return ["workspace summary", "list files in agent", "read README.md", "summarize results"]
    if "readme" in lowered:
        return ["read README.md", "summarize results"]
    return ["workspace summary", "summarize results"]


def _extract_id(text: str, prefix: str) -> str | None:
    match = re.search(rf"\b{prefix}_\d+\b", text)
    if match:
        return match.group(0)
    return None


def _get_plan(plan_id: str) -> dict[str, Any] | None:
    return next((plan for plan in load_plans() if plan.get("id") == plan_id), None)


def _blocked_reason(plan_id: str) -> str:
    plan = _get_plan(plan_id)
    if plan is None:
        return f"Plan not found: {plan_id}"
    blocked = [step for step in plan.get("steps", []) if step.get("status") == "blocked"]
    if not blocked:
        return "plan execution did not finish"
    step = blocked[0]
    return f"Step {step.get('index')} blocked: {step.get('error', 'unknown reason')}"


def _cycle_result(plan: dict[str, Any]) -> str:
    rows = [format_plan_progress(plan)]
    for step in plan.get("steps", []):
        result = str(step.get("result", ""))
        if result:
            rows.append(f"- Step {step.get('index')} {step.get('content')}: {result_preview(result, 200)}")
    return "\n".join(rows)


def _cycle_report(
    title: str,
    task_id: str | None,
    plan_id: str | None,
    trace: list[dict[str, str]],
    final_status: str,
    final_result: str,
) -> str:
    task = get_task_record(task_id) if task_id else None
    plan = _get_plan(plan_id) if plan_id else None
    task_status = str(task.get("status")) if task else final_status

    rows = [
        "Task cycle report",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Title | {title} |",
        f"| Task ID | {task_id or '(not created)'} |",
        f"| Plan ID | {plan_id or '(not created)'} |",
        f"| Task status | {task_status} |",
        f"| Plan progress | {format_plan_progress(plan) if plan else '(no plan)'} |",
        "",
        "Execution trace",
        "",
        "| # | Phase | Tool | Status | Result |",
        "|---:|---|---|---|---|",
    ]
    for index, event in enumerate(trace, start=1):
        rows.append(
            "| "
            f"{index} | "
            f"{_cell(event['phase'])} | "
            f"`{_cell(event['tool'])}` | "
            f"{_cell(event['status'])} | "
            f"{_cell(event['result'])} |"
        )

    if plan:
        rows.extend(["", "Plan steps", "", "| Step | Status | Executor | Result |", "|---:|---|---|---|"])
        for step in plan.get("steps", []):
            rows.append(
                "| "
                f"{step.get('index')} | "
                f"{_cell(str(step.get('status', '')))} | "
                f"{_cell(describe_step_mapping(step))} | "
                f"{_cell(result_preview(str(step.get('result') or step.get('error') or ''), 160))} |"
            )

    rows.extend(["", "Final result", "", final_result])
    return "\n".join(rows)


def _add_trace(trace: list[dict[str, str]], tool: str, phase: str, status: str, result: str) -> None:
    trace.append(
        {
            "tool": tool,
            "phase": phase,
            "status": status,
            "result": _trace_preview(result),
        }
    )


def _step_tool_name(step: dict[str, Any]) -> str:
    executor = step.get("executor") or {}
    if executor.get("mode") == "tool":
        return str(executor.get("tool") or "execute_next_plan_step")
    if executor.get("mode") == "summary":
        return "summary"
    return "manual"


def _step_status(plan_id: str, step_index: int) -> str:
    plan = _get_plan(plan_id)
    if plan is None:
        return "error"
    step = next((item for item in plan.get("steps", []) if int(item.get("index", 0)) == step_index), None)
    if step is None:
        return "error"
    status = str(step.get("status", ""))
    return "ok" if status == "done" else status


def _cell(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split())


def _trace_preview(result: str) -> str:
    marker = "Tool result:\n"
    if marker in result:
        result = result.split(marker, 1)[1]
        result = result.split("\n\nUpdated ", 1)[0]
    return result_preview(result, 160)
