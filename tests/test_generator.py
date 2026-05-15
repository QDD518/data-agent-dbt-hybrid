"""Path B — SQL Generator tests (mock LLM)."""

import pytest
from unittest.mock import patch


class TestSQLGenerator:
    """Test generate_sql with mocked LLM."""

    @pytest.fixture
    def mock_chat(self):
        with patch("backend.sql.generator.chat") as mock:
            yield mock

    @pytest.fixture
    def mock_retrieve(self):
        with patch("backend.sql.generator.retrieve_context") as mock:
            mock.return_value = [
                "Table fact_orders (analytics): Orders. Columns: order_id, customer_id, net_amount",
            ]
            yield mock

    def test_generates_sql(self, mock_chat, mock_retrieve):
        mock_chat.return_value = "SELECT city, AVG(net_amount) AS avg_order_value FROM analytics.fact_orders GROUP BY city ORDER BY 2 DESC LIMIT 10"
        from backend.sql.generator import generate_sql
        sql = generate_sql("哪个城市平均客单价最高")
        assert "SELECT" in sql.upper()
        assert "FROM" in sql.upper()

    def test_unable_to_generate(self, mock_chat, mock_retrieve):
        mock_chat.return_value = "UNABLE_TO_GENERATE"
        from backend.sql.generator import generate_sql
        sql = generate_sql("some impossible question")
        assert sql == "UNABLE_TO_GENERATE"

    def test_strips_markdown_fences(self, mock_chat, mock_retrieve):
        mock_chat.return_value = "```sql\nSELECT * FROM analytics.fact_orders LIMIT 10\n```"
        from backend.sql.generator import generate_sql
        sql = generate_sql("show me orders")
        assert not sql.startswith("```")

    def test_empty_rag_context_handled(self, mock_chat, mock_retrieve):
        mock_retrieve.return_value = []
        mock_chat.return_value = "SELECT * FROM analytics.fact_orders LIMIT 10"
        from backend.sql.generator import generate_sql
        sql = generate_sql("show data")
        assert "SELECT" in sql.upper()
