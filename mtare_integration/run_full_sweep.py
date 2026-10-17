#!/usr/bin/env python3
"""
Full live-deployment sweep across environments x team sizes x conditions x
iterations, computing both the attack paper's coverage-side metrics and the
detection paper's timing-side metrics for every mission, and writing the
result to an Excel workbook.

For each (environment, team_size):
  1. Launch that many robots headlessly (launch_headless.sh).
  2. For each condition (baseline / sla / bla) x iteration:
       a. Reset the detector, start a fresh position logger.
       b. Deploy sender behavior: all-benign for baseline, one randomly
          chosen non-coordinator robot attacking for sla/bla.
       c. Run for a fixed wall-clock duration.
       d. Pull the position log + detection snapshot off robot0.
       e. Compute coverage metrics against the environment's saved
          reference (build_references.py must have been run first).
       f. Compute detection metrics from the snapshot.
       g. Restore all robots to benign and record one result row.
  3. Tear down the team before moving to the next team size.

Requires a reference JSON per environment (see build_references_from_csv.py
or an equivalent build-reference run) at
    <mtare_integration>/reference_<environment>.json

Usage:
    python3 run_full_sweep.py \\
        --environments tunnel garage campus \\
        --team-sizes 4 8 12 16 \\
        --conditions baseline sla bla \\
        --iterations 10 \\
        --duration-min 30 \\
        --lambda-s 1.5 \\
        --network-interface eno12399 \\
        --display :50 \\
        --excel-out sweep_results.xlsx
"""

import argparse
import csv
import json
import random
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def run(cmd, timeout=120):
    return subprocess.run(cmd, cwd=SCRIPT_DIR, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=timeout)


def docker_exec(container, cmd, check=True):
    return subprocess.run(["docker", "exec", container, "bash", "-lc", cmd],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, check=check)


def kill_pattern(container, pattern, wait_s=10):
    """Kill all processes matching pattern and BLOCK until confirmed dead.
    Prior version fired-and-forgot a plain pkill with only a fixed sleep,
    which let slow-to-die processes (esp. attack senders with internal
    sleep loops) survive into the next mission and keep a stale socket
    bound alongside the new one -- both listening with SO_REUSEADDR,
    silently splitting/starving real traffic between them. This is what
    caused coverage to collapse to ~0 from iteration 2 onward in the first
    sweep attempt: orphaned processes accumulated mission after mission."""
    docker_exec(container, f"pkill -f '{pattern}'", check=False)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        r = docker_exec(container, f"pgrep -f '{pattern}'", check=False)
        if r.returncode != 0:
            return True
        time.sleep(0.5)
    # Escalate to SIGKILL if it's still alive after the grace period.
    docker_exec(container, f"pkill -9 -f '{pattern}'", check=False)
    time.sleep(1)
    r = docker_exec(container, f"pgrep -f '{pattern}'", check=False)
    return r.returncode != 0


SENDER_PATTERNS = ["mtare_position_sender.py", "udp_tee.py", "benign_sender.py",
                    "sla_sender.py", "bla_sender.py"]


def kill_all_senders(container):
    for pattern in SENDER_PATTERNS:
        ok = kill_pattern(container, pattern)
        if not ok:
            print(f"WARNING: {container} still has a process matching "
                  f"'{pattern}' after kill+timeout", file=sys.stderr)


