#!/usr/bin/env python3
"""
Robustness of the frozen detectors to timing effects the simulated channel does not contain. Each recorded trace is
perturbed offline (detectors are passive, so mission dynamics are left unchanged) and re-sorted by the new receive time:

  clock  : every sender's clock is offset by o_j ~ U(-c, c) steps and drifts at s_j ~ U(-r, r) steps per step, so the
           observed delay of a message generated at g is the true delay - (o_j + s_j * g). Applies to all senders.
  hetero : sender-specific link latency: a constant extra latency b_j ~ U(0, B) and extra per-message jitter
           U{0..J_j} with J_j ~ U{0..J}, so honest senders no longer share one delay distribution.

  python3 perturb_traces.py traces/std_moderate.pkl traces/rob_clock_c1_moderate.pkl --clock 1 0
  python3 perturb_traces.py traces/std_moderate.pkl traces/rob_het_B1_J2_moderate.pkl --hetero 1 2
"""
import argparse, pickle, random


def perturb(m, clock=None, hetero=None, seed=0):
    rng = random.Random(seed * 1000003 + m["seed"] * 31 + (0 if m["cond"] == "baseline" else 1 if m["cond"] == "sla" else 2))
    senders = sorted({s for (_t, s, _q, _g, _r) in m["trace"]})
    if clock:
        c, r = clock
        par = {s: (rng.uniform(-c, c), rng.uniform(-r, r)) for s in senders}
    if hetero:
        B, J = hetero
        par = {s: (rng.uniform(0, B), rng.randint(0, int(J))) for s in senders}
    out = []
    for (t, s, q, g, rec) in m["trace"]:
        if clock:
            o, sk = par[s]
            g2, rec2 = g + o + sk * g, rec                    # sender stamps with its own (wrong) clock
        else:
            b, j = par[s]
            g2, rec2 = g, rec + b + (rng.randint(0, j) if j else 0)
        out.append((rec2, s, q, g2, rec2))
    out.sort(key=lambda x: x[0])
    mm = dict(m); mm["trace"] = out
    return mm


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--clock", type=float, nargs=2, default=None, metavar=("C", "R"))
    ap.add_argument("--hetero", type=float, nargs=2, default=None, metavar=("B", "J"))
    a = ap.parse_args()
    d = pickle.load(open(a.src, "rb"))
    d["missions"] = [perturb(m, a.clock, a.hetero) for m in d["missions"]]
    d["meta"]["perturb"] = dict(clock=a.clock, hetero=a.hetero)
    pickle.dump(d, open(a.dst, "wb"))
    print("wrote", a.dst, len(d["missions"]))
