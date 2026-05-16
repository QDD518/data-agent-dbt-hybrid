with source as (
    select * from {{ ref('raw_inventory') }}
),

renamed as (
    select
        inventory_id,
        product_id::integer as product_id,
        warehouse_id,
        quantity_on_hand,
        reorder_point,
        last_restock_date,
        -- Derived flags
        case when quantity_on_hand < reorder_point then true else false end as needs_reorder,
        quantity_on_hand - reorder_point as stock_surplus,
        -- Cost of understock
        case when quantity_on_hand = 0 then true else false end as is_out_of_stock
    from source
)

select * from renamed
