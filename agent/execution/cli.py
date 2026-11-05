from __future__ import annotations

import argparse
import sys

from ..models import DemoModel, load_model_from_env
from .reporting import write_goal_report
from .runner import GoalRunner, MOBILE_MANIP_GOAL_TOOLS, MOBILE_MANIP_RULES, ROBOT_GOAL_TOOLS
from .verification import RobotFeedbackVerifier


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run a feedback-driven goal without a saved plan.")
    parser.add_argument("goal", help="Final goal in natural language.")
    parser.add_argument("--max-steps", type=int, default=8, help="Maximum number of tool steps.")
    parser.add_argument("--output", help="Write the JSON trace to this path.")
    parser.add_argument("--allow-demo", action="store_true", help="Allow the deterministic demo model for a local check.")
    parser.add_argument("--robot", action="store_true", help="Enable robot tools and feedback verification.")
    parser.add_argument(
        "--mobile-manip",
        action="store_true",
        help="Mobile manipulation mission mode (SLAM navigation + VLA skills; backend via MOBILE_MANIP_BACKEND=mock|isaac).",
    )
    args = parser.parse_args()

    if args.max_steps < 1 or args.max_steps > 20:
        parser.error("--max-steps must be between 1 and 20")
    model = load_model_from_env()
    if isinstance(model, DemoModel) and not args.allow_demo:
        parser.error("A real model is required; configure AGENT_PROVIDER or pass --allow-demo for a local check.")

    if args.mobile_manip:
        runner = GoalRunner(
            model,
            max_steps=args.max_steps,
            tool_names=MOBILE_MANIP_GOAL_TOOLS,
            goal_rules=MOBILE_MANIP_RULES,
        )
        result = runner.run(args.goal)
        path = write_goal_report(result, args.output)
        print("\n" + result["answer"])
        print(f"\nstatus: {result['status']} ({result['stop_reason']})")
        print(f"steps: {result['steps_executed']}")
        print(f"report: {path}")
        return

    runner = (
        GoalRunner(
            model,
            max_steps=args.max_steps,
            tool_names=ROBOT_GOAL_TOOLS,
            completion_verifier=RobotFeedbackVerifier(
                critic_model=None if isinstance(model, DemoModel) else model
            ),
        )
        if args.robot
        else GoalRunner(model, max_steps=args.max_steps)
    )
    result = runner.run(args.goal)
    path = write_goal_report(result, args.output)
    print("\n" + result["answer"])
    print(f"\nstatus: {result['status']} ({result['stop_reason']})")
    print(f"steps: {result['steps_executed']}")
    print(f"report: {path}")


if __name__ == "__main__":
    main()
