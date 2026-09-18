# Create 3 setup and diagnostic scripts

Three scripts that automate the parts of the Create 3 setup that live outside this
repository's source tree: one prepares **the host**, one configures **the robot**,
and one diagnoses the link between them.

The Create 3 stores its ROS 2 and networking configuration in its own flash. None of it
is in this repo, in a dotfile, or in a container image, so a robot that has been factory
reset, re-flashed, or swapped for a spare needs all of it re-entered through the web UI
before it will ever appear in `ros2 node list`. These scripts make that configuration
reproducible, and make diagnosing a silent link fast.

| Script | Acts on | What it does |
|---|---|---|
| `bootstrap_host.sh` | **the host** | Prepares a fresh host: static IP on the robot link, chrony, Docker |
| `configure_create3.py` | the robot | Reads, diffs and applies the robot's configuration over its web UI |
| `preflight_create3.sh` | both | Walks the five layers of the link and names the one that is broken |

They need no Python packages beyond the standard library and no ROS build, but they
are not free of external commands. `bootstrap_host.sh` needs **`nmcli`** — so a
NetworkManager-managed host — plus `ip`, `systemctl` and `apt-get`.
`preflight_create3.sh` needs **`ip`**, **`ping`** and **`curl`**, and **`ros2`** for
layer 5. That is exactly why `docker/Dockerfile` apt-installs `iputils-ping`,
`iproute2` and `curl`: without them the in-container preflight cannot run.

They run in order, and the order matters:

```bash
sudo ./bootstrap_host.sh                   # host: static IP + chrony + Docker (once per machine)
./configure_create3.py apply               # robot: its own flash configuration
cd .. && docker compose up -d              # the ROS 2 stack
docker compose run --rm preflight          # verify all five layers
```

For a native (non-Docker) install, `bootstrap_host.sh --skip-docker` is the first
step instead, and `./preflight_create3.sh` on the host is the right verification.
Run the host copy only on a machine that actually has ROS 2: without it, layer 5
is skipped and the script still reports a healthy link (see below).

`configure_create3.py` reaches the robot over IP, so the host must already hold its
static address on the robot subnet. The robot also has no battery-backed clock and takes
its time from the host. Neither the address nor the NTP server can come from a
container, which is what `bootstrap_host.sh` is for.

---

## `bootstrap_host.sh`

Prepares the three things a container cannot own, because they belong to the host kernel
and the host's service manager:

1. a static IP on the direct Ethernet link to the robot (a NetworkManager profile)
2. chrony, serving time to the robot's subnet
3. Docker and the `docker` group

```bash
./bootstrap_host.sh --dry-run          # print every change it would make
sudo ./bootstrap_host.sh               # apply
sudo ./bootstrap_host.sh --skip-docker # if Docker is managed some other way
```

| Option | Default | Meaning |
|---|---|---|
| `--iface NAME` | autodetect | Ethernet interface facing the robot |
| `--host-ip IP` | `192.168.186.3` | this machine's address on the robot subnet |
| `--robot-ip IP` | `192.168.186.2` | the robot's address |
| `--con-name NAME` | `create3-wired` | NetworkManager profile to create |
| `--skip-network`, `--skip-ntp`, `--skip-docker` | off | skip a section |
| `-n`, `--dry-run` | off | show what would happen, change nothing |

It is idempotent and conservative. Every mutating command is routed through one helper,
so `--dry-run` is honest by construction rather than by remembering to guard each call
site. If a network profile already provides the right address it is left alone rather
than duplicated -- on a machine where netplan already manages the link, creating a second
NetworkManager profile for the same interface would fight with the first.

Interface autodetection looks for a wired interface that has carrier but no address yet,
and declines rather than guessing if it cannot find one. Pass `--iface` in that case.

---

## `preflight_create3.sh`

Start here whenever the robot is not showing up. The link has five independent layers,
and a fault in any one of them produces the same unhelpful symptom — an empty
`ros2 node list`. This checks them from the bottom up, so you are not guessing whether
the cause is a cable, a clock, the robot's flash configuration, or an environment
variable in `~/.bashrc`.

```bash
./preflight_create3.sh                  # full check, ~10 s
./preflight_create3.sh --quick          # skip the DDS discovery and live-data checks
./preflight_create3.sh --robot 192.168.186.2 --nuc 192.168.186.3 --namespace /cpsl_ugv_1
```

Exit status is 0 only if every check passed, so it also works as a gate in a startup
script.

What each layer covers:

| Layer | Checks |
|---|---|
| 1. NUC network interface | which interface holds the robot subnet, link carrier, packets received |
| 2. NUC ROS 2 environment | `ROS_DISTRO`, `ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`, `ROS_AUTOMATIC_DISCOVERY_RANGE`, `FASTDDS_BUILTIN_TRANSPORTS`, `FASTRTPS_DEFAULT_PROFILES_FILE` |
| 3. Link to the robot | ICMP, web UI reachable |
| 4. Robot-side configuration | domain id / namespace / RMW agree with the host, discovery server off, RMW profile override names the host, `ntp.conf` points at the host, clock skew under 5 s |
| 5. DDS discovery and live data | all ten robot nodes discovered, topic count, and a real message received on `battery_state` and `dock_status` |

