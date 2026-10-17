#!/usr/bin/env python3
"""
Closed-loop response study (grid world). A population-referenced detector (frozen, tuned in the benchmark) watches the
delivered messages; once it flags a sender, receivers either keep everything ('none' -> baseline attack), ignore that
sender entirely ('drop_all'), or keep its visited-cell facts but drop its stale next-move claim ('drop_intent').
Compared on total redundant visits, completion step and coverage completeness, paired by seed; attack-free missions
measure collateral damage from false flags.
"""
import csv, json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_experiment import attacker_count_for
from simulation.grid_env import GridEnv
from simulation.maps import get_map_obstacles
from simulation.simulator import Simulator
from attacks.sla import SequentialLagAttacker
from attacks.bla import BoundedLagAttacker

TUNED = json.load(open("study_results/tuned.json"))
NOISE = {"none": (0, 0.0), "moderate": (2, 0.05)}


def job(a):
    m, n, cond, i, noise, det, mode = a
    seed = i * 100 + n
    env = GridEnv(size=16, obstacles=get_map_obstacles(m))
    adv, prox = [], {}
    if cond != "baseline":
        cls = SequentialLagAttacker if cond == "sla" else BoundedLagAttacker
        adv = list(range(attacker_count_for(n)))
        prox = {x: cls(lambda_steps=3) for x in adv}
    jit, loss = NOISE[noise]
    if mode in ("stale_drop", "stale_intent"):
        mit = {"mode": mode, "T": 2}
    else:
        mit = {"det": det, "params": TUNED[det]["params"], "mode": mode} if mode != "none" else None
    sim = Simulator(env=env, n_robots=n, adversary_ids=adv, attack_proxies=prox, enable_detection=False, seed=seed,
                    max_steps=2000, channel_jitter=jit, channel_loss=loss, mitigation=mit)
    sim.run()
    sm = sim.summary()
    flagged = set(sim.mit_flag_step)
    return dict(map=m, n=n, cond=cond, iter=i, noise=noise, det=det, mode=mode, redundant=sm["total_redundant"],
                completion=sm["completion_step"], cov_eff=sm["coverage_efficiency"], collisions=sm["total_collisions"],
                n_att=len(adv), flagged_att=len(flagged & set(adv)), flagged_honest=len(flagged - set(adv)))


if __name__ == "__main__":
    dets = sys.argv[1].split(",") if len(sys.argv) > 1 else ["ewma_pop"]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 48
    sizes = [5, 10, 20, 50]
    jobs = [(m, n, c, i, nz, d, mode) for m in ["tunnel", "indoor", "garage", "campus", "forest"] for n in sizes
            for c in ("baseline", "sla", "bla") for i in range(25) for nz in NOISE for d in dets
            for mode in ("none", "drop_all")]
    # freshness responses need no detector: run them once (recorded under det="freshness")
    jobs += [(m, n, c, i, nz, "freshness", mode) for m in ["tunnel", "indoor", "garage", "campus", "forest"] for n in sizes
             for c in ("baseline", "sla", "bla") for i in range(25) for nz in NOISE for mode in ("stale_drop",)]
    print(len(jobs), "runs", flush=True)
    with Pool(workers) as p:
        rows = p.map(job, jobs, chunksize=8)
    with open("study_results/mitigation_raw.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("wrote study_results/mitigation_raw.csv")
