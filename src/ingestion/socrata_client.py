"""Extract NYC 311 records through the Socrata SODA API with pagination, retries and timeouts.

Raw pages are written to a temporary file and only renamed into place after the full extract
succeeds and the record count matches the API's own count, so a failed run never replaces a
previously valid raw file.
"""
import gzip
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    pass


class SocrataClient:
    def __init__(self, base_url: str, dataset_id: str, page_size: int = 50000, timeout: int = 120,
                 max_retries: int = 5, backoff: float = 2.0, app_token: str | None = None,
                 session: requests.Session | None = None):
        self.url = f"{base_url.rstrip('/')}/{dataset_id}.json"
        self.page_size, self.timeout, self.max_retries, self.backoff = page_size, timeout, max_retries, backoff
        self.session = session or requests.Session()
        if app_token:
            self.session.headers["X-App-Token"] = app_token

    def _get(self, params: dict) -> list:
        """GET with retry on network errors, 429 and 5xx. 4xx other than 429 fail immediately."""
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(self.url, params=params, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"retryable status {resp.status_code}", response=resp)
                if resp.status_code >= 400:
                    raise ExtractionError(f"API rejected request ({resp.status_code}): {resp.text[:300]}")
                data = resp.json()
                if not isinstance(data, list):
                    raise ExtractionError(f"unexpected payload type {type(data).__name__}")
                return data
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError, ValueError) as exc:
                if attempt == self.max_retries:
                    raise ExtractionError(f"giving up after {attempt} attempts: {exc}") from exc
                wait = self.backoff * 2 ** (attempt - 1)
                log.warning("request failed attempt=%s wait=%.1fs error=%s", attempt, wait, exc)
                time.sleep(wait)
        raise ExtractionError("unreachable")

    @staticmethod
    def build_where(start: str, end: str, filters: dict, updated_since: str | None = None) -> str:
        # half-open window: avoids the millisecond gap/overlap of an inclusive "between ... 23:59:59.999"
        clauses = [f"created_date >= '{start}'", f"created_date < '{end}'"]
        clauses += [f"{k}='{v}'" for k, v in filters.items()]
        if updated_since:
            clauses.append(f":updated_at > '{updated_since}'")
        return " AND ".join(clauses)

    def count(self, where: str) -> int:
        data = self._get({"$select": "count(*) AS n", "$where": where})
        try:
            return int(data[0]["n"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ExtractionError(f"malformed count response: {str(data)[:200]}") from exc

    def iter_pages(self, where: str, columns: list[str]):
        """Offset pagination ordered by the stable unique key (required for consistent paging)."""
        select = ",".join(columns + [":updated_at"])
        offset = 0
        while True:
            page = self._get({"$select": select, "$where": where, "$order": "unique_key",
                              "$limit": self.page_size, "$offset": offset})
            log.info("fetched page offset=%s rows=%s", offset, len(page))
            if any(not isinstance(r, dict) for r in page):
                raise ExtractionError(f"page at offset {offset} contains non-object rows")
            if not page:
                return
            yield page
            if len(page) < self.page_size:
                return
            offset += self.page_size

    def extract_to_file(self, where: str, columns: list[str], out_path: Path) -> dict:
        expected = self.count(where)
        log.info("api reports expected_rows=%s", expected)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        n = 0
        try:
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                for page in self.iter_pages(where, columns):
                    for rec in page:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n += len(page)
            # Records can be added while paging; fewer rows than expected means a lost page.
            if n < expected:
                raise ExtractionError(f"row count mismatch: extracted {n}, API reported {expected}")
            os.replace(tmp, out_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return {"rows": n, "expected": expected, "path": str(out_path),
                "extracted_at": datetime.now().astimezone().isoformat()}


def read_raw_file(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
