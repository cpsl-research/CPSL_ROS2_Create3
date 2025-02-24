# CPSL ROS2 Create3 ROS2 Nodes

A collection of nodes/packages used to interact with the iRobot Create3 in simulation or otherwise

## Developted for iRobotCreate3 on Raspberri Pi5 with ROS2 Jazzy on Ubuntu 24.04

The following steps can be used to setup a gazebo simulation of a TurtleBot4 with the following versions/software. Note, that the TurtleBot4 is built on top of the Create3 and so the CPSL's create3 may not come with all of the hardware available on the TurtleBot4

- ROS Version: ROS2 Jazzy
- Ubuntu Version: Ubuntu 24.04

## [Setup/Installation] with RPi5 (ROS2 Jazzy)

### 1. Install ROS2 Jazzy
1. Install ROS2 Jazzy by following the instructions here: [ROS2 Jazzy Installation Guide](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)

2. Once ROS is installed, install the create3 messages for ROS2 Jazzy using the following command:
    ```
    sudo apt install -y ros-jazzy-irobot-create-msgs
    ```

### 2. Install cpsl_ros2_create3 ros package
1. In order to read/write commands/data to the Create3, we must install a series of packages
    ```
    git clone --recurse-submodules https://github.com/cpsl-research/CPSL_ROS2_Create3
    ```

    If you forgot to clone the submodules as well, you can use the following command:
    ```
    git submodule update --init --recursive
    ```

    Once, cloned, the following commands can be used to build/install the necessary packages

    ```
    cd CPSL_ROS2_Create3
    colcon build --symlink-install
    source install/setup.bash
    rosdep install -i --from-path src --rosdistro jazzy -y
    ```

### 3. Setting ROS2 Middleware
In order to connect to the Create3 using ROS, the correct MiddleWare and discovery settings must be applied.. The 1st option should work just fine, but you may need to try the second option as well 

#### Option 1: Default
1. By default, the Create3 uses the rmw_fastrtps_cpp and uses the ROS2 Domain ID of 0 (confirm in the Create3 web interface by going to Application -> Configuration). In order to connect to the Create3 in the easiest manner, add the following commands to your .bashrc
```
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_STATIC_PEERS=192.168.186.2
```

2. Once this is completed, you should be able to follow the "Nominal Startup of RPi5 + Create3" instructions to confirm that everything is setup correctly. 

#### Option 2: fast-DDS .xml file
1. If the below option doesn't work, you should be able to follow the "Fast-DDS" instructions here [Fast-DDS instructions](https://iroboteducation.github.io/create3_docs/setup/xml-config/) to establish a connection correctly. For example, create a file called "fast_dds.xml" in your Documents folder and paste the following contents inside:
```
<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
   <participant profile_name="unicast_connection" is_default_profile="true">
       <rtps>
           <builtin>
               <metatrafficUnicastLocatorList>
                   <locator/>
               </metatrafficUnicastLocatorList>
               <initialPeersList>
                   <locator>
                       <udpv4>
                           <address>192.168.186.2</address>
                       </udpv4>
                   </locator>
               </initialPeersList>
           </builtin>
       </rtps>
   </participant>
</profiles>
```
2. Then in your .bashrc file, paste the following (instead of Option1's content):
```
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export FASTRTPS_DEFAULT_PROFILES_FILE=/home/cpsl/Documents/fast_dds.xml
```
3. Once this is completed, you should be able to follow the "Nominal Startup of RPi5 + Create3" instructions to confirm that everything is setup correctly. 

## Tutorials:

### 1. Undocking the robot:
To undock the robot, send the following action command. Here, replace /cpslCreate3 with the namespace of the robot (or omit it if the robot does not have a namespace assigned):

```
ros2 action send_goal /cpslCreate3/undock irobot_create_msgs/action/Undock "{}"
```

### 2. Docking the robot:
Once donce with the robot, send the following action command to redock the robot. Here, replace /cpslCreate3 with the namespace of the robot (or omit it if the robot does not have a namespace assigned):
```
ros2 action send_goal /cpslCreate3/dock irobot_create_msgs/action/Dock "{}"
```

### 3. Controlling the vehicle with keyboard operation
To control the vehicle with keyboard commands, run the following command. Here, replace /cpslCreate3 with the namespace of the robot (or omit it if the robot does not have a namespace assigned)
```
cd CPSL_ROS2_Create3
source install/setup.bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args --remap /cmd_vel:=/cpslCreate3/cmd_vel
```

### 4. Resetting the robot pose (say at a particular origin)
If you want to reset the pose to a specific location, you can use the following service
```
ros2 service call /cpslCreate3/reset_pose irobot_create_msgs/srv/ResetPose "pose: {position: {x: 0, y: 0, z: 0}, orientation: {x: 0, y: 0, z: 0, w: 1}}"
```