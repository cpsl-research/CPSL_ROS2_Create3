#!/usr/bin/env bash
# preflight_create3.sh -- work out, in about ten seconds, why the Create 3 is not
# showing up in ROS 2.
#
# The Create 3 link has five independent layers that each have to be right, and a
# failure in any one of them produces the same useless symptom: an empty
# `ros2 node list`. This walks the layers from the bottom up and names the first
# one that is broken, so you are not guessing whether the problem is a cable, a
# clock, the robot's flash configuration, or an environment variable in .bashrc.
#
# Robot-side values are read through the parsers in configure_create3.py so the
# two scripts cannot disagree about how the web UI is laid out.
#
# Usage:
#   ./preflight_create3.sh                 # full check
#   ./preflight_create3.sh --quick         # skip the DDS discovery + live data checks
#   ./preflight_create3.sh --robot IP --nuc IP --namespace /ns
#
# Exit status: 0 = every check passed and a message was seen from the robot,
#              1 = at least one FAIL,
#              2 = inconclusive: nothing failed, but no robot message arrived.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ROBOT_IP="192.168.186.2"
NUC_IP="192.168.186.3"
NAMESPACE="/cpsl_ugv_1"
IFACE=""
QUICK=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --robot)     ROBOT_IP="$2"; shift 2 ;;
        --nuc)       NUC_IP="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --iface)     IFACE="$2"; shift 2 ;;
        --quick|-q)  QUICK=1; shift ;;
        -h|--help)   awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

