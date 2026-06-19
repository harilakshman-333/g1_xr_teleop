#!/usr/bin/env bash
# docker/viz/start_robot_state.sh
# Starts robot_state_publisher with the G1 URDF read from the mounted volume.
# This script runs inside the g1_robot_state container.
set -e

source /opt/ros/humble/setup.bash

URDF=/opt/xr_teleoperate/assets/g1/g1_body29_hand14.urdf

if [ ! -f "$URDF" ]; then
    echo "[ERROR] URDF not found at $URDF"
    echo "Make sure ./xr_teleoperate is mounted at /opt/xr_teleoperate"
    exit 1
fi

echo "[INFO] Loading URDF: $URDF"
# RViz needs absolute file:/// paths to resolve meshes correctly when loaded from a string param
ROBOT_DESC=$(sed 's|filename="meshes/|filename="file:///opt/xr_teleoperate/assets/g1/meshes/|g' "$URDF")

echo "[INFO] Starting robot_state_publisher..."
exec ros2 run robot_state_publisher robot_state_publisher \
    --ros-args -p robot_description:="$ROBOT_DESC"
