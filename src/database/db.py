"""Database helpers: engine creation, SQL file execution and fast COPY loading."""
import io
import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from src.config import ROOT, database_url

log = logging.getLogger(__name__)


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True, future=True)


def run_sql_file(conn: Connection, path: Path) -> None:
    """Execute a SQL script (may contain many statements) on an open connection/transaction."""
    sql = Path(path).read_text(encoding="utf-8")
    conn.exec_driver_sql(sql)


def init_db(engine: Engine) -> None:
    with engine.begin() as conn:
        for f in sorted((ROOT / "sql" / "schema").glob("*.sql")):
            run_sql_file(conn, f)
    log.info("database schema initialised")


def build_views(target) -> None:
    """Rebuild reporting views. Pass a Connection to join the caller's transaction (views are
    transactional in PostgreSQL, so a failure rolls back together with the data it describes)."""
    def _run(conn):
        for f in sorted((ROOT / "sql" / "transformations").glob("*views*.sql")):
            run_sql_file(conn, f)
    if isinstance(target, Engine):
        with target.begin() as conn:
            _run(conn)
    else:
        _run(target)
    log.info("reporting views built")


def copy_df(conn: Connection, table: str, df: pd.DataFrame) -> int:
    """Bulk-load a DataFrame with PostgreSQL COPY inside the caller's transaction."""
    if df.empty:
        return 0
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cols = ", ".join(df.columns)
    raw = conn.connection.driver_connection  # psycopg3 connection sharing this transaction
    with raw.cursor() as cur:
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')") as cp:
            while chunk := buf.read(1 << 20):
                cp.write(chunk)
    return len(df)


def read_df(conn: Connection, sql: str, **params) -> pd.DataFrame:
    return pd.read_sql(text(sql), conn, params=params)
