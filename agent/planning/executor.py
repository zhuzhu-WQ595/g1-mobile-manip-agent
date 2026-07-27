from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..permissions import resolve_workspace_path
from ..state.task_store import get_task_record
from .formatter import format_plan, format_plan_progress
from .store import load_plans, save_plans
from .summary import is_summary_step, previous_step_results, summarize_previous_results


def suggest_next_plan_step(plan_id: str) -> str:
    plans = load_plans()
    for plan in plans:
        if plan.get("id") != plan_id:
            continue
        for step in plan.get("steps", []):
            if step.get("status") == "pending":
                content = str(step.get("content", ""))
                return "\n".join(
                    [
                        f"Plan: {plan_id} - {plan.get('title')}",
                        f"Next step: {step.get('index')}. {content}",
                        f"Suggested action: {_suggest_action(content)}",
                        "Status was not changed.",
                    ]
                )
        return f"Plan {plan_id} has no pending steps"
    return f"Plan not found: {plan_id}"


def execute_plan_step(plan_id: str, step_index: int) -> str:
    plans = load_plans()
    for plan in plans:
        if plan.get("id") != plan_id:
            continue
        for step in plan.get("steps", []):
            if int(step.get("index", 0)) != int(step_index):
                continue
            if step.get("status") == "done":
                return f"Step already done: {plan_id} step {step_index}"
            linked_error = _linked_execution_error(plan, int(step_index))
            if linked_error:
                return linked_error
            content = str(step.get("content", ""))
            result = _execute_supported_step(content, plan, int(step_index))
            if result is None:
                step["status"] = "blocked"
                step["error"] = _blocked_error_for_step(content, plan, int(step_index))
                step["blocked_at"] = int(time.time())
                save_plans(plans)
                return (
                    f"Step is not supported for automatic execution yet: {content}\n"
                    "Updated status to blocked.\n"
                    f"{format_plan_progress(plan)}"
                )
            step["status"] = "done"
            step["result"] = result
            step["completed_at"] = int(time.time())
            step.pop("error", None)
            step.pop("blocked_at", None)
            step.pop("diagnosis", None)
            save_plans(plans)
            rows = [
                    f"Executed step {step_index}: {content}",
                    "Tool result:",
                    result,
                    "",
                    f"Updated {plan_id} step {step_index} to done.",
                    format_plan_progress(plan),
                ]
            if plan.get("task_id") and all(item.get("status") == "done" for item in plan.get("steps", [])):
                rows.append(f"All plan steps are done. Complete linked task {plan['task_id']} explicitly.")
            return "\n".join(rows)
        return f"Step not found: {plan_id} step {step_index}"
    return f"Plan not found: {plan_id}"


def execute_next_plan_step(plan_id: str) -> str:
    plans = load_plans()
    for plan in plans:
        if plan.get("id") != plan_id:
            continue
        for step in plan.get("steps", []):
            if step.get("status") == "pending":
                return execute_plan_step(plan_id, int(step.get("index", 0)))
        return f"Plan {plan_id} has no pending steps"
    return f"Plan not found: {plan_id}"


def _linked_execution_error(plan: dict[str, Any], step_index: int) -> str | None:
    task_id = plan.get("task_id")
    if not task_id:
        return None
    task = get_task_record(str(task_id))
    if task is None:
        return f"Linked task not found: {task_id}"
    if task.get("status") != "in_progress":
        return f"Linked task {task_id} is {task.get('status')}; start or retry it before executing plan steps"
    unfinished_previous = [
        step
        for step in plan.get("steps", [])
        if int(step.get("index", 0)) < step_index and step.get("status") != "done"
    ]
    if unfinished_previous:
        first = unfinished_previous[0]
        return f"Cannot execute step {step_index} before step {first.get('index')} is done"
    return None


def _execute_supported_step(content: str, plan: dict[str, Any] | None = None, step_index: int = 0) -> str | None:
    lowered = content.lower()
    if "readme" in lowered and "读取" in content:
        path = resolve_workspace_path("README.md")
        if not path.is_file():
            return "README.md not found"
        return path.read_text(encoding="utf-8", errors="replace")
    if "python" in lowered and "统计" in content:
        return _count_files_by_extension(".py")
    if ("markdown" in lowered or ".md" in lowered) and "统计" in content:
        return _count_files_by_extension(".md")
    if "workspace" in lowered and ("统计" in content or "摘要" in content):
        return _workspace_summary()
    if "readme" in lowered and ("读取" in content or "read" in lowered):
        path = resolve_workspace_path("README.md")
        if not path.is_file():
            return "README.md not found"
        return path.read_text(encoding="utf-8", errors="replace")

    if "python" in lowered and ("count" in lowered or "统计" in content):
        return _count_files_by_extension(".py")

    if ("markdown" in lowered or ".md" in lowered) and ("count" in lowered or "统计" in content):
        return _count_files_by_extension(".md")

    if "workspace" in lowered and ("summary" in lowered or "统计" in content or "摘要" in content):
        return _workspace_summary()

    if plan is not None and is_summary_step(content):
        return summarize_previous_results(plan, step_index)

    return None


def _blocked_error_for_step(content: str, plan: dict[str, Any], step_index: int) -> str:
    if is_summary_step(content) and not previous_step_results(plan, step_index):
        return "missing previous step results"
    return "unsupported step type"


def _count_files_by_extension(extension: str) -> str:
    root = Path.cwd()
    ignored_dirs = {".agent_state", ".git", ".venv", "__pycache__"}
    count = 0
    for item in root.rglob("*"):
        rel_parts = item.relative_to(root).parts
        if any(part in ignored_dirs for part in rel_parts):
            continue
        if item.is_file() and item.suffix.lower() == extension:
            count += 1
    return f"Extension: {extension}\nCount: {count}"


def _workspace_summary() -> str:
    root = Path.cwd()
    ignored_dirs = {".agent_state", ".git", ".venv", "__pycache__"}
    file_count = 0
    dir_count = 0
    for item in root.rglob("*"):
        rel_parts = item.relative_to(root).parts
        if any(part in ignored_dirs for part in rel_parts):
            continue
        if item.is_dir():
            dir_count += 1
        elif item.is_file():
            file_count += 1
    return f"Workspace: {root.name}\nFiles: {file_count}\nDirectories: {dir_count}"


def _suggest_action(content: str) -> str:
    lowered = content.lower()
    if "readme" in lowered and "读取" in content:
        return "Use read_file with path README.md."
    if "python" in lowered and "统计" in content:
        return "Use count_files_by_extension with extension .py."
    if ("markdown" in lowered or ".md" in lowered) and "统计" in content:
        return "Use count_files_by_extension with extension .md."
    if "搜索" in content:
        return "Use search_files with the relevant query."
    if "readme" in lowered:
        return "Use read_file with path README.md."
    if "python" in lowered and ("count" in lowered or "统计" in content):
        return "Use count_files_by_extension with extension .py."
    if "markdown" in lowered or ".md" in lowered:
        return "Use count_files_by_extension with extension .md, or read the specific Markdown file if named."
    if is_summary_step(content):
        return "Use previous completed step results to write a concise summary."
    if "search" in lowered or "搜索" in content:
        return "Use search_files with the relevant query."
    return "Review the step and choose the smallest relevant tool. Ask the user if the action is ambiguous."
