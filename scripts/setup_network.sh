#!/usr/bin/env bash
# =============================================================================
# scripts/setup_network.sh — Network Configuration Helper
#
# Configures the Host machine's Ethernet interface for direct robot comms.
#
# Network topology for this project:
#
#   [Meta Quest 3] ─── WiFi ───► [WiFi Router] ─── Ethernet ──► [Host PC]
#                                                                     │
#                                                               Ethernet
#                                                                     │
#                                                           [G1 Robot network]
#                                                              /          \
#                                                          [PC2]         [MCU]
#                                                    192.168.123.164  192.168.123.x
#
# The G1 robot runs an internal network at 192.168.123.x.
# The Host must have a static IP on this subnet to:
#   - SSH into PC2 (robot's onboard compute unit)
#   - Send DDS joint commands via CycloneDDS
#   - Receive ZMQ image frames from the PC2 image server
#
# The Quest 3 connects via WiFi to a router that should bridge to the
# 192.168.123.x subnet so the Quest can reach the Host at port 8012.
#
# Usage:
#   chmod +x scripts/setup_network.sh
#   sudo ./scripts/setup_network.sh
#   sudo ./scripts/setup_network.sh --iface enp3s0 --ip 192.168.123.2
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Must run as root (requires ip / nmcli commands)
# ---------------------------------------------------------------------------
[[ "${EUID}" -eq 0 ]] || { echo "Re-run as root: sudo $0 $*"; exit 1; }

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

# ---------------------------------------------------------------------------
# Defaults (can be overridden with flags)
# ---------------------------------------------------------------------------
HOST_IP="192.168.123.2"      # Host's IP on the robot subnet
ROBOT_PC2_IP="192.168.123.164"
IFACE=""                     # Auto-detect if blank

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --iface) IFACE="$2"; shift 2 ;;
        --ip)    HOST_IP="$2"; shift 2 ;;
        *) error "Unknown argument: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Auto-detect Ethernet interface (prefer the one with a cable plugged in)
# ---------------------------------------------------------------------------
section "Detecting Ethernet interface"

if [[ -z "${IFACE}" ]]; then
    # Find first connected ethernet interface (state UP, not lo/wl*/docker*/veth*)
    IFACE=$(ip link show | \
        awk '/^[0-9]+: /{iface=$2} /state UP/{print iface}' | \
        tr -d ':' | \
        grep -E '^(eth|en|eno|enp|ens)' | \
        head -1 || true)

    if [[ -z "${IFACE}" ]]; then
        # Fall back: any ethernet-looking interface
        IFACE=$(ip link show | \
            awk '/^[0-9]+:/{print $2}' | \
            tr -d ':' | \
            grep -E '^(eth|en|eno|enp|ens)' | \
            grep -v 'docker\|veth\|br-' | \
            head -1 || true)
    fi

    [[ -n "${IFACE}" ]] || error "No Ethernet interface found. Specify with --iface <name>"
    info "Auto-detected interface: ${IFACE}"
fi

info "Interface : ${IFACE}"
info "Host IP   : ${HOST_IP}"

# ---------------------------------------------------------------------------
# Assign static IP using ip command (temporary — survives until reboot)
# For permanent config, use NetworkManager (shown below as alternative).
# ---------------------------------------------------------------------------
section "Assigning static IP ${HOST_IP}/24 to ${IFACE}"

# Remove existing 192.168.123.x addresses on this interface
EXISTING=$(ip -4 addr show dev "${IFACE}" | grep -oP '192\.168\.123\.\d+/\d+' || true)
for addr in ${EXISTING}; do
    info "Removing existing address: ${addr}"
    ip addr del "${addr}" dev "${IFACE}" 2>/dev/null || true
done

ip addr add "${HOST_IP}/24" dev "${IFACE}"
ip link set "${IFACE}" up
info "Static IP assigned."

# ---------------------------------------------------------------------------
# Open UFW firewall rules required by the system
# ---------------------------------------------------------------------------
section "Configuring UFW firewall"

if command -v ufw &>/dev/null; then
    ufw allow 8012/tcp   comment "televuer WebXR (Quest 3 WebSocket)"   2>/dev/null || true
    ufw allow 5555/tcp   comment "ZMQ image frames from PC2"            2>/dev/null || true
    ufw allow 60001/tcp  comment "teleimager WebRTC preview"            2>/dev/null || true
    # CycloneDDS uses UDP multicast — allow DDS traffic
    ufw allow in on "${IFACE}" proto udp comment "CycloneDDS DDS traffic" 2>/dev/null || true
    info "UFW rules added."
else
    warn "UFW not found. Ensure ports 8012, 5555, 60001 and UDP are open."
fi

# ---------------------------------------------------------------------------
# Verify connectivity to the robot's PC2
# ---------------------------------------------------------------------------
section "Testing connectivity to robot PC2 (${ROBOT_PC2_IP})"

if ping -c 2 -W 2 "${ROBOT_PC2_IP}" &>/dev/null; then
    info "Robot PC2 is reachable at ${ROBOT_PC2_IP} ✓"
else
    warn "Cannot reach ${ROBOT_PC2_IP}. Check:"
    warn "  - Robot is powered on and booted"
    warn "  - Ethernet cable is connected between Host and robot/router"
    warn "  - No firewall blocking ICMP on this interface"
fi

# ---------------------------------------------------------------------------
# Print summary and next steps
# ---------------------------------------------------------------------------
section "Network setup complete"
echo ""
echo -e "  Host IP on robot subnet : ${GREEN}${HOST_IP}${NC}"
echo -e "  Robot PC2               : ${GREEN}${ROBOT_PC2_IP}${NC}"
echo -e "  Ethernet interface      : ${GREEN}${IFACE}${NC}"
echo ""
echo -e "${CYAN}Quest 3 Connection URL:${NC}"
echo -e "  Open Meta Quest Browser → ${GREEN}https://${HOST_IP}:8012/?ws=wss://${HOST_IP}:8012${NC}"
echo ""
echo -e "${CYAN}Verify with:${NC}"
echo -e "  ${GREEN}ssh unitree@${ROBOT_PC2_IP}${NC}   (password: 123)"
echo ""
echo -e "${YELLOW}Note:${NC} This configuration is temporary (resets on reboot)."
echo "  For permanent config, add to NetworkManager or /etc/network/interfaces."
echo ""

# ---------------------------------------------------------------------------
# Optional: NetworkManager permanent config snippet (informational only)
# ---------------------------------------------------------------------------
NM_PROFILE="g1-robot-static"
echo -e "${CYAN}For permanent NetworkManager config, run:${NC}"
cat <<NMCMD
  nmcli con add type ethernet \
    con-name ${NM_PROFILE} \
    ifname ${IFACE} \
    ipv4.method manual \
    ipv4.addresses ${HOST_IP}/24 \
    ipv4.gateway "" \
    connection.autoconnect yes
  nmcli con up ${NM_PROFILE}
NMCMD
echo ""
