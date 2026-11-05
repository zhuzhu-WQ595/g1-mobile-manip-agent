from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable

from contracts.robot import ActionStatus, RobotCommand, RobotResult, RobotState

from .safety import validate_command


def _quat_to_heading_deg(x: float, y: float, z: float, w: float) -> float:
    """Convert a quaternion to planar heading in degrees.

    Heading is zero along +x and increases counterclockwise, matching the
    ROS REP-103 planar convention used by ``RobotState``.
    """
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return math.degrees(yaw) % 360.0


class ROS2RobotAdapter:
    """RobotRuntimeAdapter backed by ROS 2 topics.

    Subscribes to ``odom`` and ``scan``, publishes ``Twist`` to ``cmd_vel``.
    Topic names are configurable via environment variables:

    - ``ROS2_CMD_VEL_TOPIC``  (default: ``/cmd_vel``)
    - ``ROS2_ODOM_TOPIC``     (default: ``/odom``)
    - ``ROS2_SCAN_TOPIC``     (default: ``/scan``)
    """

    def __init__(self) -> None:
        try:
            import rclpy
            from geometry_msgs.msg import Twist
            from nav_msgs.msg import Odometry
            from sensor_msgs.msg import LaserScan
        except ImportError as exc:
            raise RuntimeError(
                "rclpy or required message types are not available. "
                "Source ROS 2 setup.bash before using the ros2 adapter."
            ) from exc

        self._rclpy = rclpy
        self._Twist = Twist
        self._Odometry = Odometry
        self._LaserScan = LaserScan

        self._cmd_vel_topic = os.environ.get("ROS2_CMD_VEL_TOPIC", "/cmd_vel")
        self._odom_topic = os.environ.get("ROS2_ODOM_TOPIC", "/odom")
        self._scan_topic = os.environ.get("ROS2_SCAN_TOPIC", "/scan")

        rclpy.init(args=None)
        self._node = rclpy.create_node("ros2_robot_adapter")

        self._lock = threading.Lock()
        self._odom_x = 0.0
        self._odom_y = 0.0
        self._odom_heading_deg = 0.0
        self._odom_received = False
        self._scan_min_range = None
        self._scan_min_all = None
        self._scan_received = False
        self._emergency = False
        self._closed = False

        self._node.create_subscription(
            Odometry, self._odom_topic, self._odom_cb, 10
        )
        self._node.create_subscription(
            LaserScan, self._scan_topic, self._scan_cb, 10
        )
        self._cmd_pub = self._node.create_publisher(Twist, self._cmd_vel_topic, 10)

        self._spin_thread = threading.Thread(
            target=self._spin_loop, name="ros2-adapter-spin", daemon=True
        )
        self._spin_thread.start()

    @property
    def name(self) -> str:
        return "ros2"

    # -- subscriptions callbacks -------------------------------------------

    def _odom_cb(self, msg: object) -> None:
        pos = msg.pose.pose.position
        orient = msg.pose.pose.orientation
        heading = _quat_to_heading_deg(
            orient.x, orient.y, orient.z, orient.w
        )
        with self._lock:
            self._odom_x = pos.x
            self._odom_y = pos.y
            self._odom_heading_deg = heading
            self._odom_received = True

    _scan_count = 0

    def _scan_cb(self, msg: object) -> None:
        ranges = list(msg.ranges)
        n = len(ranges)
        if n == 0:
            with self._lock:
                self._scan_min_range = None
                self._scan_received = True
            return
        angle_min = msg.angle_min
        angle_inc = msg.angle_increment
        # Front sector: ±30 degrees (≈0.524 rad) around forward (angle=0)
        # Wider sector to catch obstacles approaching from diagonal directions
        front_half_angle = 0.524
        front_ranges = []
        all_valid = []
        for i, r in enumerate(ranges):
            angle = angle_min + i * angle_inc
            if math.isfinite(r) and r > 0:
                all_valid.append(r)
            if abs(angle) <= front_half_angle and math.isfinite(r) and r > 0:
                front_ranges.append(r)
        min_front = min(front_ranges) if front_ranges else None
        min_all = min(all_valid) if all_valid else None
        with self._lock:
            self._scan_min_range = min_front
            self._scan_min_all = min_all
            self._scan_received = True
            self._scan_count += 1
            cnt = self._scan_count
        if cnt <= 3 or cnt % 50 == 0:
            print(f"  [lidar] scan#{cnt} front±30°={min_front}m  all={min_all}m  beams={n}")

    def _spin_loop(self) -> None:
        try:
            self._rclpy.spin(self._node)
        except Exception:
            pass

    # -- state -------------------------------------------------------------

    def get_state(self) -> RobotState:
        with self._lock:
            x = self._odom_x
            y = self._odom_y
            heading = self._odom_heading_deg
            front_obstacle = self._scan_min_range
            emergency = self._emergency

        return RobotState(
            mode="ros2",
            battery_percent=100.0,
            x=x,
            y=y,
            heading_deg=heading,
            front_obstacle_m=front_obstacle if front_obstacle is not None else 10.0,
            stopped=True,
            emergency_stopped=emergency,
            last_command="get_state",
        )

    # -- publish helpers ---------------------------------------------------

    def _publish_twist(self, linear_x: float = 0.0, angular_z: float = 0.0) -> None:
        msg = self._Twist()
        msg.linear.x = float(linear_x)
        msg.angular.z = float(angular_z)
        self._cmd_pub.publish(msg)

    def _stop_robot(self) -> None:
        self._publish_twist(0.0, 0.0)

    # -- execute (non-motion) ---------------------------------------------

    def execute(self, command: RobotCommand) -> RobotResult:
        action = command.action

        try:
            validate_command(command, self.get_state())
        except ValueError as exc:
            return RobotResult(
                False,
                "action rejected by ros2 adapter safety",
                self.get_state(),
                action_id=command.action_id,
                status=ActionStatus.FAILED,
                error=str(exc),
            )

        if action == "get_status":
            return self._result(command, True, "status read")
        if action == "stop":
            self._stop_robot()
            return self._result(command, True, "robot stopped")
        if action == "speak":
            return self._result(command, True, f"speak: {command.params.get('text', '')}")
        if action == "capture_image":
            return self._result(
                command,
                True,
                "ros2 camera capture not implemented",
                error="not_implemented",
            )
        if action in {"move", "rotate"}:
            return RobotResult(
                False,
                "motion actions must go through execute_motion",
                self.get_state(),
                action_id=command.action_id,
                status=ActionStatus.FAILED,
                error="use_execute_motion",
            )
        return RobotResult(
            False,
            f"unsupported ros2 action: {action}",
            self.get_state(),
            action_id=command.action_id,
            status=ActionStatus.FAILED,
            error="unsupported_action",
        )

    # -- execute_motion (move / rotate) -----------------------------------

    def execute_motion(
        self,
        command: RobotCommand,
        cancel_event: threading.Event,
        feedback: Callable[[float | None], None],
    ) -> RobotResult:
        action = command.action
        if action not in {"move", "rotate"}:
            return RobotResult(
                False,
                f"execute_motion does not support action: {action}",
                self.get_state(),
                action_id=command.action_id,
                status=ActionStatus.FAILED,
                error="unsupported_action",
            )

        try:
            validate_command(command, self.get_state())
        except ValueError as exc:
            return RobotResult(
                False,
                "action rejected by ros2 adapter safety",
                self.get_state(),
                action_id=command.action_id,
                status=ActionStatus.FAILED,
                error=str(exc),
            )

        with self._lock:
            if self._emergency:
                self._stop_robot()
                return RobotResult(
                    False,
                    "emergency stop is latched; motion is disabled",
                    self.get_state(),
                    action_id=command.action_id,
                    status=ActionStatus.FAILED,
                    error="emergency_stopped",
                )

        speed = abs(float(command.params.get("speed", 0.3)))
        speed = max(speed, 0.05)

        if action == "move":
            return self._do_move(command, cancel_event, feedback, speed)
        return self._do_rotate(command, cancel_event, feedback, speed)

    def _do_move(
        self,
        command: RobotCommand,
        cancel_event: threading.Event,
        feedback: Callable[[float | None], None],
        speed: float,
    ) -> RobotResult:
        distance = abs(float(command.params.get("distance", 0.0)))
        direction = str(command.params.get("direction", "forward"))
        sign = 1.0 if direction == "forward" else -1.0
        target_distance = distance
        linear_x = speed * sign

        start_x, start_y = self._get_odom_pos()
        with self._lock:
            scan_ok = self._scan_received
            scan_val = self._scan_min_range
        print(f"  [move] dist={distance}m dir={direction} speed={speed} pos=({start_x:.2f},{start_y:.2f}) lidar_ready={scan_ok} front={scan_val}")
        self._publish_twist(linear_x, 0.0)
        feedback(0.0)
        started = time.monotonic()

        result = self._poll_motion(
            command,
            cancel_event,
            feedback,
            started,
            target=target_distance,
            progress_fn=lambda traveled: min(0.99, traveled / target_distance) if target_distance > 0 else 1.0,
            measure_fn=lambda: self._distance_since(start_x, start_y),
            done_fn=lambda traveled: traveled >= target_distance,
            check_obstacle=True,
        )

        self._stop_robot()
        return result

    def _do_rotate(
        self,
        command: RobotCommand,
        cancel_event: threading.Event,
        feedback: Callable[[float | None], None],
        speed: float,
    ) -> RobotResult:
        angle = float(command.params.get("angle", 0.0))
        target_angle = abs(angle)
        angular_z = speed if angle >= 0 else -speed

        start_heading = self._get_odom_heading()
        self._publish_twist(0.0, angular_z)
        feedback(0.0)
        started = time.monotonic()

        result = self._poll_motion(
            command,
            cancel_event,
            feedback,
            started,
            target=target_angle,
            progress_fn=lambda turned: min(0.99, turned / target_angle) if target_angle > 0 else 1.0,
            measure_fn=lambda: self._angle_since(start_heading),
            done_fn=lambda turned: turned >= target_angle,
        )

        self._stop_robot()
        return result

    def _poll_motion(
        self,
        command: RobotCommand,
        cancel_event: threading.Event,
        feedback: Callable[[float | None], None],
        started: float,
        target: float,
        progress_fn: Callable[[float], float],
        measure_fn: Callable[[], float],
        done_fn: Callable[[float], bool],
        check_obstacle: bool = False,
    ) -> RobotResult:
        """Poll odom until the motion target is reached, cancelled, or timed out."""
        last_progress = 0.0
        obstacle_stop_threshold = 0.5
        stuck_dist_threshold = 0.02
        stuck_check_interval = 0.5
        last_stuck_check = 0.0
        last_stuck_measured = 0.0
        # Odom-based collision detection: track position change rate
        odom_collision_check_interval = 0.5
        last_odom_check = 0.0
        last_odom_pos = (0.0, 0.0)
        expected_speed = 0.0
        if check_obstacle:
            # Get expected speed from command params
            speed_val = abs(float(command.params.get("speed", 0.2)))
            expected_speed = speed_val
            last_odom_pos = self._get_odom_pos()
        while True:
            if cancel_event.is_set():
                return RobotResult(
                    True,
                    "action cancelled by runtime",
                    self.get_state(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.CANCELLED,
                    error="runtime_cancelled",
                )
            elapsed = time.monotonic() - started
            if elapsed >= command.timeout_s:
                return RobotResult(
                    False,
                    "action timed out",
                    self.get_state(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.TIMED_OUT,
                    progress=last_progress,
                    error="action_timeout",
                )
            with self._lock:
                if self._emergency:
                    return RobotResult(
                        False,
                        "emergency stop during motion",
                        self.get_state(),
                        {"command": command.to_dict()},
                        action_id=command.action_id,
                        status=ActionStatus.FAILED,
                        error="emergency_stopped",
                    )

            if check_obstacle:
                with self._lock:
                    min_front = self._scan_min_range
                    min_all = self._scan_min_all
                    scan_received = self._scan_received
                # Use the minimum of front-sector and all-direction ranges
                # to catch obstacles from any angle near the robot
                effective_min = min(filter(lambda x: x is not None, [min_front, min_all]), default=None)
                if effective_min is not None and effective_min < obstacle_stop_threshold:
                    self._stop_robot()
                    print(f"  [obstacle] lidar front={min_front}m all={min_all}m < {obstacle_stop_threshold}m, stopping!")
                    return RobotResult(
                        False,
                        f"obstacle detected at {effective_min:.2f}m during motion; robot stopped",
                        self.get_state(),
                        {"command": command.to_dict()},
                        action_id=command.action_id,
                        status=ActionStatus.FAILED,
                        progress=last_progress,
                        error="obstacle_detected",
                    )
                if not scan_received and elapsed > 1.0:
                    print(f"  [warning] no lidar scan data received after {elapsed:.1f}s, obstacle detection inactive!")
                elif scan_received and elapsed > 1.0 and effective_min is None:
                    print(f"  [warning] lidar scan received but no valid ranges, obstacle detection inactive!")

                # Odom-based collision detection (fallback when lidar is stale)
                # If robot is moving but position barely changes, it has hit something
                if elapsed - last_odom_check >= odom_collision_check_interval and elapsed > 0.5:
                    cur_pos = self._get_odom_pos()
                    dx = cur_pos[0] - last_odom_pos[0]
                    dy = cur_pos[1] - last_odom_pos[1]
                    actual_dist = math.sqrt(dx * dx + dy * dy)
                    expected_dist = expected_speed * (elapsed - last_odom_check)
                    last_odom_pos = cur_pos
                    last_odom_check = elapsed
                    # If robot moved less than 30% of expected distance, it's likely stuck/collided
                    if expected_dist > 0.01 and actual_dist < expected_dist * 0.3:
                        self._stop_robot()
                        print(f"  [collision] odom-based: expected {expected_dist:.3f}m but moved only {actual_dist:.3f}m in {elapsed - last_odom_check + odom_collision_check_interval:.1f}s, stopping!")
                        return RobotResult(
                            False,
                            f"collision detected: robot moved only {actual_dist:.3f}m out of expected {expected_dist:.3f}m; likely hit an obstacle",
                            self.get_state(),
                            {"command": command.to_dict()},
                            action_id=command.action_id,
                            status=ActionStatus.FAILED,
                            progress=last_progress,
                            error="obstacle_detected",
                        )

            measured = measure_fn()
            if done_fn(measured):
                feedback(1.0)
                return RobotResult(
                    True,
                    f"{command.action} completed",
                    self.get_state(),
                    {"command": command.to_dict()},
                    action_id=command.action_id,
                    status=ActionStatus.SUCCEEDED,
                    progress=1.0,
                )

            if check_obstacle and elapsed - last_stuck_check > stuck_check_interval:
                delta = abs(measured - last_stuck_measured)
                if elapsed > 1.0 and delta < stuck_dist_threshold:
                    self._stop_robot()
                    print(f"  [stuck] elapsed={elapsed:.1f}s measured={measured:.4f} delta={delta:.4f} < {stuck_dist_threshold}, stopping!")
                    return RobotResult(
                        False,
                        f"robot appears stuck (progress stalled at {measured:.3f}m, delta={delta:.4f}m); stopped for safety",
                        self.get_state(),
                        {"command": command.to_dict()},
                        action_id=command.action_id,
                        status=ActionStatus.FAILED,
                        progress=last_progress,
                        error="stuck_detected",
                    )
                if elapsed > 0.5:
                    print(f"  [stuck-check] elapsed={elapsed:.1f}s measured={measured:.4f} delta={delta:.4f}")
                last_stuck_check = elapsed
                last_stuck_measured = measured

            last_progress = progress_fn(measured)
            feedback(last_progress)
            cancel_event.wait(0.05)

    # -- odom helpers ------------------------------------------------------

    def _get_odom_pos(self) -> tuple[float, float]:
        with self._lock:
            return self._odom_x, self._odom_y

    def _get_odom_heading(self) -> float:
        with self._lock:
            return self._odom_heading_deg

    def _distance_since(self, start_x: float, start_y: float) -> float:
        with self._lock:
            dx = self._odom_x - start_x
            dy = self._odom_y - start_y
        return math.hypot(dx, dy)

    def _angle_since(self, start_heading: float) -> float:
        with self._lock:
            current = self._odom_heading_deg
        diff = (current - start_heading) % 360.0
        if diff > 180.0:
            diff = 360.0 - diff
        return diff

    # -- emergency stop ----------------------------------------------------

    def emergency_stop(self) -> RobotResult:
        with self._lock:
            self._emergency = True
        self._stop_robot()
        command = RobotCommand("emergency_stop")
        return RobotResult(
            True,
            "emergency stop latched",
            self.get_state(),
            action_id=command.action_id,
            status=ActionStatus.SUCCEEDED,
        )

    # -- cleanup -----------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._stop_robot()
        try:
            self._node.destroy_node()
        except Exception:
            pass
        try:
            self._rclpy.shutdown()
        except Exception:
            pass

    # -- result helper -----------------------------------------------------

    def _result(
        self,
        command: RobotCommand,
        ok: bool,
        message: str,
        data: dict | None = None,
        error: str | None = None,
    ) -> RobotResult:
        return RobotResult(
            ok,
            message,
            self.get_state(),
            {"command": command.to_dict(), **(data or {})},
            action_id=command.action_id,
            status=ActionStatus.SUCCEEDED if ok else ActionStatus.FAILED,
            progress=1.0 if ok else None,
            error=error,
        )
