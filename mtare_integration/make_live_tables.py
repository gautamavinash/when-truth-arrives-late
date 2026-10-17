"""LaTeX tables + summary numbers for the live section, from the main live sweep."""
import json, statistics as st, sys
sys.path.insert(0, '.')
import live_main_analysis as L

def fit(table, star):
    """Scale a tabular down to the column/page width if (and only if) it is wider; never enlarge it."""
    import re
    w = r"\textwidth" if star else r"\columnwidth"
    table = table.replace(r"\begin{tabular}", r"\resizebox{\ifdim\width>" + w + r"" + w + r"\else\width\fi}{!}{%" + "\n" + r"\begin{tabular}", 1)
    table = table.replace(r"\end{tabular}", r"\end{tabular}}", 1)
    return table

sweeps = ["live_runs/live_main.csv"]
base = L.analyze("sweep_data", sweeps, 0.0)
jit = {j: L.analyze("sweep_data", sweeps, j) for j in (0.05, 0.2, 0.5)}

def stats(recs, det):
    rs = [r for r in recs if r["det"] == det and r["correct"] is not None]
    k = sum(r["correct"] for r in rs); lo, hi = L.wilson(k, len(rs))
    atk = [r for r in rs if r["cond"] != "baseline"]; bs = [r for r in rs if r["cond"] == "baseline"]
    byc = lambda c: (sum(r["found"] for r in atk if r["cond"] == c), sum(r["n_eff"] for r in atk if r["cond"] == c))
    lats = [x for r in atk for x in r["lat"]]
    return dict(n=len(rs), acc=100*k/len(rs), lo=100*lo, hi=100*hi, sla=byc("sla"), bla=byc("bla"),
                base_fp=(sum(r["fp"] > 0 for r in bs), len(bs)), atk_fp=(sum(r["fp"] > 0 for r in atk), len(atk)),
                lat=(st.mean(lats) if lats else float("nan")))

rows = []
for det in L.ORDER:
    s = stats(base, det)
    rows.append(f"{L.NAMES[det]} & {s['acc']:.1f} ({s['lo']:.1f}--{s['hi']:.1f}) & {s['sla'][0]}/{s['sla'][1]} & {s['bla'][0]}/{s['bla'][1]} & "
                f"{s['base_fp'][0]}/{s['base_fp'][1]} & {s['atk_fp'][0]}/{s['atk_fp'][1]} & {('%.1f' % s['lat']) if s['lat']==s['lat'] else '--'} \\\\")
    if det in ("bocpd_self", "iforest"): rows.append(r"\hline")
t1 = "\n".join([r"\begin{table*}[t]", r"\centering",
  r"\caption{Live detection on the original M-TARE system, replayed offline from the recorded traffic. Mission accuracy (\%, 95\% Wilson interval): attack-free missions correct when nothing is flagged, attack missions when every effective attacker is flagged and no honest robot is. Parameters are those tuned in simulation (never tuned on live data).}",
  r"\label{tab:live}", r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{lcccccc}", r"\hline",
  r"Detector & Accuracy & SLA found & BLA found & Attack-free with & Attack missions with & Mean latency \\",
  r" & & (effective) & (effective) & false flag & false flag & (s) \\", r"\hline"] + rows + [r"\hline", r"\end{tabular}", r"\end{table*}"])

# jitter robustness table
cols = [("0", base)] + [(f"{j}", jit[j]) for j in (0.05, 0.2, 0.5)]
rows = []
for det in L.ORDER:
    rows.append(L.NAMES[det] + " & " + " & ".join(f"{stats(rc, det)['acc']:.1f}" for _, rc in cols) + r" \\")
    if det in ("bocpd_self", "iforest"): rows.append(r"\hline")
t2 = "\n".join([r"\begin{table}[t]", r"\centering",
  r"\caption{Live mission accuracy (\%) when extra random delay, uniform on $0$ to the stated value in seconds, is added to every receive time of the recorded traffic.}",
  r"\label{tab:livejit}", r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{lcccc}", r"\hline",
  r"Detector & 0 & 0.05 & 0.2 & 0.5 \\", r"\hline"] + rows + [r"\hline", r"\end{tabular}", r"\end{table}"])
open("live_runs/live_tables.tex", "w").write(fit(t1, True) + "\n\n" + fit(t2, False) + "\n")

# numbers for the text
atk_all = [r for r in base if r["det"] == "calibrated" and r["cond"] != "baseline"]
print("missions", len({(r['env'], r['n'], r['cond'], i) for i, r in enumerate(atk_all)}), "attack missions", len(atk_all))
print("attackers total", sum(r["n_att"] for r in atk_all), "effective", sum(r["n_eff"] for r in atk_all))
ineff = [(r["env"], r["n"], r["cond"]) for r in atk_all if r["n_eff"] < r["n_att"]]
print("missions with an ineffective attacker:", len(ineff), ineff[:10])
for det in L.ORDER:
    s = stats(base, det); print(f"{det:18} acc {s['acc']:.1f} [{s['lo']:.1f},{s['hi']:.1f}] SLA {s['sla']} BLA {s['bla']} baseFP {s['base_fp']} atkFP {s['atk_fp']} lat {s['lat']:.1f}")
# by env and by team size for population-ref detectors and deployed
for key in ("env", "n"):
    print("by", key)
    for v in sorted({r[key] for r in base}):
        sub = [r for r in base if r[key] == v]
        print(" ", v, {d: f"{stats(sub, d)['acc']:.0f}" for d in ("deployed_monitor", "fixed_orig", "calibrated", "cusum_pop", "ewma_pop", "mad_pop")})
