#!/usr/bin/env python3
"""
Impact of SLA/BLA in the grid world (v3: queue-preserving SLA, collisions counted at every step), from the noiseless
trace set traces/impact_none.pkl (5 layouts x 14 team sizes x 3 conditions x 25 seeds; same seeds as the detection
study). Prints the numbers used in the paper, writes LaTeX tables and the figures.

Normalization: an attacker's coverage is compared with the fair share |F|/m of the free cells and with the mean
coverage of the legitimate robots in the same mission, so the effect of a growing team on a fixed map is removed.
Intervals: 95% bootstrap over seeds (clusters = iteration index, 2000 resamples), ratio of totals.
"""
import collections, os, pickle, random, statistics as st, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from simulation.grid_env import GridEnv
from simulation.maps import get_map_obstacles

OUT = "figures"
MAPS = ["tunnel", "indoor", "garage", "campus", "forest"]
BIG = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
SMALL = [4, 8, 12, 16]
FREE = {m: GridEnv(size=16, obstacles=get_map_obstacles(m)).total_free() for m in MAPS}

ms = pickle.load(open("traces/impact_none.pkl", "rb"))["missions"]
D = {(m["map"], m["n"], m["cond"], m["iter"]): m for m in ms}
ITERS = sorted({m["iter"] for m in ms})


def ratio_ci(keys_att, keys_base, field, B=2000, seed=1):
    """Percent change sum(att)/sum(base)-1 with a bootstrap over iterations (paired by seed)."""
    by_it = collections.defaultdict(lambda: [0.0, 0.0])
    for ka, kb in zip(keys_att, keys_base):
        by_it[ka[3]][0] += D[ka][field]; by_it[ka[3]][1] += D[kb][field]
    its = list(by_it)
    est = sum(by_it[i][0] for i in its) / sum(by_it[i][1] for i in its) - 1
    rng = random.Random(seed); bs = []
    for _ in range(B):
        smp = [rng.choice(its) for _ in its]
        a = sum(by_it[i][0] for i in smp); b = sum(by_it[i][1] for i in smp)
        bs.append(a / b - 1 if b else 0)
    bs.sort()
    return 100 * est, 100 * bs[int(.025 * B)], 100 * bs[int(.975 * B)]


def keys(mp, sizes, cond):
    return [(mp, n, cond, i) for n in sizes for i in ITERS]


def mean(field, mp, sizes, cond):
    return st.mean(D[k][field] for k in keys(mp, sizes, cond))


print("free cells:", FREE)
print("coverage efficiency min:", min(m["cov_eff"] for m in ms), " missions:", len(ms))

# ---------------------------------------------------------------- redundancy, collisions, completion (sizes 5-50)
rows = []
print("\nRedundant visits, sizes 5-50 (mean per mission; change vs baseline, 95% CI over seeds)")
for mp in MAPS + ["all"]:
    mps = MAPS if mp == "all" else [mp]
    kb = [k for x in mps for k in keys(x, BIG, "baseline")]
    out = [mp, st.mean(D[k]["redundant"] for k in kb)]
    for c in ("sla", "bla"):
        ka = [k for x in mps for k in keys(x, BIG, c)]
        e, lo, hi = ratio_ci(ka, kb, "redundant")
        out += [st.mean(D[k]["redundant"] for k in ka), e, lo, hi]
    rows.append(out)
    print(f"  {mp:7} base {out[1]:6.1f} | SLA {out[2]:6.1f} {out[3]:+6.1f}% [{out[4]:+.1f},{out[5]:+.1f}] | BLA {out[6]:6.1f} {out[7]:+6.1f}% [{out[8]:+.1f},{out[9]:+.1f}]")

print("\nCollisions per mission and completion step, sizes 5-50 (change vs baseline, 95% CI)")
crow = {}
for field in ("collisions", "completion"):
    for mp in MAPS + ["all"]:
        mps = MAPS if mp == "all" else [mp]
        kb = [k for x in mps for k in keys(x, BIG, "baseline")]
        res = [st.mean(D[k][field] for k in kb)]
        for c in ("sla", "bla"):
            ka = [k for x in mps for k in keys(x, BIG, c)]
            res += list(ratio_ci(ka, kb, field))
        crow[(field, mp)] = res
        print(f"  {field:10} {mp:7} base {res[0]:7.1f} | SLA {res[1]:+6.1f}% [{res[2]:+.1f},{res[3]:+.1f}] | BLA {res[4]:+6.1f}% [{res[5]:+.1f},{res[6]:+.1f}]")

print("\nBaseline completion step by map (mean over sizes 5-50):", {mp: round(mean("completion", mp, BIG, "baseline"), 1) for mp in MAPS})

