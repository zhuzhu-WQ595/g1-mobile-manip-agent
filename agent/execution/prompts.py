"""Prompt rules for feedback-driven goal execution."""

GOAL_RULES = """
Goal-driven execution mode:
- A macro-level navigation plan has been generated above. Execute it by calling robot_move repeatedly.
- The plan describes segments like "move forward 3m" but robot_move only accepts 1.0m per command. You must auto-split: to move 3m, call robot_move 3 times with distance=1.0.
- robot_move has built-in real-time obstacle detection via lidar. If an obstacle is detected during motion, the robot stops automatically and the move returns FAILED with error="obstacle_detected" or "stuck_detected".
- Keep moving forward according to the plan. Do NOT call robot_get_status between every move — just keep issuing robot_move commands until you've covered the planned distance or a move fails.
- Only call robot_get_status when:
  1. A move failed — to check position and front_obstacle_m.
  2. You've completed a turning maneuver and want to verify orientation.
  3. You believe you're near the endpoint.
- If a move fails:
  1. Call robot_get_status to check current position and front_obstacle_m.
  2. Rotate 90 degrees left or right to find a clear direction.
  3. Move forward in the new direction. If that also fails, rotate again.
- The robot can move at most 1.0m per command and rotate at most 90 degrees per command.
- Do not stop after a single move. Continue executing until the goal is reached (x > 15m) or a blocker is confirmed.
- When the goal is satisfied, return a concise final answer.
- Do not read files, search code, or use any workspace tools. Focus entirely on robot navigation.

World map layout (corridor_world):
- The robot starts at approximately (x=0, y=0) facing +x direction.
- A main corridor extends from x=0 to x=3, then forks into three parallel paths (each 3m wide):
  - Path A (y around -2.5): clear, no obstacles. Easiest path.
  - Path B (y around 0.5): has a narrow gap (1.2m) between two obstacles.
  - Path C (y around 3.5): has 5 scattered box obstacles in a zigzag pattern.
- All three paths merge back at x=13 and continue to the endpoint at x=16.
- The robot MUST rotate and choose a path before reaching x=3 (the fork).
- front_obstacle_m in robot_get_status is the minimum distance to obstacles in the forward ±15° sector.

Navigation strategy:
1. Move forward along the main corridor until approaching the fork (x ≈ 2-3m).
2. When a move fails or front_obstacle_m is small, rotate right 90° to face Path A (y ≈ -2.5).
3. Move forward 2-3m to enter Path A, then rotate left 90° to face +x again.
4. Continue moving forward through Path A until reaching the merge point (x ≈ 13m).
5. Continue forward to the endpoint (x ≈ 16m).
6. If blocked at any point, use sensor data to find an alternate direction.
""".strip()
