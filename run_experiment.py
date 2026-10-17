#!/usr/bin/env python3
"""
Run SLA / BLA simulation experiments and print results.

Replicates the paper's setup:
  - 16x16 grid, 18 obstacles
  - Team sizes 5 to 40 (step 5), 25 iterations each
  - Three conditions: baseline, SLA, BLA
  - Metrics: coverage, uncovered cells, collisions, redundant coverage,
             malicious robot coverage vs legitimate coverage,
             detection time

Usage:
    python3 run_experiment.py                          # full paper replication
    python3 run_experiment.py --robots 10 --iters 5   # quick test
    python3 run_experiment.py --robots 5 --attack sla --lambda 3
"""

import argparse
import math
import statistics
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

EXCEL_METRICS = [
    "completion_step", "coverage_efficiency", "uncovered_cells",
    "total_collisions", "total_redundant", "n_attackers",
    "malicious_coverage", "malicious_coverage_total", "legitimate_avg_coverage",
]

from simulation.grid_env import GridEnv
from simulation.simulator import Simulator
from simulation.maps import get_map_obstacles
from attacks.sla import SequentialLagAttacker
from attacks.bla import BoundedLagAttacker


def attacker_count_for(n_robots: int) -> int:
    """Scale attacker count with team size: few attackers for small teams,
    up to (and capped at) 10% of the team for large teams."""
    return max(1, math.ceil(0.1 * n_robots))


def run_one(n_robots, attack_type, lambda_steps, seed, enable_detection=True, map_name=None):
    obstacles = get_map_obstacles(map_name) if map_name else None
    env = GridEnv(size=16, obstacles=obstacles)

    adversary_ids = []
    attack_proxies = {}
    if attack_type != "baseline":
        proxy_cls = SequentialLagAttacker if attack_type == "sla" else BoundedLagAttacker
        k = attacker_count_for(n_robots)
        adversary_ids = list(range(k))
        attack_proxies = {aid: proxy_cls(lambda_steps=lambda_steps) for aid in adversary_ids}

    sim = Simulator(
        env=env,
        n_robots=n_robots,
        adversary_ids=adversary_ids,
        attack_proxies=attack_proxies,
        enable_detection=enable_detection,
        seed=seed,
        max_steps=2000,
    )
    sim.run()
    return sim.summary()


def aggregate(results: list) -> dict:
    keys = results[0].keys()
    out = {}
    for k in keys:
        vals = [r[k] for r in results if r[k] is not None and isinstance(r[k], (int, float))]
        if vals:
            out[k] = {
                "mean": statistics.mean(vals),
                "std":  statistics.stdev(vals) if len(vals) > 1 else 0.0,
            }
        else:
            out[k] = {"mean": None, "std": None}
    # detection accuracy: fraction of runs where every attacker was flagged and
    # no legitimate robot was falsely flagged
    det_vals = [r.get("detection_all_correct") for r in results if r.get("detection_all_correct") is not None]
    if det_vals:
        out["detection_accuracy"] = sum(det_vals) / len(det_vals)
    return out


def print_row(label, agg, keys):
    parts = [f"{label:<20}"]
    for k in keys:
        v = agg.get(k, {}).get("mean")
        parts.append(f"{v:>10.2f}" if v is not None else f"{'N/A':>10}")
    print("  ".join(parts))


def write_excel(summary_rows, raw_rows, out_path):
    import openpyxl
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "summary"
    summary_fields = list(summary_rows[0].keys())
    ws.append(summary_fields)
    for row in summary_rows:
        ws.append([row.get(k) for k in summary_fields])
    for i, _ in enumerate(summary_fields, start=1):
        ws.column_dimensions[get_column_letter(i)].width = 16

    ws2 = wb.create_sheet("raw")
    raw_fields = list(raw_rows[0].keys())
    ws2.append(raw_fields)
    for row in raw_rows:
        ws2.append([row.get(k) for k in raw_fields])
    for i, _ in enumerate(raw_fields, start=1):
        ws2.column_dimensions[get_column_letter(i)].width = 14

    wb.save(out_path)
    print(f"\nWrote {out_path}  ({len(summary_rows)} summary rows, {len(raw_rows)} raw rows)")


