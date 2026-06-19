# Unitree G1 XR Teleoperation & ROS 2 Visualization Skill File

This file serves as a reference manual and skill file for configuring, operating, and troubleshooting the Unitree G1 Humanoid robot (29-DoF body + 14-DoF dexterous hands) in an XR teleoperation or real-time visualization environment.

---

## 1. System Architecture & Data Flow

```mermaid
graph TD
    Quest3[Meta Quest 3 VR Headset] -- "WebSocket / WebXR (30Hz)" --> Host[Host PC (Docker Stack)]
    PC2[Robot PC2 (192.168.123.164)] -- "ZMQ TCP (30Hz)" --> Host
    Host -- "CycloneDDS UDP (30Hz)" --> Robot[Robot PC1 (192.168.123.161)]
    Robot -- "DDS LowState (200-500Hz)" --> Relay[g1_joint_relay Container]
    Relay -- "/joint_states (30Hz)" --> Publisher[g1_robot_state_publisher]
    Publisher -- "/tf Transforms" --> RViz2[g1_rviz Container]
```

### Stream Frequencies
* **Quest 3 WebSocket / WebXR:** ~30Hz (delivers tracking poses and receives the VR camera stream).
* **Camera ZMQ Stream:** ~30Hz (retrieves raw JPEG compressed frames from PC2 to the Host).
* **Robot DDS Telemetry (`LowState`):** 200–500Hz (internal robot state).
* **ROS 2 Joint State Relay:** Downsampled to 30Hz for visualization stability.

---

## 2. Network Topology & Interface Isolation

> [!IMPORTANT]
> **Multicast Isolation Rule:** By default, ROS 2 (CycloneDDS) broadcasts UDP multicast packets across all host network interfaces. This floods the Wi-Fi card and saturates the link to the Quest 3, causing the camera stream to lag and freeze. All host-side ROS 2 containers must restrict CycloneDDS to the physical Ethernet port.

### Interface Configurations
* **Host Ethernet IP (e.g., `eno2`):** `192.168.123.2/24` (static IP on robot subnet).
* **Robot PC1 IP:** `192.168.123.161` (main low-level locomotion controller).
* **Robot PC2 IP:** `192.168.123.164` (secondary computer running cameras).
* **Host Wi-Fi IP:** Dynamically assigned (used for communicating with Quest 3 over the local router).

### Inline CycloneDDS Isolation Configuration
To restrict CycloneDDS from broadcasting onto the Wi-Fi card, configure the `CYCLONEDDS_URI` environment variable inside `docker-compose.yml` for all host-side ROS 2 services:

```yaml
CYCLONEDDS_URI: "<CycloneDDS><Domain><General><Interfaces><NetworkInterface name='${NETWORK_INTERFACE:-eno2}'/></Interfaces></General></Domain></CycloneDDS>"
```

---

## 3. Physical Controller Debug Mode Sequence

The G1's default locomotion controller blocks direct joint commands. To enable teleoperation, the robot must be suspended in a harness, and the following sequence must be executed on the physical controller to suspend the locomotion stack:

| Step | Button Combo | State Transition / Meaning |
|:---:|---|---|
| **1** | `L1 + A` | Damping Mode (robot goes limp) |
| **2** | `L2 + R2` (simultaneously) | **Suspends locomotion stack** (debug mode active) |
| **3** | `L2 + A` | Diagnostic Pose (arms move forward to confirm control) |
| **4** | `L2 + B` | Returns arms to rest pose |
| **5** | `L2 + R2` | **Re-enter debug mode** (required after every `L2 + A` / `L2 + B` pose reset) |

---

## 4. URDF & Joint State Mapping

### 29-DoF Body Joint Index Mapping
The G1 controller expects a specific joint state order for control and telemetry:

```python
G1_29_JOINT_NAMES = [
    # Left Leg (6 DoF)
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
    "left_knee_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    # Right Leg (6 DoF)
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
    "right_knee_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
    # Waist (3 DoF)
    "waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint",
    # Left Arm (7 DoF)
    "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint",
    "left_elbow_joint", "left_wrist_roll_joint", "left_wrist_pitch_joint", "left_wrist_yaw_joint",
    # Right Arm (7 DoF)
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint",
    "right_elbow_joint", "right_wrist_roll_joint", "right_wrist_pitch_joint", "right_wrist_yaw_joint"
]
```

### Dexterous Hand Joint Names (14 DoF)
The G1 Dex3 hands require 7 additional joints per hand to be published in the TF tree, even if they are set to default `0.0` values:

```python
G1_HAND_JOINT_NAMES = [
    # Left Hand (7 DoF)
    "left_thumb_joint", "left_index_joint1", "left_index_joint2",
    "left_middle_joint1", "left_middle_joint2", "left_ring_joint1", "left_ring_joint2",
    # Right Hand (7 DoF)
    "right_thumb_joint", "right_index_joint1", "right_index_joint2",
    "right_middle_joint1", "right_middle_joint2", "right_ring_joint1", "right_ring_joint2"
]
```

### URDF Path Rewriting for RViz2
To render URDF visual meshes inside Docker containers, startup scripts must dynamically translate relative package paths to absolute `file:///` URIs:
```bash
sed -i 's|package://g1_description/|file:///opt/xr_teleoperate/assets/g1/|g' /tmp/g1.urdf
```

---

## 5. Troubleshooting & Diagnostics

### Symptom: Camera Stream is Black or Timed Out
1. Run `ip addr show eno2` on the host to verify if the interface is `<NO-CARRIER>` (unplugged/powered off) or `state DOWN`.
2. Check if the static IP is assigned. If not, re-run:
   ```bash
   sudo ./scripts/setup_network.sh --iface eno2 --ip 192.168.123.2
   ```
3. Test connectivity with: `ping 192.168.123.164`.

### Symptom: Quest 3 Camera Stream Lagging / Freezing
1. Verify the `CYCLONEDDS_URI` is correctly populated in `docker-compose.yml`.
2. Run `route -n` or `ip route show` on the host to check if multicast routes have leaked onto the Wi-Fi card interface.

### Symptom: RViz Shows Model Error / Broken TF Tree
1. Check `docker logs g1_teleop_joint_relay` to ensure joint states are publishing.
2. Confirm the joint relay is publishing **all 43 joints** (29 body + 14 hand). A missing hand joint will break the parent-child TF transformation chain.

---

## 6. How to Use this Skill File in Future Sessions

When a new coding assistant or agent starts working on this repository, you can provide this instruction:

> **Prompt:** "Please read the `g1_teleop_skill.md` file using your file viewer tool with `IsSkillFile: true` to load all system architectures, network interfaces, URDF joint mappings, and troubleshooting commands for our G1 teleop configuration."

This will instantly load the correct network parameters, paths, and configurations, preventing the agent from making redundant changes or disrupting your network setup.