# --- output helpers -----------------------------------------------------------
if [[ -t 1 ]]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[1m'; Z=$'\033[0m'
else
    R=""; G=""; Y=""; B=""; Z=""
fi

PASSED=0; FAILED=0; WARNED=0
# Whether layer 5 actually proved a message arrives from the robot.
DATA_VERIFIED=0
pass() { printf '  [%sPASS%s] %s\n' "$G" "$Z" "$1"; PASSED=$((PASSED+1)); }
fail() { printf '  [%sFAIL%s] %s\n' "$R" "$Z" "$1"; FAILED=$((FAILED+1)); }
warned() { printf '  [%sWARN%s] %s\n' "$Y" "$Z" "$1"; WARNED=$((WARNED+1)); }
info() { printf '         %s\n' "$1"; }
fix()  { printf '         %s-> %s%s\n' "$Y" "$1" "$Z"; }
section() { printf '\n%s%s%s\n' "$B" "$1" "$Z"; }

# ==============================================================================
section "1. NUC network interface"
# ==============================================================================
# Find whichever interface actually carries the robot subnet, so the check keeps
# working if the NIC is renamed or the cable is moved to another port.
SUBNET_PREFIX="${NUC_IP%.*}."
if [[ -z "$IFACE" ]]; then
    IFACE="$(ip -o -4 addr show 2>/dev/null | awk -v p="$SUBNET_PREFIX" '$4 ~ "^"p {print $2; exit}')"
fi
if [[ -z "$IFACE" ]]; then
    fail "no interface holds an address on ${SUBNET_PREFIX}0/24"
    info "interfaces seen:"
    ip -br -4 addr show 2>/dev/null | sed 's/^/           /'
    fix "sudo nmcli connection up create3-wired"
    fix "if that profile does not exist, see Part B2 of iRobotCreate3_Hardware.md"
    IFACE=""
else
    ADDR="$(ip -o -4 addr show dev "$IFACE" | awk '{print $4; exit}')"
    if [[ "$ADDR" == "$NUC_IP/24" ]]; then
        pass "$IFACE holds $ADDR"
    else
        warned "$IFACE holds $ADDR (expected $NUC_IP/24)"
        fix "sudo nmcli connection modify create3-wired ipv4.addresses $NUC_IP/24"
    fi

    CARRIER="$(cat "/sys/class/net/$IFACE/carrier" 2>/dev/null || echo 0)"
    OPER="$(cat "/sys/class/net/$IFACE/operstate" 2>/dev/null || echo unknown)"
    if [[ "$CARRIER" == "1" ]]; then
        pass "$IFACE has link carrier (operstate=$OPER)"
    else
        fail "$IFACE has NO CARRIER (operstate=$OPER) -- the cable is not connected"
        fix "plug the Ethernet cable into the Create 3's USB-C adapter and the NUC"
        fix "the adapter must be in the robot's USB-C *host* port, robot powered on"
    fi

    RX="$(cat "/sys/class/net/$IFACE/statistics/rx_packets" 2>/dev/null || echo 0)"
    if [[ "$RX" -gt 0 ]]; then
        pass "$IFACE has received $RX packets"
    else
        fail "$IFACE has received 0 packets -- nothing is talking on this link"
    fi
fi

# ==============================================================================
section "2. NUC ROS 2 environment"
# ==============================================================================
# This is read from the environment this script inherited, which is the same
# environment your ros2 commands run in. It is audited before anything is
# sourced, because the interesting failures are variables that are set.
if [[ -z "${ROS_DISTRO:-}" ]]; then
    warned "no ROS 2 environment in the calling shell (ROS_DISTRO unset)"
    fix "source /opt/ros/jazzy/setup.bash  (normally done by ~/.bashrc)"
    # ROS's setup.bash reads unset variables, which `set -u` treats as fatal --
    # aborting the script in exactly the situation this branch exists to handle.
    # shellcheck disable=SC1091
    if [[ -f /opt/ros/jazzy/setup.bash ]]; then
        set +u
        source /opt/ros/jazzy/setup.bash
        set -u
    fi
else
    pass "ROS_DISTRO=$ROS_DISTRO"
fi

if [[ "${ROS_DOMAIN_ID:-0}" == "0" ]]; then
    pass "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0 (unset, defaults to 0)}"
else
    warned "ROS_DOMAIN_ID=${ROS_DOMAIN_ID} -- must match the robot's domain id"
fi

RMW="${RMW_IMPLEMENTATION:-}"
if [[ -z "$RMW" || "$RMW" == "rmw_fastrtps_cpp" ]]; then
    pass "RMW_IMPLEMENTATION=${RMW:-rmw_fastrtps_cpp (default)}"
else
    fail "RMW_IMPLEMENTATION=$RMW -- the Create 3 only speaks Fast DDS"
    fix "export RMW_IMPLEMENTATION=rmw_fastrtps_cpp"
fi

case "${ROS_AUTOMATIC_DISCOVERY_RANGE:-}" in
    ""|SUBNET) pass "ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET (default)}" ;;
    LOCALHOST) fail "ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST -- off-host nodes are ignored"
               fix "export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET" ;;
    *)         warned "ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE}" ;;
esac

# The single most expensive misconfiguration on this link. LARGE_DATA switches
# Fast DDS user-data traffic to TCP, which the robot's ROS 2 Iron stack will not
# negotiate: discovery still half-works, so the robot answers pings and serves
# its web UI, but not one of its nodes or topics ever appears.
if [[ -n "${FASTDDS_BUILTIN_TRANSPORTS:-}" ]]; then
    if [[ "${FASTDDS_BUILTIN_TRANSPORTS}" == *LARGE_DATA* ]]; then
        fail "FASTDDS_BUILTIN_TRANSPORTS=${FASTDDS_BUILTIN_TRANSPORTS} -- incompatible with the Create 3"
        fix "unset FASTDDS_BUILTIN_TRANSPORTS   (and comment it out in ~/.bashrc)"
        fix "set it per-process for the links that need it, never globally"
    else
        warned "FASTDDS_BUILTIN_TRANSPORTS=${FASTDDS_BUILTIN_TRANSPORTS}"
    fi
else
    pass "FASTDDS_BUILTIN_TRANSPORTS is unset"
fi

