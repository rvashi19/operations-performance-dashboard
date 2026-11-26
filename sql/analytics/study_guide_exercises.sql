-- Solutions to the SQL exercises in docs/interview_study_guide.md (section 17). Output: reports/evidence/sql_exercises_output.txt
\echo '=== E1 requests and median hours per channel ==='
SELECT channel, count(*) AS requests,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_h
FROM analytics.fact_service_request GROUP BY channel ORDER BY requests DESC;

\echo '=== E2 busiest weekday per agency (top 5 agencies) ==='
SELECT agency_code, day_name, requests FROM (
  SELECT a.agency_code, d.day_name, count(*) AS requests,
         ROW_NUMBER() OVER (PARTITION BY a.agency_code ORDER BY count(*) DESC) AS rn
  FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key)
  JOIN analytics.dim_date d ON d.date_key = f.created_date_key
  GROUP BY 1, 2) t
WHERE rn = 1 AND agency_code IN ('NYPD','DSNY','DOT','DEP','HPD') ORDER BY requests DESC;

\echo '=== E3 month-over-month change in created requests ==='
SELECT to_char(month, 'YYYY-MM') AS month, created_requests,
       created_requests - LAG(created_requests) OVER (ORDER BY month) AS mom_change
FROM analytics.v_monthly_volume_rolling ORDER BY month;

\echo '=== E4 complaint types with >= 500 requests and within-target rate below 70 percent ==='
SELECT c.complaint_type, count(*) AS requests,
       round(100 * avg(f.within_analytical_target::int), 1) AS pct_within_7d
FROM analytics.fact_service_request f JOIN analytics.dim_complaint c USING (complaint_key)
GROUP BY 1 HAVING count(*) >= 500 AND avg(f.within_analytical_target::int) < 0.7
ORDER BY pct_within_7d;

\echo '=== E5 data quality issues per rule as share of all issues ==='
SELECT rule_id, count(*) AS issues, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_issues
FROM ops.v_dq_issues_latest GROUP BY 1 ORDER BY 2 DESC;

\echo '=== E6 agencies whose open backlog share exceeds the overall share ==='
SELECT agency_code, open_requests, total_requests, round(100.0 * open_requests / total_requests, 2) AS pct_open
FROM analytics.v_agency_performance
WHERE open_requests::numeric / total_requests > (SELECT open_requests::numeric / total_requests FROM analytics.v_kpi_summary)
ORDER BY pct_open DESC;

\echo '=== E7 top 3 ZIPs by median resolution, min 1000 resolved, with DENSE_RANK ==='
SELECT * FROM (
  SELECT g.incident_zip, count(f.resolution_hours) AS resolved,
         round(percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours)::numeric, 1) AS median_h,
         DENSE_RANK() OVER (ORDER BY percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours) DESC) AS rnk
  FROM analytics.fact_service_request f JOIN analytics.dim_geography g USING (geography_key)
  WHERE g.incident_zip <> 'Unknown' GROUP BY 1 HAVING count(f.resolution_hours) >= 1000) t
WHERE rnk <= 3;

\echo '=== E8 requests flagged by more than one rule ==='
SELECT unique_key, string_agg(rule_id, ',' ORDER BY rule_id) AS rules
FROM ops.v_dq_issues_latest GROUP BY unique_key HAVING count(DISTINCT rule_id) > 1 ORDER BY unique_key LIMIT 5;
SELECT count(*) AS requests_with_multiple_rules FROM (
  SELECT unique_key FROM ops.v_dq_issues_latest GROUP BY 1 HAVING count(DISTINCT rule_id) > 1) t;

\echo '=== E9 cumulative closures in 2025 (running total) ==='
SELECT to_char(month, 'YYYY-MM') AS month, closed_requests,
       sum(closed_requests) OVER (ORDER BY month) AS cumulative_closed
FROM analytics.v_monthly_volume_rolling ORDER BY month;

\echo '=== E10 percentage of each agency volume that is in its single largest complaint type ==='
WITH t AS (SELECT a.agency_code, c.complaint_type, count(*) AS n,
                  sum(count(*)) OVER (PARTITION BY a.agency_code) AS agency_total,
                  RANK() OVER (PARTITION BY a.agency_code ORDER BY count(*) DESC) AS r
           FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key)
           JOIN analytics.dim_complaint c USING (complaint_key) GROUP BY 1, 2)
SELECT agency_code, complaint_type, n, round(100.0 * n / agency_total, 1) AS pct_of_agency
FROM t WHERE r = 1 AND agency_total >= 3000 ORDER BY pct_of_agency DESC;
