from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable

from contracts.execution import (
    ExecutionError,
    ExecutionRequest,
    ExecutionStatus,
    normalize_execution_status,
)

from ..capabilities import CAPABILITY_REGISTRY
from ..context import build_system_prompt
from ..message_builder import (
    assistant_message,
    assistant_tool_call_message,
    tool_result_message,
    tool_result_text,
    user_message,
)
from ..models import ModelAdapter
from ..robot.policy import check_motion_against_latest_perception
from ..scheduling import DISPATCHER
from ..state.event_log import record_tool_event
from .prompts import GOAL_RULES
from .verification import CompletionVerifier

ROBOT_SYSTEM_PROMPT = """\
You are an autonomous robot control agent.
Your role is to drive a physical or simulated robot through the available tools to reach goals.
You have access to robot status, perception, and motion tools.
You must make decisions based on real-time sensor feedback, not on stored files or prior knowledge.
Do not read files, search code, or explore the workspace. Focus entirely on robot control.
Always reason about the current robot state and sensor data before choosing the next action.
Never assume a map, layout, or obstacle you have not observed through a tool result.
""".strip()

PLANNING_PROMPT = """\
You are planning how a robot should reach the user's goal.

Plan only from the robot state and any observations supplied below. You have no map of the
environment unless one is given; do not invent corridors, rooms, obstacles, or coordinates.
If the goal is a single short motion, the plan may be a single step.
Keep each step expressible with the available motion tools, and prefer verifying with a
perception or status tool before any motion whose path you have not confirmed.

Output ONLY the numbered plan, no other text.
""".strip()

# Opt-in world description for the Gazebo corridor_world scenario. Pass it to
# GoalRunner(world_description=...) when that scenario is actually loaded; it must
# not be assumed for other robots or scenes.
CORRIDOR_WORLD_DESCRIPTION = """\
World map layout (corridor_world):
- The robot starts at approximately (x=0, y=0) facing +x direction.
- A main corridor extends from x=0 to x=3, then forks into three parallel paths (each 3m wide):
  - Path A (y around -2.5): clear, no obstacles. Easiest path.
  - Path B (y around 0.5): has a narrow gap (1.2m) between two obstacles.
  - Path C (y around 3.5): has 5 scattered box obstacles in a zigzag pattern.
- All three paths merge back at x=13 and continue to the endpoint at x=16.
- The robot is 0.8m long and 0.6m wide. It can move at most 1.0m per command and rotate at most 90 degrees per command.
- robot_move has built-in real-time obstacle detection. It will stop automatically if an obstacle is detected.
""".strip()


def _build_goal_system_prompt(messages: list[dict[str, Any]], capability_prompt: str, goal_rules: str, step: int, max_steps: int) -> str:
    remaining = max_steps - step + 1
    return (
        ROBOT_SYSTEM_PROMPT
        + "\n\n"
        + capability_prompt
        + "\n\n"
        + goal_rules
        + f"\n\nTool-step budget: this is step {step} of {max_steps}; "
        f"{remaining} tool step(s) remain."
    )


MOBILE_MANIP_GOAL_TOOLS = frozenset(
    {
        "slam_get_pose",
        "nav_list_places",
        "nav_go_to_place",
        "vla_run_skill",
        "vision_verify",
        "robot_speak",
        "robot_get_status",
        "robot_stop",
        "robot_emergency_stop",
    }
)

MOBILE_MANIP_RULES = """\
Mobile manipulation mission mode:
- Tools: slam_get_pose (localization), nav_list_places (semantic map), nav_go_to_place (SLAM navigation),
  vla_run_skill (manipulation policy, ONE atomic skill per call, English instruction),
  vision_verify (scene camera + visual QA; use it to confirm a manipulation or final task result).
- Only use place names returned by nav_list_places. Navigate before any manipulation; the VLA only works within arm reach.
- Decompose the request into atomic skills, e.g. 'open the fridge door', 'pick up the apple', 'close the fridge door'.
- After every step read the result. If ok=false, use the error and message to recover (re-navigate, retry the skill once with a
  rephrased instruction) or stop and report the blocker. Never repeat an identical failing call.
- If the request says to return to a place, finish with nav_go_to_place to that place and confirm with slam_get_pose.
- Final answer: concise, based only on tool results, state whether the mission succeeded.
""".strip()

DEFAULT_GOAL_TOOLS = frozenset(
    {
        "list_files",
        "read_file",
        "search_files",
        "preview_file_head",
        "get_workspace_summary",
        "count_files_by_extension",
        "read_memory",
        "list_tasks",
        "get_task_details",
        "list_skills",
        "read_skill",
        "list_plans",
    }
)

