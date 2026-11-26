# Data Quality Report

_Generated from pipeline run `0413c6d5-d438-4361-898b-7cc49b5a0160` (extracted 2026-11-25 21:38 New York time). Scope: NYC 311 requests created 2025-01-01 to 2025-12-31 inclusive, borough = STATEN ISLAND._

## Summary

Two rates are reported because they answer different questions. **Record level** counts every inspected row of the current source snapshot (an exact-duplicate copy or a row without an ID is still a row). **Request level** counts distinct `unique_key` values. In this extract each request has exactly one row, so the two coincide; they diverge as soon as duplicates or missing IDs appear.

| Measure | Value |
|---|---|
| Records (rows) inspected | 134,348 |
| Records affected by at least one rule | 1,479 (1.101%) |
| **Record-level pass rate** | **98.899%** |
| Requests (distinct IDs) inspected | 134,348 |
| Requests affected | 1,479 (1.101%) |
| **Request-level pass rate** | **98.899%** |
| Total individual issues (one per record per rule) | 1,508 |
| Duplicate request IDs inside the snapshot | 0 |
| Rows without a request ID | 0 |
| Records requiring manual investigation | 191 |

## Issues by rule

| rule_id   | rule_name                                | category     | severity   | treatment                       |   issues |   affected_records |
|:----------|:-----------------------------------------|:-------------|:-----------|:--------------------------------|---------:|-------------------:|
| DQ001     | Duplicate request ID                     | duplicate    | high       | deduplicate                     |        0 |                  0 |
| DQ002     | Exact duplicate record                   | duplicate    | medium     | deduplicate                     |        0 |                  0 |
| DQ003     | Missing request ID                       | completeness | critical   | quarantine                      |        0 |                  0 |
| DQ004     | Missing created date                     | completeness | critical   | quarantine                      |        0 |                  0 |
| DQ005     | Closed status without closed date        | consistency  | high       | exclude_from_resolution_metrics |       62 |                 62 |
| DQ006     | Closed before created                    | validity     | high       | exclude_from_resolution_metrics |       24 |                 24 |
| DQ007     | Invalid timestamp                        | validity     | high       | quarantine                      |        0 |                  0 |
| DQ008     | Unexpected future timestamp              | validity     | high       | exclude_from_resolution_metrics |        0 |                  0 |
| DQ009     | Missing complaint category               | completeness | medium     | retain                          |        0 |                  0 |
| DQ010     | Missing agency                           | completeness | medium     | manual_review                   |        0 |                  0 |
| DQ011     | Open status with closed date             | consistency  | medium     | manual_review                   |      191 |                191 |
| DQ012     | Undocumented status value                | validity     | medium     | manual_review                   |        0 |                  0 |
| DQ013     | Extreme resolution duration              | plausibility | low        | retain                          |      459 |                459 |
| DQ014     | Missing geography                        | completeness | low        | retain                          |      731 |                731 |
| DQ015     | Ambiguous or nonexistent local timestamp | validity     | low        | retain                          |       41 |                 34 |

## Issues by category

| issue_category   |   issues |   affected_records |
|:-----------------|---------:|-------------------:|
| completeness     |      731 |                731 |
| consistency      |      253 |                253 |
| plausibility     |      459 |                459 |
| validity         |       65 |                 55 |

## Issues by severity

| severity   |   issues |
|:-----------|---------:|
| high       |       86 |
| low        |     1231 |
| medium     |      191 |

## Missing values (all inspected records)

Missing values are not automatically errors: `closed_at` is legitimately empty for open requests, and `due_at` is an optional field populated by few agencies.

| column                 |   missing |   missing_pct |
|:-----------------------|----------:|--------------:|
| unique_key             |         0 |        0.0000 |
| created_at             |         0 |        0.0000 |
| closed_at              |      2200 |        1.6380 |
| due_at                 |    133971 |       99.7190 |
| resolution_updated_at  |      1114 |        0.8290 |
| agency                 |         0 |        0.0000 |
| complaint_type         |         0 |        0.0000 |
| descriptor             |        69 |        0.0510 |
| status                 |         0 |        0.0000 |
| resolution_description |      1779 |        1.3240 |
| borough                |         0 |        0.0000 |
| incident_zip           |       769 |        0.5720 |
| community_board        |         0 |        0.0000 |
| latitude               |      2936 |        2.1850 |
| longitude              |      2936 |        2.1850 |
| channel                |         0 |        0.0000 |

