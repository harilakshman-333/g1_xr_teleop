#!/usr/bin/env python3
"""
docker/viz/dds_joint_relay.py
──────────────────────────────
Subscribes to the Unitree G1's live DDS LowState topic on the robot network
and re-publishes the 14 arm joint positions as a ROS 2 JointState message
on /joint_states at 30 Hz so RViz can visualize them in real time.

This runs inside the g1_viz Docker container which uses host networking,
giving it direct access to the same CycloneDDS multicast traffic that the
teleoperation script uses.

Usage (auto-started by docker compose):
    python3 /workspace/dds_joint_relay.py [--interface eno2]
"""

import argparse
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

# ── Unitree SDK ────────────────────────────────────────────────────────────────
try:
    from unitree_sdk2py.core.channel import (
        ChannelFactoryInitialize,
        ChannelSubscriber,
    )
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    TOPIC_LOWSTATE = "rt/lowstate"
except ImportError:
    # Fallback to unitree_go LowState (older SDK versions)
    try:
        from unitree_sdk2py.core.channel import (
            ChannelFactoryInitialize,
            ChannelSubscriber,
        )
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_
        TOPIC_LOWSTATE = "rt/lowstate"
    except ImportError:
        print("ERROR: unitree_sdk2py not found. Cannot subscribe to DDS.")
        sys.exit(1)

# ── G1 29-DoF arm joint indices in the LowState motor_state array ─────────────
# These match the mapping used in robot_arm.py / teleop_hand_and_arm.py
# ── G1 29-DoF body joint indices in the LowState motor_state array ─────────────
# These match the mapping used in robot_arm.py / teleop_hand_and_arm.py
BODY_JOINT_MAPPING = [
    ("left_hip_pitch_joint", 0),
    ("left_hip_roll_joint", 1),
    ("left_hip_yaw_joint", 2),
    ("left_knee_joint", 3),
    ("left_ankle_pitch_joint", 4),
    ("left_ankle_roll_joint", 5),
    
    ("right_hip_pitch_joint", 6),
    ("right_hip_roll_joint", 7),
    ("right_hip_yaw_joint", 8),
    ("right_knee_joint", 9),
    ("right_ankle_pitch_joint", 10),
    ("right_ankle_roll_joint", 11),
    
    ("waist_yaw_joint", 12),
    ("waist_roll_joint", 13),
    ("waist_pitch_joint", 14),
    
    ("left_shoulder_pitch_joint", 15),
    ("left_shoulder_roll_joint", 16),
    ("left_shoulder_yaw_joint", 17),
    ("left_elbow_joint", 18),
    ("left_wrist_roll_joint", 19),
    ("left_wrist_pitch_joint", 20),
    ("left_wrist_yaw_joint", 21),
    
    ("right_shoulder_pitch_joint", 22),
    ("right_shoulder_roll_joint", 23),
    ("right_shoulder_yaw_joint", 24),
    ("right_elbow_joint", 25),
    ("right_wrist_roll_joint", 26),
    ("right_wrist_pitch_joint", 27),
    ("right_wrist_yaw_joint", 28),
]

HAND_JOINT_NAMES = [
    "left_hand_thumb_0_joint",
    "left_hand_thumb_1_joint",
    "left_hand_thumb_2_joint",
    "left_hand_middle_0_joint",
    "left_hand_middle_1_joint",
    "left_hand_index_0_joint",
    "left_hand_index_1_joint",
    
    "right_hand_thumb_0_joint",
    "right_hand_thumb_1_joint",
    "right_hand_thumb_2_joint",
    "right_hand_middle_0_joint",
    "right_hand_middle_1_joint",
    "right_hand_index_0_joint",
    "right_hand_index_1_joint",
]

JOINT_NAMES = [item[0] for item in BODY_JOINT_MAPPING] + HAND_JOINT_NAMES

PUBLISH_HZ = 30


class DdsJointRelay(Node):
    """
    ROS 2 node that bridges Unitree DDS LowState → /joint_states.
    Thread-safe: the DDS callback runs in a separate thread managed by the SDK.
    """

    def __init__(self):
        super().__init__("g1_dds_joint_relay")
        self._lock = threading.Lock()
        self._positions = [0.0] * len(JOINT_NAMES)
        self._last_msg_time = 0.0
        self._msg_count = 0

        self._pub = self.create_publisher(JointState, "/joint_states", 10)
        self._timer = self.create_timer(1.0 / PUBLISH_HZ, self._publish_tick)

        self.get_logger().info(
            f"Subscribed to DDS topic '{TOPIC_LOWSTATE}'. "
            f"Publishing /joint_states at {PUBLISH_HZ} Hz …"
        )

    # ── DDS callback (called by SDK thread) ───────────────────────────────────
    def on_lowstate(self, msg: LowState_):
        positions = []
        for name, idx in BODY_JOINT_MAPPING:
            try:
                positions.append(msg.motor_state[idx].q)
            except (IndexError, AttributeError):
                positions.append(0.0)

        # Append default positions (0.0) for hands so RViz doesn't throw TF errors
        positions.extend([0.0] * len(HAND_JOINT_NAMES))

        with self._lock:
            self._positions = positions
            self._last_msg_time = time.time()
            self._msg_count += 1

        # Log first message and then every 300 (every 10 s at 30 Hz)
        if self._msg_count == 1 or self._msg_count % 300 == 0:
            self.get_logger().info(
                f"[DDS] Received LowState #{self._msg_count}. "
                f"Left shoulder pitch: {positions[15]:.3f} rad"
            )

    # ── ROS timer callback (called by ROS executor thread) ────────────────────
    def _publish_tick(self):
        with self._lock:
            positions = list(self._positions)
            last_t = self._last_msg_time

        # Warn if no DDS data has been received in the last 5 seconds
        if last_t > 0 and (time.time() - last_t) > 5.0:
            self.get_logger().warn(
                "No DDS LowState received for >5 s. "
                "Is the robot connected and in Debug Mode?"
            )

        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = JOINT_NAMES
        msg.position = positions
        self._pub.publish(msg)


def main():
    parser = argparse.ArgumentParser(description="G1 DDS → ROS2 Joint State Relay")
    parser.add_argument(
        "--interface", "-i",
        type=str, default=None,
        help="Network interface for CycloneDDS (e.g. eno2). Auto-detect if omitted."
    )
    parser.add_argument(
        "--domain", "-d",
        type=int, default=0,
        help="DDS domain ID (0=real robot, 1=simulation). Default: 0"
    )
    args, ros_args = parser.parse_known_args()

    # Initialise the Unitree DDS channel factory
    print(f"[DDS] Initialising on interface: {args.interface or 'auto-detect'}, domain: {args.domain}")
    ChannelFactoryInitialize(args.domain, args.interface)

    # Initialise ROS 2
    rclpy.init(args=ros_args or None)
    node = DdsJointRelay()

    # Subscribe to LowState
    sub = ChannelSubscriber(TOPIC_LOWSTATE, LowState_)
    sub.Init(node.on_lowstate, 10)
    print(f"[DDS] Subscriber active on topic: {TOPIC_LOWSTATE}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
