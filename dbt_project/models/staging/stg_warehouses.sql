with source as (
    select * from {{ ref('raw_warehouses') }}
),

renamed as (
    select
        warehouse_id,
        warehouse_name,
        city,
        region,
        capacity_sqft,
        is_active,
        case
            when capacity_sqft >= 50000 then 'Large'
            when capacity_sqft >= 35000 then 'Medium'
            else 'Small'
        end as size_tier
    from source
)

select * from renamed
