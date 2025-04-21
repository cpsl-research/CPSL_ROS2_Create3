from ament_index_python.packages import get_package_share_directory
import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import PushRosNamespace, SetRemap, Node
from launch_ros.descriptions import ComposableNode, ParameterFile
from nav2_common.launch import RewrittenYaml


#locating other packages
pkg_tf_repub = get_package_share_directory('tf_repub')

#ROS2 launch arguments
ARGUMENTS = [
    DeclareLaunchArgument('namespace', default_value='',
                          description='namespace')                         
]

def launch_setup(context, *args, **kwargs):

    #load parameters
    namespace = LaunchConfiguration('namespace')

    #updating paths
    namespace_str = namespace.perform(context)
    if (namespace_str and not namespace_str.startswith('/')):
        namespace_str = '/' + namespace_str

    # Apply the following re-mappings only within this group
    bringup_group = GroupAction([
        PushRosNamespace(namespace),

        Node(
            package='tf_repub',
            executable='tf_repub',
            name='tf_repub',
            output='screen',
            parameters=[]
        ),
        Node(
            package='odom_repub',
            executable='odom_repub',
            name='odom_repub',
            output='screen',
            parameters=[]
        )
    ])

    return [bringup_group]


def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=launch_setup))
    return ld
