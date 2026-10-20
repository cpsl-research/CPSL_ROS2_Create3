# 4. DDS pitfalls

The robot runs ROS 2 **Iron** and your host runs **Jazzy**. They interoperate over plain RTPS/UDP,
but three things fail silently: the robot looks fine, `ping` works, the web UI works, and no data
arrives. [Tutorial 03](03_verify_link.md) checks all of them; this page explains why.

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

The robot configures networking and DDS **at boot**. If it powered on without its Ethernet cable,
*Restart application* does nothing useful: `scripts/configure_create3.py reboot`.

## Host environment for the native path

Put these in `~/.bashrc` (the Docker stack sets the same values itself, from `.env`):

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

`docker-compose.yml` sets `network_mode: host`; it is required. On a bridge network the
container advertises its private `172.x` address, which the robot cannot route back to, and
multicast never leaves the bridge. `ipc: host` and `pid: host` let Fast DDS shared memory work
between containers and host processes.
