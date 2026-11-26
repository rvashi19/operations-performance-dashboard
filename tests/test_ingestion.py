import gzip
import json

import pytest

from src.ingestion.socrata_client import ExtractionError, SocrataClient, read_raw_file
from tests.conftest import FakeResponse, FakeSession, rec


def client(session, page_size=2):
    return SocrataClient("https://example.test/resource", "abcd-1234", page_size=page_size, timeout=5,
                         max_retries=3, backoff=0, session=session)


def test_pagination_fetches_all_pages_in_order(tmp_path):
    records = [rec(key=str(i)) for i in range(5)]
    s = FakeSession(records)
    out = tmp_path / "raw.jsonl.gz"
    result = client(s).extract_to_file("x", ["unique_key"], out)
    assert result["rows"] == 5
    offsets = [c["$offset"] for c in s.calls if "$offset" in c]
    assert offsets == [0, 2, 4]          # stops after the short last page
    assert all(c["$order"] == "unique_key" for c in s.calls if "$order" in c)
    assert [r["unique_key"] for r in read_raw_file(out)] == [str(i) for i in range(5)]


def test_exact_multiple_of_page_size_terminates(tmp_path):
    s = FakeSession([rec(key=str(i)) for i in range(4)])
    assert client(s).extract_to_file("x", ["unique_key"], tmp_path / "r.gz")["rows"] == 4


def test_retries_transient_errors_then_succeeds(tmp_path):
    s = FakeSession([rec()], fail_first=2, fail_status=503)
    assert client(s).extract_to_file("x", ["unique_key"], tmp_path / "r.gz")["rows"] == 1


def test_gives_up_after_max_retries_and_keeps_previous_file(tmp_path):
    out = tmp_path / "r.gz"
    with gzip.open(out, "wt") as f:
        f.write(json.dumps(rec(key="previous")) + "\n")
    with pytest.raises(ExtractionError):
        client(FakeSession([rec()], fail_first=10)).extract_to_file("x", ["unique_key"], out)
    assert read_raw_file(out)[0]["unique_key"] == "previous"   # valid data not overwritten
    assert not (tmp_path / "r.gz.part").exists()


def test_client_error_is_not_retried():
    s = FakeSession([], fail_first=1, fail_status=400)
    with pytest.raises(ExtractionError, match="rejected"):
        client(s).count("x")
    assert len(s.calls) == 1


def test_row_count_mismatch_fails(tmp_path):
    class Short(FakeSession):
        def get(self, url, params=None, timeout=None):
            if params["$select"].startswith("count"):
                return FakeResponse(200, [{"n": "10"}])
            return super().get(url, params, timeout)
    with pytest.raises(ExtractionError, match="mismatch"):
        client(Short([rec()])).extract_to_file("x", ["unique_key"], tmp_path / "r.gz")


def test_non_list_payload_is_rejected():
    class Bad(FakeSession):
        def get(self, url, params=None, timeout=None):
            return FakeResponse(200, {"message": "oops"})
    with pytest.raises(ExtractionError):
        client(Bad([])).count("x")


def test_where_clause_contains_window_filters_and_checkpoint():
    w = SocrataClient.build_where("2025-01-01T00:00:00", "2026-01-01T00:00:00", {"borough": "STATEN ISLAND"},
                                  "2025-06-01T00:00:00")
    # half-open window: nothing at 23:59:59.9995 is lost and nothing at the next midnight is double counted
    assert "created_date >= '2025-01-01T00:00:00' AND created_date < '2026-01-01T00:00:00'" in w
    assert "borough='STATEN ISLAND'" in w and ":updated_at > '2025-06-01T00:00:00'" in w
