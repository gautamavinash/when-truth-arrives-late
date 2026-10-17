#!/usr/bin/env python3
"""
Infrastructure fix: bidirectional cross-robot ROS topic bridge.

Root cause this fixes: each robot runs its own isolated ROS master, with no
shared graph, only a macvlan network. RobotManager::ExplorationInfoCallback
and PositionCallback (tare_planner, unmodified by this file) subscribe
to /{mobility_type}{peer_id}/exploration_info and .../position for every
OTHER robot, expecting to track peers' positions and last-known VRP plans so
UpdateCommsStatus can detect proximity and the pursuit/relay-comms mechanism
has real cached plans to route towards. Nothing has ever published those
exact topic names across container boundaries: mtare_position_sender.py and
mtare_viz_bridge_*.py only relay data out to an external visualization
receiver under a renamed topic (/mtare_viz/robotN/...).
Confirmed empirically: across 26 collected episodes (123,720
in_comms_debug samples, 5 environments, 4-18 robots, comms ranges 8-24), no
robot ever registered as in comms with any peer, and no peer's cached VRP
plan was ever non-empty -- the planner's entire cross-robot awareness
mechanism has never received real peer data in this deployment.

This script runs once per robot container -- it is shared launcher
infrastructure, not part of tare_planner's C++ source, so it doesn't touch
the frozen tare_system baseline. It subscribes to this robot's own position
and exploration_info topics, sends each message via UDP to every other
robot's fixed macvlan IP (10.0.2.<id>, same scheme as run_mtare.sh's
CONTAINER_IP), and simultaneously listens for incoming peer messages,
republishing each one locally under the *exact* topic name a peer
RobotManager subscriber expects.

Serialization reuses the same raw-ROS-serialize + JSON-header framing as
mtare_viz_bridge_receiver.py, so arbitrary message types (including the
custom tare_msgs/ExplorationInfo) need no per-field conversion code. UDP
(not TCP) is used deliberately, matching
mtare_position_sender.py's own transport choice for position: this is a
best-effort, real-time state feed, not a lossless logging channel, and a
full N-to-N TCP mesh would need every robot managing robot_num-1 outbound
connections plus accepting robot_num-1 inbound ones, with retry logic for
whichever peer hasn't started yet. Checked against real logs before choosing
this: exploration_info payloads are ~7.5KB even in the largest collected map
(campus, 18 robots), comfortably within one UDP datagram (65507-byte limit),
so no chunking is needed.
"""

import io
import json
import socket
import struct
import sys
import threading
import time as _time

import rospy
import roslib.message

MAX_UDP_PAYLOAD = 60000  # comfortably under the 65507-byte UDP datagram limit


