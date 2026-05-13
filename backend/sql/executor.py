import time
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from backend.config import settings
from backend.sql.security import validate_sql, SQLSecurityError


_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database_sync_url,
            poolclass=QueuePool,
            pool_size=4,
            max_overflow=4,
            pool_pre_ping=True,
            connect_args={
                "options": "-c default_transaction_read_only=on"
            },
        )
    return _engine


class QueryResult:
    """Result of a SQL query execution."""

    def __init__(self):
        self.columns: list[str] = []
        self.rows: list[list[Any]] = []
        self.row_count: int = 0
        self.elapsed_ms: float = 0
        self.truncated: bool = False


def execute_sql(sql: str) -> QueryResult:
    """Validate and execute a read-only SQL query. Returns QueryResult."""
    validate_sql(sql)

    start = time.perf_counter()
    engine = _get_engine()

    with engine.connect() as conn:
        # Set statement timeout
        conn.execute(text(f"SET LOCAL statement_timeout = '{settings.max_query_timeout}s'"))

        # Wrap with row limit
        limited_sql = f"SELECT * FROM ({sql}) AS _limited LIMIT {settings.max_result_rows}"
        result = conn.execute(text(limited_sql))

        qr = QueryResult()
        qr.columns = list(result.keys())
        qr.rows = [list(row) for row in result.fetchall()]
        qr.row_count = len(qr.rows)
        qr.truncated = qr.row_count >= settings.max_result_rows
        qr.elapsed_ms = (time.perf_counter() - start) * 1000

    return qr
