# Root Cause Analysis: Data Quality Issues

Scope: 134,348 NYC 311 requests created in 2025 in Staten Island, extracted 2026-11-25 (America/New_York) by run
`6429c255-…` (see `reports/data_quality_report.md`). Evidence queries are in `sql/validation/root_cause_queries.sql`
and in notebook sections 8 and 10.

**Labels.** **Confirmed** means directly shown by the data. **Hypothesis** means plausible but needs the
agency's source system to verify. We had no access to any internal municipal system. Nothing below claims manual
data-entry error, because the published data contains no evidence of who or what wrote each timestamp.

## Summary

| Rule | Records | Concentrated in | Treatment | Metrics affected |
|---|---:|---|---|---|
| DQ005 Closed without closed date | 62 | DHS, Homeless Person Assistance, Jan 9 – May 5 2025 only | Exclude from resolution time | avg/median/P90, historical backlog |
| DQ006 Closed before created | 24 | DOT Street Light (18, Pending), DOT Street Condition (3), NYPD Noise on 2025-11-02 (3) | Exclude from resolution time | avg/median, target compliance |
| DQ011 Open status with closed date | 191 | DOB (154), DOT signals/lights (29), HPD (6), DOHMH (2) | Count as open; manual review | resolution time, closure rate, backlog |
| DQ013 Duration > 365 days | 459 | DPR trees/sidewalks (313), DOB (104) | Retain + flag | average (+34 h), P90 |
| DQ014 No ZIP and no coordinates | 731 | Highway Condition (529), Traffic (150) | Retain as "Unknown" geography | geographic breakdowns only |
| DQ015 Ambiguous local time (DST) | 34 requests (41 timestamps) | All on 2025-11-01/02 fall-back night (NYPD most) | Retain + flag | durations crossing the hour (±1 h) |
| DQ001–DQ004, DQ007–DQ010, DQ012 | 0 | — | — | — |

Separate from the rules, two **timestamp-precision observations** affect how comparable agencies are (section 6).

## 1. DQ005: Closed status without a closed date (62)

* **Pattern (confirmed).** All 62 are DHS *Homeless Person Assistance* requests. They make up 62 of 369 DHS requests
  (16.8%), and every DHS request in the extract has status Closed. All 62 were created between 2025-01-09 and
  2025-05-05. None appear after that date.
* **Comparison with unaffected records (confirmed).** The other 307 DHS requests carry closure dates and have a
  median resolution of 2.1 h. The resolution descriptions on affected and unaffected records use the same outreach
  outcome text ("could not find the person", "refused services").
* **Explanation (hypothesis).** The issue is limited to one workflow and a bounded time window, then stops. That fits
  a change in how the DHS outreach system passed closure timestamps to 311, which was later fixed. It does not fit
  random omission.
* **Metrics affected.** Resolution time cannot be computed for these records. In historical backlog their open
  interval is unknown, so they are excluded rather than counted as open forever. They still count in volume and
  closure rate.
* **Remediation.** Exclude from duration metrics only. Ask DHS/311 whether closure times can be backfilled from the
  outreach system.
* **Cannot establish.** The actual closure time, and whether a system migration happened in May 2025.

## 2. DQ006: Closed date before created date (24)

Two distinct mechanisms:

**a) NYPD Noise – Residential, 3 records, all created 2025-11-02 between 01:34 and 01:58 (confirmed).**
2025-11-02 is the US fall-back date, when 01:00–01:59 occurs twice. The dataset publishes local "floating"
timestamps with no UTC offset. A request created in the second 01:xx hour and closed in the first appears to close
before it opened, and the negative gaps (−4 to −40 minutes) are under one hour, as expected. *Confirmed by timing;
how the source system stores time zones is a hypothesis.*

**DQ015 cross-check (QA review):** the new ambiguous-timestamp rule flags these same records, plus 31
other requests created or closed in that hour that did not produce negative durations.

**b) DOT Street Light Condition, 18 records, status Pending, closed ≈24 h (−24.02 to −24.13 h) before creation (confirmed pattern).**
The offset is almost exactly one day and appears only on still-pending street-light requests whose resolution text
points to DOT's own tracking site. *Hypothesis:* the closed date belongs to a linked or prior street-light ticket for
the same pole, or a date was shifted when the two systems synchronised. Three further DOT Street Condition records
are 1.7–8.9 h negative, with no clear pattern.