# Even with a clean shell, an uncommented export in .bashrc will break the next
# terminal you open, so the file itself is checked too.
if grep -qE '^[[:space:]]*export[[:space:]]+FASTDDS_BUILTIN_TRANSPORTS.*LARGE_DATA' "$HOME/.bashrc" 2>/dev/null; then
    fail "~/.bashrc still exports FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA"
    fix "comment that line out; it will break every new shell"
fi

if [[ -n "${FASTRTPS_DEFAULT_PROFILES_FILE:-}" ]]; then
    XMLF="${FASTRTPS_DEFAULT_PROFILES_FILE/#\~/$HOME}"
    if [[ -f "$XMLF" ]]; then
        pass "FASTRTPS_DEFAULT_PROFILES_FILE=$XMLF (exists)"

        # A stale profile here is the quietest failure on this link, and the one
        # most likely to burn a new user after the LARGE_DATA trap above. Fast DDS
        # applies this file to every participant on the host, so a profile left
        # over from another robot makes your OWN nodes invisible to `ros2 node
        # list` -- the processes are alive, the robot still pings and serves its
        # web UI, and nothing anywhere says the profile is to blame.
        #
        # These are text heuristics, NOT an XML parse. That is deliberate: the
        # script is plain bash and also runs inside a minimal container, where
        # neither xmllint nor a Python XML module can be assumed. So comments,
        # exotic formatting or a namespace prefix can fool the matching below.
        # For that reason both findings are warnings, never failures -- a profile
        # is allowed to be unusual, and plenty of odd-looking ones work.

        # (a) an initialPeersList that does not name the robot. A list that is
        #     absent entirely is fine (default discovery applies); a list that
        #     exists and names other machines instead is what goes wrong.
        # Drop XML comments first, so a peers list someone commented out is not
        # read as the live one: whole comments on one line go by substitution,
        # and only what is left -- a real multi-line comment -- is deleted by
        # range. Doing the range alone would be a bug: a sed range does not end
        # on the line it starts on, so a one-line comment would swallow the whole
        # rest of the file and silently disable both checks below.
        PROFILE_TEXT="$(sed -e 's/<!--.*-->//g' -e '/<!--/,/-->/d' "$XMLF" 2>/dev/null)"
        PEERS_BLOCK="$(printf '%s\n' "$PROFILE_TEXT" \
            | sed -n '/<initialPeersList/,/<\/initialPeersList>/p')"
        if [[ -n "$PEERS_BLOCK" ]]; then
            PEER_ADDRS="$(printf '%s\n' "$PEERS_BLOCK" \
                | grep -oE '<address>[^<]*</address>' \
                | sed -e 's/<[^>]*>//g' -e 's/[[:space:]]//g' \
                | tr '\n' ',' | sed 's/,$//')"
            if [[ ",${PEER_ADDRS}," == *",${ROBOT_IP},"* ]]; then
                pass "profile initialPeersList names the robot ($ROBOT_IP)"
            else
                warned "$XMLF: initialPeersList does not name the robot $ROBOT_IP (lists: ${PEER_ADDRS:-none})"
                info "a profile from another network makes your own nodes invisible"
                fix "point initialPeersList at $ROBOT_IP, or unset FASTRTPS_DEFAULT_PROFILES_FILE"
            fi
        fi

        # (b) a locator list emptied with a bare <locator/>. That suppresses the
        #     default locators for the list it appears in, so the participant
        #     stops announcing or listening on the addresses it would otherwise
        #     use -- discovery silently goes one-way.
        EMPTY_LISTS="$(awk '
            {
                rest = $0
                while (match(rest, /<[A-Za-z_][A-Za-z0-9_]*LocatorList[^>]*>/)) {
                    tag = substr(rest, RSTART + 1, RLENGTH - 2)
                    sub(/[[:space:]].*/, "", tag)
                    cur = tag
                    rest = substr(rest, RSTART + RLENGTH)
                }
            }
            /<locator[[:space:]]*\/>/ {
                name = (cur == "" ? "locator list" : cur)
                if (!(name in seen)) { seen[name] = 1; print name }
            }
        ' <<<"$PROFILE_TEXT" | tr '\n' ',' | sed 's/,$//')"
        if [[ -n "$EMPTY_LISTS" ]]; then
            warned "$XMLF: empty <locator/> empties ${EMPTY_LISTS}"
            info "an emptied locator list suppresses the default locators"
            fix "delete the empty <locator/> element, or unset FASTRTPS_DEFAULT_PROFILES_FILE"
        fi
    else
        fail "FASTRTPS_DEFAULT_PROFILES_FILE=$XMLF does not exist"
        fix "unset it, or create the file; a missing profile file is silently ignored"
    fi
