# 1. Host setup

Prepare the computer that will talk to the robot (a NUC, a laptop). Three things belong to the
host and cannot live in a container: a **static IP** on the wired link to the robot, a **time
server** (the Create 3 has no battery-backed clock, so it takes its time from the host), and
**Docker** if you want the container path.

You need: Ubuntu 24.04 **with NetworkManager** (Ubuntu Desktop has it; Ubuntu Server uses
netplan/networkd and does not, so `nmcli` is missing), a wired Ethernet port, and the robot
connected to it by cable and powered on. Install ROS 2 separately only for the native path
([tutorial 06](06_native_install.md)).

## Fixed addresses

| | Address |
|---|---|
| Robot | `192.168.186.2` (factory default for the wired link) |
| This host | `192.168.186.3` |

Defaults live in `scripts/bootstrap_host.sh` (`HOST_IP`, `ROBOT_IP`); override with
`--host-ip` and `--robot-ip`.

## Step 1: preview

```bash
cd CPSL_ROS2_Create3
scripts/bootstrap_host.sh --dry-run
```

It changes nothing and needs no root. You should see three sections: `1. Static IP on the robot
link`, `2. NTP server for the robot`, `3. Docker`, then `Summary` with `N change(s) would be
made`. Each line is tagged `[ok]` (already fine), `[..]` (would change) or `[!!]` (a problem you
must fix).

A typical `[!!]` is `could not autodetect the interface facing the robot`. The script looks for
a wired interface with link but no address. Plug the cable in, or name the interface:

```bash
ip -br link                                  # find it, e.g. enp86s0
scripts/bootstrap_host.sh --dry-run --iface enp86s0
```

## Step 2: apply

```bash
sudo scripts/bootstrap_host.sh               # everything
sudo scripts/bootstrap_host.sh --skip-docker # native path: no Docker needed
```

What it does, and nothing more if it is already true:

1. **Network.** Creates a NetworkManager profile `create3-wired` giving the interface
   `192.168.186.3/24`, `ipv4.never-default yes` (so internet traffic never goes to the robot).
   If an interface already holds an address on `192.168.186.x` it is left alone.
2. **Time.** Installs `chrony` if missing and appends `allow 192.168.186.0/24` to
   `/etc/chrony/chrony.conf` (backing the file up first), then restarts chrony.
3. **Docker.** If Docker is missing, installs it with Docker's convenience script
   (`get.docker.com`); adds you to the `docker` group. **Log out and back in** for the group
   to take effect.

Skip a section with `--skip-network`, `--skip-ntp` or `--skip-docker`.

## Check it

```bash
ip -br addr | grep 192.168.186               # the interface holds 192.168.186.3/24
ping -c 3 192.168.186.2                      # replies once the robot is on the cable
chronyc tracking | head -3                   # chrony is running
```

Run the dry-run again: every line should now be `[ok]` and `0 change(s)`.

## If something is off

- `nmcli: command not found`: the host is not NetworkManager-managed. Configure the static
  address yourself (netplan) and run with `--skip-network`.
- The robot does not answer ping: cable, or the robot booted without the cable. Reboot it
  ([tutorial 02](02_robot_config.md)).
- Next: [robot configuration](02_robot_config.md).
