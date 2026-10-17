#!/usr/bin/env python3
"""
Score the live M-TARE traces with every study detector (parameters tuned in simulation, never on live data).

  python3 live_main_analysis.py --data-dir sweep_data live_runs/live_main.csv [--jitter 0.2]

Delay = recv_time - stamp (s). Effective attacker: mean delay > 0.5 s (defined from the traffic, not a detector).
Mission correct: attack-free -> nothing flagged; attack -> every effective attacker flagged and no non-attacker flagged.
"""
import argparse, collections, csv, json, math, random, statistics as st, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import replay_live_traces as R
import study_detectors as sd

tuned = json.load(open(HERE.parent / "study_results" / "tuned.json"))
import pickle
sd.MODELS.update(pickle.load(open(HERE.parent / "study_results" / "tuned.json.models.pkl", "rb")))
DETS = [("deployed_monitor", None, None), ("fixed_orig", "fixed", sd.ORIG_FIXED)] + [(n, n, v["params"]) for n, v in tuned.items()]
NAMES = {"deployed_monitor": "Deployed monitor", "fixed_orig": "Fixed thresholds (original)", "fixed": "Fixed thresholds (retuned)",
         "calibrated": "Calibrated (persistence rule)", "cusum_pop": "CUSUM, population ref.", "ewma_pop": "EWMA, population ref.",
         "mad_pop": "MAD test, population ref.", "cusum_self": "CUSUM, own-stream ref.", "ewma_self": "EWMA, own-stream ref.",
         "mad_self": "MAD test, own-stream ref.",
         "etd_style": "ETD-style (one-class + K-Means)", "hotd_style": "HOTD-style (supervised)",
         "iforest": "Isolation Forest (attack-free training)", "bocpd_self": "Bayesian change-point, own-stream ref.", "bocpd_pop": "Bayesian change-point, population ref.",
         "maxage": "Message-age (freshness) check", "etd_pop": "ETD-style, population-normalised features",
         "hotd_pop": "HOTD-style, population-normalised features", "iforest_pop": "Isolation Forest, population-normalised features"}
ORDER = ["deployed_monitor", "fixed_orig", "fixed", "maxage", "cusum_self", "ewma_self", "mad_self", "bocpd_self", "etd_style", "hotd_style", "iforest", "etd_pop", "hotd_pop", "iforest_pop", "mad_pop", "cusum_pop", "ewma_pop", "bocpd_pop", "calibrated"]


def wilson(k, n, z=1.96):
    if n == 0: return (float("nan"),) * 2
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def parse_atts(v):
    v = str(v).replace("[", "").replace("]", "")
    return {int(float(x)) for x in v.split(",") if x.strip() not in ("", "None")}


def flags(name, params, trace):
    if name is None: return R.replay_live_monitor(trace)
    det = sd.make(name, **params)
    for recv, rid, seq, stamp in trace: det.observe(rid, seq, stamp, recv)
    return det.first_flag


def analyze(data_dir, sweeps, jitter=0.0, seed=0):
    rng = random.Random(seed); recs = []
    for sp in sweeps:
        for row in csv.DictReader(open(sp)):
            env, n, cond, it = row["environment"], int(row["team_size"]), row["condition"], row["iteration"]
            tp = Path(data_dir) / (f"{env}_{n}_{cond}_{it}" + (f"_{row['netem']}" if row.get("netem") else "") + ".csv")
            if not tp.exists(): continue
            tr = R.load_trace(tp)
            if not tr: continue
            if jitter > 0: tr = sorted([(rc + rng.uniform(0, jitter), rid, sq, s_) for rc, rid, sq, s_ in tr])
            atts = parse_atts(row.get("attacker_robot")) if cond != "baseline" else set()
            d = collections.defaultdict(list); tfirst = {}
            for rc, rid, sq, s_ in tr: d[rid].append(rc - s_); tfirst.setdefault(rid, rc)
            hm = st.median([st.mean(v) for k, v in d.items() if k not in atts] or [0.0])
            eff = {a for a in atts if a in d and st.mean(d[a]) - hm > 0.5}   # effective: clearly later than the honest senders'
            for label, name, params in DETS:
                fl = flags(name, params, tr)
                fp = {r for r in fl if r not in atts}
                miss = eff - set(fl)
                recs.append(dict(det=label, env=env, n=n, cond=cond, n_eff=len(eff), n_att=len(atts), found=len(eff & set(fl)),
                                 fp=len(fp), correct=(len(fp) == 0 and not miss) if (cond != "baseline" and eff) or cond == "baseline" else None,
                                 lat=[fl[a] - tfirst[a] for a in eff if a in fl]))
    return recs


def report(recs, title):
    print(title)
    print(f"{'detector':30}{'missions':>9}{'correct%':>9}{'[95% CI]':>15}{'eff.found':>11}{'SLA':>9}{'BLA':>9}{'baseFP':>8}{'atkFP':>8}{'lat(s)':>8}")
    for det in ORDER:
        rs = [r for r in recs if r["det"] == det and r["correct"] is not None]
        if not rs: continue
        k = sum(r["correct"] for r in rs); lo, hi = wilson(k, len(rs))
        atk = [r for r in rs if r["cond"] != "baseline"]; base = [r for r in rs if r["cond"] == "baseline"]
        e = sum(r["n_eff"] for r in atk); f = sum(r["found"] for r in atk)
        by = {c: (sum(r["found"] for r in atk if r["cond"] == c), sum(r["n_eff"] for r in atk if r["cond"] == c)) for c in ("sla", "bla")}
        lats = [x for r in atk for x in r["lat"]]
        print(f"{NAMES[det]:30}{len(rs):>9}{100*k/len(rs):9.1f}  [{100*lo:5.1f},{100*hi:5.1f}]{f'{f}/{e}':>11}{f'{by['sla'][0]}/{by['sla'][1]}':>9}{f'{by['bla'][0]}/{by['bla'][1]}':>9}"
              f"{f'{sum(r['fp']>0 for r in base)}/{len(base)}':>8}{f'{sum(r['fp']>0 for r in atk)}/{len(atk)}':>8}{(st.mean(lats) if lats else float('nan')):8.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sweeps", nargs="+"); ap.add_argument("--data-dir", default=str(HERE / "sweep_data"))
    ap.add_argument("--jitter", type=float, default=0.0); ap.add_argument("--by", choices=["n", "env"], default=None)
    a = ap.parse_args()
    recs = analyze(a.data_dir, a.sweeps, a.jitter)
    report(recs, f"== all missions (extra synthetic jitter U(0,{a.jitter}) s) ==")
    if a.by:
        for v in sorted({r[a.by] for r in recs}):
            report([r for r in recs if r[a.by] == v], f"\n-- {a.by} = {v} --")
