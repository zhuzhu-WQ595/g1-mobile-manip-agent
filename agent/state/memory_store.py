from __future__ import annotations

from datetime import datetime
from pathlib import Path

STATE_DIR = Path.cwd() / ".agent_state"
MEMORY_FILE = STATE_DIR / "memory.md"


def load_memory(limit: int = 4000) -> str:
    if not MEMORY_FILE.exists():
        return ""
    text = MEMORY_FILE.read_text(encoding="utf-8", errors="replace").strip()
    return text[-limit:]


def remember(text: str) -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n- {timestamp}: {text.strip()}\n"
    with MEMORY_FILE.open("a", encoding="utf-8") as fp:
        fp.write(entry)
    return f"Memory saved to {MEMORY_FILE.relative_to(Path.cwd())}"


def clear_memory() -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text("", encoding="utf-8")
    return "Memory cleared"
