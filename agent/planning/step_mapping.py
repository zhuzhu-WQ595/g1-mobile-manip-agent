from __future__ import annotations

import re
from typing import Any


def map_plan_step(content: str) -> dict[str, Any]:
    text = content.strip()
    lowered = text.lower()

    match = re.match(r"^(?:read|读取)\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        return _tool("read_file", {"path": match.group(1).strip()})

    extension = _count_extension(lowered, text)
    if extension:
        return _tool("count_files_by_extension", {"extension": extension})

    if ("workspace" in lowered or "工作区" in text) and any(
        token in lowered or token in text for token in ("summary", "stats", "摘要", "统计")
    ):
        return _tool("get_workspace_summary", {})

    if any(token in lowered for token in ("summary", "summarize")) or any(
        token in text for token in ("汇总", "总结")
    ):
        return {"mode": "summary"}

    return {
        "mode": "manual",
        "reason": "No supported automatic tool mapping",
    }


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