fi

# ==============================================================================
section "3. Link to the robot"
# ==============================================================================
if ping -c 2 -W 2 "$ROBOT_IP" >/dev/null 2>&1; then
    pass "$ROBOT_IP answers ICMP"
else
    fail "$ROBOT_IP does not answer ping"
    fix "check layer 1 above; if the cable is fine, reboot the robot"
fi

HTTP="$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://$ROBOT_IP/home" 2>/dev/null)"
HTTP="${HTTP:-000}"
if [[ "$HTTP" == "200" ]]; then
    pass "web UI at http://$ROBOT_IP/ responds (HTTP 200)"
else
    fail "web UI at http://$ROBOT_IP/ returned HTTP $HTTP"
    fix "the robot may still be booting; wait for the chime and a solid white ring"
fi

# ==============================================================================
section "4. Robot-side configuration"
# ==============================================================================
# Read through configure_create3.py's parsers rather than re-scraping the HTML.
ROBOT_FACTS="$(
    python3 - "$SCRIPT_DIR" "$ROBOT_IP" <<'PY' 2>/dev/null
import sys
sys.path.insert(0, sys.argv[1])
try:
    from configure_create3 import Robot, read_config
    r = Robot(sys.argv[2], 6)
    c = read_config(r)
    import re
    peers = ",".join(re.findall(r"<address>\s*([^<\s]+)\s*</address>", c["rmw_override"]))
    ntp = ",".join(l.split()[1] for l in c["ntp_conf"].splitlines()
                   if l.strip().startswith("server") and len(l.split()) > 1)
    skew = r.clock_skew()
    print("ok=1")
    print(f"domain_id={c['domain_id']}")
    print(f"namespace={c['namespace']}")
    print(f"rmw={c['rmw']}")
    print(f"discovery={'on' if c['discovery_enabled'] else 'off'}")
    print(f"peers={peers}")
    print(f"ntp={ntp}")
    print(f"skew={'' if skew is None else round(skew, 1)}")
except Exception as e:
    print("ok=0")
    print(f"err={e}")
PY
)"
eval "$(echo "$ROBOT_FACTS" | sed 's/^\([a-z_]*\)=\(.*\)$/RF_\1="\2"/')"

if [[ "${RF_ok:-0}" != "1" ]]; then
    fail "could not read the robot's configuration (${RF_err:-unknown error})"
    fix "open http://$ROBOT_IP/ros-config in a browser to check it by hand"
