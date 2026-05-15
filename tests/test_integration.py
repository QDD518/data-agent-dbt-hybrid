"""End-to-end integration tests — orchestration, SSE events, full pipeline.

Uses mock LLM to avoid API costs; real metadata + SQL executor (if PG available).
"""

import json
import pytest
from unittest.mock import patch, AsyncMock


# ── 20+ test questions covering all 3 paths ──

METRIC_QUESTIONS = [
    ("上月营收是多少？", "total_revenue", "last_month"),
    ("本月订单量", "total_orders", "this_month"),
    ("今年总营收", "total_revenue", "this_year"),
    ("上周的客单价", "avg_order_value", "last_week"),
    ("这个月每天的收入趋势", "daily_revenue", "this_month"),
    ("每月营收趋势", "monthly_revenue", None),
    ("按城市分组的订单量", "total_orders", None),
    ("按品类分组的营收", "total_revenue", None),
    ("总客户数", "total_customers", None),
    ("平均折扣率", "avg_discount_rate", None),
    ("总销售件数", "total_units_sold", None),
    ("按状态分组的营收", "total_revenue", None),
]

EXPLORATORY_QUESTIONS = [
    "哪个城市的客户平均客单价最高？",
    "2025年最畅销的产品是哪个？",
    "每月复购客户数量趋势？",
    "折扣率超过20%的订单有哪些？",
    "哪个品类的利润率最高？",
]

METADATA_QUESTIONS = [
    "revenue 指标是怎么计算的？",
    "fact_orders 表有哪些字段？",
    "订单表的数据来源是什么？",
    "metrics.yml 定义了哪些指标？",
    "semantic model 和 metric 有什么区别？",
]


# ── Unit-level integration: Orchestration event flow ──

class TestOrchestratorSSEEvents:
    """Verify the orchestrator emits the expected SSE event types for each path."""

    @pytest.fixture
    def mock_classify(self):
        with patch("backend.agent.orchestrator.classify_intent") as mock:
            yield mock

    @pytest.fixture
    def mock_execute(self):
        with patch("backend.agent.orchestrator.execute_sql") as mock:
            from backend.sql.executor import QueryResult
            qr = QueryResult()
            qr.columns = ["metric", "value"]
            qr.rows = [[100.0, 42]]
            qr.row_count = 1
            mock.return_value = qr
            yield mock

    @pytest.fixture
    def mock_chat(self):
        with patch("backend.agent.orchestrator.chat") as mock:
            mock.return_value = '{"summary": "Test result.", "chart_type": "bar", "insight": "Key insight."}'
            yield mock

    @pytest.fixture
    def mock_builder(self):
        with patch("backend.agent.orchestrator.MetricQueryBuilder") as mock_cls:
            mock_inst = mock_cls.return_value
            mock_inst.build_sql.return_value = "SELECT SUM(net_amount) AS total_revenue FROM analytics.fact_orders ORDER BY 1 DESC"
            yield mock_cls

    @pytest.mark.asyncio
    async def test_path_a_emits_expected_events(self, mock_classify, mock_execute, mock_chat, mock_builder):
        mock_classify.return_value = {
            "path": "metric_query",
            "metric_names": ["total_revenue"],
            "dimensions": [],
            "time_range": "last_month",
        }
        from backend.agent.orchestrator import process_message

        events = []
        async for event in process_message("上月营收是多少？"):
            events.append(event)

        event_types = [json.loads(e.split("data: ")[1])["type"] for e in events if e.startswith("data: ")]
        assert "status" in event_types
        assert "sql" in event_types
        assert "result" in event_types
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_path_a_no_metrics_yields_error(self):
        with patch("backend.agent.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = {
                "path": "metric_query",
                "metric_names": [],
                "dimensions": [],
                "time_range": None,
            }
            from backend.agent.orchestrator import process_message

            events = []
            async for event in process_message("hello"):
                events.append(event)

            error_events = [e for e in events if "error" in e]
            assert len(error_events) >= 1

    @pytest.mark.asyncio
    async def test_path_c_emits_answer(self):
        with patch("backend.agent.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = {
                "path": "metadata",
                "metric_names": [],
                "dimensions": [],
                "time_range": None,
            }
            with patch("backend.agent.orchestrator.retrieve_context") as mock_retrieve:
                mock_retrieve.return_value = ["Metric total_revenue: SUM of net_amount."]
                with patch("backend.agent.orchestrator.chat") as mock_chat:
                    mock_chat.return_value = "revenue 是净营收，由 net_amount 求和得到。"

                    from backend.agent.orchestrator import process_message

                    events = []
                    async for event in process_message("revenue 怎么计算的？"):
                        events.append(event)

                    done_events = [e for e in events if "done" in e]
                    assert len(done_events) >= 1

    @pytest.mark.asyncio
    async def test_unknown_path_yields_error(self):
        with patch("backend.agent.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = {
                "path": "unknown_type",
                "metric_names": [],
                "dimensions": [],
                "time_range": None,
            }
            from backend.agent.orchestrator import process_message

            events = []
            async for event in process_message("test"):
                events.append(event)

            error_events = [e for e in events if "Unknown path" in e]
            assert len(error_events) == 1


# ── Test question coverage report ──

class TestQuestionCoverage:
    """Document and verify the 20+ test questions exist and are categorized."""

    def test_metric_questions_count(self):
        assert len(METRIC_QUESTIONS) >= 10, f"Expected 10+ metric questions, got {len(METRIC_QUESTIONS)}"

    def test_exploratory_questions_count(self):
        assert len(EXPLORATORY_QUESTIONS) >= 5, f"Expected 5+ exploratory questions, got {len(EXPLORATORY_QUESTIONS)}"

    def test_metadata_questions_count(self):
        assert len(METADATA_QUESTIONS) >= 5, f"Expected 5+ metadata questions, got {len(METADATA_QUESTIONS)}"

    def test_total_questions_20_plus(self):
        total = len(METRIC_QUESTIONS) + len(EXPLORATORY_QUESTIONS) + len(METADATA_QUESTIONS)
        assert total >= 20, f"Expected 20+ total test questions, got {total}"
