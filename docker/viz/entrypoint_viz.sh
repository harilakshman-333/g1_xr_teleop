#!/usr/bin/env bash
# =============================================================================
# docker/viz/entrypoint_viz.sh
# Entrypoint for the G1 XR Teleop visualization container.
# Sources ROS 2 Humble + optional unitree_ws overlay, then runs the command.
# =============================================================================
set -e

# Source ROS 2 Humble
source /opt/ros/humble/setup.bash

# Source the Unitree ROS2 workspace overlay if it was successfully built
if [ -f /opt/unitree_ws/install/setup.bash ]; then
    source /opt/unitree_ws/install/setup.bash
fi

# Use CycloneDDS as the RMW implementation (matches the teleoperation container)
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

exec "$@"
