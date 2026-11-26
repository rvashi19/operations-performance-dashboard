"""Regression tests added by the QA review (reports/qa_review.md). Records are synthetic."""
import copy

import pandas as pd
import pytest
from sqlalchemy import text

from src import config, pipeline
from src.analytics.kpis import backlog_at, clean_kpis, monthly_rolling_average
from src.database import loader
from src.ingestion.socrata_client import ExtractionError, SocrataClient
from src.transformation.cleaning import clean
from src.validation.framework import Validator, summarize
from tests.conftest import FakeResponse, FakeSession, rec

BASE = [rec(key="1"), rec(key="2", status="Open", closed=None), rec(key="3", closed="2025-02-01T00:00:00"),
        rec(key="4", created=None), rec(key="5", status="Pending"),
        rec(key="6", agency="DOT", zip_=None, lat=None, lon=None)]


def fake_client(records, **kw):
    return SocrataClient("https://example.test/resource", "x", page_size=4, max_retries=2, backoff=0,
                         session=FakeSession(records, **kw))


def q(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(text(sql), p).all()


def scalar(engine, sql, **p):
    return q(engine, sql, **p)[0][0]


def counts(engine):
    return {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in
            ["raw.service_requests", "staging.current_snapshot", "analytics.fact_service_request", "ops.dq_issues"]}


# ------------------------------------------------------------------------------- unit tests
def test_duplicate_rows_with_multiple_issues(rules, settings, now, make_df):
    bad = rec(key="9", closed="2025-02-01T00:00:00", zip_=None, lat=None, lon=None)
    df = make_df([bad, bad, rec(key="10")])
    issues = Validator(rules, now).run(df)
    assert set(issues["rule_id"]) == {"DQ002", "DQ006", "DQ014"}
    assert not issues.duplicated(["record_hash", "rule_id", "affected_column"]).any()
    s = summarize(df, issues)
    # both copies of the bad record are affected rows; they are one request
    assert (s["records_inspected"], s["records_affected"]) == (3, 2)
    assert (s["requests_inspected"], s["requests_affected"]) == (2, 1)
    out, _, audit = clean(df, issues, rules, settings)
    assert sorted(out["unique_key"]) == ["10", "9"]
    assert (audit["action"] == "deduplicated_dropped").sum() == 1


def test_missing_request_id_excluded_from_request_denominator(rules, settings, now, make_df):
    df = make_df([rec(key=None), rec(key="2")])
    issues = Validator(rules, now).run(df)
    s = summarize(df, issues)
    assert s["records_without_id"] == 1 and s["requests_inspected"] == 1
    assert s["records_affected"] == 1 and s["requests_affected"] == 0
    out, quarantine, _ = clean(df, issues, rules, settings)
    assert list(out["unique_key"]) == ["2"] and len(quarantine) == 1


@pytest.mark.parametrize("status,expect_rule", [("Cancel", False), ("Unspecified", False), ("Teleported", True)])
def test_unknown_statuses_are_not_open(rules, settings, now, make_df, status, expect_rule):
    df = make_df([rec(key="1", status=status, closed=None), rec(key="2", status="Open", closed=None), rec(key="3")])
    issues = Validator(rules, now).run(df)
    assert ("DQ012" in set(issues["rule_id"])) == expect_rule
    out, _, _ = clean(df, issues, rules, settings)
    grp = dict(zip(out["unique_key"], out["status_group"]))
    assert grp == {"1": "Unknown", "2": "Open", "3": "Closed"}
    k = clean_kpis(out)
    assert (k["total_requests"], k["open_requests"], k["closed_requests"], k["unknown_status_requests"]) == (3, 1, 1, 1)
    assert backlog_at(out, pd.Timestamp("2025-12-31")) == 1


def test_dst_ambiguous_and_nonexistent_local_times(rules, now, make_df):
    df = make_df([rec(key="fall", created="2025-11-02T01:30:00", closed="2025-11-02T05:00:00"),
                  rec(key="spring", created="2025-03-09T02:30:00", closed="2025-03-09T05:00:00"),
                  rec(key="normal", created="2025-11-02T03:00:00", closed="2025-11-02T05:00:00")])
    issues = Validator(rules, now).run(df)
    flagged = set(issues.loc[issues["rule_id"] == "DQ015", "unique_key"])
    assert flagged == {"fall", "spring"}


def test_treatment_is_configuration_driven(rules, settings, now, make_df):
    df = make_df([rec(key="1", status="Pending")])          # DQ011 only
    issues = Validator(rules, now).run(df)
    out, _, _ = clean(df, issues, rules, settings)
    assert not out["include_in_resolution_metrics"].iat[0]
    edited = copy.deepcopy(rules)
    for r in edited["rules"]:
        if r["id"] == "DQ011":
            r["excludes_from_resolution"] = False
            r["treatment"] = "retain"
    # status Pending is still Open, so it has no resolution time either way; use a Closed record with DQ006
    df2 = make_df([rec(key="2", closed="2025-02-28T09:00:00")])
    iss2 = Validator(edited, now).run(df2)
    for r in edited["rules"]:
        if r["id"] == "DQ006":
            r["excludes_from_resolution"] = False
    out2, _, _ = clean(df2, iss2, edited, settings)
    assert out2["include_in_resolution_metrics"].iat[0]       # behaviour followed the YAML flag
    s2 = copy.deepcopy(settings)
    s2["analytics"]["unknown_labels"]["agency"] = "NO-AGENCY"
    out3, _, _ = clean(make_df([rec(key="3", agency=None)]), Validator(rules, now).run(make_df([rec(key="3", agency=None)])),
                       rules, s2)
    assert out3["agency"].iat[0] == "NO-AGENCY"


def test_calendar_month_rolling_average_counts_empty_months_as_zero():
    dates = pd.Series(pd.to_datetime(["2025-01-05"] * 3 + ["2025-03-10"] * 6 + ["2025-04-01"] * 3))
    r = monthly_rolling_average(dates, 3).set_index("month")
    assert r.loc["2025-02-01", "requests"] == 0                     # empty month is kept as a zero
    assert pd.isna(r.loc["2025-02-01", "rolling_3m_avg"])            # fewer than 3 months available
    assert r.loc["2025-03-01", "rolling_3m_avg"] == pytest.approx((3 + 0 + 6) / 3)
    assert r.loc["2025-04-01", "rolling_3m_avg"] == pytest.approx((0 + 6 + 3) / 3)
    # trailing empty month inside the window is a real zero, not skipped
    r2 = monthly_rolling_average(dates, 3, end=pd.Period("2025-05", "M")).set_index("month")
    assert r2.loc["2025-05-01", "rolling_3m_avg"] == pytest.approx((6 + 3 + 0) / 3)


def test_malformed_count_and_page_responses():
    class BadCount(FakeSession):
        def get(self, url, params=None, timeout=None):
            return FakeResponse(200, [{"unexpected": "x"}])
    with pytest.raises(ExtractionError, match="malformed count"):
        fake = SocrataClient("https://example.test/resource", "x", max_retries=1, backoff=0, session=BadCount([]))
        fake.count("x")

    class BadPage(FakeSession):
        def get(self, url, params=None, timeout=None):
            if params["$select"].startswith("count"):
                return FakeResponse(200, [{"n": "2"}])
            return FakeResponse(200, ["not-an-object", {"unique_key": "1"}])
    with pytest.raises(ExtractionError, match="non-object"):
        list(SocrataClient("https://example.test/resource", "x", max_retries=1, backoff=0,
                           session=BadPage([])).iter_pages("x", ["unique_key"]))

    class BadJson(FakeSession):
        def get(self, url, params=None, timeout=None):
            return FakeResponse(200, ValueError("truncated JSON"))
    with pytest.raises(ExtractionError):
        SocrataClient("https://example.test/resource", "x", max_retries=2, backoff=0, session=BadJson([])).count("x")


# ------------------------------------------------------------------------------- integration tests
@pytest.mark.integration
def test_full_refresh_drops_records_no_longer_in_source(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(BASE), raw_file=tmp_path / "a.gz")
    assert scalar(clean_db, "SELECT count(*) FROM analytics.fact_service_request WHERE unique_key='1'") == 1
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(BASE[1:]), raw_file=tmp_path / "b.gz")
    assert scalar(clean_db, "SELECT count(*) FROM analytics.fact_service_request WHERE unique_key='1'") == 0
    assert scalar(clean_db, "SELECT count(*) FROM raw.service_requests WHERE unique_key='1'") == 1   # history kept
    assert scalar(clean_db, "SELECT count(*) FROM staging.current_snapshot WHERE unique_key='1'") == 0


