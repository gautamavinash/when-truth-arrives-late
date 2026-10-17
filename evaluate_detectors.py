#!/usr/bin/env python3
"""
Fair detector comparison on observer traces.

tune : for every detector, draw SEARCH_N random configurations (same RNG seed and budget for
       all detectors), score each on held-out traces at several noise levels, and keep the one
       with the best worst-case mission accuracy across noise levels.
test : evaluate the frozen configurations (plus the original fixed-threshold detector) on the
       standard traces, with Wilson confidence intervals and exact McNemar tests.

Mission accuracy = share of missions classified exactly right: an attack-free mission raises no
flag; an attack mission flags every attacker and no honest robot. Flags are "ever flagged".

Usage:
  python3 evaluate_detectors.py tune --traces traces/ho_none.pkl traces/ho_light.pkl ... --out tuned.json
  python3 evaluate_detectors.py test --traces traces/std_none.pkl ... --params tuned.json --out results
"""
import argparse, csv, itertools, json, math, os, pickle, random, statistics as st, sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import study_detectors as sd

TRACESETS = []   # list of (tag, missions)  -- filled before forking workers


def load(paths):
    out = []
    for p in paths:
        d = pickle.load(open(p, "rb"))
        tag = os.path.splitext(os.path.basename(p))[0]
        out.append((tag, d["missions"]))
    return out


def run_mission(name, params, m):
    det = sd.make(name, **params)
    for (_t, sender, seq, gen, rec) in m["trace"]:
        det.observe(sender, seq, gen, rec)
    adv = set(m["adv"])
    flagged = set(det.first_flag)
    fp = len(flagged - adv)
    if m["cond"] == "baseline":
        return dict(correct=(len(flagged) == 0), recall=None, fp=fp, lat=[])
    hit = adv & flagged
    onset = m.get("onset", 0)
    return dict(correct=(len(hit) == len(adv) and fp == 0), recall=len(hit) / len(adv), fp=fp,
                lat=[det.first_flag[a] - onset for a in hit])


def eval_set(name, params, missions):
    res = [run_mission(name, params, m) for m in missions]
    return res


def acc(res):
    return sum(r["correct"] for r in res) / len(res)


def _task(args):
    name, idx, params, ts = args
    res = eval_set(name, params, TRACESETS[ts][1])
    return name, idx, ts, acc(res), sum(r["fp"] > 0 for r in res) / len(res)


def draw_configs(name, n=sd.SEARCH_N, seed=2026):
    rng = random.Random(seed)
    keys = sorted(sd.SPACE[name])
    seen, out = set(), []
    total = 1
    for k in keys:
        total *= len(sd.SPACE[name][k])
    n = min(n, total)
    while len(out) < n:
        cfg = tuple(rng.choice(sd.SPACE[name][k]) for k in keys)
        if cfg not in seen:
            seen.add(cfg)
            out.append(dict(zip(keys, cfg)))
    return out


def _m(v):
    return st.mean(v) if v else float("nan")


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def mcnemar_p(a_correct, b_correct):
    """Exact two-sided McNemar test on paired mission correctness."""
    b = sum(x and not y for x, y in zip(a_correct, b_correct))
    c = sum((not x) and y for x, y in zip(a_correct, b_correct))
    n = b + c
    if n == 0:
        return 1.0, b, c
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p), b, c


def cmd_tune(a):
    global TRACESETS
    TRACESETS = load(a.traces)
    import study_ml
    sd.MODELS.update(study_ml.fit_models([m for _, ms in TRACESETS for m in ms]))
    pickle.dump(sd.MODELS, open(a.out + '.models.pkl', 'wb'))
    print('fitted ML baselines on', sd.MODELS['n_samples'], 'held-out sender-window samples (', sd.MODELS['n_pos'], 'attacker)', flush=True)
    tasks, cfgs = [], {}
    for name in sd.SPACE:
        cfgs[name] = draw_configs(name)
        for i, p in enumerate(cfgs[name]):
            for ts in range(len(TRACESETS)):
                tasks.append((name, i, p, ts))
    print(f"{len(tasks)} tasks ({sum(len(v) for v in cfgs.values())} configs x {len(TRACESETS)} trace sets, "
          f"{[len(m) for _, m in TRACESETS]} missions)", flush=True)
    scores = {}
    with Pool(a.workers) as pool:
        for k, (name, i, ts, ac, fpr) in enumerate(pool.imap_unordered(_task, tasks, chunksize=1), 1):
            scores.setdefault((name, i), {})[ts] = (ac, fpr)
            if k % 200 == 0:
                print(f"  {k}/{len(tasks)}", flush=True)
    best = {}
    log = []
    for name in sd.SPACE:
        ranked = []
        for i, p in enumerate(cfgs[name]):
            s = scores[(name, i)]
            accs = [s[t][0] for t in range(len(TRACESETS))]
            ranked.append((min(accs), st.mean(accs), -st.mean(s[t][1] for t in s), i))
        ranked.sort(reverse=True)
        w, mean_acc, _, i = ranked[0]
        best[name] = dict(params=cfgs[name][i], worst=w, mean=mean_acc,
                          per_set={TRACESETS[t][0]: scores[(name, i)][t][0] for t in range(len(TRACESETS))})
        log.append((name, w, mean_acc, cfgs[name][i]))
        print(f"{name:11} worst-case acc {w:.3f}  mean {mean_acc:.3f}  {cfgs[name][i]}", flush=True)
    json.dump(best, open(a.out, "w"), indent=1)


