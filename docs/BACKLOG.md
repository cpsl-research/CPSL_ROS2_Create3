# Review backlog — outstanding work

> **This is a working document, not user documentation.** It is a punch list of
> findings from three independent reviews of this repository, kept so they can be
> worked through deliberately rather than lost. Do not delete it during
> documentation cleanup, and do not treat it as setup instructions — the setup
> instructions are `README.md`, `scripts/README.md` and `src/create3_web/README.md`.

Findings come from an independent review of the native (from-source) install
path, an independent review of the Docker path, and items noticed during
development. Each entry says what is wrong, why it matters, and where to fix it.

**Status legend**

| | |
|---|---|
| `TODO` | not started |
| `DEFERRED` | deliberately postponed, with a reason |
| `DONE` | fixed; kept here for the record |

---

## 1. Correctness bugs

### 1.1 `tf_repub` and `odom_repub` emit frame IDs with a leading slash — `DEFERRED`

`src/tf_repub/tf_repub/tf_repub.py:12-17` (and `src/odom_repub/odom_repub/odom_repub.py:40-41`)

```python
self.namespace = self.get_namespace()        # already returns "/cpsl_ugv_1"
self.tf_prefix = "{}/".format(self.namespace)  # -> "/cpsl_ugv_1/"
```

`get_namespace()` already includes the leading slash, so the prefix ends up with
two levels of slash and the published frames are `/cpsl_ugv_1/odom` and
`/cpsl_ugv_1/base_link`. tf2 rejects these outright:

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

### 1.2 `preflight_create3.sh` aborts when run from a shell without ROS — `TODO`

`scripts/preflight_create3.sh` — `set -uo pipefail` (line 21) versus
`source /opt/ros/jazzy/setup.bash` (line 111).

```
[WARN] no ROS 2 environment in the calling shell (ROS_DISTRO unset)
/opt/ros/jazzy/setup.bash: line 8: AMENT_TRACE_SETUP_FILES: unbound variable
EXIT=1
```

Layers 3, 4 and 5 never run, and the user gets a bash error instead of a
diagnosis — in exactly the situation the script advertises that it handles. Fix
by wrapping the source in `set +u` / `set -u`.

### 1.3 Preflight layer 5 trusts the ROS 2 daemon and can report a false PASS — `TODO`

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

### 1.4 Preflight does not validate `FASTRTPS_DEFAULT_PROFILES_FILE` contents — `TODO`

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

---

## 2. Security and exposure

### 2.1 Web GUI reachable from the university network without authentication — `DONE`

The GUI binds `0.0.0.0:8080` and this host is on Duke's `10.197.36.73/16` as well
as the robot link. Verified reachable and serving live telemetry plus teleop and
dock/undock controls from the campus address, with `CREATE3_WEB_TOKEN` empty.

Fixed. A token is generated into `.env` (mode 600, gitignored), `CREATE3_WEB_HOST`
and `CREATE3_WEB_TELEMETRY_HZ` are now forwarded through compose, and **every**
surface is gated — the page itself, the telemetry API, the websocket, the control
endpoints and the diagnostics endpoints.

A hole was found while verifying this: the `/api/robot/*` diagnostics routes had
no authentication at all, because `admin.py` never received the token callback.
`POST /api/robot/reboot` was therefore open to anyone who could reach the port.
Now gated. Verified: all nine endpoints return 401 unauthenticated, including
from the campus address, and the websocket rejects a missing or wrong token.

Remaining:

- Decide whether the GUI should bind the robot subnet only, and accept that this
  makes it unreachable from a laptop on wifi. A token plus `0.0.0.0` is the
  usable compromise; binding to `192.168.186.3` is the strict one.
- A token in a query string appears in browser history and any proxy logs.
  Acceptable on a lab network; revisit if this is ever exposed more widely.
- There is no TLS, so the token crosses the network in clear text.

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
one another; the static peer covers the robot. Needs testing before adoption.

---

## 2b. Docker path and dev workflow

### 2b.1 Documented dev rebuild command was unresolvable — `DONE`

`docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm colcon`
failed with `invalid service "colcon". Must specify either image or build`, and
poisoned the whole project so that even `config` errored. Cause: `extends:` with
no `file:` resolves within the same file, where `shell` was only a volumes
fragment with no image.

Fixed: `extends` now names `docker-compose.yml` explicitly, and the volume list
is a top-level anchor so `colcon` actually receives the source mount and the
build/install volumes — without them it would have "rebuilt" the image's baked-in
copy into a throwaway layer. Verified: `11 packages finished [4.89s]`, exit 0.

### 2b.2 Dev override skipped the `web` service — `DONE`

`docker-compose.dev.yml` mounted the host source into `bringup`, `teleop`,
`shell` and `preflight` but not `web` — the package most likely to be edited,
being the GUI. Dev mode silently kept serving the copy baked into the image.
Fixed.

### 2b.3 Two documented web settings were dropped by compose — `DONE`

