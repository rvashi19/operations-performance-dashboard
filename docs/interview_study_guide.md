# Interview Study Guide: Operations Performance & Data Quality Dashboard

This guide is meant to help you *understand* the project well enough to explain any part of it in your own words.
Every number comes from the processed dataset (run `0413c6d5-…`, 134,348 Staten Island requests created in 2025)
and is reproducible with the files named in each section.

**Labels used throughout.** **[Built]** = implemented in the repository. **[Measured]** = produced by running it.
**[Hypothesis]** = plausible but not provable from public data. **[Suggested wording]** = a way you *could* phrase
something; it is not a description of what you personally did. Adapt it to what you actually did and understand.

How each technical topic is laid out: **What**, **Why**, **Where**, **Code**, **What could go wrong**,
**Manager version** (the plain-English explanation).

---

## 1. 60-second introduction [Suggested wording]

"I built an end-to-end operations analytics pipeline on real public data: 134,348 NYC 311 service requests from
Staten Island in 2025. Python pulls the data from the city's open data API with pagination, retries and a
row-count check. PostgreSQL keeps three layers: untouched raw records, a typed staging layer, and a star schema
for reporting. Before anything is reported, 15 configurable data quality rules check every record. About 1.1% of
requests fail at least one rule, and the problems are concentrated: 17% of Homeless Services requests, for
example, had closure problems in the first five months of the year. I measured how much cleaning changes the
KPIs: under half a percent for the borough, but 9.2% on the Buildings median. A five-page Power BI dashboard
reads the cleaned model, and I reconcile its numbers against SQL and Python automatically. The same pattern
(extract, validate, treat, reconcile, report) is what a supplier scorecard needs."

## 2. Five-minute dashboard demonstration

Open `powerbi/Ops311Dashboard.pbip` (or the screenshots in `powerbi/screenshots/`).

1. **Executive Overview (about 60 s).** "134,348 requests, 98.3% closed. Look at the median, 15.3 h, against the
   average, 275.7 h. The gap is the first insight: a small number of very slow jobs drive the average, so we
   manage with median and P90." Point at the created-vs-closed line: closures trailed demand in 10 of 12 months.
2. **Operational Performance (about 60 s).** "Median and P90 by agency. Police close in about 1.4 h, Buildings in
   about 23 days. The 7-day figure is an *analytical* target I chose; the source has no official SLA." Show the
   bottleneck scatter: top-right = high volume and slow.
3. **Backlog & Demand (about 60 s).** "Two different backlogs. *Current* backlog is what's open today (2,329, all
   older than 60 days because the data window ended in December). *Historical* backlog is reconstructed for each
   month end (6,641 at year end), mostly Parks and Buildings." Change the agency slicer to show it propagating.
4. **Data Quality Monitoring (about 60 s).** "98.90% of requests pass all 15 rules, but the agency bar shows why
   one number isn't enough: DHS is at 17%." Click a rule bar; the issue table filters to the affected requests.
5. **Data Quality Impact (about 60 s).** "Raw versus cleaned with identical formulas. Borough-level KPIs barely
   move (at most 0.41%), but Buildings' median moves 9.2%. I can explain exactly why." (See section 9 and
   `reports/business_findings.md` F2.)

## 3. One record's journey through the pipeline

Take request **63924345** (DOT, *Street Light Condition*, status *Pending*), one of the real DQ006 records.

| Step | What happens | Where |
|---|---|---|
| 1. Extract | The API returns it as JSON text: `created_date "2025-01-29T13:33:00.000"`, `closed_date "2025-01-28T13:26:00.000"`, `status "Pending"` | `socrata_client.iter_pages` |
| 2. Raw file | Written unchanged to `data/raw/nyc311_full-refresh_*.jsonl.gz` (atomic rename after the count check) | `extract_to_file` |
| 3. Raw table | Stored as JSONB with `record_hash` = md5 of its business fields | `loader.load_raw_and_staging` |
| 4. Staging | Typed: `created_at` / `closed_at` timestamps; original text kept in `*_raw` | `staging.to_staging` |
| 5. Snapshot | Its hash is recorded in `staging.current_snapshot` (it is in the current source extract) | `loader.replace_snapshot` |
| 6. Validation | Fails **DQ006** (closed before created: −24.12 h) and **DQ011** (status Pending but has a closed date) | `framework.Validator.run` |
| 7. Treatment | Status *Pending* → `status_group = Open`. Because DQ006/DQ011 have `excludes_from_resolution: true`, its duration is NULL. It is escalated for manual review (DQ011 is `manual_review`) | `cleaning.clean` |
| 8. Star schema | Becomes one fact row with keys to date, agency (DOT), complaint and geography; `dq_issue_count = 2` | `loader.load_analytics` |
| 9. Reporting | Counted in total volume and current backlog; **not** in resolution time; appears in the page 4 issue table | views + Power BI |

