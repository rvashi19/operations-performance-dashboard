"""Idempotent writes to each layer. Every function runs inside the caller's transaction."""
import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.database.db import copy_df, read_df
from src.transformation.staging import STAGING_COLUMNS

log = logging.getLogger(__name__)

FACT_COLUMNS = ["unique_key", "record_hash", "created_date_key", "closed_date_key", "agency_key", "complaint_key",
                "geography_key", "status", "status_group", "created_at", "closed_at", "effective_closed_at", "due_at",
                "channel", "resolution_hours", "resolution_days", "include_in_resolution_metrics",
                "within_analytical_target", "dq_issue_count", "dq_max_severity", "needs_manual_review",
                "loaded_run_id"]


def _upsert_via_temp(conn: Connection, target: str, df: pd.DataFrame, conflict: str, update_cols=None) -> int:
    tmp = "tmp_" + target.replace(".", "_")
    conn.exec_driver_sql(f"CREATE TEMP TABLE {tmp} (LIKE {target} INCLUDING DEFAULTS) ON COMMIT DROP")
    copy_df(conn, tmp, df)
    cols = ", ".join(df.columns)
    action = ("DO NOTHING" if not update_cols else
              "DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols))
    res = conn.exec_driver_sql(f"INSERT INTO {target} ({cols}) SELECT {cols} FROM {tmp} "
                               f"ON CONFLICT ({conflict}) {action}")
    conn.exec_driver_sql(f"DROP TABLE {tmp}")
    return res.rowcount


def load_raw_and_staging(conn: Connection, batch: pd.DataFrame, run_id: str, extracted_at) -> int:
    distinct = batch.drop_duplicates("record_hash")
    raw = pd.DataFrame({"record_hash": distinct["record_hash"], "unique_key": distinct["unique_key"],
                        "payload": distinct["payload"], "source_updated_at": distinct["source_updated_at"],
                        "first_run_id": run_id, "extracted_at": extracted_at})
    inserted = _upsert_via_temp(conn, "raw.service_requests", raw, "record_hash")
    _upsert_via_temp(conn, "staging.service_requests", distinct[STAGING_COLUMNS], "record_hash")
    log.info("raw rows new=%s already_present=%s", inserted, len(distinct) - inserted)
    return inserted


def read_snapshot(conn: Connection) -> pd.DataFrame:
    """Staging rows that belong to the current source snapshot (never superseded history)."""
    cols = ", ".join(f"s.{c}" for c in STAGING_COLUMNS)
    df = read_df(conn, f"SELECT {cols} FROM staging.service_requests s "
                       "JOIN staging.current_snapshot c USING (record_hash)")
    for c in STAGING_COLUMNS:
        if df[c].dtype == object:
            df[c] = df[c].astype("string")
    return df


def replace_snapshot(conn: Connection, inspected: pd.DataFrame, run_id: str) -> int:
    snap = inspected.drop_duplicates("record_hash")[["record_hash", "unique_key"]].assign(run_id=run_id)
    conn.exec_driver_sql("DELETE FROM staging.current_snapshot")
    return copy_df(conn, "staging.current_snapshot", snap)


def write_rules(conn: Connection, rules_cfg: dict) -> None:
    for r in rules_cfg["rules"]:
        conn.execute(text("""
            INSERT INTO ops.dq_rules (rule_id, rule_name, check_type, category, severity, treatment, explanation)
            VALUES (:id, :name, :check, :category, :severity, :treatment, :explanation)
            ON CONFLICT (rule_id) DO UPDATE SET rule_name=EXCLUDED.rule_name, check_type=EXCLUDED.check_type,
              category=EXCLUDED.category, severity=EXCLUDED.severity, treatment=EXCLUDED.treatment,
              explanation=EXCLUDED.explanation"""), {k: r[k] for k in
                                                     ("id", "name", "check", "category", "severity", "treatment", "explanation")})


def write_issues(conn: Connection, issues: pd.DataFrame, run_id: str, detected_at) -> int:
    conn.execute(text("DELETE FROM ops.dq_issues WHERE run_id = :r"), {"r": run_id})  # safe re-run of same run
    return copy_df(conn, "ops.dq_issues", issues.assign(run_id=run_id, detected_at=detected_at))


def _date_dim(dates: pd.Series) -> pd.DataFrame:
    d = pd.date_range(dates.min().normalize(), dates.max().normalize(), freq="D")
    return pd.DataFrame({"date_key": d.strftime("%Y%m%d").astype(int), "full_date": d.date, "year": d.year,
                         "quarter": d.quarter, "month": d.month, "month_name": d.strftime("%B"),
                         "year_month": d.strftime("%Y-%m"), "iso_week": d.isocalendar().week.values,
                         "day_of_week": d.dayofweek + 1, "day_name": d.strftime("%A"), "is_weekend": d.dayofweek >= 5})


def _dim(conn, table, key, natural: list[str], rows: pd.DataFrame, update=None) -> pd.DataFrame:
    _upsert_via_temp(conn, table, rows.drop_duplicates(natural), ", ".join(natural), update)
    return read_df(conn, f"SELECT {key}, {', '.join(natural)} FROM {table}")


def load_analytics(conn: Connection, clean: pd.DataFrame, quarantine: pd.DataFrame, audit: pd.DataFrame,
                   run_id: str, decided_at) -> int:
    dates = pd.concat([clean["created_at"], clean["closed_at"].dropna(), pd.Series([pd.Timestamp.now()])])
    _upsert_via_temp(conn, "analytics.dim_date", _date_dim(dates), "date_key")
    ag = _dim(conn, "analytics.dim_agency", "agency_key", ["agency_code"],
              clean.groupby("agency", as_index=False)["agency_name"].first()
              .rename(columns={"agency": "agency_code"}), update=["agency_name"])
    cp = _dim(conn, "analytics.dim_complaint", "complaint_key", ["complaint_type", "descriptor"],
              clean[["complaint_type", "descriptor"]])
    geo = _dim(conn, "analytics.dim_geography", "geography_key", ["borough", "incident_zip", "community_board"],
               clean[["borough", "incident_zip", "community_board"]])

    f = (clean.merge(ag, left_on="agency", right_on="agency_code")
         .merge(cp, on=["complaint_type", "descriptor"]).merge(geo, on=["borough", "incident_zip", "community_board"]))
    assert len(f) == len(clean), "dimension lookup lost rows"
    f["created_date_key"] = f["created_at"].dt.strftime("%Y%m%d").astype(int)
    f["closed_date_key"] = pd.to_numeric(f["closed_at"].dt.strftime("%Y%m%d"), errors="coerce").astype("Int64")
    f["loaded_run_id"] = run_id
    f["dq_issue_count"] = f["dq_issue_count"].astype(int)
    fact = f[FACT_COLUMNS]
    n = _upsert_via_temp(conn, "analytics.fact_service_request", fact, "unique_key",
                         [c for c in FACT_COLUMNS if c != "unique_key"])
    conn.exec_driver_sql("CREATE TEMP TABLE keep_keys (unique_key TEXT PRIMARY KEY) ON COMMIT DROP")
    copy_df(conn, "keep_keys", fact[["unique_key"]])
    removed = conn.exec_driver_sql("DELETE FROM analytics.fact_service_request f WHERE NOT EXISTS "
                                   "(SELECT 1 FROM keep_keys k WHERE k.unique_key = f.unique_key)").rowcount
    conn.exec_driver_sql("TRUNCATE analytics.quarantine")
    copy_df(conn, "analytics.quarantine", quarantine.assign(run_id=run_id))
    copy_df(conn, "analytics.cleaning_audit", audit.assign(run_id=run_id, decided_at=decided_at))
    log.info("fact upserted=%s stale_removed=%s quarantined=%s audit_rows=%s", n, removed, len(quarantine), len(audit))
    return len(fact)


def start_run(conn: Connection, run_id: str, mode: str, started_at, window, scope_key: str) -> None:
    conn.execute(text("INSERT INTO ops.pipeline_runs (run_id, mode, status, started_at, window_start, window_end, scope_key) "
                      "VALUES (:r, :m, 'running', :s, :ws, :we, :k)"),
                 {"r": run_id, "m": mode, "s": started_at, "ws": window[0], "we": window[1], "k": scope_key})


def finish_run(conn: Connection, run_id: str, status: str, finished_at, **metrics) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in metrics)
    conn.execute(text(f"UPDATE ops.pipeline_runs SET status=:st, finished_at=:f, "
                      f"duration_seconds = EXTRACT(EPOCH FROM (:f - started_at)){', ' + sets if sets else ''} "
                      f"WHERE run_id=:r"), {"st": status, "f": finished_at, "r": run_id, **metrics})


def last_checkpoint(conn: Connection, scope_key: str):
    """Checkpoint of the latest successful load for THIS scope, provided the current snapshot was built by a
    run with the same scope (a full refresh of another borough/date range invalidates it)."""
    snapshot_scope = conn.execute(text(
        "SELECT r.scope_key FROM staging.current_snapshot c JOIN ops.pipeline_runs r USING (run_id) LIMIT 1")).scalar()
    if snapshot_scope != scope_key:
        return None
    return conn.execute(text("SELECT max(checkpoint_updated_at) FROM ops.pipeline_runs WHERE status='succeeded' "
                             "AND mode IN ('full-refresh','incremental') AND scope_key = :k"), {"k": scope_key}).scalar()
