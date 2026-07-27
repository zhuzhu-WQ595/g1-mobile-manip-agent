from __future__ import annotations

import json
import re
from typing import Any

from .tool_runner import plan_tool_names


def map_plan_step(content: str) -> dict[str, Any]:
    text = content.strip()
    lowered = text.lower()

    explicit_tool = _explicit_tool_call(text)
    if explicit_tool:
        return explicit_tool

    match = re.match(r"^list files(?:\s+in\s+(.+))?$", text, flags=re.IGNORECASE)
    if match:
        return _tool("list_files", {"path": (match.group(1) or ".").strip()})

    match = re.match(r"^(?:read|读取)\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _tool("read_file", {"path": match.group(1).strip()})

    match = re.match(r"^(?:show|preview|read)\s+first\s+(\d+)\s+lines?\s+of\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _tool("preview_file_head", {"lines": int(match.group(1)), "path": match.group(2).strip()})

    match = re.match(r"^preview\s+(.+?)\s+(\d+)\s+lines?$", text, flags=re.IGNORECASE)
    if match:
        return _tool("preview_file_head", {"path": match.group(1).strip(), "lines": int(match.group(2))})

    match = re.match(r"^search\s+(.+?)\s+for\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _tool("search_files", {"path": match.group(1).strip(), "query": match.group(2).strip()})

    match = re.match(r"^find\s+(.+?)\s+in\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _tool("search_files", {"path": match.group(2).strip(), "query": match.group(1).strip()})

    match = re.match(r"^(?:search|find|搜索)\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _tool("search_files", {"path": ".", "query": match.group(1).strip()})

    command = _command_for_step(lowered, text)
    if command:
        return _tool("run_command", {"command": command})

    match = re.match(r"^request edit\s+(.+?)\s+::\s*(.*?)\s+=>\s*(.+)$", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return _tool(
            "request_edit_file",
            {
                "path": match.group(1).strip(),
                "old_text": match.group(2),
                "new_text": match.group(3),
            },
        )

    match = re.match(r"^request overwrite\s+(.+?)\s+::\s*(.*)$", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return _tool("request_overwrite_file", {"path": match.group(1).strip(), "content": match.group(2)})

    match = re.match(r"^(?:save|record|log)\s+experiment\s+note\s+::\s*(.+)$", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return _tool("save_experiment_note", {"note": match.group(1).strip()})

    extension = _count_extension(lowered, text)
    if extension:
        return _tool("count_files_by_extension", {"extension": extension})

    if ("workspace" in lowered or "工作区" in text) and any(
        token in lowered or token in text for token in ("summary", "stats", "摘要", "统计")
    ):
        return _tool("get_workspace_summary", {})

    if any(token in lowered for token in ("summary", "summarize")) or any(token in text for token in ("汇总", "总结")):
        return {"mode": "summary"}

    return _manual("No supported automatic tool mapping")


def describe_step_mapping(step: dict[str, Any]) -> str:
    executor = step.get("executor") or map_plan_step(str(step.get("content", "")))
    mode = executor.get("mode")
    if mode == "tool":
        arguments = executor.get("arguments", {})
        return f"tool={executor.get('tool')} arguments={arguments}"
    if mode == "summary":
        return "internal=summary_previous_results"
    return f"manual={executor.get('reason', 'Manual execution required')}"


def _tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"mode": "tool", "tool": name, "arguments": arguments}


def _manual(reason: str) -> dict[str, str]:
    return {"mode": "manual", "reason": reason}


def _explicit_tool_call(text: str) -> dict[str, Any] | None:
    match = re.match(r"^tool\s*:?\s*([A-Za-z_][A-Za-z0-9_]*)\s+({.*})$", text, flags=re.DOTALL)
    if not match:
        return None
    name = match.group(1)
    if name not in plan_tool_names():
        return _manual(f"Tool is not enabled for plan execution: {name}")
    try:
        arguments = json.loads(match.group(2))
    except json.JSONDecodeError:
        return _manual("Explicit tool step arguments must be a JSON object")
    if not isinstance(arguments, dict):
        return _manual("Explicit tool step arguments must be a JSON object")
    return _tool(name, arguments)


def _command_for_step(lowered: str, text: str) -> str | None:
    aliases = {
        "pytest": "python -m pytest -q",
        "run pytest": "python -m pytest -q",
        "run tests": "python -m pytest -q",
        "python -m pytest": "python -m pytest",
        "python -m pytest -q": "python -m pytest -q",
        "python version": "python --version",
        "python --version": "python --version",
    }
    if lowered in aliases:
        return aliases[lowered]
    match = re.match(r"^run command\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _count_extension(lowered: str, text: str) -> str | None:
    if not ("count" in lowered or "统计" in text):
        return None
    aliases = {
        "python": ".py",
        ".py": ".py",
        "markdown": ".md",
        ".md": ".md",
        "javascript": ".js",
        ".js": ".js",
        "css": ".css",
        ".txt": ".txt",
        "文本": ".txt",
    }
    for token, extension in aliases.items():
        if token in lowered or token in text:
            return extension
    return None
