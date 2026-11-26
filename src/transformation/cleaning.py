"""Treatment policy: turns validated staging rows + issues into analytics-ready rows.

Policy (see docs/validation_framework.md):
  deduplicate                     -> keep one version per unique_key (latest), drop the rest
  quarantine                      -> remove from analytics entirely (kept in raw/staging + quarantine table)
  exclude_from_resolution_metrics -> keep for volume/closure counts, NULL the resolution duration
  manual_review                   -> keep, set needs_manual_review; resolution excluded if DQ011
  retain                          -> keep unchanged, flagged only
Every decision is written to the audit frame.
"""
import pandas as pd

from src.validation.framework import SEVERITY_ORDER

RESOLUTION_EXCLUDING_RULES = {"DQ005", "DQ006", "DQ008", "DQ011"}


def clean(df: pd.DataFrame, issues: pd.DataFrame, rules_cfg: dict, settings: dict):
    """Returns (clean_df, quarantine_df, audit_df)."""
    ref = rules_cfg["reference"]
    treatment = {r["id"]: r["treatment"] for r in rules_cfg["rules"]}
    audit = []

    def log(rows, action, rule_ids, detail):
        for h, k in zip(rows["record_hash"], rows["unique_key"]):
            audit.append({"record_hash": h, "unique_key": k, "action": action, "rule_ids": rule_ids, "detail": detail})

    by_hash = issues.groupby("record_hash")["rule_id"].agg(lambda s: ",".join(sorted(set(s)))) \
        if not issues.empty else pd.Series(dtype="string")

    # 1. exact duplicates: one row per hash
    dup_copies = df[df["record_hash"].duplicated()]
    log(dup_copies, "deduplicated_dropped", "DQ002", "exact duplicate copy removed")
    work = df.drop_duplicates("record_hash").copy()

    # 2. quarantine critical records
    q_rules = {r for r, t in treatment.items() if t == "quarantine"}
    q_hashes = set(issues.loc[issues["rule_id"].isin(q_rules), "record_hash"]) if not issues.empty else set()
    quarantine = work[work["record_hash"].isin(q_hashes)][["record_hash", "unique_key"]].copy()
    quarantine["rule_ids"] = quarantine["record_hash"].map(by_hash).astype("string")
    quarantine["reason"] = "critical data quality issue: " + quarantine["rule_ids"]
    log(quarantine, "quarantined", None, "removed from analytics; original retained in raw/staging")
    work = work[~work["record_hash"].isin(q_hashes)]

    # 3. superseded versions of the same unique_key
    superseded = set(issues.loc[issues["rule_id"] == "DQ001", "record_hash"]) if not issues.empty else set()
    dropped = work[work["record_hash"].isin(superseded)]
    log(dropped, "deduplicated_dropped", "DQ001", "superseded version; latest version of unique_key kept")
    work = work[~work["record_hash"].isin(superseded)]
    # safety net: guarantee one row per key even if two versions tie on update time
    work = work.sort_values("source_updated_at", na_position="first").drop_duplicates("unique_key", keep="last")

    # 4. derived fields
    rule_sets = work["record_hash"].map(by_hash).astype("string").fillna("")
    issue_rules = rule_sets.str.split(",").apply(lambda xs: {x for x in xs if x})
    work["status_group"] = work["status"].isin(ref["closed_statuses"]).map({True: "Closed", False: "Open"})
    excluded = issue_rules.apply(lambda s: bool(s & RESOLUTION_EXCLUDING_RULES))
    eligible = (work["status_group"] == "Closed") & work["closed_at"].notna() & ~excluded
    work["include_in_resolution_metrics"] = eligible
    hours = (work["closed_at"] - work["created_at"]).dt.total_seconds() / 3600
    work["resolution_hours"] = hours.where(eligible).round(3)
    work["resolution_days"] = (work["resolution_hours"] / 24).round(4)
    # effective close used for historical backlog: only a genuinely Closed request with a valid close
    work["effective_closed_at"] = work["closed_at"].where(eligible)
    log(work[(work["status_group"] == "Closed") & ~eligible], "excluded_from_resolution",
        None, "kept in volume/closure counts; excluded from resolution-time metrics")

    cfg = settings["analytics"]
    target = work["complaint_type"].map(cfg.get("category_targets_days") or {}).fillna(cfg["analytical_target_days"])
    work["within_analytical_target"] = (work["resolution_days"] <= target).where(eligible)

    manual = {r for r, t in treatment.items() if t == "manual_review"}
    work["needs_manual_review"] = issue_rules.apply(lambda s: bool(s & manual))
    log(work[work["needs_manual_review"]], "escalated", None, "pending manual review")
    work["dq_issue_count"] = issue_rules.apply(len)
    sev = issues.assign(o=issues["severity"].map(SEVERITY_ORDER)).sort_values("o").groupby("record_hash")["severity"].last() \
        if not issues.empty else pd.Series(dtype="string")
    work["dq_max_severity"] = work["record_hash"].map(sev)

    # 5. safe normalisation of reporting labels (NULL -> explicit Unknown label, audited)
    for col, label in [("agency", "UNKNOWN"), ("complaint_type", "Unknown"), ("descriptor", "Unspecified"),
                       ("borough", "Unspecified"), ("incident_zip", "Unknown"), ("community_board", "Unknown")]:
        miss = work[col].isna()
        if col in ("agency", "complaint_type"):
            log(work[miss], "normalized", None, f"{col} NULL reported as '{label}'")
        work[col] = work[col].fillna(label)
    work["agency_name"] = work["agency_name"].fillna(work["agency"])
    return work, quarantine, pd.DataFrame(audit, columns=["record_hash", "unique_key", "action", "rule_ids", "detail"])
