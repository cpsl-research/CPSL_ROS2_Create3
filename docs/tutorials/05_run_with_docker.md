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
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # prints a token
nano .env                                # paste it after CREATE3_WEB_TOKEN= ; set the rest below
chmod 600 .env                           # .env is gitignored; keep it private
```

The submodule (`irobot_create_msgs`) must be checked out *before* the image is built; the
Dockerfile copies `src/` in. `.env` holds the namespace (`CREATE3_NAMESPACE`, default
`cpsl_ugv_1`, no leading slash; it must match the robot's), `ROS_DOMAIN_ID` (must match the
robot's), `CREATE3_ROBOT_IP` and `CREATE3_HOST_IP` (`192.168.186.2` / `.3`), and the web
settings; compose reads it automatically. If `docker` says permission denied, log out and in
once so the `docker` group applies ([tutorial 01](01_host_setup.md)). **An empty `CREATE3_WEB_TOKEN` turns authentication off**:
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

`docker compose ps` should list both as `running`; `docker compose logs -f bringup` follows the log
(it ends with the `odom_repub` node starting). To develop on the source without rebuilding the
image, see [DEVELOPING](../DEVELOPING.md).

## 3. Verify, from inside the container

```bash
docker compose run --rm preflight
```

This runs `scripts/preflight_create3.sh` with the container's ROS 2, so layer 5 really tests
data flow ([tutorial 03](03_verify_link.md)).

## 4. Use it

| Command | Gives you |
|---|---|
| `docker compose run --rm teleop` | keyboard teleop in your terminal (`teleop_twist_keyboard`, remapped to `/<ns>/cmd_vel`) |
| `docker compose run --rm shell` | a shell with ROS 2 and the workspace sourced; use the `ros2` commands of [tutorial 06](06_native_install.md) here |
| `docker compose down` | stop and remove the services |

`teleop`, `shell` and `preflight` are under the `tools` profile, so `up -d` never starts them.

### The web GUI (`create3_web`)

Open `http://localhost:8080/?token=<token>` (`<this host>` instead of `localhost` from another computer). Panels, driving rules and settings:
[`src/create3_web/README.md`](../../src/create3_web/README.md). Change the token with
`docker compose up -d web` after editing `.env`; open tabs then need the new URL.

## You should see

`docker compose config -q` exits 0 (valid file); `docker compose config --services` lists
`bringup` and `web`; with `--profile tools` it adds `preflight`, `shell`, `teleop`. With the
robot connected, `preflight` ends `The Create 3 link is healthy`.
