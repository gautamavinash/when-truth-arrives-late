#!/usr/bin/env python3
"""
Live-deployment trial harness for SLA/BLA detection on a real M-TARE
multi-robot Docker deployment. Scales from a handful of robots up to large
teams (e.g. N=20) by attacking multiple robots concurrently per round.

Because the detector keeps independent, self-referential state per robot
identifier, detection of one robot does not depend on what any other robot
is doing — so it is methodologically valid to attack several robots at once
(each with its own attack type / lambda) while the rest of the team stays
benign as a live control group, and read off each robot's own detection
latency from the same shared observation window.

--batch-size 1 reproduces the original one-attacker-at-a-time methodology
exactly (used for the N=5 evaluation). --batch-size B > 1 packs up to B
concurrent attacks per round, cutting the number of rounds needed by
roughly a factor of B, at the cost of concurrent attacks sharing host
CPU/GPU/network load with each other (report this as a caveat).

Usage:
    # N=5, one-at-a-time (original methodology)
    python3 run_live_trials.py --n-robots 5 --batch-size 1

    # N=20, up to 8 concurrent attackers per round
    python3 run_live_trials.py --n-robots 20 --batch-size 8 \
        --attack-types sla bla --lambdas 1.0 1.5 2.0 --duration 35
"""

import argparse
import csv
import random
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUSPECT_RE = re.compile(r"robot(\d+) SUSPECTED as delay attacker")


def run(cmd):
    return subprocess.run(cmd, cwd=SCRIPT_DIR, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True)


def monitor_log():
    r = subprocess.run(
        ["docker", "exec", "robot0", "cat", "/tmp/monitoring_receiver.log"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    return r.stdout or ""


def reset_detector(n_robots, monitor_port):
    run(["./deploy_detection.sh", str(n_robots), str(monitor_port)])


def deploy_attack(robot_id, attack_type, robot0_ip, lam, monitor_port):
    run(["./deploy_attack.sh", str(robot_id), attack_type, robot0_ip,
         str(lam), str(monitor_port)])


def restore_benign(robot_id, robot0_ip, monitor_port):
    run(["./deploy_benign_tee.sh", str(robot_id), robot0_ip, str(monitor_port)])


def parallel(fn, items, max_workers=16):
    """Run fn(*item) for each item in items concurrently; raise the first error, if any."""
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(items)))) as ex:
        futures = [ex.submit(fn, *item) for item in items]
        for f in futures:
            f.result()


def build_work_queue(attackers, attack_types, lambdas, repeats, shuffle, seed):
    items = [
        (robot, atk, lam)
        for robot in attackers
        for atk in attack_types
        for lam in lambdas
        for _ in range(repeats)
    ]
    if shuffle:
        random.Random(seed).shuffle(items)
    return items


def pack_round(queue, batch_size):
    """Pull up to batch_size items from queue whose robot ids are all distinct."""
    batch = []
    used_robots = set()
    leftover = []
    for item in queue:
        robot = item[0]
        if len(batch) < batch_size and robot not in used_robots:
            batch.append(item)
            used_robots.add(robot)
        else:
            leftover.append(item)
    return batch, leftover


def run_round(round_idx, batch, all_attackers, robot0_ip, monitor_port, duration, n_robots):
    reset_detector(n_robots=n_robots, monitor_port=monitor_port)
    time.sleep(2)

    attacked_robots = {robot for robot, _, _ in batch}
    control_robots = set(all_attackers) - attacked_robots

    t0 = time.time()
    parallel(deploy_attack,
             [(robot, atk, robot0_ip, lam, monitor_port) for robot, atk, lam in batch])

    first_flag = {}  # robot_id -> latency
    while time.time() - t0 < duration:
        log = monitor_log()
        for m in SUSPECT_RE.finditer(log):
            rid = int(m.group(1))
            if rid not in first_flag:
                first_flag[rid] = time.time() - t0
        time.sleep(1.5)

    parallel(restore_benign,
             [(robot, robot0_ip, monitor_port) for robot in attacked_robots])
    time.sleep(2)

    false_positive_robots = sorted(r for r in first_flag if r in control_robots)

    rows = []
    for robot, atk, lam in batch:
        detected = robot in first_flag
        rows.append({
            "round": round_idx,
            "batch_size": len(batch),
            "attacker": robot,
            "attack_type": atk,
            "lambda": lam,
            "duration": duration,
            "n_controls_this_round": len(control_robots),
            "detected": detected,
            "detection_latency_s": round(first_flag[robot], 2) if detected else "",
            "false_positive_robots": ";".join(str(r) for r in false_positive_robots),
            "n_false_positives": len(false_positive_robots),
        })
    return rows


