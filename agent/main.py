from __future__ import annotations

import sys

from .agent_loop import Agent
from .execution import GoalRunner, ROBOT_GOAL_TOOLS, RobotFeedbackVerifier, write_goal_report
from .models import DemoModel, load_model_from_env


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    model = load_model_from_env()
    agent = Agent(model=model)
    goal_runner = GoalRunner(model=model)
    robot_goal_runner = GoalRunner(
        model=model,
        tool_names=ROBOT_GOAL_TOOLS,
        completion_verifier=RobotFeedbackVerifier(
            critic_model=None if isinstance(model, DemoModel) else model
        ),
    )

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

        if text.lower().startswith("/goal "):
            result = goal_runner.run(text[6:])
            report_path = write_goal_report(result)
            print(result["answer"])
            print(f"[goal: {result['status']}; steps: {result['steps_executed']}; report: {report_path}]")
            continue

        if text.lower().startswith("/robot-goal "):
            result = robot_goal_runner.run(text[12:])
            report_path = write_goal_report(result)
            print(result["answer"])
            print(
                f"[robot goal: {result['status']} ({result['stop_reason']}); "
                f"steps: {result['steps_executed']}; report: {report_path}]"
            )
            continue

        answer = agent.run_turn(text)
        print(answer)


if __name__ == "__main__":
    main()
