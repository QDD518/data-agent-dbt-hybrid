with source as (
    select * from {{ ref('raw_suppliers') }}
),

renamed as (
    select
        supplier_id,
        supplier_name,
        country,
        lead_time_days,
        is_premium,
        product_category,
        case
            when lead_time_days <= 5 then 'Fast'
            when lead_time_days <= 14 then 'Normal'
            else 'Slow'
        end as delivery_tier
    from source
)

select * from renamed
