"""Optional database-level verification of compiled semantic SQL.

Run after ``dbt build`` with ``$env:RUN_DB_INTEGRATION='1'``. The default test
suite remains hermetic and does not require a local PostgreSQL service.
"""

import os

import pytest

from backend.semantic.compiler import compile_entity_query, compile_metric_query
from backend.semantic.query_plan import EntityQueryPlan, MetricQueryPlan
from backend.semantic.registry import load_registry
from backend.sql.executor import execute_sql


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_database():
    if os.getenv("RUN_DB_INTEGRATION") != "1":
        pytest.skip("set RUN_DB_INTEGRATION=1 after dbt build to run database integration tests")


def test_compiled_metric_query_executes_against_dbt_models():
    sql = compile_metric_query(MetricQueryPlan(metrics=["total_revenue"]), load_registry())
    result = execute_sql(sql)
    assert result.columns == ["total_revenue"]
    assert result.row_count == 1


def test_compiled_entity_relationship_query_executes_against_dbt_models():
    sql = compile_entity_query(
        EntityQueryPlan(
            root_entity="InventoryRecord",
            selections=[
                {"entity": "InventoryRecord", "property": "quantity_on_hand"},
                {"entity": "Product", "property": "product_name"},
            ],
            relationships=[
                {"relationship": "tracks", "from_entity": "InventoryRecord", "to_entity": "Product"}
            ],
            limit=10,
        ),
        load_registry(),
    )
    result = execute_sql(sql)
    assert result.columns == ["quantity_on_hand", "product_name"]


def test_cross_model_scalar_metric_query_executes_against_dbt_models():
    sql = compile_metric_query(
        MetricQueryPlan(metrics=["total_revenue", "total_stock_quantity"]),
        load_registry(),
    )
    result = execute_sql(sql)
    assert result.columns == ["total_revenue", "total_stock_quantity"]
    assert result.row_count == 1