ROBOT_GOAL_TOOLS = frozenset(
    {
        "robot_get_status",
        "robot_move",
        "robot_rotate",
        "robot_stop",
        "robot_get_action_status",
        "robot_cancel_action",
        "robot_emergency_stop",
        "robot_speak",
        "robot_capture_image",
        "perception_observe",
        "perception_check_path",
        "duck_walk",
        "duck_stop",
        "duck_sit",
        "duck_kick",
        "duck_roulade",
        "duck_ground_pick",
        "duck_head",
        "duck_body_pose",
    }
)


@dataclass(frozen=True)
class ToolInterception:
    result: str
    status: str = "error"
    reason: str = "injected feedback"


ToolInterceptor = Callable[[int, str, dict[str, Any]], ToolInterception | None]


class GoalRunner:
    def __init__(
        self,
        model: ModelAdapter,
        max_steps: int = 8,
        tool_names: Iterable[str] = DEFAULT_GOAL_TOOLS,
        tool_interceptor: ToolInterceptor | None = None,
        completion_verifier: CompletionVerifier | None = None,
        world_description: str | None = None,
        goal_rules: str = GOAL_RULES,
    ) -> None:
        self.goal_rules = goal_rules
        self.model = model
        self.max_steps = max_steps
        self.tool_names = frozenset(tool_names)
        self.tool_interceptor = tool_interceptor
        self.completion_verifier = completion_verifier
        self.world_description = (world_description or "").strip() or None
        known_tools = {capability.tool_name for capability in CAPABILITY_REGISTRY.all()}
        unknown = self.tool_names - known_tools
        if unknown:
            raise ValueError(f"Unknown goal tools: {', '.join(sorted(unknown))}")
        self.tool_schemas = CAPABILITY_REGISTRY.schemas_for_names(self.tool_names)
        self.capability_prompt = CAPABILITY_REGISTRY.prompt_summary(
            CAPABILITY_REGISTRY.get(name) for name in self.tool_names
        )

    def run(self, goal: str) -> dict[str, Any]:
        clean_goal = goal.strip()
        if not clean_goal:
            raise ValueError("goal cannot be empty")

        run_id = "goal_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        messages: list[dict[str, Any]] = [user_message(clean_goal)]
        events: list[dict[str, Any]] = []
        preflight: list[dict[str, Any]] = []
        verifications: list[dict[str, Any]] = []
        seen_calls: set[str] = set()

        # Phase 1: Get initial robot state
        status_result = ""
        status_tool = (
            "slam_get_pose" if "slam_get_pose" in self.tool_names
            else "robot_get_status" if "robot_get_status" in self.tool_names
            else ""
        )
        if status_tool:
            print("> phase 1: acquiring initial robot state")
            status_request = ExecutionRequest(
                capability=f"robot.{status_tool}",
                execution_target="robot_gateway",
                arguments={},
                metadata={"run_id": run_id, "phase": "initial_status"},
            )
            try:
                status_event = DISPATCHER.dispatch(status_request)
                status_result = tool_result_text(status_event.result)
            except Exception as exc:
                status_result = f"ERROR: {type(exc).__name__}: {exc}"
                status_event = status_request.event(
                    ExecutionStatus.FAILED,
                    result=status_result,
                    error=ExecutionError.from_exception(exc),
                )
            status_detail = {**status_event.to_dict(), "mode": "goal", "run_id": run_id, "phase": "initial_status", "tool": status_tool, "arguments": {}}
            preflight.append(status_detail)
            record_tool_event(status_detail)
            if status_tool == "slam_get_pose" and "nav_list_places" in self.tool_names:
                try:
                    places_event = DISPATCHER.dispatch(
                        ExecutionRequest(
                            capability="robot.nav_list_places",
                            execution_target="robot_gateway",
                            arguments={},
                            metadata={"run_id": run_id, "phase": "initial_places"},
                        )
                    )
                    status_result += "\nKnown places: " + tool_result_text(places_event.result)
                except Exception as exc:
                    status_result += f"\nKnown places unavailable: {type(exc).__name__}: {exc}"
            print(f"  initial state: {status_result[:200]}")

        # Phase 2: Generate navigation plan
        if status_tool and status_result:
            print("> phase 2: generating navigation plan")
            plan_prompt = PLANNING_PROMPT
            if self.world_description:
                plan_prompt += f"\n\n{self.world_description}"
            plan_prompt += f"\n\nCurrent robot state:\n{status_result}\n\nUser goal:\n{clean_goal}"
            plan_messages = [user_message(plan_prompt)]
            try:
                plan_response = self.model.complete(plan_messages, [], system_prompt=ROBOT_SYSTEM_PROMPT)
                if plan_response.get("type") == "message":
                    plan_text = str(plan_response.get("text", "")).strip()
                else:
                    plan_text = ""
            except Exception as exc:
                print(f"  planning failed ({type(exc).__name__}: {exc})")
                plan_text = ""
            if plan_text:
                print("  navigation plan:")
                for line in plan_text.split("\n"):
                    print(f"    {line}")
                messages.append(assistant_message(plan_text))
                messages.append(user_message(
                    "Now execute this plan step by step using the available tools. "
                    "After each action, check the result and decide the next step. "
                    "If an action fails or an obstacle is detected, adjust the plan accordingly. "
                    "Continue until the goal is achieved or you determine it is impossible."
                ))
            else:
                print("  no plan produced; executing directly from the goal")

        # Phase 3: Execute tools following the plan
        for step in range(1, self.max_steps + 1):
            prompt = _build_goal_system_prompt(messages, self.capability_prompt, self.goal_rules, step, self.max_steps)
            try:
                response = self.model.complete(messages, self.tool_schemas, system_prompt=prompt)
            except Exception as exc:
                reason = f"The model request failed at step {step}: {type(exc).__name__}: {exc}"
                print(f"  {reason}")
                return self._result(
                    run_id, clean_goal, "blocked", "model_unavailable", reason, events, verifications, preflight
                )
            if response.get("type") == "message":
                answer = str(response.get("text", "")).strip()
                messages.append(assistant_message(answer))
                if self.completion_verifier is None:
                    return self._result(
                        run_id, clean_goal, "completed", "model_finished", answer, events, verifications, preflight
                    )
                verification = self.completion_verifier(clean_goal, answer, events)
                verifications.append(
                    {
                        "attempt": len(verifications) + 1,
                        "achieved": verification.achieved,
                        "reason": verification.reason,
                        "source": verification.source,
                    }
                )
                if verification.achieved:
                    return self._result(
                        run_id, clean_goal, "completed", "feedback_verified", answer, events, verifications, preflight
                    )
                if not verification.retryable or len(verifications) >= 2 or step == self.max_steps:
                    return self._result(
                        run_id,
                        clean_goal,
                        "blocked",
                        "completion_unverified",
                        verification.reason,
                        events,
                        verifications,
                        preflight,
                    )
                messages.append(
                    user_message(
                        "Completion verifier rejected the proposed answer: "
                        + verification.reason
                        + " Continue from the latest feedback. Do not repeat a completed action."
                    )
                )
                continue

            calls = list(response.get("tool_calls", []))
            if not calls:
                answer = self._finish(messages, "No tool call or final answer was produced.")
                return self._result(
                    run_id, clean_goal, "blocked", "empty_model_action", answer, events, verifications, preflight
                )

            call = calls[0]
            name = str(call.get("name", ""))
            arguments = call.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            signature = json.dumps({"tool": name, "arguments": arguments}, ensure_ascii=False, sort_keys=True)
            if (
                signature in seen_calls
                and not _can_repeat_status_poll(name, arguments, events)
                and _is_blocked_repeat(signature, events)
            ):
                reason = f"The model repeated {name} with unchanged arguments, so execution stopped."
                answer = self._finish(messages, reason)
                return self._result(
                    run_id, clean_goal, "blocked", "repeated_action", answer, events, verifications, preflight
                )
            seen_calls.add(signature)

            selected_call = {
                "id": str(call.get("id") or f"goal_call_{step}"),
                "name": name,
                "arguments": arguments,
            }
            messages.append(assistant_tool_call_message([selected_call], response.get("reasoning_content")))

            capability = None
            try:
                capability = CAPABILITY_REGISTRY.get(name)
            except KeyError:
                pass
            request = ExecutionRequest(
                capability=capability.name if capability is not None else f"unknown.{name}",
                execution_target=(
                    capability.execution_target.value if capability is not None else "unknown"
                ),
                arguments=arguments,
                metadata={"run_id": run_id, "step": step},
            )
            event_details: dict[str, Any] = {
                "mode": "goal",
                "run_id": run_id,
                "step": step,
                "tool": name,
                "arguments": arguments,
                "proposed_tool_calls": len(calls),
            }
            print(f"> step {step}: {name} {arguments}")
            try:
                if name not in self.tool_names:
                    raise PermissionError(f"Tool is not enabled in goal mode: {name}")
                check_motion_against_latest_perception(name, arguments, events)
                interception = (
                    self.tool_interceptor(step, name, arguments)
                    if self.tool_interceptor is not None
                    else None
                )
                if interception is not None:
                    result = interception.result
                    execution_status = normalize_execution_status(interception.status)
                    error = (
                        ExecutionError(
                            code="injected_feedback",
                            message=result,
                            retryable=True,
                            details={"reason": interception.reason},
                        )
                        if execution_status is ExecutionStatus.FAILED
                        else None
                    )
                    execution_event = request.event(
                        execution_status,
                        result=result,
                        error=error,
                    )
                    event_details["injected"] = True
                    event_details["injection_reason"] = interception.reason
                else:
                    execution_event = DISPATCHER.dispatch(request)
                    result = tool_result_text(execution_event.result)
            except Exception as exc:
                result = f"ERROR: {type(exc).__name__}: {exc}"
                execution_event = request.event(
                    ExecutionStatus.FAILED,
                    result=result,
                    error=ExecutionError.from_exception(exc),
                )
            event = {**execution_event.to_dict(), **event_details}
            events.append(event)
            record_tool_event(event)
            messages.append(tool_result_message(selected_call["id"], name, result))
            if event["status"] == ExecutionStatus.FAILED.value and _is_permission_denial(str(result)):
                answer = self._finish(
                    messages,
                    "A permission or policy denial is terminal; alternate tools must not be used to bypass it.",
                )
                return self._result(
                    run_id, clean_goal, "blocked", "permission_denied", answer, events, verifications, preflight
                )

        answer = self._finish(
            messages,
            f"The execution budget of {self.max_steps} tool steps was exhausted.",
        )
        return self._result(
            run_id, clean_goal, "max_steps", "step_budget_exhausted", answer, events, verifications, preflight
        )

    def _finish(self, messages: list[dict[str, Any]], reason: str) -> str:
        prompt = ROBOT_SYSTEM_PROMPT + "\n\n" + self.goal_rules + (
            "\n\nExecution has stopped: " + reason
            + " Summarize verified evidence, state whether the goal was achieved, and explain any blocker. "
            "Do not claim that another tool was executed."
        )
        try:
            response = self.model.complete(messages, [], system_prompt=prompt)
        except Exception as exc:
            return f"{reason} (summary unavailable: {type(exc).__name__}: {exc})"
        if response.get("type") == "message":
            text = str(response.get("text", "")).strip()
            if text and not _looks_like_tool_request(text):
                return text
        return reason

    @staticmethod
    def _result(
        run_id: str,
        goal: str,
        status: str,
        stop_reason: str,
        answer: str,
        events: list[dict[str, Any]],
        verifications: list[dict[str, Any]] | None = None,
        preflight: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "goal": goal,
            "status": status,
            "stop_reason": stop_reason,
            "answer": answer,
            "steps_executed": len(events),
            "events": events,
            "preflight": preflight or [],
            "verifications": verifications or [],
        }


