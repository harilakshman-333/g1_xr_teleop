# =============================================================================
# HOST CONTAINER — xr_teleoperate (G1 29DoF + Dex3-1 + Meta Quest 3)
#
# Runs on: Operator's Ubuntu 22.04 machine (x86-64)
# Purpose: Runs the main teleop loop, IK solver, hand retargeting,
#          DDS communication to the robot, and the Vuer WebXR server
#          that streams data to/from the Meta Quest 3.
#
# Uses micromamba (lightweight conda) to replicate the project's exact
# conda environment: pinocchio=3.1.0 + numpy=1.26.4 from conda-forge.
# This matches the original project's setup exactly and avoids the
# robotpkg apt repository which does not support Ubuntu 22.04 Jammy.
#
# Build:  docker compose build host
# Run:    docker compose up host
# =============================================================================

# mambaorg/micromamba:jammy tag unavailable; install micromamba into ubuntu:22.04 directly.
FROM ubuntu:22.04

# Run system-level installs as root
# (ubuntu:22.04 starts as root by default)

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ---------------------------------------------------------------------------
# 1. System dependencies
#    - python3.10  : required by pinocchio conda pin (we replicate version here)
#    - libGL / libX: needed by OpenCV display and meshcat visualizer
#    - libeigen3   : pinocchio's C++ backend header dependency
#    - openssl     : certificate generation (also used at runtime by televuer)
#    - git / curl  : cloning submodules inside the build
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        python3.10-dev \
        python3-pip \
        python3.10-venv \
        git \
        curl \
        wget \
        bzip2 \
        openssl \
        ca-certificates \
        libeigen3-dev \
        libboost-all-dev \
        libgl1-mesa-glx \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libasound2 \
        ufw \
        iproute2 \
        net-tools \
        iputils-ping \
        ssh \
        rsync \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 2. Install micromamba — lightweight conda package manager
#    micromamba can install from conda-forge without a full Anaconda/Miniconda.
#    This is the official single-binary install method.
# ---------------------------------------------------------------------------
RUN curl -L https://micro.mamba.pm/api/micromamba/linux-64/latest \
      | tar -xvj -C /usr/local/bin --strip-components=1 bin/micromamba

ENV MAMBA_ROOT_PREFIX=/opt/conda
ENV PATH="/opt/conda/bin:/opt/conda/envs/tv/bin:${PATH}"

# ---------------------------------------------------------------------------
# 3. Conda environment — mirrors the project's original conda create command:
#
#    conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge
#
#    CasADi is included here as well (IK optimisation backend used by
#    robot_arm_ik.py). conda-forge provides a clean, compatible build.
# ---------------------------------------------------------------------------
COPY environment.yml /tmp/environment.yml
RUN micromamba create -y -f /tmp/environment.yml -p /opt/conda/envs/tv \
 && micromamba clean -y --all

# Activate the 'tv' conda env for all subsequent RUN commands and at runtime
ARG MAMBA_DOCKERFILE_ACTIVATE=1
ENV MAMBA_DEFAULT_ENV=tv
ENV PATH="/opt/conda/envs/tv/bin:${PATH}"
ENV CONDA_DEFAULT_ENV=tv

# ---------------------------------------------------------------------------
# 3. Clone xr_teleoperate and its submodules
#    We clone at build time so the image is self-contained.
#    Submodules:
#      - teleop/teleimager : ZMQ image client (receives D435i frames from PC2)
#      - teleop/televuer   : Vuer WebXR server (talks to Meta Quest 3)
# ---------------------------------------------------------------------------
WORKDIR /opt
RUN git clone --depth 1 https://github.com/unitreerobotics/xr_teleoperate.git \
 && cd xr_teleoperate \
 && git submodule update --init --depth 1

WORKDIR /opt/xr_teleoperate

# ---------------------------------------------------------------------------
# 4. Install Python submodule packages
#    teleimager first (--no-deps to avoid version conflicts with numpy pin)
#    televuer second (includes Vuer, asyncio WebSocket server, WebRTC)
# ---------------------------------------------------------------------------
RUN pip install -e teleop/teleimager --no-deps \
 && pip install 'params-proto==2.13.2' \
 && pip install -e teleop/televuer \
 && pip install 'vuer[all]==0.0.60' \
 && pip install -e teleop/robot_control/dex-retargeting

# ---------------------------------------------------------------------------
# 5. Install Unitree robot SDK (unitree_sdk2_python)
#    This provides the DDS channel primitives used to command arm joints
#    and receive motor state over the robot's CycloneDDS middleware.
#    Pinned to a commit >= 404fe44 (required for v1.1+)
# ---------------------------------------------------------------------------
RUN git clone https://github.com/unitreerobotics/unitree_sdk2_python.git /opt/unitree_sdk2_python \
 && cd /opt/unitree_sdk2_python \
 && git checkout 404fe44d76f705c002c97e773276f2a8fefb57e4 \
 && pip install -e .

# ---------------------------------------------------------------------------
# 6. Install remaining Python requirements from xr_teleoperate
# ---------------------------------------------------------------------------
RUN pip install -r /opt/xr_teleoperate/requirements.txt

# ---------------------------------------------------------------------------
# 7. Additional utilities
#    - meshcat       : 3D visualiser (optional, used for debugging IK)
#    - rerun-sdk     : used by rerun_visualizer.py to replay recorded data
#    - sshkeyboard   : listens for r/s/q keypresses in the terminal
#    - pyzmq         : ZMQ transport between image client and image server
#    - psutil        : optional CPU affinity mode (--affinity flag)
# ---------------------------------------------------------------------------
RUN pip install meshcat rerun-sdk sshkeyboard pyzmq psutil

# ---------------------------------------------------------------------------
# 8. SSL certificate handling
#     The cert files are expected at /certs/cert.pem and /certs/key.pem.
#     These are mounted in at runtime via docker compose volumes.
#     The televuer library reads from:
#       - ~/.config/xr_teleoperate/cert.pem  (preferred)
#       - XR_TELEOP_CERT / XR_TELEOP_KEY env vars (alternative)
#     We configure the env vars here; the actual files come from the volume.
# ---------------------------------------------------------------------------
ENV XR_TELEOP_CERT="/certs/cert.pem"
ENV XR_TELEOP_KEY="/certs/key.pem"

# ---------------------------------------------------------------------------
# 9. Working directory, exposed port, and entrypoint
# ---------------------------------------------------------------------------
WORKDIR /opt/xr_teleoperate/teleop

# Port 8012: televuer WebSocket/WebRTC (Quest 3 connects here)
EXPOSE 8012

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
