#!/usr/bin/env python3
"""
Offline computation of the paper's coverage-side metrics from a mission's
position log (as captured by mission_logger.py), since no equivalent is
published anywhere in the M-TARE ROS stack.

M-TARE has no fixed, shared, per-environment free-space grid, and a raw
bounding box around one mission's own trajectory badly overestimates free
space in a corridor-shaped environment (e.g. `tunnel`) while also being
circular (a mission's coverage denominator should not be derived from that
same mission's own trajectory). Instead:

  1. `build-reference` — run once per environment, on a long/thorough
     exploration log — computes the free-space cell set as a buffered
     (dilated) union of every visited cell, and saves it to a JSON file.
     This is a proxy for "reachable area", not literal mesh geometry, but
     unlike a bounding box it hugs the actual corridor/branching shape.
  2. `analyze` — run per mission (baseline/SLA/BLA, any team size, any
     iteration) — loads that SAME saved reference and computes:

       coverage_efficiency = |unique visited cells| / |reference free cells|
       uncovered_cells     = |reference free cells| - |unique visited cells|
       collision           = (cell, time-bucket) pairs with >=2 distinct
                              robots present, divided by all occupied
                              (cell, time-bucket) pairs
       redundant_coverage  = total re-entries into a cell already visited
                              by any robot at an earlier time, averaged
                              per robot

     Using the same fixed reference across all conditions in an environment
     is what makes coverage_efficiency/uncovered_cells comparable across
     baseline/SLA/BLA — the denominator doesn't move under the attack.

Usage:
    python3 coverage_metrics.py build-reference <position_csv> \\
        [--cell-size 1.0] [--buffer-radius 2.0] --out reference.json

    python3 coverage_metrics.py analyze <position_csv> \\
        --reference reference.json [--time-bucket 1.0] [--json]
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict


def load_records(path, exclude_robot_ids=()):
    records = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                rid = int(row["robot_id"])
                if rid in exclude_robot_ids:
                    continue
                records.append({
                    "recv_time": float(row["recv_time"]),
                    "robot_id":  rid,
                    "x":         float(row["x"]),
                    "y":         float(row["y"]),
                })
            except (TypeError, ValueError, KeyError):
                continue
    records.sort(key=lambda r: r["recv_time"])
    return records


def cell_of(x, y, cell_size):
    return (math.floor(x / cell_size), math.floor(y / cell_size))


def dilate(cells, radius_cells):
    """Union of disks of the given radius (in cells) around each cell."""
    if radius_cells <= 0:
        return set(cells)
    r = math.ceil(radius_cells)
    offsets = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
               if dx * dx + dy * dy <= radius_cells * radius_cells]
    dilated = set()
    for (cx, cy) in cells:
        for dx, dy in offsets:
            dilated.add((cx + dx, cy + dy))
    return dilated


def build_reference(records, cell_size, buffer_radius):
    visited = {cell_of(r["x"], r["y"], cell_size) for r in records}
    free_cells = dilate(visited, buffer_radius)
    return {
        "cell_size": cell_size,
        "buffer_radius": buffer_radius,
        "n_reference_records": len(records),
        "n_visited_cells_raw": len(visited),
        "free_cells": sorted(list(free_cells)),
    }


def compute_metrics(records, reference, time_bucket, attacker_robot_id=None):
    cell_size = reference["cell_size"]
    free_cells = set(tuple(c) for c in reference["free_cells"])
    total_free_cells = len(free_cells)

    visited_cells = set()
    robot_ids = set()

    per_robot_visited = defaultdict(set)
    global_visited_so_far = set()
    redundant_entries = 0
    occupancy = defaultdict(set)

    for rec in records:
        robot_ids.add(rec["robot_id"])
        cell = cell_of(rec["x"], rec["y"], cell_size)
        visited_cells.add(cell)

        if cell in global_visited_so_far:
            redundant_entries += 1
        else:
            global_visited_so_far.add(cell)
        per_robot_visited[rec["robot_id"]].add(cell)

        tb = math.floor(rec["recv_time"] / time_bucket)
        occupancy[(tb, cell)].add(rec["robot_id"])

    n_robots = max(1, len(robot_ids))

    occupied_events = len(occupancy)
    collision_events = sum(1 for robots in occupancy.values() if len(robots) >= 2)
    collision = collision_events / occupied_events if occupied_events else 0.0

    visited_within_reference = visited_cells & free_cells
    coverage_efficiency = (len(visited_within_reference) / total_free_cells
                            if total_free_cells else 0.0)
    uncovered_cells = total_free_cells - len(visited_within_reference)
    redundant_coverage = redundant_entries / n_robots

    result = {
        "n_records": len(records),
        "n_robots": n_robots,
        "cell_size": cell_size,
        "total_free_cells": total_free_cells,
        "unique_visited_cells": len(visited_cells),
        "visited_within_reference": len(visited_within_reference),
        "coverage_efficiency": round(coverage_efficiency, 4),
        "uncovered_cells": uncovered_cells,
        "collision": round(collision, 4),
        "redundant_coverage": round(redundant_coverage, 3),
    }

    # Malicious vs. legitimate coverage split (paper Fig. 1 finding), only
    # meaningful when an attacker robot id is known for this mission.
    if attacker_robot_id is not None:
        malicious_cells = per_robot_visited.get(attacker_robot_id, set())
        legitimate_cells = set()
        for rid, cells in per_robot_visited.items():
            if rid != attacker_robot_id:
                legitimate_cells |= cells
        result["malicious_coverage_cells"] = len(malicious_cells)
        result["legitimate_coverage_cells"] = len(legitimate_cells)
        result["malicious_coverage_efficiency"] = (
            round(len(malicious_cells & free_cells) / total_free_cells, 4)
            if total_free_cells else 0.0
        )
        result["legitimate_coverage_efficiency"] = (
            round(len(legitimate_cells & free_cells) / total_free_cells, 4)
            if total_free_cells else 0.0
        )

    return result


def main():
    p = argparse.ArgumentParser(description="Coverage-side metrics for M-TARE live missions")
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build-reference", help="Build a per-environment free-space reference")
    pb.add_argument("csv_path")
    pb.add_argument("--cell-size", type=float, default=1.0)
    pb.add_argument("--buffer-radius", type=float, default=2.0,
                     help="Dilation radius in cells around each visited cell")
    pb.add_argument("--exclude-robot-id", type=int, action="append", default=[],
                     help="Robot id(s) to exclude (e.g. manual test packets)")
    pb.add_argument("--out", required=True)

    pa = sub.add_parser("analyze", help="Compute metrics for a mission against a saved reference")
    pa.add_argument("csv_path")
    pa.add_argument("--reference", required=True)
    pa.add_argument("--time-bucket", type=float, default=1.0)
    pa.add_argument("--exclude-robot-id", type=int, action="append", default=[],
                     help="Robot id(s) to exclude (e.g. manual test packets)")
    pa.add_argument("--attacker-robot-id", type=int, default=None,
                     help="If set, also splits coverage into malicious vs. legitimate")
    pa.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "build-reference":
        records = load_records(args.csv_path, exclude_robot_ids=set(args.exclude_robot_id))
        if not records:
            print("No valid position records found.", file=sys.stderr)
            sys.exit(1)
        ref = build_reference(records, args.cell_size, args.buffer_radius)
        with open(args.out, "w") as f:
            json.dump(ref, f)
        print(f"Reference built: {ref['n_visited_cells_raw']} visited cells -> "
              f"{len(ref['free_cells'])} free cells after buffer_radius={args.buffer_radius}. "
              f"Saved to {args.out}")

    elif args.cmd == "analyze":
        records = load_records(args.csv_path, exclude_robot_ids=set(args.exclude_robot_id))
        if not records:
            print("No valid position records found.", file=sys.stderr)
            sys.exit(1)
        with open(args.reference) as f:
            reference = json.load(f)
        metrics = compute_metrics(records, reference, args.time_bucket,
                                   attacker_robot_id=args.attacker_robot_id)
        if args.json:
            print(json.dumps(metrics))
        else:
            for k, v in metrics.items():
                print(f"{k:>26}: {v}")


if __name__ == "__main__":
    main()
