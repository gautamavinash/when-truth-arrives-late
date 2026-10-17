#!/usr/bin/env python3
"""
Mission logger for M-TARE live experiments — dumps every mirrored position
record to CSV for offline computation of coverage-side metrics (Coverage
Efficiency, Uncovered Cells, Collision, Redundant Coverage), which have no
equivalent published anywhere in the M-TARE ROS stack.

Deploy alongside monitoring_receiver.py: both listen on ports mirrored by
each robot's udp_tee.py, so no additional tee destination is needed as long
as this is bound to the same monitor port as the detector on a distinct
process, or a third mirrored port if run concurrently with detection.

Usage (inside robot0 container):
    python3 mission_logger.py <listen_port> <out_csv>
"""

import csv
import json
import socket
import sys
import time


def main():
    if len(sys.argv) < 3:
        print("Usage: mission_logger.py <listen_port> <out_csv>")
        sys.exit(1)

    listen_port = int(sys.argv[1])
    out_csv = sys.argv[2]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", listen_port))

    fields = ["recv_time", "robot_id", "x", "y", "z", "stamp", "seq",
              "relay_comms", "attack"]

    print(f"[mission_logger] listening on :{listen_port} -> {out_csv}", flush=True)

    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        f.flush()

        count = 0
        while True:
            data, _addr = sock.recvfrom(65535)
            try:
                payload = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            row = {
                "recv_time":   time.time(),
                "robot_id":    payload.get("robot_id"),
                "x":           payload.get("x"),
                "y":           payload.get("y"),
                "z":           payload.get("z"),
                "stamp":       payload.get("stamp"),
                "seq":         payload.get("seq"),
                "relay_comms": payload.get("relay_comms"),
                "attack":      payload.get("attack", "none"),
            }
            writer.writerow(row)
            count += 1
            if count % 200 == 0:
                f.flush()
                print(f"[mission_logger] logged {count} records", flush=True)


if __name__ == "__main__":
    main()
