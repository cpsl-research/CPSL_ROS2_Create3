#!/usr/bin/env python3
"""Declaratively configure an iRobot Create 3 through its built-in web UI.

The Create 3 keeps its ROS 2 / networking configuration in its own flash, which
means none of it lives in this repo, in a dotfile, or in a container image. A
robot that has been factory reset, re-flashed or swapped for a spare needs these
settings re-entered by hand through the web UI before it will ever appear in
`ros2 node list`. This script does that over HTTP instead, so the robot-side
configuration is version controlled and reproducible.

It is idempotent: it reads the robot's current configuration, compares it with
the desired configuration, and only POSTs the forms that actually differ. Run it
twice and the second run reports "already up to date" and touches nothing.

Endpoints used (all verified against firmware create3+I.0.0.FastDDS, sku RCi3099):

    GET  /ros-config                  read domain id, namespace, RMW, discovery server, params yaml
    GET  /rmw-profile-override        read the Fast DDS profile override XML
    GET  /beta-ntp-conf               read ntp.conf
    POST /ros-config-save-main        ros_domain_id, ros_namespace, rmw_implementation,
                                      fast_discovery_server_enabled, fast_discovery_server_value
    POST /ros-config-save-params      yaml
    POST /rmw-profile-override-save   config
    POST /beta-ntp-conf-save          config
    POST /beta-wired-subnet-save      new_wired_subnet
    POST /api/restart-app             restart the robot application
    POST /api/restart-ntpd            restart ntpd (forces an immediate clock resync)
    POST /api/reboot                  full reboot

Examples:
    ./configure_create3.py show                 # print current robot config
    ./configure_create3.py apply --dry-run      # show what would change
    ./configure_create3.py apply                # apply, with confirmation
    ./configure_create3.py apply --yes          # apply unattended
    ./configure_create3.py restart-ntpd         # fix a drifted robot clock
"""

import argparse
import difflib
import html
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import email.utils

# --- defaults -----------------------------------------------------------------
# These describe the CPSL UGV as wired today: the robot's own eth0 and the NUC
# sit alone on 192.168.186.0/24 over a direct Ethernet cable.
DEFAULT_ROBOT = "192.168.186.2"
DEFAULT_NUC = "192.168.186.3"
DEFAULT_NAMESPACE = "/cpsl_ugv_1"
DEFAULT_DOMAIN_ID = "0"
DEFAULT_RMW = "rmw_fastrtps_cpp"
DEFAULT_TIMEOUT = 10

# The robot application creates exactly these ten nodes once it is healthy.
EXPECTED_NODES = [
    "_internal/composite_hazard",
    "_internal/kinematics_engine",
    "_internal/mobility",
    "_internal/stasis",
    "mobility_monitor",
    "motion_control",
    "robot_state",
    "static_transform",
    "system_health",
    "ui_mgr",
]

# Without this profile the robot relies on multicast SPDP alone to find the NUC.
# On a two-host point-to-point link that is unreliable across a robot reboot: the
# robot can come up before the carrier is present, never announce itself on eth0,
# and stay invisible until it is rebooted again. Naming the NUC as an initial
# unicast peer makes discovery deterministic.
RMW_OVERRIDE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
    <participant profile_name="create3_unicast" is_default_profile="true">
        <rtps>
            <builtin>
                <initialPeersList>
                    <locator>
                        <udpv4>
                            <address>{nuc}</address>
                        </udpv4>
                    </locator>
                </initialPeersList>
            </builtin>
        </rtps>
    </participant>
</profiles>
"""

# The robot has no RTC and no route to the internet on this link, so it must take
# its time from chrony on the NUC. A robot whose clock is wrong will appear in
# `ros2 node list` but its messages will be silently discarded or wildly
# timestamped, which breaks tf and every recorded dataset.
NTP_CONF_TEMPLATE = """# irobot servers
#server 0.irobot.pool.ntp.org iburst
#server 1.irobot.pool.ntp.org iburst
#server 2.irobot.pool.ntp.org iburst
#server 3.irobot.pool.ntp.org iburst
# SBC servers
#server 192.168.186.1 iburst
server {nuc} iburst
"""

PARAMS_YAML_TEMPLATE = """{ns}/motion_control:
  ros__parameters:
    safety_override: "{safety}"
    # safety_override options are 
    # "none" - standard safety profile, robot cannot backup more than an inch because of lack of cliff protection in rear, max speed 0.306m/s
    # "backup_only" - allow backup without cliff safety, but keep cliff safety forward and max speed at 0.306m/s
    # "full" - no cliff safety, robot will ignore cliffs and set max speed to 0.46m/s
