#!/usr/bin/env python3
"""
LaTeX tables for the v3 paper, generated from the per-mission CSVs so the numbers cannot drift.

Intervals: 95% bootstrap over seeds (iteration indices are the clusters; missions with the same seed share start
positions), 2000 resamples. Per-class rates: SLA / BLA mission correctness and the share of attack-free missions with
any false flag.

  python3 make_tables_v3.py            -> study_results/tables_v3.tex, prints the numbers quoted in the text
"""
import collections, csv, json, os, re, sys
import numpy as np

S = "study_results/"
B = 2000
RNG = np.random.default_rng(7)

NAMES = {"fixed_orig": "Fixed thresholds (original)", "fixed": "Fixed thresholds (retuned)", "maxage": "Message-age check",
         "cusum_self": "CUSUM, own-stream ref.", "ewma_self": "EWMA, own-stream ref.", "mad_self": "MAD test, own-stream ref.",
         "bocpd_self": "Bayesian change-point, own-stream ref.",
         "etd_style": "ETD-style (one-class + K-Means)", "hotd_style": "HOTD-style (supervised)", "iforest": "Isolation Forest",
         "etd_pop": "ETD-style, pop.-normalized", "hotd_pop": "HOTD-style, pop.-normalized", "iforest_pop": "Isolation Forest, pop.-normalized",
         "mad_pop": "MAD test, population ref.", "cusum_pop": "CUSUM, population ref.", "ewma_pop": "EWMA, population ref.",
         "bocpd_pop": "Bayesian change-point, population ref.", "calibrated": "Calibrated (persistence rule)"}
GROUPS = [["fixed_orig", "fixed", "maxage"], ["cusum_self", "ewma_self", "mad_self", "bocpd_self"],
          ["etd_style", "hotd_style", "iforest"], ["etd_pop", "hotd_pop", "iforest_pop"],
          ["mad_pop", "cusum_pop", "ewma_pop", "bocpd_pop", "calibrated"]]
ORDER = [d for g in GROUPS for d in g]
SYM = {"alpha": r"\alpha", "density_threshold": r"\tau_\rho", "mean_delay_threshold": r"\tau_\mu", "min_votes": r"v_{\min}",
       "seq_gap_threshold": r"\tau_s", "variance_threshold": r"\tau_v", "T": "T", "persist": "P", "k": None, "h": "h",
       "n0": "n_0", "L": "L", "lam": r"\omega", "c": "c", "delta": None, "hazard": "H", "theta": r"\theta", "smin": r"s_{\min}",
       "tau": r"\tau", "min_samples": r"n_{\min}"}


def fit(table, star):
    w = r"\textwidth" if star else r"\columnwidth"
    table = table.replace(r"\begin{tabular}", r"\resizebox{\ifdim\width>" + w + w + r"\else\width\fi}{!}{%" + "\n" + r"\begin{tabular}", 1)
    return table.replace(r"\end{tabular}", r"\end{tabular}}", 1)


def load(path):
    rows = list(csv.DictReader(open(path)))
    for r in rows:
        r["correct"] = int(r["correct"]); r["fp"] = int(r["fp"]); r["iter"] = int(r["iter"]); r["n"] = int(r["n"])
        r["lat"] = float(r["lat"]) if r["lat"] not in ("", "None") else None
    return rows


def index(rows):
    D = collections.defaultdict(list)
    for r in rows:
        D[(r["noise"], r["detector"])].append(r)
    return D


