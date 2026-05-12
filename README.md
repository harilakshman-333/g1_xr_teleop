# G1 XR Teleoperation — Meta Quest 3

Teleoperation of the **Unitree G1 (29 DoF) + Dex3-1 dexterous hands** using a **Meta Quest 3** headset.  
Based on [unitreerobotics/xr_teleoperate](https://github.com/unitreerobotics/xr_teleoperate) v1.5, fully containerised with Docker.

---

## Hardware

| Component | Spec | Notes |
|---|---|---|
| Robot | Unitree G1 29DoF EDU | Developer computing unit version required (has PC2) |
| Hands | Unitree Dex3-1 (×2) | 7 finger joints per hand, controlled via DDS |
| XR Headset | Meta Quest 3 | Hand tracking mode used (no controllers needed) |
| Head Camera | Intel RealSense D435i | Built into G1 head, monocular RGB 640×480 @ 30fps |
| Host Computer | Ubuntu 22.04 x86-64 | Runs Docker, connected via Ethernet to robot |
| Router | WiFi 6 (recommended) | Bridges Quest 3 WiFi to robot Ethernet network |

---

## System Architecture

```
[Meta Quest 3] ── WiFi ──► [Router] ── Ethernet ──► [Host PC / Ubuntu 22.04]
                                                            │
                                                       Ethernet (192.168.123.x)
                                                            │
                                                   [G1 Robot Network]
                                                      /           \
                                                  [PC2]          [MCU]
                                            192.168.123.164    (joints/motors)
                                         (runs image server)
```

### Data flow during teleoperation

```
Quest 3 Browser
    │  WebSocket (wss://HOST:8012)
    │  Sends: head pose, left/right wrist SE(3), 21 hand keypoints/hand
    ▼
televuer (Host container, port 8012)
    │  tv_wrapper.py — coordinate frame conversion + smoothing
    ▼
teleop_hand_and_arm.py (Host container, main loop @ 30 Hz)
    │
    ├──► robot_arm_ik.py ──► pinocchio + CasADi IK solver
    │       Input:  left/right wrist target SE(3) poses
    │       Output: 14 arm joint angles (7 per arm)
    │       Sends:  joint commands via CycloneDDS → G1 MCU
    │
    └──► hand_retargeting.py ──► dex-retargeting library
            Input:  21 hand keypoints (from Quest 3 hand tracking)
            Output: 7 Dex3-1 finger joint angles per hand
            Sends:  finger joint commands via CycloneDDS → Dex3-1

PC2 (192.168.123.164)
    │  D435i captures RGB frames
    │  teleimager publishes over ZMQ tcp://PC2:5555
    ▼
Host container (image_client)
    │  Receives frames
    ▼
televuer → WebRTC/WebSocket → Quest 3 (first-person view in headset)
```

---

## Repository Structure

```
g1_xr_teleop/
│
├── docker/
│   ├── host/
│   │   ├── Dockerfile        ← Host container: teleop loop, IK, hand retargeting
│   │   └── entrypoint.sh     ← Validates env vars + SSL, launches teleop script
│   └── pc2/
│       ├── Dockerfile        ← PC2 container: D435i image server (runs on robot)
│       └── entrypoint.sh     ← Validates config + certs, starts teleimager server
│
├── scripts/
│   ├── gen_certs.sh          ← Generates SSL certs required by Quest 3 WebSocket
│   ├── setup_network.sh      ← Assigns static IP on Host Ethernet interface
│   └── deploy_to_pc2.sh      ← Copies files + starts Docker on robot's PC2
│
├── configs/
│   └── cam_config_server.yaml ← Camera config for PC2 image server (D435i settings)
│
├── certs/                    ← SSL certificates (git-ignored, generated locally)
│   ├── cert.pem              ← Public certificate (share to devices)
│   └── key.pem               ← Private key (never commit)
│
├── data/                     ← Recorded episodes (git-ignored)
│   └── <task-name>/
│       └── episode_NNNN/     ← Arm states, hand states, camera frames per episode
│
├── docker-compose.yml        ← Host service (run on your laptop/desktop)
├── docker-compose.pc2.yml    ← PC2 service (deployed to robot, run via deploy_to_pc2.sh)
├── .env.example              ← Environment variable template — copy to .env
└── README.md                 ← This file
```

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2 installed on the Host
- Docker Engine installed on the G1's PC2 (usually pre-installed on EDU units)
- G1 robot powered on, booted, in standalone mode
- Host Ethernet connected to the robot network (or router bridging them)
- Meta Quest 3 on the same network as the Host

---

## Setup Guide

### Step 1 — Clone this repository

```bash
git clone <this-repo> ~/projects/g1_xr_teleop
cd ~/projects/g1_xr_teleop
```

### Step 2 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and verify the defaults. For your hardware, these are the critical fields:

```dotenv
ARM=G1_29          # G1 with 29 DoF
EE=dex3            # Dex3-1 dexterous hands
IMG_SERVER_IP=192.168.123.164   # PC2 fixed IP
INPUT_MODE=hand    # Quest 3 hand tracking
```

Set `NETWORK_INTERFACE` to your Ethernet interface name (find it with `ip link show`).

### Step 3 — Configure the network

Assigns a static IP (`192.168.123.2`) on your Ethernet interface and opens firewall ports:

```bash
chmod +x scripts/setup_network.sh
sudo ./scripts/setup_network.sh
```

The script auto-detects your Ethernet interface. Override if needed:

```bash
sudo ./scripts/setup_network.sh --iface enp3s0 --ip 192.168.123.2
```

Verify the robot is reachable:
```bash
ping 192.168.123.164        # should respond
ssh unitree@192.168.123.164 # password: 123
```

### Step 4 — Generate SSL certificates

The Quest 3's browser requires HTTPS/WSS. This creates a self-signed certificate:

```bash
chmod +x scripts/gen_certs.sh
./scripts/gen_certs.sh
```

The script auto-detects your Host IP and includes it in the certificate's Subject
Alternative Names (SANs), which modern browsers require. Output: `certs/cert.pem` and `certs/key.pem`.

### Step 5 — Deploy the image server to PC2

Copies Docker files and certificates to PC2, then starts the image server:

```bash
chmod +x scripts/deploy_to_pc2.sh
./scripts/deploy_to_pc2.sh
```

Verify the D435i camera is working by opening in the Quest 3 browser:
```
https://192.168.123.164:60001
```
Accept the certificate warning → click Start. If you see the robot's camera feed, the image server is working.

### Step 6 — Trust the certificate on the Quest 3

This step unlocks the WebSocket connection from the headset to the Host:

1. Put on the Quest 3
2. Open **Meta Quest Browser**
3. Navigate to: `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012`
4. Tap **Advanced** → **Proceed to 192.168.123.2 (unsafe)**
5. The page will attempt to connect — this is enough to store the trust decision

You only need to do this **once** per certificate (re-run `gen_certs.sh` if the cert expires or the IP changes).

### Step 7 — Build and launch the Host container

```bash
docker compose build
docker compose up
```

You'll see the startup banner in the terminal:

```
[INFO]  Robot arm  : G1_29
[INFO]  End-eff    : dex3
[INFO]  Input mode : hand
[INFO]  Press [r] to start teleoperation
[INFO]  Press [s] to toggle recording
[INFO]  Press [q] to stop and exit safely
```

---

## Operating Procedure

### Standard teleoperation

1. Robot is on, PC2 image server is running (Step 5)
2. `docker compose up` is running on Host (Step 7)
3. Put on Quest 3. Open Meta Quest Browser.
4. Go to `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012`
5. Tap **Virtual Reality** → allow all XR permissions
6. You'll see the robot's D435i camera feed in the headset
7. **Align your arms** to match the robot's resting pose before starting (arms slightly forward, elbows ~90°). This prevents a jerk at start.
8. In the terminal (Host), press **`r`** — the robot begins following your movements
9. Press **`q`** to stop. The arms smoothly return to home over 5 seconds.

### Controls

| Key | Action |
|---|---|
| `r` | Start teleoperation (robot follows your motions) |
| `q` | Stop teleoperation and exit safely |
| `s` | Start recording an episode (when `RECORD=true` in .env) |
| `s` again | Stop and save the current episode |

### Recording episodes for imitation learning

Set `RECORD=true` and configure the task metadata in `.env`:

```dotenv
RECORD=true
TASK_NAME=pick_cube
TASK_GOAL=Pick up the red cube and place it in the bin.
TASK_STEPS=step1: approach; step2: open hand; step3: grasp; step4: lift; step5: place;
```

Then restart the container and follow the workflow:
```
Press r  →  robot starts tracking
Press s  →  recording starts
           ... perform the task ...
Press s  →  episode auto-saved to data/pick_cube/episode_NNNN/
Press s  →  start next episode
Press q  →  exit
```

Episode data is saved to `./data/` on the Host (mounted into the container). Each episode contains:
- `states.json` — arm joint positions (14 values @ 30Hz), hand joint positions (14 values @ 30Hz)
- `actions.json` — IK solution targets and retargeted hand joint targets
- `color_0/` — head camera BGR frames (640×480 @ 30fps)

Convert to HuggingFace LeRobot format using [unitree_IL_lerobot](https://github.com/unitreerobotics/unitree_IL_lerobot).

---

## Simulation Mode (test without the real robot)

Before touching the physical robot, test the full pipeline in simulation:

1. Install [unitree_sim_isaaclab](https://github.com/unitreerobotics/unitree_sim_isaaclab) on the Host
2. Start the simulator:
   ```bash
   conda activate unitree_sim_env
   python sim_main.py --device cpu --enable_cameras \
     --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint \
     --enable_dex3_dds --robot_type g129
   ```
3. In `.env`, set `SIM=true`
4. Start the Host container: `docker compose up`
5. Connect your Quest 3 as usual — you'll see the simulated robot

---

## Safety

> The robot arms move to match your arm positions with minimal latency. Always maintain safe working distance.

- Keep at least **2 metres** clearance around the robot during initial testing
- Have another person near the robot's **emergency stop**
- In debug mode (no `--motion`), legs and waist are locked. Only arms move.
- If the Quest 3 disconnects mid-session, the robot holds the last commanded position. Press `q` immediately.
- On `q`, arms return to the home pose over **5 seconds** — do not power off before this completes.
- Your G1 has **no waist motor**. Never set `MOTION=true` — this mode requires the waist DoF.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Quest 3 browser shows "connection refused" | Port 8012 blocked or container not running | Check `docker compose ps`, verify UFW `ufw status` |
| "Your connection is not private" on Quest 3 | SSL cert not yet trusted | Follow Step 6 — tap Advanced → Proceed |
| Quest 3 connects but no camera image | PC2 image server not running | SSH to PC2 and check container logs |
| IK solver returns no solution | Arms outside robot's workspace | Move arms to a more natural, central position |
| Arm jerks on pressing `r` | Pose mismatch at start | Align your arms to robot initial pose before pressing `r` |
| DDS connection failed | Wrong network interface | Set `NETWORK_INTERFACE=<iface>` in `.env` |
| Container exits immediately | Missing certs or bad `.env` | Check `docker compose logs host` for the error |

---

## Key Source Code (from xr_teleoperate)

| File | What it does |
|---|---|
| `teleop/teleop_hand_and_arm.py` | Main loop: reads XR data, runs IK, sends commands at 30Hz |
| `teleop/televuer/src/televuer/television.py` | WebXR server receiving Quest 3 hand/head data via Vuer |
| `teleop/televuer/src/televuer/tv_wrapper.py` | Coordinate frame conversion, smoothing, extracts wrist SE(3) |
| `teleop/robot_control/robot_arm_ik.py` | `G1_29_ArmIK`: pinocchio + CasADi IK, 7-DoF per arm |
| `teleop/robot_control/robot_arm.py` | `G1_29_ArmController`: DDS joint commands, home pose, ramp-up |
| `teleop/robot_control/hand_retargeting.py` | Maps 21 Quest 3 keypoints → 7 Dex3-1 finger joints |
| `teleop/robot_control/robot_hand_unitree.py` | `Dex3_1_Controller`: DDS publisher for finger joint targets |
| `teleop/utils/episode_writer.py` | Saves state/action/image data per timestep for IL |
| `teleop/utils/weighted_moving_filter.py` | Smooths joint velocity to prevent jitter |
