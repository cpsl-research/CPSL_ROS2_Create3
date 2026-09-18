# syntax=docker/dockerfile:1
#
# CPSL Create 3 ROS 2 workspace.
#
# Everything the NUC needs in order to talk to an iRobot Create 3: ROS 2, the
# workspace's apt dependencies, and the built colcon workspace. What is NOT in
# here, because a container cannot own it, is the host's static IP on the robot
# subnet, the NTP server the robot takes its clock from, and the robot's own
# flash configuration. Those are handled by scripts/bootstrap_host.sh and
# scripts/configure_create3.py respectively.
#
# Build:  docker compose build
# Run:    docker compose up -d

ARG ROS_DISTRO=jazzy
ARG BASE_IMAGE=ros:${ROS_DISTRO}-ros-base

FROM ${BASE_IMAGE} AS base
ARG ROS_DISTRO
ENV ROS_DISTRO=${ROS_DISTRO}
ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Workspace dependencies, pinned to their own layer so that editing source does
# not re-run apt. `rosdep install` below is a safety net that catches anything
# added to a package.xml later; if it starts installing things, add them here.
#
#   teleop_twist_keyboard  - create3_bringup + the teleop service
#   nav2_common            - RewrittenYaml, used by create3_bringup's launch file
#   rplidar_ros            - create3_examples/create3_lidar_slam
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-colcon-common-extensions \
        python3-rosdep \
        ros-${ROS_DISTRO}-rmw-fastrtps-cpp \
        ros-${ROS_DISTRO}-teleop-twist-keyboard \
        ros-${ROS_DISTRO}-nav2-common \
        ros-${ROS_DISTRO}-rplidar-ros \
        iputils-ping \
        iproute2 \
        curl \
        less \
        nano \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 base images already ship a user at UID 1000 ("ubuntu"), which
# collides with the host user on most machines. Reclaim the UID so that files
# written into bind-mounted volumes are owned by the host user rather than root.
ARG USERNAME=cpsl
ARG USER_UID=1000
ARG USER_GID=1000
RUN existing="$(getent passwd ${USER_UID} | cut -d: -f1)"; \
    if [ -n "${existing}" ] && [ "${existing}" != "${USERNAME}" ]; then \
        userdel -r "${existing}" 2>/dev/null || true; \
    fi; \
    groupadd -f -g ${USER_GID} ${USERNAME}; \
    id -u ${USERNAME} >/dev/null 2>&1 || \
        useradd -m -u ${USER_UID} -g ${USER_GID} -s /bin/bash ${USERNAME}

WORKDIR /ws

# The submodules must be checked out on the host before building:
#   git submodule update --init --recursive
COPY --chown=${USER_UID}:${USER_GID} src/ /ws/src/

RUN apt-get update \
    && rosdep update --rosdistro ${ROS_DISTRO} \
    && rosdep install --from-paths /ws/src --ignore-src -y --rosdistro ${ROS_DISTRO} \
    && rm -rf /var/lib/apt/lists/*

RUN source /opt/ros/${ROS_DISTRO}/setup.bash \
    && colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release \
    && chown -R ${USER_UID}:${USER_GID} /ws

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER ${USERNAME}
ENV HOME=/home/${USERNAME}

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
