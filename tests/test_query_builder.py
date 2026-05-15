"""Path A — MetricQueryBuilder tests (no LLM / no PG needed)."""

import pytest
from backend.semantic.query_builder import (
    MetricQueryBuilder, SemanticQuery, _agg_sql, _resolve_time_filter,
)


class TestAggSQL:
    def test_sum(self):
        assert _agg_sql("sum", "net_amount") == "SUM(net_amount)"

    def test_count_distinct(self):
        assert _agg_sql("count_distinct", "order_id") == "COUNT(DISTINCT order_id)"

    def test_average(self):
        assert _agg_sql("average", "net_amount") == "AVG(net_amount)"

    def test_min_max(self):
        assert _agg_sql("min", "price") == "MIN(price)"
        assert _agg_sql("max", "price") == "MAX(price)"

    def test_case_insensitive(self):
        assert _agg_sql("SUM", "amount") == "SUM(amount)"


class TestTimeFilter:
    def test_last_month(self):
        result = _resolve_time_filter("last_month", "day")
        assert "date_trunc('month', CURRENT_DATE)" in result
        assert "- interval '1 month'" in result

    def test_this_month(self):
        result = _resolve_time_filter("this_month", "day")
        assert "date_trunc('month', CURRENT_DATE)" in result
        assert "interval" not in result

    def test_none(self):
        assert _resolve_time_filter(None, "day") is None

    def test_empty_string(self):
        assert _resolve_time_filter("", "day") is None


class TestMetricQueryBuilder:
    @pytest.fixture(scope="class")
    def builder(self):
        return MetricQueryBuilder()

    def test_list_metrics(self, builder):
        metrics = builder.list_metrics()
        assert len(metrics) > 0
        names = [m["name"] for m in metrics]
        assert "total_revenue" in names or len(names) >= 8

    def test_list_dimensions(self, builder):
        dims = builder.list_dimensions()
        assert len(dims) > 0
        names = [d["name"] for d in dims]
        assert any("order_date" in n or "city" in n for n in names)

    # ── SQL generation ──

    def test_single_metric_no_dimensions(self, builder):
        sql = builder.build_sql(SemanticQuery(metric_names=["total_revenue"]))
        assert "SELECT" in sql
        assert "SUM" in sql or "COUNT" in sql
        assert "FROM" in sql
        assert "ORDER BY 1 DESC" in sql

    def test_metric_with_dimension(self, builder):
        sql = builder.build_sql(SemanticQuery(
            metric_names=["total_revenue"],
            dimensions=["order_date"],
        ))
        assert "GROUP BY" in sql
        assert "order_date" in sql

    def test_metric_with_time_range(self, builder):
        sql = builder.build_sql(SemanticQuery(
            metric_names=["total_revenue"],
            time_range="last_month",
        ))
        assert "WHERE" in sql
        assert "CURRENT_DATE" in sql

    def test_metric_with_filter(self, builder):
        sql = builder.build_sql(SemanticQuery(
            metric_names=["total_revenue"],
            filters={"product_category": "Smartphones"},
        ))
        assert "WHERE" in sql
        assert "Smartphones" in sql

    def test_unknown_metric_raises(self, builder):
        with pytest.raises(ValueError, match="Unknown metric"):
            builder.build_sql(SemanticQuery(metric_names=["nonexistent_metric_xyz"]))

    def test_sql_is_readable(self, builder):
        """Generated SQL should be well-formatted."""
        sql = builder.build_sql(SemanticQuery(
            metric_names=["total_revenue"],
            dimensions=["order_date"],
            time_range="last_month",
        ))
        assert "\n" in sql  # multi-line
        assert "SELECT" in sql.split("\n")[0]