# ---------------------------------------------------------------- normalized attacker coverage
print("\nAttacker coverage: cells per attacker, fair share |F|/m, ratio to fair share, ratio to mean legitimate coverage")
norm = {}
for c in ("sla", "bla"):
    for mp in MAPS:
        for n in BIG + SMALL:
            ks = [(mp, n, c, i) for i in ITERS]
            cov = st.mean(D[k]["mal_cov"] for k in ks)
            leg = st.mean(D[k]["legit_cov"] for k in ks)
            bl = st.mean(D[(mp, n, "baseline", i)]["legit_cov"] for i in ITERS)
            norm[(c, mp, n)] = dict(cov=cov, fair=FREE[mp] / n, r_fair=cov / (FREE[mp] / n), r_leg=st.mean(D[k]["mal_cov"] / D[k]["legit_cov"] for k in ks),
                                    total=st.mean(D[k]["mal_cov"] * D[k]["n_att"] for k in ks), leg=leg, base_leg=bl)
    for n in (5, 10, 20, 50):
        v = [norm[(c, mp, n)] for mp in MAPS]
        print(f"  {c:4} m={n:2}: cells {min(x['cov'] for x in v):5.1f}-{max(x['cov'] for x in v):5.1f}  fair {min(x['fair'] for x in v):5.1f}-{max(x['fair'] for x in v):5.1f}"
              f"  /fair {min(x['r_fair'] for x in v):4.2f}-{max(x['r_fair'] for x in v):4.2f}  /legit {min(x['r_leg'] for x in v):4.2f}-{max(x['r_leg'] for x in v):4.2f}"
              f"  total {min(x['total'] for x in v):5.1f}-{max(x['total'] for x in v):5.1f}")
for c in ("sla", "bla"):
    rl = [norm[(c, mp, n)]["r_leg"] for mp in MAPS for n in BIG]
    rf = [norm[(c, mp, n)]["r_fair"] for mp in MAPS for n in BIG]
    print(f"  {c}: attacker/legit ratio over sizes 5-50 and maps: mean {st.mean(rl):.2f}, range {min(rl):.2f}-{max(rl):.2f};  attacker/fair share: mean {st.mean(rf):.2f}, range {min(rf):.2f}-{max(rf):.2f}")
for c in ("sla", "bla"):
    for mp in MAPS:
        a, b = norm[(c, mp, 5)]["total"], norm[(c, mp, 50)]["total"]
        print(f"  total attacker footprint {c} {mp}: m=5 {a:.1f} -> m=50 {b:.1f} ({100*(1-b/a):.1f}% drop); attacker share of free cells {100*a/FREE[mp]:.1f}% -> {100*b/FREE[mp]:.1f}%")

# ---------------------------------------------------------------- small teams
print("\nSmall teams (means over 5 layouts and 25 seeds)")
small = []
for n in SMALL:
    r = [n, 1 if n < 11 else 2]
    for c in ("sla", "bla"):
        r.append(st.mean(norm[(c, mp, n)]["cov"] for mp in MAPS))
    for c in ("sla", "bla"):
        kb = [k for mp in MAPS for k in keys(mp, [n], "baseline")]; ka = [k for mp in MAPS for k in keys(mp, [n], c)]
        r.append(ratio_ci(ka, kb, "redundant"))
    for c in ("sla", "bla"):
        kb = [k for mp in MAPS for k in keys(mp, [n], "baseline")]; ka = [k for mp in MAPS for k in keys(mp, [n], c)]
        r.append(ratio_ci(ka, kb, "collisions"))
    small.append(r)
    print(f"  m={n:2} att={r[1]} cov/att SLA {r[2]:.1f} BLA {r[3]:.1f} | redundant SLA {r[4][0]:+.0f}% [{r[4][1]:+.0f},{r[4][2]:+.0f}] BLA {r[5][0]:+.0f}% [{r[5][1]:+.0f},{r[5][2]:+.0f}]"
          f" | collisions SLA {r[6][0]:+.0f}% BLA {r[7][0]:+.0f}%")
print("  collisions in every mission > 0:", sum(m["collisions"] > 0 for m in ms), "/", len(ms))

# ---------------------------------------------------------------- LaTeX tables
with open("study_results/impact_tables.tex", "w") as f:
    f.write("% redundancy table (sizes 5-50)\n")
    for r in rows:
        name = "All layouts" if r[0] == "all" else r[0].capitalize()
        f.write(f"{name} & {r[1]:.1f} & {r[2]:.1f} ({r[3]:+.1f}\\%, {r[4]:+.0f} to {r[5]:+.0f}) & {r[6]:.1f} ({r[7]:+.1f}\\%, {r[8]:+.0f} to {r[9]:+.0f}) \\\\\n")
    f.write("% small teams\n")
    for r in small:
        f.write(f"{r[0]} & {r[1]} & {r[2]:.1f} & {r[3]:.1f} & ${r[4][0]:+.0f}\\%$ & ${r[5][0]:+.0f}\\%$ & ${r[6][0]:+.0f}\\%$ & ${r[7][0]:+.0f}\\%$ \\\\\n")
    f.write("% collisions/completion (all layouts, sizes 5-50)\n")
    for fld in ("collisions", "completion"):
        r = crow[(fld, "all")]
        f.write(f"{fld} & {r[0]:.1f} & {r[1]:+.1f} [{r[2]:+.1f},{r[3]:+.1f}] & {r[4]:+.1f} [{r[5]:+.1f},{r[6]:+.1f}] \\\\\n")

