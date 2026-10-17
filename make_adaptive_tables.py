"""LaTeX tables for the compromised-fraction and stealth-attacker studies."""
import csv, glob, pickle, re, statistics as st, collections
S = "study_results/"; f = float
NAMES = {"cusum_pop": "CUSUM, pop. ref.", "ewma_pop": "EWMA, pop. ref.", "bocpd_pop": "Bayesian, pop. ref.", "calibrated": "Calibrated rule",
         "hotd_style": "HOTD-style (supervised)", "fixed": "Fixed thresholds (retuned)", "maxage": "Message-age check"}
def fit(table, star=False):
    w = r"\textwidth" if star else r"\columnwidth"
    table = table.replace(r"\begin{tabular}", r"\resizebox{\ifdim\width>" + w + w + r"\else\width\fi}{!}{%" + "\n" + r"\begin{tabular}", 1)
    return table.replace(r"\end{tabular}", r"\end{tabular}}", 1)

rows = list(csv.DictReader(open(S + "adv_br_summary.csv")))
R = collections.defaultdict(dict)
for r in rows:
    m = re.match(r"br_(\w+)_f([\d.]+)_(\w+)", r["noise"])
    R[(m.group(1), m.group(3), r["detector"])][float(m.group(2))] = st.mean([f(r["sla_acc"]), f(r["bla_acc"])])
fr = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
L = [r"\begin{table*}[t]", r"\centering",
     r"\caption{Attack-mission accuracy (\%; both attacks pooled) as the compromised share of the team grows (team sizes 10, 20, 50; 25 seeds, 5 layouts; frozen detectors, tuned at 10\% colluding attackers). Colluding attackers share one delay window and start together; staggered attackers have random windows (2--5 steps) and start steps (0--9).}",
     r"\label{tab:breakdown}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{llcccccc}", r"\hline",
     r"Attackers, noise & Detector & 10\% & 20\% & 30\% & 40\% & 50\% & 60\% \\", r"\hline"]
for style, sname in (("colluding", "Colluding"), ("independent", "Staggered")):
    for noise, nname in (("none", "none"), ("moderate", "moderate")):
        for k, d in enumerate(["cusum_pop", "ewma_pop", "calibrated", "bocpd_pop", "hotd_style", "fixed", "maxage"]):
            lab = f"{sname}, {nname}" if k == 0 else ""
            L.append(f"{lab} & {NAMES[d]} & " + " & ".join(f"{100*R[(style, noise, d)][x]:.1f}" for x in fr) + r" \\")
        L.append(r"\hline")
L += [r"\end{tabular}", r"\end{table*}"]
t1 = fit("\n".join(L), True)

rows = list(csv.DictReader(open(S + "adv_st_summary.csv")))
Sx = collections.defaultdict(dict)
for r in rows:
    m = re.match(r"st_d(\d+)_p([\d.]+)_(\w+)", r["noise"])
    Sx[(int(m.group(1)), float(m.group(2)), m.group(3))][r["detector"]] = f(r["sla_acc"])
dmg = {}
for fn in glob.glob("traces/adv/st_*.pkl"):
    m = re.match(r".*st_d(\d+)_p([\d.]+)_(\w+)\.pkl", fn)
    ms = pickle.load(open(fn, "rb"))["missions"]
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for x in ms: by[(x["map"], x["n"])][x["cond"]].append(x["redundant"])
    dmg[(int(m.group(1)), float(m.group(2)), m.group(3))] = 100 * st.mean(st.mean(c["sla"]) / st.mean(c["baseline"]) - 1 for c in by.values() if c["baseline"] and c["sla"])
DET = ["cusum_pop", "ewma_pop", "calibrated", "bocpd_pop", "hotd_style", "fixed", "maxage"]
L = [r"\begin{table*}[t]", r"\centering",
     r"\caption{Stealth attacker: each message of every attacker is delayed by $d$ steps with probability $p$. Damage is the increase in total redundant visits over a mission without attackers (a full-strength SLA with $\lambda=3$ adds 61.5\% over team sizes 5--50). Entries are attack-mission accuracy (\%) of the frozen detectors at moderate noise; the last column is CUSUM on a noiseless channel. Team sizes 8, 20, 50; 25 seeds; 5 layouts.}",
     r"\label{tab:stealth}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{rrr" + "c" * len(DET) + "c}", r"\hline",
     r"$d$ & $p$ & Damage (\%) & " + " & ".join(NAMES[d] for d in DET) + r" & CUSUM, noiseless \\", r"\hline"]
for d in (1, 2, 3):
    for p in (0.1, 0.25, 0.5, 1.0):
        v = Sx[(d, p, "moderate")]
        L.append(f"{d} & {p} & {dmg[(d, p, 'moderate')]:.1f} & " + " & ".join(f"{100*v[k]:.0f}" for k in DET) + f" & {100*Sx[(d, p, 'none')]['cusum_pop']:.0f}" + r" \\")
    L.append(r"\hline")
L += [r"\end{tabular}", r"\end{table*}"]
t2 = fit("\n".join(L), True)
open(S + "adaptive_tables.tex", "w").write(t1 + "\n\n" + t2 + "\n")
print("ok")
