#!/bin/bash
# v3: regenerate every trace set that contains SLA after fixing the SLA queue (no message is discarded).
cd "$(dirname "$0")"
W=72
G="python3 gen_traces.py"
$G --out traces/ho_none.pkl     --iter-start 100 --iters 5 --team-sizes 4 12 30 50 --jitter 0 --loss 0    --workers $W
$G --out traces/ho_light.pkl    --iter-start 100 --iters 5 --team-sizes 4 12 30 50 --jitter 1 --loss 0.02 --workers $W
$G --out traces/ho_moderate.pkl --iter-start 100 --iters 5 --team-sizes 4 12 30 50 --jitter 2 --loss 0.05 --workers $W
$G --out traces/ho_heavy.pkl    --iter-start 100 --iters 5 --team-sizes 4 12 30 50 --jitter 3 --loss 0.10 --workers $W
echo HELDOUTDONE
$G --out traces/std_none.pkl     --jitter 0 --loss 0    --workers $W
$G --out traces/std_light.pkl    --jitter 1 --loss 0.02 --workers $W
$G --out traces/std_moderate.pkl --jitter 2 --loss 0.05 --workers $W
$G --out traces/std_heavy.pkl    --jitter 3 --loss 0.10 --workers $W
$G --out traces/std_shift.pkl    --model shift          --workers $W
echo STDDONE
$G --out traces/sec_lam2.pkl    --team-sizes 8 20 50 --lambda 2 --jitter 2 --loss 0.05 --workers $W
$G --out traces/sec_lam5.pkl    --team-sizes 8 20 50 --lambda 5 --jitter 2 --loss 0.05 --workers $W
$G --out traces/sec_onset10.pkl --team-sizes 8 20 50 --onset 10 --jitter 2 --loss 0.05 --workers $W
# late onset (own-stream fairness): held-out for tuning and test sets, small teams whose missions are long enough
$G --out traces/ho_onset20_none.pkl      --iter-start 100 --iters 5 --team-sizes 4 8 12 --onset 20 --jitter 0 --loss 0    --workers $W
$G --out traces/ho_onset20_moderate.pkl  --iter-start 100 --iters 5 --team-sizes 4 8 12 --onset 20 --jitter 2 --loss 0.05 --workers $W
$G --out traces/late_onset20_none.pkl     --team-sizes 4 8 12 --onset 20 --jitter 0 --loss 0    --workers $W
$G --out traces/late_onset20_moderate.pkl --team-sizes 4 8 12 --onset 20 --jitter 2 --loss 0.05 --workers $W
echo SECDONE
for style in colluding independent; do
 for frac in 0.1 0.2 0.3 0.4 0.5 0.6; do
  $G --out traces/adv/br_${style}_f${frac}_none.pkl     --team-sizes 10 20 50 --frac $frac --style $style --jitter 0 --loss 0    --workers $W > /dev/null
  $G --out traces/adv/br_${style}_f${frac}_moderate.pkl --team-sizes 10 20 50 --frac $frac --style $style --jitter 2 --loss 0.05 --workers $W > /dev/null
 done
done
echo V3TRACESDONE