def main():
    parser = argparse.ArgumentParser(description="SLA/BLA simulation experiment")
    parser.add_argument("--robots",   type=int,   default=None,
                        help="Fixed robot count (overrides team size sweep)")
    parser.add_argument("--team-sizes", type=int, nargs="+", default=None,
                        help="Custom team-size sweep, e.g. --team-sizes 10 15 20 (overrides default 5-40 step 5)")
    parser.add_argument("--iters",    type=int,   default=25)
    parser.add_argument("--attack",   choices=["baseline", "sla", "bla", "all"],
                        default="all")
    parser.add_argument("--lambda",   dest="lam", type=int, default=3,
                        help="Delay window (simulation steps)")
    parser.add_argument("--maps", nargs="+", default=[None],
                        choices=["tunnel", "indoor", "garage", "campus", "forest"],
                        help="Named obstacle layouts to sweep (default: paper's original 18-obstacle layout)")
    parser.add_argument("--no-detection", action="store_true")
    parser.add_argument("--excel-out", default=None,
                        help="If set, write all results (summary + raw per-iteration) to this .xlsx file")
    args = parser.parse_args()

    if args.robots:
        team_sizes = [args.robots]
    elif args.team_sizes:
        team_sizes = args.team_sizes
    else:
        team_sizes = list(range(5, 45, 5))
    attacks = ["baseline", "sla", "bla"] if args.attack == "all" else [args.attack]
    maps = args.maps

    header_keys = [
        "completion_step", "coverage_efficiency", "uncovered_cells",
        "total_collisions", "total_redundant", "n_attackers",
        "malicious_coverage", "malicious_coverage_total", "legitimate_avg_coverage",
        "detection_recall", "detection_precision",
    ]

    print("\n" + "=" * 80)
    print("M-TARE Security Simulation  —  SLA / BLA Attack Evaluation")
    print("=" * 80)
    print(f"Grid: 16×16  |  Maps: {', '.join(m or 'default' for m in maps)}  |  "
          f"Iterations: {args.iters}  |  λ={args.lam}")
    print("=" * 80)

    summary_rows = []
    raw_rows = []

    for map_name in maps:
        print(f"\n{'#' * 80}")
        print(f"# Map: {map_name or 'default'}")
        print(f"{'#' * 80}")

        for n in team_sizes:
            print(f"\n── Team size: {n} robots ──")

            # Header
            col = f"{'Condition':<20}  " + "  ".join(f"{k:>10}" for k in header_keys)
            print(col)
            print("-" * len(col))

            all_aggs = {}
            for atk in attacks:
                results = []
                for i in range(args.iters):
                    seed = i * 100 + n
                    r = run_one(
                        n_robots=n,
                        attack_type=atk,
                        lambda_steps=args.lam,
                        seed=seed,
                        enable_detection=not args.no_detection,
                        map_name=map_name,
                    )
                    results.append(r)
                    raw_row = {
                        "map": map_name or "default", "team_size": n,
                        "condition": atk, "iteration": i, "seed": seed,
                    }
                    raw_row.update(r)
                    raw_rows.append(raw_row)
                    sys.stdout.write(f"\r  {atk:8} iter {i+1}/{args.iters}   ")
                    sys.stdout.flush()
                print()
                agg = aggregate(results)
                all_aggs[atk] = agg
                print_row(atk, agg, header_keys)

                summary_row = {
                    "map": map_name or "default", "team_size": n,
                    "condition": atk, "n_iterations": args.iters,
                }
                for k in header_keys:
                    summary_row[f"{k}_mean"] = agg.get(k, {}).get("mean")
                    summary_row[f"{k}_std"] = agg.get(k, {}).get("std")
                summary_row["detection_accuracy"] = agg.get("detection_accuracy")
                summary_rows.append(summary_row)

            # Detection accuracy
            if not args.no_detection:
                for atk in ["sla", "bla"]:
                    if atk in all_aggs:
                        acc = all_aggs[atk].get("detection_accuracy")
                        if acc is not None:
                            print(f"  Detection accuracy ({atk}): {acc*100:.1f}%")

    print("\n" + "=" * 80)
    print("Experiment complete.")

    if args.excel_out:
        write_excel(summary_rows, raw_rows, args.excel_out)


if __name__ == "__main__":
    main()