def cmd_test(a):
    global TRACESETS
    TRACESETS = load(a.traces)
    tuned = json.load(open(a.params))
    sd.MODELS.update(pickle.load(open(a.params + '.models.pkl', 'rb')))
    dets = [("fixed_orig", "fixed", sd.ORIG_FIXED)] + [(n, n, v["params"]) for n, v in tuned.items()]
    if getattr(a, "only", None):
        keep = set(a.only.split(","))
        dets = [d for d in dets if d[0] in keep]
    tasks = [(label, name, p, ts) for (label, name, p) in dets for ts in range(len(TRACESETS))]

    def worker_args(t):
        return t
    rows = []
    with Pool(a.workers) as pool:
        for label, ts, res in pool.imap_unordered(_test_task, tasks, chunksize=1):
            m = TRACESETS[ts][1]
            for mm, r in zip(m, res):
                rows.append(dict(detector=label, noise=TRACESETS[ts][0], map=mm["map"], n=mm["n"], cond=mm["cond"],
                                 iter=mm["iter"], correct=int(r["correct"]), recall=r["recall"], fp=r["fp"],
                                 lat=(st.mean(r["lat"]) if r["lat"] else None), nlat=len(r["lat"])))
    os.makedirs(os.path.dirname(os.path.abspath(a.out + "_missions.csv")), exist_ok=True)
    with open(a.out + "_missions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summarize(rows, a.out, [t for t, _ in TRACESETS], [d[0] for d in dets])


def _test_task(args):
    label, name, params, ts = args
    return label, ts, eval_set(name, params, TRACESETS[ts][1])


def summarize(rows, out, noises, dets):
    key = lambda r: (r["map"], r["n"], r["cond"], r["iter"])
    lines = []
    summ = []
    for nz in noises:
        R = {d: sorted([r for r in rows if r["detector"] == d and r["noise"] == nz], key=key) for d in dets}
        ref = [bool(r["correct"]) for r in R["calibrated"]] if "calibrated" in R else None
        for d in dets:
            rs = R[d]
            base = [r for r in rs if r["cond"] == "baseline"]
            atk = [r for r in rs if r["cond"] != "baseline"]
            k = sum(r["correct"] for r in rs)
            lo, hi = wilson(k, len(rs))
            p = mcnemar_p([bool(r["correct"]) for r in rs], ref)[0] if ref and d != "calibrated" else None
            lats = [r["lat"] for r in atk if r["lat"] is not None]
            row = dict(noise=nz, detector=d, missions=len(rs), accuracy=k / len(rs), acc_lo=lo, acc_hi=hi,
                       attack_recall=st.mean(r["recall"] for r in atk),
                       sla_acc=_m([r["correct"] for r in atk if r["cond"] == "sla"]),
                       bla_acc=_m([r["correct"] for r in atk if r["cond"] == "bla"]),
                       base_fp=sum(r["fp"] > 0 for r in base) / len(base),
                       atk_fp=sum(r["fp"] > 0 for r in atk) / len(atk),
                       lat_mean=(st.mean(lats) if lats else None), lat_median=(st.median(lats) if lats else None),
                       p_vs_calibrated=p)
            summ.append(row)
    with open(out + "_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summ[0].keys()))
        w.writeheader()
        w.writerows(summ)
    print(f"{'noise':14}{'detector':12}{'acc%':>6}{'[95% CI]':>15}{'recall%':>8}{'SLA%':>7}{'BLA%':>6}{'baseFP%':>8}{'atkFP%':>7}{'lat':>6}{'p(vs cal)':>10}")
    for r in summ:
        print(f"{r['noise']:14}{r['detector']:12}{100*r['accuracy']:6.1f}  [{100*r['acc_lo']:5.1f},{100*r['acc_hi']:5.1f}]"
              f"{100*r['attack_recall']:8.1f}{100*r['sla_acc']:7.1f}{100*r['bla_acc']:6.1f}{100*r['base_fp']:8.1f}"
              f"{100*r['atk_fp']:7.1f}{(r['lat_mean'] if r['lat_mean'] is not None else float('nan')):6.1f}"
              f"{(r['p_vs_calibrated'] if r['p_vs_calibrated'] is not None else float('nan')):10.3g}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tune", "test"])
    ap.add_argument("--traces", nargs="+", required=True)
    ap.add_argument("--params")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--only", default=None, help="comma-separated detector labels to evaluate")
    a = ap.parse_args()
    {"tune": cmd_tune, "test": cmd_test}[a.cmd](a)
