#!/usr/bin/env bash
# Create 3 bringup: what create3_bringup and odom_repub need to build
# and run -- the always-on stack that republishes the robot's odometry
# (reliable QoS) for the rest of the CPSL stack.
#
# Used by docker/Dockerfile and by console (which runs it inside its own
# container before building these two packages), so a dependency added here
# reaches both. The browser GUI's extras are not here: they
# belong to this repo's own image, not to the bringup.
#
#   nav2_common            - RewrittenYaml, used by create3_bringup's launch file
#   teleop_twist_keyboard  - a declared dependency of create3_bringup
#   rmw_fastrtps_cpp       - the RMW the Create 3 speaks
#
# irobot_create_msgs is deliberately absent. A full build compiles it from the
# src/irobot_create_msgs submodule, and the apt package alongside it is the
# version-skew trap docs/tutorials/06_native_install.md warns about. A bringup-only build (console)
# gets it from wherever the machine already has it: console's image installs
# the apt package for its own node, and rosdep resolves it otherwise.
#
# Usage:
#   sudo bash create3.sh           install whatever is missing
#   bash create3.sh --check        no root, installs nothing: exit 0 if every package
#                                below is installed, else exit 1 and list the missing
#                                ones on stderr. Works on plain ROS 2, without console.
ROS_DISTRO="${ROS_DISTRO:-jazzy}"

PACKAGES=(
    python3-colcon-common-extensions
    python3-rosdep
    "ros-${ROS_DISTRO}-nav2-common"
    "ros-${ROS_DISTRO}-teleop-twist-keyboard"
    "ros-${ROS_DISTRO}-rmw-fastrtps-cpp"
)

# Handled before _common.sh, whose root check would fail for a normal user.
if [ "${1:-}" = "--check" ]; then
    missing=()
    for pkg in "${PACKAGES[@]}"; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
            missing+=("$pkg")
        fi
    done
    if [ ${#missing[@]} -ne 0 ]; then
        echo "missing: ${missing[*]}" >&2
        exit 1
    fi
    exit 0
fi

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

apt_ensure "${PACKAGES[@]}"
