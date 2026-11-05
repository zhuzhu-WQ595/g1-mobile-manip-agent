#!/bin/bash
# 一键清理并重启 Gazebo 仿真环境
echo "=== 清理旧进程 ==="
pkill -f 'ign gazebo' 2>/dev/null
pkill -f 'parameter_bridge' 2>/dev/null
pkill -f 'ros_gz' 2>/dev/null
pkill -f 'corridor_sim' 2>/dev/null
sleep 2

if pgrep -f 'ign gazebo' >/dev/null; then
    echo "警告: Gazebo 进程仍未终止，强制杀掉"
    pkill -9 -f 'ign gazebo'
    sleep 1
fi

echo "=== 清理端口 ==="
fuser -k 9000/tcp 2>/dev/null
fuser -k 9030/tcp 2>/dev/null

echo "=== 启动 Gazebo ==="
source /opt/ros/humble/setup.bash
source ~/robot_ws/install/setup.bash
ros2 launch self_test_sim corridor_sim.launch.py
