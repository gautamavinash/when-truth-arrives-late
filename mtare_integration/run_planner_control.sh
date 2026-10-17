#!/bin/bash
# Order-effect control: waits for the current extra run, then runs 6 new iterations per environment (4 robots) with
# conditions in a random order per iteration, including a second no-attack mission (baseline2).
cd "$(dirname "$0")"
until grep -q PLANNERMOREDONE planner_more_wrapper.log; do sleep 60; done
date +%T
python3 run_planner_attack.py --environments tunnel garage --team-sizes 4 --iter-start 15 --iterations 6 \
   --conditions baseline baseline2 sla bla --randomize-order --budget-s 360 --lambda-s 2.5 --comms-range 50 \
   --attacker 1 --start-mode clustered --out-dir planner_runs > planner_control.log 2>&1
date +%T; echo PLANNERCONTROLDONE
