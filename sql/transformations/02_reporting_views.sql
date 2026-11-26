-- Reporting views consumed by Power BI, CSV exports and markdown reports.
-- Rebuilt inside every load transaction. Views are dropped first so column changes never fail half-way.
DROP VIEW IF EXISTS analytics.v_raw_vs_clean_agency, analytics.v_raw_vs_clean, ops.v_dq_rule_summary,
    ops.v_dq_issues_latest, ops.v_dq_run_summary, analytics.v_complaint_performance, analytics.v_agency_performance,
    analytics.v_open_requests, analytics.v_backlog_monthly, analytics.v_monthly_volume_rolling,
    analytics.v_monthly_volume, analytics.v_kpi_summary, analytics.v_service_requests,
    analytics.v_snapshot_raw, ops.v_latest_load_run CASCADE;

-- Latest successful load run and its reporting date (the "as of" date for current backlog).
CREATE VIEW ops.v_latest_load_run AS
SELECT run_id, started_at, (started_at AT TIME ZONE 'America/New_York')::date AS reporting_date
FROM ops.pipeline_runs
WHERE status = 'succeeded' AND mode IN ('full-refresh', 'incremental')
ORDER BY started_at DESC
LIMIT 1;

-- Denormalised fact for exports and drill-through.
CREATE VIEW analytics.v_service_requests AS
SELECT f.unique_key, f.status, f.status_group, f.created_at, f.closed_at, f.effective_closed_at, f.due_at,
       f.created_date_key, f.closed_date_key, f.channel,
       a.agency_code, a.agency_name, c.complaint_type, c.descriptor,
       g.borough, g.incident_zip, g.community_board,
       f.resolution_hours, f.resolution_days, f.include_in_resolution_metrics, f.within_analytical_target,
       f.dq_issue_count, f.dq_max_severity, f.needs_manual_review,
       to_char(f.created_at, 'YYYY-MM') AS created_month
FROM analytics.fact_service_request f
JOIN analytics.dim_agency a USING (agency_key)
JOIN analytics.dim_complaint c USING (complaint_key)
JOIN analytics.dim_geography g USING (geography_key);

-- Headline KPIs (cleaned data). Durations in hours.
CREATE VIEW analytics.v_kpi_summary AS
SELECT count(*)                                                     AS total_requests,
       count(*) FILTER (WHERE status_group = 'Closed')              AS closed_requests,
       count(*) FILTER (WHERE status_group = 'Open')                AS open_requests,
       count(*) FILTER (WHERE status_group = 'Unknown')             AS unknown_status_requests,
       round(count(*) FILTER (WHERE status_group = 'Closed')::numeric / NULLIF(count(*), 0), 4) AS resolution_rate,
       round(avg(resolution_hours), 2)                              AS avg_resolution_hours,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS median_resolution_hours,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS p90_resolution_hours,
       round(avg(within_analytical_target::int)::numeric, 4)       AS within_target_rate,
       count(*) FILTER (WHERE include_in_resolution_metrics)        AS resolution_sample
FROM analytics.fact_service_request;

-- Monthly incoming vs closed volume.
CREATE VIEW analytics.v_monthly_volume AS
WITH created AS (SELECT date_trunc('month', created_at)::date AS month, count(*) AS created_requests
                 FROM analytics.fact_service_request GROUP BY 1),
     closed AS (SELECT date_trunc('month', effective_closed_at)::date AS month, count(*) AS closed_requests
                FROM analytics.fact_service_request WHERE effective_closed_at IS NOT NULL GROUP BY 1)
SELECT COALESCE(c.month, d.month) AS month, COALESCE(created_requests, 0) AS created_requests,
       COALESCE(closed_requests, 0) AS closed_requests
FROM created c FULL JOIN closed d USING (month);

-- Exact 3-calendar-month rolling average: months are generated (zero-filled, never skipped) and the
-- average is only shown once three complete calendar months of the reporting window exist.
CREATE VIEW analytics.v_monthly_volume_rolling AS
WITH bounds AS (SELECT date_trunc('month', window_start)::date AS m0,
                       date_trunc('month', window_end - interval '1 microsecond')::date AS m1
                FROM ops.pipeline_runs WHERE run_id = (SELECT run_id FROM ops.v_latest_load_run)),
months AS (SELECT generate_series(m0, m1, interval '1 month')::date AS month FROM bounds),
counts AS (SELECT m.month, COALESCE(v.created_requests, 0) AS created_requests,
                  COALESCE(v.closed_requests, 0) AS closed_requests
           FROM months m LEFT JOIN analytics.v_monthly_volume v USING (month))
SELECT month, created_requests, closed_requests,
       CASE WHEN month >= (SELECT m0 FROM bounds) + interval '2 months'
            THEN round(avg(created_requests) OVER (ORDER BY month RANGE BETWEEN interval '2 months' PRECEDING
                                                                     AND CURRENT ROW), 2) END AS created_rolling_3m_avg
