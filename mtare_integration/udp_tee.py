#!/usr/bin/env python3
"""
UDP tee — duplicates every datagram received on a local port to N destinations.

Used to mirror attack-sender traffic to both the real M-TARE receiver and the
monitoring_receiver.py detector, without modifying the sender scripts.

Usage:
    python3 udp_tee.py <listen_port> <dest_ip:dest_port> [<dest_ip:dest_port> ...]
"""

import socket
import sys


def main():
    if len(sys.argv) < 3:
        print("Usage: udp_tee.py <listen_port> <dest_ip:dest_port> [<dest_ip:dest_port> ...]")
        sys.exit(1)

    listen_port = int(sys.argv[1])
    dests = []
    for arg in sys.argv[2:]:
        ip, port = arg.rsplit(":", 1)
        dests.append((ip, int(port)))

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(("0.0.0.0", listen_port))

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"[udp_tee] listening on :{listen_port} -> {dests}", flush=True)

    count = 0
    while True:
        data, _addr = recv_sock.recvfrom(65535)
        for dest in dests:
            send_sock.sendto(data, dest)
        count += 1
        if count % 50 == 0:
            print(f"[udp_tee] relayed {count} packets", flush=True)


if __name__ == "__main__":
    main()