Manager version: "We keep the request and count it as open work, but we don't let its impossible dates distort
how fast we say we resolve things, and we put it on a list for someone to check."

## 4. Important Python modules

### 4.1 `src/ingestion/socrata_client.py` (extraction)
* **What:** downloads all pages for a date window and borough, with retries and a row-count check.
* **Why:** APIs fail and pages can be lost; a silent partial download would under-report demand.
* **Where:** `SocrataClient._get`, `iter_pages`, `extract_to_file`.
* **Code:**
  ```python
  if resp.status_code == 429 or resp.status_code >= 500:   # retryable
      raise requests.HTTPError(...)
  ...
  if n < expected:                                          # lost a page
      raise ExtractionError(f"row count mismatch: extracted {n}, API reported {expected}")
  os.replace(tmp, out_path)                                 # only now replace the good file
  ```
* **What could go wrong:** offset paging over a changing dataset can skip or repeat rows (mitigated by ordering
  on `unique_key` and the count check); the API could change field names (tested: malformed responses raise
  `ExtractionError`).
* **Manager version:** "If the download is incomplete, we stop and keep yesterday's numbers rather than publish
  wrong ones."

### 4.2 `src/transformation/staging.py` (typing and safe normalisation)
* **What:** turns JSON into typed columns, hashes each record, trims text, upper-cases codes, keeps the original
  timestamp text.
* **Why:** analysis needs real timestamps, and audits need to see what the source actually said.
* **Code:** `out["created_at"] = pd.to_datetime(raw, format="ISO8601", errors="coerce")`. An unparseable value becomes
  NaT and DQ007 catches it because `created_date_raw` is still present.
* **What could go wrong:** "fixing" data here (e.g. guessing a ZIP) would hide problems. Only reversible, safe
  normalisation is allowed.
* **Manager version:** "We clean up formatting, never meaning."

### 4.3 `src/validation/framework.py` (rules engine)
* **What:** runs each YAML rule's check and produces one issue row per record, rule and column; summarises
  record-level and request-level rates.
* **Why:** rules change more often than code; making them configuration keeps them reviewable by non-developers.
* **Code:**
  ```python
  for rule in self.rules:
      for mask, column, original in CHECKS[rule["check"]](df, rule, self.ref, self.now):
          ...  # build issue rows with severity, treatment, explanation
  ```
* **What could go wrong:** treating every NULL as an error (an open request legitimately has no closed date);
  double-counting a record with several issues (`summarize` counts distinct records and requests).
* **Manager version:** "A checklist every record goes through, written in plain configuration."

### 4.4 `src/transformation/cleaning.py` (treatment policy)
* **What:** dedupe, quarantine, exclude-from-metric, escalate or retain, each driven by YAML flags; groups statuses
  into Closed, Open and Unknown; writes an audit row for every decision.
* **Why:** deleting bad rows hides problems and changes counts; the right treatment depends on which metric a
  defect corrupts.
* **Code:** `resolution_excluding = {r["id"] for r in rules_cfg["rules"] if r.get("excludes_from_resolution")}`.
* **What could go wrong:** hardcoded rule IDs drifting from the YAML (fixed in the QA review: now read from
  config); treating an unknown status as open (fixed: `Unknown` group).
* **Manager version:** "Each problem is handled in the narrowest way that protects the affected number, and we
  log every decision."

### 4.5 `src/database/loader.py` and `src/pipeline.py` (orchestration and publishing)
* **What:** loads raw history, replaces the current snapshot, validates, publishes the star schema, rebuilds
  views and records the run, all in one transaction.
