import rclpy
from rclpy.node import Node
from tf2_msgs.msg import TFMessage
from geometry_msgs.msg import TransformStamped
from copy import deepcopy

class TFRelay(Node):
    def __init__(self):
        super().__init__('tf_relay')

        #specify the namespace
        self.namespace = self.get_namespace()
        if self.namespace == '/':
            self.namespace = ''
            self.tf_prefix = ''
        else:
            self.tf_prefix = "{}/".format(self.namespace)

        #setup the subscription to the tf frame
        self.subscription = self.create_subscription(
            TFMessage,
            '{}tf'.format(self.tf_prefix),
            self.tf_callback,
            1
        )
        self.publisher = self.create_publisher(
            TFMessage,
            '/tf',
            1
        )

    def tf_callback(self, msg: TFMessage):
        filtered_transforms = []
        t:TransformStamped = None
        for t in msg.transforms:
            if t.header.frame_id == 'odom' and t.child_frame_id == 'base_link':
                # Create original odom -> base_link transformation
                t_odom_base = deepcopy(t)
                t_odom_base.header.frame_id = "{}odom".format(self.tf_prefix)
                t_odom_base.child_frame_id = "{}base_link".format(self.tf_prefix)
                filtered_transforms.append(t_odom_base)

                # Create derived odom -> base_footprint transformation with Z=0.0
                t_odom_footprint = deepcopy(t_odom_base)
                t_odom_footprint.child_frame_id = "{}base_footprint".format(self.tf_prefix)
                t_odom_footprint.transform.translation.z = 0.0
                filtered_transforms.append(t_odom_footprint)

        if filtered_transforms:
            filtered_msg = TFMessage(transforms=filtered_transforms)
            self.publisher.publish(filtered_msg)

def main(args=None):
    rclpy.init(args=args)
    node = TFRelay()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
