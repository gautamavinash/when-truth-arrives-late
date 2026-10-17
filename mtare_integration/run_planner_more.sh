#!/bin/bash
# Extra paired iterations (5-14) for 4-robot teams; iterations 0-4 already exist and are skipped.
cd "$(dirname "$0")"
date +%T
python3 run_planner_attack.py --environments tunnel garage --team-sizes 4 --iterations 15 \
   --conditions baseline sla bla --budget-s 360 --lambda-s 2.5 --comms-range 50 --attacker 1 \
   --start-mode clustered --out-dir planner_runs > planner_more.log 2>&1
date +%T; echo PLANNERMOREDONE