* **Why:** a half-finished publish (new data with old views, or "succeeded" with missing data) misleads users.
* **Code:**
  ```python
  with engine.begin() as conn:            # one transaction
      loader.load_raw_and_staging(conn, batch, run_id, ...)
      loader.replace_snapshot(conn, inspected, run_id)
      m = validate_and_publish(conn, inspected, ...)
      build_views(conn)
      loader.finish_run(conn, run_id, "succeeded", ...)
  ```
* **What could go wrong:** a failure after commit would leave "failed" metadata over good data; this is avoided by
  committing everything at once (tested by injecting failures in validation, publication and views).

### 4.6 `src/analytics/kpis.py` and `src/reporting/reports.py` (KPIs and reconciliation)
* **What:** independent Python KPI calculations; reports fail if Python and SQL disagree.
* **Why:** two independent implementations agreeing is strong evidence both are right.
* **Code:** `mismatches = {k: v for k, v in checks.items() if not _close(v[0], v[1], v[2])}` raises when they differ.
* **Manager version:** "Every headline number is calculated twice, two different ways, and must match."

## 5. Database schema walkthrough

* `raw.service_requests`: `record_hash` PK, `payload` JSONB, never modified. **Why:** audit trail and replay.
* `staging.service_requests`: typed copy of each raw row. `staging.current_snapshot`: which rows are the
  source **now**.
* `ops.pipeline_runs`: run history, scope key, checkpoint, record/request counts. `ops.dq_rules`,
  `ops.dq_issues`: rule catalogue and every issue.
* `analytics`: star schema. `fact_service_request` (one row per request) joined to `dim_date`, `dim_agency`,
  `dim_complaint` and `dim_geography`; plus `quarantine` and `cleaning_audit`.
* **Why a star schema:** Power BI filters flow from small dimension tables to the fact table; measures stay simple.
* **What could go wrong:** a fact row whose dimension lookup fails would silently disappear in an INNER JOIN, so
  `load_analytics` asserts that no rows were lost.
* **Manager version:** "One big table of requests and small lookup tables for who, what, where and when."

## 6. Ten important SQL queries, line by line

Files: `sql/analytics/operational_analysis.sql` (Q1–Q17), `sql/transformations/02_reporting_views.sql`.

1. **Q1 Volume by agency.** `JOIN dim_agency` turns keys into names; `count(*) ... GROUP BY` counts per agency;
   `sum(count(*)) OVER ()` is a window over the *grouped* rows that gives the grand total for the percentage;
   `RANK() OVER (ORDER BY count(*) DESC)` ranks with gaps for ties.
2. **Q2 Longest median by category.** `percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)` is the
   interpolated median; `count(f.resolution_hours)` counts only non-NULL durations; `HAVING ... >= 100` drops
   small samples *after* grouping.
3. **Q3 Demand vs closures.** Two CTEs (`created`, `closed`) aggregate by month on different date columns;
   `LEFT JOIN` keeps months with no closures; `sum(net) OVER (ORDER BY month)` is a running total.
4. **Q4 Increasing backlog.** `LAG(backlog) OVER (PARTITION BY agency ORDER BY month_end)` compares each month
   with the previous one for the same agency; `FILTER (WHERE mom_change > 0)` counts increasing months.
5. **Q5 Overdue categories.** Filters open requests older than the analytical target; `DENSE_RANK` ranks without
   gaps.
