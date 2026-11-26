-- Reporting views consumed by Power BI, CSV exports and markdown reports.
-- Rebuilt at the end of every load run (CREATE OR REPLACE = idempotent).

-- Latest successful load run and its reporting date (the "as of" date for current backlog).
CREATE OR REPLACE VIEW ops.v_latest_load_run AS
SELECT run_id, started_at, (started_at AT TIME ZONE 'America/New_York')::date AS reporting_date
FROM ops.pipeline_runs
WHERE status = 'succeeded' AND mode IN ('full-refresh', 'incremental')
ORDER BY started_at DESC
LIMIT 1;

-- Denormalised fact for exports and drill-through.
CREATE OR REPLACE VIEW analytics.v_service_requests AS
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
CREATE OR REPLACE VIEW analytics.v_kpi_summary AS
SELECT count(*)                                                     AS total_requests,
       count(*) FILTER (WHERE status_group = 'Closed')              AS closed_requests,
       count(*) FILTER (WHERE status_group = 'Open')                AS open_requests,
       round(count(*) FILTER (WHERE status_group = 'Closed')::numeric / NULLIF(count(*), 0), 4) AS resolution_rate,
       round(avg(resolution_hours), 2)                              AS avg_resolution_hours,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS median_resolution_hours,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS p90_resolution_hours,
       round(avg(within_analytical_target::int)::numeric, 4)       AS within_target_rate,
       count(*) FILTER (WHERE include_in_resolution_metrics)        AS resolution_sample
FROM analytics.fact_service_request;

-- Monthly incoming vs closed volume.
CREATE OR REPLACE VIEW analytics.v_monthly_volume AS
WITH created AS (SELECT date_trunc('month', created_at)::date AS month, count(*) AS created_requests
                 FROM analytics.fact_service_request GROUP BY 1),
     closed AS (SELECT date_trunc('month', effective_closed_at)::date AS month, count(*) AS closed_requests
                FROM analytics.fact_service_request WHERE effective_closed_at IS NOT NULL GROUP BY 1)
SELECT COALESCE(c.month, d.month) AS month, COALESCE(created_requests, 0) AS created_requests,
       COALESCE(closed_requests, 0) AS closed_requests
FROM created c FULL JOIN closed d USING (month);

-- Month-end backlog by agency: created on/before month end and not validly closed by then.
-- Closed requests with no usable close date are excluded (their open interval is unknown).
CREATE OR REPLACE VIEW analytics.v_backlog_monthly AS
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
JOIN analytics.dim_agency a USING (agency_key)
GROUP BY 1, 2;

-- Current open requests with age and aging bucket as of the reporting date.
CREATE OR REPLACE VIEW analytics.v_open_requests AS
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

CREATE OR REPLACE VIEW analytics.v_agency_performance AS
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

CREATE OR REPLACE VIEW analytics.v_complaint_performance AS
SELECT agency_code, complaint_type, count(*) AS total_requests,
       count(*) FILTER (WHERE status_group = 'Open') AS open_requests,
       round(avg(resolution_hours), 2) AS avg_resolution_hours,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS median_resolution_hours,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS p90_resolution_hours,
       round(avg(within_analytical_target::int)::numeric, 4) AS within_target_rate
FROM analytics.v_service_requests
GROUP BY agency_code, complaint_type;

-- Issues from the latest load run with record attributes, for monitoring and drill-through.
CREATE OR REPLACE VIEW ops.v_dq_issues_latest AS
SELECT i.issue_id, i.unique_key, i.record_hash, i.rule_id, r.rule_name, i.issue_category, i.severity,
       i.affected_column, i.original_value, i.explanation, i.recommended_treatment, i.resolution_status,
       i.detected_at, s.agency, s.complaint_type, s.status, s.created_at, s.closed_at, s.borough,
       to_char(s.created_at, 'YYYY-MM') AS created_month
FROM ops.dq_issues i
JOIN ops.v_latest_load_run lr ON lr.run_id = i.run_id
JOIN ops.dq_rules r USING (rule_id)
JOIN staging.service_requests s USING (record_hash);

CREATE OR REPLACE VIEW ops.v_dq_rule_summary AS
SELECT r.rule_id, r.rule_name, r.category, r.severity, r.treatment,
       count(i.issue_id) AS issues, count(DISTINCT i.record_hash) AS affected_records
