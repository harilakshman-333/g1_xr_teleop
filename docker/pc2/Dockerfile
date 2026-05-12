# =============================================================================
# PC2 CONTAINER — teleimager image server (G1 onboard development unit)
#
# Runs on: The G1 robot's onboard Development Computing Unit (PC2)
#          IP: 192.168.123.164 (fixed on the robot's internal network)
#
# Purpose: Captures frames from the G1's head RealSense D435i camera,
#          optionally from wrist cameras, and streams them to the Host
#          via ZMQ (default) or WebRTC (lower latency, optional).
#
# The Meta Quest 3 can also receive a WebRTC preview stream directly
# from this container for verifying camera feed before teleoperation.
#
# Build:  docker compose -f docker-compose.pc2.yml build pc2
# Run:    docker compose -f docker-compose.pc2.yml up pc2
# =============================================================================

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ---------------------------------------------------------------------------
# 1. System dependencies
#    - librealsense2 : Intel RealSense SDK for D435i head camera
#    - python3.10    : runtime
#    - libssl        : WebRTC / HTTPS certificate handling
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        python3.10-dev \
        python3-pip \
        git \
        curl \
        wget \
        openssl \
        ca-certificates \
        libssl-dev \
        libusb-1.0-0-dev \
        libglfw3-dev \
        libgl1-mesa-dev \
        libglu1-mesa-dev \
        libgtk-3-dev \
        pkg-config \
        cmake \
        build-essential \
        udev \
        iproute2 \
        net-tools \
    && rm -rf /var/lib/apt/lists/*

# Make python3.10 default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 \
 && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 \
 && python -m pip install --upgrade pip setuptools wheel

# ---------------------------------------------------------------------------
# 2. Intel RealSense SDK (librealsense2)
#    Required for the D435i head camera and optional D405 wrist cameras.
#    Installed from Intel's official apt repository.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
        gnupg2 \
        lsb-release \
 && curl -fsSL https://librealsense.intel.com/Debian/librealsense.pgp \
        | gpg --dearmor -o /usr/share/keyrings/realsense-archive-keyring.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/realsense-archive-keyring.gpg] \
        https://librealsense.intel.com/Debian/apt-repo $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/librealsense.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        librealsense2 \
        librealsense2-udev-rules \
        librealsense2-utils \
        python3-pyrealsense2 \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 3. Clone teleimager (the image server component)
#    This is the same submodule used by the Host, but here we run the
#    *server* side (image_server.py) instead of the client.
# ---------------------------------------------------------------------------
RUN git clone --depth 1 https://github.com/silencht/teleimager.git /opt/teleimager
WORKDIR /opt/teleimager
RUN pip install -e .

# ---------------------------------------------------------------------------
# 4. Python packages
#    - pyzmq   : ZMQ transport (primary: Host subscribes to frames via ZMQ)
#    - aiortc  : WebRTC for optional direct-to-Quest-3 preview stream
#    - opencv  : frame capture / colour conversion
#    - numpy   : array handling (pinned for consistency with Host image)
# ---------------------------------------------------------------------------
RUN pip install \
    "numpy==1.26.4" \
    pyzmq \
    aiortc \
    "opencv-python-headless>=4.8" \
    aiohttp \
    aiohttp-cors

# ---------------------------------------------------------------------------
# 5. SSL certificates
#    Certs are generated on the Host and copied here (see setup guide).
#    Mounted at /certs at runtime.
# ---------------------------------------------------------------------------
ENV XR_TELEOP_CERT="/certs/cert.pem"
ENV XR_TELEOP_KEY="/certs/key.pem"

# ---------------------------------------------------------------------------
# 6. Camera config
#    cam_config_server.yaml is mounted at runtime from the configs/ directory.
#    Default path expected by teleimager.
# ---------------------------------------------------------------------------
VOLUME ["/certs", "/config"]

# Port 60001 : WebRTC offer endpoint (Quest 3 browser preview)
# Port 5555  : ZMQ PUB socket (Host image client subscribes here)
EXPOSE 60001 5555

WORKDIR /opt/teleimager

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
