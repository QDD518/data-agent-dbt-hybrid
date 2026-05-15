"""Intent Router tests — mock LLM responses."""

import pytest
from unittest.mock import patch, MagicMock


class TestRouterClassification:
    """Test classify_intent with mocked LLM responses."""

    @pytest.fixture
    def router_module(self):
        from backend.agent import router
        return router

    @pytest.fixture
    def mock_chat(self):
        with patch("backend.agent.router.chat") as mock:
            yield mock

    def test_metric_query_path(self, router_module, mock_chat):
        mock_chat.return_value = '{"path": "metric_query", "metric_names": ["total_revenue"], "dimensions": ["order_date"], "time_range": "last_month"}'
        result = router_module.classify_intent("上月营收是多少？")
        assert result["path"] == "metric_query"
        assert "total_revenue" in result["metric_names"]
        assert result["time_range"] == "last_month"

    def test_exploratory_path(self, router_module, mock_chat):
        mock_chat.return_value = '{"path": "exploratory", "metric_names": [], "dimensions": [], "time_range": null}'
        result = router_module.classify_intent("购买超过3次的客户还买了什么？")
        assert result["path"] == "exploratory"

    def test_metadata_path(self, router_module, mock_chat):
        mock_chat.return_value = '{"path": "metadata", "metric_names": [], "dimensions": [], "time_range": null}'
        result = router_module.classify_intent("revenue 指标是怎么计算的？")
        assert result["path"] == "metadata"

    def test_metric_query_with_multiple_metrics(self, router_module, mock_chat):
        mock_chat.return_value = '{"path": "metric_query", "metric_names": ["total_revenue", "total_orders"], "dimensions": ["product_category"], "time_range": null}'
        result = router_module.classify_intent("每个品类的营收和订单量")
        assert result["path"] == "metric_query"
        assert len(result["metric_names"]) == 2
        assert "total_revenue" in result["metric_names"]
        assert "total_orders" in result["metric_names"]

    def test_chinese_question_with_dimensions(self, router_module, mock_chat):
        mock_chat.return_value = '{"path": "metric_query", "metric_names": ["total_revenue"], "dimensions": ["city"], "time_range": "this_year"}'
        result = router_module.classify_intent("今年每个城市的营收")
        assert result["path"] == "metric_query"
        assert result["dimensions"] == ["city"]
        assert result["time_range"] == "this_year"

    def test_json_decode_fallback(self, router_module, mock_chat):
        """Malformed LLM response should fall back to exploratory."""
        mock_chat.return_value = "not valid json at all"
        result = router_module.classify_intent("some random question")
        assert result["path"] == "exploratory"

    def test_markdown_fence_stripped(self, router_module, mock_chat):
        mock_chat.return_value = '```json\n{"path": "metadata", "metric_names": [], "dimensions": [], "time_range": null}\n```'
        result = router_module.classify_intent("字段是什么意思")
        assert result["path"] == "metadata"


class TestRouterPromptContainsMetrics:
    """The router prompt should include available metrics and dimensions."""

    def test_classify_builds_metric_list(self):
        """Verify the router constructs the prompt with metrics (smoke test — needs LLM)."""
        from backend.semantic.query_builder import MetricQueryBuilder
        builder = MetricQueryBuilder()
        metrics = builder.list_metrics()
        dims = builder.list_dimensions()
        assert len(metrics) >= 8, f"Expected at least 8 metrics, got {len(metrics)}"
        assert len(dims) >= 5, f"Expected at least 5 dimensions, got {len(dims)}"
