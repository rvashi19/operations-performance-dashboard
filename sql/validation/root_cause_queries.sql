-- Evidence queries behind reports/root_cause_analysis.md (latest load run).
-- docker exec -i ops311_postgres psql -U ops -d ops311 < sql/validation/root_cause_queries.sql

-- 1. Issue concentration by rule, agency and complaint type
SELECT rule_id, agency, complaint_type, count(*) AS records
FROM ops.v_dq_issues_latest GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC;

-- 2. Time window of each issue (bounded window => workflow/system event, not random noise)
SELECT rule_id, min(created_at)::date AS first_seen, max(created_at)::date AS last_seen, count(*)
FROM ops.v_dq_issues_latest GROUP BY 1 ORDER BY 1;

-- 3. DQ006 representative records with the size of the negative gap
SELECT unique_key, agency, complaint_type, status, created_at, closed_at,
       round(extract(epoch FROM closed_at - created_at) / 3600, 2) AS hours
FROM ops.v_dq_issues_latest WHERE rule_id = 'DQ006' ORDER BY hours;

-- 4. DQ005: affected vs unaffected DHS records (same outcome texts => same workflow)
SELECT (s.closed_at IS NULL) AS missing_close, left(s.resolution_description, 80) AS resolution, count(*)
FROM staging.service_requests s WHERE s.agency = 'DHS' GROUP BY 1, 2 ORDER BY 1, 3 DESC;

-- 5. DQ011: status and resolution text of open records with a closed date
SELECT s.agency, s.status, left(s.resolution_description, 90) AS resolution, count(*)
FROM staging.service_requests s
WHERE s.status <> 'Closed' AND s.closed_at IS NOT NULL GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 15;

-- 6. Timestamp precision by agency (midnight closures and zero durations)
SELECT agency, count(*) AS n,
       round(100.0 * avg((closed_at::time = '00:00:00')::int), 1) AS pct_midnight_close,
       round(100.0 * avg((closed_at = created_at)::int), 1) AS pct_zero_duration
FROM staging.service_requests WHERE closed_at IS NOT NULL GROUP BY 1 ORDER BY 3 DESC;

-- 7. DQ013 extreme durations by complaint type
SELECT agency, complaint_type, count(*), round(avg(extract(epoch FROM closed_at - created_at) / 86400)) AS avg_days
FROM staging.service_requests WHERE closed_at - created_at > interval '365 days'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- 8. DQ014 missing geography by complaint type
SELECT complaint_type, agency, count(*) FROM ops.v_dq_issues_latest WHERE rule_id = 'DQ014'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- 9. Affected vs unaffected comparison: median resolution with and without issue records, per agency
SELECT f.agency_code,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours)::numeric, 1) AS median_all_valid,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours) FILTER (WHERE f.dq_issue_count = 0))::numeric, 1) AS median_issue_free
FROM analytics.v_service_requests f GROUP BY 1 ORDER BY 1;
