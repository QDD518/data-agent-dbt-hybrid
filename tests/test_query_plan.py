"""Query-plan parsing and registry validation tests."""

import pytest
from unittest.mock import patch

from backend.agent.planner import resolve_query_plan
from backend.semantic.query_plan import (
    EntityQueryPlan,
    FilterPlan,
    MetricQueryPlan,
    PlanValidationError,
    plan_from_legacy_intent,
    validate_query_plan,
)
from backend.semantic.registry import load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def test_legacy_metric_intent_becomes_validated_plan(registry):
    plan = plan_from_legacy_intent(
        {
            "path": "metric_query",
            "metric_names": ["total_revenue"],
            "dimensions": ["product_category"],
            "time_range": "last_month",
        },
        registry,
    )
    assert isinstance(plan, MetricQueryPlan)
    assert plan.metrics == ["total_revenue"]


def test_legacy_entity_intent_resolves_relationship_step(registry):
    plan = plan_from_legacy_intent(
        {
            "path": "ontology_query",
            "start_object": "InventoryRecord",
            "properties": ["quantity_on_hand", "product_name"],
            "filters": [{"property": "needs_reorder", "op": "eq", "value": True}],
        },
        registry,
    )
    assert isinstance(plan, EntityQueryPlan)
    assert [(step.from_entity, step.to_entity) for step in plan.relationships] == [
        ("InventoryRecord", "Product")
    ]


def test_legacy_entity_filter_can_target_related_entity(registry):
    plan = plan_from_legacy_intent(
        {
            "path": "ontology_query",
            "start_object": "InventoryRecord",
            "properties": ["quantity_on_hand"],
            "filters": [{"property": "warehouse_region", "op": "eq", "value": "North China"}],
        },
        registry,
    )
    assert plan.filters[0].entity == "Warehouse"
    assert [(step.from_entity, step.to_entity) for step in plan.relationships] == [
        ("InventoryRecord", "Warehouse")
    ]


def test_legacy_entity_intent_supports_multiple_root_relationships(registry):
    plan = plan_from_legacy_intent(
        {
            "path": "ontology_query",
            "start_object": "Order",
            "properties": ["segment", "category"],
        },
        registry,
    )
    assert {(step.from_entity, step.to_entity) for step in plan.relationships} == {
        ("Order", "Customer"),
        ("Order", "Product"),
    }


def test_cross_model_metric_plan_requires_scalar_shape(registry):
    plan = MetricQueryPlan(metrics=["total_revenue", "total_stock_quantity"])
    validate_query_plan(plan, registry)

    dimensional = MetricQueryPlan(
        metrics=["total_revenue", "total_stock_quantity"],
        dimensions=["product_category"],
    )
    with pytest.raises(PlanValidationError, match="only scalar metrics"):
        validate_query_plan(dimensional, registry)


def test_entity_plan_rejects_property_outside_path(registry):
    plan = EntityQueryPlan(
        root_entity="InventoryRecord",
        selections=[{"entity": "Customer", "property": "segment"}],
    )
    with pytest.raises(PlanValidationError, match="not present"):
        validate_query_plan(plan, registry)


def test_filter_plan_rejects_invalid_operator():
    with pytest.raises(ValueError, match="Unsupported filter operator"):
        FilterPlan(field="status", operator="contains", value="Completed")


def test_exploratory_fallback_rejects_raw_sql_and_accepts_json_plan(registry):
    with patch("backend.agent.planner.chat", return_value="SELECT * FROM users"):
        with pytest.raises(PlanValidationError, match="valid JSON"):
            resolve_query_plan("show data", {"path": "exploratory"}, registry)

    with patch(
        "backend.agent.planner.chat",
        return_value='{"mode":"entity_analysis","root_entity":"InventoryRecord","selections":[],"relationships":[],"filters":[],"time_range":null}',
    ):
        plan = resolve_query_plan("show stock", {"path": "exploratory"}, registry)
    assert isinstance(plan, EntityQueryPlan)
