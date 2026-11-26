# KPI Definitions

Shared conventions:
* **Population.** Cleaned analytics rows (`analytics.fact_service_request`): one row per `unique_key` created in the
  window, after deduplication and quarantine.
* **Eligible for resolution metrics.** `include_in_resolution_metrics`: status Closed, closed date present and not
  flagged DQ005/DQ006/DQ008/DQ011. `resolution_hours` is NULL otherwise, so SQL and DAX aggregates skip it.
* **Reporting date.** Date of the latest successful load run, in America/New_York (`ops.v_latest_load_run`).
* **Raw versions** of each KPI, used for comparison, apply the same formula to every staging row
  (`analytics.v_raw_vs_clean`).

Values are from the latest run (`reports/metrics.json`).

| KPI | Purpose | Formula (numerator / denominator) | Source fields | Inclusion / exclusion | Null handling | Value | Limitations | SQL | DAX |
|---|---|---|---|---|---|---|---|---|---|
| Total requests | Demand | COUNT DISTINCT unique_key | unique_key | Quarantined rows excluded | — | 134,348 | Current state only | `v_kpi_summary.total_requests` | `[Total Requests]` |
| Closed requests | Throughput | COUNT where status_group = Closed | status | DQ005 rows still count (status says closed) | — | 132,019 | Status may lag reality (DQ011) | `closed_requests` | `[Closed Requests]` |
| Open requests | Unresolved work today | COUNT where status_group = Open | status | DQ011 counted open | — | 2,329 | All are 60+ days old because the window ended 2025-12-31 | `open_requests` | `[Open Requests]` |
| Resolution rate | Share completed | Closed / Total | status | Same population | — | 98.27% | Later months have had less time to close | `resolution_rate` | `[Resolution Rate]` |
| Average resolution time | Overall effort incl. tail | AVG(resolution_hours) over eligible | created_date, closed_date | Eligible only | NULL skipped | 275.68 h | Very sensitive to multi-month cases (−34 h without DQ013) | `avg_resolution_hours` | `[Avg Resolution Hours]` |
| Median resolution time | Typical experience | PERCENTILE_CONT(0.5) | same | Eligible only | NULL skipped | 15.30 h | Day-precision DOB and zero-duration DOHMH distort agency medians | `median_resolution_hours` | `[Median Resolution Hours]` |
| P90 resolution time | Tail commitment | PERCENTILE_CONT(0.9) (DAX: PERCENTILE.INC, same method) | same | Eligible only | NULL skipped | 335.38 h | As above | `p90_resolution_hours` | `[P90 Resolution Hours]` |
| Monthly request volume | Demand trend | COUNT by month of created_at | created_date | — | — | Jan 10,128 … Jul 13,363 | — | `v_monthly_volume.created_requests` | `[Requests Created]` |
| Monthly closure volume | Throughput trend | COUNT by month of effective_closed_at | closed_date | Only valid closures | NULL not counted | Dec 11,091 | Only closures of requests created in the window | `v_monthly_volume.closed_requests` | `[Requests Closed]` |
| Backlog (historical) | Accumulation | COUNT created ≤ D and (effective_closed_at NULL or > D), excluding Closed-with-no-valid-date | created, closed, status | Window cohort only | Closed without date excluded (interval unknown) | 2025-12-31: 6,641 | No carry-over from before 2025; reconstructed from current state | `v_backlog_monthly` | `[Backlog At Period End]` |
| Backlog (current) | Open today | COUNT status_group = Open at reporting date | status | — | — | 2,329 | — | `v_open_requests` | `[Current Backlog]` |
| Backlog aging | Age profile | reporting_date − created_date, bucketed 0–7, 8–14, 15–30, 31–60, 60+ | created_date | Open only | — | 60+: 2,329 | — | `v_open_requests.aging_bucket` | `[Current Backlog]` by bucket |
| SLA compliance | **Not calculated.** `due_date` is 0.28% populated and is an update date, not a deadline | — | — | — | — | — | — | — | — |
| Analytical target compliance (labelled substitute) | Speed vs internal 7-day target | within_analytical_target = TRUE / eligible | resolution_days | Eligible only | NULL not eligible | 83.02% | The target is an analyst's assumption, configurable per category in `settings.yaml` | `within_target_rate` | `[Analytical Target Compliance %]` |
| Overdue requests | Late work | Open and age > 7 days (analytical target) | created_date, status | Open only | — | 2,329 | Same caveat as the target | `v_open_requests.overdue_vs_analytical_target` | `[Overdue Open Requests]` |
| Data quality pass rate | Trust in reporting | (inspected − unique affected) / inspected | all validated fields | All staging rows in window | Legitimate nulls do not fail | 98.922% | Only as good as the rule set | `ops.v_dq_issues_latest` + staging count | `[DQ Pass Rate]` |

**Current vs historical backlog.** "Open requests" is the state on the reporting date (2026-11-25). "Backlog at
period end" reconstructs, for each past month end, how many requests from the window were still unresolved, using
today's close dates.
