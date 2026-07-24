from __future__ import annotations

from pathlib import Path

from .schema import ToolHandler, schema


WORKSPACE_TOOL_SCHEMAS: list[dict[str, object]] = [
    schema(
        "get_workspace_summary",
        "Get workspace summary statistics: workspace name, total files, directories, Python files, and Markdown files. Use this when the user asks for workspace summary, workspace stats, project summary, or file counts.",
        {},
        [],
    ),
    schema(
        "count_files_by_extension",
        "Count files in the current workspace by extension. Use this when the user asks to count Python, Markdown, text, HTML, CSS, JavaScript, or other extension-specific files.",
        {
            "extension": {
                "type": "string",
                "description": "File extension to count, such as .py, .md, .txt, .html, .css, or .js.",
            }
        },
        ["extension"],
    ),
]


def get_workspace_summary() -> str:
    root = Path.cwd()
    ignored_dirs = {".agent_state", ".git", ".venv", "__pycache__"}
    file_count = 0
    dir_count = 0
    python_count = 0
    markdown_count = 0

    for item in root.rglob("*"):
        rel_parts = item.relative_to(root).parts
        if any(part in ignored_dirs for part in rel_parts):
            continue
        if item.is_dir():
            dir_count += 1
            continue
        if not item.is_file():
            continue
        file_count += 1
        suffix = item.suffix.lower()
        if suffix == ".py":
            python_count += 1
        elif suffix == ".md":
            markdown_count += 1

    return "\n".join(
        [
            f"Workspace: {root.name}",
            f"Files: {file_count}",
            f"Directories: {dir_count}",
            f"Python files: {python_count}",
            f"Markdown files: {markdown_count}",
        ]
    )


def count_files_by_extension(extension: str) -> str:
    ext = extension.strip().lower()
    if not ext:
        raise ValueError("extension is required")
    if not ext.startswith("."):
        ext = "." + ext

    root = Path.cwd()
    ignored_dirs = {".agent_state", ".git", ".venv", "__pycache__"}
    count = 0
    for item in root.rglob("*"):
        rel_parts = item.relative_to(root).parts
        if any(part in ignored_dirs for part in rel_parts):
            continue
        if item.is_file() and item.suffix.lower() == ext:
            count += 1

    return "\n".join(
        [
            f"Extension: {ext}",
            f"Count: {count}",
        ]
    )


WORKSPACE_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_workspace_summary": get_workspace_summary,
    "count_files_by_extension": count_files_by_extension,
}
