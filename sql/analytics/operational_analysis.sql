-- =====================================================================================
-- Operational & data-quality analysis queries (PostgreSQL 16).
-- Run: docker exec -i ops311_postgres psql -U ops -d ops311 < sql/analytics/operational_analysis.sql
-- All durations come from analytics.fact_service_request.resolution_hours, which is NULL for
-- records excluded from resolution metrics, so aggregates ignore them automatically.
-- =====================================================================================

-- Q1. Which agencies have the highest request volumes?
-- Purpose: workload distribution; who receives the demand. (INNER JOIN, GROUP BY, RANK)
SELECT a.agency_code, a.agency_name, count(*) AS requests,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_of_total,
       RANK() OVER (ORDER BY count(*) DESC) AS volume_rank
FROM analytics.fact_service_request f
JOIN analytics.dim_agency a ON a.agency_key = f.agency_key
GROUP BY a.agency_code, a.agency_name
ORDER BY requests DESC;

-- Q2. Which complaint categories have the longest median resolution time (min 100 resolved)?
-- Purpose: identify slow service lines; median avoids skew from multi-month cases. (percentile_cont, HAVING)
SELECT c.complaint_type, count(f.resolution_hours) AS resolved,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours)::numeric / 24, 2) AS median_days
FROM analytics.fact_service_request f
JOIN analytics.dim_complaint c ON c.complaint_key = f.complaint_key
GROUP BY c.complaint_type
HAVING count(f.resolution_hours) >= 100
ORDER BY median_days DESC
LIMIT 15;

-- Q3. How does monthly demand compare with closure volume?
-- Purpose: closures < demand means backlog is building. (CTE, LEFT JOIN, date_trunc)
WITH created AS (SELECT date_trunc('month', created_at) AS m, count(*) AS created FROM analytics.fact_service_request GROUP BY 1),
     closed  AS (SELECT date_trunc('month', effective_closed_at) AS m, count(*) AS closed
                 FROM analytics.fact_service_request WHERE effective_closed_at IS NOT NULL GROUP BY 1)
SELECT to_char(cr.m, 'YYYY-MM') AS month, cr.created, COALESCE(cl.closed, 0) AS closed,
       cr.created - COALESCE(cl.closed, 0) AS net_change,
       sum(cr.created - COALESCE(cl.closed, 0)) OVER (ORDER BY cr.m) AS cumulative_net
FROM created cr LEFT JOIN closed cl ON cl.m = cr.m
ORDER BY cr.m;

-- Q4. Which agencies have increasing backlog? (month-end backlog trend, LAG window function)
-- Purpose: early warning for agencies falling behind. Compares last vs first month-end and month-over-month.
WITH b AS (SELECT agency_code, month_end, backlog,
                  backlog - LAG(backlog) OVER (PARTITION BY agency_code ORDER BY month_end) AS mom_change
           FROM analytics.v_backlog_monthly)
SELECT agency_code,
       min(backlog) FILTER (WHERE month_end = (SELECT min(month_end) FROM b)) AS first_month_backlog,
       min(backlog) FILTER (WHERE month_end = (SELECT max(month_end) FROM b)) AS last_month_backlog,
       count(*) FILTER (WHERE mom_change > 0) AS months_increasing
FROM b GROUP BY agency_code
HAVING min(backlog) FILTER (WHERE month_end = (SELECT max(month_end) FROM b)) >
       COALESCE(min(backlog) FILTER (WHERE month_end = (SELECT min(month_end) FROM b)), 0)
ORDER BY last_month_backlog DESC;

-- Q5. Which complaint categories contribute most to overdue requests?
-- Purpose: target remediation. "Overdue" = open longer than the 7-day ANALYTICAL target (no official SLA in source).
SELECT complaint_type, agency_code, count(*) AS overdue_open,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_of_overdue,
       DENSE_RANK() OVER (ORDER BY count(*) DESC) AS rnk
FROM analytics.v_open_requests
WHERE overdue_vs_analytical_target
GROUP BY complaint_type, agency_code
ORDER BY overdue_open DESC
LIMIT 15;

-- Q6. Which geographical areas (ZIP codes) experience the longest resolution times?
-- Purpose: equity / geographic service gaps. (JOIN geography, HAVING min sample)
SELECT g.incident_zip, count(f.resolution_hours) AS resolved,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours)::numeric, 1) AS median_hours,
       round(avg(f.resolution_hours), 1) AS avg_hours
FROM analytics.fact_service_request f
JOIN analytics.dim_geography g ON g.geography_key = f.geography_key
WHERE g.incident_zip <> 'Unknown'
GROUP BY g.incident_zip
HAVING count(f.resolution_hours) >= 200
ORDER BY median_hours DESC;

-- Q7. Are resolution times improving over time? 3-month rolling median proxy via rolling average of monthly medians.
-- Purpose: trend in service performance. (window frame ROWS BETWEEN)
WITH m AS (SELECT date_trunc('month', created_at) AS month,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours) AS median_h,
                  avg(resolution_hours) AS avg_h
           FROM analytics.fact_service_request GROUP BY 1)
