# Quick Start Guide: G1 XR Teleoperation

This guide provides the minimum steps to get teleoperation running on the Unitree G1 robot using the Meta Quest 3 headset.

---

## 📋 Prerequisites

Before starting, ensure:
1. The **G1 Robot** is powered on, booted, and in standalone mode.
2. The **Host PC** (Ubuntu 22.04) is connected via Ethernet to the robot's network (or via a router bridging them).
3. The **Meta Quest 3** is connected to the same WiFi network as the Host PC.
4. **Docker** and **Docker Compose** are installed on both the Host PC and the G1's PC2.

---

## 🚀 Step-by-Step Setup

### 1. Configure the Environment
Copy the example environment file and configure your settings:
```bash
cp .env.example .env
```
Open `.env` and verify the critical fields:
* `NETWORK_INTERFACE`: Set this to your Ethernet interface name connected to the robot (find it via `ip link show`).
* `ARM=G1_29`
* `EE=dex3`
* `INPUT_MODE=hand`
* `IMG_SERVER_IP=192.168.123.164` (Default PC2 IP)

### 2. Configure the Network Interface
Assign the static IP `192.168.123.2` to your Ethernet interface:
```bash
chmod +x scripts/setup_network.sh
sudo ./scripts/setup_network.sh
```
*Verify connection:*
```bash
ping 192.168.123.164
```

### 3. Generate and Trust SSL Certificates
Since Meta Quest Browser requires HTTPS/WSS for WebXR features, generate a self-signed certificate:
```bash
chmod +x scripts/gen_certs.sh
./scripts/gen_certs.sh
```
**Trusting the certificate on Quest 3:**
1. Put on your Meta Quest 3 headset.
2. Open the **Meta Quest Browser**.
3. Navigate to: `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012` (replace with your Host IP if different).
4. Tap **Advanced** → **Proceed to <IP> (unsafe)**. This saves the security exception on the headset.

### 4. Deploy the Camera Server to the Robot (PC2)
Deploy and run the image server container on the G1's PC2:
```bash
chmod +x scripts/deploy_to_pc2.sh
./scripts/deploy_to_pc2.sh
```
*Verify:* Open `https://192.168.123.164:60001` in your headset browser, bypass the SSL warning, and click **Start**. You should see the RealSense camera feed.

### 5. Build and Launch the Host Teleop Container
On your Host PC, run:
```bash
docker compose build
docker compose up
```

---

## 🎮 Running the Demo

1. Put on the **Quest 3** headset and open the **Meta Quest Browser**.
2. Navigate to:
   ```
   https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012
   ```
3. Click the **Virtual Reality** button at the bottom of the page to enter VR mode and allow access to hand tracking.
4. **Align your arms** with the robot's default rest posture (elbows at ~90 degrees, slightly forward).
5. In your Host PC terminal, press **`r`** to start tracking and teleoperating.
6. Press **`q`** to stop and return the robot safely to its home posture.

---

## 🖥️ Simulation Mode (Testing Without Robot)

If you don't have the physical robot ready, you can test the entire pipeline in simulation:
1. Run [unitree_sim_isaaclab](https://github.com/unitreerobotics/unitree_sim_isaaclab) on the Host PC:
   ```bash
   conda activate unitree_sim_env
   python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint --enable_dex3_dds --robot_type g129
   ```
2. In `.env`, set `SIM=true`.
3. Start the host container:
   ```bash
   docker compose up
   ```
4. Connect the Quest 3 browser to the host IP as described in step 2.
