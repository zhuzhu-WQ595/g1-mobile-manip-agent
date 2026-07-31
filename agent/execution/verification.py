from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from contracts.execution import ExecutionStatus, normalize_execution_status

from ..message_builder import user_message
from ..models import ModelAdapter


@dataclass(frozen=True)
class CompletionVerification:
    achieved: bool
    reason: str
    retryable: bool = True
    source: str = "structural_gate"


CompletionVerifier = Callable[[str, str, list[dict[str, Any]]], CompletionVerification]


class RobotFeedbackVerifier:
    """Verify terminal gateway evidence, then optionally judge goal semantics."""

    MOTION_TOOLS = {"robot_move", "robot_rotate", "robot_stop"}

    def __init__(self, critic_model: ModelAdapter | None = None) -> None:
        self.critic_model = critic_model

    def __call__(
        self,
        goal: str,
        answer: str,
        events: list[dict[str, Any]],
    ) -> CompletionVerification:
        robot_events = [event for event in events if str(event.get("tool", "")).startswith("robot_")]
        if not robot_events:
            perception_events = [
                event for event in events if str(event.get("tool", "")).startswith("perception_")
            ]
            if perception_events and _is_conditional_motion_goal(goal):
                latest = perception_events[-1]
                observation = latest.get("observation")
                if (
                    normalize_execution_status(str(latest.get("status", "failed")))
                    is ExecutionStatus.SUCCEEDED
                    and isinstance(observation, dict)
                    and observation.get("path_clear") is False
                ):
                    return CompletionVerification(
                        True,
                        "Perception reported a blocked path, so conditional motion was correctly withheld.",
                        retryable=False,
                        source="perception_gate",
                    )
            return CompletionVerification(False, "No robot observation or action feedback was collected.")

        latest_feedback: dict[str, tuple[str, dict[str, Any]]] = {}
        critic_evidence: list[dict[str, Any]] = []
        last_failure = "No successful terminal robot feedback was found."
        for index, event in enumerate(robot_events):
            tool = str(event.get("tool", ""))
            if normalize_execution_status(str(event.get("status", "failed"))) is not ExecutionStatus.SUCCEEDED:
                critic_evidence.append(
                    {
                        "step": event.get("step"),
                        "tool": tool,
                        "arguments": event.get("arguments", {}),
                        "tool_status": event.get("status"),
                        "error": str(event.get("result", "")),
                    }
                )
                last_failure = f"{tool} did not return a successful tool result."
                continue
            try:
                feedback = json.loads(str(event.get("result", "")))
            except (json.JSONDecodeError, TypeError):
                return CompletionVerification(False, f"{tool} returned unstructured feedback.")
            if not isinstance(feedback, dict):
                return CompletionVerification(False, f"{tool} feedback is not a JSON object.")

            critic_evidence.append(
                {
                    "step": event.get("step"),
                    "tool": tool,
                    "arguments": event.get("arguments", {}),
                    "feedback": feedback,
                }
            )
            action_id = str(feedback.get("action_id", "")).strip()
            key = action_id or f"event_{index}"
            effective_tool = tool
            if tool == "robot_get_action_status" and action_id in latest_feedback:
                effective_tool = latest_feedback[action_id][0]
            latest_feedback[key] = (effective_tool, feedback)

        successful_receipts = 0
        for tool, feedback in latest_feedback.values():
            status = str(feedback.get("status", ""))
            if status in {"pending", "running"}:
                return CompletionVerification(
                    False,
                    f"{tool} is still {status}; query its action status before claiming completion.",
                )
            if not bool(feedback.get("ok", False)):
                last_failure = f"{tool} failed: {feedback.get('error') or feedback.get('message')}"
                continue
            if status == "cancelled" and tool != "robot_cancel_action":
                last_failure = f"{tool} was cancelled rather than completed."
                continue
            if status not in {"succeeded", "cancelled"}:
                last_failure = f"{tool} has unsupported terminal status: {status}."
                continue

            state = feedback.get("state")
            if tool in self.MOTION_TOOLS:
                if not isinstance(state, dict):
                    return CompletionVerification(False, f"{tool} has no resulting robot state.")
                if state.get("stopped") is not True:
                    return CompletionVerification(False, f"{tool} did not confirm a stopped terminal state.")
            if tool == "robot_emergency_stop":
                if not isinstance(state, dict) or state.get("emergency_stopped") is not True:
                    return CompletionVerification(False, "Emergency stop was not confirmed by robot state.")
            if tool == "robot_capture_image":
                data = feedback.get("data")
                if not isinstance(data, dict) or not data.get("frame"):
                    return CompletionVerification(False, "Camera feedback does not contain a frame reference.")
            successful_receipts += 1

        if successful_receipts == 0:
            return CompletionVerification(False, last_failure)
        if self.critic_model is None:
            return CompletionVerification(
                True,
                "Structured terminal robot feedback supports completion.",
                retryable=False,
                source="structured_feedback",
            )
        return self._semantic_check(goal, answer, critic_evidence)

    def _semantic_check(
        self,
        goal: str,
        answer: str,
        evidence: list[dict[str, Any]],
    ) -> CompletionVerification:
        system_prompt = """
Robot completion critic.
Judge only whether the supplied execution evidence proves that the user's goal was achieved.
Treat tool arguments as intended actions and gateway feedback/state as execution evidence.
Do not assume an action succeeded without terminal evidence. Do not execute tools.
Return exactly one JSON object with this schema:
{"achieved": true, "reason": "short evidence-based reason", "recommended_next_step": ""}
Set achieved=false when evidence is insufficient, parameters do not match the goal, or observations contradict completion.
When achieved=false, recommended_next_step should name the smallest additional action or observation needed.
""".strip()
        payload = json.dumps(
            {"goal": goal, "proposed_answer": answer, "execution_evidence": evidence},
            ensure_ascii=False,
        )
        response = self.critic_model.complete([user_message(payload)], [], system_prompt=system_prompt)
        if response.get("type") != "message":
            return CompletionVerification(
                False,
                "Semantic critic did not return a final JSON decision.",
                source="semantic_critic",
            )
        decision = _parse_json_object(str(response.get("text", "")))
        if decision is None or not isinstance(decision.get("achieved"), bool):
            return CompletionVerification(False, "Semantic critic returned invalid JSON.", source="semantic_critic")
        reason = str(decision.get("reason", "")).strip() or "Semantic critic provided no reason."
        next_step = str(decision.get("recommended_next_step", "")).strip()
        if not decision["achieved"] and next_step:
            reason += f" Recommended next step: {next_step}"
        return CompletionVerification(
            achieved=decision["achieved"],
            reason=reason,
            retryable=not decision["achieved"],
            source="semantic_critic",
        )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _is_conditional_motion_goal(goal: str) -> bool:
    lowered = goal.lower()
    return any(
        marker in lowered
        for marker in ("only if", "if clear", "if safe", "如果安全", "路径安全", "安全才")
    )
