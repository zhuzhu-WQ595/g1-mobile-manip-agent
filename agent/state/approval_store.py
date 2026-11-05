from __future__ import annotations

import json
from datetime import datetime
from difflib import unified_diff
from hashlib import sha256
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


def _approval_status(approval: dict[str, Any]) -> str:
    return str(approval.get("status") or "pending")


def _history_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer between 1 and 100") from exc
    if value < 1 or value > 100:
        raise ValueError("limit must be between 1 and 100")
    return value


def _table_cell(value: Any) -> str:
    return str(value or "-").replace("\n", " ").replace("|", r"\|")


def _resolve_approval(
    approvals: dict[str, Any],
    approval_id: str,
    status: str,
    result: str,
) -> str:
    approval = approvals[approval_id]
    approval["status"] = status
    approval["resolved_at"] = datetime.now().isoformat(timespec="seconds")
    approval["result"] = result
    _save_approvals(approvals)
    return result


def request_overwrite_file(path: str, content: str) -> str:
    file_path = resolve_workspace_path(path)
    approvals = _load_approvals()
    approval_id = _next_approval_id(approvals)
    approvals[approval_id] = {
        "action": "overwrite_file",
        "path": str(file_path.relative_to(Path.cwd())),
        "content": content,
        "status": "pending",
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
            f"Or: cancel {approval_id}",
        ]
    )


def request_edit_file(path: str, old_text: str, new_text: str) -> str:
    file_path = resolve_workspace_path(path)
    if not file_path.is_file():
        return f"Not a file: {path}"
    if not old_text:
        return "old_text must not be empty"
    if old_text == new_text:
        return "old_text and new_text are identical; approval was not created"

    text = file_path.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_text)
    if count == 0:
        return "No match found; approval was not created"
    if count > 1:
        return f"Found {count} matches; refine old_text before requesting approval"

    updated = text.replace(old_text, new_text, 1)
    relative_path = file_path.relative_to(Path.cwd())
    diff = "\n".join(
        unified_diff(
            text.splitlines(),
            updated.splitlines(),
            fromfile=f"a/{relative_path.as_posix()}",
            tofile=f"b/{relative_path.as_posix()}",
            lineterm="",
        )
    )

    approvals = _load_approvals()
    approval_id = _next_approval_id(approvals)
    approvals[approval_id] = {
        "action": "edit_file",
        "path": str(relative_path),
        "old_text": old_text,
        "new_text": new_text,
        "diff": diff,
        "original_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "status": "pending",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_approvals(approvals)

    return "\n".join(
        [
            "Approval required before editing a file.",
            f"Approval ID: {approval_id}",
            "Action: edit_file",
            f"Path: {relative_path}",
            "Diff:",
            "```diff",
            diff,
            "```",
            "",
            f"Type: approve {approval_id}",
            f"Or: cancel {approval_id}",
        ]
    )


def approve_pending_action(approval_id: str) -> str:
    approvals = _load_approvals()
    approval = approvals.get(approval_id)
    if approval is None:
        return f"No pending approval found: {approval_id}"
    status = _approval_status(approval)
    if status != "pending":
        return f"Approval {approval_id} is already {status}"

    action = approval.get("action")
    file_path = resolve_workspace_path(str(approval["path"]))
    if action == "overwrite_file":
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = str(approval.get("content", ""))
        file_path.write_text(content, encoding="utf-8")
        result = f"Approved {approval_id}; overwrote {file_path.relative_to(Path.cwd())} with {len(content)} characters"
    elif action == "edit_file":
        if not file_path.is_file():
            result = f"Cancelled {approval_id}; file no longer exists: {approval['path']}"
            return _resolve_approval(approvals, approval_id, "cancelled", result)

        text = file_path.read_text(encoding="utf-8", errors="replace")
        current_sha256 = sha256(text.encode("utf-8")).hexdigest()
        if current_sha256 != approval.get("original_sha256"):
            result = f"Cancelled {approval_id}; file changed after approval was requested"
            return _resolve_approval(approvals, approval_id, "cancelled", result)

        old_text = str(approval.get("old_text", ""))
        if not old_text or text.count(old_text) != 1:
            result = f"Cancelled {approval_id}; the approved text no longer has one exact match"
            return _resolve_approval(approvals, approval_id, "cancelled", result)

        new_text = str(approval.get("new_text", ""))
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        result = f"Approved {approval_id}; edited {file_path.relative_to(Path.cwd())}"
    else:
        return f"Unsupported approval action: {action}"

    return _resolve_approval(approvals, approval_id, "approved", result)


def cancel_pending_action(approval_id: str) -> str:
    approvals = _load_approvals()
    approval = approvals.get(approval_id)
    if approval is None:
        return f"No pending approval found: {approval_id}"
    status = _approval_status(approval)
    if status != "pending":
        return f"Approval {approval_id} is already {status}"

    result = (
        f"Cancelled {approval_id}; {approval.get('action')} for "
        f"{approval.get('path')} was not executed"
    )
    return _resolve_approval(approvals, approval_id, "cancelled", result)


def list_pending_approvals() -> str:
    approvals = _load_approvals()
    if not approvals:
        return "(no pending approvals)"
    rows = []
    for approval_id, approval in sorted(approvals.items()):
        if _approval_status(approval) != "pending":
            continue
        rows.append(
            f"{approval_id}: {approval.get('action')} {approval.get('path')} created_at={approval.get('created_at')}"
        )
    return "\n".join(rows) if rows else "(no pending approvals)"


def list_approval_history(limit: int = 10) -> str:
    row_limit = _history_limit(limit)
    approvals = _load_approvals()
    if not approvals:
        return "(no approval history)"

    records = sorted(
        approvals.items(),
        key=lambda item: (str(item[1].get("created_at", "")), item[0]),
        reverse=True,
    )[:row_limit]
    rows = [
        "Approval history:",
        "| # | ID | Status | Action | Path | Created | Resolved |",
        "|---:|---|---|---|---|---|---|",
    ]
    for index, (approval_id, approval) in enumerate(records, start=1):
        rows.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _table_cell(approval_id),
                    _table_cell(_approval_status(approval)),
                    _table_cell(approval.get("action")),
                    _table_cell(approval.get("path")),
                    _table_cell(approval.get("created_at")),
                    _table_cell(approval.get("resolved_at")),
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def get_approval_details(approval_id: str) -> str:
    approval = _load_approvals().get(approval_id)
    if approval is None:
        return f"Approval not found: {approval_id}"

    rows = [
        "Approval details:",
        f"ID: {approval_id}",
        f"Status: {_approval_status(approval)}",
        f"Action: {approval.get('action')}",
        f"Path: {approval.get('path')}",
        f"Created: {approval.get('created_at')}",
    ]
    if approval.get("resolved_at"):
        rows.append(f"Resolved: {approval['resolved_at']}")
    if approval.get("result"):
        rows.append(f"Result: {approval['result']}")

    if approval.get("action") == "edit_file":
        diff = str(approval.get("diff") or "")
        if diff:
            rows.extend(["Diff:", "```diff", diff, "```"])
        else:
            rows.append("Diff: (not recorded for this approval)")
    elif approval.get("action") == "overwrite_file":
        content = str(approval.get("content", ""))
        preview = content[:500]
        if len(content) > 500:
            preview += "..."
        rows.extend(["Content preview:", "```text", preview, "```"])

    return "\n".join(rows)