def boot(rs, val=lambda r: r["correct"], pick=lambda r: True):
    """Mean of val over rows passing pick, with a cluster bootstrap over iterations."""
    rs = [r for r in rs if pick(r)]
    if not rs:
        return float("nan"), float("nan"), float("nan")
    its = sorted({r["iter"] for r in rs}); ix = {it: i for i, it in enumerate(its)}
    s = np.zeros(len(its)); n = np.zeros(len(its))
    for r in rs:
        s[ix[r["iter"]]] += val(r); n[ix[r["iter"]]] += 1
    W = RNG.multinomial(len(its), [1 / len(its)] * len(its), size=B)
    bs = (W @ s) / np.maximum(W @ n, 1)
    return s.sum() / n.sum(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def paired(ra, rb):
    """Accuracy difference a-b, paired by mission, cluster bootstrap over iterations."""
    key = lambda r: (r["map"], r["n"], r["cond"], r["iter"])
    A = {key(r): r["correct"] for r in ra}; Bm = {key(r): r["correct"] for r in rb}
    rows = [dict(iter=k[3], correct=A[k] - Bm[k]) for k in A if k in Bm]
    return boot(rows)


def pc(x):
    return f"{100*x:.1f}"


def acc_cell(rs):
    e, lo, hi = boot(rs)
    return f"{100*e:.1f} ({100*max(lo,0):.1f}--{100*min(hi,1):.1f})"


def cls(rs):
    by = boot(rs, pick=lambda r: r["cond"] == "sla")[0]
    bd = boot(rs, pick=lambda r: r["cond"] == "bla")[0]
    af = boot(rs, val=lambda r: int(r["fp"] > 0), pick=lambda r: r["cond"] == "baseline")[0]
    return by, bd, af


out = []
txt = []
tuned = json.load(open(S + "tuned.json"))
std = index(load(S + "std_missions.csv"))
NZ = [("std_none", "None"), ("std_light", "Light"), ("std_moderate", "Moderate"), ("std_heavy", "Heavy"), ("std_shift", "Shifted")]

# ------------------------------------------------------------------ tuned configurations
def fmt_params(d, p):
    parts = []
    for k, v in sorted(p.items()):
        if d == "calibrated" and k == "k": sym = r"\kappa"
        elif d.startswith("cusum") and k == "k": sym = r"\nu"
        elif k == "delta": sym = r"\delta_B" if d.startswith("bocpd") else r"\delta"
        elif k == "lam": sym = r"\omega"
        else: sym = SYM.get(k, k)
        val = r"\infty" if isinstance(v, (int, float)) and v >= 1e8 else (f"{v:g}" if isinstance(v, (int, float)) else str(v))
        parts.append(f"${sym}={val}$")
    return ", ".join(parts)

t = [r"\begin{table*}[t]", r"\centering",
     r"\caption{Configurations selected on the held-out missions (300 per noise level), with their worst-case and mean mission accuracy (\%) across the four held-out uniform-noise levels. Every detector was searched with the same number of random draws (up to 36). Symbols as in Section~\ref{sec:method_cal}; $\infty$ disables an indicator.}",
     r"\label{tab:tuned}", r"\footnotesize", r"\begin{tabular}{lp{0.55\textwidth}rr}", r"\hline", r"Detector & Selected parameters & Worst case & Mean \\", r"\hline"]
for d in ORDER:
    if d == "fixed_orig": continue
    v = tuned[d]
    t.append(f"{NAMES[d]} & {fmt_params(d, v['params'])} & {100*v['worst']:.1f} & {100*v['mean']:.1f} \\\\")
t += [r"\hline", r"\end{tabular}", r"\end{table*}"]
out.append("\n".join(t))

# ------------------------------------------------------------------ accuracy table
t = [r"\begin{table*}[t]", r"\centering",
     r"\caption{Mission accuracy (\%, 95\% bootstrap interval over seeds) of each detector, in 5{,}250 missions per noise level (5 layouts, 14 team sizes, 3 conditions, 25 seeds). A mission is correct when every attacker is flagged and no honest robot is flagged (attack-free missions: nothing flagged); a detector that flags nothing scores 33.3\%, one that finds only SLA 66.7\%. Noise: none; light (jitter $\le1$ step, 2\% loss); moderate ($\le2$, 5\%); heavy ($\le3$, 10\%); shifted (heavy-tailed jitter and bursty loss, never used for tuning). All parameters were fixed on held-out missions beforehand.}",
     r"\label{tab:acc}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{lccccc}", r"\hline",
     "Detector & " + " & ".join(n for _, n in NZ) + r" \\", r"\hline"]
for g in GROUPS:
    for d in g:
        t.append(NAMES[d] + " & " + " & ".join(acc_cell(std[(k, d)]) for k, _ in NZ) + r" \\")
    t.append(r"\hline")
t += [r"\end{tabular}", r"\end{table*}"]
out.append("\n".join(t))

# ------------------------------------------------------------------ per-class table
t = [r"\begin{table*}[t]", r"\centering",
     r"\caption{Per-class rates (\%) for the runs of Table~\ref{tab:acc}: SLA missions correct / BLA missions correct / attack-free missions with any false flag. Higher is better for the first two, lower for the third.}",
     r"\label{tab:recfp}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{lccccc}", r"\hline",
     "Detector & " + " & ".join(n for _, n in NZ) + r" \\", r"\hline"]
CLS = {}
for g in GROUPS:
    for d in g:
        cells = []
        for k, _ in NZ:
            by, bd, af = cls(std[(k, d)]); CLS[(k, d)] = (by, bd, af)
            cells.append(f"{100*by:.0f} / {100*bd:.0f} / {100*af:.0f}")
        t.append(NAMES[d] + " & " + " & ".join(cells) + r" \\")
    t.append(r"\hline")
t += [r"\end{tabular}", r"\end{table*}"]
out.append("\n".join(t))

txt.append("== accuracy and per-class (std)")
for d in ORDER:
    line = f"{d:12}"
    for k, _ in NZ:
        e = boot(std[(k, d)])[0]; by, bd, af = CLS[(k, d)]
        line += f" | {k[4:]:8} {100*e:5.1f} ({100*by:3.0f}/{100*bd:3.0f}/{100*af:3.0f})"
    txt.append(line)

# paired differences quoted in the text
txt.append("== paired accuracy differences (a-b, 95% CI), std")
PAIRS = [("ewma_pop", "calibrated"), ("cusum_pop", "calibrated"), ("bocpd_pop", "calibrated"), ("hotd_style", "calibrated"),
         ("hotd_pop", "calibrated"), ("fixed", "calibrated"), ("maxage", "calibrated"), ("ewma_pop", "cusum_pop"),
         ("bocpd_pop", "ewma_pop"), ("etd_pop", "etd_style"), ("iforest_pop", "iforest"), ("hotd_pop", "hotd_style")]
for a, b in PAIRS:
    txt.append(f"{a:11} - {b:11}: " + "  ".join(f"{k[4:]} {100*paired(std[(k, a)], std[(k, b)])[0]:+.1f} [{100*paired(std[(k, a)], std[(k, b)])[1]:+.1f},{100*paired(std[(k, a)], std[(k, b)])[2]:+.1f}]" for k, _ in NZ))

# ------------------------------------------------------------------ latency
t = [r"\begin{table}[t]", r"\centering",
     r"\caption{Mean detection latency (steps after the attack starts, over detected attackers), by noise level, for detectors whose accuracy exceeds 66.7\% at some uniform-noise level.}",
     r"\label{tab:lat}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{lcccc}", r"\hline", r"Detector & None & Light & Moderate & Heavy \\", r"\hline"]
for d in ORDER:
    if max(boot(std[(k, d)])[0] for k, _ in NZ[:4]) <= 0.6675: continue
    cells = []
    for k, _ in NZ[:4]:
        L = [r["lat"] for r in std[(k, d)] if r["lat"] is not None]
        cells.append(f"{np.mean(L):.1f}" if L else "--")
    t.append(NAMES[d] + " & " + " & ".join(cells) + r" \\")
t += [r"\hline", r"\end{tabular}", r"\end{table}"]
out.append("\n".join(t))

# ------------------------------------------------------------------ per map / per team size (moderate noise)
t = [r"\begin{table*}[t]", r"\centering",
     r"\caption{Mission accuracy (\%) at moderate noise by layout and by team size, for the population-referenced detectors and the strongest baselines (25 seeds, 3 conditions per cell).}",
     r"\label{tab:bymapsize}", r"\setlength{\tabcolsep}{3pt}"]
MAPS = ["tunnel", "indoor", "garage", "campus", "forest"]; SIZES = [4, 5, 8, 10, 12, 15, 16, 20, 25, 30, 35, 40, 45, 50]
DS = ["fixed", "maxage", "hotd_style", "hotd_pop", "cusum_pop", "ewma_pop", "bocpd_pop", "calibrated"]
t += [r"\begin{tabular}{l" + "c" * (len(MAPS) + len(SIZES)) + "}", r"\hline",
      r"Detector & " + " & ".join(m.capitalize() for m in MAPS) + " & " + " & ".join(f"$m{{=}}{n}$" if i == 0 else str(n) for i, n in enumerate(SIZES)) + r" \\", r"\hline"]
for d in DS:
    rs = std[("std_moderate", d)]
    cells = [f"{100*np.mean([r['correct'] for r in rs if r['map'] == m]):.0f}" for m in MAPS] + \
            [f"{100*np.mean([r['correct'] for r in rs if r['n'] == n]):.0f}" for n in SIZES]
    t.append(NAMES[d] + " & " + " & ".join(cells) + r" \\")
t += [r"\hline", r"\end{tabular}", r"\end{table*}"]
out.append("\n".join(t))
txt.append("== by map / size at moderate (min-max over maps; min over sizes) for pop detectors")
for d in DS:
    rs = std[("std_moderate", d)]
    bm = [np.mean([r['correct'] for r in rs if r['map'] == m]) for m in MAPS]
    bs = [np.mean([r['correct'] for r in rs if r['n'] == n]) for n in SIZES]
    txt.append(f"  {d:11} maps {100*min(bm):.1f}-{100*max(bm):.1f}  sizes {100*min(bs):.1f}-{100*max(bs):.1f} (worst n={SIZES[int(np.argmin(bs))]})")

# ------------------------------------------------------------------ secondary
sec = index(load(S + "sec_missions.csv"))
SEC = [("sec_lam2", r"$\lambda=2$"), ("sec_lam5", r"$\lambda=5$"), ("sec_onset10", "Onset at step 10")]
t = [r"\begin{table}[t]", r"\centering",
     r"\caption{Mission accuracy (\%, 95\% bootstrap interval) at moderate noise for other delay windows $\lambda$ (steps) and for attacks that start at step 10, with parameters tuned only for $\lambda=3$ and onset 0 (1{,}125 missions per column).}",
     r"\label{tab:sec}", r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{lccc}", r"\hline",
     "Detector & " + " & ".join(n for _, n in SEC) + r" \\", r"\hline"]
for g in GROUPS:
    for d in g:
        t.append(NAMES[d] + " & " + " & ".join(acc_cell(sec[(k, d)]) for k, _ in SEC) + r" \\")
    t.append(r"\hline")
t += [r"\end{tabular}", r"\end{table}"]
out.append("\n".join(t))
txt.append("== secondary per-class")
for d in ORDER:
    txt.append(f"  {d:12}" + "  ".join(f"{k[4:]} {100*boot(sec[(k, d)])[0]:5.1f} ({'/'.join(f'{100*x:.0f}' for x in cls(sec[(k, d)]))})" for k, _ in SEC))

# ------------------------------------------------------------------ late onset (own-stream fairness)
if os.path.exists(S + "late_missions.csv"):
    late = index(load(S + "late_missions.csv")); tl = json.load(open(S + "tuned_late.json"))
    latem = index(load(S + "late_maintuned_missions.csv"))
    LN = [("late_onset20_none", "None"), ("late_onset20_moderate", "Moderate")]
    t = [r"\begin{table}[t]", r"\centering",
         r"\caption{Attack starting at step 20 (teams of 4, 8, 12; 1{,}125 missions per noise level), with every detector retuned on held-out late-onset missions so that an own-stream reference can learn from attack-free messages. Entries: mission accuracy (\%) and SLA / BLA / attack-free false-flag rates (\%); the last column is the selected own-stream warm-up $n_0$.}",
         r"\label{tab:late}", r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{lccc}", r"\hline",
         r"Detector & None & Moderate & $n_0$ \\", r"\hline"]
    for g in GROUPS:
        for d in g:
            if (LN[0][0], d) not in late: continue
            cells = []
            for k, _ in LN:
                rs = late[(k, d)]; by, bd, af = cls(rs)
                cells.append(f"{100*boot(rs)[0]:.1f} ({100*by:.0f}/{100*bd:.0f}/{100*af:.0f})")
            n0 = tl.get(d, {}).get("params", {}).get("n0", "--")
            t.append(NAMES[d] + " & " + " & ".join(cells) + f" & {n0}" + r" \\")
        t.append(r"\hline")
    t += [r"\end{tabular}", r"\end{table}"]
    out.append(fit("\n".join(t), False))
    txt.append("== late onset (retuned) vs main-tuned")
    for d in ORDER:
        if (LN[0][0], d) in late:
            txt.append(f"  {d:12} retuned " + " ".join(f"{100*boot(late[(k, d)])[0]:5.1f}" for k, _ in LN) +
                       "  main-tuned " + " ".join(f"{100*boot(latem[(k, d)])[0]:5.1f}" for k, _ in LN) + f"  params {tl.get(d, {}).get('params')}")

# ------------------------------------------------------------------ robustness (clock, heterogeneity)
if os.path.exists(S + "rob_missions.csv"):
    rob = index(load(S + "rob_missions.csv"))
    RS = [("std_moderate", "No perturbation", None), ("rob_clock_c0.5_moderate", r"Clock offset $\pm0.5$", None),
          ("rob_clock_c1_moderate", r"Clock offset $\pm1$", None), ("rob_clock_c2_moderate", r"Clock offset $\pm2$", None),
          ("rob_drift_r0.01_moderate", r"Clock drift $\pm1\%$", None), ("rob_het_B1_J0_moderate", r"Latency $b_j\le1$", None),
          ("rob_het_B0_J2_moderate", r"Jitter $J_j\le2$", None), ("rob_het_B1_J2_moderate", r"$b_j\le1$, $J_j\le2$", None),
          ("rob_het_B2_J3_moderate", r"$b_j\le2$, $J_j\le3$", None)]
    DR = ["fixed", "maxage", "hotd_style", "cusum_pop", "ewma_pop", "bocpd_pop", "calibrated"]
    t = [r"\begin{table*}[t]", r"\centering",
         r"\caption{Robustness to timing effects absent from the simulated channel (moderate noise, 5{,}250 missions per row, frozen detectors). Clock: every sender's clock is offset by $o_j\sim U(-c,c)$ steps or drifts by up to $\pm1\%$ per step. Latency: sender-specific extra delay $b_j\sim U(0,B)$ and extra jitter on $\{0,\dots,J_j\}$, $J_j\sim U\{0,\dots,J\}$. Entries: mission accuracy (\%) / attack-free missions with a false flag (\%).}",
         r"\label{tab:robust}", r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{l" + "c" * len(DR) + "}", r"\hline",
         "Perturbation & " + " & ".join(NAMES[d].replace(", population ref.", " (pop.)") for d in DR) + r" \\", r"\hline"]
    for k, lab, _ in RS:
        src = std if k == "std_moderate" else rob
        cells = []
        for d in DR:
            rs = src[(k, d)]
            cells.append(f"{100*boot(rs)[0]:.1f} / {100*cls(rs)[2]:.0f}")
        t.append(lab + " & " + " & ".join(cells) + r" \\")
    t += [r"\hline", r"\end{tabular}", r"\end{table*}"]
    out.append(fit("\n".join(t), True))
    txt.append("== robustness (acc / af-fp / sla / bla)")
    for k in sorted({k for k, _ in rob}):
        txt.append("  " + k + ": " + "  ".join(f"{d} {100*boot(rob[(k, d)])[0]:.1f}/{100*cls(rob[(k, d)])[2]:.0f}/{100*cls(rob[(k, d)])[0]:.0f}/{100*cls(rob[(k, d)])[1]:.0f}" for d in DR))

# ------------------------------------------------------------------ sensitivity
SV = [("", "Default ($W=10$, $\\epsilon=0.05$)"), ("sens_W5", "$W=5$"), ("sens_W20", "$W=20$"), ("sens_e0.01", "$\\epsilon=0.01$"),
      ("sens_e0.2", "$\\epsilon=0.2$"), ("sens_loo", "Leave-one-out median")]
if all(os.path.exists(S + f"{p}_missions.csv") for p, _ in SV[1:]):
    DS2 = ["cusum_pop", "ewma_pop", "bocpd_pop", "calibrated"]
    t = [r"\begin{table}[t]", r"\centering",
         r"\caption{Sensitivity of the population-referenced detectors (frozen parameters) to the population window $W$, the scale floor $\epsilon$, and a leave-one-out median. Mission accuracy (\%) under no / moderate / heavy noise.}",
         r"\label{tab:sens}", r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{l" + "c" * len(DS2) + "}", r"\hline",
         "Setting & " + " & ".join(["CUSUM", "EWMA", "Bayesian", "Calibrated"]) + r" \\", r"\hline"]
    for p, lab in SV:
        src = std if p == "" else index(load(S + f"{p}_missions.csv"))
        cells = ["/".join(f"{100*boot(src[(k, d)])[0]:.1f}" for k in ("std_none", "std_moderate", "std_heavy")) for d in DS2]
        t.append(lab + " & " + " & ".join(cells) + r" \\")
    t += [r"\hline", r"\end{tabular}", r"\end{table}"]
    out.append(fit("\n".join(t), False))

open(S + "tables_v3.tex", "w").write("\n\n".join(fit(x, "table*" in x) if "resizebox" not in x and "p{0.55" not in x else x for x in out) + "\n")
print("\n".join(txt))
