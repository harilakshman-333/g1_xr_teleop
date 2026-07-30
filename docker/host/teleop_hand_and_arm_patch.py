import time
import argparse
from multiprocessing import Value, Array, Lock
import threading
import logging_mp
logging_mp.basicConfig(level=logging_mp.INFO)
logger_mp = logging_mp.getLogger(__name__)

import os 
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from unitree_sdk2py.core.channel import ChannelFactoryInitialize # dds 
from televuer import TeleVuerWrapper
from teleop.robot_control.robot_arm import G1_29_ArmController, G1_23_ArmController, H1_2_ArmController, H1_ArmController
from teleop.robot_control.robot_arm_ik import G1_29_ArmIK, G1_23_ArmIK, H1_2_ArmIK, H1_ArmIK
from teleimager.image_client import ImageClient
from teleop.utils.episode_writer import EpisodeWriter
from teleop.utils.ipc import IPC_Server
from teleop.utils.motion_switcher import MotionSwitcher, LocoClientWrapper
from sshkeyboard import listen_keyboard, stop_listening
from collision_guard import CollisionGuard

# for simulation
from unitree_sdk2py.core.channel import ChannelPublisher
from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
def publish_reset_category(category: int, publisher): # Scene Reset signal
    msg = String_(data=str(category))
    publisher.Write(msg)
    logger_mp.info(f"published reset category: {category}")

# state transition
START          = False  # Enable to start robot following VR user motion
STOP           = False  # Enable to begin system exit procedure
READY          = False  # Ready to (1) enter START state, (2) enter RECORD_RUNNING state
RECORD_RUNNING = False  # True if [Recording]
RECORD_TOGGLE  = False  # Toggle recording state

# ---------------------------------------------------------------------------
# Workspace Boundary: Cartesian limits in the robot's base frame (metres).
# Only wrist target positions that fall outside these bounds will be clamped
# to the nearest valid point on the boundary surface.  Rotation is untouched.
#
# Axes convention (robot standing upright, facing forward / +X):
#   X → forward (+) / backward (-)   Y → left (+) / right (-)   Z → up (+)
#
# G1 arm reach from shoulder to end-effector ≈ 0.55 m.
# Tune these to match your physical setup and safety requirements.
# ---------------------------------------------------------------------------
import numpy as _np_ws

WS_LIMITS = {
    # Forward / backward reach.
    # x_min = 0.10  keeps hands in FRONT of the chest; arms cannot go behind body.
    "x_min":  0.10,   # arms must stay in front of the robot's torso
    "x_max":  0.65,   # max safe forward reach (arm fully extended ~0.65 m from base)
    # Left / right reach
    "y_min": -0.55,   # max reach to the right  (right arm)
    "y_max":  0.55,   # max reach to the left   (left arm)
    # Up / down reach  (pelvis ≈ Z=0, shoulder ≈ Z=0.40)
    "z_min":  0.02,   # hands must stay strictly above hip/thigh level
    "z_max":  0.55,   # hands must stay below the shoulders
}

# Maximum spherical reach from shoulder origin (metres).
# Prevents the IK from trying to reach beyond the physical arm length.
WS_MAX_REACH = 0.55

# Minimum lateral separation between each hand and the body centre-line.
# Left  hand: Y must be ≥ +LEFT_Y_MIN   (positive = left side)
# Right hand: Y must be ≤ -RIGHT_Y_MIN  (negative = right side)
# This stops arms crossing through the torso or colliding with it.
LEFT_Y_MIN  =  0.10
RIGHT_Y_MAX = -0.10

# Maximum joint-angle change per control step (rad).
# Caps sudden IK branch-switches that would snap joints to extreme angles.
MAX_JOINT_DELTA = 0.08   # ≈ 4.6° per step at 30 Hz


class WristPoseFilter:
    """
    Exponential Moving Average (EMA) filter for SE3 wrist pose transforms.
    Smooths position and orientation to eliminate Quest 3 hand tracking noise (±3mm jitter).
    """
    def __init__(self, alpha: float = 0.35):
        self.alpha = alpha
        self.prev_pos = None
        self.prev_rot = None

    def filter(self, pose: '_np_ws.ndarray') -> '_np_ws.ndarray':
        if pose is None:
            return pose
        pos = pose[:3, 3]
        rot = pose[:3, :3]
        if self.prev_pos is None:
            self.prev_pos = pos.copy()
            self.prev_rot = rot.copy()
            return pose.copy()

        smooth_pos = self.alpha * pos + (1.0 - self.alpha) * self.prev_pos
        smooth_rot = self.alpha * rot + (1.0 - self.alpha) * self.prev_rot
        self.prev_pos = smooth_pos.copy()
        self.prev_rot = smooth_rot.copy()

        out_pose = pose.copy()
        out_pose[:3, 3] = smooth_pos
        out_pose[:3, :3] = smooth_rot
        return out_pose


