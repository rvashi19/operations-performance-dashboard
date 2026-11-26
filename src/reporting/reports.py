"""CSV exports for Power BI and generated markdown reports. Every number comes from the database."""
import json
import logging

import pandas as pd
from sqlalchemy.engine import Engine

from src import config
from src.analytics.kpis import clean_kpis, monthly_rolling_average, naive_kpis
from src.database.db import read_df
from src.validation.framework import summarize

log = logging.getLogger(__name__)
EXPORTS = {
    "fact_service_requests": "SELECT * FROM analytics.v_service_requests",
    "dim_date": "SELECT * FROM analytics.dim_date",
    "dim_agency": "SELECT * FROM analytics.dim_agency",
    "dim_complaint": "SELECT * FROM analytics.dim_complaint",
    "dim_geography": "SELECT * FROM analytics.dim_geography",
    "kpi_summary": "SELECT * FROM analytics.v_kpi_summary",
    "monthly_volume": "SELECT * FROM analytics.v_monthly_volume ORDER BY month",
    "monthly_volume_rolling": "SELECT * FROM analytics.v_monthly_volume_rolling ORDER BY month",
    "dq_run_summary": "SELECT * FROM ops.v_dq_run_summary",
    "backlog_monthly": "SELECT * FROM analytics.v_backlog_monthly ORDER BY month_end, agency_code",
    "open_requests": "SELECT * FROM analytics.v_open_requests",
    "agency_performance": "SELECT * FROM analytics.v_agency_performance ORDER BY total_requests DESC",
    "complaint_performance": "SELECT * FROM analytics.v_complaint_performance ORDER BY total_requests DESC",
    "dq_issues": "SELECT * FROM ops.v_dq_issues_latest",
    "dq_rule_summary": "SELECT * FROM ops.v_dq_rule_summary ORDER BY rule_id",
    "raw_vs_clean": "SELECT * FROM analytics.v_raw_vs_clean ORDER BY ord",
    "raw_vs_clean_agency": "SELECT * FROM analytics.v_raw_vs_clean_agency ORDER BY agency_code",
    "cleaning_audit_summary": """SELECT action, COALESCE(rule_ids, '') AS rule_ids, count(*) AS records
        FROM analytics.cleaning_audit WHERE run_id = (SELECT run_id FROM ops.v_latest_load_run)
        GROUP BY 1, 2 ORDER BY 3 DESC""",
    "pipeline_runs": "SELECT * FROM ops.pipeline_runs ORDER BY started_at",
}
STAGING_FIELDS = ["unique_key", "created_at", "closed_at", "due_at", "resolution_updated_at", "agency",
                  "complaint_type", "descriptor", "status", "resolution_description", "borough",
                  "incident_zip", "community_board", "latitude", "longitude", "channel"]


def md_table(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False, floatfmt=",.4f")


def _fmt(v, kind="n"):
    if v is None or pd.isna(v):
        return "n/a"
    return f"{v:.2%}" if kind == "%" else f"{v:,.2f}" if kind == "f" else f"{int(v):,}"


def export_csvs(conn) -> dict:
    out = config.ROOT / "data" / "exports"
    out.mkdir(parents=True, exist_ok=True)
    frames = {}
    for name, sql in EXPORTS.items():
        df = read_df(conn, sql)
        df.to_csv(out / f"{name}.csv", index=False)
        frames[name] = df
    log.info("exported %s csv files to %s", len(EXPORTS), out)
    return frames



def _close(a, b, tol):
    return a is not None and b is not None and not pd.isna(a) and not pd.isna(b) and abs(float(a) - float(b)) <= tol


