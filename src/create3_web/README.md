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

Then open **`http://<robot-host>:8080/`**.

Natively, without Docker. The web dependencies are declared in `package.xml`, so
rosdep installs them; the package builds without them but will not start:

```bash
rosdep install --from-paths src --ignore-src -y     # python3-{fastapi,uvicorn,websockets}
colcon build --packages-select create3_web
source install/setup.bash
ros2 launch create3_web create3_web.launch.py namespace:=cpsl_ugv_1
```

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

All settings come from the environment, so compose supplies them from `.env`:

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

> **There is no authentication unless you set `CREATE3_WEB_TOKEN`.** Anyone who
> can reach the port can drive the robot. Set it in `.env` on any shared network;
> the page then needs `?token=…` in its URL. The node logs a warning at startup
> when no token is configured.

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

`/api/state` makes this scriptable without a browser:

```bash
curl -s localhost:8080/api/state | jq '.battery.percentage, .dock.is_docked'
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