def _clamp_reach(pos: '_np_ws.ndarray', max_reach: float) -> '_np_ws.ndarray':
    """Clamp a 3-D position vector to a sphere of radius *max_reach*."""
    dist = _np_ws.linalg.norm(pos)
    if dist > max_reach:
        return pos * (max_reach / dist)
    return pos


def clamp_wrist_pose(pose: 'np.ndarray', is_left: bool = True) -> 'np.ndarray':
    """
    Apply layered safety clamping to a 4x4 SE3 wrist target pose:
      1. Box clamp to WS_LIMITS (no behind-body, no extreme reach).
      2. Per-arm lateral separation (left arm stays left, right arm stays right).
      3. Spherical reach cap so the IK target is always reachable.
    The rotation block is preserved unchanged.

    Args:
        pose:    (4, 4) numpy array — SE3 transform from robot base to wrist target.
        is_left: True for the left arm, False for the right arm.
    Returns:
        A copy of *pose* with translation clamped to the safe workspace.
    """
    clamped = pose.copy()

    # ── 1. Box clamp ──────────────────────────────────────────────────────────
    clamped[0, 3] = _np_ws.clip(pose[0, 3], WS_LIMITS["x_min"], WS_LIMITS["x_max"])
    clamped[1, 3] = _np_ws.clip(pose[1, 3], WS_LIMITS["y_min"], WS_LIMITS["y_max"])
    clamped[2, 3] = _np_ws.clip(pose[2, 3], WS_LIMITS["z_min"], WS_LIMITS["z_max"])

    # ── 2. Per-arm lateral separation (prevents crossing through the torso) ──
    if is_left:
        clamped[1, 3] = max(clamped[1, 3], LEFT_Y_MIN)
    else:
        clamped[1, 3] = min(clamped[1, 3], RIGHT_Y_MAX)

    # ── 3. Spherical reach cap ────────────────────────────────────────────────
    clamped[:3, 3] = _clamp_reach(clamped[:3, 3], WS_MAX_REACH)

    return clamped
#  -------        ---------                -----------                -----------            ---------
#   state          [Ready]      ==>        [Recording]     ==>         [AutoSave]     -->     [Ready]
#  -------        ---------      |         -----------      |         -----------      |     ---------
#   START           True         |manual      True          |manual      True          |        True
#   READY           True         |set         False         |set         False         |auto    True
#   RECORD_RUNNING  False        |to          True          |to          False         |        False
#                                ∨                          ∨                          ∨
#   RECORD_TOGGLE   False       True          False        True          False                  False
#  -------        ---------                -----------                 -----------            ---------
#  ==> manual: when READY is True, set RECORD_TOGGLE=True to transition.
#  --> auto  : Auto-transition after saving data.

def on_press(key):
    global STOP, START, RECORD_TOGGLE
    if key == 'r':
        START = True
    elif key == 'q':
        START = False
        STOP = True
    elif key == 's' and START == True:
        RECORD_TOGGLE = True
    else:
        logger_mp.warning(f"[on_press] {key} was pressed, but no action is defined for this key.")

