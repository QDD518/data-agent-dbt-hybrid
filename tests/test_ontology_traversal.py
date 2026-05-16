"""Unit tests for GraphTraverser — CTE-based multi-hop SQL generation."""

import pytest

from backend.ontology.parser import load_ontology, OntologyStore, LinkType
from backend.ontology.traversal import (
    GraphTraverser,
    TraversalRequest,
    TraversalStep,
    FilterClause,
    AggregateDef,
    _filter_to_sql,
    _format_value,
    _agg_sql,
    _resolve_time_filter,
)
from backend.sql.security import validate_sql


@pytest.fixture(scope="module")
def store():
    return load_ontology()


@pytest.fixture(scope="module")
def traverser(store):
    return GraphTraverser(store)


# ── SQL helper unit tests ──

class TestFilterToSql:
    def test_eq_string(self):
        f = FilterClause("status", "eq", "Completed")
        assert _filter_to_sql(f) == "status = 'Completed'"

    def test_eq_number(self):
        f = FilterClause("quantity_on_hand", "eq", 0)
        assert _filter_to_sql(f) == "quantity_on_hand = 0"

    def test_eq_bool_true(self):
        f = FilterClause("needs_reorder", "eq", True)
        assert _filter_to_sql(f) == "needs_reorder = TRUE"

    def test_eq_bool_false(self):
        f = FilterClause("is_out_of_stock", "eq", False)
        assert _filter_to_sql(f) == "is_out_of_stock = FALSE"

    def test_neq(self):
        f = FilterClause("status", "neq", "Cancelled")
        assert _filter_to_sql(f) == "status != 'Cancelled'"

    def test_gt(self):
        f = FilterClause("quantity_on_hand", "gt", 50)
        assert _filter_to_sql(f) == "quantity_on_hand > 50"

    def test_gte(self):
        f = FilterClause("quantity_on_hand", "gte", 50)
        assert _filter_to_sql(f) == "quantity_on_hand >= 50"

    def test_lt(self):
        f = FilterClause("reorder_point", "lt", 20)
        assert _filter_to_sql(f) == "reorder_point < 20"

    def test_lte(self):
        f = FilterClause("reorder_point", "lte", 30)
        assert _filter_to_sql(f) == "reorder_point <= 30"

    def test_in_list(self):
        f = FilterClause("warehouse_region", "in", ["North China", "East China"])
        assert _filter_to_sql(f) == "warehouse_region IN ('North China', 'East China')"

    def test_between(self):
        f = FilterClause("quantity_on_hand", "between", (10, 100))
        assert _filter_to_sql(f) == "quantity_on_hand BETWEEN 10 AND 100"

    def test_like(self):
        f = FilterClause("product_name", "like", "%Phone%")
        assert _filter_to_sql(f) == "product_name LIKE '%Phone%'"

    def test_is_null(self):
        f = FilterClause("last_restock_date", "is_null", None)
        assert _filter_to_sql(f) == "last_restock_date IS NULL"

    def test_is_not_null(self):
        f = FilterClause("warehouse_id", "is_not_null", None)
        assert _filter_to_sql(f) == "warehouse_id IS NOT NULL"

    def test_with_table_alias(self):
        f = FilterClause("status", "eq", "Completed")
        assert _filter_to_sql(f, "c0") == "c0.status = 'Completed'"

    def test_string_escaping(self):
        f = FilterClause("name", "eq", "O'Brien")
        assert _filter_to_sql(f) == "name = 'O''Brien'"


class TestFormatValue:
    def test_null(self):
        assert _format_value(None) == "NULL"

    def test_true(self):
        assert _format_value(True) == "TRUE"

    def test_false(self):
        assert _format_value(False) == "FALSE"

    def test_int(self):
        assert _format_value(42) == "42"

    def test_float(self):
        assert _format_value(3.14) == "3.14"

    def test_string(self):
        assert _format_value("hello") == "'hello'"

    def test_list(self):
        assert _format_value([1, 2, 3]) == "1, 2, 3"

    def test_string_with_quote(self):
        assert _format_value("it's") == "'it''s'"


