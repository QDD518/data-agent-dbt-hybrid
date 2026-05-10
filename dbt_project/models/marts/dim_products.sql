SELECT
    product_id,
    product_name,
    category,
    subcategory,
    cost_price,
    list_price,
    margin,
    margin_pct
FROM {{ ref('stg_products') }}
