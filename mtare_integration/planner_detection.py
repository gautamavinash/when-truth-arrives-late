#!/usr/bin/env python3
"""
Detection on the planner's own cross-robot traffic (the stream whose delay changes exploration).

Input: planner_runs_logged/<env>_<n>_<cond>_<it>/bridge_rx_<r>.csv written by the instrumented bridges
(recv_time, sender, topic, seq, gen_time). Every honest robot is an observer of its own received stream, so this
experiment also exercises several receivers and the majority vote across them. Topics are scored separately:
exploration_info (visited cells, roadmap, plans) and position.

Detectors: the simulation-tuned configurations (study_results/tuned.json), never tuned on this traffic, plus the
deployed-monitor rule and the original fixed thresholds. Delay unit: seconds read as steps, as in the live study.

Per (mission, observer): correct when the attacker is flagged (attack missions) and no honest sender is flagged.
Per mission (team decision): a sender is confirmed when a majority of the honest observers flag it; correct when the
attacker is confirmed (attack missions) and no honest sender is confirmed.

  python3 planner_detection.py planner_runs_logged > planner_runs_logged/planner_detection.txt
"""
import collections, csv, json, pickle, statistics as st, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import replay_live_traces as R
import study_detectors as sd
from evaluate_detectors import wilson
from live_main_analysis import NAMES

ATTACKER = 1


def load_rx(path, topic):
    rows = []
    for r in csv.DictReader(open(path)):
        if r["topic"] != topic:
            continue
        rows.append((float(r["recv_time"]), int(r["sender"]), int(r["seq"]), float(r["gen_time"])))
    rows.sort()
    return rows


def flags(name, params, trace):
    if name is None:
        return R.replay_live_monitor(trace)
    det = sd.make(name, **params)
    for recv, rid, seq, gen in trace:
        det.observe(rid, seq, gen, recv)
    return det.first_flag


def main():
    root = HERE / sys.argv[1]
    tuned = json.load(open(HERE.parent / "study_results" / "tuned.json"))
    sd.MODELS.update(pickle.load(open(HERE.parent / "study_results" / "tuned.json.models.pkl", "rb")))
    dets = [("deployed_monitor", None, None), ("fixed_orig", "fixed", sd.ORIG_FIXED)] + [(n, n, v["params"]) for n, v in tuned.items()]
    missions = sorted(d for d in root.iterdir() if (d / "DONE").exists() and list(d.glob("bridge_rx_*.csv")))
    delays = collections.defaultdict(list)
    res = collections.defaultdict(list)          # (topic, det) -> per-observer records
    team = collections.defaultdict(list)         # (topic, det) -> per-mission records
    for md in missions:
        env, n, cond, it = md.name.split("_")
        n = int(n)
        attack = cond in ("sla", "bla")
        for topic in ("exploration_info", "position"):
            obs = {}
            for f in md.glob("bridge_rx_*.csv"):
                rid = int(f.stem.split("_")[-1])
                if attack and rid == ATTACKER:
                    continue                      # the compromised robot is not an observer
                tr = load_rx(f, topic)
                if tr:
                    obs[rid] = tr
                    for recv, s, _q, gen in tr:
                        delays[(topic, cond, "attacker" if (attack and s == ATTACKER) else "honest")].append(recv - gen)
            if not obs:
                continue
            for label, name, params in dets:
                votes = collections.Counter()
                for rid, tr in obs.items():
                    fl = flags(name, params, tr)
                    for s in fl:
                        votes[s] += 1
                    fp = [s for s in fl if not (attack and s == ATTACKER)]
                    hit = (ATTACKER in fl) if attack else None
                    res[(topic, label)].append(dict(cond=cond, env=env, n=n, correct=(not fp) and (hit is not False), fp=len(fp) > 0, hit=hit))
                conf = {s for s, v in votes.items() if v > len(obs) / 2}
                fp = [s for s in conf if not (attack and s == ATTACKER)]
                hit = (ATTACKER in conf) if attack else None
                team[(topic, label)].append(dict(cond=cond, env=env, n=n, correct=(not fp) and (hit is not False), fp=len(fp) > 0, hit=hit))
    print(f"missions: {len(missions)}  ({collections.Counter(m.name.split('_')[2] for m in missions)})")
    print("\nMeasured delay (s), by topic / condition / sender role: median, 99th percentile, max")
    for k in sorted(delays):
        v = sorted(delays[k])
        print(f"  {k[0]:17}{k[1]:9}{k[2]:9} n={len(v):6} median {st.median(v):8.4f}  p99 {v[int(.99*(len(v)-1))]:8.4f}  max {v[-1]:8.3f}")
    for topic in ("exploration_info", "position"):
        print(f"\n== topic {topic}: per observer (each honest robot) | team decision (majority of honest observers)")
        print(f"{'detector':40}{'obs acc%':>9}{'[95% CI]':>15}{'SLA hit':>10}{'BLA hit':>9}{'af FP':>8}  |{'team acc%':>10}{'SLA':>7}{'BLA':>7}{'af FP':>7}")
        for label, _n, _p in dets:
            rs, ts = res[(topic, label)], team[(topic, label)]
            if not rs:
                continue
            k = sum(r["correct"] for r in rs); lo, hi = wilson(k, len(rs))
            def hits(rr, c):
                x = [r for r in rr if r["cond"] == c]
                return f"{sum(r['hit'] for r in x)}/{len(x)}"
            def afp(rr):
                x = [r for r in rr if r["cond"] == "baseline"]
                return f"{sum(r['fp'] for r in x)}/{len(x)}"
            kt = sum(r["correct"] for r in ts)
            print(f"{NAMES.get(label, label)[:39]:40}{100*k/len(rs):9.1f}  [{100*lo:5.1f},{100*hi:5.1f}]{hits(rs,'sla'):>10}{hits(rs,'bla'):>9}{afp(rs):>8}  |"
                  f"{100*kt/len(ts):10.1f}{hits(ts,'sla'):>7}{hits(ts,'bla'):>7}{afp(ts):>7}")


if __name__ == "__main__":
    main()
