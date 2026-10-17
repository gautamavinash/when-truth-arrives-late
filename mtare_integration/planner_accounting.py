#!/usr/bin/env python3
"""Mission accounting for the planner-level study: missions run, failed (validity rule), and pairs analysed, per setting
and design. Fixed-order design: iterations 0-14 (4 robots) / 0-4 (8 robots); randomized-order control: iterations 15-20."""
import collections, sys
from analyze_planner_final import load

M = load("planner_runs", 360.0)
rows = collections.OrderedDict()
for (env, n, it, c), r in sorted(M.items()):
    design = "fixed" if it < 15 else "control"
    rows.setdefault((design, env, n), []).append((it, c, r["valid"]))
print(f"{'design':8}{'setting':12}{'iters':>6}{'missions':>9}{'failed':>7}{'excl. w/ pair':>14}{'SLA pairs':>11}{'BLA pairs':>10}")
tex = []
for (design, env, n), v in rows.items():
    its = sorted({x[0] for x in v}); ok = {(i, c): val for i, c, val in v}
    failed = sum(1 for i, c, val in v if not val)
    pairs = {}
    for c in ("sla", "bla"):
        if design == "fixed":
            pairs[c] = sum(1 for i in its if ok.get((i, "baseline")) and ok.get((i, c)))
        else:
            pairs[c] = sum(1 for i in its if ok.get((i, c)) and (ok.get((i, "baseline")) or ok.get((i, "baseline2"))))
    used = set()
    for i in its:
        for c in ("sla", "bla"):
            if design == "fixed" and ok.get((i, "baseline")) and ok.get((i, c)): used |= {(i, "baseline"), (i, c)}
            if design == "control" and ok.get((i, c)) and (ok.get((i, "baseline")) or ok.get((i, "baseline2"))):
                used |= {(i, c)} | {(i, b) for b in ("baseline", "baseline2") if ok.get((i, b))}
    excl = len(v) - len(used)
    print(f"{design:8}{env+' '+str(n):12}{len(its):>6}{len(v):>9}{failed:>7}{excl:>14}{pairs['sla']:>11}{pairs['bla']:>10}")
    tex.append(f"{'Fixed order' if design == 'fixed' else 'Randomized order'} & {env.capitalize()}, {n} & {len(its)} & {len(v)} & {failed} & {excl} & {pairs['sla']} / {pairs['bla']} \\\\")
open("planner_runs/planner_accounting.tex", "w").write("\n".join(tex) + "\n")
