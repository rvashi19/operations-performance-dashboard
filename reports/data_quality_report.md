# Data Quality Report

_Generated from pipeline run `6429c255-b84f-48bb-8a71-91db31e92a3c` (extracted 2026-11-26 00:37 UTC). Scope: NYC 311 requests created 2025-01-01 to 2025-12-31, borough = STATEN ISLAND._

## Summary

| Measure | Value |
|---|---|
| Total records inspected | 134,348 |
| Records passing all rules (valid) | 132,900 |
| Unique affected records | 1,448 (1.078%) |
| Total individual issues | 1,467 |
| Data quality pass rate | 98.922% |
| Duplicate request IDs | 0 (0.000%) |
| Exact duplicate records | 0 (0.000%) |
| Records requiring manual investigation | 191 |

A record with several issues is counted once in *unique affected records* and the pass rate; it is counted once per rule in *total individual issues*.

## Issues by rule

| rule_id   | rule_name                         | category     | severity   | treatment                       |   issues |   affected_records |
|:----------|:----------------------------------|:-------------|:-----------|:--------------------------------|---------:|-------------------:|
| DQ001     | Duplicate request ID              | duplicate    | high       | deduplicate                     |        0 |                  0 |
| DQ002     | Exact duplicate record            | duplicate    | medium     | deduplicate                     |        0 |                  0 |
| DQ003     | Missing request ID                | completeness | critical   | quarantine                      |        0 |                  0 |
| DQ004     | Missing created date              | completeness | critical   | quarantine                      |        0 |                  0 |
| DQ005     | Closed status without closed date | consistency  | high       | exclude_from_resolution_metrics |       62 |                 62 |
| DQ006     | Closed before created             | validity     | high       | exclude_from_resolution_metrics |       24 |                 24 |
| DQ007     | Invalid timestamp                 | validity     | high       | quarantine                      |        0 |                  0 |
| DQ008     | Unexpected future timestamp       | validity     | high       | exclude_from_resolution_metrics |        0 |                  0 |
| DQ009     | Missing complaint category        | completeness | medium     | retain                          |        0 |                  0 |
| DQ010     | Missing agency                    | completeness | medium     | manual_review                   |        0 |                  0 |
| DQ011     | Open status with closed date      | consistency  | medium     | manual_review                   |      191 |                191 |
| DQ012     | Undocumented status value         | validity     | medium     | manual_review                   |        0 |                  0 |
| DQ013     | Extreme resolution duration       | plausibility | low        | retain                          |      459 |                459 |
| DQ014     | Missing geography                 | completeness | low        | retain                          |      731 |                731 |

## Issues by category

| issue_category   |   issues |   affected_records |
|:-----------------|---------:|-------------------:|
| completeness     |      731 |                731 |
| consistency      |      253 |                253 |
| plausibility     |      459 |                459 |
| validity         |       24 |                 24 |

## Issues by severity

| severity   |   issues |
|:-----------|---------:|
| high       |       86 |
| low        |     1190 |
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

## Issue distribution by agency

| agency_code   |   total_requests |   records_with_dq_issues |   dq_issues |   affected_pct |
|:--------------|-----------------:|-------------------------:|------------:|---------------:|
| DHS           |              369 |                       63 |          63 |        17.0730 |
| TLC           |              133 |                       10 |          10 |         7.5190 |
| DOB           |             4456 |                      257 |         258 |         5.7680 |
| EDC           |              316 |                       15 |          15 |         4.7470 |
| DPR           |            11729 |                      313 |         313 |         2.6690 |
| DOT           |            16829 |                      347 |         365 |         2.0620 |
| DOE           |               86 |                        1 |           1 |         1.1630 |
| DSNY          |            23878 |                      273 |         273 |         1.1430 |
| NYPD          |            48108 |                      156 |         156 |         0.3240 |
| DOHMH         |             3497 |                        5 |           5 |         0.1430 |
| HPD           |            11903 |                        6 |           6 |         0.0500 |
| DEP           |            12324 |                        2 |           2 |         0.0160 |
| DCWP          |              635 |                        0 |           0 |         0.0000 |
| OOS           |               68 |                        0 |           0 |         0.0000 |
| OTI           |               17 |                        0 |           0 |         0.0000 |

## Issue distribution over time (month request was created)

| created_month   |   DQ005 |   DQ006 |   DQ011 |   DQ013 |   DQ014 |
|:----------------|--------:|--------:|--------:|--------:|--------:|
| 2025-01         |       8 |       2 |      12 |      35 |      60 |
| 2025-02         |       3 |       2 |      14 |      37 |      69 |
| 2025-03         |      26 |       1 |      12 |      84 |      74 |
| 2025-04         |      21 |       0 |      22 |      54 |     100 |
| 2025-05         |       4 |       1 |      14 |      65 |      55 |
| 2025-06         |       0 |       0 |      13 |      47 |      72 |
| 2025-07         |       0 |       0 |      14 |      58 |      31 |
| 2025-08         |       0 |       1 |      11 |      39 |      49 |
| 2025-09         |       0 |       6 |      22 |      23 |      39 |
| 2025-10         |       0 |       4 |      25 |      14 |      65 |
| 2025-11         |       0 |       3 |      18 |       3 |      60 |
| 2025-12         |       0 |       4 |      14 |       0 |      57 |

## Reconciliation

Headline KPIs were computed independently in Python (`src/analytics/kpis.py`) and SQL (`analytics.v_kpi_summary`) and matched: total_requests = 134348.0, closed_requests = 132019.0, median_resolution_hours = 15.3, avg_resolution_hours = 275.68.
