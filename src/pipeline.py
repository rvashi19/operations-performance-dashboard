"""Pipeline entry point.

    python -m src.pipeline --full-refresh       extract whole window, load, validate, clean, publish
    python -m src.pipeline --incremental        extract records updated since last checkpoint
    python -m src.pipeline --validate-only      re-validate staging; analytics untouched
    python -m src.pipeline --generate-reports   rebuild views, CSV exports and markdown reports
"""
import argparse
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

from src import config
from src.database import loader
from src.database.db import build_views, get_engine, init_db
from src.ingestion.socrata_client import SocrataClient, read_raw_file
from src.transformation.cleaning import clean
from src.transformation.staging import to_staging
from src.validation.framework import Validator, summarize

log = logging.getLogger("pipeline")


def _client(s):
    e = s["extraction"]
    return SocrataClient(s["source"]["base_url"], s["source"]["dataset_id"], e["page_size"], e["timeout_seconds"],
                         e["max_retries"], e["backoff_seconds"], os.getenv("SOCRATA_APP_TOKEN") or None)


def validate_and_publish(conn, inspected: pd.DataFrame, run_id, now, settings, rules, publish=True) -> dict:
    issues = Validator(rules, now).run(inspected)
    loader.write_rules(conn, rules)
    loader.write_issues(conn, issues, run_id, now)
    summary = summarize(inspected, issues)
    log.info("validation %s", " ".join(f"{k}={v}" for k, v in summary.items()))
    if not publish:
        return {**summary, "loaded": 0, "rejected": 0}
    cleaned, quarantine, audit = clean(inspected, issues, rules, settings)
    if cleaned.empty:
        # Never publish an empty fact table: it would show zero-valued operational metrics.
        raise RuntimeError("cleaning produced 0 publishable records; refusing to overwrite analytics layer")
    loaded = loader.load_analytics(conn, cleaned, quarantine, audit, run_id, now)
    return {**summary, "loaded": loaded, "rejected": len(inspected) - loaded}


def run(mode: str, engine=None, client=None, raw_file=None) -> str:
    settings, rules = config.settings(), config.validation_rules()
    src = settings["source"]
    window = (src["start_date"], src["end_date"])
    engine = engine or get_engine()
    init_db(engine)
    run_id, started = str(uuid.uuid4()), datetime.now().astimezone()
    with engine.begin() as conn:
        loader.start_run(conn, run_id, mode, started, window)
    log.info("run_id=%s mode=%s started", run_id, mode)
    metrics = {}
    try:
        if mode == "generate-reports":
            from src.reporting.reports import generate_all
            build_views(engine)
            generate_all(engine)
        elif mode == "validate-only":
            with engine.begin() as conn:
                inspected = loader.read_staging(conn, *window)
                if inspected.empty:
                    raise RuntimeError("staging is empty; run --full-refresh first")
                m = validate_and_publish(conn, inspected, run_id, started, settings, rules, publish=False)
            metrics = {"records_extracted": 0, "records_loaded": 0, "records_rejected": 0,
                       "issues_detected": m["total_issues"]}
        else:
            client = client or _client(settings)
            since = None
            if mode == "incremental":
                with engine.connect() as conn:
                    cp = loader.last_checkpoint(conn)
                if cp is None:
                    raise RuntimeError("no successful previous run; use --full-refresh first")
                since = (cp - timedelta(days=settings["extraction"]["incremental_lookback_days"])) \
                    .astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
            where = client.build_where(*window, src["filters"], since)
            out = raw_file or config.ROOT / "data" / "raw" / f"nyc311_{mode}_{started:%Y%m%dT%H%M%S}.jsonl.gz"
            ext = client.extract_to_file(where, src["columns"], out)
            batch = to_staging(read_raw_file(out))
            log.info("extracted rows=%s file=%s", len(batch), out)
            if mode == "full-refresh" and batch.empty:
                raise RuntimeError("full refresh returned 0 records; existing data left untouched")
            # One transaction: raw + staging + issues + analytics either all commit or all roll back.
            with engine.begin() as conn:
                loader.load_raw_and_staging(conn, batch, run_id, ext["extracted_at"])
                stored = loader.read_staging(conn, *window)
                inspected = pd.concat([stored[~stored["record_hash"].isin(batch["record_hash"])],
                                       batch.drop(columns="payload")], ignore_index=True)
                m = validate_and_publish(conn, inspected, run_id, started, settings, rules)
            cp = batch["source_updated_at"].max() if not batch.empty else None
            metrics = {"records_extracted": len(batch), "records_loaded": m["loaded"],
                       "records_rejected": m["rejected"], "issues_detected": m["total_issues"],
                       "raw_file": str(out), "checkpoint_updated_at": None if pd.isna(cp) else cp.to_pydatetime()}
            if mode == "incremental" and metrics["checkpoint_updated_at"] is None:
                with engine.connect() as conn:  # nothing changed: carry the previous checkpoint forward
                    metrics["checkpoint_updated_at"] = loader.last_checkpoint(conn)
            build_views(engine)
        with engine.begin() as conn:
            loader.finish_run(conn, run_id, "succeeded", datetime.now().astimezone(), **metrics)
        log.info("run_id=%s succeeded %s", run_id, metrics)
        return run_id
    except Exception as exc:
        log.exception("run_id=%s failed", run_id)
        with engine.begin() as conn:
            loader.finish_run(conn, run_id, "failed", datetime.now().astimezone(), error_message=str(exc)[:2000])
        raise


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    for m in ("full-refresh", "incremental", "validate-only", "generate-reports"):
        g.add_argument(f"--{m}", dest="mode", action="store_const", const=m)
    args = p.parse_args(argv)
    config.setup_logging()
    try:
        run(args.mode)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
