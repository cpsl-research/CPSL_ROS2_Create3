# create3_web

A lightweight browser GUI for operating and monitoring a CPSL iRobot Create 3:
live telemetry, dock/undock, keyboard teleop, and a diagnostics panel backed by
the setup scripts.

It exists to replace reaching for a remote desktop session. A NoMachine or VNC
stream costs roughly 1–10 Mbit/s and needs a desktop on the robot host; this
sends a JSON snapshot at 10 Hz, on the order of **5 KB/s**, and renders in any
browser on the network — including a phone.

## Running it

It is a compose service, so it comes up with everything else:

```bash
docker compose up -d          # bringup + web
```

Then open **`http://<robot-host>:8080/?token=<token>`**. The token is required —
see [Access control](#access-control) below.

Natively, without Docker. The web dependencies (`fastapi`, `uvicorn`,
`websockets`) are declared in `package.xml`; the package builds without them but
will not start. Run this **from the workspace root** — `src` is relative to where
you run it, and does not resolve from this package's directory:

```bash
cd /path/to/CPSL_ROS2_Create3
rosdep install -i --from-path src --rosdistro jazzy -y
colcon build --packages-select create3_web
source install/setup.bash
ros2 launch create3_web create3_web.launch.py namespace:=cpsl_ugv_1
```

The workspace's native path installs those three into a `uv`-managed virtualenv
instead of system-wide, which needs one extra `PYTHONPATH` export to take effect.
See "Native installation" in the [top-level README](../../README.md) — the node
will start under either arrangement, but not with neither.

## What it shows

| Panel | Contents |
|---|---|
| Battery | charge percentage, voltage, charging state |
| Dock | docked / undocked, dock visibility, **Dock** and **Undock** buttons |
| Motion | x, y, yaw, linear and angular velocity |
| Safety | hazard chips (bump, cliff, stall, wheel drop), kidnap and stop status |
| Position | a top-down odometry trail on a 1 m grid |
| Control | take/release control, speed sliders, WASD teleop |
| Robot setup | the robot's own configuration, clock skew, preflight, restart buttons |

Tiles grey out when their topic goes stale, so a dead feed looks dead instead of
showing the last value forever.

## Driving it

Press **Take control**, then hold <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd>
or the arrow keys. <kbd>Space</kbd> stops. On a touchscreen, use the on-screen pad.

Four safety properties are built in, because a robot driven from a web page has
failure modes a dashboard does not:

- **Velocity deadman.** The browser repeats the command while a key is held and
  the node republishes it at 20 Hz, but zeroes it after 400 ms of silence. A
  dropped websocket, a closed laptop, or a key-up event that the browser
  swallowed when the window lost focus all stop the robot.
- **One driver at a time.** Control is a lock. Everyone else is a read-only
  observer, so two tabs cannot fight over `cmd_vel`. The lock has a 10 s lease
  refreshed by a heartbeat, so it survives idling but not disconnecting.
- **Speed caps.** `CREATE3_WEB_MAX_LINEAR` / `CREATE3_WEB_MAX_ANGULAR` clamp
  every command server-side, so a crafted request cannot exceed them.
- **E-stop for anyone.** The e-stop deliberately ignores the control lock: the
  person who can see the robot is not always the person driving it. It zeroes
  the command, cancels any running action, and blocks new commands until cleared.

The command readout shows what is *actually being published*, not the last thing
requested, so it reads zero the moment the deadman fires.

## Robot setup & diagnostics

The bottom panel drives `scripts/configure_create3.py` and
`scripts/preflight_create3.sh` from the browser: the robot's domain ID,
namespace, RMW, initial DDS peers, NTP servers and clock skew, a **Run preflight**
button that renders the five-layer ladder, and buttons to restart ntpd, restart
the application, or reboot the robot.

The scripts are imported rather than reimplemented, so there is one definition of
how the robot's web UI is laid out. The panel needs `scripts/` mounted — compose
does this — and degrades to "unavailable" rather than breaking the GUI if it is
not.

## Configuration

All settings come from the environment. Compose reads `.env` automatically; a
native shell does not, so export them yourself first
(`set -a; source .env; set +a`):

| Variable | Default | Meaning |
|---|---|---|
| `CREATE3_NAMESPACE` | `cpsl_ugv_1` | robot namespace, no leading slash |
| `CREATE3_WEB_PORT` | `8080` | listen port |
| `CREATE3_WEB_HOST` | `0.0.0.0` | bind address |
| `CREATE3_WEB_TOKEN` | *(empty)* | shared access token; empty disables auth |
| `CREATE3_WEB_MAX_LINEAR` | `0.31` | teleop linear cap, m/s |
| `CREATE3_WEB_MAX_ANGULAR` | `1.90` | teleop angular cap, rad/s |
| `CREATE3_WEB_TELEMETRY_HZ` | `10` | telemetry push rate |
| `CREATE3_ROBOT_IP` / `CREATE3_HOST_IP` | `192.168.186.2` / `.3` | used by the diagnostics panel |
| `CREATE3_SCRIPTS_DIR` | `/ws/scripts` | where the diagnostics panel looks for `configure_create3.py` and `preflight_create3.sh` |

`CREATE3_SCRIPTS_DIR` only needs setting in unusual layouts. The default is the
path compose mounts `scripts/` at inside the container; when that directory does
not exist — running natively from a checkout, for instance — the node walks up
from its own location to find `scripts/` and uses that instead. The panel degrades
to "unavailable" rather than breaking the GUI if neither is found.

### Access control

The GUI binds every interface by default, so on a lab or campus network the robot
is reachable by any host on that network. `CREATE3_WEB_TOKEN` is what stands
between them and the drive controls.

**Generate a token — do not invent one by hand, and do not reuse it between
machines:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

Put it in `.env`, which is gitignored so the token is never committed, and keep
the file readable only by you:

```bash
cp .env.example .env          # if you have not already
$EDITOR .env                  # set CREATE3_WEB_TOKEN=<the generated value>
chmod 600 .env
docker compose up -d web      # pick up the change
```

Then open `http://<host>:8080/?token=<token>`.

Everything is gated: the page, `/api/*` and `/api/robot/*` return **401** without
a valid token, and the websocket refuses the connection with close code **4401**.
The token is compared with `secrets.compare_digest`, so it cannot be recovered by
timing the response. Static assets (`/static/*`) are deliberately not gated — the
browser requests them from a `<script src>` that cannot carry the token, and they
are inert JavaScript and CSS containing no robot data.

The token is accepted either as a `?token=` query parameter or as an
**`X-Auth-Token`** header. The browser has to use the query parameter; scripts
should prefer the header, which keeps the token out of the logs described below.

**Leaving `CREATE3_WEB_TOKEN` empty disables authentication entirely.** That is
supported for an isolated bench setup, and the node logs a warning at startup so
it is never silent, but it means anyone who can reach the port can drive the
robot and reboot it.

To rotate: generate a new value, edit `.env`, `docker compose up -d web`. Any
open browser tab stops working and needs the new URL.

Two limits worth knowing. The token travels in a query string, so it appears in
browser history and in any proxy logs — acceptable on a lab network, not for
wider exposure. And there is no TLS, so it crosses the network in clear text.
If this ever needs to leave a trusted network, put it behind a reverse proxy
with HTTPS rather than hardening this server.

To restrict by network instead of by token, set `CREATE3_WEB_HOST` to the
robot-subnet address (e.g. `192.168.186.3`). That is stricter, but the GUI is
then unreachable from a laptop or phone on wifi, which is usually the point of
having it.

## HTTP interface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | the page |
| `GET` | `/api/state` | one telemetry snapshot as JSON |
| `WS` | `/ws` | telemetry down, velocity commands up |
| `POST` | `/api/dock`, `/api/undock`, `/api/cancel` | dock actions |
| `POST` | `/api/estop` | `{"engaged": true\|false}` |
| `GET` | `/api/robot/config` | the robot's own configuration |
| `GET` | `/api/robot/preflight` | the diagnostic ladder, structured |
| `POST` | `/api/robot/restart-app`, `/api/robot/restart-ntpd`, `/api/robot/reboot` | robot control |

Every path above except `/static/*` requires the token (see
[Access control](#access-control)).

`/api/state` makes this scriptable without a browser:

```bash
curl -s -H "X-Auth-Token: $CREATE3_WEB_TOKEN" localhost:8080/api/state \
  | jq '.battery.percentage, .dock.is_docked'
```

## Design notes

**Why not rosbridge.** rosbridge_suite would need less code, but it forwards
every topic as JSON at the publisher's rate — `imu` alone is ~100 Hz — and does
nothing for process supervision. Here each ROS callback only writes into a
snapshot which the web layer samples at its own much lower rate, so cost is
independent of how fast the robot talks.

**Threading.** rclpy spins its executor on a background thread while uvicorn owns
the main thread's event loop. They share only the node's mutex-guarded snapshot
and command setters; no ROS object is touched from the event loop, and blocking
HTTP calls to the robot run in a thread pool.

**Scope.** This is an operator console, not a visualiser. Point clouds, images
and 3D do not belong on a JSON websocket — for those, run `foxglove_bridge`
alongside it rather than extending this.
