"""Shared fixtures. All records here are synthetic and used only in tests."""
import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src import config
from src.transformation.staging import to_staging


def rec(key="1", created="2025-03-01T10:00:00.000", closed="2025-03-02T10:00:00.000", status="Closed",
        agency="DSNY", complaint="Dirty Condition", zip_="10301", lat="40.6", lon="-74.1", **extra):
    r = {"unique_key": key, "created_date": created, "closed_date": closed, "status": status, "agency": agency,
         "agency_name": "Department of Sanitation", "complaint_type": complaint, "descriptor": "Trash",
         "borough": "STATEN ISLAND", "incident_zip": zip_, "latitude": lat, "longitude": lon,
         "community_board": "01 STATEN ISLAND", "open_data_channel_type": "ONLINE",
         ":updated_at": "2025-03-03T00:00:00.000Z"}
    r.update(extra)
    return {k: v for k, v in r.items() if v is not None}


@pytest.fixture
def rules():
    return config.validation_rules()


@pytest.fixture
def settings():
    return config.settings()


@pytest.fixture
def now():
    return datetime(2026, 1, 15)


@pytest.fixture
def make_df():
    return lambda records: to_staging(records)


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload, self.text = status, payload, str(payload)[:100]

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Serves count(*) and paged data from an in-memory list; can inject failures."""

    def __init__(self, records, fail_first=0, fail_status=503):
        self.records, self.fail_first, self.fail_status, self.calls = records, fail_first, fail_status, []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        if self.fail_first > 0:
            self.fail_first -= 1
            return FakeResponse(self.fail_status, {"error": True})
        if params["$select"].startswith("count"):
            return FakeResponse(200, [{"n": str(len(self.records))}])
        off, lim = int(params["$offset"]), int(params["$limit"])
        return FakeResponse(200, self.records[off:off + lim])


@pytest.fixture(scope="session")
def test_engine():
    """Engine for a dedicated *_test database on the configured server; skips if unreachable."""
    url = make_url(os.getenv("TEST_DATABASE_URL") or config.database_url())
    test_db = url.database if url.database.endswith("_test") else url.database + "_test"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:d"), {"d": test_db}).scalar():
                c.execute(text(f'CREATE DATABASE "{test_db}"'))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available for integration tests: {exc}")
    eng = create_engine(url.set(database=test_db))
    yield eng
    eng.dispose()


@pytest.fixture
def clean_db(test_engine):
    with test_engine.begin() as c:
        c.exec_driver_sql("DROP SCHEMA IF EXISTS analytics, staging, raw, ops CASCADE")
    return test_engine
