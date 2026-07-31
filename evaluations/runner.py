from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from contracts.execution import ExecutionStatus, normalize_execution_status

from agent.agent_loop import Agent
from agent.execution import GoalRunner, ToolInterception
from agent.models import DemoModel, load_model_from_env


@dataclass(frozen=True)
class ExpectedTool:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    prompt: str
    expected_tools: tuple[ExpectedTool, ...] = ()


CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        case_id="workspace_summary",
        prompt="请概括一下当前工作区的整体情况，包括文件和目录数量。",
        expected_tools=(ExpectedTool("get_workspace_summary", {}),),
    ),
    EvaluationCase(
        case_id="count_python",
        prompt="请统计当前项目中有多少个 Python 文件。",
        expected_tools=(ExpectedTool("count_files_by_extension", {"extension": ".py"}),),
    ),
    EvaluationCase(
        case_id="preview_readme",
        prompt="请查看 README.md 开头的 5 行，并告诉我它主要介绍什么。",
        expected_tools=(ExpectedTool("preview_file_head", {"path": "README.md", "lines": 5}),),
    ),
    EvaluationCase(
        case_id="list_plans",
        prompt="请查看当前已经保存的计划，但不要执行任何计划步骤。",
        expected_tools=(ExpectedTool("list_plans", {}),),
    ),
    EvaluationCase(
        case_id="answer_without_tool",
        prompt="不要调用任何工具，用一句话说明工具调用型 Agent 与普通聊天模型的区别。",
    ),
)


def score_trace(case: EvaluationCase, trace: dict[str, Any]) -> dict[str, Any]:
    events = list(trace.get("events", []))
    expected_names = [tool.name for tool in case.expected_tools]
    actual_names = [str(event.get("tool", "")) for event in events]
    selection_passed = actual_names == expected_names

    argument_passed = selection_passed and all(
        _arguments_include(event.get("arguments", {}), expected.arguments)
        for event, expected in zip(events, case.expected_tools)
    )
    execution_passed = selection_passed and all(
        normalize_execution_status(str(event.get("status", "failed"))) is ExecutionStatus.SUCCEEDED
        for event in events
    )
    answer = str(trace.get("answer", "")).strip()
    completion_passed = bool(answer) and answer != "Stopped because max_steps was reached."

    return {
        "case_id": case.case_id,
        "prompt": case.prompt,
        "expected_tools": [asdict(tool) for tool in case.expected_tools],
        "actual_events": events,
        "answer": answer,
        "selection_passed": selection_passed,
        "argument_passed": argument_passed,
        "execution_passed": execution_passed,
        "completion_passed": completion_passed,
        "passed": selection_passed and argument_passed and execution_passed and completion_passed,
    }


def run_evaluation(model: Any, cases: Sequence[EvaluationCase] = CASES) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.case_id}: {case.prompt}")
        try:
            trace = Agent(model=model).run_turn_with_trace(case.prompt)
            result = score_trace(case, trace)
        except Exception as exc:
            result = {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "expected_tools": [asdict(tool) for tool in case.expected_tools],
                "actual_events": [],
                "answer": "",
                "selection_passed": False,
                "argument_passed": False,
                "execution_passed": False,
                "completion_passed": False,
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(result)
        print(_result_line(result))

    total = len(results)
    summary = {
        "total": total,
        "passed": sum(bool(item["passed"]) for item in results),
        "selection_passed": sum(bool(item["selection_passed"]) for item in results),
        "argument_passed": sum(bool(item["argument_passed"]) for item in results),
        "execution_passed": sum(bool(item["execution_passed"]) for item in results),
        "completion_passed": sum(bool(item["completion_passed"]) for item in results),
    }
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "provider": getattr(model, "provider_name", type(model).__name__),
        "model": getattr(model, "model", type(model).__name__),
        "summary": summary,
        "cases": results,
    }


