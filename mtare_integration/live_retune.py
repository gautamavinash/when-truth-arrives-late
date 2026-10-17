#!/usr/bin/env python3
"""
Live detection with detectors retuned on live data (answers: are the simulation-tuned absolute thresholds unfair on a
channel measured in seconds?).

Split of the 225 live position-stream missions: iteration 0 of every (environment, team size, condition) is the live
tuning set (75 missions); iterations 1 and 2 are the test set (150 missions). Every detector is retuned on the tuning
set with the same protocol as in simulation (same random-search budget and seed; keep the configuration with the
highest tuning accuracy, ties broken by fewer false flags); the learned baselines are refitted on the tuning set.
Both the simulation-tuned (frozen) and the live-retuned configurations are scored on the same test missions.

Labels: effective attackers (mean delay more than 0.5 s above the median honest sender, a traffic definition) must be
found; flagging a non-effective attacker is neither a hit nor a false flag; attack missions without an effective
attacker are excluded, as in the main live analysis.

  python3 live_retune.py live_runs/live_main.csv > live_runs/live_retune.txt
"""
import collections, csv, json, math, pickle, statistics as st, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import replay_live_traces as R
import study_detectors as sd
import study_ml
from evaluate_detectors import draw_configs, wilson
from live_main_analysis import NAMES, parse_atts


def load(sweep, data_dir=HERE / "sweep_data", all_attackers=False):
    out = []
    for row in csv.DictReader(open(sweep)):
        env, n, cond, it = row["environment"], int(row["team_size"]), row["condition"], int(row["iteration"])
        tp = Path(data_dir) / f"{env}_{n}_{cond}_{it}.csv"
        if not tp.exists():
            continue
        tr = R.load_trace(tp)
        if not tr:
            continue
        atts = parse_atts(row.get("attacker_robot")) if cond != "baseline" else set()
        d = collections.defaultdict(list)
        for rc, rid, sq, s_ in tr:
            d[rid].append(rc - s_)
        hm = st.median([st.mean(v) for k, v in d.items() if k not in atts] or [0.0])
        eff = {a for a in atts if a in d and st.mean(d[a]) - hm > 0.5}
        if all_attackers:
            eff = {a for a in atts if a in d}
        if cond != "baseline" and not eff:
            continue
        out.append(dict(env=env, n=n, cond=cond, iter=it, adv=sorted(eff), atts=sorted(atts),
                        trace=[(rc, rid, sq, s_, rc) for rc, rid, sq, s_ in tr]))
    return out


def score(name, params, m):
    if name is None:
        fl = R.replay_live_monitor([(t[0], t[1], t[2], t[3]) for t in m["trace"]])
    else:
        det = sd.make(name, **params)
        for (_t, rid, sq, gen, rec) in m["trace"]:
            det.observe(rid, sq, gen, rec)
        fl = det.first_flag
    fp = {r for r in fl if r not in set(m["atts"])}
    found = set(m["adv"]) & set(fl)
    return dict(correct=(not fp and len(found) == len(m["adv"])), fp=len(fp), found=len(found), n_eff=len(m["adv"]))


_TUN = []


def _cfg(a):
    name, p = a
    rs = [score(name, p, m) for m in _TUN]
    return name, p, (sum(r["correct"] for r in rs) / len(rs), -sum(r["fp"] > 0 for r in rs))


def tune_all(names, missions, workers=24):
    """Parallel equal-budget search over every detector's configurations on the live tuning set."""
    global _TUN
    _TUN = missions
    from multiprocessing import Pool
    tasks = [(n, p) for n in names for p in draw_configs(n)]
    best = {}
    with Pool(workers) as pool:
        for name, p, key in pool.imap_unordered(_cfg, tasks, chunksize=1):
            if name not in best or key > best[name][0]:
                best[name] = (key, p)
    return {n: (b[1], b[0][0]) for n, b in best.items()}


def report(label, rows):
    k = sum(r["correct"] for r in rows); lo, hi = wilson(k, len(rows))
    base = [r for r in rows if r["cond"] == "baseline"]
    by = {c: (sum(r["found"] for r in rows if r["cond"] == c), sum(r["n_eff"] for r in rows if r["cond"] == c)) for c in ("sla", "bla")}
    return (f"{label:44}{100*k/len(rows):7.1f} [{100*lo:5.1f},{100*hi:5.1f}]  SLA {by['sla'][0]:>3}/{by['sla'][1]:<3} "
            f"BLA {by['bla'][0]:>3}/{by['bla'][1]:<3} attack-free FP {sum(r['fp'] > 0 for r in base):>2}/{len(base)}")


def main():
    ms = load(sys.argv[1])
    tun = [m for m in ms if m["iter"] == 0]
    test = [m for m in ms if m["iter"] != 0]
    print(f"live tuning missions {len(tun)}, test missions {len(test)}")
    tuned = json.load(open(HERE.parent / "study_results" / "tuned.json"))
    sim_models = pickle.load(open(HERE.parent / "study_results" / "tuned.json.models.pkl", "rb"))
    live_models = study_ml.fit_models(tun)
    sd.MODELS.clear(); sd.MODELS.update(live_models)
    out = {}
    dets = ["fixed"] + [n for n in tuned if n != "fixed"]
    best = tune_all(dets, tun)
    print("retuned on live tuning set", flush=True)
    print(f"\n{'detector':44}{'acc%':>7} [95% CI]       hits / effective attackers, false flags   (test missions)")
    sd.MODELS.clear(); sd.MODELS.update(sim_models)
    print(report("Deployed monitor (as deployed)", [dict(cond=m["cond"], **score(None, None, m)) for m in test]))
    print(report("Fixed thresholds (original)", [dict(cond=m["cond"], **score("fixed", sd.ORIG_FIXED, m)) for m in test]))
    for name in dets:
        sd.MODELS.clear(); sd.MODELS.update(sim_models)
        frozen = [dict(cond=m["cond"], **score(name, tuned[name]["params"], m)) for m in test]
        sd.MODELS.clear(); sd.MODELS.update(live_models)
        p, tacc = best[name]
        retuned = [dict(cond=m["cond"], **score(name, p, m)) for m in test]
        out[name] = dict(params=p, tune_acc=tacc,
                         frozen=sum(r["correct"] for r in frozen) / len(frozen),
                         retuned=sum(r["correct"] for r in retuned) / len(retuned))
        print(report(NAMES.get(name, name) + " [sim-tuned]", frozen))
        print(report(NAMES.get(name, name) + " [live-retuned]", retuned) + f"   {p}", flush=True)
    json.dump(out, open(HERE / "live_runs" / "live_retune.json", "w"), indent=1)
    # sensitivity of the frozen (simulation-tuned) results to the effective-attacker filter: require all attackers
    allm = load(sys.argv[1], all_attackers=True)
    sd.MODELS.clear(); sd.MODELS.update(sim_models)
    print(f"\nAll {len(allm)} missions, every attacker (effective or not) must be found; simulation-tuned parameters")
    for name in dets:
        print(report(NAMES.get(name, name), [dict(cond=m["cond"], **score(name, tuned[name]["params"], m)) for m in allm]))


if __name__ == "__main__":
    main()
