from __future__ import annotations

SAFETY_RULES = [
    "When the user asks to overwrite a file, use request_overwrite_file instead of write_file. Do not overwrite until the user sends approve approval_id.",
    "When the user sends approve approval_id, use approve_pending_action.",
    "If a tool fails because requested parameters are outside allowed limits, do not retry with modified parameters unless the user explicitly confirms the new parameters. Explain the limit and wait for the user.",
    "If a request is unsafe or outside the workspace, say so.",
]
