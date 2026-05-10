WITH orders AS (
    SELECT * FROM {{ ref('stg_orders') }}
),

customers AS (
    SELECT * FROM {{ ref('stg_customers') }}
),

products AS (
    SELECT * FROM {{ ref('stg_products') }}
)

SELECT
    -- Order dimensions
    o.order_id,
    o.order_date,
    o.status,
    o.quantity,

    -- Financials
    o.unit_price,
    o.discount_pct,
    o.gross_amount,
    o.net_amount,

    -- Customer dimensions
    o.customer_id,
    c.customer_name,
    c.city,
    c.region          AS customer_region,
    c.country         AS customer_country,
    c.segment         AS customer_segment,
    c.registered_date AS customer_registered_date,

    -- Product dimensions
    o.product_id,
    p.product_name,
    p.category        AS product_category,
    p.subcategory     AS product_subcategory,
    p.cost_price      AS product_cost_price,
    p.list_price      AS product_list_price,
    p.margin          AS product_margin,
    p.margin_pct      AS product_margin_pct

FROM orders o
LEFT JOIN customers c ON o.customer_id = c.customer_id
LEFT JOIN products p ON o.product_id = p.product_id
