from __future__ import annotations

TOOL_RULES = [
    "For conceptual, explanatory, or architecture questions, answer directly without tools unless workspace or robot state is needed.",
    "Use tools only when you need workspace state, file contents, memory, tasks, robot state, or command output.",
    "When the user asks for workspace summary, workspace stats, project summary, or file counts, prefer get_workspace_summary over multiple list_files calls.",
    "When the user asks to count files of a specific extension or type, use count_files_by_extension with the matching extension.",
    "When the user asks to preview, show, or read the first N lines of a file, always use preview_file_head, not read_file. Pass the requested N exactly; preview_file_head will reject values outside 1 to 50.",
    "When the user asks to save, record, or log an experiment result, use save_experiment_note.",
    "When the user asks for recent tool calls, tool events, tool logs, or tool history, use get_recent_tool_events.",
    "Do not call tools that are not listed in the provided tool schema.",
    "Prefer the smallest useful action.",
]
