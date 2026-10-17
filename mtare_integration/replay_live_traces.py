#!/usr/bin/env python3
"""
Offline replay of live M-TARE delay traces through two detectors.

Input: the per-mission position CSVs written by mission_logger.py (every mirrored
UDP packet with its send stamp and receive time) plus the sweep CSV that records
which robot was the attacker. Delay = recv_time - stamp (seconds; all containers
share the host clock).

Detectors (single receiver at the coordinator, as in the live deployment):
  live_monitor : the deployed monitoring_receiver logic (temporal anomaly density
                 >= 0.4 or accumulated sequence gaps >= 3; one vote suffices).
  calibrated   : the noise-calibrated population-relative detector, with the
                 parameters fixed on held-out simulation missions (k=4, delta=0,
                 min_samples=3, persist=3) -- not re-tuned on live data.

Per mission: attack missions -> attacker detected? latency (s from the attacker's
first packet to first flag), honest robots ever flagged (false positives);
baseline missions -> any robot ever flagged.

Usage: python3 replay_live_traces.py live_runs/live_*.csv > live_replay.txt
"""
import csv
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from monitoring_receiver import SenderRecord  # noqa: E402
from detection.calibrated import CalibratedDetector  # noqa: E402


def load_trace(path):
    rows = []
    for r in csv.DictReader(open(path)):
        if not r["stamp"] or not r["recv_time"] or r["robot_id"] in ("", None):
            continue
        rows.append((float(r["recv_time"]), int(float(r["robot_id"])),
                     int(float(r["seq"] or 0)), float(r["stamp"])))
    rows.sort()
    return rows


def replay_live_monitor(trace):
    recs = defaultdict(lambda: SenderRecord(window=10, alpha=2.0))
    first_flag = {}
    for recv, rid, seq, stamp in trace:
        rec = recs[rid]
        rec.record(recv - stamp, seq)
        if (rec.density >= 0.4 or rec.seq_gaps >= 3) and rid not in first_flag:
            first_flag[rid] = recv
    return first_flag


def replay_calibrated(trace):
    det = CalibratedDetector(receiver_id=0, window=10, k=4.0, delta=0.0,
                             persist=3, min_samples=3)
    first_flag = {}
    for recv, rid, seq, stamp in trace:
        det.observe(rid, seq, stamp, recv)
        if det._suspicious.get(rid) and rid not in first_flag:
            first_flag[rid] = recv
    return first_flag


def main():
    sweeps = [Path(p) for p in sys.argv[1:]]
    results = defaultdict(list)  # (env,N,detector) -> list of per-mission dicts
    for sp in sweeps:
        for row in csv.DictReader(open(sp)):
            env, n, cond, it = row["environment"], int(row["team_size"]), row["condition"], row["iteration"]
            tp = HERE / "sweep_data" / f"{env}_{n}_{cond}_{it}.csv"
            if not tp.exists():
                continue
            trace = load_trace(tp)
            if not trace:
                continue
            att = None if cond == "baseline" else int(float(row["attacker_robot"]))
            t_first = {}
            for recv, rid, _s, _st in trace:
                t_first.setdefault(rid, recv)
            for name, fn in (("live_monitor", replay_live_monitor), ("calibrated", replay_calibrated)):
                flags = fn(trace)
                fp = [r for r in flags if r != att]
                rec = {"cond": cond, "n_msgs": len(trace), "fp": len(fp), "n_honest": len(t_first) - (1 if att in t_first else 0)}
                if att is not None:
                    rec["detected"] = att in flags
                    rec["lat"] = (flags[att] - t_first[att]) if att in flags and att in t_first else None
                results[(env, n, name)].append(rec)

    print(f"{'env':8}{'N':>3} {'detector':13}{'attacks':>8}{'detected':>9}{'lat_mean_s':>11}{'lat_max_s':>10}"
          f"{'base_missions':>14}{'base_FP_missions':>17}{'atk_FP_missions':>16}{'honest_flag_rate':>17}")
    for (env, n, name), recs in sorted(results.items()):
        atk = [r for r in recs if r["cond"] != "baseline"]
        base = [r for r in recs if r["cond"] == "baseline"]
        det = [r for r in atk if r["detected"]]
        lats = [r["lat"] for r in det if r["lat"] is not None]
        honest_total = sum(r["n_honest"] for r in recs)
        honest_flagged = sum(r["fp"] for r in recs)
        print(f"{env:8}{n:>3} {name:13}{len(atk):>8}{len(det):>9}"
              f"{(st.mean(lats) if lats else float('nan')):>11.1f}{(max(lats) if lats else float('nan')):>10.1f}"
              f"{len(base):>14}{sum(r['fp'] > 0 for r in base):>17}{sum(r['fp'] > 0 for r in atk):>16}"
              f"{(honest_flagged / honest_total if honest_total else float('nan')):>17.3f}")
    # by attack type
    print("\nBy attack type (all environments / team sizes pooled):")
    for name in ("live_monitor", "calibrated"):
        for cond in ("sla", "bla"):
            rs = [r for (e, n, nm), recs in results.items() if nm == name for r in recs if r["cond"] == cond]
            if not rs:
                continue
            det = [r for r in rs if r["detected"]]
            lats = [r["lat"] for r in det if r["lat"] is not None]
            print(f"  {name:13} {cond:5} detected {len(det)}/{len(rs)}  mean latency {st.mean(lats) if lats else float('nan'):.1f}s")


if __name__ == "__main__":
    main()