* **Metrics affected.** Negative durations pull the average down and inflate within-target compliance. Removing
  them alone raises the raw mean by 0.06 h (`reports/kpi_comparison.md`).
* **Remediation.** Exclude from resolution metrics. Request offset-aware timestamps from the publisher. Send DOT
  pending street-light records to DOT for review (18 of them are also flagged DQ011).

## 3. DQ011: Open/assigned/pending status with a closed date (191)

* **Pattern (confirmed).** DOB accounts for 154 (General Construction/Plumbing 68, Building/Use 67). 109 are status
  *Open* with the resolution text "has been submitted to the Department of Buildings… check back". Others are
  *Assigned* with text about failed access or inspection attempts. The issue appears throughout the year.
* **Explanation (hypothesis).** These look like requests that were closed in 311 and then **reopened or handed back**
  inside the agency's workflow (for example, after a failed inspection attempt), with the old closed date never
  cleared. The data cannot confirm reopen events.
* **Metrics affected.** In a naive report these records would contribute durations even though the work is not
  finished. Removing them changes DOB's median resolution from 512 h to 560 h (+9.2%) and average from 1,757 h to
  1,804 h (+2.6%).
* **Remediation.** Treat as open (the status field is the documented state of the request), exclude its
  closed date, and route to DOB for manual review. These are the 191 *needs_manual_review* records.

## 4. DQ013: Resolution longer than 365 days (459, retained)

* **Pattern (confirmed).** DPR tree and sidewalk work (Dead/Dying Tree 90, Root/Sewer/Sidewalk 79, Damaged Tree 76,
  Overgrown 64; average about 420 days) and DOB construction complaints. The Noise – Helicopter cases (EDC, 15) have a
  328-day median across all closures.
* **Interpretation.** Tree and sidewalk repairs are known to be scheduled in multi-year programmes, so long durations
  are **plausible, not erroneous**. Some EDC helicopter cases may be batch closures. That is a hypothesis.
* **Metrics affected.** Excluding them would lower the mean from 275.8 h to 241.4 h (−12.5%) and barely move the
  median (15.2 → 15.0 h). This is why the dashboard leads with median and P90 rather than the average.
* **Remediation.** Retain and flag. Report DPR/DOB separately or by median.

## 5. DQ014: Missing geography (731, retained)

* **Pattern (confirmed).** 529 are *Highway Condition* and 150 are *Traffic* (DOT, NYPD, DSNY).
  *Hypothesis:* these are on expressways and are located by highway name rather than by address, which would
  explain the missing ZIP and coordinates; the location-capture process is not visible in the data.
* **Treatment.** Retained under "Unknown" geography. Only ZIP-level breakdowns are affected, and those cover 0.54%
  of records.

## 6. Observations that are not rule violations

* **Day-level precision at DOB (confirmed):** 3,985 of 4,456 DOB requests (89%) have closed times of exactly
  00:00:00, so DOB durations are measured in whole days, which biases them by up to ±1 day. DSNY has 234 such cases.
* **Zero-duration closures (confirmed):** 1,464 DOHMH requests (42%) close at the same second they are created,
  which looks like automatic closure or referral. DOHMH's 4.9 h median therefore says little about field response
  time. *Hypothesis:* these are referrals to another channel.
* **No official SLA:** `due_date` is populated for 377 of 134,348 records (0.28%), and the data dictionary describes
  it as the date the agency is expected to *update* the request. No official SLA is computed. A labelled 7-day
  **analytical target** is used instead.
* **Right-censoring:** requests created late in 2025 have had less time to close. This lowers the average for
  recent months (Q7 in `sql/analytics/operational_analysis.sql`). Month-to-month resolution trends should be read
  with that in mind.
* **Backlog window effect:** historical backlog counts only requests *created in 2025*. The January figure leaves
  out older carry-over requests, so the backlog grows from a base of zero by construction.

## 7. What cannot be established without the source systems

Actual closure times for DQ005, whether DQ011 records were genuinely reopened, the source of the DOT 24-hour
offset, whether DOHMH zero-duration records were real resolutions, and the time zone convention of the internal
timestamps.
