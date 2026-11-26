import pandas as pd
import pytest

from src.analytics.kpis import aging_buckets, backlog_at, clean_kpis, naive_kpis
from src.transformation.cleaning import clean
from src.validation.framework import Validator
from tests.conftest import rec


@pytest.fixture
def cleaned(rules, settings, now, make_df):
    def _run(records):
        df = make_df(records)
        issues = Validator(rules, now).run(df)
        return clean(df, issues, rules, settings)
    return _run


def test_resolution_time_calculation(cleaned):
    out, _, _ = cleaned([rec(created="2025-03-01T10:00:00", closed="2025-03-01T16:30:00")])
    assert out["resolution_hours"].iat[0] == pytest.approx(6.5)
    assert out["within_analytical_target"].iat[0] == True  # noqa: E712


def test_negative_duration_excluded_from_resolution_but_counted(cleaned):
    out, q, audit = cleaned([rec(closed="2025-02-01T00:00:00"), rec(key="2")])
    bad = out[out["unique_key"] == "1"].iloc[0]
    assert len(out) == 2 and q.empty
    assert not bad["include_in_resolution_metrics"] and pd.isna(bad["resolution_hours"])
    assert "excluded_from_resolution" in set(audit["action"])


def test_open_request_retained_with_null_duration(cleaned):
    out, _, _ = cleaned([rec(status="Open", closed=None)])
    assert out["status_group"].iat[0] == "Open" and pd.isna(out["resolution_hours"].iat[0])


def test_open_with_closed_date_escalated_and_counted_open(cleaned):
    out, _, audit = cleaned([rec(status="Pending")])
    r = out.iloc[0]
    assert r["status_group"] == "Open" and r["needs_manual_review"] and not r["include_in_resolution_metrics"]
    assert "escalated" in set(audit["action"])


def test_quarantine_missing_created_date(cleaned):
    out, q, audit = cleaned([rec(created=None), rec(key="2")])
    assert list(out["unique_key"]) == ["2"] and list(q["unique_key"]) == ["1"]
    assert "quarantined" in set(audit["action"])


def test_deduplication_keeps_latest_version(cleaned):
    old = rec(status="Open", closed=None, **{":updated_at": "2025-03-01T00:00:00Z"})
    new = rec(**{":updated_at": "2025-03-05T00:00:00Z"})
    out, _, audit = cleaned([old, new, new])
    assert len(out) == 1 and out["status"].iat[0] == "Closed"
    assert (audit["action"] == "deduplicated_dropped").sum() == 2


def test_missing_agency_normalized_to_unknown(cleaned):
    out, _, audit = cleaned([rec(agency=None)])
    assert out["agency"].iat[0] == "UNKNOWN" and out["needs_manual_review"].iat[0]
    assert "normalized" in set(audit["action"])


def test_extreme_duration_retained(cleaned):
    out, _, _ = cleaned([rec(created="2025-01-01T00:00:00", closed="2026-01-10T00:00:00")])
    assert out["include_in_resolution_metrics"].iat[0] and out["dq_issue_count"].iat[0] == 1


def test_kpi_accuracy(cleaned, settings):
    records = [rec(key="1", created="2025-03-01T00:00:00", closed="2025-03-01T02:00:00"),
               rec(key="2", created="2025-03-01T00:00:00", closed="2025-03-01T04:00:00"),
               rec(key="3", created="2025-03-01T00:00:00", closed="2025-03-01T12:00:00"),
               rec(key="4", status="Open", closed=None),
               rec(key="5", closed="2025-02-01T00:00:00")]      # negative -> excluded from durations
    out, _, _ = cleaned(records)
    k = clean_kpis(out)
    assert k["total_requests"] == 5 and k["closed_requests"] == 4 and k["open_requests"] == 1
    assert k["resolution_rate"] == pytest.approx(0.8)
    assert k["avg_resolution_hours"] == pytest.approx(6.0)
    assert k["median_resolution_hours"] == pytest.approx(4.0)
    assert k["resolution_sample"] == 3


def test_naive_kpis_include_bad_durations(make_df):
    stg = make_df([rec(key="1", created="2025-03-01T00:00:00", closed="2025-03-01T10:00:00"),
                   rec(key="2", created="2025-03-02T00:00:00", closed="2025-03-01T00:00:00")])
    assert naive_kpis(stg, 7)["avg_resolution_hours"] == pytest.approx(-7.0)


def test_backlog_and_aging(cleaned, settings):
    out, _, _ = cleaned([rec(key="1", created="2025-03-01T00:00:00", closed="2025-03-10T00:00:00"),
                         rec(key="2", created="2025-03-01T00:00:00", status="Open", closed=None),
                         rec(key="3", created="2025-03-01T00:00:00", closed=None)])   # closed, no date: excluded
    assert backlog_at(out, pd.Timestamp("2025-03-05")) == 2
    assert backlog_at(out, pd.Timestamp("2025-03-20")) == 1
    buckets = aging_buckets(out, pd.Timestamp("2025-03-12"), settings["analytics"]["aging_buckets"])
    assert buckets["8-14"] == 1 and buckets.sum() == 1
