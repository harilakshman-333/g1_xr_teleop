#!/usr/bin/env bash
# =============================================================================
# HOST CONTAINER ENTRYPOINT
#
# Validates required environment variables and certificates, then launches
# the teleoperation script with the correct arguments.
#
# All arguments are passed through the .env file or docker compose environment
# section. See ../../.env for the full list of tunable parameters.
# =============================================================================

set -e

# ---------------------------------------------------------------------------
# Colour helpers for readable terminal output
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# 1. Validate SSL certificates
#    The certs volume must be mounted before starting the container.
#    Run `./scripts/gen_certs.sh` on the Host if certs don't exist yet.
# ---------------------------------------------------------------------------
info "Checking SSL certificates..."
[[ -f "${XR_TELEOP_CERT}" ]] || error "cert.pem not found at ${XR_TELEOP_CERT}. Run ./scripts/gen_certs.sh first."
[[ -f "${XR_TELEOP_KEY}"  ]] || error "key.pem not found at ${XR_TELEOP_KEY}. Run ./scripts/gen_certs.sh first."
info "SSL certificates OK."

# ---------------------------------------------------------------------------
# 2. Validate required environment variables
# ---------------------------------------------------------------------------
: "${ARM:?ARM env var is required (e.g. G1_29). Set it in .env}"
: "${EE:?EE env var is required (e.g. dex3). Set it in .env}"
: "${IMG_SERVER_IP:?IMG_SERVER_IP env var is required (e.g. 192.168.123.164). Set it in .env}"

# ---------------------------------------------------------------------------
# 3. Build the argument list for teleop_hand_and_arm.py
# ---------------------------------------------------------------------------
ARGS=(
    --arm="${ARM}"
    --ee="${EE}"
    --img-server-ip="${IMG_SERVER_IP}"
    --frequency="${FREQUENCY:-30.0}"
    --input-mode="${INPUT_MODE:-hand}"
    --display-mode="${DISPLAY_MODE:-immersive}"
)

# Optional flags — only added if the env var is set to "true"
[[ "${MOTION}"   == "true" ]] && ARGS+=(--motion)
[[ "${HEADLESS}" == "true" ]] && ARGS+=(--headless)
[[ "${SIM}"      == "true" ]] && ARGS+=(--sim)
[[ "${RECORD}"   == "true" ]] && ARGS+=(
    --record
    --task-name="${TASK_NAME:-task}"
    --task-goal="${TASK_GOAL:-perform task}"
    --task-desc="${TASK_DESC:-task description}"
    --task-steps="${TASK_STEPS:-step1: do this; step2: do that;}"
)
[[ -n "${NETWORK_INTERFACE}" ]] && ARGS+=(--network-interface="${NETWORK_INTERFACE}")
[[ "${AUTO_START}" == "true" ]] && ARGS+=(--auto-start)

# ---------------------------------------------------------------------------
# 4. Print startup summary
# ---------------------------------------------------------------------------
info "========================================================="
info "  G1 XR Teleop — Host Container"
info "========================================================="
info "  Robot arm  : ${ARM}"
info "  End-eff    : ${EE}"
info "  Input mode : ${INPUT_MODE:-hand}"
info "  Display    : ${DISPLAY_MODE:-immersive}"
info "  Img server : ${IMG_SERVER_IP}"
info "  Frequency  : ${FREQUENCY:-30.0} Hz"
info "  Record     : ${RECORD:-false}"
info "  Sim mode   : ${SIM:-false}"
info "  Motion mode: ${MOTION:-false}"
info "---------------------------------------------------------"
info "  Press [r] to start teleoperation"
info "  Press [s] to toggle recording (if --record enabled)"
info "  Press [q] to stop and exit safely"
info "========================================================="

# ---------------------------------------------------------------------------
# 5. Launch
# ---------------------------------------------------------------------------
exec python teleop_hand_and_arm.py "${ARGS[@]}"
