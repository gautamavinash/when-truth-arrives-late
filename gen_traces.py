#!/usr/bin/env python3
"""
Generate observer message traces for the detector comparison study.

A mission is simulated once; the stream of messages delivered to one honest observer
robot (the last robot id; attackers are always the first ids) is recorded as
(delivered_step, sender, seq, generated_at, received_at). Detectors are passive, so
they are scored offline on these traces (see evaluate_detectors.py).

Usage:
  python3 gen_traces.py --out traces/std_none.pkl --jitter 0 --loss 0
  python3 gen_traces.py --out traces/heldout_light.pkl --iter-start 100 --iters 5 --team-sizes 4 12 30 50 --jitter 1 --loss 0.02
"""
import argparse, math, os, pickle, random, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_experiment import attacker_count_for
from simulation.grid_env import GridEnv
from simulation.maps import get_map_obstacles
from simulation.simulator import Simulator
from attacks.sla import SequentialLagAttacker
from attacks.bla import BoundedLagAttacker
from attacks.stealth import StealthDelayAttacker

ALL_SIZES = [4, 5, 8, 10, 12, 15, 16, 20, 25, 30, 35, 40, 45, 50]


def job(a):
    m, n, cond, i, lam, jit, loss, model, onset = a[:9]
    opt = a[9] if len(a) > 9 else {}
    seed = i * 100 + n
    env = GridEnv(size=16, obstacles=get_map_obstacles(m))
    adv, prox, onsets = [], {}, None
    lams = {}
    if cond != "baseline":
        frac = opt.get("frac")
        k = attacker_count_for(n) if frac is None else min(n - 1, max(1, math.ceil(frac * n)))
        adv = list(range(k))
        if opt.get("style") == "independent":      # staggered start and per-attacker delay window
            rr = random.Random(seed * 7 + 1)
            lams = {x: rr.choice([2, 3, 4, 5]) for x in adv}
            onsets = {x: rr.randint(0, 9) for x in adv}
        else:                                       # colluding: identical window, simultaneous start
            lams = {x: lam for x in adv}
        if opt.get("stealth"):
            d, pp = opt["stealth"]
            prox = {x: StealthDelayAttacker(delay_steps=d, p=pp, seed=seed * 31 + x) for x in adv}
        else:
            cls = SequentialLagAttacker if cond == "sla" else BoundedLagAttacker
            prox = {x: cls(lambda_steps=lams[x]) for x in adv}
    sim = Simulator(env=env, n_robots=n, adversary_ids=adv, attack_proxies=prox, enable_detection=False,
                    seed=seed, max_steps=2000, channel_jitter=jit, channel_loss=loss, channel_model=model,
                    attack_onset=onset, record_trace_for=n - 1, attack_onsets=onsets)
    sim.run()
    sm = sim.summary()
    return dict(map=m, n=n, cond=cond, iter=i, seed=seed, lam=lam, adv=adv, observer=n - 1, onset=onset,
                jitter=jit, loss=loss, model=model,
                completion=sm["completion_step"], cov_eff=sm["coverage_efficiency"], redundant=sm["total_redundant"],
                legit_cov=sm["legitimate_avg_coverage"], mal_cov=sm["malicious_coverage"], n_att=len(adv), style=opt.get("style", "colluding"),
                frac=opt.get("frac"), stealth=opt.get("stealth"),
                collisions=sm["total_collisions"], trace=sim.trace)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--maps", nargs="+", default=["tunnel", "indoor", "garage", "campus", "forest"])
    p.add_argument("--team-sizes", type=int, nargs="+", default=ALL_SIZES)
    p.add_argument("--conds", nargs="+", default=["baseline", "sla", "bla"])
    p.add_argument("--iters", type=int, default=25)
    p.add_argument("--iter-start", type=int, default=0)
    p.add_argument("--lambda", dest="lam", type=int, default=3)
    p.add_argument("--jitter", type=int, default=0)
    p.add_argument("--loss", type=float, default=0.0)
    p.add_argument("--model", default="uniform")
    p.add_argument("--onset", type=int, default=0)
    p.add_argument("--workers", type=int, default=48)
    p.add_argument("--frac", type=float, default=None, help="attacker fraction of the team (default: 10% rule)")
    p.add_argument("--style", default="colluding", choices=["colluding", "independent"])
    p.add_argument("--stealth", type=float, nargs=2, default=None, metavar=("DELAY", "P"), help="stealth attacker: delay steps and probability")
    a = p.parse_args()
    opt = dict(frac=a.frac, style=a.style, stealth=(int(a.stealth[0]), a.stealth[1]) if a.stealth else None)
    jobs = [(m, n, c, i, a.lam, a.jitter, a.loss, a.model, a.onset, opt) for m in a.maps for n in a.team_sizes
            for c in a.conds for i in range(a.iter_start, a.iter_start + a.iters)]
    jobs.sort(key=lambda j: -j[1])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    print(f"{len(jobs)} missions -> {a.out}", flush=True)
    out = []
    with Pool(a.workers) as pool:
        for k, r in enumerate(pool.imap_unordered(job, jobs, chunksize=2), 1):
            out.append(r)
            if k % 250 == 0:
                print(f"  {k}/{len(jobs)}", flush=True)
    meta = dict(args=vars(a))
    with open(a.out, "wb") as f:
        pickle.dump(dict(meta=meta, missions=out), f)
    print("wrote", a.out, len(out), flush=True)
