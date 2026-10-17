#!/bin/bash
# Full re-run of the grid-world simulation study (traces, detector benchmark, mitigation, robustness, sensitivity,
# trade-off curves), then all tables and figures. Deterministic: seeds are fixed, so results match the paper.
# Expect a few hours on a 64-80 core machine. Set W to the number of worker processes.
set -e
cd "$(dirname "$0")/.."
W=${W:-$(nproc)}
sed -i "s/^W=.*/W=$W/" run_v3_traces.sh run_v3_eval.sh 2>/dev/null || true
mkdir -p traces/adv study_results figures

echo "== 1. traces (simulation, all trace sets)"
bash run_v3_traces.sh
python3 gen_traces.py --out traces/impact_none.pkl --jitter 0 --loss 0 --workers $W
# stealth-attacker traces
for d in 1 2 3; do for p in 0.1 0.25 0.5 1.0; do for nz in "none 0 0" "moderate 2 0.05"; do set -- $nz
  python3 gen_traces.py --out traces/adv/st_d${d}_p${p}_$1.pkl --team-sizes 8 20 50 --conds baseline sla --stealth $d $p --jitter $2 --loss $3 --workers $W > /dev/null
done; done; done

echo "== 2. detector tuning and evaluation"
bash run_v3_eval.sh

echo "== 3. closed-loop responses"
python3 run_mitigation_study.py ewma_pop,calibrated $W

echo "== 4. robustness to clock offsets and sender-specific latency"
P="python3 perturb_traces.py"
for c in 0.5 1 2; do $P traces/std_moderate.pkl traces/rob_clock_c${c}_moderate.pkl --clock $c 0; done
$P traces/std_moderate.pkl traces/rob_drift_r0.01_moderate.pkl --clock 0 0.01
$P traces/std_none.pkl traces/rob_clock_c1_none.pkl --clock 1 0
for bj in "1 0" "0 2" "1 2" "2 3"; do set -- $bj; $P traces/std_moderate.pkl traces/rob_het_B$1_J$2_moderate.pkl --hetero $1 $2; done
$P traces/std_none.pkl traces/rob_het_B1_J2_none.pkl --hetero 1 2
python3 evaluate_detectors.py test --traces $(ls traces/rob_*.pkl) --params study_results/tuned.json --out study_results/rob --workers $W

echo "== 5. sensitivity (window, floor, leave-one-out)"
S="traces/std_none.pkl traces/std_moderate.pkl traces/std_heavy.pkl"
python3 sensitivity.py --window 5  --out study_results/sens_W5  --traces $S --workers $W
python3 sensitivity.py --window 20 --out study_results/sens_W20 --traces $S --workers $W
python3 sensitivity.py --eps 0.01  --out study_results/sens_e0.01 --traces $S --workers $W
python3 sensitivity.py --eps 0.2   --out study_results/sens_e0.2  --traces $S --workers $W
python3 sensitivity.py --loo 1     --out study_results/sens_loo   --traces $S --workers $W

echo "== 6. threshold trade-off curves, impact analysis, tables, figures"
python3 threshold_curves.py $W
python3 impact_analysis.py > study_results/impact_numbers.txt
python3 make_tables_v3.py > study_results/tables_v3_numbers.txt
python3 make_adaptive_tables.py
python3 make_mitigation_table.py
echo "done: tables in study_results/, figures in figures/"
