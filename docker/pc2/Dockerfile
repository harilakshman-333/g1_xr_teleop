# =============================================================================
# PC2 CONTAINER — teleimager image server (G1 onboard development unit)
#
# Runs on: The G1 robot's onboard Development Computing Unit (PC2)
#          IP: 192.168.123.164 (fixed on the robot's internal network)
#
# Build:  docker-compose -f docker-compose.pc2.yml build pc2
# Run:    docker-compose -f docker-compose.pc2.yml up pc2
# =============================================================================

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ---------------------------------------------------------------------------
# 1. System dependencies
#    libusb-1.0-0-dev : required by pupil-labs-uvc at build time
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
        libusb-1.0-0 \
        libusb-1.0-0-dev \
        libgl1-mesa-glx \
        libglib2.0-0 \
        udev \
        iproute2 \
        net-tools \
        libturbojpeg0-dev \
    && rm -rf /var/lib/apt/lists/*

# Make python3.10 default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 \
 && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 \
 && python -m pip install --upgrade pip setuptools wheel

# ---------------------------------------------------------------------------
# 2. Intel RealSense SDK — via pip (bundles aarch64 native libs, no apt repo needed)
# ---------------------------------------------------------------------------
RUN pip install pyrealsense2

# ---------------------------------------------------------------------------
# 3. Pin logging_mp to 0.1.6 — teleimager uses the old get_logger(name, level=)
#    API which was removed in 0.2.x. Install before teleimager to avoid the
#    newer version being pulled in as a dependency.
# ---------------------------------------------------------------------------
RUN pip install "logging_mp==0.1.6"

# ---------------------------------------------------------------------------
# 4. Clone teleimager and install with [server] extras.
#    [server] pulls in: aiohttp, aiortc, pupil-labs-uvc (provides uvc module)
# ---------------------------------------------------------------------------
RUN git clone --depth 1 https://github.com/silencht/teleimager.git /opt/teleimager
WORKDIR /opt/teleimager
RUN pip install -e ".[server]"

# ---------------------------------------------------------------------------
# 5. Additional packages
# ---------------------------------------------------------------------------
RUN pip install \
    "numpy==1.26.4" \
    pyzmq \
    "opencv-python-headless>=4.8" \
    aiohttp-cors

# ---------------------------------------------------------------------------
# 6. SSL certificates — mounted at /certs at runtime
# ---------------------------------------------------------------------------
ENV XR_TELEOP_CERT="/certs/cert.pem"
ENV XR_TELEOP_KEY="/certs/key.pem"

VOLUME ["/certs", "/config"]

EXPOSE 60001 5555

WORKDIR /opt/teleimager

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
