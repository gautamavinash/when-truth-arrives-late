"""Order-effect control: iterations 15-20 (4 robots, tunnel+garage), conditions in random order incl. a second baseline."""
import sys, random, statistics as st
from pathlib import Path
import numpy as np
sys.path.insert(0, '.')
import analyze_planner_final as AF
M = AF.load("planner_runs", 360.0)
rows = []
for (e, n, i, c), v in M.items():
    if n != 4 or i < 15: continue
    of = Path("planner_runs") / f"{e}_{n}_{c}_{i}" / "ORDER"
    rows.append(dict(env=e, it=i, cond=c, pos=int(of.read_text()) if of.exists() else None, cov=v["union_cells"], red=v["redundancy"], valid=v["valid"]))
bad = [(r["env"], r["it"], r["cond"]) for r in rows if not r["valid"]]
print(len(rows), "control missions; invalid:", bad)
# drop whole iterations with any invalid mission (keeps the design balanced)
badit = {(e, i) for e, i, c in bad}
rows = [r for r in rows if (r["env"], r["it"]) not in badit]
its = sorted({(r["env"], r["it"]) for r in rows})
print("complete iterations used:", len(its), its, "\n")
idx = {(r["env"], r["it"], r["cond"]): r for r in rows}

def boot_mean(d, B=5000, seed=3):
    rng = random.Random(seed); m = sorted(st.mean(rng.choice(d) for _ in d) for _ in range(B)); return m[int(.025*B)], m[int(.975*B)]

# 1) second baseline vs first baseline (no attack either way)
d = [idx[(e, i, "baseline2")]["cov"] / idx[(e, i, "baseline")]["cov"] - 1 for e, i in its]
print("baseline2 vs baseline (both no attack): mean %+.1f%%, |diff| median %.1f%%, range %+.1f..%+.1f%%" % (100*st.mean(d), 100*st.median([abs(x) for x in d]), 100*min(d), 100*max(d)))
# later-run minus earlier-run baseline
dl = []
for e, i in its:
    a, b = idx[(e, i, "baseline")], idx[(e, i, "baseline2")]
    later, earlier = (a, b) if a["pos"] > b["pos"] else (b, a)
    dl.append(later["cov"] / earlier["cov"] - 1)
lo, hi = boot_mean(dl)
print("later-run baseline vs earlier-run baseline: mean %+.1f%% [%+.0f, %+.0f], later higher in %d of %d" % (100*st.mean(dl), 100*lo, 100*hi, sum(x > 0 for x in dl), len(dl)))

# 2) regression: log(cov) ~ iteration FE + condition + position (per-step), bootstrap over iterations
def fit(sample_its):
    X, y = [], []
    conds = ["sla", "bla"]
    for k, (e, i) in enumerate(sample_its):
        for c in ("baseline", "baseline2", "sla", "bla"):
            r = idx[(e, i, c)]
            fe = [0.0] * len(sample_its); fe[k] = 1.0
            X.append(fe + [1.0 if c == cc else 0.0 for cc in conds] + [float(r["pos"])]); y.append(np.log(r["cov"]))
    beta, *_ = np.linalg.lstsq(np.array(X), np.array(y), rcond=None)
    return beta[-3:]   # sla, bla, position
est = fit(its)
rng = random.Random(7); bs = []
for _ in range(2000):
    s = [its[rng.randrange(len(its))] for _ in its]
    try: bs.append(fit(s))
    except Exception: pass
bs = np.array(bs)
names = ["SLA effect", "BLA effect", "position effect (per later slot)"]
print("\nRegression on log(coverage), iteration fixed effects, both no-attack runs as reference:")
for j, nm in enumerate(names):
    lo, hi = np.percentile(bs[:, j], [2.5, 97.5])
    print(f"  {nm:34} {100*(np.exp(est[j])-1):+6.1f}%   95% bootstrap [{100*(np.exp(lo)-1):+.0f}, {100*(np.exp(hi)-1):+.0f}]")

# 3) per environment, attack vs mean of the two baselines
print("\nAttack vs mean of the two no-attack runs (randomized order):")
for env in ("tunnel", "garage", None):
    for c in ("sla", "bla"):
        d = [idx[(e, i, c)]["cov"] / st.mean([idx[(e, i, "baseline")]["cov"], idx[(e, i, "baseline2")]["cov"]]) - 1 for e, i in its if env is None or e == env]
        if len(d) >= 3:
            lo, hi = boot_mean(d)
            print(f"  {env or 'both':7}{c:5} coverage {100*st.mean(d):+6.1f}% [{100*lo:+.0f}, {100*hi:+.0f}]  lower in {sum(x<0 for x in d)}/{len(d)}  sign p={AF.sign_p(d):.3f}")
