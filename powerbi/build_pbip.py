"""Generates the Power BI Project (PBIP) powerbi/Ops311Dashboard.pbip from code.

Semantic model: import mode over data/exports/*.csv (refresh in Power BI Desktop after
`python -m src.pipeline --generate-reports`). Report: 5 pages, legacy report.json format.
    python powerbi/build_pbip.py
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "powerbi"
NAME = "Ops311Dashboard"
EXPORTS = str(ROOT / "data" / "exports") + "\\"

S, I, D, DT, B = "string", "int64", "double", "dateTime", "boolean"
M_TYPE = {S: "type text", I: "Int64.Type", D: "type number", DT: "type datetime", B: "type logical"}

# table -> (csv file, [(column, type)])
TABLES = {
    "Requests": ("fact_service_requests", [
        ("unique_key", S), ("status", S), ("status_group", S), ("created_at", DT), ("closed_at", DT),
        ("effective_closed_at", DT), ("created_date_key", I), ("closed_date_key", I), ("channel", S),
        ("agency_code", S), ("complaint_type", S), ("descriptor", S), ("incident_zip", S),
        ("community_board", S), ("resolution_hours", D), ("resolution_days", D),
        ("include_in_resolution_metrics", B), ("within_analytical_target", B), ("dq_issue_count", I),
        ("dq_max_severity", S), ("needs_manual_review", B), ("created_month", S)]),
    "Calendar": ("dim_date", [("date_key", I), ("full_date", DT), ("year", I), ("quarter", I), ("month", I),
                              ("month_name", S), ("year_month", S), ("day_of_week", I), ("day_name", S)]),
    "Agency": ("dim_agency", [("agency_code", S), ("agency_name", S)]),
    "Backlog": ("backlog_monthly", [("month_end", DT), ("agency_code", S), ("backlog", I)]),
    "OpenRequests": ("open_requests", [("unique_key", S), ("agency_code", S), ("complaint_type", S),
                                       ("incident_zip", S), ("status", S), ("created_at", DT), ("age_days", I),
                                       ("aging_bucket", S), ("overdue_vs_analytical_target", B)]),
    "DQIssues": ("dq_issues", [("issue_id", I), ("unique_key", S), ("record_hash", S), ("rule_id", S),
                               ("rule_name", S), ("issue_category", S), ("severity", S), ("affected_column", S),
                               ("original_value", S), ("recommended_treatment", S), ("resolution_status", S),
                               ("agency", S), ("complaint_type", S), ("status", S), ("created_at", DT),
                               ("closed_at", DT), ("created_month", S)]),
    "DQRules": ("dq_rule_summary", [("rule_id", S), ("rule_name", S), ("category", S), ("severity", S),
                                    ("treatment", S), ("issues", I), ("affected_records", I)]),
    "DQSummary": ("dq_run_summary", [("records_inspected", I), ("records_affected", I), ("record_pass_rate", D),
                                      ("requests_inspected", I), ("requests_affected", I), ("request_pass_rate", D),
                                      ("total_issues", I)]),
    "MissingValues": ("dq_missing_values", [("column", S), ("missing", I), ("missing_pct", D)]),
    "RawVsClean": ("raw_vs_clean", [("metric", S), ("ord", I), ("unit", S), ("raw_value", D), ("clean_value", D),
                                    ("abs_diff", D), ("pct_diff", D)]),
    "RawVsCleanAgency": ("raw_vs_clean_agency", [("agency_code", S), ("raw_avg_hours", D), ("clean_avg_hours", D),
                                                 ("avg_pct_diff", D), ("raw_median_hours", D),
                                                 ("clean_median_hours", D), ("median_pct_diff", D)]),
    "CleaningAudit": ("cleaning_audit_summary", [("action", S), ("rule_ids", S), ("records", I)]),
}

R = "Requests"
MEASURES = {
    R: [
        ("Total Requests", "COUNTROWS ( Requests )", "#,0", "Volume"),
        ("Closed Requests", "CALCULATE ( [Total Requests], Requests[status_group] = \"Closed\" )", "#,0", "Volume"),
        ("Open Requests", "CALCULATE ( [Total Requests], Requests[status_group] = \"Open\" )", "#,0", "Volume"),
        ("Unknown Status Requests", "CALCULATE ( [Total Requests], Requests[status_group] = \"Unknown\" )", "#,0", "Volume"),
        ("Resolution Rate", "DIVIDE ( [Closed Requests], [Total Requests] )", "0.0%", "Volume"),
        ("Requests Created", "[Total Requests]", "#,0", "Flow"),
        ("Requests Closed", "CALCULATE ( COUNTROWS ( Requests ), USERELATIONSHIP ( Requests[closed_date_key], Calendar[date_key] ), NOT ISBLANK ( Requests[effective_closed_at] ), Requests[closed_date_key] IN VALUES ( Calendar[date_key] ) )", "#,0", "Flow"),
        ("Net Backlog Change", "[Requests Created] - [Requests Closed]", "#,0", "Flow"),
        ("Requests Created 3M Rolling Avg",
         "VAR LastDay = MAX ( Calendar[full_date] ) "
         "VAR FirstDay = MINX ( ALL ( Calendar ), Calendar[full_date] ) "
         "VAR WindowStart = EDATE ( EOMONTH ( LastDay, -1 ) + 1, -2 ) "
         "RETURN IF ( WindowStart >= DATE ( YEAR ( FirstDay ), MONTH ( FirstDay ), 1 ), "
         "DIVIDE ( CALCULATE ( [Requests Created], DATESINPERIOD ( Calendar[full_date], LastDay, -3, MONTH ) ), 3 ) )",
         "#,0.0", "Flow"),
        ("Backlog At Period End",
         "VAR AsOf = MAX ( Calendar[full_date] ) + 1 "
         "RETURN CALCULATE ( COUNTROWS ( Requests ), REMOVEFILTERS ( Calendar ), Requests[created_at] < AsOf, "
         "Requests[status_group] <> \"Unknown\", "
         "NOT ( Requests[status_group] = \"Closed\" && ISBLANK ( Requests[effective_closed_at] ) ), "
         "ISBLANK ( Requests[effective_closed_at] ) || Requests[effective_closed_at] >= AsOf )",
         "#,0", "Backlog"),
        ("Avg Resolution Hours", "AVERAGE ( Requests[resolution_hours] )", "#,0.0", "Resolution"),
        ("Median Resolution Hours", "MEDIAN ( Requests[resolution_hours] )", "#,0.0", "Resolution"),
        ("P90 Resolution Hours", "PERCENTILE.INC ( Requests[resolution_hours], 0.9 )", "#,0", "Resolution"),
        ("Median Resolution Days", "DIVIDE ( [Median Resolution Hours], 24 )", "#,0.0", "Resolution"),
        ("Avg Resolution Days", "DIVIDE ( [Avg Resolution Hours], 24 )", "#,0.0", "Resolution"),
        ("P90 Resolution Days", "DIVIDE ( [P90 Resolution Hours], 24 )", "#,0.0", "Resolution"),
        ("Resolution Sample", "CALCULATE ( COUNTROWS ( Requests ), Requests[include_in_resolution_metrics] = TRUE () )", "#,0", "Resolution"),
        ("Within 7-Day Analytical Target %", "DIVIDE ( CALCULATE ( COUNTROWS ( Requests ), Requests[within_analytical_target] = TRUE () ), [Resolution Sample] )", "0.0%", "Resolution"),
        ("Published Requests With Issues", "CALCULATE ( COUNTROWS ( Requests ), Requests[dq_issue_count] > 0 )", "#,0", "Data Quality"),
        ("Published Requests With Issues %", "DIVIDE ( [Published Requests With Issues], [Total Requests] )", "0.00%", "Data Quality"),
        ("Pending Manual Review", "CALCULATE ( COUNTROWS ( Requests ), Requests[needs_manual_review] = TRUE () )", "#,0", "Data Quality"),
    ],
    "OpenRequests": [
        ("Current Backlog", "COUNTROWS ( OpenRequests )", "#,0", None),
        ("Overdue Open Requests", "CALCULATE ( COUNTROWS ( OpenRequests ), OpenRequests[overdue_vs_analytical_target] = TRUE () )", "#,0", None),
        ("Avg Backlog Age Days", "AVERAGE ( OpenRequests[age_days] )", "#,0", None),
    ],
    "Backlog": [("Month-End Backlog (SQL view)", "SUM ( Backlog[backlog] )", "#,0", None)],
    # run-level headline rates from the pipeline (explicit denominators; not affected by report slicers)
    "DQSummary": [("Record-Level DQ Pass Rate", "MAX ( DQSummary[record_pass_rate] )", "0.00%", None),
                  ("Request-Level DQ Pass Rate", "MAX ( DQSummary[request_pass_rate] )", "0.00%", None),
                  ("Records Inspected", "MAX ( DQSummary[records_inspected] )", "#,0", None),
                  ("Requests Affected", "MAX ( DQSummary[requests_affected] )", "#,0", None)],
    "DQIssues": [("DQ Issues", "COUNTROWS ( DQIssues )", "#,0", None)],
}

RELATIONSHIPS = [  # from (many), to (one), active
    (R, "created_date_key", "Calendar", "date_key", True),
    (R, "closed_date_key", "Calendar", "date_key", False),
    (R, "agency_code", "Agency", "agency_code", True),
    ("Backlog", "agency_code", "Agency", "agency_code", True),
    # OpenRequests and DQIssues hang off Requests, so EVERY slicer (agency, complaint, ZIP, status, month)
    # propagates to them through one unambiguous path.
    ("OpenRequests", "unique_key", R, "unique_key", True),
    ("DQIssues", "unique_key", R, "unique_key", True),
    ("RawVsCleanAgency", "agency_code", "Agency", "agency_code", True),
]


def _m_dt(iso):
    d = __import__("datetime").datetime.fromisoformat(iso)
    return f"#datetime({d.year}, {d.month}, {d.day}, 0, 0, 0)"


_SRC = __import__("src.config", fromlist=["settings"]).settings()["source"]
# Calendar limited to the configured (half-open) reporting window, read from config/settings.yaml
ROW_FILTER = {"Calendar": f"each [full_date] >= {_m_dt(_SRC['start_date'])} and [full_date] < {_m_dt(_SRC['end_date'])}"}


def m_expr(csv, cols, row_filter=None):
    types = ", ".join(f'{{"{c}", {M_TYPE[t]}}}' for c, t in cols)
    keep = ", ".join(f'"{c}"' for c, _ in cols)
    return "\n".join([
        "let",
        f'    Source = Csv.Document(File.Contents(ExportFolder & "{csv}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f"    Selected = Table.SelectColumns(Promoted, {{{keep}}}),",
        "    Nulls = Table.TransformColumns(Selected, List.Transform(Table.ColumnNames(Selected), (c) => {c, each if _ = \"\" then null else _})),",
        f'    Typed = Table.TransformColumnTypes(Nulls, {{{types}}}, "en-US"),',
        f"    Result = Table.SelectRows(Typed, {row_filter})" if row_filter else "    Result = Typed",
        "in",
        "    Result"])


def build_model():
    tables = []
    for name, (csv, cols) in TABLES.items():
        t = {"name": name, "columns": [], "partitions": [{"name": name, "mode": "import",
                                                          "source": {"type": "m", "expression": m_expr(csv, cols, ROW_FILTER.get(name))}}]}
        for c, typ in cols:
            col = {"name": c, "dataType": typ, "sourceColumn": c, "summarizeBy": "none"}
            if name == "Calendar" and c == "month_name":
                col["sortByColumn"] = "month"
            if name == "Calendar" and c == "day_name":
                col["sortByColumn"] = "day_of_week"
            if typ == DT and name == "Calendar":
                col["formatString"] = "yyyy-mm-dd"
            if c.endswith("_key") or c in ("ord",):
                col["isHidden"] = True
            t["columns"].append(col)
        if name == "Calendar":
            t["dataCategory"] = "Time"
            t["columns"][1]["isKey"] = True
        for mname, expr, fmt, folder in MEASURES.get(name, []):
            m = {"name": mname, "expression": expr, "formatString": fmt}
            if folder:
                m["displayFolder"] = folder
            t.setdefault("measures", []).append(m)
        tables.append(t)
    rels = [{"name": f"r{i}", "fromTable": a, "fromColumn": b, "toTable": c, "toColumn": d,
             **({} if active else {"isActive": False})} for i, (a, b, c, d, active) in enumerate(RELATIONSHIPS)]
    return {"compatibilityLevel": 1567, "model": {
        "culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3", "sourceQueryCulture": "en-US",
        "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
        "expressions": [{"name": "ExportFolder", "kind": "m", "expression":
                         json.dumps(EXPORTS) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'}],
        "tables": tables, "relationships": rels,
        "annotations": [{"name": "PBI_QueryOrder", "value": json.dumps(list(TABLES))}]}}


# ------------------------------------------------------------------ report helpers
MEASURE_HOME = {m[0]: t for t, ms in MEASURES.items() for m in ms}
NAVY, ORANGE, GREY = "#1F4E79", "#E07B39", "#605E5C"
DISPLAY = {"complaint_type": "Complaint type", "unique_key": "Request ID", "rule_id": "Rule", "severity": "Severity",
           "agency": "Agency", "status": "Status", "original_value": "Original value",
           "recommended_treatment": "Treatment", "resolution_status": "Resolution status", "metric": "Metric",
           "raw_value": "Raw", "clean_value": "Cleaned", "abs_diff": "Difference", "pct_diff": "% change",
           "Median Resolution Days": "Median days", "P90 Resolution Days": "P90 days",
           "Within 7-Day Analytical Target %": "Within 7 days", "unit": "Unit", "median_pct_diff": "Median % change",
           "avg_pct_diff": "Average % change", "raw_value": "Raw", "Total Requests": "Requests"}


def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": f"'{v}'"}}}


def color(hex_):
    return {"solid": {"color": lit(hex_)}}


class F:
    """A field reference: measure, column, or aggregated column."""

    def __init__(self, table, prop, kind="col", agg=None):
        self.table, self.prop, self.kind, self.agg = table, prop, kind, agg

    def expr(self, alias):
        src = {"SourceRef": {"Source": alias}}
        if self.kind == "measure":
            return {"Measure": {"Expression": src, "Property": self.prop}}
        col = {"Column": {"Expression": src, "Property": self.prop}}
        return {"Aggregation": {"Expression": col, "Function": self.agg}} if self.agg is not None else col

    @property
    def ref(self):
        base = f"{self.table}.{self.prop}"
        return {0: f"Sum({base})", 4: f"Max({base})"}.get(self.agg, base)


def M(name):
    return F(MEASURE_HOME[name], name, "measure")


def C(table, col, agg=None):
    return F(table, col, "col", agg)


X0, W, G = 16, 1248, 12          # page margin, usable width, gutter
SL_Y, SL_H = 66, 64              # slicer row
CARD_Y, CARD_H = 142, 80         # KPI card row
BODY_Y, BODY_B = 234, 706        # content area top / bottom
CHARTS = {"clusteredBarChart", "clusteredColumnChart", "lineChart", "scatterChart", "areaChart"}


def cols(*weights, x0=X0, width=W):
    """Split a row into columns proportional to weights, separated by the gutter."""
    free = width - G * (len(weights) - 1)
    out, x = [], x0
    for i, wt in enumerate(weights):
        w = round(free * wt / sum(weights)) if i < len(weights) - 1 else x0 + width - x
        out.append((x, w))
        x += w + G
    return out


def rows(n, y0=BODY_Y, bottom=BODY_B):
    h = (bottom - y0 - G * (n - 1)) // n
    return [(y0 + i * (h + G), h) for i in range(n)]


def _merge(objects, key, props):
    cur = objects.setdefault(key, [{"properties": {}}])
    for k, v in props.items():
        cur[0]["properties"].setdefault(k, v)


class Page:
    def __init__(self, name, title, subtitle):
        self.name, self.visuals, self.z = name, [], 0
        paragraphs = [
            {"textRuns": [{"value": title, "textStyle": {"fontSize": "18pt", "fontWeight": "bold", "color": "#1B2A41"}}]},
            {"textRuns": [{"value": subtitle, "textStyle": {"fontSize": "9pt", "color": GREY}}]}]
        self._add(X0, 2, W, 62, {"visualType": "textbox", "drillFilterOtherVisuals": True,
                                  "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
                                  "vcObjects": {"background": [{"properties": {"show": lit(False)}}],
                                                "border": [{"properties": {"show": lit(False)}}],
                                                "dropShadow": [{"properties": {"show": lit(False)}}]}})

    def _add(self, x, y, w, h, single, filters=None):
        self.z += 1
        vid = f"{self.name[:6]}{self.z:03d}".replace(" ", "")
        cfg = {"name": vid, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": self.z * 100, "width": w, "height": h}}],
               "singleVisual": single}
        self.visuals.append({"x": x, "y": y, "z": self.z * 100, "width": w, "height": h,
                             "config": json.dumps(cfg), "filters": json.dumps(filters or [])})

    def text(self, txt, x, y, w, h, size=10):
        paragraphs = []
        for line in txt.split("\n"):
            heading = line and not line.startswith("-")
            style = {"fontSize": f"{size + (1 if heading else 0)}pt", "color": "#1B2A41" if heading else "#323130"}
            if heading:
                style["fontWeight"] = "bold"
            paragraphs.append({"textRuns": [{"value": line or " ", "textStyle": style}]})
        self._add(x, y, w, h, {"visualType": "textbox", "drillFilterOtherVisuals": True,
                               "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
                               "vcObjects": {"background": [{"properties": {"show": lit(True), "color": color("#FFFFFF")}}],
                                             "border": [{"properties": {"show": lit(True), "color": color("#E1E4E8"), "radius": lit(8)}}],
                                             "padding": [{"properties": {"top": lit(10), "left": lit(14), "right": lit(14)}}]}})

    def visual(self, vtype, x, y, w, h, roles: dict, title=None, sort=None, objects=None, top_n=None, sync=None):
        aliases, frm, select, proj = {}, [], [], {}
        for role, fields in roles.items():
            for f in fields:
                if f.table not in aliases:
                    aliases[f.table] = f"t{len(aliases)}"
                    frm.append({"Name": aliases[f.table], "Entity": f.table, "Type": 0})
                if f.ref not in [s["Name"] for s in select]:
                    select.append({**f.expr(aliases[f.table]), "Name": f.ref})
                proj.setdefault(role, []).append({"queryRef": f.ref})
        query = {"Version": 2, "From": frm, "Select": select}
        if sort:
            f, desc = sort
            query["OrderBy"] = [{"Direction": 2 if desc else 1, "Expression": f.expr(aliases[f.table])}]
        objs = json.loads(json.dumps(objects or {}))
        if vtype in CHARTS:
            scatter = vtype == "scatterChart"
            _merge(objs, "categoryAxis", {"fontSize": lit(9), "showAxisTitle": lit(scatter), "titleFontSize": lit(9),
                                          "labelColor": color(GREY)})
            _merge(objs, "valueAxis", {"fontSize": lit(9), "showAxisTitle": lit(scatter), "titleFontSize": lit(9),
                                       "labelColor": color(GREY), "gridlineColor": color("#EDEBE9"), "labelDisplayUnits": lit(1)})
            if vtype == "clusteredBarChart":
                objs["categoryAxis"][0]["properties"]["maxMarginFactor"] = lit(45)
            if "legend" in objs:
                _merge(objs, "legend", {"fontSize": lit(9), "showTitle": lit(False)})
        if vtype == "tableEx":
            _merge(objs, "total", {"totals": lit(False)})
            _merge(objs, "columnHeaders", {"fontSize": lit(9), "fontColor": color("#FFFFFF"), "backColor": color(NAVY)})
            _merge(objs, "values", {"fontSize": lit(9)})
            _merge(objs, "grid", {"rowPadding": lit(3)})
        single = {"visualType": vtype, "projections": proj, "prototypeQuery": query, "drillFilterOtherVisuals": True,
                  "objects": objs}
        if vtype != "card":  # friendly display names for tables and legends; cards keep full measure names
            single["columnProperties"] = {q["Name"]: {"displayName": DISPLAY[q["Name"].split(".", 1)[1].rstrip(")")]}
                                          for q in select if q["Name"].split(".", 1)[1].rstrip(")") in DISPLAY}
        vc = {"background": [{"properties": {"show": lit(True), "color": color("#FFFFFF"), "transparency": lit(0)}}],
              "border": [{"properties": {"show": lit(True), "color": color("#E1E4E8"), "radius": lit(8)}}],
              "dropShadow": [{"properties": {"show": lit(False)}}],
              "padding": [{"properties": {"top": lit(6), "bottom": lit(6), "left": lit(8), "right": lit(8)}}]}
        if title:
            vc["title"] = [{"properties": {"show": lit(True), "text": lit(title), "fontSize": lit(11),
                                           "fontColor": color("#1B2A41"), "bold": lit(True)}}]
        else:
            vc["title"] = [{"properties": {"show": lit(False)}}]
        single["vcObjects"] = vc
        if sync:
            single["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
        filters = [self._topn(*top_n)] if top_n else []
        self._add(x, y, w, h, single, filters)

    @staticmethod
    def _topn(col, measure, n):
        # the measure may live in another table than the column (e.g. Agency column ranked by a Requests measure)
        frm = [{"Name": "f", "Entity": col.table, "Type": 0}]
        msrc = "f"
        if measure.table != col.table:
            frm.append({"Name": "m", "Entity": measure.table, "Type": 0})
            msrc = "m"
        sub = {"Version": 2, "From": frm,
               "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": col.prop}, "Name": "field"}],
               "OrderBy": [{"Direction": 2, "Expression": {"Measure": {"Expression": {"SourceRef": {"Source": msrc}}, "Property": measure.prop}}}],
               "Top": n}
        return {"name": f"topn_{col.prop}", "type": "TopN", "howCreated": 1,
                "expression": {"Column": {"Expression": {"SourceRef": {"Entity": col.table}}, "Property": col.prop}},
                "filter": {"Version": 2,
                           "From": [{"Name": "subquery", "Expression": {"Subquery": {"Query": sub}}, "Type": 2},
                                    {"Name": "f", "Entity": col.table, "Type": 0}],
                           "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": col.prop}}],
                                                           "Table": {"SourceRef": {"Source": "subquery"}}}}}]}}

    def cards(self, measures):
        objects = {"labels": [{"properties": {"fontSize": lit(22), "color": color(NAVY), "labelDisplayUnits": lit(1)}}],
                   "categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(9), "color": color(GREY)}}]}
        for (x, w), m in zip(cols(*[1] * len(measures)), measures):
            self.visual("card", x, CARD_Y, w, CARD_H, {"Values": [M(m)]}, objects=objects)

    def slicers(self):
        specs = [(C("Calendar", "year_month"), "Month", "sync_month"), (C("Agency", "agency_code"), "Agency", "sync_agency"),
                 (C(R, "complaint_type"), "Complaint type", "sync_cat"), (C(R, "incident_zip"), "ZIP code", "sync_zip"),
                 (C(R, "status"), "Status", "sync_status")]
        for (x, w), (f, label, grp) in zip(cols(1, 1, 1, 1, 1), specs):
            obj = {"data": [{"properties": {"mode": lit("Dropdown")}}],
                   "header": [{"properties": {"show": lit(True), "text": lit(label), "fontSize": lit(9),
                                              "fontColor": color(GREY)}}],
                   "items": [{"properties": {"fontSize": lit(9)}}]}
            self.visual("slicer", x, SL_Y, w, SL_H, {"Values": [f]}, objects=obj, sync=grp)

    def section(self, ordinal):
        return {"name": f"ReportSection{ordinal}", "displayName": self.name, "displayOption": 1,
                "width": 1280, "height": 720, "ordinal": ordinal, "visualContainers": self.visuals,
                "config": json.dumps({"objects": {"background": [{"properties": {"color": color("#F3F5F8"), "transparency": lit(0)}}]}}),
                "filters": "[]"}


def build_report():
    pages = []
    datalabels = {"labels": [{"properties": {"show": lit(True), "fontSize": lit(8), "labelDisplayUnits": lit(1), "color": color(GREY)}}]}
    legend_top = {"legend": [{"properties": {"show": lit(True), "position": lit("Top")}}]}
    orange = {"dataPoint": [{"properties": {"fill": color(ORANGE)}}]}

    # 1 ---------------------------------------------------------------- Executive Overview
    p = Page("Executive Overview", "Executive Overview",
             "Staten Island 311 requests created in 2025 | NYC Open Data erm2-nwe9 | 7-day target is analytical, not an official SLA | Current backlog = open at extraction")
    p.slicers()
    p.cards(["Total Requests", "Resolution Rate", "Median Resolution Hours", "Avg Resolution Hours",
             "Within 7-Day Analytical Target %", "Current Backlog"])
    (x1, w1), (x2, w2), (x3, w3) = cols(5, 3, 4)
    h = BODY_B - BODY_Y
    p.visual("lineChart", x1, BODY_Y, w1, h, {"Category": [C("Calendar", "year_month")],
                                             "Y": [M("Requests Created"), M("Requests Closed")]},
             title="Monthly incoming vs closed requests", sort=(C("Calendar", "year_month"), False), objects=dict(legend_top))
    p.visual("clusteredBarChart", x2, BODY_Y, w2, h, {"Category": [C("Agency", "agency_code")], "Y": [M("Total Requests")]},
             title="Requests by agency", sort=(M("Total Requests"), True), objects=dict(datalabels))
    p.visual("clusteredBarChart", x3, BODY_Y, w3, h, {"Category": [C(R, "complaint_type")], "Y": [M("Total Requests")]},
             title="Top 10 complaint types", sort=(M("Total Requests"), True),
             top_n=(C(R, "complaint_type"), M("Total Requests"), 10), objects={**datalabels, **orange})
    pages.append(p)

    # 2 ---------------------------------------------------------------- Operational Performance
    p = Page("Operational Performance", "Operational Performance",
             "Resolution time uses valid closures only. The 7-day target is an analytical benchmark: the source has no official SLA.")
    p.slicers()
    p.cards(["Median Resolution Days", "Avg Resolution Days", "P90 Resolution Days", "Within 7-Day Analytical Target %", "Resolution Sample"])
    (x1, w1), (x2, w2), (x3, w3) = cols(1, 1.25, 1)
    (ya, ha), (yb, hb) = rows(2)
    p.visual("clusteredBarChart", x1, BODY_Y, w1, BODY_B - BODY_Y, {"Category": [C("Agency", "agency_code")],
                                                                   "Y": [M("Median Resolution Days"), M("P90 Resolution Days")]},
             title="Median and P90 resolution days by agency", sort=(M("Median Resolution Days"), True), objects=dict(legend_top))
    p.visual("tableEx", x2, BODY_Y, w2, BODY_B - BODY_Y,
             {"Values": [C(R, "complaint_type"), M("Total Requests"), M("Median Resolution Days"),
                         M("P90 Resolution Days"), M("Within 7-Day Analytical Target %")]},
             title="Resolution by complaint type", sort=(M("Total Requests"), True))
    p.visual("lineChart", x3, ya, w3, ha, {"Category": [C("Calendar", "year_month")], "Y": [M("Median Resolution Hours")]},
             title="Median resolution hours by month created", sort=(C("Calendar", "year_month"), False))
    p.visual("scatterChart", x3, yb, w3, hb, {"Category": [C(R, "complaint_type")], "X": [M("Total Requests")],
                                             "Y": [M("Median Resolution Days")]},
             title="Bottlenecks: volume vs median days")
    pages.append(p)

    # 3 ---------------------------------------------------------------- Backlog & Demand
    p = Page("Backlog & Demand", "Backlog & Demand",
             "CURRENT backlog = open at extraction (all 60+ days old: window ended 2025-12-31). "
             "HISTORICAL backlog = 2025-created requests not validly closed at each month end (no pre-2025 carry-over).")
    p.slicers()
    p.cards(["Current Backlog", "Overdue Open Requests", "Avg Backlog Age Days", "Backlog At Period End"])
    (x1, w1), (x2, w2) = cols(1, 1)
    (ya, ha), (yb, hb) = rows(2)
    (x2a, w2a), (x2b, w2b) = cols(1, 1, x0=x2, width=w2)
    p.visual("lineChart", x1, BODY_Y, w1, BODY_B - BODY_Y,
             {"Category": [C("Calendar", "year_month")], "Series": [C("Agency", "agency_code")], "Y": [M("Backlog At Period End")]},
             title="Historical backlog at month end, top 6 agencies", sort=(C("Calendar", "year_month"), False),
             top_n=(C("Agency", "agency_code"), M("Backlog At Period End"), 6), objects=dict(legend_top))
    p.visual("clusteredColumnChart", x2a, ya, w2a, ha, {"Category": [C("OpenRequests", "aging_bucket")], "Y": [M("Current Backlog")]},
             title="Current backlog by age (days)", objects=dict(datalabels))
    p.visual("clusteredBarChart", x2b, ya, w2b, ha, {"Category": [C("OpenRequests", "complaint_type")], "Y": [M("Current Backlog")]},
             title="Current backlog: top complaint types", sort=(M("Current Backlog"), True),
             top_n=(C("OpenRequests", "complaint_type"), M("Current Backlog"), 8), objects=dict(datalabels))
    p.visual("clusteredColumnChart", x2, yb, w2, hb, {"Category": [C("OpenRequests", "incident_zip")], "Y": [M("Current Backlog")]},
             title="Current backlog by ZIP code", sort=(M("Current Backlog"), True), objects={**datalabels, **orange})
    pages.append(p)

    # 4 ---------------------------------------------------------------- Data Quality Monitoring
    p = Page("Data Quality Monitoring", "Data Quality Monitoring",
             "15 rules (config/validation_rules.yaml). Pass rates are run-level with explicit denominators; "
             "click a rule or agency to filter the issue detail table.")
    p.slicers()
    p.cards(["Record-Level DQ Pass Rate", "Request-Level DQ Pass Rate", "DQ Issues", "Pending Manual Review"])
    (ya, ha), (yb, hb) = rows(2)
    (x1, w1), (x2, w2), (x3, w3) = cols(1, 1, 1)
    p.visual("clusteredBarChart", x1, ya, w1, ha, {"Category": [C("DQIssues", "rule_name")], "Series": [C("DQIssues", "severity")],
                                                  "Y": [M("DQ Issues")]},
             title="Issues by rule and severity", sort=(M("DQ Issues"), True), objects=dict(legend_top))
    p.visual("clusteredBarChart", x2, ya, w2, ha, {"Category": [C("Agency", "agency_code")], "Y": [M("Published Requests With Issues %")]},
             title="% of published requests with issues, by agency", sort=(M("Published Requests With Issues %"), True),
             objects=dict(datalabels))
    p.visual("clusteredBarChart", x3, ya, w3, ha, {"Category": [C("MissingValues", "column")], "Y": [C("MissingValues", "missing_pct", 0)]},
             title="Missing values % by field", sort=(C("MissingValues", "missing_pct", 0), True), objects=dict(orange))
    (x1, w1), (x2, w2) = cols(1, 2)
    p.visual("lineChart", x1, yb, w1, hb, {"Category": [C("DQIssues", "created_month")], "Series": [C("DQIssues", "rule_id")],
                                          "Y": [M("DQ Issues")]},
             title="Issues by month request was created", sort=(C("DQIssues", "created_month"), False), objects=dict(legend_top))
    p.visual("tableEx", x2, yb, w2, hb, {"Values": [C("DQIssues", "unique_key"), C("DQIssues", "rule_id"), C("DQIssues", "severity"),
                                                   C("DQIssues", "agency"), C("DQIssues", "status"),
                                                   C("DQIssues", "original_value"), C("DQIssues", "recommended_treatment"),
                                                   C("DQIssues", "resolution_status")]},
             title="Issue detail (affected records)")
    pages.append(p)

    # 5 ---------------------------------------------------------------- Data Quality Impact
    p = Page("Data Quality Impact", "Data Quality Impact",
             "Raw = naive report on the extract; Cleaned = documented treatment policy. Same formulas, only the treatment differs.")
    (ya, ha), (yb, hb) = rows(2, y0=SL_Y)
    (x1, w1), (x2, w2) = cols(1, 1)
    p.visual("tableEx", x1, ya, w1, ha, {"Values": [C("RawVsClean", "metric"), C("RawVsClean", "unit"), C("RawVsClean", "raw_value"),
                                                   C("RawVsClean", "clean_value"), C("RawVsClean", "abs_diff"),
                                                   C("RawVsClean", "pct_diff")]},
             title="Raw vs cleaned KPIs")
    p.visual("clusteredBarChart", x2, ya, w2, ha, {"Category": [C("RawVsCleanAgency", "agency_code")],
                                                  "Y": [C("RawVsCleanAgency", "median_pct_diff", 0), C("RawVsCleanAgency", "avg_pct_diff", 0)]},
             title="% change in median and average resolution after cleaning, by agency",
             sort=(C("RawVsCleanAgency", "median_pct_diff", 0), True), objects={**datalabels, **legend_top})
    (x1, w1), (x2, w2), (x3, w3) = cols(1, 0.8, 1.4)
    p.visual("clusteredBarChart", x1, yb, w1, hb, {"Category": [C("DQRules", "rule_name")], "Y": [C("DQRules", "affected_records", 0)]},
             title="Records affected by rule", sort=(C("DQRules", "affected_records", 0), True), objects=dict(datalabels))
    p.visual("clusteredBarChart", x2, yb, w2, hb, {"Category": [C("CleaningAudit", "action")], "Y": [C("CleaningAudit", "records", 0)]},
             title="Cleaning treatment summary", objects={**datalabels, **orange})
    p.text("Key findings\n"
           "- Every Staten Island headline KPI moved by less than 0.5% after cleaning.\n"
           "- DOB median rises 9.2% (512 h to 560 h): 154 open DOB requests carried closed dates, mostly ~0 h after creation.\n"
           "- 24 negative durations: 3 NYPD records fall in the DST fall-back hour; 18 DOT street-light tickets show a ~24 h offset (cause unconfirmed).\n"
           "- 62 DHS requests closed without a closed date, all Jan 9 - May 5 2025.\n"
           "- 459 cases over 365 days retained; they add ~34 h to the average.\n"
           "\n"
           "Recommendations\n"
           "- Report median and P90 by agency rather than one average.\n"
           "- DOB to review 191 open-with-close-date requests.\n"
           "- Request offset-aware timestamps and documented deadlines from the publisher.",
           x3, yb, w3, hb, size=9)
    pages.append(p)

    cfg = {"version": "5.59", "themeCollection": {"customTheme": {"name": "Ops311Theme.json", "version": "5.59", "type": 1}},
           "activeSectionIndex": 0, "objects": {"outspacePane": [{"properties": {"expanded": lit(False)}}]}}
    return {"config": json.dumps(cfg), "layoutOptimization": 0,
            "resourcePackages": [{"resourcePackage": {"name": "RegisteredResources", "type": 1, "disabled": False,
                                                      "items": [{"type": 202, "path": "Ops311Theme.json", "name": "Ops311Theme.json"}]}}],
            "sections": [pg.section(i) for i, pg in enumerate(pages)]}


def main():
    sm, rp = OUT / f"{NAME}.SemanticModel", OUT / f"{NAME}.Report"
    for d in (sm, rp):
        if d.exists():
            shutil.rmtree(d)
    sm.mkdir(parents=True)
    (rp / "StaticResources" / "RegisteredResources").mkdir(parents=True)
    (OUT / f"{NAME}.pbip").write_text(json.dumps({"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                                  "settings": {"enableAutoRecovery": True}}, indent=2))
    (sm / "definition.pbism").write_text(json.dumps({"version": "1.0", "settings": {}}, indent=2))
    (sm / "model.bim").write_text(json.dumps(build_model(), indent=2))
    (rp / "definition.pbir").write_text(json.dumps({"version": "1.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}, "byConnection": None}}, indent=2))
    (rp / "report.json").write_text(json.dumps(build_report(), indent=2))
    theme = json.loads((OUT / "theme.json").read_text())
    (rp / "StaticResources" / "RegisteredResources" / "Ops311Theme.json").write_text(json.dumps(theme, indent=2))
    print("PBIP written:", OUT / f"{NAME}.pbip")


if __name__ == "__main__":
    main()
