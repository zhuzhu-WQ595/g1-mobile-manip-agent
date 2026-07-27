from __future__ import annotations

import sys

from .agent_loop import Agent
from .model_adapter import load_model_from_env


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    model = load_model_from_env()
    agent = Agent(model=model)

    print("self-test agent")
    print("Type q to quit. Try: list files | read README.md | write notes/new-note.txt :: hello | python version")
    while True:
        try:
            text = input("agent >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if text.lower() in {"q", "quit", "exit"}:
            break
        if not text:
            continue

        answer = agent.run_turn(text)
        print(answer)


if __name__ == "__main__":
    main()