SELECT to_char(month, 'YYYY-MM') AS month, round(median_h::numeric, 2) AS median_hours, round(avg_h, 2) AS avg_hours,
       round(avg(median_h) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)::numeric, 2) AS rolling_3m_median
FROM m ORDER BY month;

-- Q8. Which agencies have the highest data quality issue rates?
-- Purpose: where reporting is least reliable. (LEFT JOIN keeps agencies with 0 issues; conditional aggregation)
SELECT s.agency, count(DISTINCT s.record_hash) AS records,
       count(DISTINCT i.record_hash) AS affected_records,
       round(100.0 * count(DISTINCT i.record_hash) / count(DISTINCT s.record_hash), 3) AS affected_pct,
       count(i.issue_id) FILTER (WHERE i.severity IN ('critical', 'high')) AS high_severity_issues
FROM staging.service_requests s
LEFT JOIN ops.v_dq_issues_latest i ON i.record_hash = s.record_hash
GROUP BY s.agency
ORDER BY affected_pct DESC;

-- Q9. How much do problematic records affect reported KPIs?
-- Purpose: quantify reporting distortion from treatment. (see view definition for formulas)
SELECT * FROM analytics.v_raw_vs_clean;

-- Q10. How do average and median resolution times differ by agency? (skew indicator)
-- Purpose: an average far above the median means a long tail of slow cases drives the headline number.
SELECT agency_code, avg_resolution_hours, median_resolution_hours,
       round(avg_resolution_hours / NULLIF(median_resolution_hours, 0), 1) AS avg_to_median_ratio
FROM analytics.v_agency_performance
WHERE median_resolution_hours IS NOT NULL
ORDER BY avg_to_median_ratio DESC;

-- Q11. Top 3 complaint types per agency by volume. (ROW_NUMBER within partition)
-- Purpose: what drives each department's workload.
SELECT agency_code, complaint_type, requests FROM (
    SELECT a.agency_code, c.complaint_type, count(*) AS requests,
           ROW_NUMBER() OVER (PARTITION BY a.agency_code ORDER BY count(*) DESC) AS rn
    FROM analytics.fact_service_request f
    JOIN analytics.dim_agency a USING (agency_key)
    JOIN analytics.dim_complaint c USING (complaint_key)
    GROUP BY a.agency_code, c.complaint_type) t
WHERE rn <= 3 ORDER BY agency_code, rn;

-- Q12. Analytical-target performance (resolved within 7 days) by agency. (CASE + conditional aggregation)
-- Purpose: stand-in for SLA compliance; labelled analytical because the source has no usable deadline.
SELECT a.agency_code,
       count(*) FILTER (WHERE f.include_in_resolution_metrics) AS eligible,
       round(100.0 * avg(CASE WHEN f.within_analytical_target THEN 1 WHEN f.within_analytical_target = FALSE THEN 0 END), 2) AS pct_within_7d
FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key)
GROUP BY a.agency_code
HAVING count(*) FILTER (WHERE f.include_in_resolution_metrics) >= 50
ORDER BY pct_within_7d;

-- Q13. Day-of-week demand pattern. (JOIN date dimension)
-- Purpose: staffing alignment.
SELECT d.day_of_week, d.day_name, count(*) AS requests,
       round(count(*)::numeric / count(DISTINCT d.date_key), 1) AS avg_per_day
FROM analytics.fact_service_request f JOIN analytics.dim_date d ON d.date_key = f.created_date_key
GROUP BY d.day_of_week, d.day_name ORDER BY d.day_of_week;

-- Q14. Channel mix and its resolution speed. Purpose: do online/mobile requests resolve differently?
SELECT channel, count(*) AS requests,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_hours
FROM analytics.fact_service_request GROUP BY channel ORDER BY requests DESC;

-- Q15. Which records require manual investigation? (subquery on issue table)
-- Purpose: work queue for data stewards.
SELECT f.unique_key, a.agency_code, f.status, f.created_at, f.closed_at,
       (SELECT string_agg(i.rule_id, ',' ORDER BY i.rule_id) FROM ops.v_dq_issues_latest i
        WHERE i.unique_key = f.unique_key) AS rules
FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key)
WHERE f.needs_manual_review
ORDER BY f.created_at
LIMIT 50;

-- Q16. Data-quality issues over time (by month the request was created).
-- Purpose: are issues a one-off event or persistent? (date functions)
SELECT created_month, rule_id, count(*) AS issues
FROM ops.v_dq_issues_latest GROUP BY created_month, rule_id ORDER BY created_month, rule_id;

-- Q17. Agencies whose median resolution exceeds the overall median (subquery in HAVING).
SELECT a.agency_code, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours)::numeric, 1) AS median_hours
FROM analytics.fact_service_request f JOIN analytics.dim_agency a USING (agency_key)
GROUP BY a.agency_code
HAVING percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours) >
       (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours) FROM analytics.fact_service_request)
ORDER BY median_hours DESC;
