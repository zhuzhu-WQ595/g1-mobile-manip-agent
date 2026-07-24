from __future__ import annotations

from pathlib import Path

from ..permissions import resolve_workspace_path

from .schema import ToolHandler, schema


FILE_TOOL_SCHEMAS: list[dict[str, object]] = [
    schema("list_files", "List files in a workspace directory.", {"path": {"type": "string"}}),
    schema(
        "read_file",
        "Read an entire UTF-8 text file inside the workspace. Do not use this for first-N-lines preview requests; use preview_file_head instead.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    schema(
        "write_file",
        "Write a UTF-8 text file inside the workspace.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    ),
    schema(
        "append_file",
        "Append UTF-8 text to a file inside the workspace.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    ),
    schema(
        "edit_file",
        "Replace an exact text fragment in a UTF-8 file inside the workspace.",
        {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        ["path", "old_text", "new_text"],
    ),
    schema("create_folder", "Create a folder inside the workspace.", {"path": {"type": "string"}}, ["path"]),
    schema(
        "search_files",
        "Search file names and text content under a workspace directory.",
        {"path": {"type": "string"}, "query": {"type": "string"}},
        ["path", "query"],
    ),
    schema(
        "preview_file_head",
        "Preview the first N lines of a UTF-8 text file inside the workspace. Always use this, not read_file, when the user asks to show, preview, or read the first N lines of a file. Pass the requested N even if it is outside the allowed range so validation can reject it.",
        {
            "path": {"type": "string", "description": "Workspace-relative file path to preview."},
            "lines": {
                "type": "integer",
                "description": "Number of lines to preview. Must be between 1 and 50.",
            },
        },
        ["path", "lines"],
    ),
]


def list_files(path: str = ".") -> str:
    directory = resolve_workspace_path(path)
    if not directory.exists():
        return f"Directory does not exist: {path}"
    if not directory.is_dir():
        return f"Not a directory: {path}"

    rows = []
    for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        kind = "dir " if item.is_dir() else "file"
        rows.append(f"{kind}  {item.name}")
    return "\n".join(rows) if rows else "(empty)"


def read_file(path: str) -> str:
    file_path = resolve_workspace_path(path)
    if not file_path.exists():
        return f"File does not exist: {path}"
    if not file_path.is_file():
        return f"Not a file: {path}"
    return file_path.read_text(encoding="utf-8", errors="replace")


def write_file(path: str, content: str) -> str:
    file_path = resolve_workspace_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {file_path.relative_to(Path.cwd())}"


def append_file(path: str, content: str) -> str:
    file_path = resolve_workspace_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as fp:
        fp.write(content)
    return f"Appended {len(content)} characters to {file_path.relative_to(Path.cwd())}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    file_path = resolve_workspace_path(path)
    if not file_path.is_file():
        return f"Not a file: {path}"
    text = file_path.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_text)
    if count == 0:
        return "No match found; file was not changed"
    if count > 1:
        return f"Found {count} matches; refine old_text before editing"
    file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
    return f"Edited {file_path.relative_to(Path.cwd())}"


def create_folder(path: str) -> str:
    directory = resolve_workspace_path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return f"Created folder {directory.relative_to(Path.cwd())}"


def search_files(path: str, query: str) -> str:
    root = resolve_workspace_path(path)
    if not root.exists():
        return f"Path does not exist: {path}"
    query_lower = query.lower()
    matches: list[str] = []
    ignored_dirs = {".venv", "__pycache__", ".git"}
    text_suffixes = {".css", ".env", ".html", ".js", ".json", ".md", ".py", ".txt"}
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for file_path in files:
        if any(part in ignored_dirs for part in file_path.parts):
            continue
        rel = file_path.relative_to(Path.cwd())
        if query_lower in file_path.name.lower():
            matches.append(f"name: {rel}")
        if file_path.suffix.lower() not in text_suffixes:
            continue
        try:
            for line_no, line in enumerate(file_path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                if query_lower in line.lower():
                    matches.append(f"text: {rel}:{line_no}: {line.strip()[:160]}")
                    break
        except OSError:
            continue
        if len(matches) >= 40:
            break
    return "\n".join(matches) if matches else "(no matches)"


def preview_file_head(path: str, lines: int) -> str:
    try:
        line_count = int(lines)
    except (TypeError, ValueError) as exc:
        raise ValueError("lines must be an integer between 1 and 50") from exc
    if line_count < 1 or line_count > 50:
        raise ValueError("lines must be between 1 and 50")

    file_path = resolve_workspace_path(path)
    if not file_path.exists():
        return f"File does not exist: {path}"
    if not file_path.is_file():
        return f"Not a file: {path}"

    rows = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    preview = rows[:line_count]
    numbered = [f"{index}: {line}" for index, line in enumerate(preview, start=1)]
    if not numbered:
        return f"{path} is empty"
    return "\n".join(numbered)


FILE_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "edit_file": edit_file,
    "create_folder": create_folder,
    "search_files": search_files,
    "preview_file_head": preview_file_head,
}