@pytest.mark.integration
def test_updated_record_is_history_not_duplicate(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(BASE), raw_file=tmp_path / "a.gz")
    updated = rec(key="2", closed="2025-03-04T00:00:00", **{":updated_at": "2025-03-09T00:00:00Z"})
    run_id = pipeline.run("incremental", engine=clean_db, client=fake_client([updated]), raw_file=tmp_path / "i.gz")
    assert scalar(clean_db, "SELECT count(*) FROM raw.service_requests WHERE unique_key='2'") == 2
    assert scalar(clean_db, "SELECT count(*) FROM ops.dq_issues WHERE run_id=:r AND rule_id='DQ001'", r=run_id) == 0
    assert scalar(clean_db, "SELECT count(*) FROM staging.current_snapshot WHERE unique_key='2'") == 1
    assert scalar(clean_db, "SELECT status FROM analytics.fact_service_request WHERE unique_key='2'") == "Closed"


@pytest.mark.integration
def test_true_duplicate_versions_in_one_extract_are_flagged(clean_db, tmp_path):
    a = rec(key="7", status="Open", closed=None, **{":updated_at": "2025-03-01T00:00:00Z"})
    b = rec(key="7", **{":updated_at": "2025-03-05T00:00:00Z"})
    run_id = pipeline.run("full-refresh", engine=clean_db, client=fake_client([a, b, rec(key="8")]),
                          raw_file=tmp_path / "d.gz")
    assert scalar(clean_db, "SELECT count(*) FROM ops.dq_issues WHERE run_id=:r AND rule_id='DQ001'", r=run_id) == 1
    assert scalar(clean_db, "SELECT count(*) FROM analytics.fact_service_request WHERE unique_key='7'") == 1


