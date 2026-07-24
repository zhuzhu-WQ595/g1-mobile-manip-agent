from __future__ import annotations

SKILLS = {
    "coding": "Read code first, make small targeted edits, then run focused verification.",
    "file_management": "Inspect paths before writing. Prefer append or targeted replace over broad rewrites.",
    "planning": "Break work into short steps, keep only one active step, and update status as work changes.",
}


def list_skills() -> str:
    return "\n".join(f"- {name}: {desc}" for name, desc in SKILLS.items())


def read_skill(name: str) -> str:
    skill = SKILLS.get(name)
    if not skill:
        return f"Skill not found: {name}. Available: {', '.join(SKILLS)}"
    return f"{name}: {skill}"
