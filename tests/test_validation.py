import pandas as pd
import pytest

from src.transformation.staging import STAGING_COLUMNS, record_hash
from src.validation.framework import ISSUE_COLUMNS, Validator, summarize
from tests.conftest import rec


def run(rules, now, make_df, records):
    df = make_df(records)
    return df, Validator(rules, now).run(df)


def rule_ids(issues, key=None):
    sel = issues if key is None else issues[issues["unique_key"] == key]
    return set(sel["rule_id"])


def test_staging_schema(make_df):
    df = make_df([rec()])
    assert list(df.columns) == STAGING_COLUMNS + ["payload"]
    assert str(df["created_at"].dtype).startswith("datetime64")
    assert df["agency"].iat[0] == "DSNY"


def test_clean_record_has_no_issues(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec()])
    assert issues.empty and list(issues.columns) == ISSUE_COLUMNS


def test_open_request_without_closed_date_is_valid(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(status="Open", closed=None), rec(key="2", status="In Progress", closed=None)])
    assert issues.empty


def test_closed_without_closed_date_flagged(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(closed=None)])
    assert rule_ids(issues) == {"DQ005"}


def test_closed_before_created_flagged(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(closed="2025-02-28T10:00:00")])
    assert "DQ006" in rule_ids(issues)


def test_invalid_timestamp_flagged_and_original_preserved(rules, now, make_df):
    df, issues = run(rules, now, make_df, [rec(created="not-a-date")])
    row = issues[issues["rule_id"] == "DQ007"].iloc[0]
    assert row["affected_column"] == "created_date" and row["original_value"] == "not-a-date"
    assert df["created_at"].isna().iat[0]


def test_future_timestamp_flagged(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(closed="2027-01-01T00:00:00")])
    assert "DQ008" in rule_ids(issues)


def test_future_due_date_not_flagged(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(due_date="2030-01-01T00:00:00")])
    assert "DQ008" not in rule_ids(issues)


def test_missing_id_created_agency_category(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(key=None), rec(key="2", created=None),
                                          rec(key="3", agency=None), rec(key="4", complaint=None)])
    assert {"DQ003", "DQ004", "DQ010", "DQ009"} <= rule_ids(issues)


def test_open_status_with_closed_date(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(status="Pending")])
    assert rule_ids(issues) == {"DQ011"}


def test_undocumented_status(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(status="Teleported")])
    assert "DQ012" in rule_ids(issues)


def test_extreme_duration(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(created="2025-01-01T00:00:00", closed="2026-01-10T00:00:00")])
    assert "DQ013" in rule_ids(issues)


def test_missing_geography_requires_zip_and_coords_missing(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(zip_=None, lat=None, lon=None), rec(key="2", zip_=None)])
    assert rule_ids(issues, "1") == {"DQ014"} and rule_ids(issues, "2") == set()


def test_exact_duplicates_detected(rules, now, make_df):
    _, issues = run(rules, now, make_df, [rec(), rec()])
    assert rule_ids(issues) == {"DQ002"} and len(issues) == 1


def test_duplicate_id_flags_superseded_version_only(rules, now, make_df):
    old = rec(status="Open", closed=None, **{":updated_at": "2025-03-01T00:00:00Z"})
    new = rec(**{":updated_at": "2025-03-05T00:00:00Z"})
    _, issues = run(rules, now, make_df, [old, new])
    dq1 = issues[issues["rule_id"] == "DQ001"]
    assert len(dq1) == 1 and dq1["record_hash"].iat[0] == record_hash(old)


def test_multiple_issues_counted_once_in_affected_records(rules, now, make_df):
    # missing geography + closed before created + extreme? -> at least two rules on one record
    df, issues = run(rules, now, make_df, [rec(closed="2025-02-01T00:00:00", zip_=None, lat=None, lon=None), rec(key="2")])
    assert len(issues) >= 2
    s = summarize(df, issues)
    assert s["records_with_issues"] == 1 and s["pass_rate"] == 0.5


def test_empty_dataset(rules, now, make_df):
    df, issues = run(rules, now, make_df, [])
    assert df.empty and issues.empty
    assert summarize(df, issues)["pass_rate"] is None


def test_malformed_record_missing_fields_and_bad_numbers(rules, now, make_df):
    df, issues = run(rules, now, make_df, [{"unique_key": "9", "latitude": "abc"}])
    assert pd.isna(df["latitude"].iat[0])
    assert {"DQ004", "DQ009", "DQ010"} <= rule_ids(issues)


def test_unknown_check_in_config_rejected(rules, now):
    bad = {**rules, "rules": rules["rules"] + [{"id": "X", "check": "nope"}]}
    with pytest.raises(ValueError, match="unknown checks"):
        Validator(bad, now)
