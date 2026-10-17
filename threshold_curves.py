#!/usr/bin/env python3
"""
Detection-delay versus false-alarm trade-off of the population-referenced detectors at moderate noise: the decision
threshold (CUSUM h, EWMA L, calibrated kappa) is swept with the other parameters frozen at their tuned values.
For each threshold: share of attack-free missions with any false flag, mean latency over detected attackers, and the
share of SLA / BLA attackers found. Writes study_results/curves.csv and the figure fig5.png.
"""
import csv, json, pickle, sys
from multiprocessing import Pool
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import study_detectors as sd

TR = None   # loaded lazily, so that --plot-only works without the simulation traces
TUNED = json.load(open("study_results/tuned.json"))
SWEEP = {"cusum_pop": ("h", [2, 3, 4, 6, 8, 12, 16, 24, 32]),
         "ewma_pop": ("L", [2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]),
         "calibrated": ("k", [2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0])}


def run(a):
    global TR
    if TR is None:
        TR = pickle.load(open("traces/std_moderate.pkl", "rb"))["missions"]
    det_name, val = a
    key, _ = SWEEP[det_name]
    p = dict(TUNED[det_name]["params"]); p[key] = val
    fp_af, lat, found = [], [], {"sla": [0, 0], "bla": [0, 0]}
    for m in TR:
        det = sd.make(det_name, **p)
        for (_t, s, q, g, r) in m["trace"]:
            det.observe(s, q, g, r)
        adv = set(m["adv"])
        if m["cond"] == "baseline":
            fp_af.append(int(len(det.first_flag) > 0))
        else:
            for x in adv:
                found[m["cond"]][1] += 1
                if x in det.first_flag:
                    found[m["cond"]][0] += 1; lat.append(det.first_flag[x] - m.get("onset", 0))
    return dict(det=det_name, param=key, value=val, af_fp=np.mean(fp_af), lat=np.mean(lat) if lat else float("nan"),
                sla_found=found["sla"][0] / found["sla"][1], bla_found=found["bla"][0] / found["bla"][1])


def plot(rows):
    plt.rcParams.update({"font.family": "serif", "font.size": 9, "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8.5})
    fig, axs = plt.subplots(1, 2, figsize=(7.1, 2.9))
    MK = {"cusum_pop": ("o", "-", "CUSUM ($h$)"), "ewma_pop": ("s", "--", "EWMA ($L$)"), "calibrated": ("^", ":", r"Calibrated ($\kappa$)")}
    for d in SWEEP:
        r = sorted([x for x in rows if x["det"] == d], key=lambda x: x["af_fp"])
        mk, ls, lab = MK[d]
        axs[0].plot([100 * x["af_fp"] for x in r], [x["lat"] for x in r], marker=mk, ls=ls, color="black", mfc="white", ms=4.5, lw=1.1, label=lab)
        axs[1].plot([100 * x["af_fp"] for x in r], [100 * x["bla_found"] for x in r], marker=mk, ls=ls, color="black", mfc="white", ms=4.5, lw=1.1, label=lab)
    for ax in axs:
        ax.set_xscale("symlog", linthresh=1.0, linscale=0.6)
        ax.set_xlim(-0.1, 110); ax.set_xticks([0, 1, 3, 10, 30, 100]); ax.set_xticklabels(["0", "1", "3", "10", "30", "100"])
        ax.set_xlabel("Attack-free false-flag rate (%, log scale)"); ax.grid(True, ls=":", lw=0.5, color="0.7")
    axs[0].set_ylabel("Mean detection latency (steps)"); axs[1].set_ylabel("BLA attackers found (%)"); axs[0].legend(frameon=False)
    fig.tight_layout(); fig.savefig("figures/fig5.png", dpi=300)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--plot-only":
    plot([{k: (float(v) if k not in ("det", "param") else v) for k, v in r.items()} for r in csv.DictReader(open("study_results/curves.csv"))])
    sys.exit(0)

if __name__ == "__main__":
    jobs = [(d, v) for d, (_, vs) in SWEEP.items() for v in vs]
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 32) as pool:
        rows = pool.map(run, jobs)
    with open("study_results/curves.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    plt.rcParams.update({"font.family": "serif", "font.size": 10})
    fig, axs = plt.subplots(1, 2, figsize=(9.2, 3.6))
    MK = {"cusum_pop": ("o", "-", "CUSUM ($h$)"), "ewma_pop": ("s", "--", "EWMA ($L$)"), "calibrated": ("^", ":", r"Calibrated ($\kappa$)")}
    for d in SWEEP:
        r = sorted([x for x in rows if x["det"] == d], key=lambda x: x["af_fp"])
        mk, ls, lab = MK[d]
        axs[0].plot([100 * x["af_fp"] for x in r], [x["lat"] for x in r], marker=mk, ls=ls, color="black", mfc="white", ms=4.5, lw=1.1, label=lab)
        axs[1].plot([100 * x["af_fp"] for x in r], [100 * x["bla_found"] for x in r], marker=mk, ls=ls, color="black", mfc="white", ms=4.5, lw=1.1, label=lab)
    for ax in axs:
        ax.set_xlabel("Attack-free missions with a false flag (%)"); ax.grid(True, ls=":", lw=0.5, color="0.7")
    axs[0].set_ylabel("Mean detection latency (steps)"); axs[1].set_ylabel("BLA attackers found (%)"); axs[0].legend(frameon=False)
    fig.tight_layout(); fig.savefig("figures/fig5.png", dpi=300)
    for x in rows:
        print(f"{x['det']:11}{x['param']}={x['value']:<5} afFP {100*x['af_fp']:5.1f}%  lat {x['lat']:5.1f}  SLA {100*x['sla_found']:5.1f}%  BLA {100*x['bla_found']:5.1f}%")
