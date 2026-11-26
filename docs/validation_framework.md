# Data Quality Validation Framework

## How it works

1. `config/validation_rules.yaml` declares each rule: `id`, `check`, column(s), `category`, `severity`,
   `treatment`, `explanation`, optional `params`, plus a `reference` block (documented, closed and open statuses).
2. `src/validation/framework.py` maps each `check` name to a function that returns a boolean mask over the staging
   DataFrame, the affected column, and the original value to report. `Validator.run()` produces one issue row per
   (record, rule, column) with every field the brief requires. The run id and detection time are added when the
   issues are written to `ops.dq_issues`.
3. Unknown check names in the YAML fail fast with `ValueError`.
4. `summarize()` counts **unique** affected records (`record_hash.nunique()`), so a record that fails three rules
   counts once in the affected-record percentage and the pass rate.

Adding a rule of an existing kind (for example, another `not_null` column) is a YAML-only change.

## Rules and why each is (or isn't) an error

| ID | Check | Severity | Treatment | Rationale from the documentation |
|---|---|---|---|---|
| DQ001 | Same `unique_key`, different content | high | deduplicate (keep latest `:updated_at`) | `unique_key` is documented as unique; multiple versions come from re-extraction after an update |
| DQ002 | Byte-identical record | medium | deduplicate | Pagination overlap can repeat rows |
| DQ003 | `unique_key` null | critical | quarantine | The record cannot be tracked |
| DQ004 | `created_date` null | critical | quarantine | Every volume, backlog and duration metric needs it |
| DQ005 | Status Closed and `closed_date` null | high | exclude from resolution metrics | `closed_date` is defined as the closure date, so it must exist when closed. **Open requests without a closed date are NOT flagged.** |
| DQ006 | `closed_date` < `created_date` | high | exclude from resolution metrics | Impossible duration |
| DQ007 | Non-empty, unparseable timestamp | high | quarantine | Value can't be used; original text kept in `*_raw` |
| DQ008 | Timestamp after extraction time | high | exclude from resolution metrics | `due_date` is exempt: future deadlines are legitimate |
| DQ009 | `complaint_type` null | medium | retain as "Unknown" | Counts are still valid; category breakdowns show Unknown |
| DQ010 | `agency` null | medium | manual review, label UNKNOWN | Accountability unknown |
| DQ011 | Open-type status with a `closed_date` | medium | manual review; counted as open | Contradictory state, probably reopened; the status field wins |
| DQ012 | Status not in the documented list | medium | manual review | Unknown state can't be classified |
| DQ013 | Duration > 365 days | low | retain + flag | Plausible for capital work (trees, sidewalks); shown as a sensitivity check |
| DQ014 | No ZIP **and** no coordinates | low | retain as "Unknown" geography | Only geographic breakdowns are affected |

## Treatment policy (src/transformation/cleaning.py)

| Treatment | Effect | Audit action |
|---|---|---|
| Deduplication | Keep one row per hash, then the latest version per `unique_key` | `deduplicated_dropped` |
| Safe normalisation | NULL agency/category/geography → explicit Unknown labels; trimming and upper-casing happen in staging | `normalized` |
| Retain legitimate nulls | Open requests keep NULL closed date and duration | none |
| Quarantine | Row removed from analytics and written to `analytics.quarantine` (still in raw/staging) | `quarantined` |
| Exclude from affected metrics only | Still counted in volume and closure rate; duration NULL; not in historical backlog if Closed | `excluded_from_resolution` |
| Escalate | `needs_manual_review = true`; issue `resolution_status = pending_manual_review` | `escalated` |

Original data is never modified: raw JSON is immutable, staging keeps the original timestamp text, and every
decision is written to `analytics.cleaning_audit` with its run id.

## Outputs

* `ops.dq_issues`: issue detail (drill-through in Power BI page 4)
* `ops.v_dq_rule_summary`, `ops.v_dq_issues_latest`: views for the latest load run
* `reports/data_quality_report.md`: totals, missing-value %, duplicate %, pass rate, by category, severity, agency
  and month, and records needing manual review

## Latest results

134,348 inspected · 132,900 valid · 1,448 affected (1.078%) · 1,467 issues · pass rate 98.922% · 191 for manual
review. See `reports/data_quality_report.md`.
