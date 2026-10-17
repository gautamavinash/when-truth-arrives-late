"""Closed-loop response table (v3): keep everything, ignore a flagged sender (EWMA / calibrated detector), and the
detector-free freshness response that discards any message older than T=2 steps."""
import csv, collections, statistics as st
R = list(csv.DictReader(open("study_results/mitigation_raw.csv")))
idx = {(r["map"], int(r["n"]), r["cond"], int(r["iter"]), r["noise"], r["det"], r["mode"]): r for r in R}
def tot(cond, noise, det, mode, f="redundant"):
    return sum(float(r[f]) for k, r in idx.items() if k[2] == cond and k[4] == noise and k[5] == det and k[6] == mode)
def base(noise):  # attack-free, no response (identical for every detector)
    return tot("baseline", noise, "ewma_pop", "none"), tot("baseline", noise, "ewma_pop", "none", "completion")
ROWS = [("ewma_pop", "none", "Keep everything"), ("ewma_pop", "drop_all", "Ignore sender flagged by EWMA"),
        ("calibrated", "drop_all", "Ignore sender flagged by calibrated rule"), ("freshness", "stale_drop", "Drop messages older than 2 steps")]
L = [r"\begin{table}[t]", r"\centering",
     r"\caption{Closed-loop responses (grid world; 5 layouts, team sizes 5, 10, 20, 50, 25 seeds). Extra redundant visits and mission time are relative to the attack-free missions with the same seeds and no response (ratio of totals); the last column is the cost of the response itself in attack-free missions. Coverage stayed complete in every run.}",
     r"\label{tab:mitigation}", r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{llcccc}", r"\hline",
     r"Noise & Response & SLA & BLA & SLA time & Attack-free \\", r"\hline"]
for noise in ("none", "moderate"):
    b, bc = base(noise)
    for k, (det, mode, name) in enumerate(ROWS):
        ex = lambda c: 100 * (tot(c, noise, det, mode) / b - 1)
        tm = 100 * (tot("sla", noise, det, mode, "completion") / bc - 1)
        L.append(f"{noise if k == 0 else ''} & {name} & ${ex('sla'):+.1f}\\%$ & ${ex('bla'):+.1f}\\%$ & ${tm:+.1f}\\%$ & ${ex('baseline'):+.1f}\\%$ \\\\")
        fl = [r for kk, r in idx.items() if kk[4] == noise and kk[5] == det and kk[6] == mode]
        fa = sum(int(r["flagged_att"]) for r in fl); na = sum(int(r["n_att"]) for r in fl)
        fh = sum(1 for r in fl if r["cond"] == "baseline" and int(r["flagged_honest"]) > 0)
        print(f"{noise:9}{name:42} SLA {ex('sla'):+6.1f}% BLA {ex('bla'):+6.1f}% time {tm:+5.1f}% AF {ex('baseline'):+5.1f}%  attackers flagged {fa}/{na}  AF missions w/ honest flag {fh}")
    L.append(r"\hline")
L += [r"\end{tabular}", r"\end{table}"]
t = "\n".join(L)
w = r"\columnwidth"
t = t.replace(r"\begin{tabular}", r"\resizebox{\ifdim\width>" + w + w + r"\else\width\fi}{!}{%" + "\n" + r"\begin{tabular}", 1).replace(r"\end{tabular}", r"\end{tabular}}", 1)
open("study_results/mitigation_table.tex", "w").write(t + "\n")
print("min cov_eff", min(float(r["cov_eff"]) for r in R))
