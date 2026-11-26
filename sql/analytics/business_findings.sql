-- Evidence queries for reports/business_findings.md. Output is saved to reports/evidence/business_findings_output.txt
-- docker exec -i ops311_postgres psql -U ops -d ops311 -P pager=off < sql/analytics/business_findings.sql

\echo '=== F0. Headline raw vs cleaned ==='
SELECT metric, unit, raw_value, clean_value, abs_diff, pct_diff FROM analytics.v_raw_vs_clean ORDER BY ord;

\echo '=== F1a. Why mean >> median: distribution of valid resolution hours ==='
SELECT count(*) AS n,
       round(avg(resolution_hours), 1) AS mean_h,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_h,
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS p75_h,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS p90_h,
       round(percentile_cont(0.99) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS p99_h,
       round(max(resolution_hours), 1) AS max_h
FROM analytics.fact_service_request WHERE include_in_resolution_metrics;

\echo '=== F1b. Share of total resolution hours contributed by the slowest 1% / 5% / 10% of requests ==='
WITH r AS (SELECT resolution_hours h, ntile(100) OVER (ORDER BY resolution_hours DESC) AS pct
           FROM analytics.fact_service_request WHERE include_in_resolution_metrics)
SELECT round(100 * sum(h) FILTER (WHERE pct <= 1) / sum(h), 1) AS slowest_1pct_share,
       round(100 * sum(h) FILTER (WHERE pct <= 5) / sum(h), 1) AS slowest_5pct_share,
       round(100 * sum(h) FILTER (WHERE pct <= 10) / sum(h), 1) AS slowest_10pct_share
FROM r;

\echo '=== F1c. Contribution of each agency to the overall mean (share of all resolution hours) ==='
SELECT a.agency_code, count(*) AS resolved, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_requests,
       round(100 * sum(f.resolution_hours) / sum(sum(f.resolution_hours)) OVER (), 1) AS pct_of_hours,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours)::numeric, 1) AS median_h
FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key)
WHERE f.include_in_resolution_metrics
GROUP BY 1 ORDER BY pct_of_hours DESC LIMIT 6;

\echo '=== F2a. DOB raw vs cleaned durations ==='
SELECT * FROM analytics.v_raw_vs_clean_agency WHERE agency_code = 'DOB';

\echo '=== F2b. DOB records removed from the duration sample, by rule and status ==='
SELECT i.rule_id, s.status, count(*) AS records,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM s.closed_at - s.created_at) / 3600)::numeric, 1) AS median_raw_h,
       round(min(extract(epoch FROM s.closed_at - s.created_at) / 3600)::numeric, 1) AS min_raw_h
FROM ops.v_dq_issues_latest i JOIN analytics.v_snapshot_raw s USING (record_hash)
WHERE s.agency = 'DOB' AND i.rule_id IN ('DQ005', 'DQ006', 'DQ008', 'DQ011') AND s.closed_at IS NOT NULL
GROUP BY 1, 2 ORDER BY 3 DESC;

\echo '=== F2c. Where the removed DOB durations sit relative to the DOB median ==='
WITH dob AS (SELECT s.record_hash, extract(epoch FROM s.closed_at - s.created_at) / 3600 AS h,
                    EXISTS (SELECT 1 FROM ops.v_dq_issues_latest i WHERE i.record_hash = s.record_hash AND i.rule_id = 'DQ011') AS dq011
             FROM analytics.v_snapshot_raw s WHERE s.agency = 'DOB' AND s.closed_at IS NOT NULL)
SELECT dq011, count(*) AS n, count(*) FILTER (WHERE h < 512.43) AS below_raw_median,
       count(*) FILTER (WHERE h < 24) AS under_one_day
FROM dob GROUP BY 1;

\echo '=== F3a. DHS before/after: the 62 Closed-without-date requests ==='
SELECT (s.closed_at IS NULL) AS closed_date_missing, count(*) AS requests, min(s.created_at)::date AS first_created,
       max(s.created_at)::date AS last_created,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM s.closed_at - s.created_at) / 3600)::numeric, 2) AS median_h
FROM analytics.v_snapshot_raw s WHERE s.agency = 'DHS' GROUP BY 1;

\echo '=== F3b. DHS requests per month and how many lack a closed date ==='
SELECT to_char(created_at, 'YYYY-MM') AS month, count(*) AS requests, count(*) FILTER (WHERE closed_at IS NULL) AS no_closed_date
FROM analytics.v_snapshot_raw WHERE agency = 'DHS' GROUP BY 1 ORDER BY 1;

\echo '=== F4a. The 459 requests over 365 days: by agency and complaint ==='
SELECT s.agency, s.complaint_type, count(*) AS n,
       round(avg(extract(epoch FROM s.closed_at - s.created_at) / 86400)) AS avg_days
FROM ops.v_dq_issues_latest i JOIN analytics.v_snapshot_raw s USING (record_hash)
WHERE i.rule_id = 'DQ013' GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 8;

\echo '=== F4b. Sensitivity: headline metrics with and without the >365-day requests ==='
SELECT 'all valid' AS sample, count(*) n, round(avg(resolution_hours), 1) AS mean_h,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2) AS median_h,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS p90_h
FROM analytics.fact_service_request WHERE include_in_resolution_metrics
UNION ALL
SELECT 'excluding > 365 days', count(*), round(avg(resolution_hours), 1),
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 2),
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1)
FROM analytics.fact_service_request WHERE include_in_resolution_metrics AND resolution_hours <= 365 * 24;

\echo '=== F4c. Do long-duration closures carry a plausible completion text? (top resolution texts) ==='
SELECT left(s.resolution_description, 90) AS resolution_text, count(*)
FROM ops.v_dq_issues_latest i JOIN analytics.v_snapshot_raw s USING (record_hash)
WHERE i.rule_id = 'DQ013' GROUP BY 1 ORDER BY 2 DESC LIMIT 5;

\echo '=== F5. DST-ambiguous timestamps (DQ015) ==='
SELECT i.affected_column, to_char(s.created_at, 'YYYY-MM-DD') AS created_day, s.agency, count(*)
FROM ops.v_dq_issues_latest i JOIN analytics.v_snapshot_raw s USING (record_hash)
WHERE i.rule_id = 'DQ015' GROUP BY 1, 2, 3 ORDER BY 4 DESC;

\echo '=== F6. Aggregate vs agency data quality (request level, published) ==='
SELECT agency_code, total_requests, records_with_dq_issues,
       round(100.0 * records_with_dq_issues / total_requests, 2) AS pct_affected
FROM analytics.v_agency_performance ORDER BY pct_affected DESC LIMIT 6;
SELECT * FROM ops.v_dq_run_summary;

\echo '=== F7. Right-censoring: share of requests still open by creation month ==='
SELECT to_char(created_at, 'YYYY-MM') AS month, count(*) AS created,
       round(100.0 * count(*) FILTER (WHERE status_group = 'Open') / count(*), 2) AS pct_still_open,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_h
FROM analytics.fact_service_request GROUP BY 1 ORDER BY 1;

\echo '=== F8. Exact rolling 3-month average of created requests ==='
SELECT * FROM analytics.v_monthly_volume_rolling;
