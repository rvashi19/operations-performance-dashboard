# Business Findings: Evidence, Implications, Actions

Data: 134,348 Staten Island NYC 311 requests created in 2025 (run `0413c6d5-…`, extracted 2026-11-25).
Every number below was produced by:
* SQL: [`sql/analytics/business_findings.sql`](../sql/analytics/business_findings.sql), with output in
  [`reports/evidence/business_findings_output.txt`](evidence/business_findings_output.txt);
* Python: [`reports/evidence/business_findings.py`](evidence/business_findings.py), with output in
  [`reports/evidence/business_findings_python_output.txt`](evidence/business_findings_python_output.txt).

The two were computed independently and agree.

**Evidence labels:** **Confirmed** = shown directly by the data. **Hypothesis** = consistent with the data but not
verifiable without the agencies' systems.

---

## F1. Why the mean (275.7 h) is 18× the median (15.3 h)

**SQL (F1a, F1b)**
```sql
WITH r AS (SELECT resolution_hours h, ntile(100) OVER (ORDER BY resolution_hours DESC) AS pct
           FROM analytics.fact_service_request WHERE include_in_resolution_metrics)
SELECT round(100 * sum(h) FILTER (WHERE pct <= 1) / sum(h), 1) AS slowest_1pct_share, ...
```
```
   n    | mean_h | median_h | p75_h | p90_h | p99_h  |  max_h
 131951 |  275.7 |     15.3 |  89.2 | 335.4 | 6716.0 | 15502.0
 slowest_1pct_share | slowest_5pct_share | slowest_10pct_share
               31.1 |               74.8 |                86.2
```
**Python**
```python
top = h.sort_values(ascending=False)
top.iloc[:int(len(top) * .05)].sum() / top.sum()      # -> 0.748
top.iloc[int(len(top) * .01):].mean()                 # -> 192.0 h
```
**Agency share of all resolution hours (F1c):** DPR holds 43.0% of all hours with 8.2% of requests; DOB holds 21.3%
of hours with 3.3% of requests.

**Explanation (confirmed).** The distribution is extremely right-skewed. Half of all requests close within 15.3
hours, but the slowest 5% of requests account for 74.8% of all resolution hours. The mean is a total-hours figure
divided by a count, so it is dominated by those few long cases, mostly Parks tree and sidewalk work and Buildings
investigations. Removing only the slowest 1% drops the mean from 275.7 h to 192.0 h; the median barely moves.

**Business implication.** A target or headline built on the average would be driven by a few hundred capital-type
jobs and would hide the experience of a typical resident. Two agencies (DPR, DOB) make up 64% of all hours.

**Action.** Report median and P90 by agency. Track multi-month work (tree, sidewalk, building enforcement) as a
separate programme backlog rather than inside a single "resolution time" figure.

---

## F2. Why the Department of Buildings median changes by about 9.2%

**SQL (F2a–F2c)**
```
 agency | raw_n | clean_n | raw_median_hours | clean_median_hours | median_pct_diff
 DOB    |  4456 |    4302 |           512.43 |             559.67 |           9.219

 rule_id |  status  | records | median_raw_h | min_raw_h        -- DOB records removed from the duration sample
 DQ011   | Open     |     109 |          0.0 |       0.0
 DQ011   | Assigned |      45 |       1135.0 |       0.0

 dq011 |  n   | below_raw_median | under_one_day
 f     | 4302 |             2103 |           771
 t     |  154 |              125 |           115
```
**Python**
```python
removed = dob.loc[dob.record_hash.isin(dq011), "h"]
(removed < 1).mean(), removed.median()     # -> 0.721, 0.0 h
kept.median() / raw.median() - 1           # -> +9.2%
```

**Explanation (confirmed mechanism).** 154 DOB requests have an *open-type* status (109 Open, 45 Assigned) but
also carry a `closed_date` (rule DQ011). A naive report treats that closed date as a resolution. For the 109
"Open" ones, the closed date is the **same timestamp as creation** (median raw duration 0.0 h; 72.1% of the 154
are under one hour). Including them adds 154 artificially short durations, 125 of them below the DOB median, which
pulls the median down from the true 559.7 h to 512.4 h. The policy excludes DQ011 records from resolution metrics
(the status field says the work is not finished), so the cleaned median is 9.2% higher. The average moves only
+2.6% because those records are short, and short values barely move a mean dominated by long cases.