def _looks_like_tool_request(text: str) -> bool:
    lowered = text.lower()
    return "dsml" in lowered or "<|tool" in lowered or "tool_calls>" in lowered


def _is_permission_denial(result: str) -> bool:
    lowered = result.lower()
    return "permissionerror" in lowered or "permission denied" in lowered or "policy denial" in lowered


def _can_repeat_status_poll(
    name: str,
    arguments: dict[str, Any],
    events: list[dict[str, Any]],
) -> bool:
    if name == "robot_get_action_status":
        for event in reversed(events):
            if event.get("tool") != name or event.get("arguments") != arguments:
                continue
            try:
                feedback = json.loads(str(event.get("result", "")))
            except (json.JSONDecodeError, TypeError):
                return False
            return isinstance(feedback, dict) and feedback.get("status") in {"pending", "running"}
    if name in {"robot_get_status", "slam_get_pose", "vision_verify", "perception_observe", "perception_check_path", "robot_move", "robot_rotate"}:
        return True
    return False


def _is_blocked_repeat(signature: str, events: list[dict[str, Any]]) -> bool:
    """Whether re-invoking an identical call should stop the run.

    Revisiting a place (e.g. nav back to the kitchen to close the fridge) is a
    legitimate pattern, so a repeat is only blocked when it is a consecutive
    duplicate of the previous call or a retry of an identical call that failed.
    """
    if not events:
        return True
    last_sig = json.dumps(
        {"tool": events[-1].get("tool"), "arguments": events[-1].get("arguments")},
        ensure_ascii=False,
        sort_keys=True,
    )
    if last_sig == signature:
        return True
    previous = None
    for event in events:
        event_sig = json.dumps(
            {"tool": event.get("tool"), "arguments": event.get("arguments")},
            ensure_ascii=False,
            sort_keys=True,
        )
        if event_sig == signature:
            previous = event
    if previous is None:
        return True
    result = str(previous.get("result") or "")
    status = str(previous.get("status") or "")
    return '"ok": false' in result or result.startswith("ERROR") or status == "failed"
