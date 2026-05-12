#!/usr/bin/env bash
# =============================================================================
# PC2 CONTAINER ENTRYPOINT
#
# Validates SSL certificates and camera config, then starts the
# teleimager image server which:
#   - Captures frames from the G1's head RealSense D435i
#   - Publishes frames over ZMQ to the Host's image client
#   - Optionally serves a WebRTC stream for direct Quest 3 preview
# =============================================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# Validate SSL certificates (required for WebRTC preview endpoint)
# ---------------------------------------------------------------------------
info "Checking SSL certificates..."
[[ -f "${XR_TELEOP_CERT}" ]] || error "cert.pem not found at ${XR_TELEOP_CERT}."
[[ -f "${XR_TELEOP_KEY}"  ]] || error "key.pem not found at ${XR_TELEOP_KEY}."
info "SSL certificates OK."

# ---------------------------------------------------------------------------
# Validate camera config
# ---------------------------------------------------------------------------
CONFIG_FILE="${CAM_CONFIG:-/config/cam_config_server.yaml}"
[[ -f "${CONFIG_FILE}" ]] || error "Camera config not found at ${CONFIG_FILE}."
info "Camera config: ${CONFIG_FILE}"

# ---------------------------------------------------------------------------
# Startup summary
# ---------------------------------------------------------------------------
info "========================================================="
info "  G1 XR Teleop — PC2 Image Server"
info "========================================================="
info "  ZMQ port    : ${ZMQ_PORT:-5555}"
info "  WebRTC port : 60001"
info "  Cam config  : ${CONFIG_FILE}"
info "========================================================="

# ---------------------------------------------------------------------------
# Start teleimager image server
# ---------------------------------------------------------------------------
exec python -m teleimager.image_server --config "${CONFIG_FILE}"
