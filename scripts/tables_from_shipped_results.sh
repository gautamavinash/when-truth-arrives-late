#!/bin/bash
# Rebuild the paper's simulation tables from the shipped per-mission results (no simulation needed).
set -e
cd "$(dirname "$0")/.."
bash scripts/unpack_results.sh
python3 make_tables_v3.py > study_results/tables_v3_numbers.txt
python3 make_mitigation_table.py
python3 threshold_curves.py --plot-only
echo "tables: study_results/tables_v3.tex, study_results/mitigation_table.tex; figure: figures/fig5.png"
