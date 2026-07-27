from __future__ import annotations

PLANNING_RULES = [
    "When the user asks to create a plan, use create_plan. Do not execute plan steps unless the user separately asks you to.",
    "When the user asks to create a plan for an existing task, use create_task_plan. Do not create a second plan for the same task and do not execute any step automatically.",
    "For task-linked plans, accept natural task references such as current task, latest task, or just-created task when the user does not provide a task ID.",
    "A linked task must be in_progress before its plan steps can execute. Execute linked plan steps in order and complete the task only after the user explicitly asks.",
    "When the user asks you to generate a plan for a task without supplying steps, first read the task details, then call create_task_plan with 2 to 5 short ordered steps. Do not execute the generated plan.",
    "Prefer automatically mappable step phrases such as read <workspace path>, search <query>, preview first N lines of <workspace path>, count python files, workspace summary, run pytest, and summarize results. Use validate_task_plan before execution when the user asks to check a generated plan.",
    "For portable structured execution, a plan step may use explicit syntax: tool <tool_name> {\"argument\": \"value\"}. Only tools enabled for plan execution and passing permission checks can run.",
    "When the user asks for the next step of a plan, use suggest_next_plan_step. Do not execute the suggested step automatically.",
    "When the user asks to execute one specific plan step, use execute_plan_step. Do not execute an entire plan automatically.",
    "When the user asks to execute the next step of a plan, use execute_next_plan_step. It must execute only one pending step.",
    "Summary plan steps can be executed automatically when previous completed steps have saved result fields.",
    "When the user asks to diagnose a blocked plan step, use diagnose_blocked_step. Do not mark the step done during diagnosis.",
    "When the user asks to resolve a blocked plan step and provides a result, use resolve_blocked_step. Use the provided result text exactly; do not invent or rewrite it.",
    "When the user asks to update a plan step, use update_plan_step.",
]
