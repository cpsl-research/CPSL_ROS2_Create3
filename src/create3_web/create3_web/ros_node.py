"""ROS 2 side of the Create 3 web GUI.

Owns everything that touches rclpy: it subscribes to the robot's telemetry
topics, publishes ``cmd_vel`` on behalf of the browser, and drives the dock and
undock actions.

Two design points matter here.

*Server-side throttling.* The robot publishes ``imu`` at ~100 Hz and several
other topics in the tens of Hz. Forwarding all of that to a browser as JSON is
what makes naive ROS web bridges heavy. Instead every callback just writes into
a snapshot, and the web layer samples that snapshot at its own, much lower rate.
Cost is therefore independent of how fast the robot talks.

*Server-side deadman.* The browser sends a velocity command repeatedly while a
key is held. The node republishes the most recent one at a fixed rate and zeroes
it as soon as it goes stale. A dropped websocket, a lost key-up event (which
browsers routinely swallow when the window loses focus), or a closed laptop lid
therefore stops the robot instead of leaving it driving.
"""

from __future__ import annotations

import math
import threading
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, Imu

from irobot_create_msgs.action import Dock, Undock
from irobot_create_msgs.msg import (
    DockStatus,
    HazardDetectionVector,
    KidnapStatus,
    StopStatus,
    WheelVels,
)

# The robot publishes its sensor topics best-effort; a reliable subscription
# would simply never match and the GUI would show nothing at all.
SENSOR_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    durability=QoSDurabilityPolicy.VOLATILE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)

HAZARD_NAMES = {
    0: 'backup_limit',
    1: 'bump',
    2: 'cliff',
    3: 'stall',
    4: 'wheel_drop',
    5: 'object_proximity',
}


def _yaw_from_quaternion(q) -> float:
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


