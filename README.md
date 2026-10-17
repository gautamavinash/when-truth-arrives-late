# When Truth Arrives Late: Spotting Delayed Teammates in Multi-Robot Exploration

Code and data for the paper

> A. Gautam, V. S. Shekhawat, R. Sagwal, and V. Gupta, "When Truth Arrives Late: Spotting Delayed Teammates in
> Multi-Robot Exploration," *under review*, 2026.

The repository contains the grid-world simulator, the two delay attacks, the eighteen detectors of the benchmark, all
analysis scripts, the per-mission results behind every table and figure of the paper, and the recordings of the
experiments on the original M-TARE ROS/Gazebo/Docker system.

## Naming

The two attacks are the Sequential-Lag Attack (SLA, `attacks/sla.py`), whose lag accumulates, and the Bounded-Lag
Attack (BLA, `attacks/bla.py`), whose lag is bounded by the release window. The same names are used for the condition
labels in the code and in every data file (`baseline`, `sla`, `bla`).

## Repository layout

| Path | Contents |
|---|---|
| `simulation/` | ORMSTC-style grid-world coverage simulator (robots, layouts, channel noise, closed-loop responses) |
| `attacks/` | SLA (`sla.py`), BLA (`bla.py`), and the stealth attacker (`stealth.py`) |
| `detection/` | Original fixed-threshold detector and the calibrated population-referenced rule |
| `study_detectors.py`, `study_ml.py` | All eighteen detectors (CUSUM, EWMA, MAD, Bayesian change-point, message-age check, ETD-style, HOTD-style, Isolation Forest, population-normalized variants) |
| `gen_traces.py` | Simulates missions and records the message stream at one observer |
| `evaluate_detectors.py` | Equal-budget tuning on held-out missions and testing |
| `perturb_traces.py`, `sensitivity.py` | Clock-offset and sender-latency robustness, sensitivity to window, floor, and leave-one-out |
| `run_mitigation_study.py` | Closed-loop responses (ignore a flagged sender, drop stale messages) |
| `impact_analysis.py`, `threshold_curves.py` | Impact numbers, impact figures, trade-off curves |
| `make_tables_v3.py`, `make_adaptive_tables.py`, `make_mitigation_table.py` | LaTeX tables of the paper |
| `scripts/` | One-command reproduction (`run_all.sh`) and table rebuild from shipped results |
| `study_results/` | Per-mission results (`*_missions.csv.gz`), summaries, tuned detector configurations and models |
| `figures/` | Figures as they appear in the paper |
| `mtare_integration/` | Real-system experiments: attack senders, patched cross-robot bridge, launchers, analysis scripts, and recorded data |

## Requirements

Simulation and analysis: Python 3.10 or newer with `numpy`, `scipy`, and `matplotlib` (`pip install -r requirements.txt`).
Developed with Python 3.12, numpy 1.26, scipy 1.11, matplotlib 3.6.

Real-system experiments (optional): Ubuntu with Docker, ROS Noetic, and the M-TARE exploration system with its Docker
launcher. The launcher scripts in `mtare_integration/` expect the M-TARE launcher under `~/mtare_project/launcher/mtare_docker`
and the network interface and X display given on their command lines. The recorded data can be re-analysed without
any of this.

## Reproducing the results

**Tables from the shipped results** (minutes, no simulation):

```bash
bash scripts/tables_from_shipped_results.sh
```

This rebuilds `study_results/tables_v3.tex` (accuracy, per-class rates, transfer, robustness, sensitivity, and the
supplementary tables), `study_results/mitigation_table.tex`, and `figures/fig5.png`.

**Full re-run of the simulation study** (deterministic, a few hours on a 64--80 core machine, about 3 GB of traces):

```bash
W=64 bash scripts/run_all.sh
```

**Real-system analyses from the recorded data:**

```bash
cd mtare_integration
python3 make_live_tables.py                                  # position-report detection, live tables
python3 live_retune.py live_runs/live_main.csv               # simulation-tuned versus live-retuned detectors
python3 analyze_planner_final.py planner_runs 360            # planner-level attack, fixed-order and control designs
python3 analyze_order_effect.py                              # randomized-order control
python3 planner_accounting.py                                # mission accounting
python3 analyze_planner_final.py planner_runs_logged 360     # instrumented replication
python3 planner_detection.py planner_runs_logged             # detection on the planner traffic
```

## Data

| Path | Description |
|---|---|
| `study_results/std_missions.csv.gz` | Detector benchmark: one row per detector, noise level, and mission (correct, recall, false flags, latency) |
| `study_results/sec_*`, `late_*` | Other delay windows and onsets, late-onset study |
| `study_results/rob_*`, `sens_*` | Robustness and sensitivity studies |
| `study_results/adv_br_*`, `adv_st_*` | Compromised-fraction and stealth studies |
| `study_results/mitigation_raw.csv.gz` | Closed-loop responses, one row per mission |
| `study_results/tuned*.json`, `*.models.pkl` | Frozen detector configurations and fitted learned models |
| `mtare_integration/sweep_data/` | Position-report missions: every received packet with send stamp and receive time |
| `mtare_integration/live_runs/` | Sweep index (`live_main.csv`), live analysis outputs |
| `mtare_integration/planner_runs/` | Planner-level attack (fixed-order and randomized-order designs): robot trajectories, planner metrics, bridge logs |
| `mtare_integration/planner_runs_logged/` | Instrumented replication: as above plus every received bridge frame (`bridge_rx_*.csv`) |

Mission folders are named `<environment>_<robots>_<condition>_<iteration>`, where the condition is `baseline`,
`baseline2` (second no-attack run of the control design), `sla`, or `bla`.

## Responsible use

The attack code implements the two timing attacks studied in the paper so that their impact and their detection can be
measured. It delays only the attacker's own messages in a simulator or in a self-contained test system, and it is
provided for research on detection and defense.

## License

Code: MIT License (`LICENSE`). Data (`study_results/`, `figures/`, and the recorded data in `mtare_integration/`):
Creative Commons Attribution 4.0 International (`LICENSE-DATA`).

## Citation

See `CITATION.cff`. Please cite the paper if you use this code or data.
