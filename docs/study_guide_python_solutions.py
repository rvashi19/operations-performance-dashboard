"""Runnable solutions to the Python exercises in docs/interview_study_guide.md (section 18).
Run from the repo root:  python docs/study_guide_python_solutions.py
All data here is synthetic and tiny so each answer can be checked by hand.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402

from src import config  # noqa: E402
from src.analytics.kpis import monthly_rolling_average  # noqa: E402
from src.transformation.cleaning import status_group  # noqa: E402
from src.transformation.staging import to_staging  # noqa: E402
from src.validation.framework import CHECKS, Validator, summarize  # noqa: E402

rules = config.validation_rules()


def rec(key, created="2025-03-01T10:00:00", closed="2025-03-02T10:00:00", status="Closed", **kw):
    r = {"unique_key": key, "created_date": created, "closed_date": closed, "status": status, "agency": "DSNY",
         "complaint_type": "Dirty Condition", "incident_zip": "10301", "latitude": "40.6", "longitude": "-74.1",
         ":updated_at": "2025-03-03T00:00:00Z"}
    r.update(kw)
    return {k: v for k, v in r.items() if v is not None}


# P1 status groups
s = pd.Series(["Closed", "Open", "In Progress", "Cancel", "Teleported"])
print("P1", status_group(s, rules["reference"]).value_counts().to_dict())


# P2 a new check: ZIP present but not 5 digits (raw text), registered like the built-ins
def check_zip_format(df, rule, ref, now):
    raw = df["incident_zip"]
    return [(raw.notna() & ~raw.str.fullmatch(r"\d{5}"), "incident_zip", raw)]


CHECKS["zip_format"] = check_zip_format
df = pd.DataFrame({"incident_zip": pd.Series(["10301", "1030", None, "ABCDE"], dtype="string")})
mask = check_zip_format(df, {}, {}, None)[0][0]
print("P2", mask.tolist())

# P3 record-level vs request-level rates
bad = rec("9", closed="2025-02-01T00:00:00")
d = to_staging([bad, bad, rec("10"), rec(None)])
iss = Validator(rules, pd.Timestamp("2026-01-01")).run(d)
sm = summarize(d, iss)
print("P3", {k: sm[k] for k in ("records_inspected", "records_affected", "requests_inspected", "requests_affected")})

# P4 keep the latest version per key
v = pd.DataFrame({"unique_key": ["1", "1", "2"], "status": ["Open", "Closed", "Open"],
                  "updated": pd.to_datetime(["2025-03-01", "2025-03-05", "2025-03-02"])})
latest = v.sort_values("updated").drop_duplicates("unique_key", keep="last").sort_values("unique_key")
print("P4", latest[["unique_key", "status"]].values.tolist())

# P5 median and P90 (pandas linear interpolation == PostgreSQL percentile_cont == DAX PERCENTILE.INC)
h = pd.Series([1, 2, 3, 4, 100])
print("P5", h.mean(), h.median(), h.quantile(0.9))

# P6 exact calendar-month rolling average with an empty month
dates = pd.Series(pd.to_datetime(["2025-01-10"] * 4 + ["2025-03-10"] * 2))
print("P6", monthly_rolling_average(dates, 3)["rolling_3m_avg"].round(2).tolist())

# P7 open requests without a closed date must not be flagged by DQ005
d7 = to_staging([rec("1", status="Open", closed=None)])
print("P7", Validator(rules, pd.Timestamp("2026-01-01")).run(d7).empty)

# P8 DST ambiguity in America/New_York
ts = pd.Series(pd.to_datetime(["2025-11-02 01:30", "2025-11-02 03:00", "2025-03-09 02:30"]))
loc = ts.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
print("P8", loc.isna().tolist())

# P9 retry waits with exponential backoff (backoff * 2 ** (attempt - 1)) for 4 retries
print("P9", [2 * 2 ** (a - 1) for a in range(1, 5)])


# P10 reconcile two KPI dictionaries within a tolerance
def reconcile(a: dict, b: dict, tol=0.01):
    return {k: (a.get(k), b.get(k)) for k in a.keys() | b.keys()
            if a.get(k) is None or b.get(k) is None or abs(a[k] - b[k]) > tol}


print("P10", reconcile({"median": 15.297, "total": 134348}, {"median": 15.30, "total": 134347}))