@pytest.mark.integration
def test_refresh_checkpoint_and_lookback(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(BASE), raw_file=tmp_path / "a.gz")
    cp = scalar(clean_db, "SELECT checkpoint_updated_at FROM ops.pipeline_runs WHERE mode='full-refresh'")
    assert cp is not None and cp.isoformat().startswith("2025-03-03")
    c = fake_client([])
    pipeline.run("incremental", engine=clean_db, client=c, raw_file=tmp_path / "i.gz")
    where = [p["$where"] for p in c.session.calls if "$where" in p][0]
    assert ":updated_at > '2025-03-01T00:00:00'" in where          # checkpoint minus 2-day overlap
    # empty incremental carries the checkpoint forward instead of losing it
    assert scalar(clean_db, "SELECT checkpoint_updated_at FROM ops.pipeline_runs WHERE mode='incremental'") == cp
    assert counts(clean_db)["analytics.fact_service_request"] == 5


@pytest.mark.integration
def test_switching_scope_resets_snapshot_and_blocks_stale_incremental(clean_db, tmp_path, monkeypatch, settings):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(BASE), raw_file=tmp_path / "a.gz")
    other = copy.deepcopy(settings)
    other["source"]["filters"] = {"borough": "BRONX"}
    other["source"]["start_date"], other["source"]["end_date"] = "2025-03-01T00:00:00", "2025-04-01T00:00:00"
    monkeypatch.setattr(config, "settings", lambda: other)
    c = fake_client([rec(key="b1", borough="BRONX"), rec(key="b2", borough="BRONX")])
    pipeline.run("full-refresh", engine=clean_db, client=c, raw_file=tmp_path / "b.gz")
    where = [p["$where"] for p in c.session.calls if "$where" in p][0]
    assert "borough='BRONX'" in where and "created_date < '2025-04-01T00:00:00'" in where
    keys = {r[0] for r in q(clean_db, "SELECT unique_key FROM analytics.fact_service_request")}
    assert keys == {"b1", "b2"}                                     # Staten Island rows are gone from "now"
    monkeypatch.setattr(config, "settings", lambda: settings)     # back to original scope
    with pytest.raises(RuntimeError, match="configured scope"):
        pipeline.run("incremental", engine=clean_db, client=fake_client([]), raw_file=tmp_path / "c.gz")


