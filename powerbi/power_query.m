// =====================================================================================
// Power Query (M) for the Operations Performance & Data Quality dashboard.
// Create two parameters first (Home > Manage Parameters):
//   pServer   (Text) = "localhost:5433"
//   pDatabase (Text) = "ops311"
//   pExportFolder (Text) = "C:\path\to\operations-performance-dashboard\data\exports\"   (CSV fallback)
// Then create one Blank Query per section below (Advanced Editor), named as in the header comment.
// Option A (recommended) reads the PostgreSQL reporting views. Option B reads the CSV exports
// produced by `python -m src.pipeline --generate-reports` when no database connection is available.
// =====================================================================================

// ---------- Helper: fnSource (Option A: PostgreSQL) ----------
// Query name: fnSource
(schema as text, item as text) as table =>
let
    Source = PostgreSQL.Database(pServer, pDatabase),
    Data   = Source{[Schema = schema, Item = item]}[Data]
in
    Data

// ---------- Helper: fnCsv (Option B: CSV exports) ----------
// Query name: fnCsv
(fileName as text) as table =>
let
    Source   = Csv.Document(File.Contents(pExportFolder & fileName & ".csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])
in
    Promoted

// ---------- FactServiceRequests ----------
let
    Source  = fnSource("analytics", "v_service_requests"),
    // Option B: Source = fnCsv("fact_service_requests"),
    Typed   = Table.TransformColumnTypes(Source, {
                {"unique_key", type text}, {"status", type text}, {"status_group", type text},
                {"created_at", type datetime}, {"closed_at", type datetime}, {"effective_closed_at", type datetime},
                {"due_at", type datetime}, {"created_date_key", Int64.Type}, {"closed_date_key", Int64.Type},
                {"channel", type text}, {"agency_code", type text}, {"agency_name", type text},
                {"complaint_type", type text}, {"descriptor", type text}, {"borough", type text},
                {"incident_zip", type text}, {"community_board", type text},
                {"resolution_hours", type number}, {"resolution_days", type number},
                {"include_in_resolution_metrics", type logical}, {"within_analytical_target", type logical},
                {"dq_issue_count", Int64.Type}, {"dq_max_severity", type text}, {"needs_manual_review", type logical},
                {"created_month", type text}}),
    AddDate = Table.AddColumn(Typed, "created_date", each DateTime.Date([created_at]), type date),
    AddClosedDate = Table.AddColumn(AddDate, "effective_closed_date",
                    each if [effective_closed_at] = null then null else DateTime.Date([effective_closed_at]), type date),
    AddDQFlag = Table.AddColumn(AddClosedDate, "has_dq_issue", each [dq_issue_count] > 0, type logical)
in
    AddDQFlag

// ---------- DimDate ----------
let
    Source = fnSource("analytics", "dim_date"),
    Typed  = Table.TransformColumnTypes(Source, {{"date_key", Int64.Type}, {"full_date", type date}, {"year", Int64.Type},
               {"quarter", Int64.Type}, {"month", Int64.Type}, {"month_name", type text}, {"year_month", type text},
               {"iso_week", Int64.Type}, {"day_of_week", Int64.Type}, {"day_name", type text}, {"is_weekend", type logical}})
in
    Typed

// ---------- DimAgency ----------
let
    Source = fnSource("analytics", "dim_agency")
in
    Table.TransformColumnTypes(Source, {{"agency_key", Int64.Type}, {"agency_code", type text}, {"agency_name", type text}})

// ---------- BacklogMonthly ----------
let
    Source = fnSource("analytics", "v_backlog_monthly"),
    Typed  = Table.TransformColumnTypes(Source, {{"month_end", type date}, {"agency_code", type text}, {"backlog", Int64.Type}})
in
    Typed

// ---------- OpenRequests ----------
let
    Source = fnSource("analytics", "v_open_requests"),
    Typed  = Table.TransformColumnTypes(Source, {{"unique_key", type text}, {"agency_code", type text},
               {"complaint_type", type text}, {"borough", type text}, {"incident_zip", type text}, {"status", type text},
               {"created_at", type datetime}, {"age_days", Int64.Type}, {"aging_bucket", type text},
               {"overdue_vs_analytical_target", type logical}}),
    BucketOrder = Table.AddColumn(Typed, "aging_bucket_order", each
        List.PositionOf({"0-7", "8-14", "15-30", "31-60", "60+"}, [aging_bucket]), Int64.Type)
in
    BucketOrder

// ---------- DQIssues ----------
let
    Source = fnSource("ops", "v_dq_issues_latest"),
    Typed  = Table.TransformColumnTypes(Source, {{"issue_id", Int64.Type}, {"unique_key", type text}, {"rule_id", type text},
               {"rule_name", type text}, {"issue_category", type text}, {"severity", type text},
               {"affected_column", type text}, {"original_value", type text}, {"explanation", type text},
               {"recommended_treatment", type text}, {"resolution_status", type text}, {"detected_at", type datetimezone},
               {"agency", type text}, {"complaint_type", type text}, {"status", type text},
               {"created_at", type datetime}, {"closed_at", type datetime}, {"created_month", type text}}),
    SeverityOrder = Table.AddColumn(Typed, "severity_order", each
        List.PositionOf({"critical", "high", "medium", "low"}, [severity]), Int64.Type)
in
    SeverityOrder

// ---------- DQRules ----------
let
    Source = fnSource("ops", "v_dq_rule_summary")
in
    Table.TransformColumnTypes(Source, {{"issues", Int64.Type}, {"affected_records", Int64.Type}})

// ---------- RawVsClean ----------
let
    Source = fnSource("analytics", "v_raw_vs_clean"),
    Typed  = Table.TransformColumnTypes(Source, {{"metric", type text}, {"ord", Int64.Type}, {"raw_value", type number},
               {"clean_value", type number}, {"abs_diff", type number}, {"pct_diff", type number}})
in
    Typed

// ---------- RawVsCleanAgency ----------
let
    Source = fnSource("analytics", "v_raw_vs_clean_agency")
in
    Source

// ---------- CleaningAudit (summary; CSV produced by the pipeline) ----------
let
    Source = fnCsv("cleaning_audit_summary"),
    Typed  = Table.TransformColumnTypes(Source, {{"action", type text}, {"rule_ids", type text}, {"records", Int64.Type}})
in
    Typed

// ---------- StagingInspected (for the pass-rate denominator) ----------
let
    Source = Value.NativeQuery(PostgreSQL.Database(pServer, pDatabase),
        "SELECT count(*) AS records_inspected FROM staging.service_requests s, ops.pipeline_runs r " &
        "WHERE r.run_id = (SELECT run_id FROM ops.v_latest_load_run) AND s.created_at BETWEEN r.window_start AND r.window_end")
in
    Source
