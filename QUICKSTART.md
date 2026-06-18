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
*(Tip: Verify the feed by opening `https://192.168.123.164:60001` in your Quest 3 browser, bypassing the SSL warning, and clicking **Start**).*

### 2️⃣ Launch the Teleop System
On your Host PC terminal, bring up the teleoperation container:
```bash
docker compose up
```

### 3️⃣ Jump into VR
1. Put on your **Quest 3** and open the **Meta Quest Browser**.
2. Navigate to your Host IP: `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012`
3. Click the **Virtual Reality** button at the bottom of the page to enter VR mode and enable hand tracking.
4. **Align your arms** with the robot's default rest posture (elbows at ~90 degrees, hands slightly forward).
5. In your Host PC terminal, press **`r`** to start teleoperating!
6. When finished, press **`q`** to safely stop and return the robot to its home posture.

---

## 📋 First-Time Prerequisites

Before starting your very first setup, please make sure:
1. The **G1 Robot** is powered on, fully booted, and in standalone mode.
2. The **Host PC** (running Ubuntu 22.04) is connected via Ethernet directly to the robot's network (or bridged via a router).
3. The **Meta Quest 3** is connected to the same WiFi network as your Host PC.
4. **Docker** and **Docker Compose** are installed on both the Host PC and the G1's PC2.

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
The Meta Quest Browser requires secure connections (HTTPS/WSS) for WebXR features to work. Generate a self-signed certificate:
```bash
chmod +x scripts/gen_certs.sh
./scripts/gen_certs.sh
```
**Trusting the certificate on your Quest 3:**
1. Put on the headset and open the **Meta Quest Browser**.
2. Navigate to: `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012` *(Change the IP if your Host IP is different).*
3. Tap **Advanced** → **Proceed to <IP> (unsafe)**. This saves a security exception on the headset so it won't block you next time!

### 4. Build the Host Container
Finally, build the host teleop container before running the Fast Track steps above:
```bash
docker compose build
```

---

## 🖥️ Simulation Mode (Testing Without the Robot)

Don't have the physical robot ready? No problem! You can test the entire pipeline in simulation:

1. Run [unitree_sim_isaaclab](https://github.com/unitreerobotics/unitree_sim_isaaclab) on your Host PC:
   ```bash
   conda activate unitree_sim_env
   python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint --enable_dex3_dds --robot_type g129
   ```
2. In your `.env` file, change the setting to `SIM=true`.
3. Start the host container:
   ```bash
   docker compose up
   ```
4. Connect the Quest 3 browser to the host IP and test VR just like you would on the real robot!
