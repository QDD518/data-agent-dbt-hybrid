SELECT
    customer_id,
    customer_name,
    email,
    city,
    region,
    country,
    registered_date,
    segment
FROM {{ ref('stg_customers') }}
