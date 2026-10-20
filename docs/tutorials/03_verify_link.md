# 3. Verify the link

A fault in any of five independent layers gives the same symptom: an empty `ros2 node list`.
`scripts/preflight_create3.sh` checks them bottom-up and names the first one that is broken.
Run it whenever the robot "is not showing up".

```bash
cd CPSL_ROS2_Create3
scripts/preflight_create3.sh                  # full check, about 10 s
scripts/preflight_create3.sh --quick          # skip layer 5
scripts/preflight_create3.sh --robot 192.168.186.2 --nuc 192.168.186.3 --namespace /cpsl_ugv_1
```

It needs `ip`, `ping` and `curl`, and the `ros2` CLI for layer 5 (so source ROS first on a
native host; with Docker use the container, below).

## The five layers

| Layer | Checks | A failure usually means |
|---|---|---|
| 1. Host network interface | which interface holds the robot subnet, link carrier, packets received | cable, or [tutorial 01](01_host_setup.md) not done |
| 2. Host ROS 2 environment | `ROS_DISTRO`, `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`, `ROS_AUTOMATIC_DISCOVERY_RANGE`, `FASTDDS_BUILTIN_TRANSPORTS`, `FASTRTPS_DEFAULT_PROFILES_FILE` (also greps `~/.bashrc`) | a bad export, usually `LARGE_DATA` ([tutorial 04](04_dds_pitfalls.md)) |
| 3. Link to the robot | ping, robot web UI reachable | cable, wrong subnet |
| 4. Robot-side configuration | domain id, namespace and RMW agree with the host; discovery server off; RMW override names the host; `ntp.conf` points at the host; clock skew under 5 s | [tutorial 02](02_robot_config.md); each failure prints a `fix` line |
| 5. DDS discovery and live data | all ten robot nodes discovered, 20+ topics, and **a message actually received** on `battery_state` and `dock_status` | discovery works but data does not: tutorial 04 |

Layer 5 reads real messages, not just the node list, on purpose: a transport mismatch lets
discovery succeed while no data ever flows.

## Exit status

| | |
|---|---|
| `0` | every check passed **and** a message arrived from the robot |
| `1` | at least one check failed |
| `2` | inconclusive: nothing failed, but no message arrived |

`--quick` exits 0 when layers 1-4 pass. Warnings never change the status; read them (layer 2
warns about a stale `FASTRTPS_DEFAULT_PROFILES_FILE`, which breaks discovery of your own nodes).

## Docker-only hosts: verify inside the container

With no ROS 2 on the host, the host copy skips layer 5 (warning `the ros2 CLI is not on PATH;
skipping discovery checks`) and cannot confirm that data flows. Treat that as unknown, not
healthy. Use the container, which has ROS 2:

```bash
docker compose run --rm preflight
```

## By hand

```bash
ping -c 3 192.168.186.2
ros2 node list                                # the robot's ten nodes
ros2 topic list --spin-time 20 | grep cpsl_ugv_1   # the default 5 s is often too short
ros2 topic echo /cpsl_ugv_1/battery_state --once
```

Healthy: `battery_state` returns one `BatteryState` message within a few seconds. The ten
nodes are listed in `EXPECTED_NODES` in `scripts/configure_create3.py` (`motion_control`,
`robot_state`, `ui_mgr`, `system_health`, and the others). Once this stack runs you will see
more: `odom_repub` and `create3_web` are extra. If `echo` says `Could not determine the type`,
add the type: `ros2 topic echo /cpsl_ugv_1/battery_state sensor_msgs/msg/BatteryState --once`.

## Suspect the terminal first

A shell opened before `~/.bashrc` was corrected still holds the old exports, and a running
`ros2` daemon keeps the environment of whichever shell started it. Open a fresh terminal, or
check from a clean one:

```bash
env -i HOME=$HOME USER=$USER TERM=xterm bash -ilc 'scripts/preflight_create3.sh'
```
