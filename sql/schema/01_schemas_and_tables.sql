-- Idempotent database initialisation: safe to run on every pipeline start.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS analytics;

-- ---------- ops: pipeline execution history ----------
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id              UUID PRIMARY KEY,
    mode                TEXT NOT NULL CHECK (mode IN ('full-refresh','incremental','validate-only','generate-reports')),
    status              TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    duration_seconds    NUMERIC(12,2),
    window_start        TIMESTAMP,
    window_end          TIMESTAMP,
    records_extracted   INTEGER,
    records_loaded      INTEGER,
    records_rejected    INTEGER,
    issues_detected     INTEGER,
    checkpoint_updated_at TIMESTAMPTZ,  -- max Socrata :updated_at seen; drives incremental runs
    raw_file            TEXT,
    error_message       TEXT
);

-- ---------- raw: records exactly as returned by the API ----------
CREATE TABLE IF NOT EXISTS raw.service_requests (
    record_hash     CHAR(32) PRIMARY KEY,           -- md5 of canonical JSON: exact duplicates cannot be stored twice
    unique_key      TEXT,                            -- nullable on purpose: missing IDs must be observable
    payload         JSONB NOT NULL,
    source_updated_at TIMESTAMPTZ,
    first_run_id    UUID NOT NULL REFERENCES ops.pipeline_runs(run_id),
    extracted_at    TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_raw_unique_key ON raw.service_requests(unique_key);

-- ---------- staging: typed, standardised, not yet validated ----------
CREATE TABLE IF NOT EXISTS staging.service_requests (
    record_hash     CHAR(32) PRIMARY KEY REFERENCES raw.service_requests(record_hash),
    unique_key      TEXT,
    created_at      TIMESTAMP,
    closed_at       TIMESTAMP,
    due_at          TIMESTAMP,
    resolution_updated_at TIMESTAMP,
    agency          TEXT,
    agency_name     TEXT,
    complaint_type  TEXT,
    descriptor      TEXT,
    status          TEXT,
    resolution_description TEXT,
    borough         TEXT,
    incident_zip    TEXT,
    community_board TEXT,
    city            TEXT,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    channel         TEXT,
    location_type   TEXT,
    source_updated_at TIMESTAMPTZ,
    -- original text of timestamp fields, kept so parse failures stay auditable
    created_date_raw TEXT,
    closed_date_raw  TEXT,
    due_date_raw     TEXT,
    resolution_updated_raw TEXT
);
CREATE INDEX IF NOT EXISTS ix_stg_unique_key ON staging.service_requests(unique_key);

-- ---------- ops: data quality ----------
CREATE TABLE IF NOT EXISTS ops.dq_rules (
    rule_id      TEXT PRIMARY KEY,
    rule_name    TEXT NOT NULL,
    check_type   TEXT NOT NULL,
    category     TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    treatment    TEXT NOT NULL,
    explanation  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.dq_issues (
    issue_id        BIGSERIAL PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES ops.pipeline_runs(run_id),
    record_hash     CHAR(32) NOT NULL,
    unique_key      TEXT,
    rule_id         TEXT NOT NULL REFERENCES ops.dq_rules(rule_id),
    issue_category  TEXT NOT NULL,
    severity        TEXT NOT NULL,
    affected_column TEXT NOT NULL,
    original_value  TEXT,
    explanation     TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL,
    recommended_treatment TEXT NOT NULL,
    resolution_status TEXT NOT NULL DEFAULT 'open'
        CHECK (resolution_status IN ('open','auto_treated','pending_manual_review','resolved')),
    UNIQUE (run_id, record_hash, rule_id, affected_column)
);
CREATE INDEX IF NOT EXISTS ix_dq_issues_rule ON ops.dq_issues(run_id, rule_id);
CREATE INDEX IF NOT EXISTS ix_dq_issues_key ON ops.dq_issues(unique_key);

-- ---------- analytics: star schema ----------
CREATE TABLE IF NOT EXISTS analytics.dim_date (
    date_key     INTEGER PRIMARY KEY,         -- yyyymmdd
    full_date    DATE NOT NULL UNIQUE,
    year         SMALLINT NOT NULL,
    quarter      SMALLINT NOT NULL,
    month        SMALLINT NOT NULL,
    month_name   TEXT NOT NULL,
    year_month   CHAR(7) NOT NULL,
    iso_week     SMALLINT NOT NULL,
    day_of_week  SMALLINT NOT NULL,           -- ISO: 1=Mon
    day_name     TEXT NOT NULL,
    is_weekend   BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_agency (
    agency_key   SERIAL PRIMARY KEY,
    agency_code  TEXT NOT NULL UNIQUE,
    agency_name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_complaint (
    complaint_key  SERIAL PRIMARY KEY,
    complaint_type TEXT NOT NULL,
    descriptor     TEXT NOT NULL,
    UNIQUE (complaint_type, descriptor)
);

CREATE TABLE IF NOT EXISTS analytics.dim_geography (
    geography_key   SERIAL PRIMARY KEY,
    borough         TEXT NOT NULL,
    incident_zip    TEXT NOT NULL,
    community_board TEXT NOT NULL,
    UNIQUE (borough, incident_zip, community_board)
);

CREATE TABLE IF NOT EXISTS analytics.fact_service_request (
    unique_key          TEXT PRIMARY KEY,
    record_hash         CHAR(32) NOT NULL REFERENCES staging.service_requests(record_hash),
    created_date_key    INTEGER NOT NULL REFERENCES analytics.dim_date(date_key),
    closed_date_key     INTEGER REFERENCES analytics.dim_date(date_key),
    agency_key          INTEGER NOT NULL REFERENCES analytics.dim_agency(agency_key),
    complaint_key       INTEGER NOT NULL REFERENCES analytics.dim_complaint(complaint_key),
    geography_key       INTEGER NOT NULL REFERENCES analytics.dim_geography(geography_key),
    status              TEXT NOT NULL,
    status_group        TEXT NOT NULL,   -- Closed | Open | Unknown (constraint below)
    created_at          TIMESTAMP NOT NULL,
    closed_at           TIMESTAMP,
    effective_closed_at TIMESTAMP,            -- closed_at only when it is valid for metrics; drives historical backlog
    due_at              TIMESTAMP,
    channel             TEXT,
    resolution_hours    NUMERIC(12,3),        -- NULL when not valid for resolution metrics
    resolution_days     NUMERIC(12,4),
    include_in_resolution_metrics BOOLEAN NOT NULL,
    within_analytical_target BOOLEAN,         -- NULL when not eligible
    dq_issue_count      SMALLINT NOT NULL DEFAULT 0,
    dq_max_severity     TEXT,
    needs_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    loaded_run_id       UUID NOT NULL REFERENCES ops.pipeline_runs(run_id),
    CHECK (resolution_hours IS NULL OR resolution_hours >= 0)
);
CREATE INDEX IF NOT EXISTS ix_fact_created ON analytics.fact_service_request(created_date_key);
CREATE INDEX IF NOT EXISTS ix_fact_closed ON analytics.fact_service_request(closed_date_key);
CREATE INDEX IF NOT EXISTS ix_fact_agency ON analytics.fact_service_request(agency_key);
CREATE INDEX IF NOT EXISTS ix_fact_complaint ON analytics.fact_service_request(complaint_key);
CREATE INDEX IF NOT EXISTS ix_fact_geo ON analytics.fact_service_request(geography_key);

-- Records excluded entirely from analytics (critical issues). Original rows remain in raw/staging.
CREATE TABLE IF NOT EXISTS analytics.quarantine (
    record_hash  CHAR(32) PRIMARY KEY REFERENCES staging.service_requests(record_hash),
    unique_key   TEXT,
    rule_ids     TEXT NOT NULL,
    reason       TEXT NOT NULL,
    run_id       UUID NOT NULL REFERENCES ops.pipeline_runs(run_id)
);

-- One row per cleaning decision taken on a record.
CREATE TABLE IF NOT EXISTS analytics.cleaning_audit (
    audit_id     BIGSERIAL PRIMARY KEY,
    run_id       UUID NOT NULL REFERENCES ops.pipeline_runs(run_id),
    record_hash  CHAR(32) NOT NULL,
    unique_key   TEXT,
    action       TEXT NOT NULL,  -- deduplicated_dropped | quarantined | excluded_from_resolution | normalized | escalated
    rule_ids     TEXT,
    detail       TEXT NOT NULL,
    decided_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_run ON analytics.cleaning_audit(run_id, action);

-- ---------- QA additions (idempotent; safe on databases created by earlier versions) ----------
ALTER TABLE ops.pipeline_runs ADD COLUMN IF NOT EXISTS scope_key TEXT;
ALTER TABLE ops.pipeline_runs ADD COLUMN IF NOT EXISTS records_inspected INTEGER;
ALTER TABLE ops.pipeline_runs ADD COLUMN IF NOT EXISTS records_affected INTEGER;
ALTER TABLE ops.pipeline_runs ADD COLUMN IF NOT EXISTS requests_inspected INTEGER;
ALTER TABLE ops.pipeline_runs ADD COLUMN IF NOT EXISTS requests_affected INTEGER;

ALTER TABLE analytics.fact_service_request DROP CONSTRAINT IF EXISTS fact_service_request_status_group_check;
ALTER TABLE analytics.fact_service_request ADD CONSTRAINT fact_service_request_status_group_check
    CHECK (status_group IN ('Closed', 'Open', 'Unknown'));

-- The records that make up the CURRENT source snapshot for the configured scope.
-- Full refresh replaces it with exactly what the source returned; incremental replaces the versions of
-- changed keys. raw/staging keep every version ever extracted (history); this table defines "now".
CREATE TABLE IF NOT EXISTS staging.current_snapshot (
    record_hash  CHAR(32) PRIMARY KEY REFERENCES staging.service_requests(record_hash),
    unique_key   TEXT,
    run_id       UUID NOT NULL REFERENCES ops.pipeline_runs(run_id)
);
CREATE INDEX IF NOT EXISTS ix_snapshot_key ON staging.current_snapshot(unique_key);
