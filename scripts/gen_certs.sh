#!/usr/bin/env bash
# =============================================================================
# scripts/gen_certs.sh — SSL Certificate Generator
#
# Generates self-signed TLS certificates required by:
#   1. televuer (WebSocket/WebRTC server on port 8012) — Quest 3 connects here
#   2. teleimager (WebRTC preview server on port 60001) — optional camera check
#
# The Meta Quest 3 browser will show a "Your connection is not private" warning
# on first connection. Click Advanced → Proceed to accept the self-signed cert.
# This trust decision is remembered per certificate per device.
#
# Output files (written to ../certs/):
#   cert.pem  — Public certificate (share to devices that need to trust it)
#   key.pem   — Private key      (keep secret, never commit to git)
#
# Usage:
#   chmod +x scripts/gen_certs.sh
#   ./scripts/gen_certs.sh
#   ./scripts/gen_certs.sh --host-ip 192.168.1.50   # override auto-detected IP
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve project root (one level above this script's directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
CERTS_DIR="${PROJECT_ROOT}/certs"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
HOST_IP=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host-ip) HOST_IP="$2"; shift 2 ;;
        *) error "Unknown argument: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Auto-detect the Host IP on the robot-facing network interface
# We look for a 192.168.123.x address first (robot subnet), then fall back
# to any non-loopback IPv4 address.
# ---------------------------------------------------------------------------
section "Detecting Host IP address"

if [[ -z "${HOST_IP}" ]]; then
    # Try robot subnet first (192.168.123.x)
    HOST_IP=$(ip -4 addr show | grep -oP '192\.168\.123\.\d+' | head -1 || true)

    if [[ -z "${HOST_IP}" ]]; then
        # Fall back to first non-loopback IPv4
        HOST_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127\.0\.0\.1' | head -1 || true)
    fi

    if [[ -z "${HOST_IP}" ]]; then
        error "Could not auto-detect Host IP. Run with: --host-ip <your-ip>"
    fi

    info "Auto-detected Host IP: ${HOST_IP}"
    warn "If this is wrong, re-run: ./scripts/gen_certs.sh --host-ip <correct-ip>"
else
    info "Using provided Host IP: ${HOST_IP}"
fi

# ---------------------------------------------------------------------------
# Check openssl is available
# ---------------------------------------------------------------------------
command -v openssl &>/dev/null || error "openssl is not installed. Run: sudo apt install openssl"

# ---------------------------------------------------------------------------
# Create output directory
# ---------------------------------------------------------------------------
section "Preparing certificates directory"
mkdir -p "${CERTS_DIR}"
info "Output directory: ${CERTS_DIR}"

# Warn if certs already exist
if [[ -f "${CERTS_DIR}/cert.pem" ]]; then
    warn "cert.pem already exists. It will be overwritten."
    warn "If you have already trusted this certificate on your Quest 3,"
    warn "you will need to trust the new one again."
    echo ""
    read -rp "Continue? [y/N] " confirm
    [[ "${confirm}" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }
fi

# ---------------------------------------------------------------------------
# Generate the SAN config file
# SubjectAltName (SAN) is required by modern browsers (Quest 3 included).
# Without SAN, the browser will reject the cert even after manual trust.
# ---------------------------------------------------------------------------
section "Generating certificate"

SAN_CONFIG="${CERTS_DIR}/san.cnf"
cat > "${SAN_CONFIG}" <<EOF
[req]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
x509_extensions    = v3_req

[dn]
C  = US
ST = State
L  = City
O  = G1XRTeleop
CN = ${HOST_IP}

[v3_req]
subjectAltName = @alt_names
keyUsage       = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = localhost
IP.1  = 127.0.0.1
IP.2  = ${HOST_IP}
EOF

info "SAN config written to: ${SAN_CONFIG}"

# ---------------------------------------------------------------------------
# Generate private key and self-signed certificate in one step
# Validity: 365 days (re-run this script annually or as needed)
# ---------------------------------------------------------------------------
openssl req \
    -x509 \
    -nodes \
    -newkey rsa:2048 \
    -keyout "${CERTS_DIR}/key.pem" \
    -out    "${CERTS_DIR}/cert.pem" \
    -days   365 \
    -config "${SAN_CONFIG}" \
    -extensions v3_req

# ---------------------------------------------------------------------------
# Lock down key permissions
# ---------------------------------------------------------------------------
chmod 600 "${CERTS_DIR}/key.pem"
chmod 644 "${CERTS_DIR}/cert.pem"

# ---------------------------------------------------------------------------
# Done — print next steps
# ---------------------------------------------------------------------------
section "Certificates generated successfully"
info "  ${CERTS_DIR}/cert.pem  (public certificate)"
info "  ${CERTS_DIR}/key.pem   (private key — do NOT commit to git)"

echo ""
echo -e "${CYAN}Next steps:${NC}"
echo ""
echo "  1. Copy certs to robot PC2 (run from Host):"
echo -e "     ${GREEN}scp certs/cert.pem certs/key.pem unitree@192.168.123.164:~/g1_xr_teleop/certs/${NC}"
echo ""
echo "  2. On your Meta Quest 3, open Meta Quest Browser and visit:"
echo -e "     ${GREEN}https://${HOST_IP}:8012/?ws=wss://${HOST_IP}:8012${NC}"
echo "     Accept the security warning (Advanced → Proceed) to trust the cert."
echo "     This only needs to be done once per certificate."
echo ""
echo "  3. Build and start the Host container:"
echo -e "     ${GREEN}docker compose up --build${NC}"
echo ""
