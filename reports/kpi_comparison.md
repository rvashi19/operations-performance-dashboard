# Raw vs Cleaned KPI Comparison

_Run `6429c255-b84f-48bb-8a71-91db31e92a3c`; reporting date 2026-11-25._

**Raw** = a report built directly on the extract: every row counts, and any row with a `closed_date` contributes a duration (including negative durations and open requests that carry a closed date). **Cleaned** = the documented treatment policy (docs/validation_framework.md). Formulas are identical; only the record treatment differs.

| metric                                    |    raw_value |   clean_value |   abs_diff |   pct_diff |
|:------------------------------------------|-------------:|--------------:|-----------:|-----------:|
| Total requests                            | 134,348.0000 |  134,348.0000 |     0.0000 |     0.0000 |
| Closed requests                           | 132,019.0000 |  132,019.0000 |     0.0000 |     0.0000 |
| Open requests (backlog at reporting date) |   2,329.0000 |    2,329.0000 |     0.0000 |     0.0000 |
| Resolution rate                           |       0.9827 |        0.9827 |     0.0000 |     0.0000 |
| Average resolution (hours)                |     275.8118 |      275.6800 |    -0.1318 |    -0.0480 |
| Median resolution (hours)                 |      15.2342 |       15.3000 |     0.0658 |     0.4320 |
| P90 resolution (hours)                    |     335.9721 |      335.3800 |    -0.5921 |    -0.1760 |
| Within 7-day analytical target            |       0.8302 |        0.8302 |     0.0000 |    -0.0020 |

## Explanation of observed changes

* **Counts unchanged.** No duplicate IDs, exact duplicates, missing IDs or missing creation dates were found, so nothing was deduplicated or quarantined; total, closed and open counts are identical.
* **Average resolution time 275.81 → 275.68 h.** Cleaning removed 24 negative durations (DQ006) and the durations of open requests that carried a closed date (DQ011). Removing negatives raises the mean; removing DQ011 (mostly long-running DOB cases) lowers it; the net effect is small.
* **Median 15.23 → 15.30 h.** Excluding negative values shifts the distribution up slightly.
* **Largest headline change: 0.432%.** At borough level the issues found here do not materially distort headline reporting; the impact is concentrated in specific agencies (below).

## Agency-level impact (agencies whose average changed)

| agency_code   |   raw_n |   raw_avg_hours |   clean_avg_hours |   avg_abs_diff |   avg_pct_diff |   raw_median_hours |   clean_median_hours |
|:--------------|--------:|----------------:|------------------:|---------------:|---------------:|-------------------:|---------------------:|
| DEP           |   12175 |         71.1700 |           71.1800 |         0.0100 |         0.0070 |            18.8000 |              18.8000 |
| DOB           |    4456 |      1,757.1300 |        1,803.5200 |        46.3900 |         2.6400 |           512.4300 |             559.6700 |
| DOT           |   16571 |        210.8000 |          211.2300 |         0.4300 |         0.2030 |            62.3200 |              62.7000 |
| HPD           |   11842 |        226.8500 |          226.9200 |         0.0700 |         0.0320 |            97.2600 |              97.2800 |

## Attribution by rule (raw duration sample, one rule removed at a time)

Raw sample: 132,148 durations, mean 275.81 h, median 15.23 h.

| rule_id   |   records_in_raw_duration_sample |   avg_hours_if_removed |   median_hours_if_removed | applied_in_cleaning   |   avg_change_vs_raw_hours |
|:----------|---------------------------------:|-----------------------:|--------------------------:|:----------------------|--------------------------:|
| DQ005     |                                0 |               275.8100 |                   15.2300 | True                  |                   -0.0000 |
| DQ006     |                               24 |               275.8700 |                   15.2500 | True                  |                    0.0600 |
| DQ008     |                                0 |               275.8100 |                   15.2300 | True                  |                   -0.0000 |
| DQ011     |                              191 |               275.6700 |                   15.2900 | True                  |                   -0.1400 |
| DQ013     |                              459 |               241.4200 |                   14.9700 | False                 |                  -34.3900 |

DQ013 (durations > 365 days) is **retained** by policy because long tree/sidewalk and building cases are plausible; the row above is a sensitivity check showing how much the average depends on those cases.

## Cleaning treatment summary

| action                   | rule_ids   |   records |
|:-------------------------|:-----------|----------:|
| escalated                |            |       191 |
| excluded_from_resolution |            |        68 |

## Python cross-check of naive KPIs

`naive_kpis()` gives total=134,348, avg=275.81 h, median=15.23 h, matching the SQL raw column.