## Issue distribution by agency (request level, published requests)

| agency_code   |   published_requests |   requests_with_issues |   dq_issues |   affected_pct |
|:--------------|---------------------:|-----------------------:|------------:|---------------:|
| DHS           |                  369 |                     64 |          64 |        17.3440 |
| TLC           |                  133 |                     10 |          10 |         7.5190 |
| DOB           |                 4456 |                    257 |         258 |         5.7680 |
| EDC           |                  316 |                     15 |          15 |         4.7470 |
| DPR           |                11729 |                    313 |         313 |         2.6690 |
| DOT           |                16829 |                    350 |         368 |         2.0800 |
| DOE           |                   86 |                      1 |           1 |         1.1630 |
| DSNY          |                23878 |                    273 |         273 |         1.1430 |
| NYPD          |                48108 |                    181 |         184 |         0.3760 |
| DOHMH         |                 3497 |                      5 |           5 |         0.1430 |
| HPD           |                11903 |                      8 |           8 |         0.0670 |
| DEP           |                12324 |                      2 |           2 |         0.0160 |
| DCWP          |                  635 |                      0 |           0 |         0.0000 |
| OOS           |                   68 |                      0 |           0 |         0.0000 |
| OTI           |                   17 |                      0 |           0 |         0.0000 |

## Issue distribution over time (month request was created)

| created_month   |   DQ005 |   DQ006 |   DQ011 |   DQ013 |   DQ014 |   DQ015 |
|:----------------|--------:|--------:|--------:|--------:|--------:|--------:|
| 2025-01         |       8 |       2 |      12 |      35 |      60 |       0 |
| 2025-02         |       3 |       2 |      14 |      37 |      69 |       0 |
| 2025-03         |      26 |       1 |      12 |      84 |      74 |       0 |
| 2025-04         |      21 |       0 |      22 |      54 |     100 |       0 |
| 2025-05         |       4 |       1 |      14 |      65 |      55 |       0 |
| 2025-06         |       0 |       0 |      13 |      47 |      72 |       0 |
| 2025-07         |       0 |       0 |      14 |      58 |      31 |       0 |
| 2025-08         |       0 |       1 |      11 |      39 |      49 |       0 |
| 2025-09         |       0 |       6 |      22 |      23 |      39 |       0 |
| 2025-10         |       0 |       4 |      25 |      14 |      65 |       0 |
| 2025-11         |       0 |       3 |      18 |       3 |      60 |      41 |
| 2025-12         |       0 |       4 |      14 |       0 |      57 |       0 |

## Reconciliation

Each value below was computed independently in Python and in SQL and must match before this report is written (the run fails otherwise):

| check                       |       python |          sql |   tolerance |
|:----------------------------|-------------:|-------------:|------------:|
| total_requests              | 134,348.0000 | 134,348.0000 |      0.0000 |
| closed_requests             | 132,019.0000 | 132,019.0000 |      0.0000 |
| open_requests               |   2,329.0000 |   2,329.0000 |      0.0000 |
| unknown_status_requests     |       0.0000 |       0.0000 |      0.0000 |
| avg_resolution_hours        |     275.6785 |     275.6800 |      0.0060 |
| median_resolution_hours     |      15.2970 |      15.3000 |      0.0060 |
| p90_resolution_hours        |     335.3760 |     335.3800 |      0.0060 |
| raw_avg_resolution_hours    |     275.8118 |     275.8118 |      0.0001 |
| raw_median_resolution_hours |      15.2342 |      15.2342 |      0.0001 |
| requests_inspected          | 134,348.0000 | 134,348.0000 |      0.0000 |
| requests_affected           |   1,479.0000 |   1,479.0000 |      0.0000 |
| rolling_3m_last_month       |  10,801.3333 |  10,801.3300 |      0.0060 |
