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
| `create3_examples` | submodule - iRobot's example packages (coverage, teleop, lidar SLAM, ...) |

---

## Setup / Installation

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

Host-side setup alone is **not** sufficient. Open the robot's web interface at
**`http://192.168.186.2`** and configure the following.

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

If `ros2 node list` is empty, check in this order: `FASTDDS_BUILTIN_TRANSPORTS` is unset, the
robot's RMW override is set, the robot booted with the cable connected, and the robot
application finished starting (`curl -s http://192.168.186.2/logs-raw | grep "Node created"`
must reach `system_health`). The manual's troubleshooting section walks through each case.

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