*Hypothesis:* the closed date on these "Open" records is set when the request is handed from 311 to DOB's own
system, not when DOB finishes the work. Their resolution text ("Your Service Request has been submitted to the
Department of Buildings. Please check back…") is consistent with that, but it cannot be confirmed from public data.

**Business implication.** A naive DOB report overstates responsiveness. Nearly 3% of DOB requests appear resolved
instantly when they are not finished. That matters more for this agency than for the borough total.

**Action.** Ask DOB/311 what the closed date means on hand-off records. Until then, keep excluding open-status
durations and report the DQ011 count beside DOB's KPIs.

---

## F3. Business implications of the 62 missing closure dates

**SQL (F3a, F3b) / Python**
```
 closed_date_missing | requests | first_created | last_created | median_h
 f                   |      307 | 2025-01-04    | 2025-12-28   |     2.11
 t                   |       62 | 2025-01-09    | 2025-05-05   |

 Jan-May: 62 of 81 DHS requests lack a closed date; Jun-Dec: 0
 (by month: Jan 8/10, Feb 3/5, Mar 26/27, Apr 21/24, May 4/15, Jun-Dec 0)
```

**Explanation.** *Confirmed:* every case is DHS "Homeless Person Assistance" with status Closed; 77% of DHS
requests created January–May lack a closed date, and none from June onwards. *Hypothesis:* a time-bounded
integration or process problem in the DHS outreach workflow that was fixed around May 2025. The available data
cannot show the cause or the actual closure times.

**Business implications.**
* DHS resolution time is measured on only 307 of 369 requests, and on almost none from March–April. Any DHS trend
  for early 2025 is unreliable.
* These requests count as **closed** (resolution rate unaffected) but are excluded from historical backlog, because
  when they stopped being open is unknown.
* At borough level the effect is invisible (62 of 134,348). At agency level it affects 17% of DHS's volume (F6).

**Action.** Request a backfill of closure times from DHS. Add a monitoring alert when an agency's
"closed without date" share exceeds a threshold in any month, which would have caught this in January.

---

## F4. Why the 459 long-duration requests were retained

**SQL (F4a–F4c)**
```
 DPR Dead/Dying Tree 90 (avg 423 days), Root/Sewer/Sidewalk 79 (417), Damaged Tree 76 (421),
 Overgrown Tree 64 (434), DOB General Construction 47 (425), DOB Building/Use 46 (399), ...

        sample        |   n    | mean_h | median_h | p90_h
 all valid            | 131951 |  275.7 |    15.30 | 335.4
 excluding > 365 days | 131493 |  241.3 |    15.02 | 325.6

 Top closing texts: "NYC Parks performed the work necessary to correct the condition." (227),
                    "NYC Parks inspected and determined this site does not rate high enough..." (63)
```
(458 of the 459 are in the cleaned resolution sample; the other is also an open-with-close-date DQ011 record and
is already excluded.)

**Explanation.** Most long cases are Parks tree and sidewalk jobs, and 227 of them close with "performed the work
necessary". That is consistent with real scheduled work, not data errors. Excluding them would lower the mean by
12.5% (to 241.3 h) and move the median only 0.28 h, which would make reported performance look better by deleting
real, slow work.

**Business implication.** Retaining them keeps the scorecard honest. The sensitivity row shows the size of the
choice, so a reader can see both figures.

**Action.** Keep them flagged (DQ013, low severity). Report them as a separate long-cycle work queue. Revisit the
365-day threshold per category once agencies supply expected durations.

---

## F5. Statements that went beyond the evidence (reviewed and corrected)

| Earlier wording | Problem | Corrected to |
|---|---|---|
| "24 requests ... **caused by** the November daylight-saving clock change" (executive summary) | Only 3 of the 24 fall in the DST hour; the 18 DOT cases are a 24-hour offset with no confirmed cause | "3 coincide with the DST fall-back hour (timing confirmed); 18 DOT street-light tickets show a ~24 h offset (cause unknown)" |
| "highway incidents ... located by highway name rather than by address, **so** the extract has no ZIP" (RCA) | Plausible, but the location-capture process isn't visible in the data | Marked as a hypothesis |
| "154 open DOB requests carried **stale** closed dates" (dashboard text) | "Stale" implies they were once valid closures; the data shows most are ~0 h after creation | "carried closed dates, mostly ~0 h after creation" |
| "City-wide KPIs moved by less than 0.5%" (README, interview notes) | The scope is Staten Island, not the city | "Staten Island headline KPIs" |
| "pass rate 98.92%" | Correct for 14 rules; adding the DST rule (DQ015) gives 98.899% | Updated everywhere with the denominator stated |

**DST check (F5 SQL).** The new DQ015 rule found 41 ambiguous local timestamps on 34 requests, all on the night of
2025-11-01/02 (issues by agency: NYPD 35, DOT 3, HPD 2, DHS 1). None fall in the skipped spring-forward hour.

---

## F6. How aggregate metrics hide agency-specific data quality problems

```
 overall request-level affected rate: 1.10%   (pass rate 98.90%)
 DHS 17.34% · TLC 7.52% · DOB 5.77% · EDC 4.75% · DPR 2.67% · DOT 2.08% ...
```

**Explanation (confirmed).** A borough-wide 98.9% pass rate averages a 17% problem rate at DHS with near-zero rates
at large agencies like NYPD (0.3%) and DEP. Because NYPD and DSNY make up over half of all requests, their clean
data dominates the denominator. The same happens with KPIs: cleaning moves borough-wide headline metrics by at
most 0.41%, while DOB's median moves 9.2%.

**Business implication.** A single pass-rate number gives false comfort to exactly the agencies whose reports are
least reliable.

**Action.** Always show data quality **by agency** next to that agency's KPIs (page 4 of the dashboard does this),
and set alert thresholds per agency, not just for the total.

---

## F7. Backlog limitations (right-censoring and cohort)

```
 month   | created | pct_still_open | median_h
 2025-01 |   10128 |           0.94 |     20.2
 ...
 2025-12 |   11015 |           1.59 |     22.3
```
* **Cohort.** Historical backlog counts only requests *created in 2025*. The January value (1,287) excludes older
  open work, so the series rises from an artificial zero. That is a property of the extract, not a trend.
* **Right-censoring.** Requests created late in the year have had less time to close, so their long cases are
  under-represented in resolution-time medians. Read monthly resolution trends with that caveat.
* **Reopened requests.** The data has no reopen history. Open-status records with a closed date (DQ011) are counted
  as open for backlog; when they were reopened cannot be known.
* **Missing closure dates** (F3) are excluded from historical backlog, because counting them as open forever would
  inflate it.
