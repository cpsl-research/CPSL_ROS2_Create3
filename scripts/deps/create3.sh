#!/usr/bin/env bash
# Create 3 bringup: what create3_bringup, tf_repub and odom_repub need to build
# and run -- the always-on stack that republishes the robot's namespaced tf
# tree and odometry for the rest of the CPSL stack.
#
# Used by docker/Dockerfile and by console (which runs it inside its own
# container before building these three packages), so a dependency added here
# reaches both. The browser GUI's and the examples' extras are not here: they
# belong to this repo's own image, not to the bringup.
#
#   nav2_common            - RewrittenYaml, used by create3_bringup's launch file
#   teleop_twist_keyboard  - a declared dependency of create3_bringup
#   rmw_fastrtps_cpp       - the RMW the Create 3 speaks
#
# irobot_create_msgs is deliberately absent. A full build compiles it from the
# src/irobot_create_msgs submodule, and the apt package alongside it is the
# version-skew trap the README warns about. A bringup-only build (console)
# gets it from wherever the machine already has it: console's image installs
# the apt package for its own node, and rosdep resolves it otherwise.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

ROS_DISTRO="${ROS_DISTRO:-jazzy}"

apt_ensure \
    python3-colcon-common-extensions \
    python3-rosdep \
    "ros-${ROS_DISTRO}-nav2-common" \
    "ros-${ROS_DISTRO}-teleop-twist-keyboard" \
    "ros-${ROS_DISTRO}-rmw-fastrtps-cpp"
