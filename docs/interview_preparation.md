# Interview Preparation

Labels used below: **[Implementation]** = a design decision in the code · **[Finding]** = produced by the pipeline
on the real data · **[Assumption]** = a judgement call or something that can't be verified from public data.
This is a portfolio project built on public open data. It was not deployed for, or used by, any municipal department.

## 60-second introduction

"I built an end-to-end operations analytics pipeline on real NYC 311 data: about 134,000 Staten Island service
requests from 2025. A Python job pulls the data from the city's open data API with pagination and retries, stores
the untouched records in PostgreSQL, and runs them through a configurable validation framework of 14 data quality
rules. A documented treatment policy then publishes a star schema that Power BI reads. 98.9% of records passed every
rule. The failures weren't random. They sat in specific workflows, for example 62 homeless-outreach requests closed
without a closure time, all between January and May. I also measured how much the cleaning changed the reported
KPIs. City-wide it was under half a percent, but the Department of Buildings' median resolution time moved by 9%.
The project includes 44 automated tests, CI, SQL analysis and a five-page Power BI dashboard."

## Five-minute technical walkthrough

1. **Source verification.** I read the Socrata metadata endpoint (`/api/views/erm2-nwe9.json`) for field
   definitions before writing code. That is how I learned `due_date` means "expected update" and is only 0.28%
   populated, so I didn't invent SLAs. [Finding]
2. **Extraction** (`src/ingestion/socrata_client.py`). Offset pagination ordered by `unique_key`, 50k rows per page,
   exponential backoff on 429/5xx, immediate failure on other 4xx. It compares the row count with the API's own
   `count(*)` and writes to a `.part` file that is renamed only on success. Two real HTTP 503 errors were retried
   during the run. [Implementation/Finding]
