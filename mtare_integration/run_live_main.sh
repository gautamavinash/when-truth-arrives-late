#!/bin/bash
# Main live sweep on the original M-TARE system: 5 environments x team sizes {4,8,12,16,20} x {baseline,sla,bla} x 3 missions.
# Random start positions, lambda=2.5 s, attackers = max(1, ceil(10% of N)), 2-minute window per mission.
cd "$(dirname "$0")"
pgrep -x Xvfb >/dev/null || (Xvfb :50 -screen 0 1280x800x24 >/tmp/xvfb50.log 2>&1 &)
sleep 2; DISPLAY=:50 xhost + >/dev/null 2>&1
date +%T
python3 run_full_sweep.py --environments tunnel garage campus indoor forest --team-sizes 4 8 12 16 20 \
   --conditions baseline sla bla --iterations 3 --duration-min 2 --lambda-s 2.5 --comms-range 30 \
   --display :50 --seed 11 --start-mode random \
   --incremental-csv live_runs/live_main.csv --excel-out live_runs/live_main.xlsx > live_runs/live_main.log 2>&1
date +%T; echo LIVEMAINDONE
