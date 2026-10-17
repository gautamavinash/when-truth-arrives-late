#!/bin/bash
cd "$(dirname "$0")"
W=64
E="python3 evaluate_detectors.py"
date +%T; echo "== tune (main)"
$E tune --traces traces/ho_none.pkl traces/ho_light.pkl traces/ho_moderate.pkl traces/ho_heavy.pkl --out study_results/tuned.json --workers $W > study_results/tune.log 2>&1
date +%T; echo "== test std"
$E test --traces traces/std_none.pkl traces/std_light.pkl traces/std_moderate.pkl traces/std_heavy.pkl traces/std_shift.pkl --params study_results/tuned.json --out study_results/std --workers $W > study_results/std.log 2>&1
date +%T; echo "== test sec"
$E test --traces traces/sec_lam2.pkl traces/sec_lam5.pkl traces/sec_onset10.pkl --params study_results/tuned.json --out study_results/sec --workers $W > study_results/sec.log 2>&1
date +%T; echo "== late onset: tune on late-onset held-out, test"
$E tune --traces traces/ho_onset20_none.pkl traces/ho_onset20_moderate.pkl --out study_results/tuned_late.json --workers $W > study_results/tune_late.log 2>&1
$E test --traces traces/late_onset20_none.pkl traces/late_onset20_moderate.pkl --params study_results/tuned_late.json --out study_results/late --workers $W > study_results/late.log 2>&1
$E test --traces traces/late_onset20_none.pkl traces/late_onset20_moderate.pkl --params study_results/tuned.json --out study_results/late_maintuned --workers $W > study_results/late_maintuned.log 2>&1
ONLY=fixed_orig,fixed,maxage,hotd_style,iforest,mad_pop,cusum_pop,ewma_pop,bocpd_pop,calibrated
$E test --traces $(ls traces/adv/br_*.pkl) --params study_results/tuned.json --out study_results/adv_br --workers $W --only $ONLY > study_results/adv_br.log 2>&1
$E test --traces $(ls traces/adv/st_*.pkl) --params study_results/tuned.json --out study_results/adv_st --workers $W --only $ONLY > study_results/adv_st.log 2>&1
date +%T; echo V3EVALDONE
