with source as (
    select * from {{ ref('raw_campaigns') }}
),

renamed as (
    select
        campaign_id,
        campaign_name,
        channel,
        start_date,
        end_date,
        budget,
        target_audience,
        campaign_type,
        end_date - start_date as duration_days
    from source
)

select * from renamed