FROM counts;

-- Month-end backlog by agency: created on/before month end and not validly closed by then.
-- Closed requests with no usable close date are excluded (their open interval is unknown).
CREATE VIEW analytics.v_backlog_monthly AS
WITH month_ends AS (
    SELECT (date_trunc('month', d) + interval '1 month' - interval '1 second') AS as_of
    FROM generate_series((SELECT date_trunc('month', min(created_at)) FROM analytics.fact_service_request),
                         (SELECT date_trunc('month', max(created_at)) FROM analytics.fact_service_request),
                         interval '1 month') d)
SELECT m.as_of::date AS month_end, a.agency_code, count(*) AS backlog
FROM month_ends m
JOIN analytics.fact_service_request f
  ON f.created_at <= m.as_of
 AND (f.effective_closed_at IS NULL OR f.effective_closed_at > m.as_of)
 AND NOT (f.status_group = 'Closed' AND f.effective_closed_at IS NULL)
 AND f.status_group <> 'Unknown'
JOIN analytics.dim_agency a USING (agency_key)
GROUP BY 1, 2;

-- Current open requests with age and aging bucket as of the reporting date.
CREATE VIEW analytics.v_open_requests AS
SELECT s.unique_key, s.agency_code, s.complaint_type, s.borough, s.incident_zip, s.status, s.created_at,
       (r.reporting_date - s.created_at::date) AS age_days,
       CASE WHEN r.reporting_date - s.created_at::date <= 7  THEN '0-7'
            WHEN r.reporting_date - s.created_at::date <= 14 THEN '8-14'
            WHEN r.reporting_date - s.created_at::date <= 30 THEN '15-30'
            WHEN r.reporting_date - s.created_at::date <= 60 THEN '31-60'
            ELSE '60+' END AS aging_bucket,
       (r.reporting_date - s.created_at::date) > 7 AS overdue_vs_analytical_target
FROM analytics.v_service_requests s CROSS JOIN ops.v_latest_load_run r
WHERE s.status_group = 'Open';

CREATE VIEW analytics.v_agency_performance AS
SELECT agency_code, max(agency_name) AS agency_name, count(*) AS total_requests,
       count(*) FILTER (WHERE status_group = 'Closed') AS closed_requests,
       count(*) FILTER (WHERE status_group = 'Open') AS open_requests,
       round(count(*) FILTER (WHERE status_group = 'Closed')::numeric / count(*), 4) AS resolution_rate,
       round(avg(resolution_hours), 2) AS avg_resolution_hours,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS median_resolution_hours,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS p90_resolution_hours,
       round(avg(within_analytical_target::int)::numeric, 4) AS within_target_rate,
       sum(dq_issue_count) AS dq_issues,
       count(*) FILTER (WHERE dq_issue_count > 0) AS records_with_dq_issues
FROM analytics.v_service_requests
GROUP BY agency_code;

CREATE VIEW analytics.v_complaint_performance AS
SELECT agency_code, complaint_type, count(*) AS total_requests,
       count(*) FILTER (WHERE status_group = 'Open') AS open_requests,
       round(avg(resolution_hours), 2) AS avg_resolution_hours,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS median_resolution_hours,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS p90_resolution_hours,
       round(avg(within_analytical_target::int)::numeric, 4) AS within_target_rate
FROM analytics.v_service_requests
GROUP BY agency_code, complaint_type;

-- Issues from the latest load run with record attributes, for monitoring and drill-through.
CREATE VIEW ops.v_dq_issues_latest AS
SELECT i.issue_id, i.unique_key, i.record_hash, i.rule_id, r.rule_name, i.issue_category, i.severity,
       i.affected_column, i.original_value, i.explanation, i.recommended_treatment, i.resolution_status,
       i.detected_at, s.agency, s.complaint_type, s.status, s.created_at, s.closed_at, s.borough,
       to_char(s.created_at, 'YYYY-MM') AS created_month
FROM ops.dq_issues i
JOIN ops.v_latest_load_run lr ON lr.run_id = i.run_id
JOIN ops.dq_rules r USING (rule_id)
JOIN staging.service_requests s USING (record_hash);

CREATE VIEW ops.v_dq_rule_summary AS
SELECT r.rule_id, r.rule_name, r.category, r.severity, r.treatment,
       count(i.issue_id) AS issues, count(DISTINCT i.record_hash) AS affected_records
FROM ops.dq_rules r
LEFT JOIN ops.v_dq_issues_latest i USING (rule_id)
GROUP BY 1, 2, 3, 4, 5;

-- Data-quality headline rates for the latest load run, with explicit denominators.
CREATE VIEW ops.v_dq_run_summary AS
SELECT r.run_id, r.records_inspected, r.records_affected,
       round(1 - r.records_affected::numeric / NULLIF(r.records_inspected, 0), 6) AS record_pass_rate,
       r.requests_inspected, r.requests_affected,
       round(1 - r.requests_affected::numeric / NULLIF(r.requests_inspected, 0), 6) AS request_pass_rate,
       r.issues_detected AS total_issues