def main():
    p = argparse.ArgumentParser(description="Live M-TARE SLA/BLA detection trials (scalable)")
    p.add_argument("--robot0-ip", default="10.0.2.0")
    p.add_argument("--n-robots", type=int, default=20)
    p.add_argument("--attackers", type=int, nargs="+", default=None,
                    help="Defaults to robots 1..n_robots-1")
    p.add_argument("--attack-types", nargs="+", default=["sla", "bla"])
    p.add_argument("--lambdas", type=float, nargs="+", default=[1.0, 1.5, 2.0])
    p.add_argument("--duration", type=float, default=35.0)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=1,
                    help="Max concurrent attackers per round. 1 = original one-at-a-time methodology.")
    p.add_argument("--no-shuffle", action="store_true",
                    help="Disable trial-order shuffling (shuffled by default to avoid load-over-time confounds)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--monitor-port", type=int, default=15001)
    p.add_argument("--out", default=str(SCRIPT_DIR / "live_trial_results.csv"))
    p.add_argument("--restore-stock", action="store_true",
                    help="Restore stock mtare_position_sender.py on all robots when done")
    args = p.parse_args()

    attackers = args.attackers or list(range(1, args.n_robots))

    queue = build_work_queue(attackers, args.attack_types, args.lambdas,
                              args.repeats, not args.no_shuffle, args.seed)
    total_cells = len(queue)
    est_rounds = -(-total_cells // args.batch_size)  # ceil

    print("=" * 70)
    print(f"Live trial harness — N={args.n_robots} robots, {len(attackers)} attacker "
          f"candidates × {len(args.attack_types)} attack types × {len(args.lambdas)} "
          f"lambdas × {args.repeats} repeat(s) = {total_cells} cells")
    print(f"batch_size={args.batch_size}  ->  ~{est_rounds} rounds  "
          f"(shuffle={'off' if args.no_shuffle else 'on'})")
    print("=" * 70)

    print(f"\n[setup] Establishing benign teed baseline on all {len(attackers)} candidate robots...")
    parallel(restore_benign, [(r, args.robot0_ip, args.monitor_port) for r in attackers])
    time.sleep(3)

    results = []
    round_idx = 0
    while queue:
        round_idx += 1
        batch, queue = pack_round(queue, args.batch_size)
        attacked_desc = ", ".join(f"robot{r}/{a}/λ={l}" for r, a, l in batch)
        print(f"\n[round {round_idx}, ~{-(-len(queue)//args.batch_size) + 1} remaining] "
              f"attacking: {attacked_desc}")

        rows = run_round(round_idx, batch, attackers, args.robot0_ip,
                          args.monitor_port, args.duration, args.n_robots)
        results.extend(rows)

        for row in rows:
            status = (f"DETECTED in {row['detection_latency_s']}s"
                       if row["detected"] else "NOT DETECTED")
            print(f"  robot{row['attacker']} ({row['attack_type']}, λ={row['lambda']}): {status}")
        fps = rows[0]["false_positive_robots"] if rows else ""
        print(f"  false_positives_this_round={fps or 'none'}")

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults written to {args.out}")

    print("\n" + "=" * 70)
    print("Summary by (attack_type, lambda)")
    print("=" * 70)
    groups = {}
    for r in results:
        key = (r["attack_type"], r["lambda"])
        groups.setdefault(key, []).append(r)
    header = f"{'type':<6} {'lambda':>7} {'n':>3} {'det_rate':>9} {'mean_latency_s':>15}"
    print(header)
    print("-" * len(header))
    for (atk, lam), rows in sorted(groups.items()):
        n = len(rows)
        det = [r for r in rows if r["detected"]]
        det_rate = len(det) / n
        mean_lat = (sum(r["detection_latency_s"] for r in det) / len(det)) if det else float("nan")
        print(f"{atk:<6} {lam:>7} {n:>3} {det_rate:>9.2f} {mean_lat:>15.2f}")

    # False-positive rate per control-robot-round opportunity (round-level, dedup)
    seen_rounds = {}
    for r in results:
        seen_rounds.setdefault(r["round"], r)
    total_control_opportunities = sum(rr["n_controls_this_round"] for rr in seen_rounds.values())
    total_fp_events = sum(rr["n_false_positives"] for rr in seen_rounds.values())
    fp_rate = total_fp_events / total_control_opportunities if total_control_opportunities else float("nan")
    print(f"\nOverall false-positive rate: {total_fp_events} incidents / "
          f"{total_control_opportunities} control-robot-round opportunities = {fp_rate:.4f}")

    if args.restore_stock:
        print("\n[cleanup] Restoring stock sender on all attacker-candidate robots...")
        for r in attackers:
            run(["./restore_sender.sh", str(r), args.robot0_ip])


if __name__ == "__main__":
    main()