else
    [[ "${RF_domain_id}" == "${ROS_DOMAIN_ID:-0}" ]] \
        && pass "robot ROS_DOMAIN_ID=${RF_domain_id} matches the NUC" \
        || { fail "robot ROS_DOMAIN_ID=${RF_domain_id} but the NUC uses ${ROS_DOMAIN_ID:-0}"
             fix "scripts/configure_create3.py apply --domain-id ${ROS_DOMAIN_ID:-0}"; }

    [[ "${RF_namespace}" == "${NAMESPACE}" ]] \
        && pass "robot namespace=${RF_namespace}" \
        || warned "robot namespace=${RF_namespace} (this check expected ${NAMESPACE})"

    [[ "${RF_rmw}" == "rmw_fastrtps_cpp" ]] \
        && pass "robot RMW=${RF_rmw}" \
        || fail "robot RMW=${RF_rmw}"

    [[ "${RF_discovery}" == "off" ]] \
        && pass "robot Fast DDS discovery server is disabled" \
        || { fail "robot Fast DDS discovery server is ENABLED"
             fix "disable it unless you are actually running a discovery server"; }

    # Without an initial-peers override the robot depends on multicast SPDP,
    # which does not reliably survive a reboot on a point-to-point link.
    if [[ -z "${RF_peers}" ]]; then
        fail "robot has no RMW profile override (no initial DDS peers)"
        fix "scripts/configure_create3.py apply --nuc $NUC_IP"
    elif [[ ",${RF_peers}," == *",${NUC_IP},"* ]]; then
        pass "robot RMW override lists the NUC ($NUC_IP) as an initial peer"
    else
        fail "robot RMW override lists peers [${RF_peers}] but not $NUC_IP"
        fix "scripts/configure_create3.py apply --nuc $NUC_IP"
    fi

    [[ ",${RF_ntp}," == *",${NUC_IP},"* ]] \
        && pass "robot ntp.conf points at the NUC ($NUC_IP)" \
        || { fail "robot ntp.conf does not list $NUC_IP (has: ${RF_ntp:-none})"
             fix "scripts/configure_create3.py apply --nuc $NUC_IP"; }

    # The robot has no RTC. A skewed clock lets nodes appear while every
    # timestamp, and therefore tf and any recorded dataset, is garbage.
    if [[ -z "${RF_skew}" ]]; then
        warned "could not determine the robot's clock skew"
    elif python3 -c "import sys; sys.exit(0 if abs(float('${RF_skew}')) < 5 else 1)"; then
        pass "robot clock is within 5s of the NUC (skew ${RF_skew}s)"
    else
        fail "robot clock is off by ${RF_skew}s"
        fix "scripts/configure_create3.py restart-ntpd"
        fix "and confirm chrony on the NUC serves this subnet: chronyc clients"
    fi
fi

# ==============================================================================
if [[ "$QUICK" == "1" ]]; then
    section "5. DDS discovery -- skipped (--quick)"
else
section "5. DDS discovery and live data"
# ==============================================================================
if ! command -v ros2 >/dev/null 2>&1; then
    warned "the ros2 CLI is not on PATH; skipping discovery checks"
