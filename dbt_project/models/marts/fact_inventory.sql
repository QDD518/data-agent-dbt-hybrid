-- OBT-style inventory fact: joins inventory to products, warehouses, suppliers
with inventory as (
    select * from {{ ref('stg_inventory') }}
),

products as (
    select * from {{ ref('stg_products') }}
),

warehouses as (
    select * from {{ ref('stg_warehouses') }}
),

suppliers as (
    select * from {{ ref('stg_suppliers') }}
),

joined as (
    select
        i.inventory_id,
        i.product_id,
        i.warehouse_id,
        i.quantity_on_hand,
        i.reorder_point,
        i.last_restock_date,
        i.needs_reorder,
        i.stock_surplus,
        i.is_out_of_stock,
        -- Product info
        p.product_name,
        p.category as product_category,
        p.subcategory as product_subcategory,
        p.cost_price,
        p.list_price,
        p.margin,
        p.margin_pct,
        -- Warehouse info
        w.warehouse_name,
        w.city as warehouse_city,
        w.region as warehouse_region,
        w.capacity_sqft,
        w.size_tier as warehouse_size,
        -- Supplier info (via product category)
        s.supplier_id,
        s.supplier_name,
        s.country as supplier_country,
        s.lead_time_days,
        s.delivery_tier,
        s.is_premium as supplier_is_premium,
        -- Computed: inventory value
        i.quantity_on_hand * p.cost_price as inventory_value,
        -- Computed: days since last restock
        current_date - i.last_restock_date as days_since_restock
    from inventory i
    left join products p on i.product_id = p.product_id
    left join warehouses w on i.warehouse_id = w.warehouse_id
    left join suppliers s on p.category = s.product_category
)

select * from joined
