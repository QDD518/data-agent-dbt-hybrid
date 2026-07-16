"""End-to-end plan-to-SQL compiler tests without an LLM or database."""

from backend.semantic.compiler import compile_entity_query, compile_metric_query
from backend.semantic.query_plan import EntityQueryPlan, MetricQueryPlan
from backend.semantic.registry import load_registry
from backend.sql.security import validate_sql


def test_metric_time_range_uses_real_default_time_column():
    sql = compile_metric_query(
        MetricQueryPlan(metrics=["total_revenue"], time_range="last_month"),
        load_registry(),
    )
    assert "order_date >= date_trunc('month', CURRENT_DATE) - interval '1 month'" in sql
    assert "order_date < date_trunc('month', CURRENT_DATE)" in sql
    assert "day >=" not in sql
    validate_sql(sql)


def test_metric_compiler_keeps_metric_filter_inside_aggregate():
    sql = compile_metric_query(MetricQueryPlan(metrics=["total_revenue"]), load_registry())
    assert "SUM(CASE WHEN status = 'Completed' THEN net_amount END) AS total_revenue" in sql
    validate_sql(sql)


def test_ratio_metrics_compile_from_declared_measure_formula():
    sql = compile_metric_query(MetricQueryPlan(metrics=["campaign_roi"]), load_registry())
    assert "SUM(net_profit) / NULLIF(SUM(cost), 0) AS campaign_roi" in sql
    validate_sql(sql)


def test_cross_model_scalar_metrics_are_preaggregated_before_cross_join():
    sql = compile_metric_query(
        MetricQueryPlan(metrics=["total_revenue", "total_stock_quantity"]),
        load_registry(),
    )
    assert "WITH" in sql
    assert "m0 AS (SELECT SUM(CASE WHEN status = 'Completed' THEN net_amount END)" in sql
    assert "m1 AS (SELECT SUM(quantity_on_hand) AS total_stock_quantity" in sql
    assert "CROSS JOIN m1" in sql
    validate_sql(sql)


def test_entity_compiler_builds_forward_relationship_join():
    sql = compile_entity_query(
        EntityQueryPlan(
            root_entity="Order",
            selections=[
                {"entity": "Order", "property": "order_id"},
                {"entity": "Customer", "property": "segment"},
            ],
            relationships=[
                {"relationship": "placed_by", "from_entity": "Order", "to_entity": "Customer"}
            ],
        ),
        load_registry(),
    )
    assert "JOIN analytics_analytics.dim_customers AS t1 ON t0.customer_id = t1.customer_id" in sql
    assert "t1.segment AS segment" in sql
    validate_sql(sql)


def test_entity_compiler_handles_denormalized_relationship_without_join():
    sql = compile_entity_query(
        EntityQueryPlan(
            root_entity="InventoryRecord",
            selections=[
                {"entity": "InventoryRecord", "property": "quantity_on_hand"},
                {"entity": "Warehouse", "property": "warehouse_name"},
            ],
            relationships=[
                {"relationship": "stored_in", "from_entity": "InventoryRecord", "to_entity": "Warehouse"}
            ],
        ),
        load_registry(),
    )
    assert "JOIN" not in sql
    assert "t0.warehouse_name AS warehouse_name" in sql
    validate_sql(sql)


def test_entity_compiler_qualifies_filter_on_related_denormalized_entity():
    sql = compile_entity_query(
        EntityQueryPlan(
            root_entity="InventoryRecord",
            selections=[{"entity": "InventoryRecord", "property": "quantity_on_hand"}],
            relationships=[
                {"relationship": "stored_in", "from_entity": "InventoryRecord", "to_entity": "Warehouse"}
            ],
            filters=[{"entity": "Warehouse", "field": "warehouse_region", "operator": "eq", "value": "North China"}],
        ),
        load_registry(),
    )
    assert "WHERE t0.warehouse_region = 'North China'" in sql
    validate_sql(sql)


def test_entity_compiler_handles_reverse_relationship_direction():
    sql = compile_entity_query(
        EntityQueryPlan(
            root_entity="Customer",
            selections=[
                {"entity": "Customer", "property": "customer_name"},
                {"entity": "Order", "property": "status"},
            ],
            relationships=[
                {"relationship": "placed_by", "from_entity": "Customer", "to_entity": "Order"}
            ],
        ),
        load_registry(),
    )
    assert "JOIN analytics_analytics.fact_orders AS t1 ON t1.customer_id = t0.customer_id" in sql
    validate_sql(sql)


def test_entity_compiler_supports_multiple_relationships_from_root():
    sql = compile_entity_query(
        EntityQueryPlan(
            root_entity="Order",
            selections=[
                {"entity": "Customer", "property": "customer_name"},
                {"entity": "Product", "property": "product_name"},
            ],
            relationships=[
                {"relationship": "placed_by", "from_entity": "Order", "to_entity": "Customer"},
                {"relationship": "contains", "from_entity": "Order", "to_entity": "Product"},
            ],
        ),
        load_registry(),
    )
    assert "JOIN analytics_analytics.dim_customers AS t1 ON t0.customer_id = t1.customer_id" in sql
    assert "JOIN analytics_analytics.dim_products AS t2 ON t0.product_id = t2.product_id" in sql
    validate_sql(sql)
