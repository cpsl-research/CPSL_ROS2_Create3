# Review backlog — outstanding work

> **This is a working document, not user documentation.** It is a punch list of
> open findings from three independent reviews of this repository. Do not delete
> it during documentation cleanup, and do not treat it as setup instructions —
> those are `README.md`, `scripts/README.md` and `src/create3_web/README.md`.

Completed items were removed on 2026-09-18 once verified; the full record,
including what each fix was and how it was tested, is in the history of this file
(`git log -p docs/BACKLOG.md`, last full version at commit `0ff80b5`).

**Status legend**

| | |
|---|---|
| `TODO` | not started |
| `ACCEPTED` | known, deliberately living with it, with a reason |
| `DEFERRED` | postponed at the owner's request |

---

## 1. Correctness

### 1.1 Preflight layer 5 trusts the ROS 2 daemon and can report a false PASS — `TODO`

`scripts/preflight_create3.sh:286` uses plain `ros2 node list`, which is answered
from the long-lived `ros2` daemon. The daemon keeps serving a cached, healthy
graph regardless of the current shell's DDS environment, so with
`FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA` set the script reports:

```
[PASS] all 10 expected nodes discovered under /cpsl_ugv_1   <- false
[PASS] 25 topics advertised under /cpsl_ugv_1               <- false
[FAIL] no message received on /cpsl_ugv_1/battery_state within 12s
```

The overall verdict was still correct because the data checks caught it, which is
why they exist. Adding `--no-daemon` to the node and topic queries would make the
layer honest rather than accidentally right. Consider also `ros2 daemon stop`.

Small, self-contained: two query sites, plus a re-run of the four preflight modes.

### 1.2 Preflight does not validate `FASTRTPS_DEFAULT_PROFILES_FILE` contents — `TODO`

The script checks only that the file exists. A stale profile silently breaks
discovery of your **own** nodes while the robot still looks reachable.

Observed on this host, where `~/.bashrc` sets
`FASTRTPS_DEFAULT_PROFILES_FILE=~/fastdds_nuc.xml` and that file names an
unrelated `192.168.0.30` in `initialPeersList` with an emptied metatraffic
multicast locator list:

```
$ ros2 launch create3_bringup create3_bringup.launch.py namespace:=cpsl_ugv_1
[INFO] [tf_repub-1]: process started
$ ros2 node list --no-daemon --spin-time 10 | grep -c repub
0                                    # processes alive, invisible

$ unset FASTRTPS_DEFAULT_PROFILES_FILE
$ ros2 node list --no-daemon --spin-time 10 | grep repub
/cpsl_ugv_1/odom_repub
/cpsl_ugv_1/tf_repub
```

Preflight reports `[PASS] FASTRTPS_DEFAULT_PROFILES_FILE=... (exists)` throughout.
It should parse the profile and warn when `initialPeersList` does not name the
robot, or when the metatraffic locator list is emptied. Rated the single most
likely thing to burn a new user after `LARGE_DATA`.

Depends on **5.2** — decide whether the native path needs a profile at all first.

### 1.3 `tf_repub` and `odom_repub` emit frame IDs with a leading slash — `DEFERRED`

`src/tf_repub/tf_repub/tf_repub.py:12-17` (and `src/odom_repub/odom_repub/odom_repub.py:40-41`)

```python
self.namespace = self.get_namespace()        # already returns "/cpsl_ugv_1"
self.tf_prefix = "{}/".format(self.namespace)  # -> "/cpsl_ugv_1/"
```

`get_namespace()` already includes the leading slash, so the published frames are
`/cpsl_ugv_1/odom` and `/cpsl_ugv_1/base_link`. tf2 rejects these outright:

```
$ ros2 run tf2_ros tf2_echo /cpsl_ugv_1/odom /cpsl_ugv_1/base_link
Invalid frame ID "/cpsl_ugv_1/odom" passed to canTransform argument target_frame
 - in tf2 frame_ids cannot start with a '/'
```

No tf2 consumer — RViz2 included — can use them, which is the stated purpose of
the package. Meanwhile `CPSL_ROS2_Nav/src/cpsl_nav/config/nav2_ugv.yaml` already
asks for the *unslashed* form (`robot_base_frame: cpsl_ugv_1/base_footprint`,
`global_frame: cpsl_ugv_1/odom`), so nothing currently publishes what nav2 wants.

Suggested fix, one line in each file:

```python
self.tf_prefix = "{}/".format(self.namespace.strip('/'))
```