FROM ops.pipeline_runs r JOIN ops.v_latest_load_run USING (run_id);

-- Rows of the current source snapshot ("raw" for comparisons; superseded history excluded).
CREATE VIEW analytics.v_snapshot_raw AS
SELECT s.* FROM staging.service_requests s JOIN staging.current_snapshot USING (record_hash);

-- Raw-vs-cleaned KPI comparison with identical formulas. Rates are in percent, durations in hours.
-- "Raw" = every snapshot row; any non-null closed_date gives a duration (negative and open-with-date included).
CREATE VIEW analytics.v_raw_vs_clean AS
WITH raw AS (
    SELECT count(*)::numeric AS total_requests,
           count(*) FILTER (WHERE status = 'Closed')::numeric AS closed_requests,
           count(*) FILTER (WHERE status IS DISTINCT FROM 'Closed')::numeric AS open_requests,
           avg(extract(epoch FROM closed_at - created_at) / 3600) AS avg_h,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM closed_at - created_at) / 3600) AS med_h,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM closed_at - created_at) / 3600) AS p90_h,
           avg((closed_at - created_at <= interval '7 days')::int) AS within_target
    FROM analytics.v_snapshot_raw),
clean AS (
    SELECT k.total_requests::numeric, k.closed_requests::numeric, k.open_requests::numeric,
           avg(resolution_hours) AS avg_h,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric AS med_h,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric AS p90_h,
           avg(within_analytical_target::int)::numeric AS within_target
    FROM analytics.fact_service_request, analytics.v_kpi_summary k
    GROUP BY 1, 2, 3),
pairs AS (
    SELECT 'Total requests' AS metric, 1 AS ord, 'count' AS unit, r.total_requests AS raw_value, c.total_requests AS clean_value FROM raw r, clean c
    UNION ALL SELECT 'Closed requests', 2, 'count', r.closed_requests, c.closed_requests FROM raw r, clean c
    UNION ALL SELECT 'Open requests', 3, 'count', r.open_requests, c.open_requests FROM raw r, clean c
    UNION ALL SELECT 'Resolution rate (percent)', 4, 'percent', 100 * r.closed_requests / r.total_requests, 100 * c.closed_requests / c.total_requests FROM raw r, clean c
    UNION ALL SELECT 'Average resolution (hours)', 5, 'hours', r.avg_h::numeric, c.avg_h FROM raw r, clean c
    UNION ALL SELECT 'Median resolution (hours)', 6, 'hours', r.med_h::numeric, c.med_h FROM raw r, clean c
    UNION ALL SELECT 'P90 resolution (hours)', 7, 'hours', r.p90_h::numeric, c.p90_h FROM raw r, clean c
    UNION ALL SELECT 'Within 7-day analytical target (percent)', 8, 'percent', 100 * r.within_target::numeric, 100 * c.within_target FROM raw r, clean c)
SELECT metric, ord, unit, round(raw_value, 4) AS raw_value, round(clean_value, 4) AS clean_value,
       round(clean_value - raw_value, 4) AS abs_diff,
       round(100 * (clean_value - raw_value) / NULLIF(raw_value, 0), 3) AS pct_diff
FROM pairs ORDER BY ord;

-- Agency-level raw vs cleaned resolution hours (unrounded inputs; rounding only on output).
CREATE VIEW analytics.v_raw_vs_clean_agency AS
WITH raw AS (
    SELECT COALESCE(agency, 'UNKNOWN') AS agency_code,
           avg(extract(epoch FROM closed_at - created_at) / 3600) AS raw_avg_h,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM closed_at - created_at) / 3600) AS raw_med_h,
           count(closed_at) AS raw_n
    FROM analytics.v_snapshot_raw GROUP BY 1),
clean AS (
    SELECT a.agency_code, avg(f.resolution_hours) AS avg_h,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours) AS med_h, count(f.resolution_hours) AS n
    FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key) GROUP BY 1)
SELECT c.agency_code, raw.raw_n, c.n AS clean_n,
       round(raw.raw_avg_h::numeric, 2) AS raw_avg_hours, round(c.avg_h, 2) AS clean_avg_hours,
       round(c.avg_h - raw.raw_avg_h::numeric, 2) AS avg_abs_diff,
       round(100 * (c.avg_h - raw.raw_avg_h::numeric) / NULLIF(raw.raw_avg_h::numeric, 0), 3) AS avg_pct_diff,
       round(raw.raw_med_h::numeric, 2) AS raw_median_hours, round(c.med_h::numeric, 2) AS clean_median_hours,
       round((100 * (c.med_h - raw.raw_med_h) / NULLIF(raw.raw_med_h, 0))::numeric, 3) AS median_pct_diff
FROM clean c JOIN raw USING (agency_code);
