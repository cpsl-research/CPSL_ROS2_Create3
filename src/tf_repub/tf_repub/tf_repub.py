import rclpy
from rclpy.node import Node
from tf2_msgs.msg import TFMessage
from geometry_msgs.msg import TransformStamped

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
            '/cpsl_ugv_1/tf',
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
                t.header.frame_id = "{}odom".format(self.tf_prefix)
                t.child_frame_id = "{}base_link".format(self.tf_prefix)
                filtered_transforms.append(t)

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
