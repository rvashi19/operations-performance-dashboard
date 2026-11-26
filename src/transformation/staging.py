"""Raw API records -> typed staging DataFrame.

Only *safe* normalisation happens here (trim whitespace, empty string -> NULL, upper-case codes,
ISO timestamp parsing). Unparseable timestamps become NULL in the typed column while the original
text is preserved in the *_raw column so the validation layer can flag them.
"""
import hashlib
import json

import pandas as pd

TS_FIELDS = {"created_date": "created_at", "closed_date": "closed_at", "due_date": "due_at",
             "resolution_action_updated_date": "resolution_updated_at"}
RAW_TS_COL = {"created_date": "created_date_raw", "closed_date": "closed_date_raw",
              "due_date": "due_date_raw", "resolution_action_updated_date": "resolution_updated_raw"}
TEXT_FIELDS = {"unique_key": "unique_key", "agency": "agency", "agency_name": "agency_name",
               "complaint_type": "complaint_type", "descriptor": "descriptor", "status": "status",
               "resolution_description": "resolution_description", "borough": "borough",
               "incident_zip": "incident_zip", "community_board": "community_board", "city": "city",
               "open_data_channel_type": "channel", "location_type": "location_type"}

STAGING_COLUMNS = ["record_hash", "unique_key", "created_at", "closed_at", "due_at", "resolution_updated_at",
                   "agency", "agency_name", "complaint_type", "descriptor", "status", "resolution_description",
                   "borough", "incident_zip", "community_board", "city", "latitude", "longitude", "channel",
                   "location_type", "source_updated_at", "created_date_raw", "closed_date_raw", "due_date_raw",
                   "resolution_updated_raw"]


def record_hash(rec: dict) -> str:
    """Hash of business content. Socrata's system field :updated_at is excluded so an untouched
    record re-extracted later gets the same hash (and is not stored twice)."""
    body = {k: v for k, v in rec.items() if not k.startswith(":")}
    return hashlib.md5(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def parse_ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="ISO8601", errors="coerce")


def _clean_text(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip()
    return s.mask(s == "", pd.NA)


def to_staging(records: list[dict]) -> pd.DataFrame:
    """Returns one row per input record (duplicates preserved) plus a `payload` JSON column."""
    if not records:
        return pd.DataFrame(columns=STAGING_COLUMNS + ["payload"])
    df = pd.DataFrame.from_records(records)
    out = pd.DataFrame(index=df.index)
    out["record_hash"] = [record_hash(r) for r in records]
    out["payload"] = [json.dumps(r, ensure_ascii=False) for r in records]
    for src, dst in TEXT_FIELDS.items():
        out[dst] = _clean_text(df[src]) if src in df else pd.Series(pd.NA, index=df.index, dtype="string")
    for src, dst in TS_FIELDS.items():
        raw = _clean_text(df[src]) if src in df else pd.Series(pd.NA, index=df.index, dtype="string")
        out[RAW_TS_COL[src]] = raw
        out[dst] = parse_ts(raw)
    for c in ("latitude", "longitude"):
        out[c] = pd.to_numeric(df[c], errors="coerce") if c in df else pd.NA
    out["source_updated_at"] = (pd.to_datetime(df[":updated_at"], errors="coerce", utc=True)
                                if ":updated_at" in df else pd.NaT)
    for c in ("agency", "borough"):
        out[c] = out[c].str.upper()
    out["incident_zip"] = out["incident_zip"].str.extract(r"^(\d{5})", expand=False).astype("string")
    return out[STAGING_COLUMNS + ["payload"]]