`src/create3_web/README.md` documents `CREATE3_WEB_HOST` and
`CREATE3_WEB_TELEMETRY_HZ`, and the code reads both, but `docker-compose.yml`
never forwarded them, so they worked natively and were dead under Docker. Both
now forwarded.

### 2b.4 The image is far larger than it needs to be — `TODO`

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

### 2b.5 Named volumes in dev mode are seeded once and never refreshed — `TODO`

`/ws/install` is populated from the image when the volume is first created, then
never again. After a `docker compose build`, the dev stack keeps running the old
install tree until the colcon service is re-run or the volumes are deleted. Now
noted in `docker-compose.dev.yml`; it should also be in the README's development
section.

### 2b.6 `GET /static/*` remains unauthenticated — `TODO` (accepted for now)

The page, APIs and websocket are all gated, but static assets are not, because
the browser fetches them from a `<script src>` that carries no token. They are
inert JavaScript and CSS with no robot data, so this is accepted. Revisit if the
GUI is ever exposed beyond a lab network — a cookie set on the authenticated `/`
response would close it.

### 2b.7 `CREATE3_SCRIPTS_DIR` is undocumented — `TODO`

`admin.py` reads it; the `src/create3_web/README.md` configuration table omits it.

---

## 3. Documentation defects

### 3.1 The `LARGE_DATA` symptom table is wrong, and two documents contradict — `TODO`

`README.md` claims `LARGE_DATA` yields **0** discovered nodes, and directs the
user to check for an empty `ros2 node list`. What actually happens:

```
$ ros2 node list            # all TEN nodes, looks perfectly healthy
$ ros2 topic echo /cpsl_ugv_1/battery_state --once
ECHO_EXIT=124               # nothing ever arrives
```

The "0 nodes" figure only reproduces with `--no-daemon`. **The documented
diagnostic is precisely the one that does not fire.**

The two reviews measured it independently and neither document is right. With
`--no-daemon`, nodes are **0** but **all 26 topics are present** (including
robot-only ones like `ir_intensity`, `cliff_intensity`, `slip_status`), and no
user data flows. With the daemon, the graph looks entirely healthy. So:

| | with `ros2` daemon | `--no-daemon` |
|---|---|---|
| nodes | all 10, looks healthy | 0 |
| topics | all present | all present |
| `topic echo` | nothing arrives | nothing arrives |

`README.md` says no topics appear; `scripts/README.md` says nodes and topics list
normally. The reliable signature is the one thing both agree on: **discovery
gives you something, data gives you nothing.**

Fix: drop the node-count table, describe the real signature, make
`ros2 topic echo` the diagnostic, and explain the daemon.

### 3.2 The native path omits host preparation entirely — `TODO`

`README.md` says "Steps 4 and 5 apply either way", implying steps 1–3 are the
complete native substitute for the Docker quick start. They are not: the Docker
quick start's step 0 is `sudo scripts/bootstrap_host.sh`, and the native section
never mentions it, the static IP, or how to set up chrony. A user following it
literally has no address on `192.168.186.0/24`, so `configure_create3.py` cannot
reach the robot at all.

Fix: the native section must start with `sudo scripts/bootstrap_host.sh --skip-docker`.
Also, that script's closing "Next:" text recommends `docker compose up -d`, which
is wrong guidance for a native user — make it aware of which path is being set up.

### 3.3 Stale RViz remap in Tutorial 6 — `TODO`

`README.md` shows `rviz2 --ros-args --remap /tf:=/forwarded_tf`. Nothing
publishes `/forwarded_tf`; `tf_repub` publishes on `/tf`, as the same document
says two sections earlier. Leftover from an older design.

### 3.4 The native apt list is both redundant and incomplete — `TODO`

- Redundant: it installs `ros-jazzy-irobot-create-msgs` while
  `src/irobot_create_msgs` is a submodule built from source. Both end up
  installed and the overlay wins — a version-skew trap (both happen to be 3.0.0
  today).
- Incomplete: a clean machine also needs `joy`, `teleop_twist_joy`,
  `slam_toolbox` and `rplidar_ros`, pulled in by the `create3_examples`
  submodule.

### 3.5 Brittle hard-coded topic count — `TODO`

`README.md` says "expect 25 topics"; measured 25 and 26 depending on what else is
attached. `preflight_create3.sh` sensibly asserts `>= 20`. Soften the prose.

---

## 4. Gaps a new user falls into

| | Gap | Where |
|---|---|---|
| 4.1 | The **ROS 2 daemon** is never mentioned, yet it is the mechanism by which the documented `LARGE_DATA` diagnostic fails. Document `--no-daemon` and `ros2 daemon stop`. | `README.md` |
| 4.2 | **Stale terminals** keep old exports after `~/.bashrc` is fixed. `scripts/README.md` covers this well; `README.md`, which a new user reads first, does not. | `README.md` |
| 4.3 | **`create3_examples` is never mentioned.** A `--recurse-submodules` clone drags in six extra packages that `colcon build` builds unconditionally (11 total), and it is the only source of the `rplidar_ros` / `slam_toolbox` / `joy` dependencies. | `README.md` |
| 4.4 | `src/create3_web/README.md` shows `rosdep install --from-paths src ...` but never says to run it **from the workspace root**; `src` does not resolve from where that README lives. It also uses `--from-paths/--ignore-src` where `README.md` uses `-i/--from-path`. | `src/create3_web/README.md` |
| 4.5 | `.gitignore` has no `.venv/`. Harmless today only because uv writes a self-ignoring `.venv/.gitignore`; do not rely on that. | `.gitignore` |

