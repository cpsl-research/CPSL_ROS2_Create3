"""Entry point: runs the rclpy executor and the web server in one process.

rclpy wants to spin its own executor and uvicorn wants to own an asyncio loop,
so the executor runs on a background thread and uvicorn keeps the main thread.
They communicate only through the node's snapshot and command setters, both of
which are mutex-guarded, so no ROS objects are touched from the event loop.
"""

from __future__ import annotations

import os
import threading

import rclpy
from rclpy.executors import MultiThreadedExecutor

from ament_index_python.packages import get_package_share_directory

from .ros_node import Create3WebNode
from .server import create_app


def _env(name: str, default):
    raw = os.environ.get(name)
    if raw is None or raw == '':
        return default
    if isinstance(default, bool):
        return raw.lower() in ('1', 'true', 'yes', 'on')
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, int):
        return int(raw)
    return raw


def main(args=None) -> None:
    import uvicorn

    namespace = _env('CREATE3_NAMESPACE', 'cpsl_ugv_1')
    host = _env('CREATE3_WEB_HOST', '0.0.0.0')
    port = int(_env('CREATE3_WEB_PORT', 8080))
    telemetry_hz = float(_env('CREATE3_WEB_TELEMETRY_HZ', 10.0))
    max_linear = float(_env('CREATE3_WEB_MAX_LINEAR', 0.31))
    max_angular = float(_env('CREATE3_WEB_MAX_ANGULAR', 1.90))
    token = _env('CREATE3_WEB_TOKEN', '') or None
    robot_ip = _env('CREATE3_ROBOT_IP', '192.168.186.2')
    host_ip = _env('CREATE3_HOST_IP', '192.168.186.3')

    rclpy.init(args=args)
    node = Create3WebNode(
        namespace=namespace,
        max_linear=max_linear,
        max_angular=max_angular,
    )

    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True, name='rclpy-executor')
    spin_thread.start()

    try:
        web_dir = os.path.join(get_package_share_directory('create3_web'), 'web')
    except Exception:  # noqa: BLE001 - running from a source checkout
        web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web')

    app = create_app(
        node, web_dir, telemetry_hz=telemetry_hz, token=token,
        robot_ip=robot_ip, host_ip=host_ip,
    )

    node.get_logger().info(f'web GUI on http://{host}:{port}/  (serving {web_dir})')
    if token:
        node.get_logger().info('access token is REQUIRED (CREATE3_WEB_TOKEN is set)')
    else:
        node.get_logger().warn(
            'no CREATE3_WEB_TOKEN set: anyone who can reach this port can drive the robot'
        )

    try:
        uvicorn.run(app, host=host, port=port, log_level='warning', ws_ping_interval=20)
    except KeyboardInterrupt:
        pass
    finally:
        # Never leave the robot with a live velocity command.
        try:
            node.stop()
        except Exception:  # noqa: BLE001
            pass
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
