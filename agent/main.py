from __future__ import annotations

import sys

from .agent_loop import Agent
from .execution import GoalRunner, ROBOT_GOAL_TOOLS, RobotFeedbackVerifier, write_goal_report
from .models import DemoModel, load_model_from_env

ROBOT_KEYWORDS = frozenset({
    "robot", "move", "forward", "backward", "turn", "rotate", "left", "right",
    "robot_move", "robot_rotate", "robot_get_status",
    "起点", "终点", "前进", "后退", "左转", "右转", "移动", "旋转",
    "路径", "导航", "障碍", "到达", "出发", "可行路径",
    "鸭子", "走路", "踢球", "翻滚", "捡东西", "坐下", "站立", "头部", "身体",
    "duck", "walk", "kick", "roulade", "ground pick", "sit", "stand", "head", "body pose",
})


def _is_robot_task(text: str) -> bool:
    lowered = text.lower()
    if any(kw in lowered for kw in ROBOT_KEYWORDS):
        return True
    if text.lower().startswith("/robot-goal "):
        return True
    return False


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    model = load_model_from_env()
    agent = Agent(model=model, max_steps=32)
    goal_runner = GoalRunner(model=model)
    robot_goal_runner = GoalRunner(
        model=model,
        max_steps=48,
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

        if _is_robot_task(text):
            result = robot_goal_runner.run(text)
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
