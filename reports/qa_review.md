# QA Review

Branch `qa/review`, reviewed 2026-11-25. Every result below was observed by running code. Nothing is claimed
without a command or test behind it.

**Verification summary**

| Check | Result |
|---|---|
| Automated tests | **62 passed, 0 failed, 0 skipped** (`python -m pytest -q -rs`; integration tests ran against PostgreSQL 16) |
| Full refresh on live API data | Succeeded: 134,348 extracted, 134,348 loaded, 0 rejected; raw `new=0 already_present=134348` (source unchanged since the previous extract) |
| Incremental refresh | Succeeded: 5,170 overlap records re-read, 0 new raw rows, 0 DQ001 (no false duplicates) |
| Report generation | Succeeded; the Python vs SQL reconciliation gate passed for 12 checks (`reports/data_quality_report.md`) |
| Notebook | Re-executed end to end with no errors |
| Power BI | Opened, refreshed and reconciled in Power BI Desktop 2.160 via DAX queries; all values match SQL (`powerbi/validation/validation_checklist.md`) |
| GitHub Actions | **Not run yet**: the branch has not been pushed. `REQUIRE_DB=1` is set so integration tests cannot silently skip |

## Issues

| ID | Severity | File:line (after fix) | Original problem | Implemented fix | Regression test | Verification | Remaining limitation |
|---|---|---|---|---|---|---|---|
| QA-01 | **High** | `src/pipeline.py:110`, `src/database/loader.py:55` | A full refresh validated every staging row ever loaded, so a record deleted at the source stayed in analytics forever | New `staging.current_snapshot`; a full refresh replaces it with exactly the extract; analytics is built from the snapshot; raw keeps history | `test_full_refresh_drops_records_no_longer_in_source` | Pass; live run `stale_removed=0` (nothing deleted at source) | Deletions are only detected by full refreshes, not incremental runs |
| QA-02 | **High** | `src/pipeline.py:112-115` | An updated record produced two staging versions, and DQ001 flagged the legitimate update as a "duplicate request ID" | Incremental runs replace the snapshot version of changed keys; DQ001 now only fires for conflicting versions inside one snapshot | `test_updated_record_is_history_not_duplicate`, `test_true_duplicate_versions_in_one_extract_are_flagged` | Pass; live incremental: 0 DQ001 | — |
| QA-03 | **High** | `src/pipeline.py:35`, `src/database/loader.py:136`, `src/ingestion/socrata_client.py:58` | Staging reads and checkpoints ignored borough; checkpoints were global; the window used inclusive `BETWEEN ... 23:59:59.999` | Scope key (dataset, filters, half-open window) stored per run; checkpoints only reused for the same scope and snapshot; `created_date >= start AND < end` | `test_switching_scope_resets_snapshot_and_blocks_stale_incremental`, `test_where_clause_contains_window_filters_and_checkpoint` | Pass | Changing scope requires a full refresh (by design) |
| QA-04 | **High** | `src/validation/framework.py:157`, `sql/transformations/02_reporting_views.sql:145`, `powerbi/build_pbip.py` (DQSummary measures) | The pass rate mixed denominators: affected = distinct hashes, inspected = rows; DAX used published facts; there was no request-level rate | `summarize()` returns record-level (rows) and request-level (distinct IDs) counts separately; stored on `pipeline_runs`; `ops.v_dq_run_summary`; DAX reads it | `test_duplicate_rows_with_multiple_issues`, `test_missing_request_id_excluded_from_request_denominator`, `test_sql_python_kpi_and_dq_reconciliation` | Pass; live: 1,479 / 134,348 both levels (98.899%); Power BI 0.988991 | Agency-level rates use published requests (labelled) |
| QA-05 | Medium | `sql/analytics/operational_analysis.sql:77`, `sql/transformations/02_reporting_views.sql:57`, `src/analytics/kpis.py:64`, DAX `Requests Created 3M Rolling Avg` | The rolling figure was "ROWS 2 PRECEDING" over monthly medians, which shifts when a month is missing; DAX used ×30.4 days | Generated calendar months (zero-filled), `RANGE '2 months'`, a pooled 3-month median in SQL, `DATESINPERIOD(-3, MONTH)/3` in DAX, BLANK until 3 full months | `test_calendar_month_rolling_average_counts_empty_months_as_zero`, reconciliation test | Pass; DAX = SQL for all 12 months (e.g. Dec 10,801.33) | — |
| QA-06 | **High** | `src/pipeline.py:117-123`, `src/database/db.py:32` | Views were rebuilt and the run marked succeeded *after* the data commit, so a view failure left new data marked as failed (and vice versa) | Snapshot, data, views and successful-run metadata in one transaction; views are dropped and recreated transactionally | `test_failure_rolls_back_everything[validation|publication|views]` | Pass: counts, facts and checkpoint unchanged; run `failed` with error | Report generation is a separate run; if it fails, the data stays valid |
| QA-07 | Medium | `src/transformation/cleaning.py:18`, `config/validation_rules.yaml` (reference) | Any non-Closed status counted as open (e.g. Cancel, or an undocumented status) | Status groups Closed / Open / Unknown from config; Unknown is excluded from open, backlog and resolution, and is shown as its own KPI | `test_unknown_statuses_are_not_open` (3 cases) | Pass; live data has 0 Unknown | The documented status list was not machine-read from the publisher's data dictionary |
| QA-08 | Medium | `src/validation/framework.py:96`, `config/validation_rules.yaml` DQ015 | Floating local timestamps were treated as unambiguous | DQ015 flags times in the repeated or skipped DST hour (America/New_York); timezone configured | `test_dst_ambiguous_and_nonexistent_local_times` | Pass; live: 41 timestamps / 34 requests, all 2025-11-01/02 | True instants can't be recovered; flagged only |
| QA-09 | Medium | `sql/transformations/02_reporting_views.sql` (v_raw_vs_clean) | Raw-vs-clean mixed rounded cleaned values (2 dp) with unrounded raw; rates shown as 0.98; "open" definitions differed silently | Both sides computed unrounded from base tables; rates in percent with a `unit` column; definitions stated in the report | Reconciliation checks in `reports.py` (raw avg/median vs Python, 1e-4 tolerance) | Pass (median diff now 0.412%, previously 0.432% because of rounding) | — |
| QA-10 | Medium | `sql/transformations/02_reporting_views.sql:85`, DAX `Backlog At Period End`, `reports/business_findings.md` F7 | Backlog limits (cohort, right-censoring, reopened, missing closures) were not stated together; Unknown status included | Unknown excluded; limitations documented with evidence; the DAX backlog measure follows all slicers | Reconciliation (SQL vs DAX Jun 4,361, Dec 6,641) | Pass | No snapshots, so true historical backlog can't be rebuilt |
| QA-11 | Medium | `src/transformation/cleaning.py:30`, `config/settings.yaml` unknown_labels | `RESOLUTION_EXCLUDING_RULES` and DQ001/DQ002 IDs and labels were hardcoded | `excludes_from_resolution` flag per rule; deduplication keyed on the check type; labels from settings | `test_treatment_is_configuration_driven` | Pass | — |
| QA-12 | **High** | `powerbi/build_pbip.py:115` (relationships) | OpenRequests and DQIssues related only to Agency, so complaint, ZIP, status and month slicers didn't filter Current Backlog or DQ Issues; historical backlog came from an agency-only table | Both relate to Requests by unique_key; historical backlog is a DAX measure over Requests | DAX filter-context checks (`powerbi/validation/run_dax_checks.ps1`) | Pass: complaint filter → backlog 455, DQ 79 = SQL | Slicers not clicked by hand |
| QA-13 | Medium | `powerbi/build_pbip.py:347` (`_topn`) | (Found during this review) The TopN filter referenced a measure through the wrong table alias, so the page 3 chart showed "unrecognized fields" | Measure gets its own source alias | Visual check in Desktop | Pass (screenshot) | — |
| QA-14 | Low | `powerbi/build_pbip.py:128` | The Calendar filter hardcoded `year = 2025` | Calendar bounded by the configured window | DAX rolling checks | Pass | — |
| QA-15 | Medium | `README.md` | README said Power BI visuals were "untested" while another section said they had been verified | Statements aligned with what was actually verified; manual checks listed | — | Reviewed | — |
| QA-16 | Low | `README.md` (installation) | Placeholder clone URL `<your-repo-url>` | Real repository URL | — | Reviewed | — |
| QA-17 | Low | `README.md`, `reports/executive_summary.md`, `docs/interview_preparation.md` | "City-wide" used for Staten Island figures | "Staten Island" / "borough-wide" | — | `grep -i city-wide` → only the factual city-wide volume statement in the data dictionary remains | — |
| QA-18 | Medium | `reports/executive_summary.md`, `reports/root_cause_analysis.md` | Causal over-statements ("caused by the DST change" for all 24 negatives; highway location stated as fact; "stale" closed dates) | Reworded to separate confirmed timing from hypotheses | — | Reviewed against evidence (`reports/business_findings.md` F5) | — |
| QA-19 | Medium | `src/ingestion/socrata_client.py:69,80` | A malformed count response raised a bare KeyError; non-object rows were written to raw | `ExtractionError` for malformed counts and pages | `test_malformed_count_and_page_responses` | Pass | — |
| QA-20 | Medium | `tests/conftest.py:83`, `.github/workflows/tests.yml:24` | Integration tests skipped silently when Postgres was unreachable, including in CI | `REQUIRE_DB=1` in CI turns the skip into a failure | Behaviour visible in CI | Not yet observed in GitHub Actions (branch not pushed) | — |

