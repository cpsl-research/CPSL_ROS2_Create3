# 4. DDS pitfalls

The robot runs ROS 2 **Iron** and your host runs **Jazzy**. They interoperate over plain RTPS/UDP,
but three things fail silently: the robot looks fine, `ping` works, the web UI works, and no data
arrives. [Tutorial 03](03_verify_link.md) checks all of them; this page explains why.
**What you must do:** sections 1 (do not set `LARGE_DATA`) and 2 (run `configure_create3.py apply`),
and for the native path the `~/.bashrc` block below. The rest is background.

## 1. Never set `FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA` on the host

`LARGE_DATA` moves DDS user data onto TCP, which the Create 3's Fast DDS will not negotiate.

**Signature: discovery gives you something, data gives you nothing.** Topics are advertised and
`ros2 node list` may list every node, but `ros2 topic echo` never returns. So the only reliable
test is to ask for a message:

```bash
ros2 topic echo /cpsl_ugv_1/battery_state --once     # hangs forever under LARGE_DATA
```

Do not use "is `node list` empty?" as the test. The `ros2` daemon caches the graph and keeps
the environment of whichever shell first started it, so a clean daemon serves a healthy-looking
graph to a polluted shell. Look at what *your* environment discovers:

```bash
ros2 daemon stop                  # the next command starts a fresh one
ros2 node list --no-daemon        # asks the network directly, using THIS environment
```

If another program genuinely needs `LARGE_DATA` (large point clouds to an edge server), scope it
to that one process: `FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA ros2 launch <that_one_thing>`.
This is why the Docker stack gives each service its own environment: `docker/entrypoint.sh`
exits with code 78 and a message if the variable is set in a container.

## 2. The robot needs the RMW profile override

With **Beta Features > Override RMW Profile** empty, the robot binds its DDS ports and answers
pings but never announces itself on the wired interface; `ros2 node list` stays empty. The
override adds your host as a Fast DDS initial peer. `configure_create3.py apply` sets it
([tutorial 02](02_robot_config.md)); clear the box to undo.

## 3. Boot order

If the robot powered on without its Ethernet cable, reboot it
([tutorial 02](02_robot_config.md#boot-order-matters)).

## Host environment for the native path

Put these in `~/.bashrc` (the Docker stack sets `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION` and `ROS_AUTOMATIC_DISCOVERY_RANGE` itself; it does not set `ROS_STATIC_PEERS`):

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_STATIC_PEERS="192.168.186.2"
```

`ROS_STATIC_PEERS` pointed at the robot is what makes the host send unicast discovery straight to
it instead of relying on multicast. `ROS_DOMAIN_ID` must equal the robot's (`show` prints it).
After editing `~/.bashrc`, open a **new terminal**; open ones keep the old values.

An XML profile (`FASTRTPS_DEFAULT_PROFILES_FILE`) is optional; if you use one, put the
**robot's** address (`192.168.186.2`) in `initialPeersList` and use an absolute path. See the
[Create 3 Fast DDS instructions](https://iroboteducation.github.io/create3_docs/setup/xml-config/).

## Why the container uses host networking

`network_mode: host` is required: on a bridge network the container advertises a private `172.x`
address the robot cannot route back to, and multicast never leaves the bridge.