@pytest.mark.integration
@pytest.mark.parametrize("target", ["validation", "publication", "views"])
def test_failure_rolls_back_everything(clean_db, tmp_path, monkeypatch, target):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(BASE), raw_file=tmp_path / "a.gz")
    before = counts(clean_db)
    fact_before = q(clean_db, "SELECT unique_key, status FROM analytics.fact_service_request ORDER BY 1")

    def boom(*a, **k):
        raise RuntimeError(f"injected {target} failure")
    if target == "validation":
        monkeypatch.setattr(Validator, "run", boom)
    elif target == "publication":
        monkeypatch.setattr(loader, "load_analytics", boom)
    else:
        monkeypatch.setattr(pipeline, "build_views", boom)
    changed = [rec(key="1", status="Open", closed=None, **{":updated_at": "2025-03-09T00:00:00Z"})] + BASE[1:]
    with pytest.raises(RuntimeError, match="injected"):
        pipeline.run("full-refresh", engine=clean_db, client=fake_client(changed), raw_file=tmp_path / "b.gz")
    assert counts(clean_db) == before
    assert q(clean_db, "SELECT unique_key, status FROM analytics.fact_service_request ORDER BY 1") == fact_before
    status, err, cp = q(clean_db, "SELECT status, error_message, checkpoint_updated_at FROM ops.pipeline_runs "
                                  "ORDER BY started_at DESC LIMIT 1")[0]
    assert status == "failed" and "injected" in err and cp is None
    # the latest successful load is still the one the views describe
    assert scalar(clean_db, "SELECT count(*) FROM ops.pipeline_runs WHERE status='succeeded'") == 1


@pytest.mark.integration
def test_sql_python_kpi_and_dq_reconciliation(clean_db, tmp_path):
    recs = BASE + [rec(key="11", created="2025-01-10T08:00:00", closed="2025-01-10T09:30:00"),
                   rec(key="12", created="2025-05-02T08:00:00", closed="2025-05-20T08:00:00"),
                   rec(key="13", status="Cancel", closed=None)]
    run_id = pipeline.run("full-refresh", engine=clean_db, client=fake_client(recs), raw_file=tmp_path / "a.gz")
    with clean_db.connect() as c:
        fact = pd.read_sql("SELECT * FROM analytics.fact_service_request", c)
        sql = pd.read_sql("SELECT * FROM analytics.v_kpi_summary", c).iloc[0]
        roll = pd.read_sql("SELECT * FROM analytics.v_monthly_volume_rolling ORDER BY month", c)
        dq = pd.read_sql("SELECT * FROM ops.v_dq_run_summary", c).iloc[0]
        snap = loader.read_snapshot(c)
        iss = pd.read_sql(text("SELECT * FROM ops.dq_issues WHERE run_id=:r"), c, params={"r": run_id})
    py = clean_kpis(fact)
    for k in ("total_requests", "closed_requests", "open_requests", "unknown_status_requests"):
        assert py[k] == sql[k], k
    assert py["median_resolution_hours"] == pytest.approx(float(sql["median_resolution_hours"]), abs=0.006)
    assert py["p90_resolution_hours"] == pytest.approx(float(sql["p90_resolution_hours"]), abs=0.006)
    pr = monthly_rolling_average(fact["created_at"], 3, start=pd.Period("2025-01", "M"), end=pd.Period("2025-12", "M"))
    pd.testing.assert_series_equal(pr["rolling_3m_avg"].round(2).reset_index(drop=True),
                                   roll["created_rolling_3m_avg"].astype(float).reset_index(drop=True),
                                   check_names=False)
    s = summarize(snap, iss)
    assert (s["records_inspected"], s["records_affected"]) == (dq["records_inspected"], dq["records_affected"])
    assert (s["requests_inspected"], s["requests_affected"]) == (dq["requests_inspected"], dq["requests_affected"])
    assert dq["requests_inspected"] == 9 and dq["records_inspected"] == 9   # every synthetic row has an ID
