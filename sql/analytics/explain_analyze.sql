-- Measures the effect of two indexes on reporting queries. Each "without index" run drops the
-- index inside a transaction that is rolled back, so the database is left unchanged.
\timing off
\echo '=== A. Manual-review work queue (correlated lookup of issues per record) WITH ix_dq_issues_key ==='
EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT f.unique_key,
  (SELECT string_agg(i.rule_id, ',') FROM ops.dq_issues i WHERE i.unique_key = f.unique_key) AS rules
FROM analytics.fact_service_request f WHERE f.needs_manual_review;
BEGIN;
DROP INDEX ops.ix_dq_issues_key;
\echo '=== A. WITHOUT ix_dq_issues_key ==='
EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT f.unique_key,
  (SELECT string_agg(i.rule_id, ',') FROM ops.dq_issues i WHERE i.unique_key = f.unique_key) AS rules
FROM analytics.fact_service_request f WHERE f.needs_manual_review;
ROLLBACK;
\echo '=== B. One agency, one month drill-down WITH ix_fact_agency + ix_fact_created ==='
EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT count(*), avg(resolution_hours)
FROM analytics.fact_service_request
WHERE agency_key = (SELECT agency_key FROM analytics.dim_agency WHERE agency_code = 'DHS')
  AND created_date_key BETWEEN 20250601 AND 20250630;
BEGIN;
DROP INDEX analytics.ix_fact_agency;
DROP INDEX analytics.ix_fact_created;
\echo '=== B. WITHOUT those indexes ==='
EXPLAIN (ANALYZE, BUFFERS, SUMMARY) SELECT count(*), avg(resolution_hours)
FROM analytics.fact_service_request
WHERE agency_key = (SELECT agency_key FROM analytics.dim_agency WHERE agency_code = 'DHS')
  AND created_date_key BETWEEN 20250601 AND 20250630;
ROLLBACK;
