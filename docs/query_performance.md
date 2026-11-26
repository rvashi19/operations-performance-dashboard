# Query Performance (EXPLAIN ANALYZE)

Script: `sql/analytics/explain_analyze.sql`. Each "without index" measurement drops the index inside a transaction
and rolls it back. Run twice; the second (warm-cache) run is reported. PostgreSQL 16 in Docker on a Windows 11
laptop, 134,348 fact rows and 1,467 issue rows. Raw plans are in `logs/explain_2.txt` after running the script.

| Query | With index | Without | Plan change | Speed-up |
|---|---|---|---|---|
| A. Manual-review work queue: for 191 flagged requests, look up their issue rule ids (correlated subquery, `ops.dq_issues.unique_key`) | 23.3 ms | 48.8 ms | Seq Scan of dq_issues ×191 → Bitmap Index Scan on `ix_dq_issues_key` | 2.1× |
| B. Drill-down: one agency (DHS), one month (`agency_key` + `created_date_key`) | 0.54 ms | 13.2 ms | Parallel Seq Scan → BitmapAnd of `ix_fact_agency` and `ix_fact_created` | 24× |

The remaining 23 ms in query A comes from the sequential scan of the fact table for `needs_manual_review`. A partial
index `WHERE needs_manual_review` would remove it. It was not added because the queue is small and the benefit at
this data size is not worth the write overhead.

Run it yourself:

```powershell
Get-Content sql/analytics/explain_analyze.sql | docker exec -i ops311_postgres psql -U ops -d ops311
```