3. **Layers.** Raw JSONB keyed by an md5 of the business fields (so re-reads don't duplicate), typed staging that
   keeps the original timestamp text, an ops schema for runs and issues, and an analytics star schema with
   date/agency/complaint/geography dimensions. [Implementation]
4. **Validation** (`src/validation/framework.py` + YAML). Each rule maps to a check function returning a mask. Issues
   carry record id, rule, category, severity, column, original value, explanation, run id, timestamp, treatment and
   resolution status. [Implementation]
5. **Treatment policy** (`src/transformation/cleaning.py`). Deduplicate, quarantine, exclude from affected metrics
   only, escalate, or retain, and every decision goes to an audit table. [Implementation]
6. **One transaction per load.** Raw → analytics commits or rolls back as a unit. Empty extracts are refused.
   [Implementation]
7. **Reporting.** SQL views (KPIs, backlog, raw-vs-clean), CSV exports, generated markdown reports. The Python and
   SQL KPI implementations are reconciled automatically. [Implementation]
8. **Testing.** 38 unit tests plus 6 integration tests against a real Postgres test database, including idempotency
   and a failed-refresh test. CI runs them with a Postgres service container. [Implementation]

## Why PostgreSQL, Python and Power BI

* PostgreSQL: real transactions, `ON CONFLICT` upserts, JSONB for unchanged raw payloads, `percentile_cont`, a
  Power BI connector, and it runs free in Docker on Windows.
* Python/pandas: validation rules are easier to read and unit-test as DataFrame logic. 134k rows fit in memory.
* Power BI: the standard BI tool in the roles I'm targeting. Business logic lives in SQL views, so DAX stays small.
* Things I deliberately didn't use: Airflow, dbt, cloud services. They would add moving parts without changing any
  result at this scale.

## Topic answers

**How was the dataset collected?** Through the official SODA API with a `$where` on created_date (2025) and borough =
Staten Island, ordered by `unique_key`. Staten Island is the only borough whose full 2025 volume (134,348) fell in
the 100k–300k range. The raw JSON lines file is kept unchanged. [Implementation/Finding]

**How does the validation framework work?** YAML declares rules, a registry maps check names to functions, and
issues are stored per run. The affected-record count uses distinct record hashes, so a record failing three rules
counts once. 1,467 issues fell on 1,448 records. [Finding]

**How do duplicates affect business metrics?** A duplicated request inflates volume, and if one copy is stale it
can count a closed request as open (inflating backlog) or add a second duration. This extract had 0 duplicate IDs
and 0 exact duplicates. That is itself a finding. The rules still matter because every incremental run re-reads a
2-day overlap: on the real run 5,170 rows came back again and none were duplicated in raw. [Finding]

**How were missing dates handled?** Missing closed dates are only an error when status is Closed (DQ005: 62
records). 2,138 open requests without a closed date are legitimate and unflagged. Missing creation dates would be
quarantined (0 found). [Finding]

**How were root causes investigated?** By grouping each rule's records by agency, complaint type, status and
date, comparing them with unaffected records, and reading the resolution text. For example: the 3 NYPD negative
durations all fall between 01:00 and 02:00 on 2025-11-02, the daylight-saving fall-back hour, which I confirmed by
timing. The 18 DOT street-light negatives are all about −24 h; that is a pattern, and the cause is a hypothesis.

**How were cleaning decisions made?** By asking which metric each defect corrupts. A negative duration only
corrupts duration metrics, so the request still counts in volume. A missing creation date breaks everything, so
that record is quarantined. Contradictory open-with-close-date records go to manual review. Long durations are
retained because tree work genuinely takes a year.

**How does the dashboard support decisions?** It shows agency median/P90 for target setting, month-end backlog by
agency for resourcing, overdue categories for prioritisation, the data quality page for stewardship work queues,
and the impact page so managers know which numbers they can trust.

**How was reporting accuracy verified?** By implementing KPIs twice (pandas and SQL) and failing report generation
if they differ. Unit tests compare hand-computed KPI values on synthetic data. I checked the API's `count(*)`
against extracted rows, and spot-checked aggregates against direct Socrata `$group` queries (the 134,348 total and
the status counts matched).

**How does the pipeline handle failed refreshes?** Nothing is written until extraction completes. The raw file is
atomic and loading happens in one transaction. The run row is marked `failed` with the error. The previous analytics
state stays in place. A zero-row full refresh is refused. Tested in `test_failed_extraction_does_not_touch_existing_data`.

**Adapting to manufacturing / supply chain / logistics / inventory:** service request → work order, purchase order
or shipment; created/closed → order/delivery dates; agency → plant, supplier or carrier; complaint type → part or
lane; due_date → promised date (often well populated, so real OTIF/SLA metrics are possible). Backlog becomes open
orders, and aging becomes days past due. The validation rules carry over directly: received before shipped,
missing supplier, status/date conflicts, duplicate PO lines.

## 30+ interview questions

1. **Why not compute SLA compliance?** `due_date` is populated on 377 of 134,348 rows and is defined as an update
   date. I used a clearly labelled 7-day analytical target instead (83.0% met).
2. **Average vs median: which did you report?** Both. Median 15.3 h vs average 275.7 h. The average is driven by
   multi-month cases. Removing the 459 cases over 365 days lowers it by 34 h but moves the median by 0.3 h.
3. **What is P90 and why include it?** 90% of eligible requests resolved within 335 h. It shows how long the tail
   is, which neither the median nor the average does.
4. **How do you make the pipeline idempotent?** Hash-keyed raw inserts with DO NOTHING, a fact upsert on
   `unique_key`, deletion of stale keys, and per-run issue rows. Tested by running twice.
5. **What's in the hash and why exclude `:updated_at`?** Business fields only, so an untouched record re-extracted
   later produces the same hash.
6. **How does incremental mode work?** It filters on Socrata `:updated_at` greater than the last checkpoint minus 2
   days, then re-validates the whole window so cross-record rules (duplicates) stay correct.
7. **Why re-validate the whole window on incremental?** Duplicate detection needs every version of a key. At 134k
   rows that takes about 1 second.
8. **Offset pagination risks?** Rows inserted during paging can shift pages. I order by a stable key and fail if
   extracted < expected count.
9. **How did you handle the DST problem?** I flagged the records and excluded them from durations. The proper fix
   is offset-aware timestamps from the publisher, which I listed as a recommendation.
10. **What's a star schema and why use one here?** A fact table of requests with conformed dimensions. It suits Power
    BI's filter propagation and keeps the measures simple.
11. **Why store raw as JSONB?** It preserves the original record exactly, including fields I don't model yet.
12. **Why COPY instead of `to_sql`?** It loads 134k rows in seconds and runs in the same transaction through the
    psycopg3 connection.
13. **What does the quarantine table do when it's empty?** It's still there and tested. Records with missing IDs or
    creation dates would land there. None did in this extract.
14. **How do you count affected records when one has several issues?** Distinct record hash, so the pass rate is
    record-level.
15. **How is historical backlog calculated?** For each month end, requests created on or before it that were not
    validly closed by then. Closed-without-date records are excluded because their open interval is unknown.
16. **Limitation of that backlog?** Only the 2025 cohort, so January leaves out older carry-over, and it's
    reconstructed from current state rather than snapshots.
17. **Why are all current open requests 60+ days old?** The window ended 2025-12-31 and extraction was 2026-11-25.
18. **Which agencies are bottlenecks?** DPR (median 5.6 days, 2,476 open at year end) and DOB (median 23 days,
    34% within target). EDC helicopter noise has a 329-day median.
19. **Did cleaning change the KPIs?** Headline metrics changed by less than 0.5%; DOB median +9.2%. I didn't claim a
    bigger distortion than the numbers show.
20. **Which rule had the most hits?** DQ014 missing geography (731), mostly highway incidents. It is low severity
    because it only affects ZIP breakdowns.
21. **How would you add a new rule?** A YAML entry if the check type exists; otherwise one function in `CHECKS` plus
    a unit test.
22. **What does EXPLAIN ANALYZE show?** Agency+month drill-down: 13.2 ms → 0.54 ms with indexes (BitmapAnd). Issue
    lookup: 48.8 → 23.3 ms.
23. **Why not index everything?** Write cost and little gain. I documented a partial index I chose not to add.
24. **How do the tests reach a database in CI?** A GitHub Actions Postgres service container. Locally, the fixtures
    create an `ops311_test` database and skip if Postgres is unreachable.
25. **What edge cases are tested?** Open requests without a closed date (valid), records with multiple issues,
    empty extract, malformed records, future due date not flagged, page size that divides the row count exactly.
26. **What happens if the API returns HTML or an error object?** A non-list payload raises `ExtractionError`, which
    is retried if it was a 5xx.
27. **How would you schedule this?** Windows Task Scheduler or cron running `--incremental` nightly, then
    `--generate-reports`. Failures are visible in `ops.pipeline_runs`.
28. **Data privacy concerns?** The dataset is public and contains no personal names. Addresses are geovalidated
    locations. I extracted only the columns I needed.
29. **What would you do with more time?** Snapshot-based historical backlog, per-category targets agreed with
    stakeholders, a partial index for the review queue, and a tested PBIP.
30. **Behavioural: tell me about a time you found the data didn't support the original plan.** The brief asked for
    SLA compliance. The metadata showed there was no usable deadline, so I explained why and delivered a labelled
    substitute rather than inventing one.
31. **Behavioural: how do you communicate uncertainty?** Every root cause is labelled confirmed or hypothesis, and
    the report lists what can't be known without the source systems.
32. **Behavioural: how do you prioritise data issues?** By the metrics each one corrupts and how many records it
    affects. DQ011 got manual review because it changes DOB's reported performance; DQ014 was simply retained.

## STAR examples (from this project's real challenges)

**1. Daylight-saving negative durations.**
*S:* Validation flagged 24 requests that closed before they were created. *T:* Decide whether this was random noise
or something systematic before choosing a treatment. *A:* I grouped them by agency and time and found two patterns:
three NYPD records all between 01:34 and 01:58 on 2025-11-02 (the fall-back hour), and 18 DOT street-light records
offset by almost exactly 24 h. *R:* I excluded them from duration metrics only, so volume counts stayed intact. I
documented the DST cause as confirmed by timing and the DOT cause as a hypothesis, and recommended offset-aware
timestamps.

**2. Quantifying cleaning impact honestly.**
*S:* The brief expected data cleaning to change reported metrics. *T:* Measure the change rather than assume it.
*A:* I built a raw-vs-clean view with identical formulas, per agency, plus a per-rule attribution table. *R:*
City-wide KPIs moved by less than 0.5%, but DOB's median rose from 512 to 560 h because 154 open-with-close-date
records were inflating its closures. The recommendation became targeted: a DOB status review rather than a
city-wide cleanup.

**3. Making refreshes safe.**
*S:* During the first real extraction, the API returned HTTP 503 twice. *T:* Make sure a failed refresh could never
replace good data or publish zeros. *A:* I added retries with backoff, a count check, an atomic `.part` rename, a
single load transaction, and refusal of empty publishes, plus tests that simulate each failure. *R:* The real run
recovered automatically, and the integration tests show a failed refresh leaves every table unchanged and is
recorded as `failed`.

## Resume bullets (verified figures)

* Built a Python/PostgreSQL ELT pipeline that ingests 134,348 NYC 311 service requests through the Socrata API
  (paginated, retrying, idempotent) into raw, staging and star-schema analytics layers, backed by 44 automated
  tests in GitHub Actions.
* Designed a YAML-configurable data quality framework (14 rules, audit trail, quarantine and manual-review routing)
  that measured a 98.9% pass rate and traced 1,448 affected records to specific causes, including a
  daylight-saving timestamp defect and a 4-month closure-date gap in one workflow.
* Quantified data-cleaning impact on operational KPIs (city-wide change under 0.5%; Buildings median resolution
  +9.2%), wrote 17 analytical SQL queries, and built a 5-page Power BI dashboard (generated as a PBIP from code) on backlog, resolution time and
  data quality; indexing cut drill-down query time from 13.2 ms to 0.5 ms.
