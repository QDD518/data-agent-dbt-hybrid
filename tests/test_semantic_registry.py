"""Tests for the canonical dbt + ontology semantic registry."""

from copy import deepcopy

import pytest

from backend.metadata.parser import load_metadata
from backend.ontology.parser import PropertyDef, load_ontology
from backend.semantic.registry import SemanticRegistryError, build_registry
from backend.semantic.registry import load_registry


def test_registry_combines_dbt_metrics_and_ontology_entities():
    registry = load_registry()
    assert "total_revenue" in registry.metrics
    assert "Order" in registry.entities
    assert "placed_by" in registry.relationships


def test_registry_uses_semantic_model_default_time_dimension():
    registry = load_registry()
    metric = registry.metric("total_revenue")
    assert metric.default_time_dimension == "order_date"
    assert metric.table == "analytics_analytics.fact_orders"


def test_registry_maps_business_property_to_physical_column():
    registry = load_registry()
    order = registry.entity("Order")
    assert order.properties["customer_city"] == "city"


def test_registry_finds_bidirectional_relationship_paths():
    registry = load_registry()
    forward = registry.find_path("InventoryRecord", "Product")
    reverse = registry.find_path("Product", "InventoryRecord")
    assert [item.name for item in forward] == ["tracks"]
    assert [item.name for item in reverse] == ["tracks"]


def test_registry_is_serializable_build_artifact():
    registry = load_registry()
    artifact = registry.to_dict()
    assert artifact["version"] == 1
    assert artifact["entities"]["Order"]["properties"]["customer_city"] == "city"


def test_registry_rejects_ontology_column_drift():
    ontology = deepcopy(load_ontology())
    ontology.object_by_name["Order"].properties["invalid_property"] = PropertyDef(
        name="invalid_property",
        prop_type="String",
        description="must not exist",
    )
    with pytest.raises(SemanticRegistryError, match="missing from dbt model"):
        build_registry(load_metadata(), ontology)
