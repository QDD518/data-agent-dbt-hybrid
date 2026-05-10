WITH source AS (
    SELECT * FROM {{ ref('raw_products') }}
),

renamed AS (
    SELECT
        product_id,
        product_name,
        category,
        subcategory,
        cost_price,
        list_price,
        list_price - cost_price AS margin,
        ROUND((list_price - cost_price) / NULLIF(list_price, 0) * 100, 2) AS margin_pct
    FROM source
)

SELECT * FROM renamed