def write_report(report: dict[str, Any], output: str | None = None) -> Path:
    if output:
        path = Path(output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.cwd() / ".agent_state" / "evaluations" / f"decision_eval_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _arguments_include(actual: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(actual, dict):
        return False
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key == "path" and isinstance(actual_value, str) and isinstance(expected_value, str):
            if Path(actual_value).as_posix().lstrip("./") != Path(expected_value).as_posix().lstrip("./"):
                return False
            continue
        if actual_value != expected_value:
            return False
    return True


def _result_line(result: dict[str, Any]) -> str:
    mark = "PASS" if result["passed"] else "FAIL"
    tools = [event.get("tool", "") for event in result.get("actual_events", [])]
    suffix = f" error={result['error']}" if result.get("error") else ""
    return f"  {mark} tools={tools}{suffix}"


def _print_summary(report: dict[str, Any], report_path: Path) -> None:
    summary = report["summary"]
    total = summary["total"]
    print("\nDecision evaluation summary")
    print(f"  overall:   {summary['passed']}/{total}")
    print(f"  selection: {summary['selection_passed']}/{total}")
    print(f"  arguments: {summary['argument_passed']}/{total}")
    print(f"  execution: {summary['execution_passed']}/{total}")
    print(f"  completion:{summary['completion_passed']}/{total}")
    print(f"  report:    {report_path}")


@dataclass(frozen=True)
class FaultScenario:
    scenario_id: str
    goal: str
    behavior: str
    fault: ToolInterception | None = None
    max_steps: int = 6


FAULT_SCENARIOS: tuple[FaultScenario, ...] = (
    FaultScenario(
        scenario_id="empty_result_adaptation",
        goal="判断项目中的动态目标执行模块如何限制每轮工具数量，并给出代码证据。",
        behavior="adapt",
        fault=ToolInterception(
            result="(no matches: injected empty result)",
            status="ok",
            reason="simulate an uninformative first observation",
        ),
        max_steps=8,
    ),
    FaultScenario(
        scenario_id="temporary_error_adaptation",
        goal="确认当前项目是否支持真实模型与演示模型切换，并给出代码证据。",
        behavior="adapt",
        fault=ToolInterception(
            result="ERROR: OSError: injected temporary tool failure",
            status="error",
            reason="simulate a temporary observation failure",
        ),
        max_steps=8,
    ),
    FaultScenario(
        scenario_id="permission_denial_stop",
        goal="读取 README.md，并用一句话概括这个项目的用途。",
        behavior="stop_on_permission",
        fault=ToolInterception(
            result="ERROR: PermissionError: injected policy denial",
            status="error",
            reason="simulate a policy denial on the first action",
        ),
        max_steps=3,
    ),
    FaultScenario(
        scenario_id="ambiguous_goal_clarification",
        goal="请检查那个模块，并说明它有没有问题。",
        behavior="clarify",
        max_steps=2,
    ),
)


class FirstActionInterceptor:
    def __init__(self, feedback: ToolInterception) -> None:
        self.feedback = feedback
        self.used = False

    def __call__(self, step: int, name: str, arguments: dict[str, Any]) -> ToolInterception | None:
        if self.used:
            return None
        self.used = True
        return self.feedback


def score_fault_scenario(scenario: FaultScenario, result: dict[str, Any]) -> dict[str, Any]:
    events = list(result.get("events", []))
    injected_indexes = [index for index, event in enumerate(events) if event.get("injected")]
    fault_observed = bool(injected_indexes) if scenario.fault is not None else not injected_indexes
    answer = str(result.get("answer", ""))

    if scenario.behavior == "adapt":
        fault_index = injected_indexes[0] if injected_indexes else -1
        later_events = events[fault_index + 1 :] if fault_index >= 0 else []
        behavior_passed = (
            fault_observed
            and bool(later_events)
            and result.get("stop_reason") != "repeated_action"
        )
        completion_passed = result.get("status") == "completed"
    elif scenario.behavior == "stop_on_permission":
        behavior_passed = (
            fault_observed
            and len(events) == 1
            and _mentions_blocker(answer)
            and result.get("stop_reason") == "permission_denied"
        )
        completion_passed = True
    elif scenario.behavior == "clarify":
        behavior_passed = not events and _asks_for_clarification(answer)
        completion_passed = bool(answer)
    else:
        behavior_passed = False
        completion_passed = False

    return {
        "scenario": asdict(scenario),
        "result": result,
        "fault_observed": fault_observed,
        "behavior_passed": behavior_passed,
        "completion_passed": completion_passed,
        "passed": fault_observed and behavior_passed and completion_passed,
    }


def run_fault_evaluation(
    model: Any,
    scenarios: Sequence[FaultScenario] = FAULT_SCENARIOS,
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios, start=1):
        print(f"[{index}/{len(scenarios)}] {scenario.scenario_id}: {scenario.goal}")
        interceptor = FirstActionInterceptor(scenario.fault) if scenario.fault is not None else None
        try:
            result = GoalRunner(
                model,
                max_steps=scenario.max_steps,
                tool_interceptor=interceptor,
            ).run(scenario.goal)
            item = score_fault_scenario(scenario, result)
        except Exception as exc:
            item = {
                "scenario": asdict(scenario),
                "result": {
                    "status": "error",
                    "stop_reason": "evaluation_exception",
                    "answer": "",
                    "events": [],
                    "error": f"{type(exc).__name__}: {exc}",
                },
                "fault_observed": False,
                "behavior_passed": False,
                "completion_passed": False,
                "passed": False,
            }
        scored.append(item)
        run_result = item["result"]
        mark = "PASS" if item["passed"] else "FAIL"
        print(
            f"  {mark} status={run_result.get('status')} "
            f"reason={run_result.get('stop_reason')} steps={len(run_result.get('events', []))}"
        )

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "provider": getattr(model, "provider_name", type(model).__name__),
        "model": getattr(model, "model", type(model).__name__),
        "summary": {
            "total": len(scored),
            "passed": sum(bool(item["passed"]) for item in scored),
            "fault_observed": sum(bool(item["fault_observed"]) for item in scored),
            "behavior_passed": sum(bool(item["behavior_passed"]) for item in scored),
            "completion_passed": sum(bool(item["completion_passed"]) for item in scored),
        },
        "scenarios": scored,
    }


