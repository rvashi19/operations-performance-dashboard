"""Configurable data-quality validation framework.

Each rule in config/validation_rules.yaml names a `check`; the check returns a boolean mask of
failing rows plus the column and original value to report. Adding a rule normally means adding
YAML only; adding a new *kind* of check means registering one function in CHECKS.
"""
import logging
from datetime import datetime

import pandas as pd

log = logging.getLogger(__name__)

ISSUE_COLUMNS = ["record_hash", "unique_key", "rule_id", "issue_category", "severity", "affected_column",
                 "original_value", "explanation", "recommended_treatment", "resolution_status"]
TS_RAW = {"created_date": ("created_at", "created_date_raw"), "closed_date": ("closed_at", "closed_date_raw"),
          "due_date": ("due_at", "due_date_raw"),
          "resolution_action_updated_date": ("resolution_updated_at", "resolution_updated_raw")}
COLUMN_MAP = {"created_date": "created_at", "closed_date": "closed_at"}  # source name -> staging name
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _col(df, name):
    return df[COLUMN_MAP.get(name, name)]


def _closed(df, ref):
    return df["status"].isin(ref["closed_statuses"])


def check_not_null(df, rule, ref, now):
    return [(_col(df, rule["column"]).isna(), rule["column"], pd.Series(pd.NA, index=df.index))]


def check_duplicate_key(df, rule, ref, now):
    """Flags superseded versions of a key; the most recently updated version is kept."""
    has_key = df["unique_key"].notna()
    distinct = df[has_key].drop_duplicates("record_hash")
    order = distinct.sort_values(["unique_key", "source_updated_at", "resolution_updated_at"],
                                 na_position="first")
    latest = set(order.groupby("unique_key").tail(1)["record_hash"])
    multi = distinct["unique_key"].duplicated(keep=False)
    superseded = set(distinct.loc[multi, "record_hash"]) - latest
    mask = df["record_hash"].isin(superseded) & ~df["record_hash"].duplicated()
    return [(mask, "unique_key", df["unique_key"])]


def check_exact_duplicate(df, rule, ref, now):
    return [(df["record_hash"].duplicated(keep="first"), "*", df["record_hash"])]


def check_closed_requires_date(df, rule, ref, now):
    return [(_closed(df, ref) & df["closed_at"].isna() & df["closed_date_raw"].isna(), "closed_date", df["status"])]


def check_closed_before_created(df, rule, ref, now):
    return [(df["closed_at"] < df["created_at"], "closed_date", df["closed_date_raw"])]


def check_invalid_timestamp(df, rule, ref, now):
    out = []
    for c in rule["columns"]:
        typed, raw = TS_RAW[c]
        out.append((df[raw].notna() & df[typed].isna(), c, df[raw]))
    return out


def check_future_timestamp(df, rule, ref, now):
    out = []
    for c in rule["columns"]:
        typed, raw = TS_RAW[c]
        out.append((df[typed] > now, c, df[raw]))
    return out


def check_open_with_closed_date(df, rule, ref, now):
    return [(df["status"].isin(ref["open_statuses"]) & df["closed_at"].notna(), "status",
             df["status"] + " | closed_date=" + df["closed_date_raw"].fillna(""))]


def check_allowed_values(df, rule, ref, now):
    allowed = set(ref["documented_statuses"])
    return [(df[rule["column"]].notna() & ~df[rule["column"]].isin(allowed), rule["column"], df[rule["column"]])]


def check_extreme_duration(df, rule, ref, now):
    days = (df["closed_at"] - df["created_at"]).dt.total_seconds() / 86400
    return [(days > rule["params"]["max_days"], "closed_date", days.round(1).astype("string"))]


def check_missing_geography(df, rule, ref, now):
    mask = df["incident_zip"].isna() & (df["latitude"].isna() | df["longitude"].isna())
    return [(mask, "incident_zip", pd.Series(pd.NA, index=df.index))]


CHECKS = {f.__name__.removeprefix("check_"): f for f in [
    check_not_null, check_duplicate_key, check_exact_duplicate, check_closed_requires_date,
    check_closed_before_created, check_invalid_timestamp, check_future_timestamp,
    check_open_with_closed_date, check_allowed_values, check_extreme_duration, check_missing_geography]}


class Validator:
    def __init__(self, config: dict, now: datetime):
        self.rules = config["rules"]
        self.ref = config["reference"]
        self.now = pd.Timestamp(now).tz_localize(None) if pd.Timestamp(now).tzinfo else pd.Timestamp(now)
        unknown = {r["check"] for r in self.rules} - CHECKS.keys()
        if unknown:
            raise ValueError(f"validation_rules.yaml references unknown checks: {sorted(unknown)}")

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        frames = []
        if df.empty:
            return pd.DataFrame(columns=ISSUE_COLUMNS)
        for rule in self.rules:
            flagged = 0
            for mask, column, original in CHECKS[rule["check"]](df, rule, self.ref, self.now):
                mask = mask.fillna(False).astype(bool)
                flagged += int(mask.sum())
                if not mask.any():
                    continue
                hit = df.loc[mask]
                frames.append(pd.DataFrame({
                    "record_hash": hit["record_hash"].values,
                    "unique_key": hit["unique_key"].values,
                    "rule_id": rule["id"],
                    "issue_category": rule["category"],
                    "severity": rule["severity"],
                    "affected_column": column,
                    "original_value": original[mask].astype("string").str.slice(0, 500).values,
                    "explanation": rule["explanation"],
                    "recommended_treatment": rule["treatment"],
                    "resolution_status": "pending_manual_review" if rule["treatment"] == "manual_review"
                    else "auto_treated",
                }))
            log.info("rule=%s flagged=%s", rule["id"], flagged)
        if not frames:
            return pd.DataFrame(columns=ISSUE_COLUMNS)
        # exact-duplicate copies share a hash; one issue per (record, rule, column) is enough
        return (pd.concat(frames, ignore_index=True)[ISSUE_COLUMNS]
                .drop_duplicates(["record_hash", "rule_id", "affected_column"], ignore_index=True))


def summarize(df: pd.DataFrame, issues: pd.DataFrame) -> dict:
    """Record-level summary. A record with several issues is counted once in affected_records."""
    total = len(df)
    affected = issues["record_hash"].nunique() if not issues.empty else 0
    return {"records_inspected": total, "records_with_issues": int(affected),
            "records_passing": int(total - affected), "total_issues": int(len(issues)),
            "pass_rate": round((total - affected) / total, 6) if total else None}
