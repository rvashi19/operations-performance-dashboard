# Data Dictionary

## Source

| Item | Value |
|---|---|
| Dataset | 311 Service Requests from 2020 to Present (NYC Open Data, id `erm2-nwe9`) |
| Publisher | NYC Office of Technology and Innovation (311) |
| Landing page | https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9 |
| API endpoint | `https://data.cityofnewyork.us/resource/erm2-nwe9.json` (Socrata SODA 2.x) |
| Metadata endpoint (verified before implementation) | `https://data.cityofnewyork.us/api/views/erm2-nwe9.json` |
| Extract scope | `created_date` 2025-01-01 → 2025-12-31, `borough = 'STATEN ISLAND'` (134,348 rows) |
| Extraction date | 2026-11-25 (full refresh plus incremental run; see `ops.pipeline_runs`) |
| Licence / terms | The NYC Open Data Terms of Use apply. The metadata API returned no licence field for this dataset. NYC Open Data is published for free public use under the City's Open Data Law (Local Law 11 of 2012). Users should check the current terms on the portal before redistributing. |
| Raw copy | `data/raw/nyc311_full-refresh_<timestamp>.jsonl.gz`: one JSON object per line exactly as returned, plus Socrata's `:updated_at` system field. It is git-ignored; regenerate with the pipeline. |

### Why Staten Island, 2025

City-wide 2025 volume is about 3.66M records. Staten Island is the only borough whose full calendar year falls in
the requested 100k–300k range. A single complete borough gives a consistent operational scope, which a random
sample would not.

### Limitations of the source

* Timestamps are published as local "floating" times with no UTC offset. This is ambiguous during the
  daylight-saving fall-back hour (see the root cause analysis).
* `due_date` is populated for only 0.28% of records and means "expected update date", not a resolution deadline.
* The dataset holds each request's *current* state. Status history and reopen events are not published.
* Some agencies record closure time to the day (DOB) or close requests automatically (DOHMH).

## Field definitions (source descriptions from the metadata API, abridged)

| Source field | Staging column | Type | Definition | Required? |
|---|---|---|---|---|
| `unique_key` | unique_key | text | Unique identifier of a service request | Yes (DQ003) |
| `created_date` | created_at | timestamp | Date the request was created | Yes (DQ004) |
| `closed_date` | closed_at | timestamp | Date the request was closed by the responding agency | Only when status = Closed (DQ005) |
| `agency` / `agency_name` | agency / agency_name | text | Responding City agency acronym / full name | Yes (DQ010) |
| `complaint_type` | complaint_type | text | First level of the problem hierarchy | Yes (DQ009) |
| `descriptor` | descriptor | text | Further detail on the problem | No |
| `status` | status | text | Status of the request | Yes; must be a documented value (DQ012) |
| `due_date` | due_at | timestamp | Date the agency is expected to *update* the request (internal SLAs) | No |
| `resolution_description` | resolution_description | text | Last action taken by the agency | No |
| `resolution_action_updated_date` | resolution_updated_at | timestamp | Date the agency last updated the request | No |
| `borough` | borough | text | Borough, provided by the submitter and confirmed by geovalidation | Scope filter |
| `incident_zip` | incident_zip | text | ZIP code from geovalidation | No (DQ014 if coordinates also missing) |
| `community_board` | community_board | text | Community board from geovalidation | No |
| `city` | city | text | City from geovalidation | No |
| `latitude`, `longitude` | latitude, longitude | float | Geo-based coordinates | No |
| `open_data_channel_type` | channel | text | How the request was submitted (phone, online, mobile, other, unknown) | No |
| `location_type` | location_type | text | Type of location in the address | No |
| `:updated_at` | source_updated_at | timestamptz | Socrata system field: last time the row changed in the portal; used for incremental checkpoints | System |

Staging also keeps `created_date_raw`, `closed_date_raw`, `due_date_raw` and `resolution_updated_raw`, the exact
source text, so timestamp parse failures stay auditable.

### Status values

Documented set used by DQ012 (`config/validation_rules.yaml`): Assigned, Cancel, Closed, Draft, Email Sent,
In Progress, Open, Pending, Started, Unassigned, Unspecified. Observed in this extract: Closed 132,019;
In Progress 1,773; Pending 233; Open 217; Assigned 99; Started 7. *Assumption:* the list is taken from the 311
data dictionary attachment and from values observed across the dataset. The attachment was not parsed
programmatically, so update the YAML if the publisher adds new statuses.

## Analytics columns (fact_service_request)

| Column | Meaning |
|---|---|
| status_group | `Closed` if status = Closed, otherwise `Open` |
| effective_closed_at | closed_at only when valid for metrics; drives historical backlog and monthly closures |
| resolution_hours / resolution_days | closed_at − created_at for eligible records; NULL otherwise |
| include_in_resolution_metrics | Closed, has a closed date, and none of DQ005/DQ006/DQ008/DQ011 |
| within_analytical_target | resolution_days ≤ 7 (configurable); NULL when not eligible |
| dq_issue_count / dq_max_severity | Number of rules the record failed / worst severity |
| needs_manual_review | Has an issue with treatment `manual_review` |