## Not changed (reviewed, judged correct)

* The PERCENTILE.INC (DAX) and percentile_cont (SQL) equivalence was verified numerically (P90 335.376 both).
* Quarantine and the audit trail were already present; no change needed.
* Dataset path portability: the CSV folder is a Power Query parameter written by `build_pbip.py`. Power Query has no
  relative paths, so regenerate or edit the parameter on a new machine (documented, not "fixed").

## Revised resume bullets (verified figures only)

* Built a Python and PostgreSQL pipeline that loads 134,348 NYC 311 service requests from the Socrata API into
  raw, snapshot and star-schema layers, with scoped incremental refreshes, single-transaction publishing and 62
  passing automated tests.
* Designed a YAML-configured data-quality framework of 15 rules that separates record-level from request-level
  rates (98.9% pass) and traced the 1.1% of affected requests to concentrated causes, including 62 Homeless
  Services closures missing dates between January and May.
* Quantified how cleaning changes operational KPIs: under 0.5% on Staten Island headline metrics, but +9.2% on the
  Department of Buildings median, caused by 154 open requests carrying near-zero closure times. Built a 5-page
  Power BI report whose KPIs reconcile exactly with SQL.

(No claim of 10% issue rates, discovered duplicates, or confirmed source data-entry errors: none of these is
supported by the data.)