FROM ops.dq_rules r
LEFT JOIN ops.v_dq_issues_latest i USING (rule_id)
GROUP BY 1, 2, 3, 4, 5;

-- Raw-vs-cleaned KPI comparison with identical formulas.
-- "Raw" = every staging row in the window, any non-null closed_date gives a duration (naive report).
CREATE OR REPLACE VIEW analytics.v_raw_vs_clean AS
WITH lr AS (SELECT window_start, window_end, started_at FROM ops.pipeline_runs
            WHERE run_id = (SELECT run_id FROM ops.v_latest_load_run)),
raw AS (
    SELECT count(*)::numeric AS total_requests,
           count(*) FILTER (WHERE status = 'Closed')::numeric AS closed_requests,
           count(*) FILTER (WHERE status IS DISTINCT FROM 'Closed')::numeric AS open_requests,
           avg(extract(epoch FROM closed_at - created_at) / 3600) AS avg_h,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM closed_at - created_at) / 3600) AS med_h,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM closed_at - created_at) / 3600) AS p90_h,
           avg((closed_at - created_at <= interval '7 days')::int) AS within_target
    FROM staging.service_requests, lr
    WHERE created_at BETWEEN lr.window_start AND lr.window_end),
clean AS (
    SELECT total_requests::numeric, closed_requests::numeric, open_requests::numeric,
           avg_resolution_hours AS avg_h, median_resolution_hours AS med_h, p90_resolution_hours AS p90_h,
           within_target_rate AS within_target
    FROM analytics.v_kpi_summary),
pairs AS (
    SELECT 'Total requests' AS metric, 1 AS ord, r.total_requests AS raw_value, c.total_requests AS clean_value FROM raw r, clean c
    UNION ALL SELECT 'Closed requests', 2, r.closed_requests, c.closed_requests FROM raw r, clean c
    UNION ALL SELECT 'Open requests (backlog at reporting date)', 3, r.open_requests, c.open_requests FROM raw r, clean c
    UNION ALL SELECT 'Resolution rate', 4, r.closed_requests / r.total_requests, c.closed_requests / c.total_requests FROM raw r, clean c
    UNION ALL SELECT 'Average resolution (hours)', 5, r.avg_h::numeric, c.avg_h FROM raw r, clean c
    UNION ALL SELECT 'Median resolution (hours)', 6, r.med_h::numeric, c.med_h FROM raw r, clean c
    UNION ALL SELECT 'P90 resolution (hours)', 7, r.p90_h::numeric, c.p90_h FROM raw r, clean c
    UNION ALL SELECT 'Within 7-day analytical target', 8, r.within_target::numeric, c.within_target FROM raw r, clean c)
SELECT metric, ord, round(raw_value, 4) AS raw_value, round(clean_value, 4) AS clean_value,
       round(clean_value - raw_value, 4) AS abs_diff,
       round(100 * (clean_value - raw_value) / NULLIF(raw_value, 0), 3) AS pct_diff
FROM pairs ORDER BY ord;

-- Agency-level raw vs cleaned average/median resolution hours.
CREATE OR REPLACE VIEW analytics.v_raw_vs_clean_agency AS
WITH lr AS (SELECT window_start, window_end FROM ops.pipeline_runs
            WHERE run_id = (SELECT run_id FROM ops.v_latest_load_run)),
raw AS (
    SELECT COALESCE(agency, 'UNKNOWN') AS agency_code,
           avg(extract(epoch FROM closed_at - created_at) / 3600) AS raw_avg_h,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM closed_at - created_at) / 3600) AS raw_med_h,
           count(closed_at) AS raw_n
    FROM staging.service_requests, lr WHERE created_at BETWEEN lr.window_start AND lr.window_end GROUP BY 1)
SELECT a.agency_code, raw.raw_n, round(raw.raw_avg_h::numeric, 2) AS raw_avg_hours,
       a.avg_resolution_hours AS clean_avg_hours,
       round(a.avg_resolution_hours - raw.raw_avg_h::numeric, 2) AS avg_abs_diff,
       round(100 * (a.avg_resolution_hours - raw.raw_avg_h::numeric) / NULLIF(raw.raw_avg_h::numeric, 0), 3) AS avg_pct_diff,
       round(raw.raw_med_h::numeric, 2) AS raw_median_hours, a.median_resolution_hours AS clean_median_hours
FROM analytics.v_agency_performance a JOIN raw USING (agency_code);
