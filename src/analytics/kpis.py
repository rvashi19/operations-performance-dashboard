"""KPI calculations shared by reports and tests.

`naive_kpis` reproduces what a report built directly on the raw extract would show;
`clean_kpis` applies the documented definitions to treated data. Both use the same formulas
so differences are attributable to data treatment, not to definitions.
"""
import pandas as pd


def _durations_hours(df, mask):
    return ((df.loc[mask, "closed_at"] - df.loc[mask, "created_at"]).dt.total_seconds() / 3600)


def _summary(total, closed, hours, open_count, within_target, unknown=0):
    return {
        "total_requests": int(total),
        "closed_requests": int(closed),
        "open_requests": int(open_count),
        "unknown_status_requests": int(unknown),
        "resolution_rate": closed / total if total else None,
        "avg_resolution_hours": float(hours.mean()) if len(hours) else None,
        "median_resolution_hours": float(hours.median()) if len(hours) else None,
        "p90_resolution_hours": float(hours.quantile(0.9)) if len(hours) else None,
        "resolution_sample": int(len(hours)),
        "within_target_rate": float(within_target.mean()) if len(within_target) else None,
    }


def naive_kpis(stg: pd.DataFrame, target_days: float) -> dict:
    """Raw view: every extracted row counts; any row with a closed_date contributes a duration."""
    closed = stg["status"].eq("Closed")
    hours = _durations_hours(stg, stg["closed_at"].notna() & stg["created_at"].notna())
    return _summary(len(stg), closed.sum(), hours, (~closed).sum(), hours <= target_days * 24)


def clean_kpis(fact: pd.DataFrame) -> dict:
    closed = fact["status_group"].eq("Closed")
    open_ = fact["status_group"].eq("Open")
    hours = fact.loc[fact["include_in_resolution_metrics"], "resolution_hours"].astype(float)
    within = fact.loc[fact["include_in_resolution_metrics"], "within_analytical_target"].astype(bool)
    return _summary(fact["unique_key"].nunique(), closed.sum(), hours, open_.sum(), within,
                    unknown=(~closed & ~open_).sum())


def backlog_at(fact: pd.DataFrame, as_of: pd.Timestamp) -> int:
    """Requests created on/before as_of and not validly closed by as_of. Closed requests with
    no usable close date are excluded (their open interval is unknown)."""
    created = fact["created_at"] <= as_of
    closed_unknown = fact["status_group"].eq("Closed") & fact["effective_closed_at"].isna()
    unknown_status = fact["status_group"].eq("Unknown")
    still_open = fact["effective_closed_at"].isna() | (fact["effective_closed_at"] > as_of)
    return int((created & still_open & ~closed_unknown & ~unknown_status).sum())


def aging_buckets(fact: pd.DataFrame, as_of: pd.Timestamp, buckets) -> pd.Series:
    open_ = fact[fact["status_group"].eq("Open")]
    age = (as_of - open_["created_at"]).dt.days
    labels = pd.Series(pd.NA, index=open_.index, dtype="string")
    for lo, hi, name in buckets:
        labels[(age >= lo) & (age <= hi)] = name
    return labels.value_counts().reindex([b[2] for b in buckets], fill_value=0)


def monthly_rolling_average(dates: pd.Series, months: int = 3, start=None, end=None) -> pd.DataFrame:
    """Exact calendar-month rolling average of monthly counts.

    Months with no records count as zero (they are not skipped), and a value is only produced once
    `months` complete calendar months of the reporting window are available (earlier months -> NaN).
    `start`/`end` bound the window so a leading or trailing empty month is still a real zero.
    """
    m = dates.dt.to_period("M")
    idx = pd.period_range(start or m.min(), end or m.max(), freq="M")
    counts = m.value_counts().reindex(idx, fill_value=0).sort_index()
    out = pd.DataFrame({"month": idx.to_timestamp(), "requests": counts.values})
    out[f"rolling_{months}m_avg"] = counts.rolling(months, min_periods=months).mean().values
    return out
