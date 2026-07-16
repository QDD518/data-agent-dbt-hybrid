"""SSE integration tests for the QueryPlan-based orchestration path."""

import json
from unittest.mock import patch

import pytest

from backend.sql.executor import QueryResult


def _result() -> QueryResult:
    result = QueryResult()
    result.columns = ["value"]
    result.rows = [[42]]
    result.row_count = 1
    return result


async def _collect_events(message: str) -> list[dict]:
    from backend.agent.orchestrator import process_message

    events = []
    async for event in process_message(message):
        events.append(json.loads(event.removeprefix("data: ")))
    return events


@pytest.mark.asyncio
async def test_metric_route_emits_validated_plan_before_sql():
    with patch("backend.agent.orchestrator.classify_intent") as classify, \
         patch("backend.agent.orchestrator.execute_sql", return_value=_result()), \
         patch("backend.agent.orchestrator.chat", return_value='{"summary":"ok","chart_type":"table","insight":""}'):
        classify.return_value = {
            "path": "metric_query",
            "metric_names": ["total_revenue"],
            "dimensions": [],
            "time_range": "last_month",
        }
        events = await _collect_events("last month revenue")

    plan = next(event["plan"] for event in events if event["type"] == "plan")
    sql = next(event["sql"] for event in events if event["type"] == "sql")
    assert plan["mode"] == "metric_analysis"
    assert "order_date" in sql


@pytest.mark.asyncio
async def test_ontology_route_compiles_relationship_plan():
    with patch("backend.agent.orchestrator.classify_intent") as classify, \
         patch("backend.agent.orchestrator.execute_sql", return_value=_result()), \
         patch("backend.agent.orchestrator.chat", return_value='{"summary":"ok","chart_type":"table","insight":""}'):
        classify.return_value = {
            "path": "ontology_query",
            "start_object": "InventoryRecord",
            "properties": ["quantity_on_hand", "product_name"],
            "filters": [{"property": "needs_reorder", "op": "eq", "value": True}],
            "time_range": None,
        }
        events = await _collect_events("products to reorder")

    plan = next(event["plan"] for event in events if event["type"] == "plan")
    sql = next(event["sql"] for event in events if event["type"] == "sql")
    assert plan["mode"] == "entity_analysis"
    assert plan["relationships"][0]["relationship"] == "tracks"
    assert "JOIN analytics_analytics.dim_products" in sql


@pytest.mark.asyncio
async def test_exploratory_route_accepts_json_plan_not_raw_sql():
    with patch("backend.agent.orchestrator.classify_intent") as classify, \
         patch("backend.agent.orchestrator.execute_sql", return_value=_result()), \
         patch("backend.agent.orchestrator.chat", return_value='{"summary":"ok","chart_type":"table","insight":""}'), \
         patch("backend.agent.planner.chat", return_value='{"mode":"metric_analysis","metrics":["total_revenue"],"dimensions":[],"filters":[],"time_range":null}'):
        classify.return_value = {"path": "exploratory"}
        events = await _collect_events("show revenue")

    assert any(event["type"] == "plan" for event in events)
    assert any(event["type"] == "sql" for event in events)
    assert not any(event["type"] == "error" for event in events)
