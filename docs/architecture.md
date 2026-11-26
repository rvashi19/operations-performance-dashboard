# Architecture

## Data flow

```mermaid
flowchart LR
    API[NYC Open Data<br/>Socrata SODA API<br/>erm2-nwe9] -->|paged GET, retries,<br/>count check| RAWF[(data/raw/*.jsonl.gz<br/>original, unchanged)]
    RAWF --> RAW[(raw.service_requests<br/>JSONB payload, md5 PK)]
    RAW --> STG[(staging.service_requests<br/>typed + safe normalisation)]
    STG --> VAL{{Validation framework<br/>config/validation_rules.yaml}}
    VAL --> ISS[(ops.dq_issues)]
    VAL --> CLN{{Treatment policy<br/>src/transformation/cleaning.py}}
    CLN --> FACT[(analytics star schema<br/>fact + 4 dimensions)]
    CLN --> Q[(analytics.quarantine)]
    CLN --> AUD[(analytics.cleaning_audit)]
    FACT --> VIEWS[Reporting views]
    ISS --> VIEWS
    VIEWS --> PBI[Power BI]
    VIEWS --> CSV[data/exports/*.csv]
    VIEWS --> MD[reports/*.md]
    RUNS[(ops.pipeline_runs)] -.checkpoint.-> API
```

## Layers

| Layer | Schema | Contents | Rule |
|---|---|---|---|
| Raw | `raw` | API records as JSONB, hash-keyed | Append-only; never modified. Old versions are kept as history. |
| Staging | `staging` | One typed row per raw row, plus original timestamp text | Only safe normalisation (trim, upper-case codes, ISO parse, 5-digit ZIP) |
| Ops | `ops` | Run history, rule catalogue, issues | One issue row per (run, record, rule, column) |
| Analytics | `analytics` | Star schema, quarantine, audit, views | Latest valid version per `unique_key` |

## Run modes

| Command | What it does |
|---|---|
| `--full-refresh` | Extracts the whole configured window, loads raw/staging, validates all staging rows in the window, rebuilds analytics |
| `--incremental` | Extracts records whose Socrata `:updated_at` is later than the last checkpoint minus a 2-day overlap, then does the same validation and publishing |
| `--validate-only` | Re-runs validation on staging and writes issues for a new run id; analytics untouched |
| `--generate-reports` | Rebuilds views, CSV exports, markdown reports and `reports/metrics.json` |

## Reliability design

* **Atomic raw file.** Pages stream to `*.part`, which is renamed only after the extracted row count is at least the
  API's own `count(*)`. A failed extract deletes the partial file and never replaces a good one.
* **Single transaction** covers raw insert, staging, issues, dimensions, fact upsert, quarantine and audit. Any
  exception rolls all of it back, and the run is recorded as `failed` with its error message.
* **No empty publish.** A full refresh that returns zero rows, or cleaning that leaves zero rows, is refused, so the
  dashboard can't show misleading zero metrics.
* **Idempotency.** Raw/staging use `ON CONFLICT (record_hash) DO NOTHING`. The fact table is upserted on
  `unique_key`, and keys no longer publishable are removed. Re-running a mode gives the same analytics state
  (verified by `tests/test_integration_pipeline.py` and by the incremental run on real data: 5,170 overlap rows
  re-read, 0 new raw rows).
* **Checkpoints.** `ops.pipeline_runs.checkpoint_updated_at` stores the maximum Socrata `:updated_at` seen. Retries
  are safe because of the overlap window and hash dedup.
* **Retries.** Exponential backoff on network errors, HTTP 429 and 5xx. Other 4xx errors fail immediately. During
  the real extraction two HTTP 503 responses were retried successfully.

## ER diagram (analytics, ops and staging)

```mermaid
erDiagram
    PIPELINE_RUNS ||--o{ RAW_SERVICE_REQUESTS : "first_run_id"
    RAW_SERVICE_REQUESTS ||--|| STAGING_SERVICE_REQUESTS : "record_hash"
    PIPELINE_RUNS ||--o{ DQ_ISSUES : "run_id"
    DQ_RULES ||--o{ DQ_ISSUES : "rule_id"
    STAGING_SERVICE_REQUESTS ||--o| FACT_SERVICE_REQUEST : "record_hash"
    STAGING_SERVICE_REQUESTS ||--o| QUARANTINE : "record_hash"
    DIM_DATE ||--o{ FACT_SERVICE_REQUEST : "created_date_key"
    DIM_DATE ||--o{ FACT_SERVICE_REQUEST : "closed_date_key"
    DIM_AGENCY ||--o{ FACT_SERVICE_REQUEST : "agency_key"
    DIM_COMPLAINT ||--o{ FACT_SERVICE_REQUEST : "complaint_key"
    DIM_GEOGRAPHY ||--o{ FACT_SERVICE_REQUEST : "geography_key"
    PIPELINE_RUNS ||--o{ CLEANING_AUDIT : "run_id"

    PIPELINE_RUNS { uuid run_id PK  text mode  text status  timestamptz started_at  int records_extracted  int records_loaded  int records_rejected  timestamptz checkpoint_updated_at }
    RAW_SERVICE_REQUESTS { char32 record_hash PK  text unique_key  jsonb payload  timestamptz source_updated_at }
    STAGING_SERVICE_REQUESTS { char32 record_hash PK  text unique_key  timestamp created_at  timestamp closed_at  text agency  text complaint_type  text status  text incident_zip }
    DQ_RULES { text rule_id PK  text category  text severity  text treatment }
    DQ_ISSUES { bigint issue_id PK  uuid run_id FK  char32 record_hash  text rule_id FK  text severity  text affected_column  text original_value  text resolution_status }
    FACT_SERVICE_REQUEST { text unique_key PK  int created_date_key FK  int closed_date_key FK  int agency_key FK  int complaint_key FK  int geography_key FK  text status_group  numeric resolution_hours  bool include_in_resolution_metrics  bool within_analytical_target  smallint dq_issue_count }
    DIM_DATE { int date_key PK  date full_date  char7 year_month  smallint day_of_week }
    DIM_AGENCY { int agency_key PK  text agency_code UK  text agency_name }
    DIM_COMPLAINT { int complaint_key PK  text complaint_type  text descriptor }
    DIM_GEOGRAPHY { int geography_key PK  text borough  text incident_zip  text community_board }
    QUARANTINE { char32 record_hash PK  text rule_ids  text reason }
    CLEANING_AUDIT { bigint audit_id PK  uuid run_id FK  char32 record_hash  text action  text detail }
```

## Why these technologies

* **PostgreSQL**: transactions, `ON CONFLICT` upserts, JSONB for unchanged raw payloads, `percentile_cont`, and a
  native Power BI connector. It runs locally in Docker.
* **Python + pandas**: the validation rules are clearer and easier to unit-test as DataFrame masks than as
  hundreds of lines of SQL. At 134k rows everything fits comfortably in memory.
* **COPY via psycopg3**: loads 134k rows in seconds inside the same transaction as the rest of the run.
* **Power BI**: the target BI tool for the roles this project is aimed at. The views keep business logic in SQL, so
  the DAX stays thin.
