# create3_web

A browser GUI for operating a CPSL iRobot Create 3: live telemetry, dock/undock, keyboard teleop
and a diagnostics panel backed by the setup scripts. It sends a JSON snapshot at 10 Hz (about
5 KB/s), so it works over wifi and on a phone, where a remote desktop would not.

## Running it

With Docker it is a compose service ([tutorial 05](../../docs/tutorials/05_run_with_docker.md)):

```bash
docker compose up -d          # bringup + web
```

Natively ([tutorial 06](../../docs/tutorials/06_native_install.md)); run from the workspace root,
since `src` is relative:

```bash
rosdep install -i --from-path src --rosdistro jazzy -y   # fastapi, uvicorn, websockets
colcon build --packages-select create3_web && source install/setup.bash
set -a; source .env; set +a                               # a native shell does not read .env
ros2 launch create3_web create3_web.launch.py namespace:=cpsl_ugv_1
```

Open **`http://<host>:8080/?token=<token>`**. The packages build without the three Python
dependencies but the node will not start.

## What it shows

| Panel | Contents |
|---|---|
| Battery, Dock | charge, voltage, charging state; docked/undocked, **Dock** and **Undock** |
| Motion, Position | x, y, yaw, velocities; a top-down odometry trail on a 1 m grid |
| Safety | hazard chips (bump, cliff, stall, wheel drop), kidnap and stop status |
| Control | take/release control, speed sliders, WASD teleop |
| Robot setup | the robot's configuration, clock skew, **Run preflight**, restart and reboot buttons |

Tiles grey out when their topic goes stale. The setup panel imports `configure_create3.py` and
runs `preflight_create3.sh` from `scripts/` (compose mounts it; natively the node walks up from
its own location to find it); without them the panel says "unavailable" and the rest works.

## Driving it

Press **Take control**, then hold <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> or the arrow
keys; <kbd>Space</kbd> stops. Safety built in:

- **Velocity deadman.** The node republishes the command at 20 Hz and zeroes it after 400 ms of
  silence, so a dropped websocket or a swallowed key-up stops the robot.
- **One driver.** Control is a lock with a 10 s lease refreshed by a heartbeat; everyone else is
  read-only.
- **Speed caps.** Every command is clamped server-side to the two limits below.
- **E-stop for anyone.** It ignores the lock, zeroes the command, cancels running actions and
  blocks new commands until cleared.

## Configuration

All settings are environment variables (compose reads `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `CREATE3_NAMESPACE` | `cpsl_ugv_1` | robot namespace, no leading slash |
| `CREATE3_WEB_PORT` / `CREATE3_WEB_HOST` | `8080` / `0.0.0.0` | listen port / bind address |
| `CREATE3_WEB_TOKEN` | *(empty)* | shared access token; **empty disables auth** |
| `CREATE3_WEB_MAX_LINEAR` / `_ANGULAR` | `0.31` / `1.90` | teleop caps, m/s and rad/s |
| `CREATE3_WEB_TELEMETRY_HZ` | `10` | telemetry push rate |
| `CREATE3_ROBOT_IP` / `CREATE3_HOST_IP` | `192.168.186.2` / `.3` | for the diagnostics panel |
| `CREATE3_SCRIPTS_DIR` | `/ws/scripts` | where the panel looks for the scripts |

## Access control

The GUI binds every interface, so on a shared network anyone who reaches the port can drive the
robot unless a token is set. Generate one (do not invent one or reuse it across machines), put it
in the gitignored `.env`, and restart the web service:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # CREATE3_WEB_TOKEN=<value>
chmod 600 .env && docker compose up -d web
```

With a token set, the page, `/api/*` and `/api/robot/*` return **401** without it and the websocket
closes with code **4401**; `/static/*` is not gated (inert JS and CSS). Send it as `?token=` (the
browser must) or as an **`X-Auth-Token`** header (prefer this for scripts: it stays out of logs).
Limits: the query string appears in history and proxy logs, and there is no TLS; put it behind an
HTTPS reverse proxy before it leaves a trusted network. To restrict by network instead, set
`CREATE3_WEB_HOST` to the robot-subnet address (then wifi clients cannot reach it).

## HTTP interface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/`, `/api/state` | the page; one telemetry snapshot as JSON |
| `WS` | `/ws` | telemetry down, velocity commands up |
| `POST` | `/api/dock`, `/api/undock`, `/api/cancel`, `/api/estop` | dock actions; e-stop `{"engaged": true\|false}` |
| `GET` | `/api/robot/config`, `/api/robot/preflight` | robot configuration; preflight ladder |
| `POST` | `/api/robot/restart-app`, `/restart-ntpd`, `/reboot` | robot control |

```bash
curl -s -H "X-Auth-Token: $CREATE3_WEB_TOKEN" localhost:8080/api/state | jq '.battery.percentage'
```

rosbridge was not used: it forwards every topic at the publisher's rate. Here callbacks only
write a snapshot that the web layer samples slowly. For point clouds and images run
`foxglove_bridge` alongside rather than extending this.
