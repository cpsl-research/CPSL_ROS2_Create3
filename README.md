# CPSL ROS 2 Create 3 Nodes

A collection of nodes/packages used to interact with the iRobot Create 3, on hardware or in
simulation.

- ROS Version (host): **ROS 2 Jazzy**
- Ubuntu Version (host): **Ubuntu 24.04**
- Create 3 firmware: **`I.0.0.FastDDS`** (the robot itself runs ROS 2 **Iron**)

> The robot firmware runs Iron while the host runs Jazzy. They interoperate over plain
> RTPS/UDP, but this mismatch causes two non-obvious requirements covered below: do **not**
> set `FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA` on the host, and the robot needs an **Override
> RMW Profile** entry. Both are in [step 4](#4-configure-the-create-3-itself).

For the full CPSL hardware setup - wiring, the NUC's static IP, chrony/NTP, day-to-day startup
and an extensive troubleshooting guide - see
**[CPSL_Manuals/UGVs/iRobotCreate3_Hardware.md](https://github.com/cpsl-research/CPSL_Manuals/blob/main/UGVs/iRobotCreate3_Hardware.md)**.
This README covers just this repository plus the minimum needed to talk to a robot.

---

## Packages in this repository

| Package | What it does |
|---|---|
| `create3_bringup` | Launches `tf_repub` + `odom_repub` for a namespaced robot |
| `tf_repub` | Subscribes to `<ns>/tf`, rewrites `odom -> base_link` with a namespace prefix, adds a derived `base_footprint` (z = 0), republishes on `/tf` |
| `odom_repub` | Subscribes to `<ns>/odom`, rewrites the frame IDs with a namespace prefix, republishes on `<ns>/odom_repub` |
| `irobot_create_msgs` | submodule - iRobot's message/service/action definitions |
| `create3_web` | Browser GUI: live telemetry, dock/undock, keyboard teleop, diagnostics ([docs](src/create3_web/README.md)) |
| `create3_examples` | submodule - iRobot's example packages (coverage, teleop, lidar SLAM, ...) |

Plus [`scripts/`](scripts/), which is not a ROS package:

| Script | What it does |
|---|---|
| `bootstrap_host.sh` | Prepares a fresh host: static IP on the robot link, chrony, Docker |
| `configure_create3.py` | Reads, diffs and applies the robot's own web-UI configuration (ROS settings, RMW profile override, `ntp.conf`); idempotent |
| `preflight_create3.sh` | Checks the five layers of the Create 3 link and names the one that is broken |

and the container definition:

| File | What it does |
|---|---|
| `docker/Dockerfile` | ROS 2 + workspace dependencies + the built colcon workspace |
| `docker-compose.yml` | `bringup`, plus `teleop` / `shell` / `preflight` tool services |
| `docker-compose.dev.yml` | Override that builds from the host's `src/` instead of the image copy |

---

## Quick start (Docker)

Four commands on a machine that has never seen this robot:

```bash
git clone --recurse-submodules <this repo> && cd CPSL_ROS2_Create3

sudo scripts/bootstrap_host.sh          # static IP + chrony + Docker   (once per machine)
scripts/configure_create3.py apply      # the robot's own flash configuration
docker compose up -d                    # the ROS 2 stack
scripts/preflight_create3.sh            # verify all five layers
```

Run `scripts/bootstrap_host.sh --dry-run` first if you want to see exactly what it
would change; it is idempotent and will not touch a network profile or a chrony
configuration that already works.

The ordering matters. `configure_create3.py` reaches the robot over IP, so the host
needs its static address on the robot subnet before that step, and the robot needs an
NTP server on the host because it has no battery-backed clock. Neither of those can
come from a container, which is why step 0 exists.

Then:

```bash
docker compose logs -f bringup                  # what the stack is doing
docker compose run --rm teleop                  # drive it from a terminal
docker compose run --rm shell                   # a shell with ROS 2 + the workspace sourced
docker compose run --rm preflight               # run the checks from INSIDE the container
docker compose down                             # stop
```

### Web GUI

`docker compose up -d` also starts a browser GUI at **`http://<this host>:8080/`**:
battery, dock state, odometry with a position trail, hazards, dock/undock buttons,
keyboard teleop, and a diagnostics panel that runs the setup scripts from the page.

It is meant to replace reaching for a remote desktop. A NoMachine or VNC session
costs roughly 1-10 Mbit/s and needs a desktop on the host; this pushes a JSON
snapshot at 10 Hz, on the order of 5 KB/s, and works on a phone.

> **Set a token before using this on any shared network.** The GUI binds every
> interface, so without one, anyone who can reach port 8080 can drive the robot
> and reboot it:
>
> ```bash
> cp .env.example .env
> python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # into CREATE3_WEB_TOKEN
> chmod 600 .env
> ```
>
> Then browse to `http://<host>:8080/?token=<token>`. See
> [`src/create3_web/README.md`](src/create3_web/README.md#access-control) for
> rotation and the limits of this scheme.

See [`src/create3_web/README.md`](src/create3_web/README.md) for the safety model
(velocity deadman, single-driver lock, speed caps, e-stop) and the HTTP interface.

### Why host networking

`docker-compose.yml` sets `network_mode: host`, and that is a requirement rather than a
preference. The Create 3 is a DDS participant on a different machine. On a bridge
network the container advertises discovery locators containing its private `172.x`
address, which the robot cannot route back to, and multicast discovery never leaves the
bridge -- so the robot looks dead while every other check passes. `ipc: host` and
`pid: host` are there so Fast DDS shared memory works between the containers and
anything still running on the host.

### Why this is worth containerising

The host's `~/.bashrc` is a single global namespace shared by every ROS workload on the
machine, and this stack has two with directly conflicting requirements:
`FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA` is needed for pushing large point clouds to an
edge server, and is fatal to the Create 3 link, which runs a ROS 2 Iron stack that will
not negotiate it. One `.bashrc` cannot satisfy both. Compose gives each service its own
environment, so the conflict stops being possible. The container entrypoint refuses to
start if `LARGE_DATA` is set, rather than handing back a stack whose nodes and topics
list normally while no message ever arrives.

### Development

To edit `src/` on the host without rebuilding the image each time:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm colcon   # rebuild
```

`build/` and `install/` are named volumes rather than bind mounts, deliberately: the
host's own colcon tree was built against the host's ROS installation, and letting the
container write over it produces artifacts that work in neither place.

---

## Native installation (without Docker)

Use this if you would rather run the stack directly on the host. Steps 4 and 5 apply
either way -- the robot's own configuration and the verification ladder are the same
whether the ROS nodes run in a container or not.

### 1. Install ROS 2 Jazzy and dependencies

1. Install ROS 2 Jazzy using the
   [ROS 2 Jazzy Installation Guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html).

2. Install the Create 3 messages and the packages this repo's bringup needs:

    ```bash
    sudo apt install -y \
      ros-jazzy-irobot-create-msgs \
      ros-jazzy-teleop-twist-keyboard \
      ros-jazzy-nav2-common
    ```

### 2. Clone and build this repository

```bash
git clone --recurse-submodules https://github.com/cpsl-research/CPSL_ROS2_Create3
```

If you forgot `--recurse-submodules`:

```bash
cd CPSL_ROS2_Create3
git submodule update --init --recursive
```

Then install dependencies and build:

```bash
cd CPSL_ROS2_Create3
rosdep install -i --from-path src --rosdistro jazzy -y
colcon build --symlink-install
source install/setup.bash
```

> Run `rosdep install` **before** `colcon build`.

### 3. Configure the ROS 2 middleware on the host

Add to your `~/.bashrc`:

```bash
source /opt/ros/jazzy/setup.bash

export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROS_STATIC_PEERS="192.168.186.2"
```

`ROS_STATIC_PEERS` pointed at the robot is what actually establishes the connection - it makes
the host send unicast discovery directly to the robot rather than relying on multicast.

#### Do not set `FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA`

```bash
# Do NOT do this on a machine that talks to the Create 3:
# export FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA
```

`LARGE_DATA` moves DDS user data onto TCP, which the Create 3's Iron-era Fast DDS will not
negotiate. The result is that **no robot nodes or topics appear at all**, while ping, the robot
web UI and the robot's own logs all look completely healthy - a genuinely confusing failure.
Measured 2026-09-17:

| Host configuration | Create 3 nodes discovered |
|---|---|
| Fast DDS XML profile + `LARGE_DATA` | **0** |
| Fast DDS XML profile only | **10** |
| `LARGE_DATA` only | **0** |
| neither | **10** |

If another process genuinely needs it (e.g. large point clouds to an edge server), scope it to
that process only:

```bash
FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA ros2 launch <that_one_thing>
```

#### Optional: Fast DDS XML profile

An XML profile is **optional** - the environment variables above are sufficient. If you prefer
one (or need it for an unusual network), point `initialPeersList` at the **robot** and use an
absolute path:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
   <participant profile_name="unicast_connection" is_default_profile="true">
       <rtps>
           <builtin>
               <metatrafficUnicastLocatorList>
                   <locator/>
               </metatrafficUnicastLocatorList>
               <initialPeersList>
                   <locator>
                       <udpv4>
                           <address>192.168.186.2</address>
                       </udpv4>
                   </locator>
               </initialPeersList>
           </builtin>
       </rtps>
   </participant>
</profiles>
```

```bash
export FASTRTPS_DEFAULT_PROFILES_FILE=/home/$USER/fastdds_create3.xml
```

See the [Create 3 Fast-DDS instructions](https://iroboteducation.github.io/create3_docs/setup/xml-config/).

### 4. Configure the Create 3 itself

Host-side setup alone is **not** sufficient. The robot keeps its own ROS 2 and networking
configuration in flash, and it has to be set before the robot will ever appear in
`ros2 node list`.

**Scripted (recommended):** [`scripts/configure_create3.py`](scripts/) applies everything in
this section over the robot's web UI, idempotently, and restarts the application for you:

```bash
cd scripts
./configure_create3.py show                 # what the robot is set to now
./configure_create3.py apply --dry-run      # what would change
./configure_create3.py apply                # apply it
```

**By hand:** open the robot's web interface at **`http://192.168.186.2`** and configure the
following.

#### 4a. Application -> Configuration

| Field | Value |
|---|---|
| `ROS 2 Domain ID` | `0` |
| `ROS 2 Namespace` | e.g. `/cpsl_ugv_1` |
| `RMW_IMPLEMENTATION` | `rmw_fastrtps_cpp` |
| `Enable Fast DDS discovery server` | **unchecked** |

Leave the discovery server disabled unless you are actually running one on the host.

#### 4b. Beta Features -> Override RMW Profile (required)

**With this box empty, the robot binds its DDS ports and answers pings but never announces
itself on its wired interface**, so `ros2 node list` stays empty even though everything else
looks fine. Paste this in and save:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
    <participant profile_name="create3_unicast" is_default_profile="true">
        <rtps>
            <builtin>
                <initialPeersList>
                    <locator>
                        <udpv4>
                            <address>192.168.186.3</address>
                        </udpv4>
                    </locator>
                </initialPeersList>
            </builtin>
        </rtps>
    </participant>
</profiles>
```

Replace `192.168.186.3` with your host's address on the robot's wired subnet. This adds the
host as a Fast DDS initial peer so the robot actively announces to it. Clear the box to undo.

Then click **Application -> Restart application**.

#### 4c. Beta Features -> Edit ntp.conf

The Create 3 has no battery-backed clock. Point it at your host and click **Restart ntpd**:

```
server 192.168.186.3 iburst
```

Your host must be running an NTP server that allows the robot's subnet (chrony with
`allow 192.168.186.0/24`). Verify the clocks agree:

```bash
echo "robot: $(curl -s -I http://192.168.186.2/home | grep -i '^date' | cut -d' ' -f2-)"
echo "nuc:   $(date -u '+%a, %d %b %Y %H:%M:%S GMT')"
```

#### 4d. Boot order matters

The Create 3 sets up its networking and DDS at **boot**, not when the application starts. If
the robot powered on without its Ethernet cable connected, **Restart application is not
enough** - use **Reboot robot**.

### 5. Verify the connection

[`scripts/preflight_create3.sh`](scripts/) checks all five layers of the link -- host NIC,
host ROS 2 environment, IP reachability, robot-side configuration, and actual DDS traffic --
and names the one that is broken:

```bash
cd scripts
./preflight_create3.sh
```

It exits non-zero if anything failed, so it also works as a gate at the top of a startup
script. To check by hand instead:

```bash
ping -c 3 192.168.186.2
ros2 node list
```

`ros2 node list` should show all ten robot nodes:

```
/cpsl_ugv_1/_internal/composite_hazard
/cpsl_ugv_1/_internal/kinematics_engine
/cpsl_ugv_1/_internal/mobility
/cpsl_ugv_1/_internal/stasis
/cpsl_ugv_1/mobility_monitor
/cpsl_ugv_1/motion_control
/cpsl_ugv_1/robot_state
/cpsl_ugv_1/static_transform
/cpsl_ugv_1/system_health
/cpsl_ugv_1/ui_mgr
```

For topics, use a longer discovery window - the default 5 s is often not enough and returns
nothing, which looks like a failure but is not:

```bash
ros2 topic list --spin-time 20 | grep cpsl_ugv_1     # expect 25 topics
ros2 topic echo /cpsl_ugv_1/battery_state --once
```

If `ros2 topic echo` says `Could not determine the type for the passed topic`, pass the type
explicitly:

```bash
ros2 topic echo /cpsl_ugv_1/battery_state sensor_msgs/msg/BatteryState --once
```

If `ros2 node list` is empty, run `scripts/preflight_create3.sh` -- it checks each of the
usual causes in dependency order: `FASTDDS_BUILTIN_TRANSPORTS` is unset, the robot's RMW
override is set, the robot booted with the cable connected, and the robot application
finished starting. The manual's troubleshooting section walks through each case in detail.

---

## Tutorials

Replace `/cpsl_ugv_1` with your robot's namespace, or omit it entirely if the robot has no
namespace assigned.

### 1. Bring up the CPSL Create 3 nodes

Launches `tf_repub` and `odom_repub` so the rest of the CPSL stack sees a namespaced tf tree
and odometry:

```bash
cd CPSL_ROS2_Create3
source install/setup.bash
ros2 launch create3_bringup create3_bringup.launch.py namespace:=cpsl_ugv_1
```

| **Parameter** | **Default** | **Description** |
|---|---|---|
| `namespace` | `''` | The robot's namespace |

### 2. Undocking the robot

```bash
ros2 action send_goal /cpsl_ugv_1/undock irobot_create_msgs/action/Undock "{}"
```

### 3. Docking the robot

```bash
ros2 action send_goal /cpsl_ugv_1/dock irobot_create_msgs/action/Dock "{}"
```

### 4. Controlling the vehicle with keyboard operation

```bash
cd CPSL_ROS2_Create3
source install/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard \
  --ros-args --remap /cmd_vel:=/cpsl_ugv_1/cmd_vel
```

### 5. Resetting the robot pose

```bash
ros2 service call /cpsl_ugv_1/reset_pose irobot_create_msgs/srv/ResetPose \
  "pose: {position: {x: 0, y: 0, z: 0}, orientation: {x: 0, y: 0, z: 0, w: 1}}"
```

### 6. Republishing the tf tree from the Create 3

To access the robot's tf tree from another server or device, run the relay node. It
republishes the robot's namespaced `/tf` onto the global `/tf`:

```bash
cd CPSL_ROS2_Create3
source install/setup.bash
ros2 run tf_repub tf_repub
```

On the receiving machine:

```bash
rviz2 --ros-args --remap /tf:=/forwarded_tf
```

### 7. Other available actions

```bash
ros2 action list | grep cpsl_ugv_1
```

```
/cpsl_ugv_1/audio_note_sequence
/cpsl_ugv_1/dock
/cpsl_ugv_1/drive_arc
/cpsl_ugv_1/drive_distance
/cpsl_ugv_1/led_animation
/cpsl_ugv_1/navigate_to_position
/cpsl_ugv_1/rotate_angle
/cpsl_ugv_1/undock
/cpsl_ugv_1/wall_follow
```

---

## Simulation

For running the Create 3 in a Gazebo simulation (via the TurtleBot 4 packages, which are built
on top of the Create 3 - note the CPSL Create 3 does not carry all of the TurtleBot 4's
hardware), see
[CPSL_Manuals/UGVs/iRobotCreate3_Simulation.md](https://github.com/cpsl-research/CPSL_Manuals/blob/main/UGVs/iRobotCreate3_Simulation.md).

---

## Helpful documentation

- [Create 3 Adapter Board Documentation](https://iroboteducation.github.io/create3_docs/hw/adapter/)
- [Create 3 NTP Setup](https://iroboteducation.github.io/create3_docs/setup/compute-ntp/)
- [Create 3 Fast-DDS setup](https://iroboteducation.github.io/create3_docs/setup/xml-config/)
- [ROS 2 Jazzy Installation Guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