6. **Q7 Exact rolling median.** `generate_series` creates every month (so a missing month can't shift the window);
   the correlated subquery pools all durations created in `[M-2, M]` and takes one median. This is not an
   average of medians.
7. **Q8 DQ rate by agency.** `LEFT JOIN` from staging keeps agencies with zero issues;
   `count(DISTINCT i.record_hash)` stops a record with three issues counting three times.
8. **v_backlog_monthly.** Month ends from `generate_series`; join condition `created_at <= as_of AND
   (effective_closed_at IS NULL OR effective_closed_at > as_of)`; excludes Closed-without-valid-date and Unknown.
9. **v_raw_vs_clean.** Same formulas over two populations (snapshot rows vs cleaned fact) in CTEs; `UNION ALL` of
   metric pairs; `NULLIF(raw,0)` prevents division by zero.
10. **Q11 Top 3 per agency.** `ROW_NUMBER() OVER (PARTITION BY agency ORDER BY count(*) DESC)` in a subquery, then
    `WHERE rn <= 3`. Window functions can't be filtered in the same SELECT's WHERE clause.

What could go wrong in SQL generally: `AVG` silently ignores NULLs (intended here); a `BETWEEN` on timestamps with
`23:59:59.999` misses rows (fixed with a half-open `>= start AND < end`).

## 7. Five DAX measures, line by line

File: `powerbi/build_pbip.py` (MEASURES) and `powerbi/dax_measures.dax`.

1. `Total Requests = COUNTROWS ( Requests )`: counts the rows of the fact table in the current filter context.
2. `Resolution Rate = DIVIDE ( [Closed Requests], [Total Requests] )`: `DIVIDE` returns BLANK instead of an
   error when the denominator is 0.
3. `Median Resolution Hours = MEDIAN ( Requests[resolution_hours] )`: BLANK durations (excluded records) are
   ignored, which mirrors SQL. The P90 uses `PERCENTILE.INC`, the same interpolation as `percentile_cont` (verified
   in Power BI: 335.376 both ways).
4. `Backlog At Period End`:
   ```
   VAR AsOf = MAX ( Calendar[full_date] ) + 1                  -- midnight after the last day in context
   RETURN CALCULATE ( COUNTROWS ( Requests ),
       REMOVEFILTERS ( Calendar ),                              -- don't restrict to requests created that month
       Requests[created_at] < AsOf,                             -- created by the as-of moment
       Requests[status_group] <> "Unknown",
       NOT ( Requests[status_group] = "Closed" && ISBLANK ( Requests[effective_closed_at] ) ),
       ISBLANK ( Requests[effective_closed_at] ) || Requests[effective_closed_at] >= AsOf )  -- still open then
   ```
   `REMOVEFILTERS` is the key line: without it, the month on the axis would filter to requests *created* that
   month, which is a different question. Verified: Dec 2025 = 6,641, matching SQL.
5. `Requests Created 3M Rolling Avg`: `DATESINPERIOD ( Calendar[full_date], LastDay, -3, MONTH )` returns
   exactly three calendar months ending with the month in context. The `IF` returns BLANK until three complete
   months exist. Verified against SQL for all 12 months.

What could go wrong: a measure that depends on filters from a table with no relationship to the slicer (fixed in QA:
complaint, ZIP and status slicers now reach Current Backlog and DQ Issues through `Requests`).

## 8. The 15 validation rules with practical examples

| Rule | Example that fails | Example that passes | Treatment | Found |
|---|---|---|---|---|
| DQ001 Duplicate request ID | Two different versions of key 7 in **one** extract | An updated version replacing an older one across runs (history, not a duplicate) | deduplicate (keep latest) | 0 |
| DQ002 Exact duplicate | The same row twice on overlapping pages | — | deduplicate | 0 |
| DQ003 Missing request ID | `unique_key` empty | — | quarantine | 0 |
| DQ004 Missing created date | `created_date` empty | — | quarantine | 0 |
| DQ005 Closed without closed date | Status Closed, no closed_date (DHS, Jan–May) | Status Open, no closed_date | exclude from resolution | 62 |
| DQ006 Closed before created | closed 2025-01-28 13:26, created 2025-01-29 13:33 | — | exclude from resolution | 24 |
| DQ007 Invalid timestamp | `"not-a-date"` | — | quarantine | 0 |
| DQ008 Future timestamp | closed_date after extraction | future **due_date** (legitimate) | exclude from resolution | 0 |
| DQ009 Missing category | complaint_type empty | — | retain as Unknown | 0 |
| DQ010 Missing agency | agency empty | — | manual review | 0 |
| DQ011 Open with closed date | Status Open + closed_date (DOB hand-offs) | — | manual review, exclude from resolution | 191 |
| DQ012 Undocumented status | "Teleported" | "Cancel" (documented, grouped Unknown) | manual review | 0 |
| DQ013 Extreme duration | > 365 days (Parks trees) | 200 days | retain + flag | 459 |
| DQ014 Missing geography | no ZIP **and** no coordinates | no ZIP but coordinates present | retain | 731 |
| DQ015 Ambiguous local time | 2025-11-02 01:30 (hour happens twice) | 2025-11-02 03:00 | retain + flag | 41 timestamps / 34 requests |

## 9. Cleaning decisions and trade-offs

| Decision | Benefit | Cost / trade-off |
|---|---|---|
| Exclude invalid durations, keep the request | Volume and closure counts stay complete | Resolution sample shrinks (131,951 of 132,019 closed) |
| Treat open-with-closed-date (DQ011) as open | The status field is the documented state | If the status is wrong instead, DOB is penalised |
| Retain >365-day cases | Doesn't hide real slow work | Average stays high (275.7 vs 241.3 h without them) |
| Quarantine missing IDs or created dates | Can't track or date them | Lost from all KPIs (0 in this data) |
| Unknown statuses are neither open nor closed | No invented backlog | Total ≠ open + closed when they exist |
| Exclude Closed-without-date from historical backlog | Avoids "open forever" | Backlog slightly understated for DHS Jan–May |

## 10. API pagination, retries and incremental extraction

* **What:** `$limit=50000&$offset=n&$order=unique_key`, exponential backoff (2, 4, 8, 16 s), incremental via
  `:updated_at > checkpoint − 2 days`.
* **Why:** large results need paging; stable order prevents duplicates and gaps; the overlap absorbs clock skew
  and late updates.
* **Where:** `socrata_client.py`, `pipeline.run`, `loader.last_checkpoint`.
* **Code:** `since = (prev_cp - timedelta(days=lookback)).astimezone(timezone.utc)...`
* **What could go wrong:** the checkpoint from a different borough being reused (fixed: checkpoints are scoped);
  an empty incremental losing the checkpoint (tested: carried forward).
* **Manager version:** "Each night we only fetch what changed, plus a two-day safety overlap."

## 11. Idempotency, transactions and rollback

* **What:** running the same refresh twice gives the same result; a failure changes nothing.
* **Why:** schedulers retry; people re-run jobs.
* **Where:** hash-keyed raw inserts (`ON CONFLICT DO NOTHING`), fact upsert on `unique_key`, snapshot replacement,
  one transaction.
* **Measured:** a real incremental run re-read 5,170 records and inserted 0 new raw rows. Tests inject failures in
  validation, publication and view rebuild; counts, facts and the successful-run record are unchanged afterwards.
* **Manager version:** "Pressing the button twice can't double anything, and a crash leaves yesterday's report
  intact."

## 12. Indexes and EXPLAIN ANALYZE

* **What:** B-tree indexes on fact foreign keys and `dq_issues.unique_key`.
* **Measured** (`docs/query_performance.md`): agency+month drill-down 13.2 ms → 0.54 ms (bitmap AND of two
  indexes); review-queue lookup 48.8 → 23.3 ms.
* **What could go wrong:** indexes slow writes and can be ignored by the planner if statistics are stale; always
  measure, don't assume.
* **Manager version:** "Like a book index: the report finds the right pages instead of reading the whole book."

## 13. Power BI relationships and filter context

* One-to-many from `Calendar`, `Agency` → `Requests`; `OpenRequests` and `DQIssues` → `Requests` (on
  `unique_key`), so every slicer has one path.
* An inactive `Requests[closed_date_key] → Calendar` relationship is activated only inside `Requests Closed` with
  `USERELATIONSHIP`.
* **Filter context** = the set of filters (slicers, axis value, visual filters) a measure is evaluated under.
  `CALCULATE` changes it.
* **What could go wrong:** two paths between tables (ambiguity), or a table with no path (slicer does nothing).
  Both were present before the QA fix and are now verified with DAX filter-context queries.

## 14. Operational KPIs and denominator choice

| KPI | Numerator | Denominator | Why that denominator |
|---|---|---|---|
| Resolution rate | Closed | All requests | Every request is demand |
| Median/P90 resolution | — | Requests with valid closures only (131,951) | Invalid durations would distort timing |
| Within 7-day target | Valid closures ≤ 7 days | Valid closures | Open work has no duration yet |
| Record-level DQ pass | Rows with no issue | All rows inspected | Data-feed health |
| Request-level DQ pass | Requests with no issue | Distinct request IDs | Business impact per case |
| Historical backlog | — (count) | — | Defined by an as-of date, not a ratio |

## 15. Limitations and future improvements

Limitations: one borough, one year; current-state data with no status history; no official SLA; the historical
backlog cohort starts at zero; right-censoring of late-2025 requests; causes marked as hypotheses can't be
confirmed; no Power BI drill-through page; the export path in PBIP is absolute (regenerate on a new machine).
Future: daily snapshots, agreed per-category targets, scheduled refresh with alerts on per-agency DQ thresholds,
all boroughs with partitioning.

## 16. Forty interview questions with answers

1. **What business question does this answer?** How fast requests are resolved, where the bottlenecks are,
   whether backlog is growing, and whether the data can be trusted.
2. **Why Staten Island 2025?** It is the only borough with a full year in the 100k–300k range, and a complete
   borough is a consistent scope.
3. **How many records, and how did you verify that?** 134,348; the API's `count(*)` must match the extracted rows.
4. **Why is the mean 18× the median?** The slowest 5% of requests hold 74.8% of all resolution hours.
5. **Why report P90?** It shows the tail commitment: 90% resolve within 335.4 h.
6. **Why is there no SLA?** `due_date` is 0.28% populated and means "expected update". I used a labelled 7-day
   analytical target.
7. **What is the DQ pass rate?** 98.899% at request level (1,479 of 134,348 affected); identical at record level
   here.
8. **Why two DQ rates?** Duplicate rows or rows without an ID make them differ; each answers a different question.
9. **Biggest DQ finding?** It isn't one number. DHS (17%) and DOB (5.8%) concentrate the issues.
10. **Explain the DOB 9.2%.** 154 open-status requests had closed dates, mostly at the creation time (0 h). Counting
    them as resolutions pulls the median down.
11. **What does "updated record is not a duplicate" mean?** A new version from an incremental run replaces the old
    one in the snapshot; the old one stays in raw history.
12. **What happens if a record disappears from the source?** The next full refresh drops it from analytics; raw
    keeps it.
13. **How do you prevent duplicates on re-runs?** Content-hash primary key on raw; upsert on `unique_key`.
14. **What if the API fails halfway?** Retries, then the run fails; the temp file is deleted; nothing is
    published.
15. **What if validation throws an error?** The whole transaction rolls back and the run is marked failed (tested).
16. **Why keep raw JSON?** Audit, replay, and fields we don't model yet.
17. **How are timestamps handled?** Floating NYC local time; ambiguous DST hours are flagged (DQ015); date windows are
    half-open.
18. **What was the DST finding?** 41 timestamps on the November fall-back night; 3 negative durations fall in it.
19. **How do you treat unknown statuses?** As a separate group, never open or closed.
20. **Why not delete bad rows?** It changes counts and hides problems; treat per metric instead.
21. **What is the quarantine table for?** Records that can't be used at all (missing ID or created date); still
    auditable.
22. **How did you verify the dashboard?** DAX queries against the open model, compared with SQL; every value matched
    (see the checklist).
23. **Which DAX function matters most for backlog?** `REMOVEFILTERS(Calendar)` inside `CALCULATE`.
24. **How does the rolling average avoid gaps?** Calendar-generated months; zero-filled; BLANK until three months
    exist.
25. **What indexes did you add and why?** Fact foreign keys and the issues key; measured 24× on a drill-down.
26. **How would you schedule it?** Nightly `--incremental` then `--generate-reports`; alert on failed runs and
    per-agency DQ thresholds.
27. **Why PostgreSQL rather than only pandas?** Transactions, constraints, a shared source of truth for Power BI,
    window and percentile functions.
28. **How is the treatment configurable?** `excludes_from_resolution`, `treatment` and labels live in YAML; tests
    change the YAML and see behaviour change.
29. **What does right-censoring mean here?** Late-2025 requests have had less time to close, so their medians look
    better than they will.
30. **Why does historical backlog start low in January?** Only 2025-created requests are included; pre-2025 open
    work isn't in the extract.
31. **How do you handle reopened requests?** No reopen history exists; DQ011 records count as open and are
    escalated.
32. **How did CI change in the QA review?** `REQUIRE_DB=1` makes integration tests fail rather than skip if
    Postgres is missing.
33. **How many tests?** 62 tests (38 original unit, 6 original integration, 18 QA regression cases); all pass
    locally.
34. **What would you do differently?** Daily snapshots for true backlog history; per-category targets agreed with
    operations.
35. **How would this work for a supplier scorecard?** POs, receipts and promised dates replace requests and
    closures (see `docs/supply_chain_application.md`).
36. **Behavioural: a time the data contradicted the requirement?** SLA compliance was requested; the source
    couldn't support it; I explained why and provided a labelled alternative.
37. **Behavioural: communicating uncertainty?** Every root cause is labelled confirmed or hypothesis.
38. **Behavioural: finding your own mistake?** The QA review found the first version's full refresh never removed
    deleted records, and its DQ denominators were inconsistent. I documented and tested each fix (`reports/qa_review.md`).
39. **Behavioural: prioritising issues?** By the metric each one corrupts and how concentrated it is (DOB/DHS
    before DQ014).
40. **Explain this project to a non-technical manager in one sentence.** "It tells you how quickly each department
    resolves requests, and how much you can trust those numbers."

## 17. Ten SQL exercises (solutions in section 21)

1. Requests and median resolution hours per submission channel.
2. The busiest day of the week for each of NYPD, DSNY, DOT, DEP, HPD.
3. Month-over-month change in created requests.
4. Complaint types with ≥ 500 requests whose within-7-day rate is below 70%.
5. Each rule's share of all DQ issues.
6. Agencies whose share of open requests is above the borough's overall share.
7. Top 3 ZIP codes by median resolution (min 1,000 resolved) using `DENSE_RANK`.
8. Requests flagged by more than one rule, and how many there are.
9. Cumulative closures through 2025 (running total).
10. For agencies with ≥ 3,000 requests, the share of volume in their single largest complaint type.

## 18. Ten Python and data-validation exercises (solutions in section 22)

1. Group `["Closed","Open","In Progress","Cancel","Teleported"]` into status groups using the project's config.
2. Write and register a check that flags ZIP codes that are present but not five digits.
3. For two copies of a bad record, one good record and one row without an ID, compute record-level and
   request-level affected counts.
4. Keep only the latest version of each key from a versions table.
5. Compute mean, median and P90 of `[1, 2, 3, 4, 100]` and say which matches `percentile_cont`.
6. Compute an exact 3-calendar-month rolling average where February has no records.
7. Prove DQ005 does not flag an open request with no closed date.
8. Detect ambiguous and nonexistent New York local times.
9. List the retry waits for 4 retries with backoff 2.
10. Write a function that reconciles two KPI dictionaries within a tolerance.

## 19. Supply chain scenario questions

1. **The ERP says a PO line is closed, but receipts total only 80% of the ordered quantity. What do you report?**
   Treat it as a status/quantity inconsistency (like DQ011): flag it, measure OTD on the received quantity, and ask
   purchasing whether the remaining 20% was cancelled. Don't silently count it as complete.
2. **A supplier's OTD jumped from 70% to 95% after the promised dates were edited. How do you check?** Keep promise
   history (raw versions) and report OTD against the first and the final promise.
3. **20% of lines have no promised date. Do you count them as late?** No. Exclude them from promised-date OTD,
   report their share by supplier, and fall back to requested-date OTD, labelled.
4. **Warehouse and ERP disagree on received quantity.** Reconcile per PO line before publishing, exactly like the
   Python-vs-SQL reconciliation here; send mismatches to a work queue.
5. **The average lead time is 40 days but the median is 12. What do you tell the planner?** The distribution is
   skewed by a few long orders; plan on median and P90 by part family, and investigate the tail separately.
6. **A receipt is dated before the PO.** A validity error (like DQ006): exclude it from lead time; it is often a
   backdated PO raised after delivery.
7. **One supplier has 30% data issues; overall it's 2%.** Show DQ by supplier next to their scorecard, as F6 shows
   by agency.

## 20. STAR stories (documented findings; not personal claims)

> These describe what the **project** shows. Use them only to the extent that you did the work and can explain it.

**Story 1: Explaining a 9.2% KPI shift.** *S:* After cleaning, the Buildings median rose 9.2% while
borough-level KPIs barely moved. *T:* Explain the cause precisely. *A:* Compared removed and kept records by rule
and status; found 154 open-status requests with closed dates, 72% under one hour. *R:* A specific explanation
and a targeted recommendation (DOB status review), instead of a vague "data was dirty".

**Story 2: A QA review of my own pipeline.** *S:* The first version passed its tests. *T:* Review it critically.
*A:* Found that full refreshes never removed deleted records, DQ denominators were inconsistent, and some slicers
didn't reach some measures; fixed each and added 18 regression test cases. *R:* 62/62 tests pass, and Power BI
values reconcile exactly with SQL.

**Story 3: A time-bounded data gap.** *S:* 62 DHS closures had no closure time. *T:* Decide whether this was
noise. *A:* Profiled by month; 62 of 81 January–May requests were affected and none after. *R:* Treated it as a
workflow issue: excluded from timing only, recommended a backfill and a monthly per-agency alert.

## 21. SQL exercise solutions (actual output: `reports/evidence/sql_exercises_output.txt`)

All solutions are in `sql/analytics/study_guide_exercises.sql`. Key results:

| # | Answer (abridged actual output) |
|---|---|
| 1 | ONLINE 63,705 req, median 5.6 h · PHONE 39,151, 27.6 h · UNKNOWN 17,171, 117.9 h · MOBILE 14,243, 1.9 h |
| 2 | NYPD Saturday 8,153 · DSNY Tuesday 4,021 · DOT Tuesday 3,017 · DEP Tuesday 2,209 · HPD Monday 2,123 |
| 3 | Biggest drop Nov (−1,641); biggest rise May (+1,532) |
| 4 | 18 types, lowest Root/Sewer/Sidewalk 3.7%, Street Light 15.1%, Building/Use 17.4% |
| 5 | DQ014 48.5%, DQ013 30.4%, DQ011 12.7%, DQ005 4.1%, DQ015 2.7%, DQ006 1.6% |
| 6 | TLC 28.6%, EDC 26.3%, OTI 23.5%, DPR 7.2%, DOHMH 6.8%, DOB 3.5%, DSNY 1.9% (borough 1.7%) |
| 7 | 10301 20.8 h, 10312 19.8 h, 10308 19.8 h |
| 8 | 22 requests; e.g. 63922507 DQ006,DQ011 |
| 9 | 127,639 closures dated in 2025 (the rest of the 132,019 closed in 2026) |
| 10 | DOB 47.8% General Construction/Plumbing · DEP 47.6% Water System · DOT 38.6% Street Condition |

Example (exercise 7):
```sql
SELECT * FROM (
  SELECT g.incident_zip, count(f.resolution_hours) AS resolved,
         round(percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours)::numeric, 1) AS median_h,
         DENSE_RANK() OVER (ORDER BY percentile_cont(0.5) WITHIN GROUP (ORDER BY f.resolution_hours) DESC) AS rnk
  FROM analytics.fact_service_request f JOIN analytics.dim_geography g USING (geography_key)
  WHERE g.incident_zip <> 'Unknown' GROUP BY 1 HAVING count(f.resolution_hours) >= 1000) t
WHERE rnk <= 3;
```

## 22. Python exercise solutions (runnable: `python docs/study_guide_python_solutions.py`)

Actual output:
```
P1 {'Open': 2, 'Unknown': 2, 'Closed': 1}
P2 [False, True, False, True]
P3 {'records_inspected': 4, 'records_affected': 3, 'requests_inspected': 2, 'requests_affected': 1}
P4 [['1', 'Closed'], ['2', 'Open']]
P5 22.0 3.0 61.60000000000001      # pandas quantile = percentile_cont = PERCENTILE.INC
P6 [nan, nan, 2.0]                  # (4 + 0 + 2) / 3; Feb counted as zero
P7 True
P8 [True, False, True]
P9 [2, 4, 8, 16]
P10 {'total': (134348, 134347)}
```
Key solution (exercise 2):
```python
def check_zip_format(df, rule, ref, now):
    raw = df["incident_zip"]
    return [(raw.notna() & ~raw.str.fullmatch(r"\d{5}"), "incident_zip", raw)]
CHECKS["zip_format"] = check_zip_format   # then add a YAML rule with check: zip_format
```
