"""Builds notebooks/exploratory_analysis.ipynb. Execute with:
    python notebooks/build_notebook.py
    python -m jupyter nbconvert --to notebook --execute --inplace notebooks/exploratory_analysis.ipynb
"""
from pathlib import Path

import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))  # noqa: E731
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))    # noqa: E731

md("""
# Exploratory Analysis: NYC 311 Service Requests, Staten Island, 2025

This notebook explores the **real** extract loaded by the pipeline (`python -m src.pipeline --full-refresh`).
It reads the original raw file (unchanged API output) and the PostgreSQL staging and analytics layers.
Every figure below is computed from that data.
""")
code("""
import sys, glob, os
from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
sys.path.insert(0, str(ROOT))
import pandas as pd, numpy as np, matplotlib.pyplot as plt, seaborn as sns
from src.database.db import get_engine, read_df
from src.ingestion.socrata_client import read_raw_file
sns.set_theme(style='whitegrid', palette=['#1F4E79', '#E07B39', '#5B9BD5', '#70AD47', '#A5A5A5'])
pd.set_option('display.width', 160, 'display.max_columns', 30)
engine = get_engine()
conn = engine.connect()
""")
md("## 1. Dataset overview\nThe original file is the newest full-refresh extract in `data/raw/`.")
code("""
raw_path = sorted(glob.glob(str(ROOT / 'data/raw/nyc311_full-refresh_*.jsonl.gz')))[-1]
raw = pd.DataFrame(read_raw_file(Path(raw_path)))
print(Path(raw_path).name, '| rows:', len(raw), '| columns:', raw.shape[1])
raw.head(3).T
""")
md("## 2. Schema inspection\nThe API returns every field as text; staging applies types. Below are the staging types and an example of the API's original values.")
code("""
stg = read_df(conn, "SELECT * FROM analytics.v_snapshot_raw")   # current source snapshot only (no superseded history)
pd.DataFrame({'dtype': stg.dtypes.astype(str), 'example': stg.iloc[0]}).head(26)
""")
md("## 3. Descriptive statistics")
code("""
fact = read_df(conn, "SELECT * FROM analytics.v_service_requests")
fact['resolution_days'] = fact['resolution_days'].astype(float)
print(fact['status'].value_counts().to_string())
fact['resolution_days'].describe(percentiles=[.25, .5, .75, .9, .99]).round(2)
""")
md("## 4. Missing-value analysis\nMissing values are only problems where a field is required. `closed_at` is legitimately empty for open requests; `due_at` is optional and almost never populated in this extract, so **official SLA compliance cannot be computed**.")
code("""
cols = ['unique_key','created_at','closed_at','due_at','resolution_updated_at','agency','complaint_type','descriptor',
        'status','resolution_description','incident_zip','latitude','longitude','community_board']
miss = (stg[cols].isna().mean() * 100).sort_values(ascending=False).round(3)
ax = miss.plot.barh(figsize=(8, 5), color='#1F4E79'); ax.set_xlabel('% missing'); ax.set_title('Missing values by field (staging)')
ax.invert_yaxis(); plt.tight_layout(); plt.show()
closed_missing = stg[stg['status'].eq('Closed') & stg['closed_at'].isna()]
open_missing = stg[~stg['status'].eq('Closed') & stg['closed_at'].isna()]
print('closed status but no closed date:', len(closed_missing), '| open with no closed date (legitimate):', len(open_missing))
""")
md("## 5. Duplicate analysis")
code("""
print('duplicate unique_key in raw extract :', raw['unique_key'].duplicated().sum())
print('exact duplicate rows in raw extract :', raw.drop(columns=[':updated_at']).duplicated().sum())
print('raw rows / distinct keys in database:', read_df(conn, 'SELECT count(*) n, count(DISTINCT unique_key) k FROM raw.service_requests').values.tolist())
""")
md("No duplicates exist in this extract. The dedup rules (DQ001/DQ002) still matter operationally: incremental refreshes re-read an overlap window, and changed records arrive as new versions.")
md("## 6. Request volume trends")
code("""
vol = read_df(conn, "SELECT * FROM analytics.v_monthly_volume WHERE month < '2026-01-01' ORDER BY month")
ax = vol.plot(x='month', y=['created_requests', 'closed_requests'], figsize=(9, 4), marker='o')
ax.set_title('Monthly incoming vs closed requests (2025)'); ax.set_ylabel('requests'); plt.tight_layout(); plt.show()
vol.assign(net=vol.created_requests - vol.closed_requests)
""")
md("## 7. Resolution duration distribution\nThe distribution is extremely right-skewed: most requests close within a day, but a long tail lasts months. This is why median and P90 are reported alongside the mean.")
code("""
d = fact.loc[fact['include_in_resolution_metrics'], 'resolution_days']
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
axes[0].hist(d.clip(upper=60), bins=60, color='#1F4E79'); axes[0].set_title('Resolution days (clipped at 60)')
axes[1].hist(np.log10(d * 24 + 1e-2), bins=60, color='#E07B39'); axes[1].set_title('log10(resolution hours)')
plt.tight_layout(); plt.show()
print(f"mean={d.mean():.2f}d  median={d.median():.2f}d  p90={d.quantile(.9):.2f}d")
""")
md("## 8. Outlier investigation\nDurations over 365 days (rule DQ013) and negative durations (DQ006).")
code("""
s = stg.assign(days=(stg.closed_at - stg.created_at).dt.total_seconds() / 86400)
print('> 365 days by agency/type:'); print(s[s.days > 365].groupby(['agency', 'complaint_type']).size().sort_values(ascending=False).head(8).to_string())
neg = s[s.days < 0][['unique_key','agency','complaint_type','status','created_at','closed_at','days']]
print('\\nnegative durations:', len(neg)); neg.sort_values('days').head(24)
""")
md("""
Two clear patterns in the negative durations:
* **NYPD noise complaints on 2025-11-02 between 01:00 and 02:00.** That is the hour US clocks fell back from EDT to EST. Timestamps are published as local "floating" times with no offset, so an event logged in the second 01:xx can appear to come before one logged in the first. *Confirmed by timing; the internal system's storage format cannot be verified.*
* **DOT Street Light Condition, status Pending, closed almost exactly 24 hours before creation.** This is a systematic one-day offset on records still in progress, consistent with the closed date being carried over from a linked or prior record. *Hypothesis: it cannot be confirmed without DOT's source system.*
""")
md("## 9. Agency comparisons")
code("""
ag = read_df(conn, "SELECT * FROM analytics.v_agency_performance WHERE total_requests >= 300 ORDER BY median_resolution_hours")
fig, ax = plt.subplots(figsize=(9, 5))
ax.barh(ag.agency_code, ag.median_resolution_hours.astype(float) / 24, color='#1F4E79', label='median')
ax.scatter(ag.avg_resolution_hours.astype(float) / 24, ag.agency_code, color='#E07B39', zorder=3, label='average')
ax.set_xscale('log'); ax.set_xlabel('days (log scale)'); ax.set_title('Median vs average resolution by agency'); ax.legend()
plt.tight_layout(); plt.show()
ag[['agency_code','total_requests','resolution_rate','median_resolution_hours','avg_resolution_hours','within_target_rate']]
""")
md("## 10. Data quality findings")
code("""
rs = read_df(conn, "SELECT rule_id, rule_name, severity, treatment, issues, affected_records FROM ops.v_dq_rule_summary ORDER BY issues DESC")
iss = read_df(conn, "SELECT * FROM ops.v_dq_issues_latest")
dqs = read_df(conn, "SELECT * FROM ops.v_dq_run_summary").iloc[0]
print(f"record level : {dqs.records_affected:,} of {dqs.records_inspected:,} rows affected, pass rate {dqs.record_pass_rate:.3%}")
print(f"request level: {dqs.requests_affected:,} of {dqs.requests_inspected:,} requests affected, pass rate {dqs.request_pass_rate:.3%}")
print(f"individual issues: {len(iss):,}")
pd.crosstab(iss.agency, iss.rule_id).loc[lambda t: t.sum(axis=1).sort_values(ascending=False).index]
""")
code("""
precision = stg.assign(midnight=stg.closed_at.dt.time.astype(str).eq('00:00:00'),
                       zero=stg.closed_at.eq(stg.created_at)).groupby('agency')[['midnight','zero']].mean().round(3)
precision.sort_values('midnight', ascending=False).head(6)
""")
md("""
**Timestamp precision (an observation, not a rule violation).** Most DOB closures are stamped exactly at midnight, so DOB closure times are recorded to the day only. DOHMH has a high share of zero-duration closures, where the request was closed at the second it was created. Both affect how comparable agency resolution times are. They are documented in `reports/root_cause_analysis.md` rather than "fixed".
""")
md("## 11. Raw vs cleaned comparison")
code("read_df(conn, 'SELECT metric, unit, raw_value, clean_value, abs_diff, pct_diff FROM analytics.v_raw_vs_clean ORDER BY ord')")
code("read_df(conn, 'SELECT * FROM analytics.v_raw_vs_clean_agency WHERE avg_abs_diff <> 0')")
md("## 12. Business conclusions\nComputed below from the data; the narrative lives in `reports/executive_summary.md`.")
code("""
k = read_df(conn, 'SELECT * FROM analytics.v_kpi_summary').iloc[0]
bk = read_df(conn, "SELECT agency_code, backlog FROM analytics.v_backlog_monthly WHERE month_end = '2025-12-31' ORDER BY backlog DESC LIMIT 3")
print(f"1. {int(k.total_requests):,} requests; {k.resolution_rate:.1%} closed; median {float(k.median_resolution_hours):.1f} h vs average {float(k.avg_resolution_hours):.1f} h.")
print(f"2. {k.within_target_rate:.1%} of eligible requests resolved within the 7-day ANALYTICAL target (not an official SLA).")
print('3. Largest month-end backlog at 2025-12-31:', ', '.join(f'{r.agency_code} ({r.backlog})' for r in bk.itertuples()))
rvc = read_df(conn, 'SELECT * FROM analytics.v_raw_vs_clean')
dob = read_df(conn, "SELECT median_pct_diff FROM analytics.v_raw_vs_clean_agency WHERE agency_code = 'DOB'").iloc[0, 0]
print(f"4. Request-level DQ pass rate {dqs.request_pass_rate:.2%}; largest headline change after cleaning "
      f"{rvc.pct_diff.abs().max():.2f}%; DOB median change {dob:+.1f}%.")
conn.close()
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}})
nbf.write(nb, Path(__file__).with_name("exploratory_analysis.ipynb"))
print("notebook written")