---

## 5. Native path with uv

The uv recipe is verified end to end and belongs in the documentation. Two
findings were not obvious and must survive into whatever is written:

### 5.1 `--system-site-packages` is mandatory

ROS's `setup.bash` only adds `/opt/ros/jazzy/lib/python3.12/site-packages` to
`PYTHONPATH`. `rclpy` additionally imports apt-provided modules (`yaml`, and
downstream `numpy`, `lark`, `catkin_pkg`, `packaging`) from
`/usr/lib/python3/dist-packages`, which a plain venv excludes:

```
$ python -c "import rclpy"
  File ".../rclpy/parameter.py", line 27, in <module>
    import yaml
ModuleNotFoundError: No module named 'yaml'
```

### 5.2 Activating the venv does nothing — bridge it with `PYTHONPATH`

`colcon` is apt-installed with a `#!/usr/bin/python3` shebang and bakes that
shebang into every console script it generates, so `ros2 run` executes under the
system interpreter no matter which venv is active:

```
$ source .venv/bin/activate && ros2 run create3_web create3_web
ModuleNotFoundError: No module named 'fastapi'
$ head -1 install/create3_web/lib/create3_web/create3_web
#!/usr/bin/python3
```

Rebuilding with the venv active does not change this. The venv must instead be
put on `PYTHONPATH`, **after** `source install/setup.bash` (which prepends to it):

```bash
export PYTHONPATH="$PWD/.venv/lib/python3.12/site-packages:$PYTHONPATH"
```

This is safe only because the venv is built on the system interpreter, so the
installed wheels are ABI-compatible with `/usr/bin/python3.12`.

### 5.3 Add `pyproject.toml` + `uv.lock` — `TODO`

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

### 5.4 Provide a `setup_native.sh` — `TODO`

The source-and-export steps (ROS, workspace, `PYTHONPATH` bridge) are fiddly and
order-dependent. Ship them as a `source`-able script so nobody has to get the
ordering right by hand.

---

## 6. Multi-repo and infrastructure

### 6.1 Share one `ROS_DOMAIN_ID` across repos — `TODO`

There is no `.env` on disk, so every repo falls back to its own `${ROS_DOMAIN_ID:-0}`
default. It works today but fails silently the moment one repo disagrees: the
containers simply stop seeing each other, with no error anywhere.

Note that `env_file:` does **not** solve this — `${VAR}` substitution in a compose
file reads the shell environment or `./.env`, not `env_file`. Use one shared file
symlinked into each repo, or `--env-file`.

```bash
echo 'ROS_DOMAIN_ID=0' > /home/cpsl/cpsl-ros.env
ln -s /home/cpsl/cpsl-ros.env /home/cpsl/CPSL_ROS2_Create3/.env
```

Keep any custom domain ID in **0–101** on Linux, or DDS port math collides with
the ephemeral port range.

### 6.2 Stale netplan file causes a boot-time parse error — `TODO`

`/etc/netplan/90-NM-7e326732-021e-346b-95c6-db9fe06a6090.yaml` contains an invalid
`192.168.186.2/0`. Needs a root shell to inspect and remove. Harmless today
because the NetworkManager profile itself is correct.

### 6.3 `ipv4.never-default` is `no` on the robot link profile — `TODO`

`bootstrap_host.sh` flags this. The profile has no gateway so no default route is
installed today, but a default route over the robot link would send this machine's
internet traffic at a robot that cannot forward it.

```bash
sudo nmcli connection modify netplan-NM-7e326732-021e-346b-95c6-db9fe06a6090 \
  ipv4.never-default yes
```

### 6.4 Legacy `~/fastdds_nuc.xml` and `ROS_STATIC_PEERS` entries — `TODO`

`~/.bashrc` still sets `FASTRTPS_DEFAULT_PROFILES_FILE=~/fastdds_nuc.xml`, whose
`initialPeersList` names an unreachable `192.168.0.30` — see 1.4 for what this
breaks. `ROS_STATIC_PEERS` also lists `192.168.0.30`, `david_laptop` and `ugv_1`,
which resolve to nothing on this machine. The containers deliberately do not set
either variable, so only the native path is affected.

Decide whether the native path needs a profile at all. If not, unset it; the
environment variables alone are sufficient.

### 6.5 Untracked backup files — `TODO`

`README.md.bak-20260917` and `UGVs/iRobotCreate3_Hardware.md.bak-20260917` (in
`CPSL_Manuals`) are untracked leftovers. The originals are in git history, so
these are redundant.

---

## 7. Future direction

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
