#!/bin/bash
# Planner-level delay attack on the original M-TARE system (see run_planner_attack.py).
cd "$(dirname "$0")"
date +%T
python3 run_planner_attack.py --environments tunnel garage --team-sizes 4 8 --iterations 5 \
   --conditions baseline sla bla --budget-s 360 --lambda-s 2.5 --comms-range 50 --attacker 1 \
   --start-mode clustered --out-dir planner_runs > planner_main.log 2>&1
date +%T; echo PLANNERMAINDONE
