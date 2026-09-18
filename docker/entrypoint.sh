#!/usr/bin/env bash
# Source ROS 2 and the workspace, then hand off to the container's command.
set -e

source "/opt/ros/${ROS_DISTRO}/setup.bash"

# In dev mode /ws/install is a named volume that starts out empty, so this is
# only sourced once `colcon build` has actually populated it.
if [ -f /ws/install/setup.bash ]; then
    source /ws/install/setup.bash
fi

# A stray LARGE_DATA in the environment moves Fast DDS user data onto TCP, which
# the Create 3's ROS 2 Iron stack will not negotiate: nodes and topics appear as
# normal but no message ever arrives. Refuse to start rather than hand back a
# stack that looks healthy and silently delivers nothing.
if [[ "${FASTDDS_BUILTIN_TRANSPORTS:-}" == *LARGE_DATA* ]]; then
    echo "entrypoint: FASTDDS_BUILTIN_TRANSPORTS=${FASTDDS_BUILTIN_TRANSPORTS} is set." >&2
    echo "entrypoint: the Create 3 cannot negotiate LARGE_DATA; refusing to start." >&2
    echo "entrypoint: remove it from your .env / compose environment." >&2
    exit 78  # EX_CONFIG
fi

exec "$@"