def generate_all(engine: Engine) -> dict:
    s = config.settings()
    rules_cfg = config.validation_rules()
    target = s["analytics"]["analytical_target_days"]
    with engine.connect() as conn:
        f = export_csvs(conn)
        run = read_df(conn, "SELECT r.*, lr.reporting_date FROM ops.pipeline_runs r "
                            "JOIN ops.v_latest_load_run lr USING (run_id)").iloc[0]
        # "raw" = the current source snapshot (superseded historical versions are not part of it)
        stg = read_df(conn, f"SELECT {', '.join(STAGING_FIELDS)}, record_hash FROM analytics.v_snapshot_raw")
        fact = read_df(conn, "SELECT unique_key, status_group, created_at, closed_at, effective_closed_at, "
                             "resolution_hours, include_in_resolution_metrics, within_analytical_target "
                             "FROM analytics.fact_service_request")
        issues = f["dq_issues"]
    for c in ("created_at", "closed_at"):
        stg[c] = pd.to_datetime(stg[c])

    # ---------- reconciliation: independent Python implementations vs SQL views ----------
    py, sql = clean_kpis(fact), f["kpi_summary"].iloc[0]
    naive = naive_kpis(stg, target)
    raw_sql = f["raw_vs_clean"].set_index("ord")["raw_value"]
    roll_sql = f["monthly_volume_rolling"]
    roll_py = monthly_rolling_average(fact["created_at"], 3, start=pd.Timestamp(run["window_start"]).to_period("M"),
                                      end=(pd.Timestamp(run["window_end"]) - pd.Timedelta("1us")).to_period("M"))
    # request-level counts are reconciled; record-level counts can legitimately differ here because the snapshot
    # view stores one row per distinct record while the pipeline also counted exact-duplicate copies.
    dq_py = summarize(stg.assign(unique_key=stg["unique_key"].astype("string")), issues)
    dq_sql = f["dq_run_summary"].iloc[0]
    checks = {
        "total_requests": (py["total_requests"], sql["total_requests"], 0),
        "closed_requests": (py["closed_requests"], sql["closed_requests"], 0),
        "open_requests": (py["open_requests"], sql["open_requests"], 0),
        "unknown_status_requests": (py["unknown_status_requests"], sql["unknown_status_requests"], 0),
        "avg_resolution_hours": (py["avg_resolution_hours"], sql["avg_resolution_hours"], 0.006),
        "median_resolution_hours": (py["median_resolution_hours"], sql["median_resolution_hours"], 0.006),
        "p90_resolution_hours": (py["p90_resolution_hours"], sql["p90_resolution_hours"], 0.006),
        "raw_avg_resolution_hours": (naive["avg_resolution_hours"], raw_sql[5], 0.0001),
        "raw_median_resolution_hours": (naive["median_resolution_hours"], raw_sql[6], 0.0001),
        "requests_inspected": (dq_py["requests_inspected"], dq_sql["requests_inspected"], 0),
        "requests_affected": (dq_py["requests_affected"], dq_sql["requests_affected"], 0),
        "rolling_3m_last_month": (roll_py.iloc[-1, 2], roll_sql["created_rolling_3m_avg"].iloc[-1], 0.006),
    }
    mismatches = {k: v for k, v in checks.items() if not _close(v[0], v[1], v[2])}
    if mismatches:
        raise AssertionError(f"KPI reconciliation failed (python vs SQL): {mismatches}")

    total, requests = int(dq_sql["records_inspected"]), int(dq_sql["requests_inspected"])
    rec_aff, req_aff = int(dq_sql["records_affected"]), int(dq_sql["requests_affected"])
    missing = pd.DataFrame({"column": STAGING_FIELDS,
                            "missing": [int(stg[c].isna().sum()) for c in STAGING_FIELDS]})
    missing["missing_pct"] = (100 * missing["missing"] / len(stg)).round(3)
    missing.to_csv(config.ROOT / "data" / "exports" / "dq_missing_values.csv", index=False)
    dup_ids = int(stg["unique_key"].dropna().duplicated().sum())
    by_rule = f["dq_rule_summary"][["rule_id", "rule_name", "category", "severity", "treatment", "issues",
                                    "affected_records"]]
    by_cat = issues.groupby("issue_category").agg(issues=("issue_id", "count"),
                                                  affected_records=("record_hash", "nunique")).reset_index()
    by_sev = issues.groupby("severity").agg(issues=("issue_id", "count")).reset_index()
    by_agency = f["agency_performance"][["agency_code", "total_requests", "records_with_dq_issues", "dq_issues"]].copy()
    by_agency["affected_pct"] = (100 * by_agency["records_with_dq_issues"] / by_agency["total_requests"]).round(3)
    by_agency = by_agency.rename(columns={"total_requests": "published_requests",
                                          "records_with_dq_issues": "requests_with_issues"})
    by_agency = by_agency.sort_values("affected_pct", ascending=False)
    by_month = issues.pivot_table(index="created_month", columns="rule_id", values="issue_id",
                                  aggfunc="count", fill_value=0).reset_index()
    manual = issues[issues["resolution_status"] == "pending_manual_review"]["record_hash"].nunique()
    end_incl = (pd.Timestamp(run["window_end"]) - pd.Timedelta("1us")).date()
    metrics = {"run_id": str(run["run_id"]), "reporting_date": str(run["reporting_date"]),
               "window_half_open": [str(run["window_start"]), str(run["window_end"])],
               "records_inspected": total, "records_affected": rec_aff, "record_pass_rate": (total - rec_aff) / total if total else None,
               "requests_inspected": requests, "requests_affected": req_aff,
               "request_pass_rate": (requests - req_aff) / requests if requests else None,
               "total_issues": int(len(issues)), "manual_review_records": int(manual),
               "duplicate_request_ids_in_snapshot": dup_ids, "records_without_id": int(stg["unique_key"].isna().sum())}

    report = [
        "# Data Quality Report", "",
        f"_Generated from pipeline run `{run['run_id']}` (extracted {pd.Timestamp(run['started_at']).tz_convert('America/New_York'):%Y-%m-%d %H:%M} New York time). "
        f"Scope: NYC 311 requests created {run['window_start']:%Y-%m-%d} to {end_incl} inclusive, "
        f"borough = {s['source']['filters']['borough']}._", "",
        "## Summary", "",
        "Two rates are reported because they answer different questions. **Record level** counts every inspected "
        "row of the current source snapshot (an exact-duplicate copy or a row without an ID is still a row). "
        "**Request level** counts distinct `unique_key` values. In this extract each request has exactly one row, "
        "so the two coincide; they diverge as soon as duplicates or missing IDs appear.", "",
        "| Measure | Value |", "|---|---|",
        f"| Records (rows) inspected | {total:,} |",
        f"| Records affected by at least one rule | {rec_aff:,} ({rec_aff / total:.3%}) |",
        f"| **Record-level pass rate** | **{(total - rec_aff) / total:.3%}** |",
        f"| Requests (distinct IDs) inspected | {requests:,} |",
        f"| Requests affected | {req_aff:,} ({req_aff / requests:.3%}) |",
        f"| **Request-level pass rate** | **{(requests - req_aff) / requests:.3%}** |",
        f"| Total individual issues (one per record per rule) | {len(issues):,} |",
        f"| Duplicate request IDs inside the snapshot | {dup_ids:,} |",
        f"| Rows without a request ID | {metrics['records_without_id']:,} |",
        f"| Records requiring manual investigation | {manual:,} |", "",
        "## Issues by rule", "", md_table(by_rule), "",
        "## Issues by category", "", md_table(by_cat), "",
        "## Issues by severity", "", md_table(by_sev), "",
        "## Missing values (all inspected records)", "",
        "Missing values are not automatically errors: `closed_at` is legitimately empty for open requests, and "
        "`due_at` is an optional field populated by few agencies.", "", md_table(missing), "",
        "## Issue distribution by agency (request level, published requests)", "", md_table(by_agency), "",
        "## Issue distribution over time (month request was created)", "", md_table(by_month), "",
        "## Reconciliation", "",
        "Each value below was computed independently in Python and in SQL and must match before this report is "
        "written (the run fails otherwise):", "",
        md_table(pd.DataFrame([{"check": k, "python": v[0], "sql": v[1], "tolerance": v[2]} for k, v in checks.items()])), ""]
    (config.ROOT / "reports" / "data_quality_report.md").write_text("\n".join(report), encoding="utf-8")

    # ---------- raw vs cleaned ----------
    rvc = f["raw_vs_clean"].drop(columns="ord")
    excluding = {r["id"] for r in rules_cfg["rules"] if r.get("excludes_from_resolution")}
    names = {r["id"]: r["name"] for r in rules_cfg["rules"]}
    dur = stg.assign(h=(stg["closed_at"] - stg["created_at"]).dt.total_seconds() / 3600).dropna(subset=["h"])
    attrib = []
    for rule in sorted(set(issues["rule_id"])):
        hs = set(issues.loc[issues["rule_id"] == rule, "record_hash"])
        n = int(dur["record_hash"].isin(hs).sum())
        if not n:
            continue
        kept = dur[~dur["record_hash"].isin(hs)]["h"]
        attrib.append({"rule_id": rule, "rule": names.get(rule, rule), "records_in_raw_duration_sample": n,
                       "avg_hours_if_removed": round(kept.mean(), 2), "median_hours_if_removed": round(kept.median(), 2),
                       "avg_change_vs_raw_hours": round(kept.mean() - dur["h"].mean(), 2),
                       "removed_by_cleaning_policy": rule in excluding})
    attrib = pd.DataFrame(attrib)
    neg = int((dur["h"] < 0).sum())
    ag = f["raw_vs_clean_agency"]
    changed = ag[(ag["avg_abs_diff"].abs() > 0) | (ag["median_pct_diff"].abs() > 0)]
    cmp_lines = [
        "# Raw vs Cleaned KPI Comparison", "",
        f"_Run `{run['run_id']}`; reporting date {run['reporting_date']}._", "",
        "**Raw** = a report built directly on the current source snapshot: every row counts, any non-Closed status "
        "counts as open, and any row with a `closed_date` contributes a duration (negative durations and open "
        "requests that carry a closed date included). **Cleaned** = the documented treatment policy "
        "(docs/validation_framework.md). Formulas are identical; only record treatment and status grouping differ. "
        "Rates are in percent; differences are computed from unrounded values and rounded only for display.", "",
        md_table(rvc), "",
        "## Explanation of observed changes", "",
        ("* **Counts unchanged.** Nothing was deduplicated or quarantined and no undocumented statuses were found, so "
         "total, closed and open counts are identical."
         if (rvc["abs_diff"].iloc[:3] == 0).all() else
         "* **Counts changed** through deduplication, quarantine or undocumented statuses (see the audit summary)."),
        f"* **Durations.** The raw sample contains {neg} negative durations; the policy removes every record whose rule "
        f"has `excludes_from_resolution: true` ({', '.join(sorted(excluding))}). The attribution table shows the "
        f"direction of each rule's effect.",
        f"* **Largest headline change: {rvc['pct_diff'].abs().max():.3f}%.** "
        + ("Headline (Staten Island) reporting is not materially distorted; the impact is concentrated in specific "
           "agencies (below)." if rvc["pct_diff"].abs().max() < 1 else "Data treatment materially changes headline reporting."), "",
        "## Agency-level impact (agencies whose average or median changed)", "", md_table(changed), "",
        "## Attribution by rule (raw duration sample, one rule removed at a time)", "",
        f"Raw sample: {len(dur):,} durations, mean {dur['h'].mean():.2f} h, median {dur['h'].median():.2f} h. "
        "Rules with `removed_by_cleaning_policy = False` are sensitivity checks only.", "",
        md_table(attrib), "",
        "## Cleaning treatment summary", "", md_table(f["cleaning_audit_summary"]), ""]
    (config.ROOT / "reports" / "kpi_comparison.md").write_text("\n".join(cmp_lines), encoding="utf-8")

    metrics.update({"kpis_clean": py, "kpis_raw": naive,
                    "reconciliation": {k: {"python": v[0], "sql": v[1]} for k, v in checks.items()}})
    (config.ROOT / "reports" / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    log.info("reports written: data_quality_report.md, kpi_comparison.md, metrics.json")
    return metrics
