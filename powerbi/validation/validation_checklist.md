# Power BI Validation Checklist

**Environment.** Power BI Desktop 2.160.1151.0 (Microsoft Store), Windows 11. Checked on 2026-11-25 against
pipeline run `0413c6d5-…` (incremental after full refresh `98e320b4-…`).

**Method.**
* **Values:** `powerbi/validation/run_dax_checks.ps1` runs DAX queries through ADOMD against the model while it is
  open in Desktop; the raw output is in `powerbi/validation/dax_results.json`. The expected values come from SQL on
  the same PostgreSQL database (`analytics.v_kpi_summary`, `v_backlog_monthly`, `v_monthly_volume_rolling`,
  `ops.v_dq_run_summary`, plus ad-hoc filtered counts).
* **Visuals:** checked from screenshots of each page after refresh (`powerbi/screenshots/`).
* **Interactive behaviour:** slicer and cross-filter behaviour was checked by DAX filter-context queries, which
  apply the same filters a slicer would. Clicking through slicers by hand was **not** done; it is listed as a
  remaining manual check.

## A. Structure

| Check | Result | Evidence |
|---|---|---|
| All five report pages open | Pass | Screenshots of all 5 pages |
| All visual references resolve | Pass (after fix) | The first build showed "unrecognized fields" on the page 3 historical backlog chart. Its TopN filter referenced a Requests measure through the Agency table alias. Fixed in `build_pbip.py` (`_topn`); the re-opened report shows no errors on any page |
| Data refresh succeeds | Pass | Refresh from `data/exports/*.csv` completes; all cards show values |
| Dataset paths are portable | **Partial** | The CSV folder is a Power Query parameter (`ExportFolder`) written by `build_pbip.py` from the repo location. Moving the repo means re-running `python powerbi/build_pbip.py` or editing the parameter (Transform data → Edit parameters). Power Query has no relative paths |
| Model relationships unambiguous | Pass | OpenRequests and DQIssues relate to Requests (on unique_key), not separately to Agency, so there is one filter path per slicer |

## B. Value reconciliation (expected = SQL, actual = DAX in Power BI)

| Measure | Filter context | Expected (SQL) | Actual (Power BI) | Result |
|---|---|---|---|---|
| Total Requests | none | 134,348 | 134,348 | ✅ |
| Closed Requests | none | 132,019 | 132,019 | ✅ |
| Open Requests | none | 2,329 | 2,329 | ✅ |
| Unknown Status Requests | none | 0 | BLANK (= 0) | ✅ |
| Resolution Rate | none | 0.9827 | 0.982664 | ✅ |
| Avg Resolution Hours | none | 275.68 | 275.678 | ✅ |
| Median Resolution Hours | none | 15.30 (15.297) | 15.297 | ✅ |
| P90 Resolution Hours | none | 335.38 (335.376) | 335.376 | ✅ (PERCENTILE.INC = percentile_cont) |
| Within 7-Day Analytical Target % | none | 0.8302 | 0.830240 | ✅ |
| Current Backlog | none | 2,329 | 2,329 | ✅ |
| Backlog At Period End | Calendar = 2025-06 | 4,361 | 4,361 | ✅ |
| Backlog At Period End | Calendar = 2025-12 | 6,641 | 6,641 | ✅ |
| Requests Created 3M Rolling Avg | 2025-01 / 2025-02 | NULL / NULL | BLANK / BLANK | ✅ |
| Requests Created 3M Rolling Avg | 2025-03 | 9,950.33 | 9,950.33 | ✅ |
| Requests Created 3M Rolling Avg | 2025-12 | 10,801.33 | 10,801.33 | ✅ (all 12 months match) |
| Record-Level DQ Pass Rate | none | 0.988991 | 0.988991 | ✅ |
| Request-Level DQ Pass Rate | none | 0.988991 | 0.988991 | ✅ |
| DQ Issues | none | 1,508 | 1,508 | ✅ |
| Pending Manual Review | none | 191 | 191 | ✅ |

## C. Slicer / filter propagation (DAX filter context = what a slicer applies)

| Filter | Measure | Expected (SQL) | Actual | Result |
|---|---|---|---|---|
| Agency = DOB | Total Requests / Current Backlog / DQ Issues / Median h | 4,456 / 154 / 258 / 559.67 | 4,456 / 154 / 258 / 559.669 | ✅ |
| Complaint = Root/Sewer/Sidewalk Condition | Total / Current Backlog / DQ Issues | 1,701 / 455 / 79 | 1,701 / 455 / 79 | ✅ (before the QA fix, complaint, ZIP and status slicers did **not** reach Current Backlog or DQ Issues) |
| ZIP = 10312 | Total / Current Backlog | 17,009 / 462 | 17,009 / 462 | ✅ |
| Status = In Progress | Total / Current Backlog | 1,773 / 1,773 | 1,773 / 1,773 | ✅ |

## D. Presentation checks

| Check | Result |
|---|---|
| Current and historical backlog clearly distinguished | ✅ Page 3 subtitle defines both; "Current backlog …" visuals use OpenRequests; "Historical backlog at month end" uses the DAX measure |
| Analytical target not presented as an official SLA | ✅ Measure named "Within 7-Day **Analytical** Target %"; subtitles on pages 1 and 2 state "not an official SLA" |
| Data quality issues can be investigated | ✅ Page 4: rule and agency bars cross-filter the issue-detail table (request ID, rule, severity, original value, treatment, status). A dedicated drill-through page was **not** generated |
| DQ denominators explicit | ✅ Record-level and request-level pass-rate cards come from the pipeline's run summary; the agency bar is labelled "% of published requests" |

## E. Manual checks still required (not performed)

1. Click each slicer value by hand and confirm the visuals respond as the DAX checks predict.
2. Click bars to confirm cross-highlighting versus cross-filtering behaviour is acceptable to a user.
3. Hover tooltips and check their formatting.
4. Save the project in Desktop (Ctrl+S, choose **Don't upgrade** to TMDL) and optionally export a .pbix.
5. Open the PBIP on a second machine after re-running `build_pbip.py` (portability).
6. Add a drill-through page if required (not generated by code).