def write_fault_report(report: dict[str, Any], output: str | None = None) -> Path:
    if output:
        path = Path(output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path.cwd() / ".agent_state" / "evaluations" / f"fault_eval_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _mentions_blocker(answer: str) -> bool:
    lowered = answer.lower()
    return any(
        token in lowered
        for token in ("permission", "denied", "cannot", "unable", "权限", "拒绝", "无法", "不能")
    )


def _asks_for_clarification(answer: str) -> bool:
    lowered = answer.lower()
    return "?" in answer or "？" in answer or any(
        token in lowered
        for token in ("which", "clarify", "specify", "哪个", "具体", "请明确", "请提供")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run agent decision and feedback evaluation suites.")
    parser.add_argument("--suite", choices=("decision", "fault"), default="decision")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only this case id; may be repeated.")
    parser.add_argument("--scenario", action="append", dest="scenario_ids", help="Run only this fault scenario id.")
    parser.add_argument("--output", help="Write the JSON report to this path.")
    parser.add_argument("--allow-demo", action="store_true", help="Allow the deterministic demo model for harness checks.")
    args = parser.parse_args()

    model = load_model_from_env()
    if isinstance(model, DemoModel) and not args.allow_demo:
        parser.error(
            "A real model is required. Set AGENT_PROVIDER, API_KEY, MODEL_ID, and BASE_URL, "
            "or pass --allow-demo only to check the evaluation harness."
        )

    if args.suite == "decision":
        if args.scenario_ids:
            parser.error("--scenario requires --suite fault")
        selected_cases = list(CASES)
        if args.case_ids:
            requested = set(args.case_ids)
            selected_cases = [case for case in CASES if case.case_id in requested]
            missing = requested - {case.case_id for case in selected_cases}
            if missing:
                parser.error(f"Unknown case id: {', '.join(sorted(missing))}")
        report = run_evaluation(model, selected_cases)
        path = write_report(report, args.output)
        _print_summary(report, path)
        return

    if args.case_ids:
        parser.error("--case is only valid for --suite decision")
    selected_scenarios = list(FAULT_SCENARIOS)
    if args.scenario_ids:
        requested = set(args.scenario_ids)
        selected_scenarios = [item for item in FAULT_SCENARIOS if item.scenario_id in requested]
        missing = requested - {item.scenario_id for item in selected_scenarios}
        if missing:
            parser.error(f"Unknown scenario id: {', '.join(sorted(missing))}")
    report = run_fault_evaluation(model, selected_scenarios)
    path = write_fault_report(report, args.output)
    summary = report["summary"]
    print(f"\nFault evaluation: {summary['passed']}/{summary['total']}")
    print(f"report: {path}")


if __name__ == "__main__":
    main()
