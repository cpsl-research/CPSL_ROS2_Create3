# 6. Native install

Run the nodes directly on the host, without Docker. Do [tutorial 01](01_host_setup.md) first
(use `--skip-docker`), and [tutorial 02](02_robot_config.md) for the robot. Tested target:
Ubuntu 24.04 and ROS 2 Jazzy.

## 1. Install ROS 2 Jazzy

Follow the official
[ROS 2 Jazzy installation guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
(`ros-jazzy-ros-base` is enough; no desktop needed). Then confirm:

```bash
source /opt/ros/jazzy/setup.bash && ros2 --help | head -2
```

## 2. Get the code and the system dependencies

```bash
git clone --recurse-submodules https://github.com/cpsl-research/CPSL_ROS2_Create3
cd CPSL_ROS2_Create3                     # forgot the flag? git submodule update --init --recursive
sudo bash scripts/deps/create3.sh
```

`scripts/deps/create3.sh` installs `python3-colcon-common-extensions`, `python3-rosdep` and
`ros-jazzy-nav2-common`, `-teleop-twist-keyboard`, `-rmw-fastrtps-cpp`. It is idempotent and
quick when nothing is missing; run it as root. That is enough for the bringup. The web GUI
also needs three Python packages, which `rosdep` finds from `package.xml`:

```bash
sudo rosdep init                         # once per machine; ignore "already exists"
rosdep update                            # (rosdep itself came from the script above)
rosdep install -i --from-path src --rosdistro jazzy -y     # run from the repo root
```

> **Do not `apt install ros-jazzy-irobot-create-msgs`.** `src/irobot_create_msgs` is built from
> source; with the apt package too you get two copies of the interfaces and a version-skew trap.

## 3. Set the DDS environment

Put the `~/.bashrc` block of [tutorial 04](04_dds_pitfalls.md#host-environment-for-the-native-path)
in `~/.bashrc` and open a new terminal. Without them the robot's topics do not appear.

## 4. Build

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

You should see `Summary: 4 packages finished` (`irobot_create_msgs`, `odom_repub`,
`create3_bringup`, `create3_web`). Each new terminal needs both `source` lines.

## 5. Run

```bash
ros2 launch create3_bringup create3_bringup.launch.py namespace:=cpsl_ugv_1
```

Argument `namespace` (default empty) is the robot's namespace; it must match
[tutorial 02](02_robot_config.md). This starts one node, `odom_repub`, which republishes
`/cpsl_ugv_1/odom` as `/cpsl_ugv_1/odom_repub` (reliable QoS). In another terminal, the GUI:

```bash
cp .env.example .env                     # set CREATE3_WEB_TOKEN as in tutorial 05
set -a; source .env; set +a              # compose reads .env itself; a native shell does not
ros2 launch create3_web create3_web.launch.py namespace:=cpsl_ugv_1
```

then open `http://localhost:8080/?token=<token>`. Verify the link first with
`scripts/preflight_create3.sh` ([tutorial 03](03_verify_link.md)).

## 6. Drive the robot

Replace `cpsl_ugv_1` with your namespace.

```bash
ros2 action send_goal /cpsl_ugv_1/undock irobot_create_msgs/action/Undock "{}"
ros2 action send_goal /cpsl_ugv_1/dock irobot_create_msgs/action/Dock "{}"
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args --remap /cmd_vel:=/cpsl_ugv_1/cmd_vel
ros2 service call /cpsl_ugv_1/reset_pose irobot_create_msgs/srv/ResetPose \
  "pose: {position: {x: 0, y: 0, z: 0}, orientation: {x: 0, y: 0, z: 0, w: 1}}"
```

The robot undocks and moves, so clear the space first. `ros2 action list | grep cpsl_ugv_1` shows the
other actions (`drive_distance`, `rotate_angle`, ...).

Using a `uv` virtualenv for the GUI instead of `rosdep`: see [DEVELOPING](../DEVELOPING.md).
