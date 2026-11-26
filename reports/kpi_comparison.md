# Raw vs Cleaned KPI Comparison

_Run `0413c6d5-d438-4361-898b-7cc49b5a0160`; reporting date 2026-11-25._

**Raw** = a report built directly on the current source snapshot: every row counts, any non-Closed status counts as open, and any row with a `closed_date` contributes a duration (negative durations and open requests that carry a closed date included). **Cleaned** = the documented treatment policy (docs/validation_framework.md). Formulas are identical; only record treatment and status grouping differ. Rates are in percent; differences are computed from unrounded values and rounded only for display.

| metric                                   | unit    |    raw_value |   clean_value |   abs_diff |   pct_diff |
|:-----------------------------------------|:--------|-------------:|--------------:|-----------:|-----------:|
| Total requests                           | count   | 134,348.0000 |  134,348.0000 |     0.0000 |     0.0000 |
| Closed requests                          | count   | 132,019.0000 |  132,019.0000 |     0.0000 |     0.0000 |
| Open requests                            | count   |   2,329.0000 |    2,329.0000 |     0.0000 |     0.0000 |
| Resolution rate (percent)                | percent |      98.2664 |       98.2664 |     0.0000 |     0.0000 |
| Average resolution (hours)               | hours   |     275.8118 |      275.6785 |    -0.1333 |    -0.0480 |
| Median resolution (hours)                | hours   |      15.2342 |       15.2970 |     0.0628 |     0.4120 |
| P90 resolution (hours)                   | hours   |     335.9721 |      335.3760 |    -0.5961 |    -0.1770 |
| Within 7-day analytical target (percent) | percent |      83.0221 |       83.0240 |     0.0019 |     0.0020 |

## Explanation of observed changes

* **Counts unchanged.** Nothing was deduplicated or quarantined and no undocumented statuses were found, so total, closed and open counts are identical.
* **Durations.** The raw sample contains 24 negative durations; the policy removes every record whose rule has `excludes_from_resolution: true` (DQ005, DQ006, DQ008, DQ011). The attribution table shows the direction of each rule's effect.
* **Largest headline change: 0.412%.** Headline (Staten Island) reporting is not materially distorted; the impact is concentrated in specific agencies (below).

## Agency-level impact (agencies whose average or median changed)

| agency_code   |   raw_n |   clean_n |   raw_avg_hours |   clean_avg_hours |   avg_abs_diff |   avg_pct_diff |   raw_median_hours |   clean_median_hours |   median_pct_diff |
|:--------------|--------:|----------:|----------------:|------------------:|---------------:|---------------:|-------------------:|---------------------:|------------------:|
| DHS           |     307 |       307 |         23.4200 |           23.4200 |         0.0000 |         0.0000 |             2.1100 |               2.1100 |            0.0210 |
| DOB           |    4456 |      4302 |      1,757.1300 |        1,803.5200 |        46.4000 |         2.6410 |           512.4300 |             559.6700 |            9.2190 |
| DOHMH         |    3263 |      3261 |        384.5400 |          384.5400 |         0.0000 |         0.0000 |             5.0100 |               4.8800 |           -2.6350 |
| DOT           |   16571 |     16539 |        210.8000 |          211.2300 |         0.4300 |         0.2020 |            62.3200 |              62.7000 |            0.6140 |
| HPD           |   11842 |     11836 |        226.8500 |          226.9200 |         0.0800 |         0.0330 |            97.2600 |              97.2800 |            0.0130 |
| NYPD          |   48108 |     48105 |          2.1200 |            2.1200 |         0.0000 |         0.0070 |             1.3500 |               1.3500 |           -0.0210 |

## Attribution by rule (raw duration sample, one rule removed at a time)

Raw sample: 132,148 durations, mean 275.81 h, median 15.23 h. Rules with `removed_by_cleaning_policy = False` are sensitivity checks only.

| rule_id   | rule                                     |   records_in_raw_duration_sample |   avg_hours_if_removed |   median_hours_if_removed |   avg_change_vs_raw_hours | removed_by_cleaning_policy   |
|:----------|:-----------------------------------------|---------------------------------:|-----------------------:|--------------------------:|--------------------------:|:-----------------------------|
| DQ006     | Closed before created                    |                               24 |               275.8700 |                   15.2500 |                    0.0500 | True                         |
| DQ011     | Open status with closed date             |                              191 |               275.6700 |                   15.2900 |                   -0.1500 | True                         |
| DQ013     | Extreme resolution duration              |                              459 |               241.4200 |                   14.9700 |                  -34.3900 | False                        |
| DQ014     | Missing geography                        |                              728 |               274.3700 |                   15.0600 |                   -1.4400 | False                        |
| DQ015     | Ambiguous or nonexistent local timestamp |                               34 |               275.8700 |                   15.2500 |                    0.0600 | False                        |

## Cleaning treatment summary

| action                   | rule_ids   |   records |
|:-------------------------|:-----------|----------:|
| escalated                |            |       191 |
| excluded_from_resolution |            |        68 |
