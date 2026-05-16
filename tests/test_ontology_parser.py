"""Unit tests for OntologyStore parser."""

import json
import pytest

from backend.ontology.parser import (
    OntologyStore,
    ObjectType,
    LinkType,
    PropertyDef,
    load_ontology,
)


class TestOntologyParser:
    """Tests that require the ontology.yml file to exist and parse correctly."""

    @pytest.fixture(scope="module")
    def store(self):
        return load_ontology()

    def test_load_succeeds(self, store):
        """Ontology file parses and indices are populated."""
        assert len(store.object_by_name) > 0
        assert len(store.link_by_name) > 0

    def test_all_object_types_loaded(self, store):
        expected = {
            "Order", "Customer", "Product", "Warehouse",
            "InventoryRecord", "CampaignResult", "Campaign", "RFMCustomer",
        }
        assert set(store.object_by_name.keys()) == expected

    def test_all_link_types_loaded(self, store):
        expected = {
            "placed_by", "contains", "tracks",
            "stored_in", "measures_performance_of", "ordered_by_rfm",
        }
        assert set(store.link_by_name.keys()) == expected

    def test_object_has_properties(self, store):
        order = store.object_by_name["Order"]
        assert isinstance(order, ObjectType)
        assert order.primary_key == "order_id"
        assert order.table == "analytics_analytics.fact_orders"
        assert order.time_dimension == "order_date"
        assert "order_id" in order.properties
        assert "net_amount" in order.properties
        assert order.properties["net_amount"].prop_type == "Numeric"
        assert order.properties["status"].prop_type == "String"

    def test_object_display_names(self, store):
        assert store.object_by_name["Order"].display_name == "订单"
        assert store.object_by_name["Customer"].display_name == "客户"
        assert store.object_by_name["Product"].display_name == "商品"
        assert store.object_by_name["Warehouse"].display_name == "仓库"

    def test_object_icons_and_colors(self, store):
        assert store.object_by_name["Product"].icon == "package"
        assert store.object_by_name["Product"].color == "#F5A623"
        assert store.object_by_name["Warehouse"].icon == "building"

    def test_link_adjacency(self, store):
        out_order = store.outbound_links.get("Order", [])
        link_names = {l.name for l in out_order}
        assert "placed_by" in link_names
        assert "contains" in link_names
        assert "ordered_by_rfm" in link_names

    def test_link_join_keys(self, store):
        link = store.link_by_name["tracks"]
        assert link.source == "InventoryRecord"
        assert link.target == "Product"
        assert link.source_column == "product_id"
        assert link.target_column == "product_id"
        assert link.cardinality == "many_to_one"

    def test_denormalized_links(self, store):
        assert store.link_by_name["stored_in"].denormalized is True
        assert store.link_by_name["measures_performance_of"].denormalized is True
        assert store.link_by_name["contains"].denormalized is False

    def test_warehouse_no_time_dimension(self, store):
        assert store.object_by_name["Warehouse"].time_dimension is None

    def test_rfm_customer_time_dimension(self, store):
        assert store.object_by_name["RFMCustomer"].time_dimension == "last_order_date"

    def test_adjacency_bidirectional(self, store):
        adj_order = store.adjacency.get("Order", [])
        neighbors = {n for n, _ in adj_order}
        assert "Customer" in neighbors
        assert "Product" in neighbors
        assert "RFMCustomer" in neighbors

    def test_to_graph_dict(self, store):
        graph = store.to_graph_dict()
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) == 8
        assert len(graph["edges"]) == 6

        # Verify node structure
        node = graph["nodes"][0]
        assert "id" in node
        assert "label" in node
        assert "properties" in node
        assert "table" in node

        # Verify edge structure
        edge = graph["edges"][0]
        assert "source" in edge
        assert "target" in edge
        assert "label" in edge
        assert "denormalized" in edge

    def test_to_graph_dict_is_json_serializable(self, store):
        graph = store.to_graph_dict()
        json_str = json.dumps(graph, ensure_ascii=False)
        assert len(json_str) > 0

    def test_to_rag_documents(self, store):
        docs = store.to_rag_documents()
        assert len(docs) == 14  # 8 objects + 6 links

        # Object documents include key info
        inv_doc = [d for d in docs if "Object Type InventoryRecord" in d][0]
        assert "库存记录" in inv_doc
        assert "fact_inventory" in inv_doc
        assert "quantity_on_hand" in inv_doc
        assert "reorder_point" in inv_doc

        # Link documents include denormalized flag
        stored_doc = [d for d in docs if "Link Type stored_in" in d][0]
        assert "denormalized" in stored_doc
        assert "no JOIN needed" in stored_doc
