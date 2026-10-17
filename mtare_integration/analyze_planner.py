#!/usr/bin/env python3
"""Team exploration metrics from collected planner-level mission data (trajectory + metrics files)."""
import csv, math, statistics as st, sys, collections
from pathlib import Path

CELL = 2.0     # metres


def load_traj(p, budget):
    pts = []
    for ln in open(p):
        v = ln.split()
        if len(v) >= 7:
            t = float(v[6])
            if t <= budget:
                pts.append((float(v[0]), float(v[1]), t))
    return pts


def metrics_last(p, budget):
    last = None
    for ln in open(p):
        v = ln.split()
        if len(v) >= 4 and float(v[3]) <= budget:
            last = [float(x) for x in v[:4]]
    return last


def mission(mdir, budget):
    cells = {}
    dist = vol = 0.0
    nrob = 0
    visits = 0
    for tf in sorted(mdir.glob("trajectory_*.txt")):
        rid = int(tf.stem.split("_")[1])
        pts = load_traj(tf, budget)
        if not pts:
            continue
        nrob += 1
        mine = set()
        for x, y, t in pts:
            c = (math.floor(x / CELL), math.floor(y / CELL))
            mine.add(c)
        for c in mine:
            cells.setdefault(c, set()).add(rid)
        visits += len(mine)
        mf = mdir / f"metrics_{rid}.txt"
        if mf.exists():
            m = metrics_last(mf, budget)
            if m:
                vol += m[0]; dist += m[1]
    union = len(cells)
    shared = sum(1 for s in cells.values() if len(s) > 1)
    return dict(robots=nrob, union_cells=union, redundancy=(visits - union) / max(visits, 1), shared_cells=shared,
                total_distance=dist, sum_explored_volume=vol)


def main(root, budget):
    rows = []
    for d in sorted(Path(root).glob("*_*_*_*")):
        if not (d / "DONE").exists():
            continue
        env, n, c, it = d.name.split("_")
        r = mission(d, budget); r.update(env=env, n=int(n), cond=c, it=int(it)); rows.append(r)
    by = collections.defaultdict(dict)
    for r in rows: by[(r["env"], r["n"], r["it"])][r["cond"]] = r
    print(f"{len(rows)} missions\n")
    print(f"{'env':8}{'N':>3}{'it':>3} | {'cond':9}{'union cells':>12}{'redundancy':>11}{'shared':>8}{'distance':>10}{'sum vol':>10}")
    for k in sorted(by):
        for c in ("baseline", "sla", "bla"):
            if c in by[k]:
                r = by[k][c]; print(f"{k[0]:8}{k[1]:>3}{k[2]:>3} | {c:9}{r['union_cells']:12d}{r['redundancy']:11.3f}{r['shared_cells']:8d}{r['total_distance']:10.0f}{r['sum_explored_volume']:10.0f}")
    print("\nPAIRED CHANGE vs baseline (same start positions), mean over iterations:")
    for key in (("union_cells", "union cells"), ("redundancy", "redundancy"), ("total_distance", "distance"), ("sum_explored_volume", "sum explored vol")):
        for c in ("sla", "bla"):
            d = []
            for k, v in by.items():
                if "baseline" in v and c in v and v["baseline"][key[0]]:
                    d.append(v[c][key[0]] / v["baseline"][key[0]] - 1)
            if d: print(f"  {key[1]:18}{c:6} {100*st.mean(d):+6.1f}%  (n={len(d)})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "planner_runs", float(sys.argv[2]) if len(sys.argv) > 2 else 240)
