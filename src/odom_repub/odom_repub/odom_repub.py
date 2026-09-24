import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from nav_msgs.msg import Odometry

class OdomRepublisher(Node):
    def __init__(self):
        super().__init__('odom_republisher')

        # Specify the namespace
        self.namespace = self.get_namespace()
        if self.namespace == '/':
            self.namespace = ''
            self.tf_prefix = ''
            self.odom_topic = "/odom"
        else:
            self.tf_prefix = "{}/".format(self.namespace)
            self.odom_topic = "{}/odom".format(self.namespace)

        # Define a best-effort QoS profile for subscription
        qos_profile = QoSProfile(depth=10)
        qos_profile.reliability = ReliabilityPolicy.BEST_EFFORT

        # Subscribe to the /odom topic with best-effort QoS
        self.subscription = self.create_subscription(
            Odometry,
            self.odom_topic,
            self.odom_callback,
            qos_profile
        )

        # Publisher for /odom_repub topic
        self.publisher = self.create_publisher(
            Odometry,
            '{}/odom_repub'.format(self.namespace),
            1  # Reliable by default
        )

    def odom_callback(self, msg: Odometry):
        # Republish the received Odometry message with updated frame IDs
        msg.header.frame_id = "{}odom".format(self.tf_prefix)
        msg.child_frame_id = "{}base_link".format(self.tf_prefix)

        self.publisher.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = OdomRepublisher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # SIGINT from ros2 launch (or Ctrl-C) is how this node is stopped, not
        # an error worth a traceback.
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

if __name__ == '__main__':
    main()
