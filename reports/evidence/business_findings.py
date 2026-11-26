"""Python cross-checks for reports/business_findings.md (independent of the SQL in sql/analytics/business_findings.sql).
Run: python reports/evidence/business_findings.py > reports/evidence/business_findings_python_output.txt
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.database.db import get_engine, read_df  # noqa: E402

with get_engine().connect() as c:
    fact = read_df(c, "SELECT f.*, a.agency_code FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key)")
    snap = read_df(c, "SELECT * FROM analytics.v_snapshot_raw")
    iss = read_df(c, "SELECT record_hash, rule_id FROM ops.v_dq_issues_latest")

h = fact.loc[fact.include_in_resolution_metrics, "resolution_hours"].astype(float)
print("F1 mean vs median")
print(f"  n={len(h):,} mean={h.mean():.1f} median={h.median():.2f} p90={h.quantile(.9):.1f}")
top = h.sort_values(ascending=False)
for pct in (1, 5, 10):
    k = int(len(top) * pct / 100)
    print(f"  slowest {pct}% ({k:,} requests) hold {top.iloc[:k].sum() / top.sum():.1%} of all resolution hours")
print(f"  mean if slowest 1% removed: {top.iloc[int(len(top) * .01):].mean():.1f} h")

print("\nF2 DOB median before/after")
dob = snap[snap.agency == "DOB"].copy()
dob["h"] = (dob.closed_at - dob.created_at).dt.total_seconds() / 3600
dq011 = set(iss.loc[iss.rule_id == "DQ011", "record_hash"])
raw = dob.h.dropna()
kept = dob.loc[~dob.record_hash.isin(dq011), "h"].dropna()
print(f"  raw DOB durations n={len(raw):,} median={raw.median():.2f} h")
print(f"  without DQ011 n={len(kept):,} median={kept.median():.2f} h ({(kept.median() / raw.median() - 1):+.1%})")
removed = dob.loc[dob.record_hash.isin(dq011), "h"]
print(f"  removed DQ011 records: n={len(removed)}, share with duration < 1 h = {(removed < 1).mean():.1%}, "
      f"median = {removed.median():.2f} h")

print("\nF3 DHS missing closed dates")
dhs = snap[snap.agency == "DHS"]
m = dhs.assign(month=dhs.created_at.dt.to_period("M"), missing=dhs.closed_at.isna()).groupby("month").missing.agg(["size", "sum"])
print(m.to_string())
jan_may = m.loc[:"2025-05"]
print(f"  Jan-May: {int(jan_may['sum'].sum())} of {int(jan_may['size'].sum())} DHS requests lack a closed date; "
      f"Jun-Dec: {int(m.loc['2025-06':, 'sum'].sum())}")

print("\nF4 long-duration sensitivity")
print(f"  >365 days: {(h > 365 * 24).sum()} requests; mean all {h.mean():.1f} h vs excluding {h[h <= 365 * 24].mean():.1f} h; "
      f"median {h.median():.2f} vs {h[h <= 365 * 24].median():.2f}")

print("\nF6 aggregate vs agency DQ rate")
fact["has_issue"] = fact.dq_issue_count > 0
g = fact.groupby("agency_code").has_issue.agg(["size", "mean"]).sort_values("mean", ascending=False)
print(f"  overall request-level affected rate: {fact.has_issue.mean():.2%}")
print((g.head(5).assign(mean=lambda d: (100 * d["mean"]).round(2))).rename(columns={"size": "requests", "mean": "pct_affected"}).to_string())
