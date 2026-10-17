#!/usr/bin/env python3
"""
Paired analysis of the planner-level delay attack on the original M-TARE system.

Validity rule (fixed before looking at attack-vs-baseline differences, and independent of condition): a mission is valid
only if every robot has trajectory data and travelled at least MIN_DIST metres within the budget. Invalid missions are
failed runs (a robot that never moved, or no data recorded) and are excluded together with their pair.
"""
import collections, math, random, statistics as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_planner as A

MIN_DIST = 100.0


def load(root, budget):
    out = {}
    for d in sorted(Path(root).glob("*_*_*_*")):
        if not (d / "DONE").exists():
            continue
        env, n, c, it = d.name.split("_"); n = int(n)
        dists = []
        for rid in range(n):
            tf = d / f"trajectory_{rid}.txt"
            p = A.load_traj(tf, budget) if tf.exists() else []
            dists.append(sum(math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]) for i in range(len(p) - 1)) if len(p) > 1 else 0.0)
        r = A.mission(d, budget)
        r["valid"] = all(x >= MIN_DIST for x in dists)
        r["min_robot_dist"] = min(dists) if dists else 0
        out[(env, n, int(it), c)] = r
    return out


def boot(d, B=5000, seed=1):
    rng = random.Random(seed); m = sorted(st.mean(rng.choice(d) for _ in d) for _ in range(B))
    return m[int(.025 * B)], m[int(.975 * B)]


def sign_p(d):
    nz = [x for x in d if x != 0]; n = len(nz)
    if not n: return 1.0
    k = sum(x < 0 for x in nz)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n)


def main(root="planner_runs", budget=360.0):
    M = load(root, budget)
    bad = sorted(k for k, v in M.items() if not v["valid"])
    print(f"{len(M)} missions, {len(bad)} invalid (excluded): {['_'.join(map(str, k)) for k in bad]}\n")
    keys = sorted({(e, n, i) for (e, n, i, c) in M})
    metrics = (("union_cells", "team union coverage"), ("redundancy", "redundancy"), ("total_distance", "total distance"), ("sum_explored_volume", "summed explored volume"))
    print(f"{'setting':14}{'attack':6} {'metric':24}{'mean change':>12}{'95% bootstrap CI':>20}{'lower':>8}{'n':>4}")
    pooled = collections.defaultdict(list)
    for (env, n) in sorted({(e, n) for e, n, i in keys}):
        for key, name in metrics:
            for c in ("sla", "bla"):
                d = []
                for (e, nn, i) in keys:
                    if (e, nn) != (env, n): continue
                    b, a = M.get((e, nn, i, "baseline")), M.get((e, nn, i, c))
                    if b and a and b["valid"] and a["valid"] and b[key]:
                        d.append(a[key] / b[key] - 1)
                pooled[(key, c)] += d
                if len(d) >= 3:
                    lo, hi = boot(d)
                    print(f"{env+' N='+str(n):14}{c:6} {name:24}{100*st.mean(d):+11.1f}%{'['+f'{100*lo:+.0f}, {100*hi:+.0f}'+']':>20}{sum(x < 0 for x in d):>5}/{len(d):<3}{len(d):>3}")
    print("\nPOOLED over environments and team sizes (valid pairs only):")
    for key, name in metrics:
        for c in ("sla", "bla"):
            d = pooled[(key, c)]
            if len(d) >= 3:
                lo, hi = boot(d)
                print(f"  {name:24}{c:6} {100*st.mean(d):+6.1f}%  95% CI [{100*lo:+.0f}, {100*hi:+.0f}]  n={len(d)}  lower in {sum(x < 0 for x in d)}  sign-test p={sign_p(d):.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "planner_runs", float(sys.argv[2]) if len(sys.argv) > 2 else 360.0)