**Deferred at the owner's request** — these packages are remnants to be revisited
later. Two things to settle when they are:

- `slam_*.yaml`, `localization.yaml` and `Start_UGV_collect_dataset.sh`
  (`base_frame_id:=base_link`) use **unnamespaced** frames, so SLAM and nav2
  disagree about frame naming today. That disagreement predates this fix.
- `CPSL_ROS2_Sensors` also publishes into this tree; confirm its static
  transforms use the same convention before declaring the tree consistent.

Pre-existing; affects the Docker and native paths identically.

---

## 2. Security and exposure

The web GUI is now token-gated on every surface — the page, the telemetry API,
the websocket, the control endpoints and the diagnostics endpoints. What follows
is what that did *not* close.

### 2.1 Residual web GUI exposure decisions — `TODO`

- **Bind address.** The GUI binds `0.0.0.0:8080` and this host is also on Duke's
  `10.197.36.73/16`. A token plus `0.0.0.0` is the usable compromise; binding
  `CREATE3_WEB_HOST=192.168.186.3` is the strict one, and makes the GUI
  unreachable from a laptop on wifi. Not yet decided.
- **Token in the query string** appears in browser history and any proxy logs.
  Acceptable on a lab network; revisit if this is ever exposed more widely.
- **No TLS**, so the token crosses the network in clear text.

### 2.2 DDS discovery is advertised on the university subnet — `TODO`

`ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` announces on every interface, including
`wlp1s0` on a `/16`. Anyone on that network running ROS 2 on domain 0 — the
default everyone uses — would discover these nodes and be discovered by them.
This gets worse as more repos are containerised and start publishing point
clouds.

Proposed, not yet verified against the robot:

```yaml
ROS_AUTOMATIC_DISCOVERY_RANGE: LOCALHOST
ROS_STATIC_PEERS: "192.168.186.2"
```

All containers share the host network namespace, so they are already localhost to
one another; the static peer covers the robot. Needs testing before adoption —
the failure mode if it is wrong is that the robot disappears entirely.

### 2.3 `GET /static/*` remains unauthenticated — `ACCEPTED`

The page, APIs and websocket are all gated, but static assets are not, because
the browser fetches them from a `<script src>` that carries no token. They are
inert JavaScript and CSS with no robot data, so this is accepted. Revisit if the
GUI is ever exposed beyond a lab network — a cookie set on the authenticated `/`
response would close it.

---

## 3. Docker image

### 3.1 The image is far larger than it needs to be — `TODO`

`docker/Dockerfile` comments call the `rosdep install` step "a safety net … if it
starts installing things, add them here". It installs on **every** build:

```
0 upgraded, 414 newly installed, 0 to remove
Need to get 288 MB of archives.
```

including `ros-jazzy-rviz-*`, `ros-jazzy-slam-toolbox`, `ros-jazzy-gz-*-vendor`,
gfortran and openmpi — all dragged in by the `create3_examples` submodule, none
of it needed to drive the robot or serve the GUI. That is ~89 s of the build and
a large share of the image.

Options: add a `COLCON_IGNORE` to `src/create3_examples`, build with
`--packages-up-to create3_bringup create3_web`, or make the examples an opt-in
build argument. Then correct the Dockerfile comment, whose stated invariant has
already been violated without anyone noticing.

---

## 4. Native (from-source) path

The uv recipe is verified end to end and is documented in `README.md`, including
the two non-obvious traps (`--system-site-packages` is mandatory; activating the
venv does nothing, so the venv must be bridged onto `PYTHONPATH` *after*
`source install/setup.bash`). What remains is making it reproducible.

### 4.1 Add `pyproject.toml` + `uv.lock` — `TODO`

Loose `uv pip install fastapi uvicorn websockets` resolved to fastapi 0.141.1 /
starlette 1.6.0 / pydantic 2.13.5 today; someone setting up next month gets
different versions from the Docker image's apt-pinned ones, and "works in Docker,
breaks natively" becomes unreproducible. A lock file also collapses the install
to `uv sync`.

Do **not** list `rclpy`, `geometry_msgs` or `irobot_create_msgs` — those come from
ROS via `--system-site-packages`. Pin `requires-python = "==3.12.*"` to match ROS
2 Jazzy's interpreter, and set `python-preference = "only-system"` and
`python-downloads = "never"` under `[tool.uv]`.

Unverified caveat: `uv sync` manages `.venv` itself and does not accept
`--system-site-packages` as a project setting, so `uv venv` may still have to
create the venv first. Test before committing.

