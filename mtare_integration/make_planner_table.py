import statistics as st, sys
sys.path.insert(0, '.')
import analyze_planner_final as AF
M = {k: v for k, v in AF.load("planner_runs", 360.0).items() if k[2] < 15}   # fixed-order design (iterations 0-14)
keys = sorted({(e, n, i) for (e, n, i, c) in M})
def pairs(cond, key, sel):
    d = []
    for (e, n, i) in keys:
        if not sel(e, n): continue
        b, a = M.get((e, n, i, "baseline")), M.get((e, n, i, cond))
        if b and a and b["valid"] and a["valid"] and b[key]:
            d.append(a[key] / b[key] - 1)
    return d
def cell(d):
    if len(d) < 3: return "--"
    lo, hi = AF.boot(d)
    return f"{100*st.mean(d):+.1f} [{100*lo:+.0f}, {100*hi:+.0f}]"
rows = []
for env, n, lab in (("tunnel", 4, "Tunnel, 4 robots"), ("garage", 4, "Garage, 4 robots"), ("tunnel", 8, "Tunnel, 8 robots"), ("garage", 8, "Garage, 8 robots"), (None, None, "All valid pairs")):
    sel = (lambda e, nn, env=env, n=n: env is None or (e == env and nn == n))
    nb, nd = len(pairs("sla", "union_cells", sel)), len(pairs("bla", "union_cells", sel))
    rows.append(f"{lab} & {nb}/{nd} & " + " & ".join(cell(pairs(c, k, sel)) for c in ("sla", "bla") for k in ("union_cells", "redundancy")) + r" \\")
    if env == "garage" and n == 8: rows.append(r"\hline")
t = "\n".join([r"\begin{table*}[t]", r"\centering",
 r"\caption{Planner-level delay attack on the original M-TARE system (fixed-order design: clustered start, 50\,m range, $\lambda=2.5$\,s, one compromised robot, 360\,s of exploration; 15 iterations for 4 robots and 5 for 8 robots, 120 missions). Entries are the mean paired change (\%) relative to the no-attack mission with the same start positions, with a 95\% bootstrap interval; pairs counted as SLA/BLA. Nine missions were failed runs (a robot that never moved, no data recorded, or a start from which most robots could not move) and are excluded together with their pairs.}",
 r"\label{tab:planner}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{lccccc}", r"\hline",
 r" & Pairs & SLA coverage & SLA redundancy & BLA coverage & BLA redundancy \\", r"\hline"] + rows + [r"\hline", r"\end{tabular}", r"\end{table*}"])
w = r"\textwidth"
t = t.replace(r"\begin{tabular}", r"\resizebox{\ifdim\width>" + w + w + r"\else\width\fi}{!}{%" + "\n" + r"\begin{tabular}", 1).replace(r"\end{tabular}", r"\end{tabular}}", 1)
open("planner_runs/planner_table.tex", "w").write(t + "\n")
print(t)
