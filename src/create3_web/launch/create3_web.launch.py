"""Launch the Create 3 web GUI.

The node reads its configuration from the environment so that the same launch
file works unchanged inside the container, where docker compose supplies the
values. Launch arguments override the environment when given.
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    args = [
        DeclareLaunchArgument('namespace', default_value=os.environ.get('CREATE3_NAMESPACE', 'cpsl_ugv_1'),
                              description='robot namespace, without a leading slash'),
        DeclareLaunchArgument('host', default_value=os.environ.get('CREATE3_WEB_HOST', '0.0.0.0'),
                              description='address the web server binds to'),
        DeclareLaunchArgument('port', default_value=os.environ.get('CREATE3_WEB_PORT', '8080'),
                              description='port the web server listens on'),
        DeclareLaunchArgument('max_linear', default_value=os.environ.get('CREATE3_WEB_MAX_LINEAR', '0.31'),
                              description='teleop linear speed cap in m/s'),
        DeclareLaunchArgument('max_angular', default_value=os.environ.get('CREATE3_WEB_MAX_ANGULAR', '1.90'),
                              description='teleop angular speed cap in rad/s'),
        DeclareLaunchArgument('token', default_value=os.environ.get('CREATE3_WEB_TOKEN', ''),
                              description='shared access token; empty disables authentication'),
    ]

    node = Node(
        package='create3_web',
        executable='create3_web',
        name='create3_web',
        output='screen',
        additional_env={
            'CREATE3_NAMESPACE': LaunchConfiguration('namespace'),
            'CREATE3_WEB_HOST': LaunchConfiguration('host'),
            'CREATE3_WEB_PORT': LaunchConfiguration('port'),
            'CREATE3_WEB_MAX_LINEAR': LaunchConfiguration('max_linear'),
            'CREATE3_WEB_MAX_ANGULAR': LaunchConfiguration('max_angular'),
            'CREATE3_WEB_TOKEN': LaunchConfiguration('token'),
        },
    )
    return LaunchDescription(args + [node])
