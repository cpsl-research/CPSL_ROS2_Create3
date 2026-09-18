#!/usr/bin/env bash
# bootstrap_host.sh -- prepare a fresh NUC to talk to an iRobot Create 3.
#
# This covers the three things a container cannot own, because they belong to
# the host kernel and the host's service manager:
#
#   1. a static IP on the direct Ethernet link to the robot
#   2. an NTP server the robot can take its clock from (it has no RTC)
#   3. Docker, so the ROS 2 stack itself can come from a container
#
# It is idempotent and conservative: it inspects what is already configured and
# only creates what is missing. It will not rewrite a working network profile or
# an existing chrony configuration.
#
# Usage:
#   ./bootstrap_host.sh --dry-run          # print every change it would make
#   sudo ./bootstrap_host.sh               # apply
#   sudo ./bootstrap_host.sh --skip-docker # e.g. docker already managed elsewhere
#
# Options:
#   --iface NAME     Ethernet interface facing the robot (default: autodetect)
#   --host-ip IP     this machine's address on the robot subnet (default 192.168.186.3)
#   --robot-ip IP    the robot's address (default 192.168.186.2)
#   --con-name NAME  NetworkManager profile name to create (default create3-wired)
#   --skip-network / --skip-ntp / --skip-docker
#   -n, --dry-run    show what would happen, change nothing
#   -h, --help

set -uo pipefail

HOST_IP="192.168.186.3"
ROBOT_IP="192.168.186.2"
CON_NAME="create3-wired"
IFACE=""
DRY_RUN=0
DO_NETWORK=1
DO_NTP=1
DO_DOCKER=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --iface)        IFACE="$2"; shift 2 ;;
        --host-ip)      HOST_IP="$2"; shift 2 ;;
        --robot-ip)     ROBOT_IP="$2"; shift 2 ;;
        --con-name)     CON_NAME="$2"; shift 2 ;;
        --skip-network) DO_NETWORK=0; shift ;;
        --skip-ntp)     DO_NTP=0; shift ;;
        --skip-docker)  DO_DOCKER=0; shift ;;
        -n|--dry-run)   DRY_RUN=1; shift ;;
        -h|--help)      awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

SUBNET="${HOST_IP%.*}.0/24"
SUBNET_PREFIX="${HOST_IP%.*}."

if [[ -t 1 ]]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; Z=$'\033[0m'
else
    R=""; G=""; Y=""; B=""; Z=""
fi
section() { printf '\n%s%s%s\n' "$B" "$1" "$Z"; }
have()    { printf '  [%sok%s]   %s\n' "$G" "$Z" "$1"; }
todo()    { printf '  [%s..%s]   %s\n' "$Y" "$Z" "$1"; }
problem() { printf '  [%s!!%s]   %s\n' "$R" "$Z" "$1"; }
note()    { printf '         %s\n' "$1"; }

CHANGES=0
# Every mutating command goes through this, so --dry-run is honest by
# construction rather than by remembering to guard each call site.
run() {
    CHANGES=$((CHANGES+1))
    if [[ $DRY_RUN == 1 ]]; then
        printf '         %s$ %s%s\n' "$Y" "$*" "$Z"
        return 0
    fi
    printf '         %s$ %s%s\n' "$B" "$*" "$Z"
    "$@"
}

if [[ $DRY_RUN == 0 && $EUID -ne 0 ]]; then
    echo "${R}This script changes system configuration and must run as root.${Z}" >&2
    echo "Re-run as:  sudo $0 $*" >&2
    echo "Or preview without changing anything:  $0 --dry-run $*" >&2
    exit 1
fi

[[ $DRY_RUN == 1 ]] && printf '%s--dry-run: nothing will be changed.%s\n' "$Y" "$Z"

# ==============================================================================
if [[ $DO_NETWORK == 1 ]]; then
section "1. Static IP on the robot link"
# ==============================================================================
EXISTING_IF="$(ip -o -4 addr show 2>/dev/null | awk -v p="$SUBNET_PREFIX" '$4 ~ "^"p {print $2; exit}')"

if [[ -n "$EXISTING_IF" ]]; then
    CUR="$(ip -o -4 addr show dev "$EXISTING_IF" | awk '{print $4; exit}')"
    have "$EXISTING_IF already holds $CUR"
    ACTIVE_CON="$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
                  | awk -F: -v d="$EXISTING_IF" '$2==d {print $1; exit}')"
    [[ -n "$ACTIVE_CON" ]] && note "provided by NetworkManager profile: $ACTIVE_CON"
    note "leaving it alone; pass --skip-network to silence this section"

    # A default route over the robot link would send this machine's internet
    # traffic at a robot that cannot forward it.
    if [[ -n "$ACTIVE_CON" ]]; then
        ND="$(nmcli -t -f ipv4.never-default connection show "$ACTIVE_CON" 2>/dev/null | cut -d: -f2)"
        if [[ "$ND" == "no" ]]; then
            note "${Y}note: ipv4.never-default is 'no' on this profile${Z}"
            note "it has no gateway so no default route is installed today, but"
            note "to be safe: nmcli connection modify \"$ACTIVE_CON\" ipv4.never-default yes"
        fi
    fi
