# TODO

Open items, one per line. Status: `TODO` not started, `ACCEPTED` known and kept, `DEFERRED` postponed.

- 2.1 `TODO` Web GUI exposure: bind address (`0.0.0.0` vs `CREATE3_WEB_HOST=192.168.186.3`), token in the query string, no TLS.
- 2.2 `TODO` DDS discovery is advertised on the university subnet; proposed `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` + `ROS_STATIC_PEERS=192.168.186.2`, untested against the robot.
- 2.3 `ACCEPTED` `GET /static/*` is unauthenticated (inert JS/CSS, no robot data); revisit if the GUI leaves the lab network.
- 3.1 `TODO` Image size: the `create3_examples` submodule that dominated the `rosdep install` step is removed (docs-09 Step 2); re-measure the image and update the Dockerfile comment if needed.
- 4.1 `TODO` Add `pyproject.toml` + `uv.lock` for the native path (no `rclpy`/`irobot_create_msgs` in it; `requires-python = "==3.12.*"`, `python-preference = "only-system"`); `uv venv --system-site-packages` may still be needed first.
- 4.2 `TODO` Ship a `source`-able `setup_native.sh` for the ROS / workspace / `PYTHONPATH` bridge ordering.
- 5.1 `TODO` Share one `ROS_DOMAIN_ID` across repos (a second `--env-file` or a shared symlinked file; keep the ID in 0-101); this repo's `.env` also holds `CREATE3_WEB_TOKEN`.
- 5.2 `TODO` Host cleanup needing root: (a) orphan `/etc/netplan/90-NM-7e326732-*.yaml` that fails to parse, (b) `chmod 600 /etc/netplan/01-network-manager-all.yaml`, (c) `ipv4.never-default yes` on the robot-link profile.
- 5.3 `TODO` Remove the untracked `UGVs/iRobotCreate3_Hardware.md.bak-20260917` in `CPSL_Manuals` (original is in git history).
- 6.1 `TODO` Containerise the remaining repos (`CPSL_ROS2_PCProcessing` first; the Create 3 container is the template).
- 6.2 `TODO` Replace the tmux workflow with compose services (restart policies, healthchecks, `docker compose logs -f`).
- 6.3 `TODO` Extend the web GUI into a process console (compose-backed list/start/stop/logs).
- 6.4 `TODO` For heavy visualisation add `foxglove_bridge` (`ros-jazzy-foxglove-bridge`) rather than extending the GUI.
- 6.5 `ACCEPTED` Docker Desktop on macOS/Windows will not work for the robot link (`network_mode: host`); Linux distributions only.