def get_state() -> dict:
    """Return current heartbeat state"""
    global START, STOP, RECORD_RUNNING, READY
    return {
        "START": START,
        "STOP": STOP,
        "READY": READY,
        "RECORD_RUNNING": RECORD_RUNNING,
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # basic control parameters
    parser.add_argument('--frequency', type = float, default = 30.0, help = 'control and record \'s frequency')
    parser.add_argument('--input-mode', type=str, choices=['hand', 'controller'], default='hand', help='Select XR device input tracking source')
    parser.add_argument('--display-mode', type=str, choices=['immersive', 'ego', 'pass-through'], default='immersive', help='Select XR device display mode')
    parser.add_argument('--arm', type=str, choices=['G1_29', 'G1_23', 'H1_2', 'H1'], default='G1_29', help='Select arm controller')
    parser.add_argument('--ee', type=str, choices=['dex1', 'dex3', 'inspire_ftp', 'inspire_dfx', 'brainco'], help='Select end effector controller')
    parser.add_argument('--img-server-ip', type=str, default='192.168.123.164', help='IP address of image server, used by teleimager and televuer')
    parser.add_argument('--network-interface', type=str, default=None, help='Network interface for dds communication, e.g., eth0, wlan0. If None, use default interface.')
    # mode flags
    parser.add_argument('--motion', action = 'store_true', help = 'Enable motion control mode')
    parser.add_argument('--headless', action='store_true', help='Enable headless mode (no display)')
    parser.add_argument('--sim', action = 'store_true', help = 'Enable isaac simulation mode')
    parser.add_argument('--ipc', action = 'store_true', help = 'Enable IPC server to handle input; otherwise enable sshkeyboard')
    parser.add_argument('--affinity', action = 'store_true', help = 'Enable high priority and set CPU affinity mode')
    # record mode and task info
    parser.add_argument('--record', action = 'store_true', help = 'Enable data recording mode')
    parser.add_argument('--task-dir', type = str, default = './utils/data/', help = 'path to save data')
    parser.add_argument('--task-name', type = str, default = 'pick cube', help = 'task file name for recording')
    parser.add_argument('--task-goal', type = str, default = 'pick up cube.', help = 'task goal for recording at json file')
    parser.add_argument('--task-desc', type = str, default = 'task description', help = 'task description for recording at json file')
    parser.add_argument('--task-steps', type = str, default = 'step1: do this; step2: do that;', help = 'task steps for recording at json file')
    parser.add_argument('--auto-start', action='store_true', help='Automatically start teleoperation without pressing [r]')

    args = parser.parse_args()
    logger_mp.info(f"args: {args}")

    try:
        # setup dds communication domains id
        if args.sim:
            ChannelFactoryInitialize(1, networkInterface=args.network_interface)
        else:
            ChannelFactoryInitialize(0, networkInterface=args.network_interface)

        # ipc communication mode. client usage: see utils/ipc.py
        if args.ipc:
            ipc_server = IPC_Server(on_press=on_press,get_state=get_state)
            ipc_server.start()
        # sshkeyboard communication mode
        else:
            listen_keyboard_thread = threading.Thread(target=listen_keyboard, 
                                                      kwargs={"on_press": on_press, "until": None, "sequential": False,}, 
                                                      daemon=True)
            listen_keyboard_thread.start()

        # image client — retry get_cam_config() to tolerate PC2 still starting up
        img_client = ImageClient(host=args.img_server_ip, request_bgr=True)
        camera_config = None
        for _cfg_attempt in range(10):
            try:
                camera_config = img_client.get_cam_config()
                if camera_config and 'head_camera' in camera_config:
                    break
            except Exception as _cfg_e:
                logger_mp.warning(f"[camera_config] attempt {_cfg_attempt+1}/10 failed: {_cfg_e}")
            logger_mp.info(f"[camera_config] PC2 not ready yet, retrying in 2 s…")
            time.sleep(2.0)
        if camera_config is None or 'head_camera' not in camera_config:
            raise RuntimeError("[camera_config] Could not fetch camera config from PC2 after 10 attempts. Is deploy_to_pc2.sh running?")
        logger_mp.info(f"Camera config: {camera_config}")
        xr_need_local_img = not (args.display_mode == 'pass-through' or camera_config['head_camera']['enable_webrtc'])

        # televuer_wrapper: obtain hand pose data from the XR device and transmit the robot's head camera image to the XR device.
        import socket
        def get_host_lan_ip():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(('8.8.8.8', 1))
                IP = s.getsockname()[0]
            except Exception:
                IP = '127.0.0.1'
            finally:
                s.close()
            return IP
        host_lan_ip = get_host_lan_ip()
        logger_mp.info(f"Resolved Host LAN/WiFi IP: {host_lan_ip}")
        webrtc_url_str = f"https://{host_lan_ip}:{camera_config['head_camera']['webrtc_port']}/offer"
        logger_mp.info(f"Configured WebRTC Stream URL: {webrtc_url_str}")

        tv_wrapper = TeleVuerWrapper(use_hand_tracking=args.input_mode == "hand", 
                                     binocular=camera_config['head_camera']['binocular'],
                                     img_shape=camera_config['head_camera']['image_shape'],
                                     # maybe should decrease fps for better performance?
                                     # https://github.com/unitreerobotics/xr_teleoperate/issues/172
                                     # display_fps=camera_config['head_camera']['fps'] ? args.frequency? 30.0?
                                     display_mode=args.display_mode,
                                     zmq=camera_config['head_camera']['enable_zmq'],
                                     webrtc=camera_config['head_camera']['enable_webrtc'],
                                     webrtc_url=webrtc_url_str,
                                     )

        # ── Pre-warm: push a neutral grey frame into the VR buffer so the Quest
        # ── never sees an all-black display when it connects before the first
        # ── real camera frame arrives from ZMQ (which can take 1-3 s to start).
        if xr_need_local_img and camera_config['head_camera']['enable_zmq']:
            _h, _w = camera_config['head_camera']['image_shape']
            _grey = _np_ws.full((_h, _w, 3), 64, dtype=_np_ws.uint8)  # dark grey
            tv_wrapper.render_to_xr(_grey)
            logger_mp.info("[VR] Pre-warmed shared memory buffer with grey frame.")
        
        # motion mode (G1: Regular mode R1+X, not Running mode R2+A)
        if args.motion:
            if args.input_mode == "controller":
                loco_wrapper = LocoClientWrapper()
        else:
            motion_switcher = MotionSwitcher()
            status, result = motion_switcher.Enter_Debug_Mode()
            logger_mp.info(f"Enter debug mode: {'Success' if status == 0 else 'Failed'}")

        # arm
        if args.arm == "G1_29":
            arm_ik = G1_29_ArmIK()
            arm_ctrl = G1_29_ArmController(motion_mode=args.motion, simulation_mode=args.sim)
            # Collision guard disabled to prevent post-IK solver fighting
            _collision_guard = None
        elif args.arm == "G1_23":
            arm_ik = G1_23_ArmIK()
            arm_ctrl = G1_23_ArmController(motion_mode=args.motion, simulation_mode=args.sim)
            _collision_guard = None  # collision guard only for G1_29
        elif args.arm == "H1_2":
            arm_ik = H1_2_ArmIK()
            arm_ctrl = H1_2_ArmController(motion_mode=args.motion, simulation_mode=args.sim)
            _collision_guard = None
        elif args.arm == "H1":
            arm_ik = H1_ArmIK()
            arm_ctrl = H1_ArmController(simulation_mode=args.sim)
            _collision_guard = None

        # end-effector
        if args.ee == "dex3":
            from teleop.robot_control.robot_hand_unitree import Dex3_1_Controller
            left_hand_pos_array = Array('d', 75, lock = True)      # [input]
            right_hand_pos_array = Array('d', 75, lock = True)     # [input]
            dual_hand_data_lock = Lock()
            dual_hand_state_array = Array('d', 14, lock = False)   # [output] current left, right hand state(14) data.
            dual_hand_action_array = Array('d', 14, lock = False)  # [output] current left, right hand action(14) data.
            hand_ctrl = Dex3_1_Controller(left_hand_pos_array, right_hand_pos_array, dual_hand_data_lock, 
                                          dual_hand_state_array, dual_hand_action_array, simulation_mode=args.sim)
        elif args.ee == "dex1":
            from teleop.robot_control.robot_hand_unitree import Dex1_1_Gripper_Controller
            left_gripper_value = Value('d', 0.0, lock=True)        # [input]
            right_gripper_value = Value('d', 0.0, lock=True)       # [input]
            dual_gripper_data_lock = Lock()
            dual_gripper_state_array = Array('d', 2, lock=False)   # current left, right gripper state(2) data.
            dual_gripper_action_array = Array('d', 2, lock=False)  # current left, right gripper action(2) data.
            gripper_ctrl = Dex1_1_Gripper_Controller(left_gripper_value, right_gripper_value, dual_gripper_data_lock, 
                                                     dual_gripper_state_array, dual_gripper_action_array, simulation_mode=args.sim)
        elif args.ee == "inspire_dfx":
            from teleop.robot_control.robot_hand_inspire import Inspire_Controller_DFX
            left_hand_pos_array = Array('d', 75, lock = True)      # [input]
            right_hand_pos_array = Array('d', 75, lock = True)     # [input]
            dual_hand_data_lock = Lock()
            dual_hand_state_array = Array('d', 12, lock = False)   # [output] current left, right hand state(12) data.
            dual_hand_action_array = Array('d', 12, lock = False)  # [output] current left, right hand action(12) data.
            hand_ctrl = Inspire_Controller_DFX(left_hand_pos_array, right_hand_pos_array, dual_hand_data_lock, dual_hand_state_array, dual_hand_action_array, simulation_mode=args.sim)
        elif args.ee == "inspire_ftp":
            from teleop.robot_control.robot_hand_inspire import Inspire_Controller_FTP
            left_hand_pos_array = Array('d', 75, lock = True)      # [input]
            right_hand_pos_array = Array('d', 75, lock = True)     # [input]
            dual_hand_data_lock = Lock()
            dual_hand_state_array = Array('d', 12, lock = False)   # [output] current left, right hand state(12) data.
            dual_hand_action_array = Array('d', 12, lock = False)  # [output] current left, right hand action(12) data.
            hand_ctrl = Inspire_Controller_FTP(left_hand_pos_array, right_hand_pos_array, dual_hand_data_lock, dual_hand_state_array, dual_hand_action_array, simulation_mode=args.sim)
        elif args.ee == "brainco":
            from teleop.robot_control.robot_hand_brainco import Brainco_Controller
            left_hand_pos_array = Array('d', 75, lock = True)      # [input]
            right_hand_pos_array = Array('d', 75, lock = True)     # [input]
            dual_hand_data_lock = Lock()
            dual_hand_state_array = Array('d', 12, lock = False)   # [output] current left, right hand state(12) data.
            dual_hand_action_array = Array('d', 12, lock = False)  # [output] current left, right hand action(12) data.
            hand_ctrl = Brainco_Controller(left_hand_pos_array, right_hand_pos_array, dual_hand_data_lock, 
                                           dual_hand_state_array, dual_hand_action_array, simulation_mode=args.sim)
        else:
            pass
        
        # affinity mode (if you dont know what it is, then you probably don't need it)
        if args.affinity:
            import psutil
            p = psutil.Process(os.getpid())
            p.cpu_affinity([0,1,2,3]) # Set CPU affinity to cores 0-3
            try:
                p.nice(-20)           # Set highest priority
                logger_mp.info("Set high priority successfully.")
            except psutil.AccessDenied:
                logger_mp.warning("Failed to set high priority. Please run as root.")
                
            for child in p.children(recursive=True):
                try:
                    logger_mp.info(f"Child process {child.pid} name: {child.name()}")
                    child.cpu_affinity([5,6])
                    child.nice(-20)
                except psutil.AccessDenied:
                    pass

        # simulation mode
        if args.sim:
            reset_pose_publisher = ChannelPublisher("rt/reset_pose/cmd", String_)
            reset_pose_publisher.Init()
            from teleop.utils.sim_state_topic import start_sim_state_subscribe
            sim_state_subscriber = start_sim_state_subscribe()

        # record + headless / non-headless mode
        if args.record:
            recorder = EpisodeWriter(task_dir = os.path.join(args.task_dir, args.task_name),
                                     task_goal = args.task_goal,
                                     task_desc = args.task_desc,
                                     task_steps = args.task_steps,
                                     frequency = args.frequency, 
                                     rerun_log = not args.headless)

        logger_mp.info("----------------------------------------------------------------")
        logger_mp.info("🟢  Press [r] to start syncing the robot with your movements.")
        if args.record:
            logger_mp.info("🟡  Press [s] to START or SAVE recording (toggle cycle).")
        else:
            logger_mp.info("🔵  Recording is DISABLED (run with --record to enable).")
        logger_mp.info("🔴  Press [q] to stop and exit the program.")
        logger_mp.info("⚠️  IMPORTANT: Please keep your distance and stay safe.")
        READY = True                  # now ready to (1) enter START state
        # Auto-start: skip waiting for [r] if --auto-start is set
        if args.auto_start:
            logger_mp.info("🚀  AUTO-START enabled — beginning teleoperation immediately.")
            START = True
        _last_good_frame = None   # track the most recent valid BGR frame
        while not START and not STOP: # wait for start or stop signal.
            time.sleep(0.033)
            if camera_config['head_camera']['enable_zmq'] and xr_need_local_img:
                head_img = img_client.get_head_frame()
                if head_img.bgr is not None:
                    _last_good_frame = head_img.bgr
                    tv_wrapper.render_to_xr(head_img.bgr)
                elif _last_good_frame is not None:
                    # ZMQ returned stale/None — re-push the last good frame so the
                    # Quest doesn't see a frozen black display on brief ZMQ gaps.
                    tv_wrapper.render_to_xr(_last_good_frame)

        logger_mp.info("---------------------🚀start Tracking🚀-------------------------")
        arm_ctrl.speed_gradual_max()
        # main loop. robot start to follow VR user's motion
        _dbg_iter = 0
        _prev_sol_q = None  # for joint slew-rate limiter
        _left_wrist_filter = WristPoseFilter(alpha=0.35)
        _right_wrist_filter = WristPoseFilter(alpha=0.35)
        if hasattr(arm_ik, '_ik_initialized'):
            arm_ik._ik_initialized = False
        while not STOP:
            start_time = time.time()
            # get image
            if camera_config['head_camera']['enable_zmq']:
                if args.record or xr_need_local_img:
                    head_img = img_client.get_head_frame()
                if xr_need_local_img:
                    if head_img.bgr is not None:
                        _last_good_frame = head_img.bgr
                        tv_wrapper.render_to_xr(head_img.bgr)
                    elif _last_good_frame is not None:
                        # Re-push last good frame on brief ZMQ stalls
                        tv_wrapper.render_to_xr(_last_good_frame)
            if camera_config['left_wrist_camera']['enable_zmq']:
                if args.record:
                    left_wrist_img = img_client.get_left_wrist_frame()
            if camera_config['right_wrist_camera']['enable_zmq']:
                if args.record:
                    right_wrist_img = img_client.get_right_wrist_frame()

            # record mode
            if args.record and RECORD_TOGGLE:
                RECORD_TOGGLE = False
                if not RECORD_RUNNING:
                    if recorder.create_episode():
                        RECORD_RUNNING = True
                    else:
                        logger_mp.error("Failed to create episode. Recording not started.")
                else:
                    RECORD_RUNNING = False
                    recorder.save_episode()
                    if args.sim:
                        publish_reset_category(1, reset_pose_publisher)

            # get xr's tele data
            tele_data = tv_wrapper.get_tele_data()
            if _dbg_iter % 90 == 0:
                logger_mp.warning(f'[DBG#{_dbg_iter}] L_wrist_t={tele_data.left_wrist_pose[:3,3].round(3)}, R_wrist_t={tele_data.right_wrist_pose[:3,3].round(3)}')
            if (args.ee == "dex3" or args.ee == "inspire_dfx" or args.ee == "inspire_ftp" or args.ee == "brainco") and args.input_mode == "hand":
                with left_hand_pos_array.get_lock():
                    left_hand_pos_array[:] = tele_data.left_hand_pos.flatten()
                with right_hand_pos_array.get_lock():
                    right_hand_pos_array[:] = tele_data.right_hand_pos.flatten()
            elif args.ee == "dex1" and args.input_mode == "controller":
                with left_gripper_value.get_lock():
                    left_gripper_value.value = tele_data.left_ctrl_triggerValue
                with right_gripper_value.get_lock():
                    right_gripper_value.value = tele_data.right_ctrl_triggerValue
            elif args.ee == "dex1" and args.input_mode == "hand":
                with left_gripper_value.get_lock():
                    left_gripper_value.value = tele_data.left_hand_pinchValue
                with right_gripper_value.get_lock():
                    right_gripper_value.value = tele_data.right_hand_pinchValue
            else:
                pass
            
            # high level control
            if args.input_mode == "controller" and args.motion:
                # quit teleoperate
                if tele_data.right_ctrl_aButton:
                    START = False
                    STOP = True
                # command robot to enter damping mode. soft emergency stop function
                if tele_data.left_ctrl_thumbstick and tele_data.right_ctrl_thumbstick:
                    loco_wrapper.Damp()
                # https://github.com/unitreerobotics/xr_teleoperate/issues/135, control, limit velocity to within 0.3
                loco_wrapper.Move(-tele_data.left_ctrl_thumbstickValue[1] * 0.3,
                                  -tele_data.left_ctrl_thumbstickValue[0] * 0.3,
                                  -tele_data.right_ctrl_thumbstickValue[0]* 0.3)

            # get current robot state data.
            current_lr_arm_q  = arm_ctrl.get_current_dual_arm_q()
            current_lr_arm_dq = arm_ctrl.get_current_dual_arm_dq()

            # Smooth raw VR wrist poses using EMA filter to remove Quest 3 tracking noise
            left_wrist_smooth  = _left_wrist_filter.filter(tele_data.left_wrist_pose)
            right_wrist_smooth = _right_wrist_filter.filter(tele_data.right_wrist_pose)

            # Clamp wrist target poses to the configured workspace boundaries
            # before passing them to the IK solver.  is_left=True/False enforces
            # per-arm lateral separation so neither hand can cross the body centreline.
            left_wrist_clamped  = clamp_wrist_pose(left_wrist_smooth,  is_left=True)
            right_wrist_clamped = clamp_wrist_pose(right_wrist_smooth, is_left=False)

            # solve ik using motor data and wrist pose, then use ik results to control arms.
            time_ik_start = time.time()
            sol_q, sol_tauff  = arm_ik.solve_ik(left_wrist_clamped, right_wrist_clamped, current_lr_arm_q, current_lr_arm_dq)
            time_ik_end = time.time()
            logger_mp.debug(f"ik:\t{round(time_ik_end - time_ik_start, 6)}")

            # ── Collision guard (Pinocchio + HPP-FCL) ──────────────────────────
            # Check candidate joint configuration against actual URDF collision
            # meshes BEFORE slew-limiting. If any arm link is close to the body,
            # apply Jacobian push-out correction.
            if _collision_guard is not None:
                _prev_safe = _prev_sol_q if _prev_sol_q is not None else sol_q
                _is_safe, sol_q = _collision_guard.check_and_correct(sol_q, _prev_safe)

            # ── Joint slew-rate limiter ────────────────────────────────────────
            # Cap the per-step joint angle change to MAX_JOINT_DELTA so that IK
            # branch-switches or collision push-outs transition smoothly without jerking.
            import numpy as _np_slew
            if _prev_sol_q is not None:
                delta = sol_q - _prev_sol_q
                clipped_delta = _np_slew.clip(delta, -MAX_JOINT_DELTA, MAX_JOINT_DELTA)
                sol_q = _prev_sol_q + clipped_delta

            _prev_sol_q = sol_q.copy()

            arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)
            if _dbg_iter % 90 == 0:
                logger_mp.warning(f'[DBG#{_dbg_iter}] sol_q={sol_q.round(3)}')
            _dbg_iter += 1

            # record data
            if args.record:
                READY = recorder.is_ready() # now ready to (2) enter RECORD_RUNNING state
                # dex hand or gripper
                if args.ee == "dex3" and args.input_mode == "hand":
                    with dual_hand_data_lock:
                        left_ee_state = dual_hand_state_array[:7]
                        right_ee_state = dual_hand_state_array[-7:]
                        left_hand_action = dual_hand_action_array[:7]
                        right_hand_action = dual_hand_action_array[-7:]
                        current_body_state = []
                        current_body_action = []
                elif args.ee == "dex1" and args.input_mode == "hand":
                    with dual_gripper_data_lock:
                        left_ee_state = [dual_gripper_state_array[0]]
                        right_ee_state = [dual_gripper_state_array[1]]
                        left_hand_action = [dual_gripper_action_array[0]]
                        right_hand_action = [dual_gripper_action_array[1]]
                        current_body_state = []
                        current_body_action = []
                elif args.ee == "dex1" and args.input_mode == "controller":
                    with dual_gripper_data_lock:
                        left_ee_state = [dual_gripper_state_array[0]]
                        right_ee_state = [dual_gripper_state_array[1]]
                        left_hand_action = [dual_gripper_action_array[0]]
                        right_hand_action = [dual_gripper_action_array[1]]
                        current_body_state = arm_ctrl.get_current_motor_q().tolist()
                        current_body_action = [-tele_data.left_ctrl_thumbstickValue[1]  * 0.3,
                                               -tele_data.left_ctrl_thumbstickValue[0]  * 0.3,
                                               -tele_data.right_ctrl_thumbstickValue[0] * 0.3]
                elif (args.ee == "inspire_dfx" or args.ee == "inspire_ftp" or args.ee == "brainco") and args.input_mode == "hand":
                    with dual_hand_data_lock:
                        left_ee_state = dual_hand_state_array[:6]
                        right_ee_state = dual_hand_state_array[-6:]
                        left_hand_action = dual_hand_action_array[:6]
                        right_hand_action = dual_hand_action_array[-6:]
                        current_body_state = []
                        current_body_action = []
                else:
                    left_ee_state = []
                    right_ee_state = []
                    left_hand_action = []
                    right_hand_action = []
                    current_body_state = []
                    current_body_action = []

                # arm state and action
                left_arm_state  = current_lr_arm_q[:7]
                right_arm_state = current_lr_arm_q[-7:]
                left_arm_action = sol_q[:7]
                right_arm_action = sol_q[-7:]
                if RECORD_RUNNING:
                    colors = {}
                    depths = {}
                    if camera_config['head_camera']['binocular']:
                        if head_img is not None:
                            colors[f"color_{0}"] = head_img.bgr[:, :camera_config['head_camera']['image_shape'][1]//2]
                            colors[f"color_{1}"] = head_img.bgr[:, camera_config['head_camera']['image_shape'][1]//2:]
                        else:
                            logger_mp.warning("Head image is None!")
                        if camera_config['left_wrist_camera']['enable_zmq']:
                            if left_wrist_img is not None:
                                colors[f"color_{2}"] = left_wrist_img.bgr
                            else:
                                logger_mp.warning("Left wrist image is None!")
                        if camera_config['right_wrist_camera']['enable_zmq']:
                            if right_wrist_img is not None:
                                colors[f"color_{3}"] = right_wrist_img.bgr
                            else:
                                logger_mp.warning("Right wrist image is None!")
                    else:
                        if head_img is not None:
                            colors[f"color_{0}"] = head_img.bgr
                        else:
                            logger_mp.warning("Head image is None!")
                        if camera_config['left_wrist_camera']['enable_zmq']:
                            if left_wrist_img is not None:
                                colors[f"color_{1}"] = left_wrist_img.bgr
                            else:
                                logger_mp.warning("Left wrist image is None!")
                        if camera_config['right_wrist_camera']['enable_zmq']:
                            if right_wrist_img is not None:
                                colors[f"color_{2}"] = right_wrist_img.bgr
                            else:
                                logger_mp.warning("Right wrist image is None!")
                    states = {
                        "left_arm": {                                                                    
                            "qpos":   left_arm_state.tolist(),    # numpy.array -> list
                            "qvel":   [],                          
                            "torque": [],                        
                        }, 
                        "right_arm": {                                                                    
                            "qpos":   right_arm_state.tolist(),       
                            "qvel":   [],                          
                            "torque": [],                         
                        },                        
                        "left_ee": {                                                                    
                            "qpos":   left_ee_state,           
                            "qvel":   [],                           
                            "torque": [],                          
                        }, 
                        "right_ee": {                                                                    
                            "qpos":   right_ee_state,       
                            "qvel":   [],                           
                            "torque": [],  
                        }, 
                        "body": {
                            "qpos": current_body_state,
                        }, 
                    }
                    actions = {
                        "left_arm": {                                   
                            "qpos":   left_arm_action.tolist(),       
                            "qvel":   [],       
                            "torque": [],      
                        }, 
                        "right_arm": {                                   
                            "qpos":   right_arm_action.tolist(),       
                            "qvel":   [],       
                            "torque": [],       
                        },                         
                        "left_ee": {                                   
                            "qpos":   left_hand_action,       
                            "qvel":   [],       
                            "torque": [],       
                        }, 
                        "right_ee": {                                   
                            "qpos":   right_hand_action,       
                            "qvel":   [],       
                            "torque": [], 
                        }, 
                        "body": {
                            "qpos": current_body_action,
                        }, 
                    }
                    if args.sim:
                        sim_state = sim_state_subscriber.read_data()            
                        recorder.add_item(colors=colors, depths=depths, states=states, actions=actions, sim_state=sim_state)
                    else:
                        recorder.add_item(colors=colors, depths=depths, states=states, actions=actions)

            current_time = time.time()
            time_elapsed = current_time - start_time
            sleep_time = max(0, (1 / args.frequency) - time_elapsed)
            time.sleep(sleep_time)
            logger_mp.debug(f"main process sleep: {sleep_time}")

    except KeyboardInterrupt:
        logger_mp.info("⛔ KeyboardInterrupt, exiting program...")
    except Exception:
        import traceback
        logger_mp.error(traceback.format_exc())
    finally:
        try:
            arm_ctrl.ctrl_dual_arm_go_home()
        except Exception as e:
            logger_mp.error(f"Failed to ctrl_dual_arm_go_home: {e}")
        
        try:
            if args.ipc:
                ipc_server.stop()
            else:
                stop_listening()
                listen_keyboard_thread.join()
        except Exception as e:
            logger_mp.error(f"Failed to stop keyboard listener or ipc server: {e}")
        
        try:
            img_client.close()
        except Exception as e:
            logger_mp.error(f"Failed to close image client: {e}")

        try:
            tv_wrapper.close()
        except Exception as e:
            logger_mp.error(f"Failed to close televuer wrapper: {e}")

        try:
            if not args.motion:
                pass
                # status, result = motion_switcher.Exit_Debug_Mode()
                # logger_mp.info(f"Exit debug mode: {'Success' if status == 3104 else 'Failed'}")
        except Exception as e:
            logger_mp.error(f"Failed to exit debug mode: {e}")

        try:
            if args.sim:
                sim_state_subscriber.stop_subscribe()
        except Exception as e:
            logger_mp.error(f"Failed to stop sim state subscriber: {e}")
        
        try:
            if args.record:
                recorder.close()
        except Exception as e:
            logger_mp.error(f"Failed to close recorder: {e}")
        logger_mp.info("✅ Finally, exiting program.")
        exit(0)
