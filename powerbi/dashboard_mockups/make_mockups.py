"""Renders static MOCKUPS of the five Power BI pages from the real CSV exports.

These are design mockups drawn with matplotlib, NOT Power BI screenshots.
    python powerbi/dashboard_mockups/make_mockups.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EX, OUT = ROOT / "data" / "exports", Path(__file__).parent
C = ["#1F4E79", "#E07B39", "#5B9BD5", "#70AD47", "#A5A5A5"]
csv = lambda n: pd.read_csv(EX / f"{n}.csv")  # noqa: E731


def page(title, n_rows=3):
    fig = plt.figure(figsize=(16, 9), facecolor="#F4F6F9")
    fig.text(0.01, 0.965, title, fontsize=18, weight="bold", color="#1B1B1B")
    fig.text(0.99, 0.965, "MOCKUP - not a Power BI screenshot", fontsize=10, color="#C62828", ha="right")
    fig.text(0.01, 0.935, "Slicers: Date range | Agency | Complaint type | ZIP | Status | Issue severity",
             fontsize=9, color="#404040")
    return fig, fig.add_gridspec(n_rows, 4, left=0.04, right=0.98, top=0.9, bottom=0.06, hspace=0.55, wspace=0.3)


def cards(fig, gs, items):
    for i, (label, value) in enumerate(items):
        ax = fig.add_subplot(gs[0, i])
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, color="white", ec="#D9D9D9", transform=ax.transAxes))
        ax.text(0.5, 0.58, value, ha="center", fontsize=22, color=C[0], transform=ax.transAxes)
        ax.text(0.5, 0.22, label, ha="center", fontsize=10, color="#404040", transform=ax.transAxes)


def save(fig, name):
    fig.savefig(OUT / name, dpi=80)
    plt.close(fig)


k = csv("kpi_summary").iloc[0]
vol = csv("monthly_volume").query("month < '2026-01-01'")
ag = csv("agency_performance")
cp = csv("complaint_performance")
bk = csv("backlog_monthly")
op = csv("open_requests")
rules = csv("dq_rule_summary")
iss = csv("dq_issues")
rvc = csv("raw_vs_clean")

# Page 1 - Executive overview
fig, gs = page("1. Executive Overview")
cards(fig, gs, [("Total requests", f"{k.total_requests:,}"), ("Resolution rate", f"{k.resolution_rate:.1%}"),
                ("Median / avg resolution (h)", f"{k.median_resolution_hours:.1f} / {k.avg_resolution_hours:.0f}"),
                ("Open at reporting date", f"{k.open_requests:,}")])
ax = fig.add_subplot(gs[1:, :2]); ax.plot(vol.month.str[:7], vol.created_requests, marker="o", color=C[0], label="created")
ax.plot(vol.month.str[:7], vol.closed_requests, marker="o", color=C[1], label="closed"); ax.legend(); ax.set_title("Monthly requests vs closures")
ax.tick_params(axis="x", rotation=45)
ax = fig.add_subplot(gs[1:, 2]); top = ag.head(8)[::-1]; ax.barh(top.agency_code, top.total_requests, color=C[0]); ax.set_title("Requests by agency")
ax = fig.add_subplot(gs[1:, 3]); tc = cp.groupby("complaint_type").total_requests.sum().nlargest(8)[::-1]
ax.barh(tc.index, tc.values, color=C[2]); ax.set_title("Top complaint types"); ax.tick_params(axis="y", labelsize=8)
save(fig, "page1_executive_overview.png")

# Page 2 - Operational performance
fig, gs = page("2. Operational Performance")
cards(fig, gs, [("P90 resolution (h)", f"{k.p90_resolution_hours:.0f}"), ("Within 7-day analytical target", f"{k.within_target_rate:.1%}"),
                ("Resolution sample", f"{k.resolution_sample:,}"), ("Avg / median ratio", f"{k.avg_resolution_hours / k.median_resolution_hours:.1f}x")])
a = ag[ag.total_requests >= 300].sort_values("median_resolution_hours")
ax = fig.add_subplot(gs[1:, :2]); ax.barh(a.agency_code, a.median_resolution_hours / 24, color=C[0], label="median")
ax.scatter(a.avg_resolution_hours / 24, a.agency_code, color=C[1], zorder=3, label="average"); ax.set_xscale("log")
ax.set_title("Resolution days by agency (log)"); ax.legend()
ax = fig.add_subplot(gs[1:, 2:]); ax.barh(a.agency_code, a.within_target_rate * 100, color=[C[3] if v >= .9 else C[1] if v >= .75 else "#C62828" for v in a.within_target_rate])
ax.set_title("% resolved within 7-day analytical target (conditional colours)"); ax.set_xlim(0, 100)
save(fig, "page2_operational_performance.png")

# Page 3 - Backlog & demand
fig, gs = page("3. Backlog and Demand")
buckets = op.aging_bucket.value_counts().reindex(["0-7", "8-14", "15-30", "31-60", "60+"], fill_value=0)
cards(fig, gs, [("Current backlog", f"{len(op):,}"), ("Overdue vs 7-day target", f"{op.overdue_vs_analytical_target.sum():,}"),
                ("Avg backlog age (days)", f"{op.age_days.mean():.0f}"), ("Dec-2025 month-end backlog", f"{bk[bk.month_end == '2025-12-31'].backlog.sum():,}")])
ax = fig.add_subplot(gs[1:, :2]); piv = bk.pivot_table(index="month_end", columns="agency_code", values="backlog").fillna(0)
piv[piv.sum().nlargest(5).index].plot.area(ax=ax, color=C, alpha=.85); ax.set_title("Month-end backlog, top 5 agencies"); ax.tick_params(axis="x", rotation=45)
ax = fig.add_subplot(gs[1:, 2]); ax.bar(buckets.index, buckets.values, color=C[0]); ax.set_title("Backlog aging buckets (days)")
ax = fig.add_subplot(gs[1:, 3]); z = op.groupby("incident_zip").size().nlargest(10)[::-1]; ax.barh(z.index.astype(str), z.values, color=C[2]); ax.set_title("Open requests by ZIP")
save(fig, "page3_backlog_demand.png")

# Page 4 - Data quality monitoring
fig, gs = page("4. Data Quality Monitoring")
inspected = k.total_requests
cards(fig, gs, [("DQ pass rate", f"{1 - iss.unique_key.nunique() / inspected:.2%}"), ("Affected records", f"{iss.unique_key.nunique():,}"),
                ("Total issues", f"{len(iss):,}"), ("Pending manual review", f"{iss[iss.resolution_status == 'pending_manual_review'].unique_key.nunique():,}")])
r = rules[rules.issues > 0]
ax = fig.add_subplot(gs[1:, :2]); ax.barh(r.rule_id + " " + r.rule_name, r.issues, color=C[1]); ax.set_title("Issues by rule")
ax = fig.add_subplot(gs[1:, 2]); a2 = (iss.groupby("agency").unique_key.nunique() / ag.set_index("agency_code").total_requests * 100).dropna().nlargest(8)[::-1]
ax.barh(a2.index, a2.values, color=C[0]); ax.set_title("% records affected by agency")
ax = fig.add_subplot(gs[1:, 3]); m = iss.groupby("created_month").size(); ax.plot(m.index, m.values, marker="o", color=C[0]); ax.set_title("Issues by created month"); ax.tick_params(axis="x", rotation=60)
save(fig, "page4_data_quality_monitoring.png")

# Page 5 - Data quality impact
fig, gs = page("5. Data Quality Impact", n_rows=2)
ax = fig.add_subplot(gs[0, :2]); ax.axis("off")
t = ax.table(cellText=rvc[["metric", "raw_value", "clean_value", "pct_diff"]].round(3).values,
             colLabels=["Metric", "Raw", "Cleaned", "% change"], loc="center"); t.scale(1, 1.4); t.auto_set_font_size(False); t.set_fontsize(9)
ax.set_title("Raw vs cleaned KPIs")
ra = csv("raw_vs_clean_agency").query("avg_abs_diff != 0")
ax = fig.add_subplot(gs[0, 2:]); ax.bar(ra.agency_code, ra.avg_pct_diff, color=C[1]); ax.set_title("% change in average resolution by agency")
ax = fig.add_subplot(gs[1, :2]); au = csv("cleaning_audit_summary"); ax.barh(au.action, au.records, color=C[0]); ax.set_title("Cleaning treatment summary")
ax = fig.add_subplot(gs[1, 2:]); ax.axis("off")
ax.text(0, 0.9, "Key findings (text box, from reports/executive_summary.md)", weight="bold")
for i, line in enumerate(["Headline KPIs change by <0.5% after cleaning", "DOB median resolution +9% after excluding open-with-close-date records",
                          "24 negative durations: DST fall-back (NYPD) and DOT 24h offset", "459 cases >365 days retained; they add ~34 h to the average"]):
    ax.text(0, 0.7 - i * 0.17, "- " + line, fontsize=10)
save(fig, "page5_data_quality_impact.png")
print("mockups written to", OUT)
