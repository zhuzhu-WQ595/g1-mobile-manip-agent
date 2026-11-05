#!/bin/bash
# Start the MicroDuck agent integration system.
#
# This script launches two services:
# 1. MuJoCo simulation with HTTP bridge (in microduck_rl)
# 2. self-test agent gateway (in self-test)
#
# Usage:
#   ./scripts/start_microduck.sh
#
# Prerequisites:
#   - microduck_rl repo at ~/microduck_rl with ONNX policies
#   - self-test repo at ~/桌面/self-test
#   - DeepSeek API key set in .env (AGENT_PROVIDER=deepseek, DEEPSEEK_API_KEY=...)
#
# The MuJoCo viewer window will open. The agent listens on port 9000.
# The bridge listens on port 9001.

set -e

MICRODUCK_DIR="${MICRODUCK_DIR:-$HOME/microduck_rl}"
SELFTEST_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_PORT="${BRIDGE_PORT:-9001}"
GATEWAY_PORT="${GATEWAY_PORT:-9000}"
PERCEPTION_PORT="${PERCEPTION_PORT:-9030}"
PERCEPTION_SCENE="${PERCEPTION_SCENE:-clear}"

# Default policies — override any of these with an env var, or set to "" to skip.
WALKING_POLICY="${WALKING_POLICY-$MICRODUCK_DIR/my_walk_final.onnx}"
STANDING_POLICY="${STANDING_POLICY-$MICRODUCK_DIR/alpha_stand.onnx}"
SITSTAND="${SITSTAND-$MICRODUCK_DIR/alpha_sitstand.onnx}"
KICK_LEFT="${KICK_LEFT-$MICRODUCK_DIR/ball_kick_left.onnx}"
KICK_RIGHT="${KICK_RIGHT-$MICRODUCK_DIR/ball_kick_right.onnx}"
ROULADE="${ROULADE-$MICRODUCK_DIR/roulade.onnx}"
GROUND_PICK="${GROUND_PICK-$MICRODUCK_DIR/alpha_ground_pick.onnx}"

echo "=== MicroDuck Agent Integration ==="
echo "  microduck_rl: $MICRODUCK_DIR"
echo "  self-test:    $SELFTEST_DIR"
echo "  bridge port:  $BRIDGE_PORT"
echo "  gateway port: $GATEWAY_PORT"
echo ""

# Build the infer_policy.py command
INFER_ARGS="--bridge --bridge-port $BRIDGE_PORT --new-cmd-obs --walking $WALKING_POLICY"
if [ -n "$STANDING_POLICY" ]; then
    INFER_ARGS="$INFER_ARGS --standing $STANDING_POLICY"
fi

# Add optional policies if they exist
for policy_var in KICK_LEFT KICK_RIGHT ROULADE GROUND_PICK SITSTAND; do
    policy_path="${!policy_var:-}"
    flag="--$(echo $policy_var | sed 's/_/-/' | tr '[:upper:]' '[:lower:]')"
    if [ -n "$policy_path" ] && [ -f "$policy_path" ]; then
        INFER_ARGS="$INFER_ARGS $flag $policy_path"
    fi
done

echo "Starting MuJoCo simulation with bridge..."
echo "  cd $MICRODUCK_DIR && uv run python scripts/infer_policy.py $INFER_ARGS"
echo ""

# Start the MuJoCo sim with bridge in the background
cd "$MICRODUCK_DIR"
uv run python scripts/infer_policy.py $INFER_ARGS &
SIM_PID=$!

# Wait for bridge to be ready
echo "Waiting for bridge to start..."
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:$BRIDGE_PORT/health > /dev/null 2>&1; then
        echo "Bridge is ready."
        break
    fi
    sleep 1
done

# Start the self-test agent gateway
echo ""
echo "Starting self-test agent gateway..."
cd "$SELFTEST_DIR"
ROBOT_RUNTIME_ADAPTER=microduck ROBOT_PORT=$GATEWAY_PORT \
    python3 -m robot_runtime.gateway_server &
GATEWAY_PID=$!

# Start the perception service. The motion safety gate refuses to move unless a
# perception check has confirmed a clear path, so this must be reachable.
echo "Starting perception service..."
python3 -m services.perception --port "$PERCEPTION_PORT" --scene "$PERCEPTION_SCENE" &
PERCEPTION_PID=$!

echo ""
echo "=== System is running ==="
echo "  MuJoCo sim PID:     $SIM_PID"
echo "  Gateway PID:        $GATEWAY_PID"
echo "  Perception PID:     $PERCEPTION_PID"
echo "  Bridge:     http://127.0.0.1:$BRIDGE_PORT/health"
echo "  Gateway:    http://127.0.0.1:$GATEWAY_PORT/robot/state"
echo "  Perception: http://127.0.0.1:$PERCEPTION_PORT (scene=$PERCEPTION_SCENE)"
echo ""
echo "To control via agent:"
echo "  cd $SELFTEST_DIR && PYTHONPATH=. python3 -m agent.main"
echo ""
echo "Press Ctrl+C to stop all services."

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $PERCEPTION_PID 2>/dev/null || true
    kill $GATEWAY_PID 2>/dev/null || true
    kill $SIM_PID 2>/dev/null || true
    wait
    echo "Done."
}

trap cleanup EXIT INT TERM

# Wait for either process to exit
wait
