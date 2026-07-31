from __future__ import annotations

import re
from typing import Any

def requested_preview_lines(text: str) -> int | None:
    patterns = [
        r"^(?:show|preview|read)\s+first\s+(\d+)\s+lines?\s+of\s+.+$",
        r"^preview\s+.+?\s+(\d+)\s+lines?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text.strip(), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def requested_plan_execution(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    match = re.match(rf"^execute next step of\s+{PLAN_REF_PATTERN}$", stripped, flags=re.IGNORECASE)
    if not match:
        match = re.match(rf"^执行{PLAN_REF_PATTERN}下一步$", stripped)
    if match:
        return {"tool": "execute_next_plan_step", "plan_id": clean_plan_ref(match.group(1))}

    match = re.match(rf"^execute step\s+(\d+)\s+of\s+{PLAN_REF_PATTERN}$", stripped, flags=re.IGNORECASE)
    if match:
        return {
            "tool": "execute_plan_step",
            "plan_id": clean_plan_ref(match.group(2)),
            "step_index": int(match.group(1)),
        }

    return None


def requested_blocked_resolution(text: str) -> dict[str, Any] | None:
    match = re.match(
        rf"^resolve blocked step\s+(\d+)\s+of\s+{PLAN_REF_PATTERN}\s+::\s*(.+)$",
        text.strip(),
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "tool": "resolve_blocked_step",
        "step_index": int(match.group(1)),
        "plan_id": clean_plan_ref(match.group(2)),
        "result": match.group(3).strip(),
    }


def requested_blocked_diagnosis(text: str) -> dict[str, Any] | None:
    match = re.match(
        rf"^diagnose blocked step\s+(\d+)\s+of\s+{PLAN_REF_PATTERN}$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "tool": "diagnose_blocked_step",
        "step_index": int(match.group(1)),
        "plan_id": clean_plan_ref(match.group(2)),
    }


def requested_exact_tool(text: str) -> dict[str, Any] | None:
    lowered = text.strip().lower()
    if lowered in {"plans", "list plans"}:
        return {"tool": "list_plans", "arguments": {}}
    return None


TASK_REF_PATTERN = (
    r"<?("
    r"task_\d+|"
    r"current(?: task)?|latest(?: task)?|last(?: task)?|recent(?: task)?|"
    r"当前任务|当前|最新任务|最新|最近任务|最近|刚才的任务|刚才那个任务|上一个任务"
    r")>?"
)

PLAN_REF_PATTERN = (
    r"<?("
    r"plan_\d+|"
    r"current(?: plan)?|latest(?: plan)?|last(?: plan)?|recent(?: plan)?|"
    r"当前计划|当前|最新计划|最新|最近计划|最近|刚才的计划|刚才那个计划|上一个计划"
    r")>?"
)


def clean_task_ref(value: str) -> str:
    return value.strip().strip("<>").lower()


def clean_plan_ref(value: str) -> str:
    return value.strip().strip("<>").lower()


def natural_task_cycle_arguments(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    lowered = stripped.lower()
    asks_full_cycle = any(
        token in lowered
        for token in (
            "complete",
            "end-to-end",
            "full cycle",
            "full workflow",
            "run through",
            "plan and execute",
        )
    ) or any(token in stripped for token in ("完整", "全流程", "完整流程", "自动规划并执行", "规划并执行"))
    asks_project_structure = any(
        token in lowered
        for token in ("project structure", "workspace structure", "inspect project", "check project")
    ) or any(token in stripped for token in ("项目结构", "工程结构", "当前项目", "项目"))
    asks_summary = any(token in lowered for token in ("summary", "summarize", "report")) or any(
        token in stripped for token in ("总结", "汇总", "报告")
    )
    if asks_project_structure and (asks_full_cycle or asks_summary):
        return {
            "title": "检查项目结构",
            "steps": ["workspace summary", "list files in agent", "read README.md", "summarize results"],
        }
    return None


def requested_task_action(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    lowered = stripped.lower()
    task_id = TASK_REF_PATTERN

    match = re.match(r"^(?:创建任务|新建任务)\s+(.+?)(?:\s+::\s*(.*))?$", stripped, flags=re.DOTALL)
    if match:
        return {
            "tool": "create_task",
            "arguments": {"title": match.group(1).strip(), "detail": (match.group(2) or "").strip()},
        }

    plan_patterns = [
        (rf"^为(?:任务)?\s*{task_id}\s*创建计划\s*::\s*(.+)$", "create_task_plan"),
        (rf"^验证(?:任务)?\s*{task_id}\s*(?:的)?计划$", "validate_task_plan"),
        (rf"^查看(?:任务)?\s*{task_id}\s*(?:的)?计划$", "get_task_plan"),
    ]
    for pattern, tool in plan_patterns:
        match = re.match(pattern, stripped, flags=re.DOTALL)
        if not match:
            continue
        arguments: dict[str, Any] = {"task_id": clean_task_ref(match.group(1))}
        if tool == "create_task_plan":
            arguments["steps"] = [step.strip() for step in match.group(2).split(";") if step.strip()]
        return {"tool": tool, "arguments": arguments}

    lifecycle_patterns = [
        (rf"^查看(?:任务)?\s*{task_id}\s*(?:的)?详情$", "get_task_details", None),
        (rf"^开始(?:任务)?\s*{task_id}$", "start_task", None),
        (rf"^重试(?:任务)?\s*{task_id}$", "retry_task", None),
        (rf"^完成(?:任务)?\s*{task_id}(?:\s+::\s*(.*))?$", "complete_task", "result"),
        (rf"^标记(?:任务)?\s*{task_id}\s*失败\s*::\s*(.+)$", "fail_task", "error"),
        (rf"^取消(?:任务)?\s*{task_id}(?:\s+::\s*(.*))?$", "cancel_task", "reason"),
    ]
    for pattern, tool, field in lifecycle_patterns:
        match = re.match(pattern, stripped, flags=re.DOTALL)
        if not match:
            continue
        arguments = {"task_id": clean_task_ref(match.group(1))}
        if field:
            arguments[field] = (match.group(2) or "").strip()
        return {"tool": tool, "arguments": arguments}

    if stripped in {"任务", "任务列表", "列出任务"}:
        return {"tool": "list_tasks", "arguments": {}}

    match = re.match(
        rf"^create task plan\s+{task_id}\s+::\s*(.+)$",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        match = re.match(rf"^为任务\s*{task_id}\s*创建计划\s*::\s*(.+)$", stripped, flags=re.DOTALL)
    if match:
        steps = [step.strip() for step in match.group(2).split(";") if step.strip()]
        return {
            "tool": "create_task_plan",
            "arguments": {"task_id": clean_task_ref(match.group(1)), "steps": steps},
        }

    match = re.match(rf"^validate task plan\s+{task_id}$", stripped, flags=re.IGNORECASE)
    if match:
        return {"tool": "validate_task_plan", "arguments": {"task_id": clean_task_ref(match.group(1))}}

    match = re.match(rf"^(?:task plan|show task plan)\s+{task_id}$", stripped, flags=re.IGNORECASE)
    if not match:
        match = re.match(rf"^查看(?:任务)?\s*{task_id}\s*(?:的)?计划$", stripped)
    if match:
        return {"tool": "get_task_plan", "arguments": {"task_id": clean_task_ref(match.group(1))}}

    match = re.match(r"^create task\s+(.+?)(?:\s+::\s*(.*))?$", stripped, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return {
            "tool": "create_task",
            "arguments": {"title": match.group(1).strip(), "detail": (match.group(2) or "").strip()},
        }

    match = re.match(r"^(?:创建任务|新建任务)\s+(.+?)(?:\s+::\s*(.*))?$", stripped, flags=re.DOTALL)
    if match:
        return {
            "tool": "create_task",
            "arguments": {"title": match.group(1).strip(), "detail": (match.group(2) or "").strip()},
        }

    if lowered in {"tasks", "list tasks"} or stripped in {"任务", "任务列表", "列出任务"}:
        return {"tool": "list_tasks", "arguments": {}}

    patterns = [
        (rf"^(?:task details|show task|task)\s+{task_id}$", "get_task_details", None, re.IGNORECASE),
        (rf"^查看(?:任务)?\s*{task_id}\s*(?:的)?详情$", "get_task_details", None, 0),
        (rf"^start(?: task)?\s+{task_id}$", "start_task", None, re.IGNORECASE),
        (rf"^开始(?:任务)?\s*{task_id}$", "start_task", None, 0),
        (rf"^retry(?: task)?\s+{task_id}$", "retry_task", None, re.IGNORECASE),
        (rf"^重试(?:任务)?\s*{task_id}$", "retry_task", None, 0),
    ]
    for pattern, tool, _, flags in patterns:
        match = re.match(pattern, stripped, flags=flags)
        if match:
            return {"tool": tool, "arguments": {"task_id": clean_task_ref(match.group(1))}}

    match = re.match(
        rf"^complete(?: task)?\s+{task_id}(?:\s+::\s*(.*))?$",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        match = re.match(rf"^完成(?:任务)?\s*{task_id}(?:\s+::\s*(.*))?$", stripped, flags=re.DOTALL)
    if match:
        return {
            "tool": "complete_task",
            "arguments": {"task_id": clean_task_ref(match.group(1)), "result": (match.group(2) or "").strip()},
        }

    match = re.match(
        rf"^fail(?: task)?\s+{task_id}\s+::\s*(.+)$",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        match = re.match(rf"^标记(?:任务)?\s*{task_id}\s*失败\s*::\s*(.+)$", stripped, flags=re.DOTALL)
    if match:
        return {
            "tool": "fail_task",
            "arguments": {"task_id": clean_task_ref(match.group(1)), "error": match.group(2).strip()},
        }

    match = re.match(
        rf"^cancel(?: task)?\s+{task_id}(?:\s+::\s*(.*))?$",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        match = re.match(rf"^取消(?:任务)?\s*{task_id}(?:\s+::\s*(.*))?$", stripped, flags=re.DOTALL)
    if match:
        return {
            "tool": "cancel_task",
            "arguments": {"task_id": clean_task_ref(match.group(1)), "reason": (match.group(2) or "").strip()},
        }

    return None


def forced_plan_tool_calls(text: str) -> list[dict[str, Any]] | None:
    requested_task = requested_task_action(text)
    if requested_task is not None:
        return [
            {
                "id": "forced_task_call_1",
                "name": requested_task["tool"],
                "arguments": requested_task["arguments"],
            }
        ]

    exact_tool = requested_exact_tool(text)
    if exact_tool is not None:
        return [
            {
                "id": "forced_exact_call_1",
                "name": exact_tool["tool"],
                "arguments": exact_tool["arguments"],
            }
        ]

    requested_plan = requested_plan_execution(text)
    requested_diagnosis = requested_blocked_diagnosis(text)
    if requested_diagnosis is not None:
        return [
            {
                "id": "forced_diagnosis_call_1",
                "name": requested_diagnosis["tool"],
                "arguments": {
                    "plan_id": requested_diagnosis["plan_id"],
                    "step_index": requested_diagnosis["step_index"],
                },
            }
        ]

    requested_resolution = requested_blocked_resolution(text)
    if requested_resolution is not None:
        return [
            {
                "id": "forced_resolution_call_1",
                "name": requested_resolution["tool"],
                "arguments": {
                    "plan_id": requested_resolution["plan_id"],
                    "step_index": requested_resolution["step_index"],
                    "result": requested_resolution["result"],
                },
            }
        ]

    if requested_plan is None:
        return None

    if requested_plan["tool"] == "execute_next_plan_step":
        arguments = {"plan_id": requested_plan["plan_id"]}
    else:
        arguments = {
            "plan_id": requested_plan["plan_id"],
            "step_index": requested_plan["step_index"],
        }

    return [
        {
            "id": "forced_plan_call_1",
            "name": requested_plan["tool"],
            "arguments": arguments,
        }
    ]


def check_user_requested_arguments(name: str, arguments: dict[str, Any], user_text: str) -> None:
    requested_task = requested_task_action(user_text)
    if requested_task is not None:
        if name != requested_task["tool"]:
            raise PermissionError(f"This request must use {requested_task['tool']} only.")
        if arguments != requested_task["arguments"]:
            raise PermissionError("Tool call changed the requested task arguments")
        return

    exact_tool = requested_exact_tool(user_text)
    if exact_tool is not None:
        if name != exact_tool["tool"]:
            raise PermissionError(f"This request must use {exact_tool['tool']} only.")
        return

    requested_plan = requested_plan_execution(user_text)
    requested_diagnosis = requested_blocked_diagnosis(user_text)
    if requested_diagnosis is not None:
        if name != requested_diagnosis["tool"]:
            raise PermissionError("This request must use diagnose_blocked_step.")
        if str(arguments.get("plan_id")) != requested_diagnosis["plan_id"]:
            raise PermissionError("Tool call changed the requested plan_id")
        if int(arguments.get("step_index", 0)) != requested_diagnosis["step_index"]:
            raise PermissionError("Tool call changed the requested step_index")
        return

    requested_resolution = requested_blocked_resolution(user_text)
    if requested_resolution is not None:
        if name != requested_resolution["tool"]:
            raise PermissionError("This request must use resolve_blocked_step.")
        if str(arguments.get("plan_id")) != requested_resolution["plan_id"]:
            raise PermissionError("Tool call changed the requested plan_id")
        if int(arguments.get("step_index", 0)) != requested_resolution["step_index"]:
            raise PermissionError("Tool call changed the requested step_index")
        if str(arguments.get("result", "")).strip() != requested_resolution["result"]:
            raise PermissionError("Tool call changed the user-provided result")
        return

    if requested_plan is not None:
        expected_tool = requested_plan["tool"]
        if name != expected_tool:
            raise PermissionError(
                f"This request must use {expected_tool}. "
                "Do not switch to another tool while executing a plan step."
            )
        if str(arguments.get("plan_id")) != requested_plan["plan_id"]:
            raise PermissionError("Tool call changed the requested plan_id")
        if expected_tool == "execute_plan_step" and int(arguments.get("step_index", 0)) != requested_plan["step_index"]:
            raise PermissionError("Tool call changed the requested step_index")
        return

    requested_lines = requested_preview_lines(user_text)
    if requested_lines is None:
        return

    if name != "preview_file_head":
        raise PermissionError(
            "First-N-lines requests must use preview_file_head. "
            "Do not switch to another tool after preview_file_head fails."
        )

    try:
        actual_lines = int(arguments.get("lines"))
    except (TypeError, ValueError) as exc:
        raise PermissionError("preview_file_head lines must match the user's requested line count") from exc

    if actual_lines != requested_lines:
        raise PermissionError(
            "Tool call changed the requested line count "
            f"from {requested_lines} to {actual_lines}. "
            "Do not retry with modified parameters unless the user confirms them."
        )


def should_stop_after_tool_error(name: str, result: str, user_text: str) -> bool:
    if requested_task_action(user_text) is not None:
        return True
    if requested_exact_tool(user_text) is not None:
        return True
    if requested_blocked_diagnosis(user_text) is not None:
        return True
    if requested_blocked_resolution(user_text) is not None:
        return True
    if requested_plan_execution(user_text) is not None:
        return True
    if requested_preview_lines(user_text) is None:
        return False
    if name != "preview_file_head":
        return True
    return "lines must be between 1 and 50" in result or "lines must be an integer" in result


def final_tool_error_message(result: str) -> str:
    return (
        f"{result}\n\n"
        "I will not retry with changed parameters or a different tool unless you confirm the new request."
    )


def should_stop_after_tool_success(name: str, user_text: str) -> bool:
    if name in {"get_recent_tool_events", "run_task_cycle"}:
        return True
    exact_tool = requested_exact_tool(user_text)
    if exact_tool is not None:
        return name == exact_tool["tool"]
    requested_diagnosis = requested_blocked_diagnosis(user_text)
    if requested_diagnosis is not None:
        return name == requested_diagnosis["tool"]
    requested_resolution = requested_blocked_resolution(user_text)
    if requested_resolution is not None:
        return name == requested_resolution["tool"]
    requested_plan = requested_plan_execution(user_text)
    return requested_plan is not None and name == requested_plan["tool"]