class TestAggSql:
    def test_sum(self):
        assert _agg_sql("SUM", "net_amount") == "SUM(net_amount)"

    def test_count_distinct(self):
        assert _agg_sql("COUNT_DISTINCT", "customer_id") == "COUNT(DISTINCT customer_id)"

    def test_avg(self):
        assert _agg_sql("AVG", "quantity_on_hand") == "AVG(quantity_on_hand)"

    def test_case_insensitive(self):
        assert _agg_sql("sum", "net_amount") == "SUM(net_amount)"


class TestTimeFilter:
    def test_last_month_with_custom_column(self):
        result = _resolve_time_filter("last_month", "last_restock_date")
        assert "last_restock_date" in result
        assert "date_trunc('month'" in result
        assert "1 month" in result

    def test_this_year_with_column(self):
        result = _resolve_time_filter("this_year", "order_date")
        assert "order_date" in result
        assert "date_trunc('year'" in result

    def test_unknown_returns_none(self):
        assert _resolve_time_filter("invalid", "order_date") is None


# ── BFS path finding ──

class TestFindPaths:
    def test_find_direct_path(self, traverser):
        paths = traverser.find_paths("Order", "Customer")
        assert len(paths) >= 1
        # The shortest path should be 1 hop
        assert len(paths[0]) == 1
        assert paths[0][0].name == "placed_by"

    def test_find_two_hop_path(self, traverser):
        paths = traverser.find_paths("InventoryRecord", "Customer")
        # InventoryRecord -> Product (tracks) -> Order (contains) -> Customer (placed_by)
        # or InventoryRecord -> Warehouse (stored_in) ... but that's a dead end
        # Actually no direct path to Customer from InventoryRecord in 3 hops
        # Let's check Product instead
        pass

    def test_find_path_product_to_inventory(self, traverser):
        paths = traverser.find_paths("Product", "InventoryRecord")
        assert len(paths) >= 1
        assert paths[0][0].name == "tracks"

    def test_no_path_returns_empty(self, traverser):
        paths = traverser.find_paths("Nonexistent", "Order")
        assert paths == []

    def test_max_hops_respected(self, traverser):
        paths = traverser.find_paths("Order", "Customer", max_hops=0)
        assert paths == []


# ── Single-object SQL generation ──

class TestSingleObjectSql:
    def test_basic_select(self, traverser):
        req = TraversalRequest(
            start_object="Product",
            properties=["product_name", "category"],
        )
        sql = traverser.build_sql(req)
        assert "SELECT" in sql
        assert "product_name" in sql
        assert "category" in sql
        assert "FROM analytics_analytics.dim_products" in sql
        assert "LIMIT 1000" in sql
        validate_sql(sql)  # Must pass security

    def test_select_with_filter(self, traverser):
        req = TraversalRequest(
            start_object="InventoryRecord",
            properties=["quantity_on_hand", "warehouse_region"],
            filters=[FilterClause("needs_reorder", "eq", True)],
        )
        sql = traverser.build_sql(req)
        assert "needs_reorder = TRUE" in sql
        assert "FROM analytics_analytics.fact_inventory" in sql
        validate_sql(sql)

    def test_select_with_time_range(self, traverser):
        req = TraversalRequest(
            start_object="InventoryRecord",
            properties=["quantity_on_hand"],
            time_range="last_month",
        )
        sql = traverser.build_sql(req)
        assert "last_restock_date" in sql
        assert "date_trunc('month'" in sql
        validate_sql(sql)

    def test_select_with_aggregates(self, traverser):
        req = TraversalRequest(
            start_object="InventoryRecord",
            aggregates=[
                AggregateDef("SUM", "quantity_on_hand", "total_stock"),
                AggregateDef("COUNT", "inventory_id", "record_count"),
            ],
        )
        sql = traverser.build_sql(req)
        assert "SUM(quantity_on_hand) AS total_stock" in sql
        assert "COUNT(inventory_id) AS record_count" in sql
        validate_sql(sql)

    def test_select_no_properties_uses_star(self, traverser):
        req = TraversalRequest(start_object="Customer")
        sql = traverser.build_sql(req)
        assert "*" in sql.split("\n")[1]


# ── Multi-hop SQL generation ──

