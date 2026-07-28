#!/usr/bin/env python3
"""
docker/viz/dds_joint_relay.py
──────────────────────────────
Subscribes to the Unitree G1's live DDS topics on the robot network:
  1. LowState (rt/lowstate) for 29 body & arm joint positions
  2. Dex3-1 Left Hand State (rt/lf/dex3/left/state) for 7 left finger joints
  3. Dex3-1 Right Hand State (rt/lf/dex3/right/state) for 7 right finger joints

Re-publishes all 43 joint positions as a ROS 2 JointState message on /joint_states
at 30 Hz so RViz can visualize both arms and dexterous grippers in real time.

Also subscribes to the ZMQ camera feed from the robot head camera and publishes
sensor_msgs/Image on /camera/image_raw for display in the RViz Camera panel.
"""

import argparse
import sys
import threading
import time
import os

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState, Image

# Add teleimager paths if mounted
for p in ["/opt/xr_teleoperate/teleop/teleimager/src", "/opt/xr_teleoperate/teleop"]:
    if p not in sys.path and os.path.exists(p):
        sys.path.append(p)

# ── Unitree SDK ────────────────────────────────────────────────────────────────
try:
    from unitree_sdk2py.core.channel import (
        ChannelFactoryInitialize,
        ChannelSubscriber,
    )
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    TOPIC_LOWSTATE = "rt/lowstate"
except ImportError:
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

# Hand state IDL
try:
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import HandState_
    TOPIC_DEX3_LEFT_STATE = "rt/lf/dex3/left/state"
    TOPIC_DEX3_RIGHT_STATE = "rt/lf/dex3/right/state"
    HAS_HAND_SDK = True
except ImportError:
    HAS_HAND_SDK = False

# ── G1 29-DoF body joint indices in the LowState motor_state array ─────────────
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
    ROS 2 node bridging Unitree DDS LowState & HandState → /joint_states
    and ZMQ head camera feed → /camera/image_raw.
    """

    def __init__(self, img_server_ip: str = None):
        super().__init__("g1_dds_joint_relay")
        self._lock = threading.Lock()
        self._body_positions = [0.0] * len(BODY_JOINT_MAPPING)
        self._left_hand_positions = [0.0] * 7
        self._right_hand_positions = [0.0] * 7
        self._last_msg_time = 0.0
        self._msg_count = 0

        self._pub = self.create_publisher(JointState, "/joint_states", 10)
        self._timer = self.create_timer(1.0 / PUBLISH_HZ, self._publish_tick)

        self._img_pub = self.create_publisher(Image, "/camera/image_raw", 10)
        self._img_server_ip = img_server_ip
        if self._img_server_ip:
            self._cam_thread = threading.Thread(target=self._camera_loop, daemon=True)
            self._cam_thread.start()

        self.get_logger().info(
            f"Subscribed to DDS topic '{TOPIC_LOWSTATE}'. "
            f"Publishing /joint_states at {PUBLISH_HZ} Hz …"
        )

    def _camera_loop(self):
        try:
            from teleimager.image_client import ImageClient
        except ImportError as e:
            self.get_logger().warn(f"[CameraRelay] teleimager import failed: {e}. Camera relay disabled.")
            return

        self.get_logger().info(f"[CameraRelay] Connecting to ZMQ image server at {self._img_server_ip}...")
        try:
            img_client = ImageClient(host=self._img_server_ip, request_bgr=True)
        except Exception as e:
            self.get_logger().error(f"[CameraRelay] Failed to start ImageClient: {e}")
            return

        self.get_logger().info("[CameraRelay] Connected to camera server! Publishing frames to /camera/image_raw")
        while rclpy.ok():
            try:
                head_frame = img_client.get_head_frame()
                if head_frame and head_frame.bgr is not None:
                    bgr_img = head_frame.bgr
                    height, width = bgr_img.shape[:2]
                    channels = bgr_img.shape[2] if len(bgr_img.shape) > 2 else 1

                    msg = Image()
                    msg.header.stamp = self.get_clock().now().to_msg()
                    msg.header.frame_id = "d435_link"
                    msg.height = height
                    msg.width = width
                    msg.encoding = "bgr8" if channels == 3 else "mono8"
                    msg.is_bigendian = False
                    msg.step = width * channels
                    msg.data = bgr_img.tobytes()

                    self._img_pub.publish(msg)
            except Exception as e:
                pass
            time.sleep(0.033)

    # ── DDS callbacks ─────────────────────────────────────────────────────────
    def on_lowstate(self, msg: LowState_):
        positions = []
        for name, idx in BODY_JOINT_MAPPING:
            try:
                positions.append(msg.motor_state[idx].q)
            except (IndexError, AttributeError):
                positions.append(0.0)

        with self._lock:
            self._body_positions = positions
            self._last_msg_time = time.time()
            self._msg_count += 1

        if self._msg_count == 1 or self._msg_count % 300 == 0:
            self.get_logger().info(
                f"[DDS] Received LowState #{self._msg_count}. "
                f"Left shoulder pitch: {positions[15]:.3f} rad"
            )

    def on_left_hand_state(self, msg: HandState_):
        try:
            positions = [msg.motor_state[i].q for i in range(min(7, len(msg.motor_state)))]
            with self._lock:
                self._left_hand_positions[:len(positions)] = positions
        except Exception:
            pass

    def on_right_hand_state(self, msg: HandState_):
        try:
            positions = [msg.motor_state[i].q for i in range(min(7, len(msg.motor_state)))]
            with self._lock:
                self._right_hand_positions[:len(positions)] = positions
        except Exception:
            pass

    # ── ROS timer callback ───────────────────────────────────────────────────
    def _publish_tick(self):
        with self._lock:
            body_p = list(self._body_positions)
            left_h = list(self._left_hand_positions)
            right_h = list(self._right_hand_positions)
            last_t = self._last_msg_time

        if last_t > 0 and (time.time() - last_t) > 5.0:
            self.get_logger().warn(
                "No DDS LowState received for >5 s. "
                "Is the robot connected and in Debug Mode?"
            )

        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = JOINT_NAMES
        msg.position = body_p + left_h + right_h
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
    parser.add_argument(
        "--img-server-ip",
        type=str, default=None,
        help="IP address of PC2 image server (e.g. 192.168.123.164) to relay camera frames to RViz."
    )
    args, ros_args = parser.parse_known_args()

    print(f"[DDS] Initialising on interface: {args.interface or 'auto-detect'}, domain: {args.domain}")
    ChannelFactoryInitialize(args.domain, args.interface)

    rclpy.init(args=ros_args or None)
    node = DdsJointRelay(img_server_ip=args.img_server_ip)

    sub_low = ChannelSubscriber(TOPIC_LOWSTATE, LowState_)
    sub_low.Init(node.on_lowstate, 10)
    print(f"[DDS] Subscriber active on topic: {TOPIC_LOWSTATE}")

    if HAS_HAND_SDK:
        sub_lhand = ChannelSubscriber(TOPIC_DEX3_LEFT_STATE, HandState_)
        sub_lhand.Init(node.on_left_hand_state, 10)
        sub_rhand = ChannelSubscriber(TOPIC_DEX3_RIGHT_STATE, HandState_)
        sub_rhand.Init(node.on_right_hand_state, 10)
        print(f"[DDS] Hand subscribers active on: {TOPIC_DEX3_LEFT_STATE}, {TOPIC_DEX3_RIGHT_STATE}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
