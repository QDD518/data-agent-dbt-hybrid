WITH source AS (
    SELECT * FROM {{ ref('raw_orders') }}
),

renamed AS (
    SELECT
        order_id,
        customer_id,
        product_id,
        order_date,
        status,
        quantity,
        unit_price,
        discount_pct,
        unit_price * quantity AS gross_amount,
        unit_price * quantity * (1 - discount_pct / 100.0) AS net_amount
    FROM source
)

SELECT * FROM renamed
