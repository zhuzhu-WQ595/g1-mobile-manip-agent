from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..permissions import resolve_workspace_path

STATE_DIR = Path.cwd() / ".agent_state"
APPROVALS_FILE = STATE_DIR / "approvals.json"


def _load_approvals() -> dict[str, Any]:
    if not APPROVALS_FILE.exists():
        return {}
    return json.loads(APPROVALS_FILE.read_text(encoding="utf-8", errors="replace") or "{}")


def _save_approvals(approvals: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    APPROVALS_FILE.write_text(json.dumps(approvals, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_approval_id(approvals: dict[str, Any]) -> str:
    index = 1
    while f"approval_{index:03d}" in approvals:
        index += 1
    return f"approval_{index:03d}"


def request_overwrite_file(path: str, content: str) -> str:
    file_path = resolve_workspace_path(path)
    approvals = _load_approvals()
    approval_id = _next_approval_id(approvals)
    approvals[approval_id] = {
        "action": "overwrite_file",
        "path": str(file_path.relative_to(Path.cwd())),
        "content": content,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_approvals(approvals)

    preview = content[:160]
    if len(content) > 160:
        preview += "..."
    return "\n".join(
        [
            "Approval required before overwriting a file.",
            f"Approval ID: {approval_id}",
            f"Action: overwrite_file",
            f"Path: {file_path.relative_to(Path.cwd())}",
            f"Content preview: {preview}",
            "",
            f"Type: approve {approval_id}",
        ]
    )


def approve_pending_action(approval_id: str) -> str:
    approvals = _load_approvals()
    approval = approvals.get(approval_id)
    if approval is None:
        return f"No pending approval found: {approval_id}"
    if approval.get("action") != "overwrite_file":
        return f"Unsupported approval action: {approval.get('action')}"

    file_path = resolve_workspace_path(str(approval["path"]))
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = str(approval.get("content", ""))
    file_path.write_text(content, encoding="utf-8")
    del approvals[approval_id]
    _save_approvals(approvals)
    return f"Approved {approval_id}; overwrote {file_path.relative_to(Path.cwd())} with {len(content)} characters"


def list_pending_approvals() -> str:
    approvals = _load_approvals()
    if not approvals:
        return "(no pending approvals)"
    rows = []
    for approval_id, approval in sorted(approvals.items()):
        rows.append(
            f"{approval_id}: {approval.get('action')} {approval.get('path')} created_at={approval.get('created_at')}"
        )
    return "\n".join(rows)