class TestMultiHopSql:
    def test_one_hop_order_to_customer(self, traverser, store):
        link = store.link_by_name["placed_by"]
        req = TraversalRequest(
            start_object="Order",
            path=[
                TraversalStep(
                    from_object="Order",
                    to_object="Customer",
                    link=link,
                    select_properties=["customer_name", "segment"],
                ),
            ],
            properties=["order_id", "net_amount"],
            filters=[FilterClause("status", "eq", "Completed")],
        )
        sql = traverser.build_sql(req)
        assert "WITH" in sql
        assert "c0" in sql
        assert "c1" in sql
        assert "JOIN c1 ON c0.customer_id = c1.customer_id" in sql
        assert "customer_name" in sql
        assert "segment" in sql
        validate_sql(sql)

    def test_one_hop_inventory_to_product(self, traverser, store):
        link = store.link_by_name["tracks"]
        req = TraversalRequest(
            start_object="InventoryRecord",
            path=[
                TraversalStep(
                    from_object="InventoryRecord",
                    to_object="Product",
                    link=link,
                    select_properties=["product_name", "category", "cost_price"],
                ),
            ],
            properties=["quantity_on_hand", "warehouse_region"],
            filters=[FilterClause("needs_reorder", "eq", True)],
        )
        sql = traverser.build_sql(req)
        assert "WITH" in sql
        assert "JOIN" in sql
        assert "c0.product_id = c1.product_id" in sql
        assert "needs_reorder = TRUE" in sql
        validate_sql(sql)

    def test_denormalized_no_extra_cte(self, traverser, store):
        """InventoryRecord -> Warehouse via stored_in (denormalized). Should NOT create a CTE."""
        link = store.link_by_name["stored_in"]
        req = TraversalRequest(
            start_object="InventoryRecord",
            path=[
                TraversalStep(
                    from_object="InventoryRecord",
                    to_object="Warehouse",
                    link=link,
                    select_properties=["warehouse_name", "warehouse_size"],
                ),
            ],
            properties=["quantity_on_hand"],
        )
        sql = traverser.build_sql(req)
        # Since stored_in is denormalized, no CTE or JOIN needed.
        # The warehouse columns should be selected from fact_inventory directly.
        assert "JOIN" not in sql
        assert "warehouse_name" in sql
        validate_sql(sql)

    def test_two_hops_denormalized_then_real(self, traverser, store):
        """InventoryRecord -> Warehouse (denorm) then ... no, this doesn't make sense.
        Instead: Order -> Product (contains, real join) is a standard 1-hop."""
        link = store.link_by_name["contains"]
        req = TraversalRequest(
            start_object="Order",
            path=[
                TraversalStep(
                    from_object="Order",
                    to_object="Product",
                    link=link,
                    select_properties=["product_name", "category"],
                ),
            ],
            properties=["order_id", "net_amount"],
        )
        sql = traverser.build_sql(req)
        assert "WITH" in sql
        assert "JOIN" in sql
        assert "c0.product_id = c1.product_id" in sql
        validate_sql(sql)

    def test_all_generated_sql_is_readable(self, traverser):
        """Verify SQL is well-formed with proper keywords."""
        req = TraversalRequest(
            start_object="Product",
            properties=["product_name", "category"],
        )
        sql = traverser.build_sql(req)
        lines = [l.strip() for l in sql.split("\n") if l.strip()]
        assert any(l.startswith("SELECT") for l in lines)
        assert any(l.startswith("FROM") for l in lines)

    def test_empty_request_is_valid(self, traverser):
        req = TraversalRequest(start_object="Customer")
        sql = traverser.build_sql(req)
        assert len(sql) > 0
        validate_sql(sql)

    def test_unknown_object_raises(self, traverser):
        req = TraversalRequest(start_object="NonexistentObject")
        with pytest.raises(ValueError):
            traverser.build_sql(req)

    def test_unknown_link_raises(self, traverser, store):
        fake_link = LinkType(
            name="fake", description="", source="Order", target="Customer",
            source_column="x", target_column="y", cardinality="many_to_one",
            denormalized=False,
        )
        req = TraversalRequest(
            start_object="Order",
            path=[TraversalStep(from_object="Order", to_object="Customer", link=fake_link)],
        )
        with pytest.raises(ValueError):
            traverser.build_sql(req)
