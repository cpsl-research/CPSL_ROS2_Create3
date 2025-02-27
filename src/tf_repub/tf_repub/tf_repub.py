import rclpy
from rclpy.node import Node
from tf2_msgs.msg import TFMessage

class TFRelay(Node):
    def __init__(self):
        super().__init__('tf_relay')
        self.subscription = self.create_subscription(TFMessage, '/tf', self.tf_callback, 10)
        self.publisher = self.create_publisher(TFMessage, '/forwarded_tf', 10)

    def tf_callback(self, msg):
        self.publisher.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = TFRelay()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
