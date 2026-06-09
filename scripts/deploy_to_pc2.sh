#!/usr/bin/env bash
# =============================================================================
# scripts/deploy_to_pc2.sh — Deploy PC2 image server to the robot
#
# Copies the required files to the G1's onboard Development Computing Unit
# (PC2 at 192.168.123.164) and starts the image server Docker container there.
#
# Run this from the Host machine after completing network setup.
#
# Usage:
#   chmod +x scripts/deploy_to_pc2.sh
#   ./scripts/deploy_to_pc2.sh
#   ./scripts/deploy_to_pc2.sh --rebuild   # force docker rebuild on PC2
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

PC2_IP="${PC2_IP:-192.168.123.164}"
PC2_USER="${PC2_USER:-unitree}"
PC2_DIR="${PC2_DIR:-~/g1_xr_teleop}"
REBUILD=false
PC2_SUDO_PASS="${PC2_SUDO_PASS:-123}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rebuild) REBUILD=true; shift ;;
        *) error "Unknown argument: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
section "Pre-flight checks"

[[ -f "${PROJECT_ROOT}/certs/cert.pem" ]] || \
    error "certs/cert.pem not found. Run ./scripts/gen_certs.sh first."
[[ -f "${PROJECT_ROOT}/certs/key.pem" ]] || \
    error "certs/key.pem not found. Run ./scripts/gen_certs.sh first."

ping -c 1 -W 2 "${PC2_IP}" &>/dev/null || \
    error "Cannot reach PC2 at ${PC2_IP}. Run ./scripts/setup_network.sh first."

info "PC2 is reachable at ${PC2_IP} ✓"

# ---------------------------------------------------------------------------
# Create directory structure on PC2
# ---------------------------------------------------------------------------
section "Creating directory structure on PC2"
ssh "${PC2_USER}@${PC2_IP}" "mkdir -p ${PC2_DIR}/{certs,configs,data,docker/pc2}"
info "Directories created on PC2."

# ---------------------------------------------------------------------------
# Ensure unitree user is in the docker group (required to run docker without sudo)
# ---------------------------------------------------------------------------
section "Ensuring docker group membership on PC2"
ssh "${PC2_USER}@${PC2_IP}" \
    "echo '${PC2_SUDO_PASS}' | sudo -S usermod -aG docker ${PC2_USER} 2>&1 || true"
info "Docker group membership confirmed (will take effect on next SSH login)."

# ---------------------------------------------------------------------------
# Copy SSL certificates
# ---------------------------------------------------------------------------
section "Copying SSL certificates to PC2"
scp "${PROJECT_ROOT}/certs/cert.pem" \
    "${PROJECT_ROOT}/certs/key.pem" \
    "${PC2_USER}@${PC2_IP}:${PC2_DIR}/certs/"
info "Certificates copied."

# ---------------------------------------------------------------------------
# Copy camera config
# ---------------------------------------------------------------------------
section "Copying camera configuration"
scp "${PROJECT_ROOT}/configs/cam_config_server.yaml" \
    "${PC2_USER}@${PC2_IP}:${PC2_DIR}/configs/"
info "Camera config copied."

# ---------------------------------------------------------------------------
# Copy PC2 docker files
# ---------------------------------------------------------------------------
section "Copying Docker files to PC2"
scp "${PROJECT_ROOT}/docker-compose.pc2.yml" \
    "${PC2_USER}@${PC2_IP}:${PC2_DIR}/"
rsync -avz --progress \
    "${PROJECT_ROOT}/docker/pc2/" \
    "${PC2_USER}@${PC2_IP}:${PC2_DIR}/docker/pc2/"
info "Docker files copied."

# ---------------------------------------------------------------------------
# Ensure standalone docker-compose is installed on PC2.
# The PC2 runs an old Docker Engine (pre-20.10) that does not support
# the CLI plugin mechanism — so we install docker-compose as a plain
# standalone binary in /usr/local/bin/ instead.
# ---------------------------------------------------------------------------
section "Installing docker-compose on PC2 (standalone, aarch64-aware)"

ssh "${PC2_USER}@${PC2_IP}" \
    "echo '${PC2_SUDO_PASS}' | sudo -S bash -s" << 'REMOTE'
set -e
ARCH=$(uname -m)
DEST=/usr/local/bin/docker-compose
# Remove any stale plugin-directory binaries that confuse old Docker
rm -f /home/unitree/.docker/cli-plugins/docker-compose \
       /usr/local/lib/docker/cli-plugins/docker-compose 2>/dev/null || true
# Download the correct architecture standalone binary
URL="https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}"
echo "[INFO] Downloading docker-compose for ${ARCH} -> ${DEST}"
curl -fsSL "${URL}" -o "${DEST}"
chmod +x "${DEST}"
echo "[INFO] $(docker-compose version)"
REMOTE

COMPOSE_CMD="sudo docker-compose"
info "Using compose command: ${COMPOSE_CMD}"

# ---------------------------------------------------------------------------
# Build and start the image server container on PC2
# ---------------------------------------------------------------------------
section "Starting PC2 image server container"

BUILD_FLAG=""
[[ "${REBUILD}" == "true" ]] && BUILD_FLAG="--build"

ssh "${PC2_USER}@${PC2_IP}" \
    "cd ${PC2_DIR} && echo '${PC2_SUDO_PASS}' | sudo -S docker-compose -f docker-compose.pc2.yml up ${BUILD_FLAG} -d"

info "PC2 image server started."

# ---------------------------------------------------------------------------
# Verify it's running
# ---------------------------------------------------------------------------
sleep 3
section "Verifying PC2 container status"
ssh "${PC2_USER}@${PC2_IP}" \
    "echo '${PC2_SUDO_PASS}' | sudo -S docker-compose -f ${PC2_DIR}/docker-compose.pc2.yml ps"

echo ""
info "Deployment complete!"
echo ""
echo -e "${CYAN}To view PC2 image server logs:${NC}"
echo -e "  ${GREEN}ssh ${PC2_USER}@${PC2_IP}"
echo -e "  sudo docker-compose -f ${PC2_DIR}/docker-compose.pc2.yml logs -f${NC}"
echo ""
echo -e "${CYAN}To verify camera stream (from your Host browser first, then Quest):${NC}"
echo -e "  ${GREEN}https://${PC2_IP}:60001${NC}"
echo ""


