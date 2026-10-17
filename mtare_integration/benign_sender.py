#!/usr/bin/env python3
"""
Benign position sender for M-TARE — drop-in replacement for
mtare_position_sender.py that adds a monotonic seq number and a wall-clock
stamp (matching bla_sender.py / sla_sender.py), so legitimate robots can be
teed to the monitoring_receiver.py detector as a false-positive baseline.

Forwards every packet immediately (no attack behavior).

Usage (inside robot container):
    python3 benign_sender.py <robot_id> <target_ip> <target_port>
"""

import json
import socket
import sys
import time

try:
    import rospy
    from geometry_msgs.msg import PointStamped
    from std_msgs.msg import Bool
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    print("[benign_sender] WARNING: rospy not found. Running in stub mode.", flush=True)


class BenignSender:
    def __init__(self):
        args = rospy.myargv(argv=sys.argv) if ROS_AVAILABLE else sys.argv
        if len(args) < 4:
            print("Usage: benign_sender.py <robot_id> <target_ip> <target_port>")
            sys.exit(1)

        self.robot_id = int(args[1])
        self.target_ip = args[2]
        self.target_port = int(args[3])

        self.relay_comms = False
        self.count_received = 0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        print(f"[benign_sender robot{self.robot_id}] started", flush=True)
        print(f"[benign_sender robot{self.robot_id}] target={self.target_ip}:{self.target_port}", flush=True)

        if ROS_AVAILABLE:
            rospy.init_node(f"benign_position_sender_{self.robot_id}", anonymous=False)
            rospy.Subscriber(
                f"/wheeled{self.robot_id}/position",
                PointStamped,
                self.position_callback,
                queue_size=1,
            )
            rospy.Subscriber(
                "/sensor_coverage_planner/relay_comms",
                Bool,
                self.relay_comms_callback,
                queue_size=1,
            )

    def relay_comms_callback(self, msg):
        self.relay_comms = msg.data

    def position_callback(self, msg):
        self.count_received += 1
        payload = {
            "robot_id":    self.robot_id,
            "x":           msg.point.x,
            "y":           msg.point.y,
            "z":           msg.point.z,
            "relay_comms": self.relay_comms,
            "stamp":       time.time(),
            "seq":         self.count_received,
            "attack":      "none",
        }
        data = json.dumps(payload).encode("utf-8")
        self.sock.sendto(data, (self.target_ip, self.target_port))

    def spin(self):
        if ROS_AVAILABLE:
            rospy.spin()
        else:
            while True:
                time.sleep(1)


if __name__ == "__main__":
    BenignSender().spin()