"""


# --- terminal helpers ---------------------------------------------------------
def _supports_color() -> bool:
    return sys.stdout.isatty()


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _supports_color() else text


def ok(t):
    return c(t, "32")


def bad(t):
    return c(t, "31")


def warn(t):
    return c(t, "33")


def bold(t):
    return c(t, "1")


# --- HTTP ---------------------------------------------------------------------
class Robot:
    def __init__(self, host: str, timeout: int = DEFAULT_TIMEOUT):
        self.host = host
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"http://{self.host}/{path.lstrip('/')}"

    def get(self, path: str) -> str:
        with urllib.request.urlopen(self._url(path), timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, path: str, fields: dict | None = None) -> int:
        data = urllib.parse.urlencode(fields or {}).encode()
        req = urllib.request.Request(
            self._url(path),
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            # The save handlers answer with a 303 redirect back to the form.
            if 300 <= e.code < 400:
                return e.code
            raise

    def clock_skew(self) -> float | None:
        """Seconds the robot clock is ahead of ours, from the HTTP Date header.

        The web UI has no endpoint that reports the current time, but its own
        responses carry one, which is enough to catch the multi-hour drift the
        robot accumulates whenever ntpd has not reached the NUC.
        """
        # The firmware only routes GET; a HEAD request 404s, so ask for the page
        # itself and read the Date off the response we already need anyway.
        try:
            with urllib.request.urlopen(self._url("home"), timeout=self.timeout) as r:
                d = r.headers.get("Date")
        except urllib.error.HTTPError as e:
            d = e.headers.get("Date") if e.headers else None
        except Exception:
            return None
        if not d:
            return None
        try:
            return email.utils.parsedate_to_datetime(d).timestamp() - time.time()
        except Exception:
            return None


# --- HTML parsing -------------------------------------------------------------
def textarea(page: str, name: str) -> str:
    m = re.search(
        rf'<textarea[^>]*name=["\']?{name}\b[^>]*>(.*?)</textarea>', page, re.I | re.S
    )
    return html.unescape(m.group(1)) if m else ""


def input_value(page: str, name: str) -> str:
    m = re.search(rf'<input[^>]*name=["\']?{name}\b[^>]*>', page, re.I)
    if not m:
        return ""
    v = re.search(r'value=["\']([^"\']*)', m.group(0), re.I)
    return v.group(1) if v else ""


def checkbox_checked(page: str, name: str) -> bool:
    m = re.search(rf'<input[^>]*name=["\']?{name}\b[^>]*>', page, re.I)
    return bool(m) and "checked" in m.group(0).lower()


def selected_option(page: str, name: str) -> str:
    m = re.search(rf'<select[^>]*name=["\']?{name}\b[^>]*>(.*?)</select>', page, re.I | re.S)
    if not m:
        return ""
    o = re.search(r'<option[^>]*value=["\']([^"\']*)["\'][^>]*\bselected\b', m.group(1), re.I)
    return o.group(1) if o else ""


def read_config(robot: Robot) -> dict:
    ros = robot.get("ros-config")
    return {
        "domain_id": input_value(ros, "ros_domain_id"),
        "namespace": input_value(ros, "ros_namespace"),
        "rmw": selected_option(ros, "rmw_implementation"),
        "discovery_enabled": checkbox_checked(ros, "fast_discovery_server_enabled"),
        "discovery_value": input_value(ros, "fast_discovery_server_value"),
        "params_yaml": textarea(ros, "yaml"),
        "rmw_override": textarea(robot.get("rmw-profile-override"), "config"),
        "ntp_conf": textarea(robot.get("beta-ntp-conf"), "config"),
    }


# --- diffing ------------------------------------------------------------------
def norm(s: str) -> str:
    """Compare text blocks ignoring trailing whitespace, which the UI rewrites."""
    return "\n".join(line.rstrip() for line in s.strip().splitlines())


def show_text_diff(label: str, current: str, desired: str) -> None:
    d = list(
        difflib.unified_diff(
            norm(current).splitlines(),
            norm(desired).splitlines(),
            fromfile=f"robot:{label}",
            tofile=f"desired:{label}",
            lineterm="",
        )
    )
    for line in d:
        if line.startswith("+") and not line.startswith("+++"):
            print("      " + ok(line))
        elif line.startswith("-") and not line.startswith("---"):
            print("      " + bad(line))
        else:
            print("      " + line)


def build_desired(args, current: dict) -> dict:
    ns = args.namespace if args.namespace.startswith("/") else "/" + args.namespace
    desired = {
        "domain_id": str(args.domain_id),
        "namespace": ns,
        "rmw": args.rmw,
        "discovery_enabled": False,
        "discovery_value": current["discovery_value"] or f"{args.nuc}:11811",
        "rmw_override": RMW_OVERRIDE_TEMPLATE.format(nuc=args.nuc),
        "ntp_conf": NTP_CONF_TEMPLATE.format(nuc=args.nuc),
    }
    # safety_override changes how the robot treats cliffs, so it is only ever
    # rewritten when the operator names a value explicitly.
    if args.safety:
        desired["params_yaml"] = PARAMS_YAML_TEMPLATE.format(ns=ns, safety=args.safety)
    else:
        desired["params_yaml"] = current["params_yaml"]
    return desired


def plan(current: dict, desired: dict) -> list:
    """Return the list of (form, label, changes) that need POSTing."""
    changes = []

    main_fields = ["domain_id", "namespace", "rmw", "discovery_enabled"]
    main_diff = [k for k in main_fields if current[k] != desired[k]]
    if main_diff:
        changes.append(("ros-config-save-main", "ROS configuration", main_diff))

    if norm(current["params_yaml"]) != norm(desired["params_yaml"]):
        changes.append(("ros-config-save-params", "ROS parameters (yaml)", ["params_yaml"]))
    if norm(current["rmw_override"]) != norm(desired["rmw_override"]):
        changes.append(("rmw-profile-override-save", "RMW profile override", ["rmw_override"]))
    if norm(current["ntp_conf"]) != norm(desired["ntp_conf"]):
        changes.append(("beta-ntp-conf-save", "ntp.conf", ["ntp_conf"]))
    return changes


# --- ros2 verification --------------------------------------------------------
def ros2_nodes(namespace: str, timeout: int = 15) -> list | None:
    """Return the robot's node names, or None if the ros2 CLI is unavailable."""
    try:
        p = subprocess.run(
            ["ros2", "node", "list"], capture_output=True, text=True, timeout=timeout
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    ns = namespace.rstrip("/")
    return sorted(
        n.strip() for n in p.stdout.splitlines() if n.strip().startswith(ns + "/")
    )


def wait_for_nodes(namespace: str, deadline_s: int = 90) -> bool:
    expected = {f"{namespace.rstrip('/')}/{n}" for n in EXPECTED_NODES}
    print(f"  waiting up to {deadline_s}s for {len(expected)} nodes under {namespace} ...")
    start = time.time()
    last = -1
    while time.time() - start < deadline_s:
        nodes = ros2_nodes(namespace)
        if nodes is None:
            print(warn("  ros2 CLI not found on PATH; skipping node verification"))
            print("  source your ROS 2 setup and run: ros2 node list")
            return True
        if len(nodes) != last:
            last = len(nodes)
            print(f"    {int(time.time()-start):3d}s  {len(nodes)}/{len(expected)} nodes")
        if expected.issubset(set(nodes)):
            print(ok(f"  all {len(expected)} nodes present"))
            return True
        time.sleep(3)
    nodes = ros2_nodes(namespace) or []
    missing = sorted(expected - set(nodes))
    print(bad(f"  timed out: {len(nodes)}/{len(expected)} nodes"))
    for m in missing:
        print(bad(f"    missing: {m}"))
    return False


# --- commands -----------------------------------------------------------------
def cmd_show(robot: Robot, args) -> int:
    cur = read_config(robot)
    skew = robot.clock_skew()
    print(bold(f"Create 3 at {robot.host}"))
    print(f"  ROS_DOMAIN_ID          {cur['domain_id']}")
    print(f"  namespace              {cur['namespace']}")
    print(f"  RMW implementation     {cur['rmw']}")
    print(
        f"  Fast discovery server  {'ENABLED  ' + cur['discovery_value'] if cur['discovery_enabled'] else 'disabled'}"
    )
    print(f"  RMW profile override   {'set (' + str(len(cur['rmw_override'])) + ' bytes)' if cur['rmw_override'].strip() else bad('EMPTY')}")
    peers = re.findall(r"<address>\s*([^<\s]+)\s*</address>", cur["rmw_override"])
    if peers:
        print(f"    initial peers        {', '.join(peers)}")
    servers = [
        l.split()[1]
        for l in cur["ntp_conf"].splitlines()
        if l.strip().startswith("server") and len(l.split()) > 1
    ]
    print(f"  ntp servers            {', '.join(servers) if servers else bad('none')}")
    if skew is not None:
        s = f"{skew:+.1f}s"
        print(f"  clock skew vs NUC      {ok(s) if abs(skew) < 5 else bad(s)}")
    safety = re.search(r'safety_override:\s*"?(\w+)"?', cur["params_yaml"])
    print(f"  safety_override        {safety.group(1) if safety else '(unset)'}")
    if args.verbose:
        print(bold("\n--- rmw-profile-override ---"))
        print(cur["rmw_override"].strip() or "(empty)")
        print(bold("\n--- ntp.conf ---"))
        print(cur["ntp_conf"].strip() or "(empty)")
        print(bold("\n--- params yaml ---"))
        print(cur["params_yaml"].strip() or "(empty)")
    return 0


def cmd_apply(robot: Robot, args) -> int:
    cur = read_config(robot)
    desired = build_desired(args, cur)
    changes = plan(cur, desired)

    if not changes:
        print(ok(f"Create 3 at {robot.host} is already up to date; nothing to do."))
        skew = robot.clock_skew()
        if skew is not None and abs(skew) > 5:
            print(warn(f"  note: clock skew is {skew:+.1f}s -- run: {sys.argv[0]} restart-ntpd"))
        return 0

    print(bold(f"Create 3 at {robot.host}: {len(changes)} form(s) to update\n"))
    for form, label, fields in changes:
        print(bold(f"  [{label}]  -> POST /{form}"))
        for f in fields:
            if f in ("rmw_override", "ntp_conf", "params_yaml"):
                show_text_diff(f, cur[f], desired[f])
            else:
                print(f"      {f}: {bad(str(cur[f]))} -> {ok(str(desired[f]))}")
        print()

    if args.dry_run:
        print(warn("--dry-run: nothing was sent to the robot."))
        return 0

    if not args.yes:
        print(
            warn(
                "Applying these will rewrite configuration stored on the robot's flash\n"
                "and restart the robot application (the robot will chime and its ROS\n"
                "nodes will briefly disappear)."
            )
        )
        try:
            if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Aborted; nothing was sent.")
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\nAborted; nothing was sent.")
            return 1
        print()

    for form, label, _ in changes:
        if form == "ros-config-save-main":
            fields = {
                "ros_domain_id": desired["domain_id"],
                "ros_namespace": desired["namespace"],
                "rmw_implementation": desired["rmw"],
                "fast_discovery_server_value": desired["discovery_value"],
            }
            # An unchecked HTML checkbox submits no value at all, so the key is
            # omitted entirely to leave the discovery server disabled.
            if desired["discovery_enabled"]:
                fields["fast_discovery_server_enabled"] = "on"
        elif form == "ros-config-save-params":
            fields = {"yaml": desired["params_yaml"]}
        elif form == "rmw-profile-override-save":
            fields = {"config": desired["rmw_override"]}
        elif form == "beta-ntp-conf-save":
            fields = {"config": desired["ntp_conf"]}
        else:
            continue
        status = robot.post(form, fields)
        print(f"  {ok('sent')}  {label}  (HTTP {status})")

    print(bold("\nRestarting the robot application ..."))
    robot.post("api/restart-app")
    time.sleep(10)
    good = wait_for_nodes(desired["namespace"])

    skew = robot.clock_skew()
    if skew is not None and abs(skew) > 5:
        print(warn(f"\nClock skew is {skew:+.1f}s; restarting ntpd ..."))
        robot.post("api/restart-ntpd")

    print()
    if good:
        print(ok("Configuration applied and the robot is publishing."))
        print(f"Verify with: scripts/preflight_create3.sh")
        return 0
    print(bad("Configuration applied but the robot did not come up cleanly."))
    print("Run scripts/preflight_create3.sh, and see the Troubleshooting section of")
    print("CPSL_Manuals/UGVs/iRobotCreate3_Hardware.md if it stays down.")
    return 1


def cmd_restart_app(robot: Robot, args) -> int:
    print(f"POST /api/restart-app to {robot.host} ...")
    robot.post("api/restart-app")
    time.sleep(10)
    ns = args.namespace if args.namespace.startswith("/") else "/" + args.namespace
    return 0 if wait_for_nodes(ns) else 1


def cmd_restart_ntpd(robot: Robot, args) -> int:
    before = robot.clock_skew()
    print(f"clock skew before: {before:+.1f}s" if before is not None else "clock skew: unknown")
    print(f"POST /api/restart-ntpd to {robot.host} ...")
    robot.post("api/restart-ntpd")
    for i in range(12):
        time.sleep(5)
        after = robot.clock_skew()
        if after is not None and abs(after) < 5:
            print(ok(f"clock skew now {after:+.1f}s after {(i+1)*5}s"))
            return 0
        print(f"  {(i+1)*5:3d}s  skew {after:+.1f}s" if after is not None else "  waiting ...")
    print(bad("clock did not converge; check that chrony on the NUC allows 192.168.186.0/24"))
    print("  on the NUC:  chronyc clients      (should list the robot)")
    return 1


def cmd_reboot(robot: Robot, args) -> int:
    if not args.yes:
        print(warn("A full reboot takes several minutes and the robot will chime when ready."))
        try:
            if input("Reboot the robot? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
    print(f"POST /api/reboot to {robot.host} ...")
    robot.post("api/reboot")
    print("Reboot initiated. Wait for the chime and a solid white light ring.")
    ns = args.namespace if args.namespace.startswith("/") else "/" + args.namespace
    time.sleep(45)
    return 0 if wait_for_nodes(ns, deadline_s=240) else 1


def cmd_set_wired_subnet(robot: Robot, args) -> int:
    n = args.octet
    if not (0 <= n <= 255):
        print(bad("subnet octet must be 0-255"))
        return 2
    print(
        warn(
            f"This sets the robot's wired subnet to 192.168.{n}.x, changing its IP\n"
            f"address to 192.168.{n}.2. You will lose contact with it at {robot.host}\n"
            f"until the NUC's own static address is moved onto the same subnet."
        )
    )
    if not args.yes:
        try:
            if input(f"Set wired subnet to {n}? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
    status = robot.post("beta-wired-subnet-save", {"new_wired_subnet": str(n)})
    print(f"sent (HTTP {status}). Reboot the robot for it to take effect.")
    return 0


# --- main ---------------------------------------------------------------------
def main() -> int:
    # Shared options live on a parent parser so that they are accepted both
    # before and after the subcommand ("apply --dry-run" as well as
    # "--dry-run apply"), which is what anyone actually types.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--robot", default=DEFAULT_ROBOT, help=f"robot IP (default {DEFAULT_ROBOT})")
    common.add_argument("--nuc", default=DEFAULT_NUC, help=f"NUC IP, used as DDS initial peer and NTP server (default {DEFAULT_NUC})")
    common.add_argument("--namespace", default=DEFAULT_NAMESPACE, help=f"ROS namespace (default {DEFAULT_NAMESPACE})")
    common.add_argument("--domain-id", default=DEFAULT_DOMAIN_ID, help=f"ROS_DOMAIN_ID (default {DEFAULT_DOMAIN_ID})")
    common.add_argument("--rmw", default=DEFAULT_RMW, help=f"RMW implementation (default {DEFAULT_RMW})")
    common.add_argument("--safety", choices=["none", "backup_only", "full"], default=None,
                   help="rewrite motion_control safety_override (default: leave the robot's value alone)")
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    common.add_argument("-y", "--yes", action="store_true", help="do not prompt for confirmation")
    common.add_argument("-n", "--dry-run", action="store_true", help="show the diff without sending anything")
    common.add_argument("-v", "--verbose", action="store_true", help="dump full config blocks")

    p = argparse.ArgumentParser(
        description="Configure an iRobot Create 3 through its web UI.",
        parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples:")[-1],
    )
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.add_parser("show", parents=[common], help="print the robot's current configuration (default)")
    sub.add_parser("apply", parents=[common], help="apply the desired configuration")
    sub.add_parser("restart-app", parents=[common], help="restart the robot application")
    sub.add_parser("restart-ntpd", parents=[common], help="restart ntpd to resync the robot clock")
    sub.add_parser("reboot", parents=[common], help="full robot reboot")
    sw = sub.add_parser("set-wired-subnet", parents=[common], help="change the robot's wired subnet (disruptive)")
    sw.add_argument("octet", type=int, help="third octet, 0-255 (e.g. 186 for 192.168.186.x)")

    args = p.parse_args()
    robot = Robot(args.robot, args.timeout)

    try:
        robot.get("home")
    except Exception as e:
        print(bad(f"Cannot reach the Create 3 web UI at http://{args.robot}/ ({e})"))
        print("Check that:")
        print(f"  - the Ethernet cable is connected  (ip -br addr show; look for NO-CARRIER)")
        print(f"  - the NUC holds {args.nuc}/24        (nmcli connection up create3-wired)")
        print(f"  - the robot answers ping            (ping {args.robot})")
        return 2

    handlers = {
        None: cmd_show,
        "show": cmd_show,
        "apply": cmd_apply,
        "restart-app": cmd_restart_app,
        "restart-ntpd": cmd_restart_ntpd,
        "reboot": cmd_reboot,
        "set-wired-subnet": cmd_set_wired_subnet,
    }
    return handlers[args.command](robot, args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
