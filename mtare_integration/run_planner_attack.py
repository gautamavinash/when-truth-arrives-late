#!/usr/bin/env python3
"""
Planner-level delay attack on the original M-TARE system.

Per mission: launch a fresh team (clustered start, same start positions across the three conditions of an iteration),
start the cross-robot bridge on every robot (the compromised robot runs cross_robot_bridge_attack.py with SLA/BLA, the
others the stock bridge copy), explore for a fixed time budget, then collect each robot's trajectory and metrics files.

  python3 run_planner_attack.py --environments tunnel --team-sizes 4 --iterations 1 --conditions baseline sla --budget-s 240
"""
import argparse, random, subprocess, sys, time
from pathlib import Path
import run_full_sweep as F

HERE = Path(__file__).resolve().parent
LOG = "/home/docker-user/mtare/autonomous_exploration_development_environment/src/vehicle_simulator/log"
PORT, MOBILITY = 16800, "wheeled"


def start_bridges(n, condition, attacker, lam):
    for rid in range(n):
        F.docker_exec(f"robot{rid}", "pkill -f cross_robot_bridge.py", check=False)
        attack = condition if (rid == attacker and condition in ("sla", "bla")) else "none"
        script = "cross_robot_bridge_attack.py" if attack != "none" else "cross_robot_bridge_stock.py"
        subprocess.run(["docker", "cp", str(HERE / script), f"robot{rid}:/home/docker-user/cross_robot_bridge.py"], check=True)
        F.docker_exec(f"robot{rid}",
                      "source /opt/ros/noetic/setup.bash; "
                      "source /home/docker-user/mtare/autonomous_exploration_development_environment/devel/setup.bash; "
                      "source /home/docker-user/mtare/tare_system/devel/setup.bash; "
                      f"nohup python3 /home/docker-user/cross_robot_bridge.py {rid} {n} {MOBILITY} {PORT} {attack} {lam} "
                      f"> /tmp/cross_robot_bridge_{rid}.log 2>&1 < /dev/null &")


def collect(n, outdir, t_start_epoch):
    outdir.mkdir(parents=True, exist_ok=True)
    for rid in range(n):
        for kind in ("trajectory", "metrics"):
            r = subprocess.run(["docker", "exec", f"robot{rid}", "bash", "-lc",
                                f"ls -t {LOG}/{kind}_{rid}_*.txt 2>/dev/null | head -1"],
                               stdout=subprocess.PIPE, text=True)
            path = r.stdout.strip()
            if path:
                subprocess.run(["docker", "cp", f"robot{rid}:{path}", str(outdir / f"{kind}_{rid}.txt")])
        subprocess.run(["docker", "cp", f"robot{rid}:/tmp/cross_robot_bridge_{rid}.log", str(outdir / f"bridge_{rid}.log")],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        F.docker_exec(f"robot{rid}", "pkill -INT -f cross_robot_bridge.py; sleep 1", check=False)   # flush the receive log
        subprocess.run(["docker", "cp", f"robot{rid}:/tmp/bridge_rx_{rid}.csv", str(outdir / f"bridge_rx_{rid}.csv")],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--environments", nargs="+", default=["tunnel", "garage"])
    p.add_argument("--team-sizes", type=int, nargs="+", default=[4, 8])
    p.add_argument("--conditions", nargs="+", default=["baseline", "sla", "bla"])
    p.add_argument("--iterations", type=int, default=4)
    p.add_argument("--budget-s", type=int, default=360)
    p.add_argument("--lambda-s", type=float, default=2.5)
    p.add_argument("--comms-range", type=int, default=50)
    p.add_argument("--attacker", type=int, default=1)
    p.add_argument("--start-mode", default="clustered")
    p.add_argument("--network-interface", default="eno12399")
    p.add_argument("--display", default=":50")
    p.add_argument("--out-dir", default="planner_runs")
    p.add_argument("--iter-start", type=int, default=0)
    p.add_argument("--randomize-order", action="store_true", help="shuffle the condition order within each iteration (recorded in ORDER)")
    p.add_argument("--order-seed", type=int, default=12345)
    a = p.parse_args()
    out = HERE / a.out_dir
    total = len(a.environments) * len(a.team_sizes) * a.iterations * len(a.conditions)
    k = 0
    for env in a.environments:
        for n in a.team_sizes:
            for it in range(a.iter_start, a.iter_start + a.iterations):
                conds = list(a.conditions)
                if a.randomize_order:
                    random.Random(a.order_seed + 1000 * it + 17 * n + (0 if env == 'tunnel' else 7)).shuffle(conds)
                for pos, c in enumerate(conds):
                    k += 1
                    mdir = out / f"{env}_{n}_{c}_{it}"
                    if (mdir / "DONE").exists():
                        continue
                    print(f"[{k}/{total}] {env} n={n} {c} iter={it}  ({time.strftime('%H:%M:%S')})", flush=True)
                    F.teardown_team(n)
                    ok = F.launch_team(env, a.comms_range, n, a.network_interface, a.display, a.start_mode, 100 * it + n)
                    if not ok:
                        print("  launch failed, skipping", flush=True)
                        F.teardown_team(n)
                        continue
                    try:
                        t0 = time.time()
                        start_bridges(n, c, a.attacker, a.lambda_s)
                        time.sleep(a.budget_s)
                        collect(n, mdir, t0)
                        (mdir / "ORDER").write_text(f"{pos}\n")
                        (mdir / "DONE").write_text(f"{time.time() - t0:.0f}s\n")
                    finally:
                        F.teardown_team(n)
    print("PLANNERRUNDONE", flush=True)


if __name__ == "__main__":
    main()