# ---------------------------------------------------------------- figures (grayscale)
plt.rcParams.update({"font.family": "serif", "font.size": 9, "axes.titlesize": 9.5, "axes.labelsize": 9,
                     "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8.5, "lines.markersize": 4})
# Canvas sizes match the printed width (IEEE text width 7.16 in, column width 3.5 in), so fonts print at ~8-9 pt.
MK = {"sla": "o", "bla": "s"}; LS = {"sla": "-", "bla": "--"}
LBL = {"sla": "SLA", "bla": "BLA", "baseline": "Baseline"}
map_ls = {"tunnel": "-", "indoor": "--", "garage": ":", "campus": "-.", "forest": (0, (3, 1, 1, 1))}
map_mk = {"tunnel": "o", "indoor": "D", "garage": "s", "campus": "v", "forest": "^"}
SZ = sorted(BIG + SMALL)


def five_panel():
    fig, axes = plt.subplots(2, 3, figsize=(7.1, 4.7), sharey=True)
    axes = axes.flatten(); axes[-1].axis("off")
    return fig, axes[:5]


fig, axes = five_panel()
for ax, mp in zip(axes, MAPS):
    for c in ("sla", "bla"):
        ax.plot(SZ, [norm[(c, mp, n)]["cov"] for n in SZ], marker=MK[c], ls=LS[c], color="black", mfc="white", ms=4.5, lw=1.2, label=LBL[c])
    ax.plot(SZ, [FREE[mp] / n for n in SZ], color="0.55", lw=1.0, ls=":", label="Fair share $|F|/m$")
    ax.set_title(mp.capitalize()); ax.set_xlabel("Team size $m$"); ax.grid(True, ls=":", lw=0.5, color="0.7")
axes[0].set_ylabel("Cells per attacker"); axes[3].set_ylabel("Cells per attacker")
h, l = axes[0].get_legend_handles_labels(); fig.legend(h, l, loc="center", bbox_to_anchor=(0.835, 0.27), frameon=False)
fig.tight_layout(); fig.savefig(f"{OUT}/fig1.png", dpi=300); plt.close(fig)

fig, ax = plt.subplots(figsize=(3.5, 2.7))
for mp in MAPS:
    ax.plot(SZ, [st.mean(D[(mp, n, "baseline", i)]["completion"] for i in ITERS) for n in SZ], marker=map_mk[mp], ls=map_ls[mp], color="black", mfc="white", ms=4.5, lw=1.2, label=mp.capitalize())
ax.set_xlabel("Team size $m$"); ax.set_ylabel("Baseline completion step"); ax.grid(True, ls=":", lw=0.5, color="0.7"); ax.legend(frameon=False, ncol=2, fontsize=7.5)
fig.tight_layout(); fig.savefig(f"{OUT}/fig2.png", dpi=300); plt.close(fig)

fig, axes = five_panel()
MK3 = {"baseline": "^", "sla": "o", "bla": "s"}; LS3 = {"baseline": ":", "sla": "-", "bla": "--"}
for ax, mp in zip(axes, MAPS):
    for c in ("baseline", "sla", "bla"):
        mu = [st.mean(D[(mp, n, c, i)]["legit_cov"] for i in ITERS) for n in SZ]
        sd = [st.pstdev([D[(mp, n, c, i)]["legit_cov"] for i in ITERS]) for n in SZ]
        ax.errorbar(SZ, mu, yerr=sd, marker=MK3[c], ls=LS3[c], color="black", mfc="white", ms=4, lw=1.1, capsize=2, elinewidth=0.6,
                    label=LBL[c])
    ax.set_title(mp.capitalize()); ax.set_xlabel("Team size $m$"); ax.grid(True, ls=":", lw=0.5, color="0.7")
axes[0].set_ylabel("Coverage per\nlegitimate robot (cells)"); axes[3].set_ylabel("Coverage per\nlegitimate robot (cells)")
h, l = axes[0].get_legend_handles_labels(); fig.legend(h, l, loc="center", bbox_to_anchor=(0.835, 0.27), frameon=False)
fig.tight_layout(); fig.savefig(f"{OUT}/fig3.png", dpi=300); plt.close(fig)

fig, axs = plt.subplots(1, 2, figsize=(7.1, 3.0), sharey=True)
for ax, c in zip(axs, ("sla", "bla")):
    for mp in MAPS:
        ax.plot(SZ, [norm[(c, mp, n)]["r_leg"] for n in SZ], marker=map_mk[mp], ls=map_ls[mp], color="black", mfc="white", ms=4.5, lw=1.2, label=mp.capitalize())
    ax.axhline(1.0, color="0.5", lw=0.8)
    ax.set_title(LBL[c]); ax.set_xlabel("Team size $m$"); ax.grid(True, ls=":", lw=0.5, color="0.7")
axs[0].set_ylabel("Attacker coverage / mean\nlegitimate coverage"); axs[0].legend(frameon=False, ncol=2)
fig.tight_layout(); fig.savefig(f"{OUT}/fig4.png", dpi=300); plt.close(fig)
print("\nwrote figures and study_results/impact_tables.tex")
