# 5. Run with Docker

The Docker stack runs the same packages as [tutorial 06](06_native_install.md) in a container,
with no ROS 2 install on the host. Prerequisites: [host setup](01_host_setup.md) (static IP,
chrony, Docker, you in the `docker` group) and a [configured robot](02_robot_config.md). Only
Linux works: `docker-compose.yml` uses `network_mode: host`, which Docker Desktop on macOS or
Windows does not provide.

## 1. Clone with submodules and set the token

```bash
git clone --recurse-submodules https://github.com/cpsl-research/CPSL_ROS2_Create3
cd CPSL_ROS2_Create3                     # forgot the flag? git submodule update --init --recursive
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # paste into CREATE3_WEB_TOKEN=
chmod 600 .env                           # .env is gitignored; keep it private
```

The submodule (`irobot_create_msgs`) must be checked out *before* the image is built; the
Dockerfile copies `src/` in. `.env` holds the namespace (`CREATE3_NAMESPACE`, default
`cpsl_ugv_1`, no leading slash), `ROS_DOMAIN_ID`, the two addresses, and the web settings;
compose reads it automatically. **An empty `CREATE3_WEB_TOKEN` turns authentication off**:
anyone who can reach port 8080 could drive the robot, and the node logs a warning. Never set
`FASTDDS_BUILTIN_TRANSPORTS` there ([tutorial 04](04_dds_pitfalls.md)).

## 2. Start

```bash
docker compose up -d
```

The first run builds `cpsl-create3:latest` from `docker/Dockerfile` (ROS 2 base image, the
dependencies from `scripts/deps/create3.sh`, `rosdep`, then `colcon build`), which takes a few
minutes; later runs start in seconds. Two services run and restart unless stopped:

| Service | What it runs |
|---|---|
| `bringup` | `ros2 launch create3_bringup create3_bringup.launch.py namespace:=$CREATE3_NAMESPACE` |
| `web` | `ros2 run create3_web create3_web`, the GUI on port 8080 |

`docker compose ps` should list both as running; `docker compose logs -f bringup` follows the log.

## 3. Verify, from inside the container

```bash
docker compose run --rm preflight
```

This runs `scripts/preflight_create3.sh` with the container's ROS 2, so layer 5 really tests
data flow ([tutorial 03](03_verify_link.md)). Do not rely on the host copy on a Docker-only
machine.

## 4. Use it

| Command | Gives you |
|---|---|
| `docker compose run --rm teleop` | keyboard teleop in your terminal (`teleop_twist_keyboard`, remapped to `/<ns>/cmd_vel`) |
| `docker compose run --rm shell` | a shell with ROS 2 and the workspace sourced; use the `ros2` commands of [tutorial 06](06_native_install.md) here |
| `docker compose down` | stop and remove the services |

`teleop`, `shell` and `preflight` are under the `tools` profile, so `up -d` never starts them.

### The web GUI (`create3_web`)

Open `http://<this host>:8080/?token=<token>`. It shows battery, dock state, odometry trail
and hazards, has dock/undock buttons and keyboard (WASD) teleop, and runs the setup scripts from
its diagnostics panel. Take control first; others are read-only, a velocity deadman zeroes the
command after 400 ms of silence, and anyone can e-stop. Full reference:
[`src/create3_web/README.md`](../../src/create3_web/README.md). Change the token with
`docker compose up -d web` after editing `.env`; open tabs then need the new URL.

## Editing source without rebuilding the image

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm colcon   # rebuild after edits
```

The override mounts `./src` and keeps `build/` and `install/` in named volumes. A named volume is
seeded from the image **once**: `docker compose build` alone will not change what the dev
stack runs. Re-run `colcon`, or reset with
`docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v`.

## You should see

`docker compose config -q` exits 0 (valid file); `docker compose config --services` lists
`bringup` and `web`; with `--profile tools` it adds `preflight`, `shell`, `teleop`. With the
robot connected, `preflight` ends `The Create 3 link is healthy`.
