WITH source AS (
    SELECT * FROM {{ ref('raw_customers') }}
),

renamed AS (
    SELECT
        customer_id,
        name AS customer_name,
        email,
        city,
        region,
        country,
        registered_date,
        segment
    FROM source
)

SELECT * FROM renamed