### 4.2 Provide a `setup_native.sh` — `TODO`

The source-and-export steps (ROS, workspace, `PYTHONPATH` bridge) are fiddly and
order-dependent. Ship them as a `source`-able script so nobody has to get the
ordering right by hand.

---

## 5. Multi-repo and host infrastructure

### 5.1 Share one `ROS_DOMAIN_ID` across repos — `TODO`

This repo now has an `.env` with `ROS_DOMAIN_ID=0`, but each other repo will fall
back to its own `${ROS_DOMAIN_ID:-0}` default. It works today and fails silently
the moment one repo disagrees: the containers simply stop seeing each other, with
no error anywhere.

Note that `env_file:` does **not** solve this — `${VAR}` substitution in a compose
file reads the shell environment or `./.env`, not `env_file`. Use one shared file
symlinked into each repo, or `--env-file`.

```bash
echo 'ROS_DOMAIN_ID=0' > /home/cpsl/cpsl-ros.env
ln -s /home/cpsl/cpsl-ros.env /home/cpsl/CPSL_ROS2_Create3/.env
```

Careful: this repo's `.env` also holds `CREATE3_WEB_TOKEN` and the rest of the
local configuration, so it cannot simply be replaced by the symlink above — the
shared file needs to be a second `--env-file`, or the token moved.

Keep any custom domain ID in **0–101** on Linux, or DDS port math collides with
the ephemeral port range.

### 5.2 Legacy `~/fastdds_nuc.xml` and `ROS_STATIC_PEERS` entries — `TODO`

`~/.bashrc` still sets `FASTRTPS_DEFAULT_PROFILES_FILE=~/fastdds_nuc.xml`, whose
`initialPeersList` names an unreachable `192.168.0.30` — see 1.2 for what this
breaks. `ROS_STATIC_PEERS` also lists `192.168.0.30`, `david_laptop` and `ugv_1`,
which resolve to nothing on this machine. The containers deliberately do not set
either variable, so only the native path is affected.

Decide whether the native path needs a profile at all. If not, unset it; the
environment variables alone are sufficient.

### 5.3 Stale netplan file causes a boot-time parse error — `TODO`

`/etc/netplan/90-NM-7e326732-021e-346b-95c6-db9fe06a6090.yaml` contains an invalid
`192.168.186.2/0`. Needs a root shell to inspect and remove. Harmless today
because the NetworkManager profile itself is correct.

### 5.4 `ipv4.never-default` is `no` on the robot link profile — `TODO`

`bootstrap_host.sh` flags this. The profile has no gateway so no default route is
installed today, but a default route over the robot link would send this machine's
internet traffic at a robot that cannot forward it.

```bash
sudo nmcli connection modify netplan-NM-7e326732-021e-346b-95c6-db9fe06a6090 \
  ipv4.never-default yes
```

### 5.5 Untracked backup file in `CPSL_Manuals` — `TODO`

`UGVs/iRobotCreate3_Hardware.md.bak-20260917` is an untracked leftover. The
original is in git history, so it is redundant. (`README.md.bak-20260917` in this
repo has already been removed.)

---

## 6. Future direction

- **Containerise the remaining repos.** `CPSL_ROS2_PCProcessing` is the one that
  pays off — 2.3 GB, 8 submodules, torch and torch-geometric under poetry. The
  Create 3 container is the validated template: host networking, `ipc`/`pid`
  host, UID mapping, per-service DDS environment scoping, dev-vs-frozen builds.
- **Docker Desktop on macOS/Windows will not work** for the robot link.
  `network_mode: host` behaves differently there because containers run inside a
  VM without the host's LAN interfaces. Portability here means across Linux
  distributions, which is still the win — it removes the dependency on running
  the one Ubuntu release that packages the ROS distro.
- **Replace the tmux workflow with compose services.** Each pane becomes a
  service, which gets restart policies, `depends_on` with healthchecks, and
  `docker compose logs -f <service>` in place of the `sleep 30` ordering hacks in
  `Start_UGV_collect_dataset.sh`.
- **Extend the web GUI into a process console.** Endpoints backed by
  `docker compose` to list, start and stop services and stream their logs. This
  is the reason the GUI has a custom backend rather than rosbridge.
- **For heavy visualisation, add `foxglove_bridge` alongside** rather than
  extending the GUI. Point clouds and images do not belong on a JSON websocket.
  `ros-jazzy-foxglove-bridge` is available in apt.
