#!/usr/bin/env python3
"""Replay live traces through every study detector (parameters tuned in simulation, not on live data).
Delay = recv_time - stamp in seconds (treated as the same unit as simulation steps). Sender 'first message'
time is the reference for latency. Effective attack: attacker mean delay > 0.5 s."""
import csv, json, statistics as st, sys, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import replay_live_traces as R
import study_detectors as sd

tuned = json.load(open(HERE.parent / "study_results" / "tuned.json"))
DETS = [("deployed_monitor", None, None), ("fixed_orig", "fixed", sd.ORIG_FIXED)] + [(n, n, v["params"]) for n, v in tuned.items()]

def run(name, params, trace):
    det = sd.make(name, **params)
    for recv, rid, seq, stamp in trace:
        det.observe(rid, seq, stamp, recv)
    return det.first_flag

def main(sweeps, jitter=0.0, seed=0):
    import random
    rng = random.Random(seed)
    out = collections.defaultdict(list)
    for sp in sweeps:
        for row in csv.DictReader(open(sp)):
            env, n, cond, it = row["environment"], int(row["team_size"]), row["condition"], row["iteration"]
            tp = HERE / "sweep_data" / f"{env}_{n}_{cond}_{it}.csv"
            if not tp.exists(): continue
            tr = R.load_trace(tp)
            if not tr: continue
            if jitter > 0:   # synthetic extra jitter on the receive time (seconds), order preserved by re-sorting
                tr = sorted([(rc + rng.uniform(0, jitter), rid, sq, sp_) for rc, rid, sq, sp_ in tr])
            atts = set() if cond == "baseline" else {int(float(x)) for x in str(row.get("attacker_robots") or row["attacker_robot"]).replace("[", "").replace("]", "").split(",") if x.strip() != ""}
            d = collections.defaultdict(list)
            tfirst = {}
            for rc, rid, sq, sp_ in tr:
                d[rid].append(rc - sp_); tfirst.setdefault(rid, rc)
            eff = {a for a in atts if a in d and st.mean(d[a]) > 0.5}
            for label, name, params in DETS:
                fl = R.replay_live_monitor(tr) if name is None else run(name, params, tr)
                fp = [r for r in fl if r not in atts]
                out[label].append(dict(cond=cond, atts=atts, eff=eff, flagged=set(fl), fp=len(fp),
                                       lat=[fl[a] - tfirst[a] for a in eff if a in fl]))
    return out

def table(out, title):
    print(title)
    print(f"{'detector':17}{'eff.attackers found':>20}{'SLA':>8}{'BLA':>8}{'baseline FP':>13}{'attack FP':>11}{'lat(s)':>8}")
    for label, recs in out.items():
        base = [r for r in recs if r["cond"] == "baseline"]; atk = [r for r in recs if r["cond"] != "baseline"]
        e = sum(len(r["eff"]) for r in atk); f = sum(len(r["eff"] & r["flagged"]) for r in atk)
        def by(c):
            rr = [r for r in atk if r["cond"] == c]; return f"{sum(len(r['eff'] & r['flagged']) for r in rr)}/{sum(len(r['eff']) for r in rr)}"
        lats = [x for r in atk for x in r["lat"]]
        print(f"{label:17}{f'{f}/{e}':>20}{by('sla'):>8}{by('bla'):>8}{f'{sum(r['fp']>0 for r in base)}/{len(base)}':>13}{f'{sum(r['fp']>0 for r in atk)}/{len(atk)}':>11}{(st.mean(lats) if lats else float('nan')):>8.1f}")

if __name__ == "__main__":
    sweeps = [Path(p) for p in sys.argv[1:]]
    table(main(sweeps), "== live traces as recorded ==")
    for j in (0.05, 0.2, 0.5):
        table(main(sweeps, jitter=j), f"\n== with synthetic extra jitter U(0,{j}) s on every receive time ==")