class CrossRobotBridge:
    def __init__(self):
        args = rospy.myargv(argv=sys.argv)
        if len(args) < 5:
            print("Usage: cross_robot_bridge.py <robot_id> <robot_num> <mobility_type> <port>", flush=True)
            sys.exit(1)

        self.robot_id = int(args[1])
        self.robot_num = int(args[2])
        self.mobility_type = args[3]
        self.port = int(args[4])
        self.robot_name = f"{self.mobility_type}{self.robot_id}"

        self.peer_ids = [i for i in range(self.robot_num) if i != self.robot_id]
        self.peer_ips = {i: f"10.0.2.{i}" for i in self.peer_ids}

        rospy.init_node(f"cross_robot_bridge_{self.robot_id}", anonymous=False)

        self.send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.recv_sock.bind(("0.0.0.0", self.port))

        self.publishers = {}
        self.pub_lock = threading.Lock()
        # Measurement instrumentation (v3): each outgoing frame header carries a per-topic sequence number and the
        # wall-clock time the message was generated; every received frame is logged with its receive time.
        # The planner never reads these fields.
        self.tx_seq = {}
        self.rx_log = open(f"/tmp/bridge_rx_{self.robot_id}.csv", "w", buffering=1)
        self.rx_log.write("recv_time,sender,topic,seq,gen_time\n")
        self.rx_lock = threading.Lock()

        # (topic_suffix, type_name)
        self.topics = [
            ("position", "geometry_msgs/PointStamped"),
            ("exploration_info", "tare_msgs/ExplorationInfo"),
        ]

        print(f"[cross_robot_bridge robot{self.robot_id}] peers: {self.peer_ids}, port {self.port}", flush=True)

        for topic_suffix, type_name in self.topics:
            msg_class = roslib.message.get_message_class(type_name)
            if msg_class is None:
                print(f"[cross_robot_bridge robot{self.robot_id}] WARNING: cannot load {type_name}, "
                      f"skipping {topic_suffix}", flush=True)
                continue
            full_topic = f"/{self.robot_name}/{topic_suffix}"
            rospy.Subscriber(
                full_topic, msg_class,
                self.make_send_callback(topic_suffix, type_name),
                queue_size=10, buff_size=32 * 1024 * 1024
            )
            print(f"[cross_robot_bridge robot{self.robot_id}] subscribed: {full_topic} [{type_name}]", flush=True)

        self.recv_thread = threading.Thread(target=self.recv_loop, daemon=True)
        self.recv_thread.start()

    def make_send_callback(self, topic_suffix, type_name):
        def callback(msg):
            try:
                buff = io.BytesIO()
                msg.serialize(buff)
                payload = buff.getvalue()
                if len(payload) > MAX_UDP_PAYLOAD:
                    print(f"[cross_robot_bridge robot{self.robot_id}] WARNING: {topic_suffix} payload "
                          f"{len(payload)} bytes exceeds {MAX_UDP_PAYLOAD}, dropping this message", flush=True)
                    return
                self.tx_seq[topic_suffix] = self.tx_seq.get(topic_suffix, -1) + 1
                header = {
                    "robot_id": self.robot_id,
                    "topic_suffix": topic_suffix,
                    "type": type_name,
                    "seq": self.tx_seq[topic_suffix],
                    "gen_time": _time.time(),
                }
                header_bytes = json.dumps(header).encode("utf-8")
                frame = struct.pack("!I", len(header_bytes)) + header_bytes + payload
                for peer_id in self.peer_ids:
                    self.send_sock.sendto(frame, (self.peer_ips[peer_id], self.port))
            except Exception as e:
                print(f"[cross_robot_bridge robot{self.robot_id}] send failed on {topic_suffix}: {e}", flush=True)
        return callback

    def get_publisher(self, sender_robot_id, topic_suffix, type_name):
        out_topic = f"/{self.mobility_type}{sender_robot_id}/{topic_suffix}"
        key = (out_topic, type_name)
        with self.pub_lock:
            if key in self.publishers:
                return self.publishers[key]
            msg_class = roslib.message.get_message_class(type_name)
            if msg_class is None:
                return None
            pub = rospy.Publisher(out_topic, msg_class, queue_size=1)
            self.publishers[key] = pub
            print(f"[cross_robot_bridge robot{self.robot_id}] publishing {out_topic} [{type_name}]", flush=True)
            return pub

    def recv_loop(self):
        while not rospy.is_shutdown():
            try:
                frame, addr = self.recv_sock.recvfrom(65535)
                t_recv = _time.time()
                header_len = struct.unpack("!I", frame[:4])[0]
                header = json.loads(frame[4:4 + header_len].decode("utf-8"))
                payload = frame[4 + header_len:]

                sender_robot_id = int(header["robot_id"])
                topic_suffix = header["topic_suffix"]
                type_name = header["type"]
                if "gen_time" in header:
                    with self.rx_lock:
                        self.rx_log.write(f"{t_recv:.6f},{sender_robot_id},{topic_suffix},{header['seq']},{header['gen_time']:.6f}\n")

                pub = self.get_publisher(sender_robot_id, topic_suffix, type_name)
                if pub is None:
                    continue

                msg_class = roslib.message.get_message_class(type_name)
                msg = msg_class()
                msg.deserialize(payload)
                pub.publish(msg)
            except Exception as e:
                print(f"[cross_robot_bridge robot{self.robot_id}] recv error: {e}", flush=True)

    def spin(self):
        rospy.spin()


if __name__ == "__main__":
    CrossRobotBridge().spin()
