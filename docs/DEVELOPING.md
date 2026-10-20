# Developing CPSL_ROS2_Create3

For changing this repo. To install and run it, start at the [README](../README.md).

## Packages

| Package | Type | Role |
|---|---|---|
| `create3_bringup` | ament_python | `launch/create3_bringup.launch.py`: pushes the `namespace` argument and starts `odom_repub`. Depends on `odom_repub`, `nav2_common`, `teleop_twist_keyboard`, `irobot_create_msgs` |
| `odom_repub` | ament_python | Subscribes `odom` (best-effort), publishes `odom_repub` (reliable); frames stay the firmware's unprefixed `odom` / `base_link` |
| `create3_web` | ament_python | FastAPI + rclpy GUI (`main.py` entry point, `ros_node.py` ROS side, `server.py` HTTP/websocket, `admin.py` robot setup via `scripts/`). Reference: [its README](../src/create3_web/README.md) |
| `irobot_create_msgs` | submodule | iRobot's interfaces, pinned; built from source, never from apt |

The robot's firmware already publishes `<ns>/tf` with unprefixed frames, so the bringup adds no
tf. The protocol (`<ns>/tf`, unprefixed frames, topic names) is
[TF_AND_TOPICS.md](https://github.com/cpsl-research/console/blob/main/docs/TF_AND_TOPICS.md);
any change to frames or topics must keep to it.

## How the bringup is built

`scripts/deps/create3.sh` (root, idempotent, uses `scripts/deps/_common.sh`) installs the system
dependencies of `create3_bringup` and `odom_repub`: colcon, rosdep, `nav2_common`,
`teleop_twist_keyboard`, `rmw_fastrtps_cpp`. `docker/Dockerfile` runs the same script, then adds
the GUI's Python packages and the tools the in-container preflight needs (`iputils-ping`,
`iproute2`, `curl`), runs `rosdep install`, and `colcon build --symlink-install`.
**Add a bringup dependency to `create3.sh`, not the Dockerfile**, so every consumer gets it. It
holds system dependencies only: the static IP, chrony and shell rc files belong to
`scripts/bootstrap_host.sh`. Another tool (such as the lab's console app) may run the script and
build only `odom_repub create3_bringup`, so keep the bringup independent of `create3_web`.

The entrypoint refuses to start if `FASTDDS_BUILTIN_TRANSPORTS` contains `LARGE_DATA`; keep that guard.

## Scripts

`scripts/README.md` is the reference. `configure_create3.py` is imported by `create3_web/admin.py`
and `preflight_create3.sh` (for `EXPECTED_NODES` and the robot-page parsers), so there is one
description of the robot's web UI: change page layouts in one place only. Scripts use the
standard library and bash only. `bootstrap_host.sh` routes every mutating command through its
`run` helper, which is what makes `--dry-run` honest; keep new changes behind it.

## Tests

There is no separate test suite. Each Python package has the ament lint tests
(`test_copyright`, `test_flake8`, `test_pep257`); `create3_web` has none.

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
colcon test --packages-select create3_bringup odom_repub && colcon test-result --verbose
```

Known state at this writing (2026-10-20): `test_flake8` fails on both packages (unused imports in
the launch file, quote style in `odom_repub.py`) and `test_copyright` is skipped; `test_pep257`
passes. A red `colcon test` is therefore not new. Checks that need no robot: `bash -n scripts/*.sh`, `python3 scripts/configure_create3.py
--help`, `scripts/bootstrap_host.sh --dry-run`, `docker compose config -q`.

## Conventions

Namespaces have no leading slash in `.env` (`CREATE3_NAMESPACE=cpsl_ugv_1`) and a leading slash
in the scripts' `--namespace`. Open items are in [TODO.md](../TODO.md).

## Appendix: submodule and image notes

- `src/irobot_create_msgs` pins commit `b4986ef`. The `.gitmodules` file declares it only.
- The image is `cpsl-create3:latest` (`x-create3-common` in the compose file); the build args are
  `ROS_DISTRO` (default `jazzy`), `USER_UID` and `USER_GID` (default 1000) so files written to
  bind mounts belong to the host user.
- Image size was 1.39 GB on disk when last built (2026-10-20); `TODO.md` 3.1 asks for a
  re-measurement.
