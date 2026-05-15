"""SQL executor tests — needs running PostgreSQL."""

import pytest
from backend.sql.executor import execute_sql, _serialize, QueryResult
from backend.sql.security import SQLSecurityError
from decimal import Decimal
from datetime import date, datetime


class TestSerialize:
    def test_decimal_to_float(self):
        assert _serialize(Decimal("10.99")) == 10.99

    def test_datetime_to_iso(self):
        dt = datetime(2025, 6, 15, 10, 30, 0)
        assert _serialize(dt) == "2025-06-15T10:30:00"

    def test_date_to_iso(self):
        d = date(2025, 6, 15)
        assert _serialize(d) == "2025-06-15"

    def test_string_passthrough(self):
        assert _serialize("hello") == "hello"

    def test_int_passthrough(self):
        assert _serialize(42) == 42

    def test_none_passthrough(self):
        assert _serialize(None) is None


class TestQueryResult:
    def test_default_values(self):
        qr = QueryResult()
        assert qr.columns == []
        assert qr.rows == []
        assert qr.row_count == 0
        assert qr.truncated is False


@pytest.mark.skip(reason="Requires running PostgreSQL")
class TestExecuteSQL:
    """Tests that need a running PostgreSQL instance."""

    def test_simple_query(self):
        result = execute_sql("SELECT 1 AS num")
        assert result.columns == ["num"]
        assert result.rows == [[1]]
        assert result.row_count == 1
        assert result.elapsed_ms > 0

    def test_query_from_analytics_schema(self):
        result = execute_sql("SELECT COUNT(*) AS cnt FROM analytics.fact_orders")
        assert result.row_count == 1
        assert result.rows[0][0] > 0

    def test_blocked_query_raises(self):
        with pytest.raises(SQLSecurityError):
            execute_sql("DROP TABLE analytics.fact_orders")

    def test_row_limit_enforced(self):
        result = execute_sql("SELECT * FROM analytics.fact_orders")
        assert result.row_count <= 1000
