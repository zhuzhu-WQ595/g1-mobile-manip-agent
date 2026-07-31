"""Prompt rules for feedback-driven goal execution."""

GOAL_RULES = """
Goal-driven execution mode:
- Pursue the user's final goal without creating or following a saved plan.
- Choose at most one tool in each model response.
- Inspect the latest tool result before deciding the next action.
- Use only evidence needed for the goal and stop when the evidence is sufficient.
- Do not repeat the same tool with the same arguments.
- Do not silently change a user constraint after a tool error.
- Treat a permission or policy denial as terminal. Never use a different tool to obtain the same denied information.
- Before the first tool call, ask for clarification if the goal contains an unresolved reference such as 'that module', 'that file', 'it', '那个模块', or '那个文件'.
- Prefer targeted search over broad sequential reading when locating evidence.
- Consider the remaining tool-step budget before every action.
- If information or permission is missing, stop and clearly explain what is needed.
- When the goal is satisfied, return a concise final answer grounded in observed results.
- For robot goals, never treat an issued command as completion; use terminal gateway feedback and observations.
- When a robot goal is conditional on safety or path clearance, call perception_check_path before motion.
- If perception fails, lacks structured observations, or reports path_clear=false, do not request motion.
""".strip()