else
    if [[ -z "$IFACE" ]]; then
        # Prefer a wired interface that has carrier but no address yet.
        for cand in $(ls /sys/class/net 2>/dev/null); do
            [[ "$cand" == lo || "$cand" == docker* || "$cand" == br-* || "$cand" == veth* ]] && continue
            [[ "$cand" == wl* || "$cand" == tailscale* ]] && continue
            if [[ "$(cat "/sys/class/net/$cand/carrier" 2>/dev/null)" == "1" ]] \
               && ! ip -o -4 addr show dev "$cand" | grep -q inet; then
                IFACE="$cand"; break
            fi
        done
    fi
    if [[ -z "$IFACE" ]]; then
        problem "could not autodetect the interface facing the robot"
        note "wired interfaces seen:"
        ip -br link show 2>/dev/null | grep -v -E '^(lo|docker|br-|veth|wl|tailscale)' | sed 's/^/           /'
        note "re-run with --iface NAME"
    else
        todo "will give $IFACE the address $HOST_IP/24 via profile '$CON_NAME'"
        if nmcli -t -f NAME connection show 2>/dev/null | grep -qx "$CON_NAME"; then
            note "profile '$CON_NAME' already exists; updating it"
            run nmcli connection modify "$CON_NAME" \
                ifname "$IFACE" ipv4.method manual ipv4.addresses "$HOST_IP/24" \
                ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
        else
            run nmcli connection add type ethernet con-name "$CON_NAME" ifname "$IFACE" \
                ipv4.method manual ipv4.addresses "$HOST_IP/24" \
                ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
        fi
        run nmcli connection up "$CON_NAME"
    fi
fi
fi

# ==============================================================================
if [[ $DO_NTP == 1 ]]; then
section "2. NTP server for the robot"
# ==============================================================================
# The Create 3 has no battery-backed clock. Left without a reachable NTP server
# it drifts by hours, and every message it publishes carries a timestamp that
# breaks tf and any recorded dataset, while the robot still looks healthy.
if ! command -v chronyd >/dev/null 2>&1 && [[ ! -f /etc/chrony/chrony.conf ]]; then
    todo "chrony is not installed"
    run apt-get update
    run apt-get install -y chrony
else
    have "chrony is installed"
fi

CHRONY_CONF=/etc/chrony/chrony.conf
if [[ -r "$CHRONY_CONF" ]] && grep -qE "^\s*allow\s+${SUBNET//./\\.}" "$CHRONY_CONF" 2>/dev/null; then
    have "chrony already serves $SUBNET"
elif [[ -r "$CHRONY_CONF" ]]; then
    todo "chrony does not serve $SUBNET yet"
    if [[ $DRY_RUN == 1 ]]; then
        printf '         %s$ echo "allow %s" >> %s%s\n' "$Y" "$SUBNET" "$CHRONY_CONF" "$Z"
        CHANGES=$((CHANGES+1))
    else
        cp -n "$CHRONY_CONF" "${CHRONY_CONF}.bak-$(date +%Y%m%d)" 2>/dev/null || true
        printf '\n# Serve time to the Create 3 on the direct wired link.\nallow %s\n' "$SUBNET" >> "$CHRONY_CONF"
        printf '         %s$ appended "allow %s" to %s%s\n' "$B" "$SUBNET" "$CHRONY_CONF" "$Z"
        CHANGES=$((CHANGES+1))
    fi
    run systemctl restart chrony
else
    problem "cannot read $CHRONY_CONF (run with sudo to inspect it)"
fi

if [[ $DRY_RUN == 0 ]]; then
    systemctl is-enabled chrony >/dev/null 2>&1 || run systemctl enable chrony
fi
fi

# ==============================================================================
if [[ $DO_DOCKER == 1 ]]; then
section "3. Docker"
# ==============================================================================
if command -v docker >/dev/null 2>&1; then
    have "docker is installed ($(docker --version 2>/dev/null | cut -d, -f1))"
    if docker compose version >/dev/null 2>&1; then
        have "docker compose v2 is available"
    else
        problem "the 'docker compose' plugin is missing"
        note "install docker-compose-plugin from Docker's apt repository"
    fi
else
    todo "docker is not installed"
    note "installing via Docker's convenience script from https://get.docker.com"
    run bash -c 'curl -fsSL https://get.docker.com | sh'
fi

# Without this, every docker command needs sudo, and anything the container
# writes into a bind mount ends up owned by root.
TARGET_USER="${SUDO_USER:-${USER:-}}"
if [[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]]; then
    if id -nG "$TARGET_USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
        have "$TARGET_USER is in the 'docker' group"
    else
        todo "$TARGET_USER is not in the 'docker' group"
        run usermod -aG docker "$TARGET_USER"
        note "${Y}log out and back in for the new group to take effect${Z}"
    fi
fi
fi

# ==============================================================================
section "Summary"
# ==============================================================================
if [[ $DRY_RUN == 1 ]]; then
    printf '  %d change(s) would be made. Re-run with sudo to apply.\n' "$CHANGES"
else
    printf '  %d change(s) applied.\n' "$CHANGES"
fi
cat <<EOF

Next:
  1. Configure the robot itself:   scripts/configure_create3.py apply
  2. Bring up the ROS 2 stack:     docker compose up -d
  3. Verify the whole link:        scripts/preflight_create3.sh

The robot must be powered on and connected by Ethernet before step 1, and it
initialises its networking at boot -- if it was powered on without the cable,
it needs a full reboot, not just an application restart:
  scripts/configure_create3.py reboot
EOF