Layer 5 checking *data* and not just discovery is deliberate, and it is the layer
that catches `FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA`. A transport mismatch lets
discovery succeed while no user data ever flows: **discovery gives you something,
data gives you nothing.** Topic names are still advertised, and whether nodes are
listed depends on whether the long-lived `ros2` daemon answers from its cache or
the query goes to the network. So neither an empty nor a full `ros2 node list`
settles it — only receiving a message does. `README.md` has the full table and
the `--no-daemon` / `ros2 daemon stop` explanation.

> **Layer 5 is skipped, not failed, when the `ros2` CLI is not on `PATH`** — it
> reports `the ros2 CLI is not on PATH; skipping discovery checks` as a warning.
> On a Docker-only host that means the script can print `The Create 3 link is
> healthy` and exit 0 having never tested whether any data flows. On such a host
> use `docker compose run --rm preflight` instead, which has ROS 2 inside it.

Layer 2 also greps `~/.bashrc` itself, not just the current environment. An uncommented
`export FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA` there will break the next terminal you
open even when the shell you are testing from is clean.

> **Note:** terminals opened *before* such a line was commented out keep the old value.
> After changing `~/.bashrc`, open a fresh terminal — or check with
> `env -i HOME=$HOME USER=$USER TERM=xterm bash -ilc ./preflight_create3.sh`.

---

## `configure_create3.py`

Declaratively manages the robot-side configuration. It reads the robot's current state,
compares it against the desired state, shows a diff, and POSTs only the forms that
actually differ. It is idempotent — run it twice and the second run reports
`already up to date` and sends nothing.

```bash
./configure_create3.py show                 # print current robot configuration (default)
./configure_create3.py show -v              # also dump the full config blocks
./configure_create3.py apply --dry-run      # show what would change, send nothing
./configure_create3.py apply                # apply, with a confirmation prompt
./configure_create3.py apply --yes          # apply unattended
./configure_create3.py restart-app          # restart the robot application, wait for nodes
./configure_create3.py restart-ntpd         # resync a drifted robot clock
./configure_create3.py reboot               # full reboot (needed after a cold boot with no cable)
```

Options (accepted before or after the subcommand):

| Option | Default | Meaning |
|---|---|---|
| `--robot IP` | `192.168.186.2` | the robot's address |
| `--nuc IP` | `192.168.186.3` | the host address used as the DDS initial peer and NTP server |
| `--namespace NS` | `/cpsl_ugv_1` | ROS namespace |
| `--domain-id N` | `0` | `ROS_DOMAIN_ID` |
| `--rmw NAME` | `rmw_fastrtps_cpp` | RMW implementation |
| `--safety MODE` | *leave alone* | rewrite `motion_control` `safety_override` (`none`, `backup_only`, `full`) |
| `-y`, `--yes` | off | skip confirmation prompts |
| `-n`, `--dry-run` | off | show the diff without sending anything |

`apply` sets four things: the ROS configuration, the **RMW profile override**, `ntp.conf`,
and (only when `--safety` is given) the motion-control parameters. It then restarts the
robot application and waits for all ten nodes to appear.

`safety_override` is left untouched unless you name it explicitly, because it controls
whether the robot respects cliff sensors. It is never changed as a side effect.

### Bringing up a fresh or reset robot

```bash
./configure_create3.py apply --yes          # push the whole configuration
./configure_create3.py reboot --yes         # reboot so networking re-initialises with the cable present
./preflight_create3.sh                      # confirm all five layers
```

The reboot matters: the Create 3 initialises networking and DDS at **boot**, not when the
application starts. A robot that powered on without its Ethernet cable will not announce
itself on the wired interface, and restarting the application is not enough to fix it.

### Disruptive commands

`set-wired-subnet N` changes the robot's wired subnet to `192.168.N.x`, which moves the
robot's own address to `192.168.N.2`. You will lose contact with it until the host's
static address is moved to the same subnet, and it only takes effect after a reboot. It is
intentionally a separate subcommand and is never part of `apply`.

---

## Reference

Full hardware and network documentation, including the host-side setup these scripts
assume, is in
[`CPSL_Manuals/UGVs/iRobotCreate3_Hardware.md`](https://github.com/davidmhunt/CPSL_Manuals/blob/main/UGVs/iRobotCreate3_Hardware.md).

Web UI endpoints used by `configure_create3.py`, verified against firmware
`create3+I.0.0.FastDDS` (sku `RCi3099`, ROS 2 Iron):

| Method | Path | Fields |
|---|---|---|
| `GET` | `/ros-config` | — |
| `GET` | `/rmw-profile-override` | — |
| `GET` | `/beta-ntp-conf` | — |
| `POST` | `/ros-config-save-main` | `ros_domain_id`, `ros_namespace`, `rmw_implementation`, `fast_discovery_server_enabled`, `fast_discovery_server_value` |
| `POST` | `/ros-config-save-params` | `yaml` |
| `POST` | `/rmw-profile-override-save` | `config` |
| `POST` | `/beta-ntp-conf-save` | `config` |
| `POST` | `/beta-wired-subnet-save` | `new_wired_subnet` |
| `POST` | `/api/restart-app` | — |
| `POST` | `/api/restart-ntpd` | — |
| `POST` | `/api/reboot` | — |

The firmware only routes `GET` and `POST`; a `HEAD` request returns 404. Unchecked
checkboxes submit no value at all, so `fast_discovery_server_enabled` is omitted entirely
to leave the discovery server disabled.