def start_positions(environment, team_size, comms_range, mode, seed):
    gen = Path.home() / "mtare_project" / "scripts" / "generate_start_positions.py"
    out = subprocess.run(["python3", str(gen), environment, str(team_size), str(comms_range), mode, str(seed)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True).stdout
    pos = [ln.split() for ln in out.strip().splitlines()]
    assert len(pos) == team_size, (environment, team_size, out)
    return pos


def launch_team(environment, comms_range, team_size, iface, display, start_mode="random", start_seed=0):
    pos = start_positions(environment, team_size, comms_range, start_mode, start_seed)
    print(f"  start positions ({start_mode}, seed {start_seed}): {pos}", flush=True)
    for rid in range(team_size):
        run(["./launch_headless.sh", environment, str(comms_range),
             str(team_size), str(rid), iface, display] + pos[rid], timeout=60)
        time.sleep(4)

    deadline = time.time() + 180
    while time.time() < deadline:
        up = 0
        for rid in range(team_size):
            r = docker_exec(f"robot{rid}", "pgrep -f tare_planner_node", check=False)
            if r.returncode == 0:
                up += 1
        if up == team_size:
            return True
        time.sleep(3)
    return False


def teardown_team(team_size):
    for rid in range(team_size):
        kill_all_senders(f"robot{rid}")
    kill_pattern("robot0", "mission_logger.py")
    kill_pattern("robot0", "monitoring_receiver.py")
    for rid in range(team_size):
        subprocess.run(["tmux", "kill-session", "-t", f"launch_robot{rid}"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", f"robot{rid}"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def deploy_mission_senders(team_size, attacker_ids, attack_type, lam,
                            robot0_ip, monitor_port, logger_port, noise=None):
    """Assigns every robot its role for this mission in a single pass (one
    kill+start per robot, never a kill-start-then-kill-start-again on the
    same robot), and verifies each kill completed before starting the
    replacement -- see kill_pattern(). robot0 uses a distinct local tee
    port (25000) to avoid the self-loop bug found during calibration
    (its 'real receiver' mirror target is itself)."""
    for rid in range(team_size):
        kill_all_senders(f"robot{rid}")

    for rid in range(team_size):
        local_port = 25000 if rid == 0 else 15000
        # noise = (delay_ms, jitter_ms, loss_pct): non-coordinator robots forward through the noisy tee (app-layer emulation)
        noisy = noise is not None and rid != 0
        subprocess.run(["docker", "cp", str(SCRIPT_DIR / ("udp_tee_noisy.py" if noisy else "udp_tee.py")),
                         f"robot{rid}:/home/docker-user/udp_tee.py"])
        env = f"NOISE_DELAY_MS={noise[0]} NOISE_JITTER_MS={noise[1]} NOISE_LOSS_PCT={noise[2]} NOISE_SEED={rid + 1} " if noisy else ""
        docker_exec(f"robot{rid}",
                     f"{env}nohup python3 /home/docker-user/udp_tee.py {local_port} "
                     f"{robot0_ip}:15000 {robot0_ip}:{monitor_port} {robot0_ip}:{logger_port} "
                     f"> /tmp/udp_tee_{rid}.log 2>&1 < /dev/null &")
        time.sleep(0.3)

        ros_env = ("source /opt/ros/noetic/setup.bash; "
                   "source /home/docker-user/mtare/autonomous_exploration_development_environment/devel/setup.bash; "
                   "source /home/docker-user/mtare/tare_system/devel/setup.bash; ")

        if rid in attacker_ids:
            subprocess.run(["docker", "cp", str(SCRIPT_DIR / f"{attack_type}_sender.py"),
                             f"robot{rid}:/home/docker-user/{attack_type}_sender.py"])
            docker_exec(f"robot{rid}", ros_env +
                        f"nohup python3 /home/docker-user/{attack_type}_sender.py "
                        f"{rid} 127.0.0.1 {local_port} {lam} "
                        f"> /tmp/{attack_type}_sender_{rid}.log 2>&1 < /dev/null &")
        else:
            subprocess.run(["docker", "cp", str(SCRIPT_DIR / "benign_sender.py"),
                             f"robot{rid}:/home/docker-user/benign_sender.py"])
            docker_exec(f"robot{rid}", ros_env +
                        f"nohup python3 /home/docker-user/benign_sender.py "
                        f"{rid} 127.0.0.1 {local_port} "
                        f"> /tmp/benign_sender_{rid}.log 2>&1 < /dev/null &")


def run_mission(environment, team_size, condition, iteration, args, tag="", noise=None):
    robot0_ip = "10.0.2.0"
    monitor_port = 15001
    logger_port = 15002
    mission_id = f"{environment}_{team_size}_{condition}_{iteration}" + (f"_{tag}" if tag else "")
    snapshot_path = f"/tmp/detection_snapshot_{mission_id}.json"
    position_csv = f"/tmp/positions_{mission_id}.csv"

    # Fresh detector + logger for this mission -- verified kill of any prior
    # instance first, since an unverified pkill is exactly what caused the
    # cross-mission process leak this function now guards against below.
    kill_pattern("robot0", "monitoring_receiver.py")
    kill_pattern("robot0", "mission_logger.py")
    docker_exec("robot0", f"rm -f {snapshot_path} {position_csv}", check=False)
    run(["./deploy_detection.sh", str(team_size), str(monitor_port), "2.0", "10", snapshot_path])
    subprocess.run(["docker", "cp", str(SCRIPT_DIR / "mission_logger.py"), "robot0:/home/docker-user/mission_logger.py"])
    docker_exec("robot0", f"nohup python3 /home/docker-user/mission_logger.py {logger_port} {position_csv} "
                            f"> /tmp/mission_logger_{mission_id}.log 2>&1 < /dev/null &")
    time.sleep(2)

    if condition == "baseline":
        attacker_ids = set()
    else:   # attackers scale with the team as in the simulation: max(1, ceil(10% of N)), never the coordinator
        k = max(1, -(-team_size // 10))
        attacker_ids = set(random.sample(range(1, team_size), min(k, team_size - 1)))
    attacker_id = min(attacker_ids) if attacker_ids else None
    deploy_mission_senders(team_size, attacker_ids, condition, args.lambda_s,
                            robot0_ip, monitor_port, logger_port, noise)

    time.sleep(args.duration_min * 60)

    # Kill every sender/tee AND the logger, verifying they're actually dead,
    # BEFORE pulling data off -- guarantees no writer is still touching the
    # position CSV mid-copy and that nothing is left running to contend with
    # the next mission's freshly-started processes on the same ports.
    for rid in range(team_size):
        kill_all_senders(f"robot{rid}")
    kill_pattern("robot0", "mission_logger.py")

    # Pull results off robot0
    local_csv = str(SCRIPT_DIR / "sweep_data" / f"{mission_id}.csv")
    local_snapshot = str(SCRIPT_DIR / "sweep_data" / f"{mission_id}_detection.json")
    Path(local_csv).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["docker", "cp", f"robot0:{position_csv}", local_csv], check=False)
    subprocess.run(["docker", "cp", f"robot0:{snapshot_path}", local_snapshot], check=False)

    # Coverage-side metrics
    ref_path = SCRIPT_DIR / f"reference_{environment}.json"
    row = {
        "environment": environment, "team_size": team_size, "condition": condition,
        "iteration": iteration, "attacker_robot": (str(sorted(attacker_ids)) if attacker_ids else None), "n_attackers": len(attacker_ids),
        "lambda_s": args.lambda_s, "start_mode": args.start_mode, "netem": tag,
        "duration_min": args.duration_min,
    }
    try:
        cov_cmd = ["python3", "coverage_metrics.py", "analyze", local_csv,
                   "--reference", str(ref_path), "--json"]
        if attacker_id is not None:
            cov_cmd += ["--attacker-robot-id", str(attacker_id)]
        cov = subprocess.run(
            cov_cmd, cwd=SCRIPT_DIR, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, check=True
        )
        cov_metrics = json.loads(cov.stdout.strip().splitlines()[-1])
        row.update({
            "coverage_efficiency": cov_metrics["coverage_efficiency"],
            "uncovered_cells": cov_metrics["uncovered_cells"],
            "collision": cov_metrics["collision"],
            "redundant_coverage": cov_metrics["redundant_coverage"],
            "malicious_coverage_efficiency": cov_metrics.get("malicious_coverage_efficiency"),
            "legitimate_coverage_efficiency": cov_metrics.get("legitimate_coverage_efficiency"),
        })
    except Exception as e:
        row.update({"coverage_efficiency": None, "uncovered_cells": None,
                     "collision": None, "redundant_coverage": None,
                     "malicious_coverage_efficiency": None,
                     "legitimate_coverage_efficiency": None,
                     "coverage_error": str(e)})

    # Detection-side metrics (only meaningful when there's an attacker)
    if attacker_id is not None and Path(local_snapshot).exists():
        try:
            with open(local_snapshot) as f:
                snap = json.load(f)
            rstats = snap.get("robots", {}).get(str(attacker_id), {})
            row.update({
                "average_delay": rstats.get("average_delay"),
                "delay_deviation": rstats.get("delay_deviation"),
                "delay_variance": rstats.get("delay_variance"),
                "detection_time": rstats.get("detection_time"),
                "detection_delay": rstats.get("detection_delay"),
                "detected": rstats.get("suspicious", False),
            })
        except Exception as e:
            row["detection_error"] = str(e)
    else:
        row.update({"average_delay": None, "delay_deviation": None, "delay_variance": None,
                     "detection_time": None, "detection_delay": None, "detected": None})

    return row


def load_completed(csv_path):
    """Returns (rows_so_far, set of (environment, team_size, condition, iteration)
    already recorded), so a restarted run can resume instead of redoing work."""
    if not Path(csv_path).exists():
        return [], set()
    rows = []
    done_keys = set()
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            done_keys.add((row["environment"], row["team_size"],
                            row["condition"], row["iteration"]))
    return rows, done_keys


def append_row_csv(row, csv_path):
    is_new = not Path(csv_path).exists()
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if is_new:
            w.writeheader()
        w.writerow(row)
        f.flush()


def write_excel(rows, out_path):
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl not installed; writing CSV fallback instead.", file=sys.stderr)
        csv_path = out_path.replace(".xlsx", ".csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {csv_path}")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "results"
    fields = list(rows[0].keys())
    ws.append(fields)
    for row in rows:
        ws.append([row.get(k) for k in fields])
    for i, _ in enumerate(fields, start=1):
        ws.column_dimensions[get_column_letter(i)].width = 16
    wb.save(out_path)
    print(f"Wrote {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--environments", nargs="+", default=["tunnel", "garage", "campus"])
    p.add_argument("--team-sizes", type=int, nargs="+", default=[4, 8, 12, 16])
    p.add_argument("--conditions", nargs="+", default=["baseline", "sla", "bla"])
    p.add_argument("--iterations", type=int, default=10)
    p.add_argument("--duration-min", type=float, default=30.0)
    p.add_argument("--lambda-s", type=float, default=1.5)
    p.add_argument("--comms-range", type=int, default=30)
    p.add_argument("--network-interface", default="eno12399")
    p.add_argument("--display", default=":50")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--start-mode", default="random", choices=["clustered", "random", "dispersed"])
    p.add_argument("--excel-out", default=str(SCRIPT_DIR / "sweep_results.xlsx"))
    p.add_argument("--incremental-csv", default=str(SCRIPT_DIR / "sweep_results_incremental.csv"),
                    help="Appended to after every mission; also used to resume an interrupted run")
    p.add_argument("--excel-refresh-every", type=int, default=1,
                    help="Regenerate the Excel file every N completed missions (not just at the end)")
    args = p.parse_args()

    random.seed(args.seed)
    all_rows, done_keys = load_completed(args.incremental_csv)
    if done_keys:
        print(f"Resuming: {len(done_keys)} missions already recorded in "
              f"{args.incremental_csv}, will skip those.", flush=True)

    total_missions = (len(args.environments) * len(args.team_sizes)
                       * len(args.conditions) * args.iterations)
    done = len(done_keys)

    for environment in args.environments:
        ref_path = SCRIPT_DIR / f"reference_{environment}.json"
        if not ref_path.exists():
            print(f"WARNING: no reference for {environment} at {ref_path}, "
                  f"coverage metrics will fail for this environment.", file=sys.stderr)

        for team_size in args.team_sizes:
            # Skip launching this team entirely if every mission for it is
            # already recorded (fully resuming a completed team/env combo).
            remaining = [
                (condition, iteration)
                for condition in args.conditions
                for iteration in range(args.iterations)
                if (environment, str(team_size), condition, str(iteration)) not in done_keys
            ]
            if not remaining:
                print(f"\n=== Skipping {environment} team={team_size} "
                      f"(all missions already recorded) ===", flush=True)
                continue

            print(f"\n=== Launching {team_size} robots in {environment} ===", flush=True)
            ok = launch_team(environment, args.comms_range, team_size,
                              args.network_interface, args.display, args.start_mode, args.seed)
            if not ok:
                print(f"FAILED to bring up {team_size} robots in {environment}, skipping.", file=sys.stderr)
                teardown_team(team_size)
                continue

            for condition, iteration in remaining:
                done += 1
                print(f"[{done}/{total_missions}] {environment} team={team_size} "
                      f"{condition} iter={iteration}", flush=True)
                row = run_mission(environment, team_size, condition, iteration, args)
                all_rows.append(row)
                append_row_csv(row, args.incremental_csv)
                print(f"  -> {row}", flush=True)

                if done % args.excel_refresh_every == 0:
                    write_excel(all_rows, args.excel_out)

            teardown_team(team_size)

    if all_rows:
        write_excel(all_rows, args.excel_out)
        print(f"\nSweep complete: {len(all_rows)} missions recorded.")
    else:
        print("No results collected.", file=sys.stderr)


if __name__ == "__main__":
    main()
