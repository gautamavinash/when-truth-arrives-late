#!/usr/bin/env python3
"""Sensitivity of the population-referenced detectors (frozen parameters) to the population window W, the scale
floor epsilon, and a leave-one-out median that excludes the tested sender.
  python3 sensitivity.py --window 20 --eps 0.05 --loo 0 --out study_results/sens_W20 --traces traces/std_none.pkl ...
"""
import argparse, sys
import study_detectors as sd
import evaluate_detectors as ev

ap = argparse.ArgumentParser()
ap.add_argument("--window", type=int, default=10); ap.add_argument("--eps", type=float, default=0.05)
ap.add_argument("--loo", type=int, default=0); ap.add_argument("--out", required=True)
ap.add_argument("--traces", nargs="+", required=True); ap.add_argument("--workers", type=int, default=64)
a = ap.parse_args()
sd.POP_WINDOW, sd.EPS, sd.LOO = a.window, a.eps, bool(a.loo)
ev.cmd_test(argparse.Namespace(traces=a.traces, params="study_results/tuned.json", out=a.out, workers=a.workers,
                               only="calibrated,cusum_pop,ewma_pop,bocpd_pop"))
