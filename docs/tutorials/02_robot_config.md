# 2. Robot configuration

The Create 3 keeps its ROS 2 and network settings **in its own flash**, not in this repo, a
dotfile or a container. A factory-reset, re-flashed or swapped robot has to be configured again
before it will ever show up in `ros2 node list`. `scripts/configure_create3.py` does that over
the robot's web UI. It needs only Python 3 (no packages, no ROS) and a host that already holds
its static address ([tutorial 01](01_host_setup.md)).

## Read, then change

```bash
cd CPSL_ROS2_Create3
scripts/configure_create3.py show               # current robot configuration (default command)
scripts/configure_create3.py apply --dry-run    # the diff, nothing sent
scripts/configure_create3.py apply              # apply, after a confirmation prompt
```

`apply --yes` skips the prompt. It is idempotent: run it again and it reports
`already up to date` and sends nothing. After applying it restarts the robot application and
waits for the robot's ten nodes to appear (`_internal/mobility`, `motion_control`, `robot_state`,
`system_health`, `ui_mgr` and five more).

Defaults, overridable with `--robot`, `--nuc`, `--namespace`, `--domain-id`, `--rmw`:

| Setting | Default |
|---|---|
| Robot address | `192.168.186.2` |
| Host address (`--nuc`) | `192.168.186.3` |
| Namespace | `/cpsl_ugv_1` |
| `ROS_DOMAIN_ID` | `0` |
| RMW | `rmw_fastrtps_cpp` |

## What `apply` sets

| Robot web UI page | Value | Why |
|---|---|---|
| Application > Configuration | domain id, namespace, `rmw_fastrtps_cpp`, **discovery server off** | must agree with the host |
| Beta Features > **Override RMW Profile** | a Fast DDS profile whose initial peer is the host (`192.168.186.3`) | **required**: with it empty the robot answers ping but never announces itself on the wire |
| Beta Features > Edit `ntp.conf` | `server 192.168.186.3 iburst` | the robot has no clock of its own |
| `motion_control` `safety_override` | only if you pass `--safety none\|backup_only\|full` | it decides whether cliff sensors are obeyed, so it is never changed as a side effect |

You can set the same fields by hand at `http://192.168.186.2`; the script exists so a reset robot
is back in one command.

## Other commands

```bash
scripts/configure_create3.py restart-app     # restart the robot application, wait for nodes
scripts/configure_create3.py restart-ntpd    # resync a drifted robot clock
scripts/configure_create3.py reboot          # full reboot
scripts/configure_create3.py set-wired-subnet 187   # DISRUPTIVE: robot moves to 192.168.187.2
```

`set-wired-subnet` is never part of `apply`; afterwards move the host's static address to the
same subnet, and reboot the robot.

## Boot order matters

The Create 3 sets up networking and DDS **at boot**. If it powered on without the Ethernet cable
attached, *Restart application* is not enough: run `reboot`. A fresh or reset robot:

```bash
scripts/configure_create3.py apply --yes
scripts/configure_create3.py reboot --yes
scripts/preflight_create3.sh --quick         # layers 1-4 (tutorial 03)
```

## You should see

`show` prints the robot's current values; `apply --dry-run` on a configured robot ends with
`already up to date`. Next: [verify the link](03_verify_link.md).
