# Executive Summary: Staten Island 311 Service Requests, 2025

_For operations management. Source: NYC Open Data, "311 Service Requests from 2020 to Present", extracted
2026-11-25. Every figure is calculated from the processed dataset. This is an independent analysis of public
data, not an official City report._

## What we looked at

134,348 service requests created in Staten Island during 2025, across 15 city agencies. The data was checked
against 15 quality rules before any metric was calculated.

## Headline results

| Measure | Result |
|---|---|
| Requests received | **134,348** |
| Requests closed | **132,019 (98.3%)** |
| Typical (median) time to resolve | **15.3 hours** |
| Average time to resolve | 275.7 hours (11.5 days) |
| 90% of requests resolved within | 335 hours (14 days) |
| Resolved within 7 days (internal analytical target, not an official SLA) | **83.0%** |
| Still open at extraction | 2,329 |
| Requests passing all data quality checks | **98.90%** (1,479 of 134,348 affected) |

## Key findings

1. **Most requests are resolved quickly, but a slow minority inflates the average.** The typical request closes in
   about 15 hours, yet the average is 18 times higher because of long-running cases such as tree and sidewalk
   work. Use the median and the 90th percentile for performance targets. An average-based target would be driven by
   a few hundred cases.
2. **Service speed differs widely by agency.** Police requests (36% of demand) close in a median of
   1.4 hours. Sanitation takes 2 days, Transportation 2.6 days, Housing 4 days, Parks 5.6 days and Buildings 23
   days. Parks and Buildings resolve fewer than 55% and 35% of requests within 7 days.
3. **Unresolved work built up through the year.** Closures trailed new requests in 10 of 12 months. Among requests
   created in 2025, those still open at month end rose from 1,287 in January to about 6,600 from September onward.
   Parks (2,476 open at year end) and Buildings (1,138) account for over half. Demand peaked in July (13,363
   requests).
4. **The biggest overdue categories** are Parks root/sewer/sidewalk conditions (455 still open), sanitation dirty
   conditions (230) and street conditions (215).
5. **Data quality is good overall, with specific, explainable problems.** 1.10% of requests (1,479) had at least one
   issue. None were duplicates or missing an ID. The problems sit in particular workflows:
   * 62 homeless-assistance requests marked closed with no closure time, all between January and May 2025;
   * 191 requests, mostly Buildings, shown as open or assigned while also carrying a closure date;
   * 24 requests that appear to close before they were opened: 3 fall in the November daylight-saving fall-back
     hour, and 18 street-light tickets show a consistent one-day offset whose cause is unknown;
   * 731 highway incidents with no address or coordinates.
6. **Cleaning changes the Staten Island headline numbers very little but matters for individual agencies.** Every headline metric
   moved by less than 0.5%. Buildings' median resolution time rose by 9% (512 → 560 hours) once open cases with old
   closure dates were excluded.

## Recommendations

1. Report resolution performance as **median and 90th percentile by agency**, not a single borough-wide average.
2. Ask Parks and Buildings for backlog reduction plans; track month-end backlog by agency each month.
3. Ask the Department of Buildings to review the 191 open-but-dated requests. Cleaning up their status would fix
   their reported performance.
4. Ask the data publisher for time-zone-aware timestamps (this removes the daylight-saving error) and for
   documented service deadlines, so official SLA compliance can be measured.
5. Treat zero-minute Health Department closures and midnight Buildings closures as administrative records when
   comparing agency response times.

## Limitations

One borough and one year. The published data reflects each request's current state, not its full history. No
internal City systems were available to confirm the causes labelled as hypotheses in
`reports/root_cause_analysis.md`.
