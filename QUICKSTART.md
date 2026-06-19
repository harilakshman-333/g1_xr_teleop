# 🚀 Quick Start Guide: G1 XR Teleoperation

Welcome to the **G1 XR Teleoperation** project! This guide will get you up and running with the Meta Quest 3 headset to control the Unitree G1 robot. 

---

## ⚡ Already Set Up? Fast Track

If you have already gone through the initial environment and network configuration and just want to jump into the demo, run these steps:

### 1️⃣ Start the Camera Server
Deploy and run the image server container directly on the G1's PC2:
```bash
./scripts/deploy_to_pc2.sh
```
> **Verify:** Open `https://192.168.123.164:60001` in your Quest 3 browser, bypass the SSL warning, and click **Start**. You should see the robot's camera feed.

### 2️⃣ Launch the Teleop System
On your Host PC terminal, bring up the teleoperation container:
```bash
docker compose up
```

### 3️⃣ Put the Robot in Debug Mode
The robot's locomotion controller blocks direct arm commands by default. You must bypass it with the physical controller before the software can move the arms.

> **The robot must be suspended in a harness before this step.**

| Step | Button Combo | Result |
|------|--------------|--------|
| 1 | `L1 + A` | Robot goes limp (damping mode) |
| 2 | `L2 + R2` (simultaneously) | Enters debug mode — locomotion controller suspended |
| 3 | `L2 + A` | ✅ Robot moves to diagnostic pose → debug mode confirmed |
| 4 | `L2 + B` | Arms return to rest |
| 5 | `L2 + R2` again | Re-enter debug mode (required after each pose reset) |

If the robot does **not** move on step 3, re-press `L2 + R2` and try again.

### 4️⃣ Jump into VR
1. Put on your **Quest 3** and open the **Meta Quest Browser**.
2. Navigate to: `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012`
3. Click the **Virtual Reality** button to enter VR mode and enable hand tracking.
4. **Align your arms** with the robot's resting posture (elbows at ~90°, hands slightly forward) to prevent a jerk when starting.
5. In your Host PC terminal, press **`r`** to begin teleoperation.
6. When finished, press **`q`** to stop — the robot returns to its home posture over 5 seconds.

---

## 📋 First-Time Prerequisites

Before starting your very first setup, make sure:

| # | Requirement |
|---|-------------|
| 1 | G1 Robot is powered on, fully booted, and in standalone mode |
| 2 | Host PC (Ubuntu 22.04) is connected via Ethernet to the robot's network |
| 3 | Meta Quest 3 is on the same WiFi network as the Host PC |
| 4 | Docker Engine 24+ and Docker Compose v2 are installed on the Host PC |
| 5 | Docker Engine is installed on the G1's PC2 (pre-installed on EDU units) |

---

## 🛠️ Step-by-Step Initial Setup

### 1. Configure the Environment
Copy the example environment file to create your own configuration:
```bash
cp .env.example .env
```
Open `.env` in your favorite editor and verify these critical fields:
* `NETWORK_INTERFACE`: Set this to your Ethernet interface name connected to the robot (find it by running `ip link show`).
* `ARM`: `G1_29`
* `EE`: `dex3`
* `INPUT_MODE`: `hand`
* `IMG_SERVER_IP`: `192.168.123.164` (Default PC2 IP)

### 2. Configure the Network Interface
Assign the static IP `192.168.123.2` to your Host PC's Ethernet interface:
```bash
chmod +x scripts/setup_network.sh
sudo ./scripts/setup_network.sh
```
*Verify your connection to the robot:*
```bash
ping 192.168.123.164
```

### 3. Generate & Trust SSL Certificates
The Meta Quest Browser requires HTTPS/WSS for WebXR. Generate a self-signed certificate:
```bash
chmod +x scripts/gen_certs.sh
./scripts/gen_certs.sh
```
**Trusting the certificate on your Quest 3:**
1. Put on the headset and open the **Meta Quest Browser**.
2. Navigate to: `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012`
   *(Adjust the IP if your Host is on a different address.)*
3. Tap **Advanced** → **Proceed to (unsafe)**. This stores the security exception so future sessions connect without prompts.

### 4. Build the Host Container
Finally, build the host teleop container before running the Fast Track steps above:
```bash
docker compose build
```

---

## 🖥️ Simulation Mode (Test Without the Robot)

You can test the full pipeline in simulation before touching the physical robot:

1. Start [unitree_sim_isaaclab](https://github.com/unitreerobotics/unitree_sim_isaaclab) on your Host PC:
   ```bash
   conda activate unitree_sim_env
   python sim_main.py --device cpu --enable_cameras \
     --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint \
     --enable_dex3_dds --robot_type g129
   ```
2. Set `SIM=true` in your `.env` file.
3. Start the host container:
   ```bash
   docker compose up
   ```
4. Connect the Quest 3 browser as normal — you'll see the simulated robot.

> **Note:** Simulation mode does not require the debug mode step (Step 3 above).
