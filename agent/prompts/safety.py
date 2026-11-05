from __future__ import annotations

SAFETY_RULES = [
    "Use write_file only to create a new file. If the file already exists, use request_overwrite_file and wait for approval.",
    "When the user asks to overwrite a file, use request_overwrite_file instead of write_file. Do not overwrite until the user sends approve approval_id.",
    "When the user asks to edit or replace text in an existing file, use request_edit_file instead of edit_file. Show the returned diff and do not edit until the user sends approve approval_id.",
    "When the user sends approve approval_id, use approve_pending_action.",
    "When the user sends cancel or reject approval_id, use cancel_pending_action and do not execute the pending action.",
    "If a tool fails because requested parameters are outside allowed limits, do not retry with modified parameters unless the user explicitly confirms the new parameters. Explain the limit and wait for the user.",
    "If a request is unsafe or outside the workspace, say so.",
]