class Create3WebNode(Node):
    """Aggregates robot telemetry and accepts control input from the web layer."""

    def __init__(
        self,
        namespace: str = 'cpsl_ugv_1',
        cmd_rate_hz: float = 20.0,
        cmd_timeout_s: float = 0.4,
        max_linear: float = 0.31,
        max_angular: float = 1.90,
    ):
        super().__init__('create3_web')

        self.ns = namespace.strip('/')
        self.max_linear = max_linear
        self.max_angular = max_angular
        self.cmd_timeout_s = cmd_timeout_s

        # Guards every field the web layer reads or writes.
        self._lock = threading.Lock()
        self._state: dict = {}
        self._stamps: dict = {}

        self._cmd = (0.0, 0.0)
        self._cmd_time = 0.0
        self._estop = False

        self._action = {'name': None, 'state': 'idle', 'since': time.time(), 'detail': ''}
        self._goal_handle = None

        # hazard_detection only publishes when a hazard actually exists, so the
        # key is seeded here. Without it the GUI cannot tell "no hazards" (the
        # normal case) from "no data yet", and would report a healthy robot as
        # having a stale safety feed forever.
        self._state['hazards'] = []

        def topic(name: str) -> str:
            return f'/{self.ns}/{name}'

        self._pub_cmd = self.create_publisher(Twist, topic('cmd_vel'), 10)

        self.create_subscription(BatteryState, topic('battery_state'), self._on_battery, SENSOR_QOS)
        self.create_subscription(DockStatus, topic('dock_status'), self._on_dock, SENSOR_QOS)
        self.create_subscription(Odometry, topic('odom'), self._on_odom, SENSOR_QOS)
        self.create_subscription(WheelVels, topic('wheel_vels'), self._on_wheels, SENSOR_QOS)
        self.create_subscription(HazardDetectionVector, topic('hazard_detection'), self._on_hazards, SENSOR_QOS)
        self.create_subscription(KidnapStatus, topic('kidnap_status'), self._on_kidnap, SENSOR_QOS)
        self.create_subscription(StopStatus, topic('stop_status'), self._on_stop, SENSOR_QOS)
        self.create_subscription(Imu, topic('imu'), self._on_imu, SENSOR_QOS)

        self._dock_client = ActionClient(self, Dock, topic('dock'))
        self._undock_client = ActionClient(self, Undock, topic('undock'))

        self.create_timer(1.0 / cmd_rate_hz, self._publish_cmd)

        self.get_logger().info(f'create3_web bridging namespace /{self.ns}')

    # --- subscriptions ---------------------------------------------------
    def _set(self, key: str, value) -> None:
        with self._lock:
            self._state[key] = value
            self._stamps[key] = time.time()

    def _on_battery(self, msg: BatteryState) -> None:
        self._set('battery', {
            'percentage': round(float(msg.percentage), 4),
            'voltage': round(float(msg.voltage), 3),
            'temperature': round(float(msg.temperature), 2),
            'present': bool(msg.present),
        })

    def _on_dock(self, msg: DockStatus) -> None:
        self._set('dock', {'is_docked': bool(msg.is_docked), 'dock_visible': bool(msg.dock_visible)})

    def _on_odom(self, msg: Odometry) -> None:
        p = msg.pose.pose.position
        self._set('odom', {
            'x': round(p.x, 4),
            'y': round(p.y, 4),
            'yaw': round(_yaw_from_quaternion(msg.pose.pose.orientation), 4),
            'vx': round(msg.twist.twist.linear.x, 4),
            'wz': round(msg.twist.twist.angular.z, 4),
        })

    def _on_wheels(self, msg: WheelVels) -> None:
        self._set('wheels', {
            'left': round(float(msg.velocity_left), 3),
            'right': round(float(msg.velocity_right), 3),
        })

    def _on_hazards(self, msg: HazardDetectionVector) -> None:
        # BACKUP_LIMIT is reported continuously while docked and is not a fault,
        # so it would otherwise pin the hazard banner on permanently.
        hazards = []
        for d in msg.detections:
            name = HAZARD_NAMES.get(int(d.type), f'type_{int(d.type)}')
            if name == 'backup_limit':
                continue
            frame = (d.header.frame_id or '').strip()
            hazards.append(f'{name}:{frame}' if frame else name)
        self._set('hazards', hazards)

    def _on_kidnap(self, msg: KidnapStatus) -> None:
        self._set('kidnapped', bool(msg.is_kidnapped))

    def _on_stop(self, msg: StopStatus) -> None:
        self._set('stopped', bool(msg.is_stopped))

    def _on_imu(self, msg: Imu) -> None:
        self._set('imu', {
            'ax': round(msg.linear_acceleration.x, 3),
            'ay': round(msg.linear_acceleration.y, 3),
            'az': round(msg.linear_acceleration.z, 3),
        })

    # --- teleop ----------------------------------------------------------
    def set_twist(self, linear: float, angular: float) -> tuple[float, float]:
        """Accept a velocity command from the web layer, clamped to configured limits."""
        if self._estop:
            return (0.0, 0.0)
        lin = max(-self.max_linear, min(self.max_linear, float(linear)))
        ang = max(-self.max_angular, min(self.max_angular, float(angular)))
        with self._lock:
            self._cmd = (lin, ang)
            self._cmd_time = time.time()
        return (lin, ang)

    def stop(self) -> None:
        with self._lock:
            self._cmd = (0.0, 0.0)
            self._cmd_time = time.time()
        msg = Twist()
        self._pub_cmd.publish(msg)

    def set_estop(self, engaged: bool) -> None:
        with self._lock:
            self._estop = bool(engaged)
            if engaged:
                self._cmd = (0.0, 0.0)
        if engaged:
            self.cancel_action()
            self._pub_cmd.publish(Twist())

    @property
    def estop(self) -> bool:
        with self._lock:
            return self._estop

    def _publish_cmd(self) -> None:
        """Republish the last command, or zero once it goes stale (the deadman)."""
        with self._lock:
            lin, ang = self._cmd
            age = time.time() - self._cmd_time
            estop = self._estop

        if estop or age > self.cmd_timeout_s:
            # Only keep asserting zero for a short while after the command goes
            # stale; beyond that stay quiet so this node does not fight nav2 or
            # any other publisher that legitimately owns cmd_vel.
            if estop or age < self.cmd_timeout_s + 1.0:
                self._pub_cmd.publish(Twist())
            return

        msg = Twist()
        msg.linear.x = lin
        msg.angular.z = ang
        self._pub_cmd.publish(msg)

    # --- actions ---------------------------------------------------------
    def _set_action(self, name, state, detail='') -> None:
        with self._lock:
            self._action = {'name': name, 'state': state, 'since': time.time(), 'detail': detail}

    def start_action(self, which: str) -> tuple[bool, str]:
        """Send a dock or undock goal. Returns (accepted, message)."""
        if self.estop:
            return False, 'e-stop is engaged'

        client = self._dock_client if which == 'dock' else self._undock_client
        goal = Dock.Goal() if which == 'dock' else Undock.Goal()

        if not client.wait_for_server(timeout_sec=2.0):
            self._set_action(which, 'failed', 'action server unavailable')
            return False, f'{which} action server is not available'

        # Teleop and an autonomous dock fighting over cmd_vel helps nobody.
        self.stop()
        self._set_action(which, 'active')

        send_future = client.send_goal_async(goal)
        send_future.add_done_callback(lambda f, w=which: self._on_goal_response(f, w))
        return True, f'{which} requested'

    def _on_goal_response(self, future, which: str) -> None:
        try:
            handle = future.result()
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator
            self._set_action(which, 'failed', str(exc))
            return
        if not handle.accepted:
            self._set_action(which, 'rejected', 'goal rejected by the robot')
            return
        with self._lock:
            self._goal_handle = handle
        handle.get_result_async().add_done_callback(lambda f, w=which: self._on_goal_result(f, w))

    def _on_goal_result(self, future, which: str) -> None:
        with self._lock:
            self._goal_handle = None
        try:
            status = future.result().status
        except Exception as exc:  # noqa: BLE001
            self._set_action(which, 'failed', str(exc))
            return
        # 4 == STATUS_SUCCEEDED in action_msgs/GoalStatus
        self._set_action(which, 'succeeded' if status == 4 else 'failed', f'status={status}')

    def cancel_action(self) -> bool:
        with self._lock:
            handle = self._goal_handle
        if handle is None:
            return False
        handle.cancel_goal_async()
        self._set_action(self._action.get('name'), 'cancelled')
        return True

    # --- snapshot for the web layer --------------------------------------
    def snapshot(self) -> dict:
        """A JSON-ready view of everything the GUI draws."""
        now = time.time()
        with self._lock:
            state = dict(self._state)
            ages = {k: round(now - t, 2) for k, t in self._stamps.items()}
            cmd = self._cmd
            cmd_age = now - self._cmd_time if self._cmd_time else None
            estop = self._estop
            action = dict(self._action)

        state['t'] = round(now, 3)
        state['ages'] = ages
        state['estop'] = estop
        state['action'] = action
        # Report the command that is actually being published, not the last one
        # requested. Once the deadman has expired or the e-stop is engaged the
        # node publishes zero, and a GUI showing the stale request would tell the
        # operator the robot is being driven when it is not.
        stale = cmd_age is None or cmd_age > self.cmd_timeout_s
        effective = (0.0, 0.0) if (estop or stale) else cmd
        state['cmd'] = {
            'linear': effective[0],
            'angular': effective[1],
            'age': round(cmd_age, 2) if cmd_age is not None else None,
            'requested': {'linear': cmd[0], 'angular': cmd[1]},
            'active': not (estop or stale),
        }
        state['limits'] = {'max_linear': self.max_linear, 'max_angular': self.max_angular}
        state['namespace'] = self.ns
        # The robot is considered present only if something arrived recently;
        # otherwise the GUI would keep showing the last values forever.
        state['online'] = any(a < 5.0 for a in ages.values()) if ages else False
        return state
