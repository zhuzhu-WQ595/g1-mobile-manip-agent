from __future__ import annotations

import json
from typing import Any

ContentPart = dict[str, Any]
Message = dict[str, Any]


def text_part(text: str) -> ContentPart:
    return {"type": "text", "text": text}


def image_part(path: str, detail: str = "auto") -> ContentPart:
    return {"type": "image", "path": path, "detail": detail}


def file_part(path: str) -> ContentPart:
    return {"type": "file", "path": path}


def user_message(text: str) -> Message:
    return {"role": "user", "content": [text_part(text)]}


def assistant_message(text: str) -> Message:
    return {"role": "assistant", "content": [text_part(text)]}


def assistant_tool_call_message(
    tool_calls: list[dict[str, Any]],
    reasoning_content: str | None = None,
) -> Message:
    message: Message = {"role": "assistant", "content": [], "tool_calls": tool_calls}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return message


def tool_result_message(tool_call_id: str, name: str, result: str) -> Message:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": [text_part(result)],
    }


def tool_result_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


def parts_to_text(parts: list[ContentPart]) -> str:
    chunks: list[str] = []
    for part in parts:
        if part.get("type") == "text":
            chunks.append(str(part.get("text", "")))
        else:
            chunks.append(f"[{part.get('type')}:{part.get('path', '')}]")
    return "\n".join(chunk for chunk in chunks if chunk)
