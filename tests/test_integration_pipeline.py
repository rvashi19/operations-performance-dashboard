"""Integration tests against a real PostgreSQL *_test database (skipped if unavailable)."""
import pytest
from sqlalchemy import text

from src import pipeline
from src.ingestion.socrata_client import SocrataClient
from tests.conftest import FakeSession, rec

pytestmark = pytest.mark.integration

RECORDS = [rec(key="1"), rec(key="2", status="Open", closed=None), rec(key="3", closed="2025-02-01T00:00:00"),
           rec(key="4", created=None), rec(key="5", status="Pending"), rec(key="6", agency="DOT", zip_=None,
                                                                         lat=None, lon=None)]


def fake_client(records, **kw):
    return SocrataClient("https://example.test/resource", "x", page_size=4, max_retries=2, backoff=0,
                         session=FakeSession(records, **kw))


def counts(engine):
    with engine.connect() as c:
        return {t: c.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in
                ["raw.service_requests", "staging.service_requests", "analytics.fact_service_request",
                 "analytics.quarantine"]}


def test_full_refresh_loads_all_layers(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(RECORDS), raw_file=tmp_path / "r.gz")
    c = counts(clean_db)
    assert c["raw.service_requests"] == 6 and c["staging.service_requests"] == 6
    assert c["analytics.fact_service_request"] == 5 and c["analytics.quarantine"] == 1
    with clean_db.connect() as conn:
        ids = {r[0] for r in conn.execute(text("SELECT DISTINCT rule_id FROM ops.dq_issues"))}
        assert {"DQ004", "DQ006", "DQ011", "DQ014"} <= ids
        kpi = conn.execute(text("SELECT total_requests, closed_requests FROM analytics.v_kpi_summary")).one()
        assert tuple(kpi) == (5, 3)


def test_rerun_is_idempotent(clean_db, tmp_path):
    for _ in range(2):
        pipeline.run("full-refresh", engine=clean_db, client=fake_client(RECORDS), raw_file=tmp_path / "r.gz")
    assert counts(clean_db)["raw.service_requests"] == 6
    assert counts(clean_db)["analytics.fact_service_request"] == 5


def test_updated_record_supersedes_old_version(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(RECORDS), raw_file=tmp_path / "r.gz")
    updated = rec(key="2", closed="2025-03-04T00:00:00", **{":updated_at": "2025-03-09T00:00:00Z"})
    pipeline.run("incremental", engine=clean_db, client=fake_client([updated]), raw_file=tmp_path / "i.gz")
    c = counts(clean_db)
    assert c["raw.service_requests"] == 7          # history kept in raw
    assert c["analytics.fact_service_request"] == 5  # one row per request
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT status FROM analytics.fact_service_request WHERE unique_key='2'")).scalar() == "Closed"


def test_failed_extraction_does_not_touch_existing_data(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(RECORDS), raw_file=tmp_path / "r.gz")
    before = counts(clean_db)
    with pytest.raises(Exception):
        pipeline.run("full-refresh", engine=clean_db, client=fake_client(RECORDS, fail_first=99),
                     raw_file=tmp_path / "r.gz")
    assert counts(clean_db) == before
    with clean_db.connect() as conn:
        last = conn.execute(text("SELECT status, error_message FROM ops.pipeline_runs ORDER BY started_at DESC LIMIT 1")).one()
    assert last[0] == "failed" and last[1]


def test_empty_extract_refused(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(RECORDS), raw_file=tmp_path / "r.gz")
    before = counts(clean_db)
    with pytest.raises(RuntimeError, match="0 records"):
        pipeline.run("full-refresh", engine=clean_db, client=fake_client([]), raw_file=tmp_path / "e.gz")
    assert counts(clean_db) == before


def test_validate_only_does_not_change_analytics(clean_db, tmp_path):
    pipeline.run("full-refresh", engine=clean_db, client=fake_client(RECORDS), raw_file=tmp_path / "r.gz")
    before = counts(clean_db)
    pipeline.run("validate-only", engine=clean_db)
    assert counts(clean_db) == before
