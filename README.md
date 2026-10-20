# CPSL ROS 2 Create 3

ROS 2 packages, host/robot setup scripts and a Docker stack for driving an iRobot Create 3 from a
lab computer, on hardware. Everything here works without any
other CPSL repository.

- Host: **Ubuntu 24.04**, **ROS 2 Jazzy** ([official install guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html))
- Robot firmware: **`I.0.0.FastDDS`**, which runs ROS 2 **Iron**. The Iron/Jazzy mismatch has two
  consequences ([tutorial 04](docs/tutorials/04_dds_pitfalls.md)): never set
  `FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA` on the host, and the robot needs an RMW profile override.
- Wiring and firmware: [tutorial 1](docs/tutorials/01_host_setup.md#before-you-start). Optional lab photos and
  simulation notes: [CPSL_Manuals](https://github.com/cpsl-research/CPSL_Manuals/blob/main/UGVs/iRobotCreate3_Hardware.md).

## What is in here

| Path | What it is |
|---|---|
| `src/create3_bringup` | Launch file: starts `odom_repub` in the robot's namespace |
| `src/odom_repub` | Republishes `<ns>/odom` (best-effort) on `<ns>/odom_repub` (reliable) |
| `src/create3_web` | Browser GUI: telemetry, dock/undock, teleop, diagnostics ([README](src/create3_web/README.md)) |
| `src/irobot_create_msgs` | Submodule: iRobot's message, service and action definitions |
| `scripts/` | `bootstrap_host.sh` (host), `configure_create3.py` (robot), `preflight_create3.sh` (link check); see [scripts/README.md](scripts/README.md) |
| `docker/`, `docker-compose*.yml`, `.env.example` | The same stack as a container |

## Quick start

Run the three scripts in order; each tutorial explains one. You need a **NetworkManager** host
(Ubuntu Desktop, not Server) and a robot with its adapter board fitted, cabled to the host and
powered on; [tutorial 1](docs/tutorials/01_host_setup.md#before-you-start) has the checklist,
including how to read the firmware version.

```bash
git clone --recurse-submodules https://github.com/cpsl-research/CPSL_ROS2_Create3
cd CPSL_ROS2_Create3
scripts/bootstrap_host.sh --dry-run     # preview, then: sudo scripts/bootstrap_host.sh
scripts/configure_create3.py apply      # the robot's own flash configuration
```

Then **one** of these two paths (Docker or native, not both):

```bash
cp .env.example .env                    # set CREATE3_WEB_TOKEN (tutorial 05)
docker compose up -d                    # Docker: bringup + web GUI
docker compose run --rm preflight       # verify the link from inside the container
```

```bash
sudo bash scripts/deps/create3.sh       # native: apt dependencies (tutorial 06)
source /opt/ros/jazzy/setup.bash && colcon build --symlink-install && source install/setup.bash
ros2 launch create3_bringup create3_bringup.launch.py namespace:=cpsl_ugv_1
```

## Documentation

1. [Host setup](docs/tutorials/01_host_setup.md) 2. [Robot configuration](docs/tutorials/02_robot_config.md)
3. [Verify the link](docs/tutorials/03_verify_link.md) 4. [DDS pitfalls](docs/tutorials/04_dds_pitfalls.md)
5. [Run with Docker](docs/tutorials/05_run_with_docker.md) 6. [Native install](docs/tutorials/06_native_install.md)

Developers: [docs/DEVELOPING.md](docs/DEVELOPING.md); open items: [TODO.md](TODO.md).
Create 3 references: [adapter board](https://iroboteducation.github.io/create3_docs/hw/adapter/),
[NTP](https://iroboteducation.github.io/create3_docs/setup/compute-ntp/),
[Fast DDS](https://iroboteducation.github.io/create3_docs/setup/xml-config/).
