#!/usr/bin/env python3
"""
Monitoring receiver for M-TARE — detects SLA and BLA at runtime.

Runs alongside mtare_udp_marker_receiver.py on robot0.
Listens on a separate monitoring port (default 15001) where each robot's
attack sender also forwards a copy of every packet.

Usage (inside robot0 container):
    python3 monitoring_receiver.py <n_robots> [listen_port] [alpha] [window]

Each robot's attack sender (sla_sender.py / bla_sender.py) must be
configured to send copies to robot0:<listen_port> in addition to the
main receiver port.

To forward from the normal sender without modifying it, use the deploy
script which sets up a UDP tee via socat inside each robot container.
"""

import json
import math
import socket
import sys
import time
from collections import defaultdict, deque


# ── Detection logic (self-contained, no dependency on detection/ module) ─────

class SenderRecord:
    def __init__(self, window=10, alpha=2.0):
        self.window = window
        self.alpha = alpha
        self._history = deque(maxlen=200)
        self._anomaly_win = deque(maxlen=window)
        self._last_seq = None
        self.seq_gaps = 0

    def record(self, delay: float, seq: int) -> bool:
        self._history.append(delay)
        if self._last_seq is not None and seq > self._last_seq + 1:
            self.seq_gaps += seq - self._last_seq - 1
        self._last_seq = seq

        anomalous = self._anomalous(delay)
        self._anomaly_win.append(1 if anomalous else 0)
        return anomalous

    def _anomalous(self, d):
        if len(self._history) < 4:
            return False
        hist = list(self._history)[:-1]
        mu = sum(hist) / len(hist)
        sig = math.sqrt(sum((x - mu) ** 2 for x in hist) / len(hist)) or 0
        return sig > 0 and abs(d - mu) > self.alpha * sig

    @property
    def density(self):
        return sum(self._anomaly_win) / max(len(self._anomaly_win), 1)

    @property
    def mean_delay(self):
        return sum(self._history) / max(len(self._history), 1)

    @property
    def variance(self):
        if len(self._history) < 2:
            return 0.0
        mu = self.mean_delay
        return sum((x - mu) ** 2 for x in self._history) / len(self._history)

    @property
    def deviation(self):
        """Average absolute deviation from the mean delay (Delay Deviation metric)."""
        if not self._history:
            return 0.0
        mu = self.mean_delay
        return sum(abs(x - mu) for x in self._history) / len(self._history)


class MonitoringReceiver:
    def __init__(self, n_robots, listen_port=15001, alpha=2.0, window=10,
                 density_thresh=0.4, seq_gap_thresh=3, snapshot_path=None):
        self.n_robots = n_robots
        self.listen_port = listen_port
        self.density_thresh = density_thresh
        self.seq_gap_thresh = seq_gap_thresh
        self.snapshot_path = snapshot_path
        self._start_time = time.time()

        self._records: dict[int, SenderRecord] = defaultdict(
            lambda: SenderRecord(window=window, alpha=alpha)
        )
        self._suspicious: dict[int, bool] = {}
        self._detected_at: dict[int, float] = {}

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", listen_port))
        print(f"[monitor] listening on :{listen_port}", flush=True)

    def run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                payload = json.loads(data.decode("utf-8"))
                self._process(payload)
            except json.JSONDecodeError:
                pass
            except KeyboardInterrupt:
                break

    def _process(self, payload: dict):
        robot_id = payload.get("robot_id")
        stamp = payload.get("stamp", 0.0)
        seq = payload.get("seq", 0)
        now = time.time()
        delay = now - stamp

        rec = self._records[robot_id]
        rec.record(delay, seq)

        temporal_flag = rec.density >= self.density_thresh
        seq_flag = rec.seq_gaps >= self.seq_gap_thresh
        vote = temporal_flag + seq_flag

        was_clean = not self._suspicious.get(robot_id, False)
        self._suspicious[robot_id] = (vote >= 1)

        if vote >= 1 and was_clean:
            self._detected_at[robot_id] = now
            print(
                f"[monitor] ⚠  robot{robot_id} SUSPECTED as delay attacker "
                f"(density={rec.density:.2f}, seq_gaps={rec.seq_gaps})",
                flush=True,
            )

        if len(self._records) % 50 == 0 or robot_id in self._detected_at:
            self._print_status()

        self._write_snapshot()

    def _print_status(self):
        print("\n[monitor] ── status ──────────────────────", flush=True)
        for rid, rec in sorted(self._records.items()):
            flag = "⚠ SUSPECT" if self._suspicious.get(rid) else "ok"
            print(
                f"  robot{rid}: mean_delay={rec.mean_delay:.3f}s "
                f"deviation={rec.deviation:.4f} variance={rec.variance:.4f} "
                f"density={rec.density:.2f} seq_gaps={rec.seq_gaps}  [{flag}]",
                flush=True,
            )
        print("[monitor] ─────────────────────────────────\n", flush=True)

    def _write_snapshot(self):
        """Machine-readable per-robot summary, overwritten on every packet, so
        an orchestration script can read final detection metrics after a
        mission ends without parsing free-text log output."""
        if not self.snapshot_path:
            return
        snapshot = {
            "mission_elapsed_s": round(time.time() - self._start_time, 3),
            "robots": {
                str(rid): {
                    "average_delay": round(rec.mean_delay, 4),
                    "delay_deviation": round(rec.deviation, 4),
                    "delay_variance": round(rec.variance, 4),
                    "density": round(rec.density, 4),
                    "seq_gaps": rec.seq_gaps,
                    "suspicious": self._suspicious.get(rid, False),
                    "detection_time": self._detected_at.get(rid),
                    "detection_delay": (
                        round(self._detected_at[rid] - self._start_time, 3)
                        if rid in self._detected_at else None
                    ),
                }
                for rid, rec in self._records.items()
            },
        }
        tmp_path = self.snapshot_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(snapshot, f)
        import os
        os.replace(tmp_path, self.snapshot_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: monitoring_receiver.py <n_robots> [listen_port] [alpha] [window] [snapshot_path]")
        sys.exit(1)

    n = int(sys.argv[1])
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 15001
    alpha = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    window = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    snapshot_path = sys.argv[5] if len(sys.argv) > 5 else None

    MonitoringReceiver(n, listen_port=port, alpha=alpha, window=window,
                        snapshot_path=snapshot_path).run()