else
    NS="${NAMESPACE%/}"
    # --no-daemon is what makes this layer honest. A plain `ros2 node list` is
    # answered by the long-lived ros2 daemon, which serves a graph cached from
    # whatever DDS environment happened to start it -- so a shell with a broken
    # profile or transport still gets a full, stale node list, and this layer
    # reports PASS for an environment that cannot see the robot at all. The
    # daemon is left alone rather than stopped: --no-daemon neither spawns nor
    # uses one, so a stale daemon cannot taint these answers, and `ros2 daemon
    # stop` would disrupt other terminals the user has open for no gain here.
    #
    # The cost is that every query now builds its own participant and has to
    # discover the graph from cold, which needs an explicit --spin-time and can
    # still come back short on the first try. Same retry idiom as before: do not
    # believe an empty or short result until a longer spin has agreed with it.
    mapfile -t NODES < <(timeout 20 ros2 node list --no-daemon --spin-time 3 2>/dev/null | grep "^${NS}/" | sort)
    if [[ ${#NODES[@]} -lt 10 ]]; then
        mapfile -t NODES < <(timeout 30 ros2 node list --no-daemon --spin-time 8 2>/dev/null | grep "^${NS}/" | sort)
    fi
    mapfile -t EXPECTED < <(python3 -c "
import sys; sys.path.insert(0,'$SCRIPT_DIR')
from configure_create3 import EXPECTED_NODES
print('\n'.join(f'$NS/{n}' for n in EXPECTED_NODES))")

    MISSING=()
    for e in "${EXPECTED[@]}"; do
        printf '%s\n' "${NODES[@]:-}" | grep -qxF "$e" || MISSING+=("$e")
    done

    if [[ ${#NODES[@]} -eq 0 ]]; then
        fail "no nodes discovered under $NS"
        fix "if layers 1-4 all passed, the robot application is wedged:"
        fix "scripts/configure_create3.py restart-app   (then, if needed, reboot)"
    elif [[ ${#MISSING[@]} -eq 0 ]]; then
        pass "all ${#EXPECTED[@]} expected nodes discovered under $NS"
    else
        fail "${#NODES[@]}/${#EXPECTED[@]} nodes discovered; missing ${#MISSING[@]}"
        for m in "${MISSING[@]}"; do info "missing: $m"; done
        fix "the robot application started only partly; restart it:"
        fix "scripts/configure_create3.py restart-app"
    fi

    if [[ ${#NODES[@]} -gt 0 ]]; then
        NTOPICS="$(timeout 20 ros2 topic list --no-daemon --spin-time 3 2>/dev/null | grep -c "^${NS}/" || true)"
        if [[ "${NTOPICS:-0}" -lt 20 ]]; then
            NTOPICS="$(timeout 30 ros2 topic list --no-daemon --spin-time 8 2>/dev/null | grep -c "^${NS}/" || true)"
        fi
        [[ "${NTOPICS:-0}" -ge 20 ]] \
            && pass "$NTOPICS topics advertised under $NS" \
            || warned "only ${NTOPICS:-0} topics under $NS (expected 20+)"

        # Discovery can succeed while user data never flows -- that is exactly
        # what a TCP/LARGE_DATA mismatch looks like -- so actually read a message.
        for t in battery_state dock_status; do
            if timeout 12 ros2 topic echo --once "$NS/$t" >/dev/null 2>&1; then
                DATA_VERIFIED=1
                pass "received a message on $NS/$t"
            else
                fail "no message received on $NS/$t within 12s"
                fix "nodes are visible but user data is not flowing -- re-check"
                fix "FASTDDS_BUILTIN_TRANSPORTS in layer 2"
            fi
        done
    fi
fi
fi

# ==============================================================================
printf '\n%s%s%s\n' "$B" "----------------------------------------" "$Z"
printf '%s%d passed%s' "$G" "$PASSED" "$Z"
[[ $WARNED -gt 0 ]] && printf ', %s%d warning(s)%s' "$Y" "$WARNED" "$Z"
[[ $FAILED -gt 0 ]] && printf ', %s%d FAILED%s' "$R" "$FAILED" "$Z"
printf '\n'

if [[ $FAILED -eq 0 ]]; then
    # Nothing failed, but a warning can still be the thing that wastes the next
    # afternoon -- a stale DDS profile warns here and breaks discovery later --
    # so say so in the verdict instead of leaving it as a number in the counts.
    [[ $WARNED -gt 0 ]] && \
        printf '%s%d warning(s) above did not fail this run; read them.%s\n' "$Y" "$WARNED" "$Z"
    if [[ "$QUICK" == "1" ]]; then
        printf 'Layers 1-4 passed. Layer 5 was skipped at your request (--quick).\n'
        exit 0
    fi
    # Reporting a healthy link having never seen a message is the worst thing
    # this script could do, and it is exactly what happens on a host that has
    # Docker but no ROS 2: layer 5 is skipped with a warning, and warnings do
    # not affect the exit status.
    if [[ $DATA_VERIFIED -eq 0 ]]; then
        printf '%sInconclusive: %d checks passed, but no message was ever received\n' "$Y" "$PASSED"
        printf 'from the robot, so the link is NOT confirmed working.%s\n' "$Z"
        printf 'If the ros2 CLI is unavailable here, run the checks in the container:\n'
        printf '  %sdocker compose run --rm preflight%s\n' "$B" "$Z"
        exit 2
    fi
    printf '%sThe Create 3 link is healthy.%s\n' "$G" "$Z"
    exit 0
fi
printf 'Fix the %slowest-numbered%s failing section first; the higher layers\n' "$B" "$Z"
printf 'depend on it. Full reference: CPSL_Manuals/UGVs/iRobotCreate3_Hardware.md\n'
exit 1
