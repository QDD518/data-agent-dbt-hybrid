with source as (
    select * from {{ ref('raw_campaign_results') }}
),

renamed as (
    select
        result_id,
        campaign_id,
        date,
        impressions,
        clicks,
        conversions,
        cost,
        revenue_generated,
        -- Derived KPIs
        case when impressions > 0 then clicks::float / impressions else 0 end as ctr,
        case when clicks > 0 then conversions::float / clicks else 0 end as conversion_rate,
        case when cost > 0 then revenue_generated::float / cost else 0 end as roas,
        case when conversions > 0 then cost::float / conversions else 0 end as cpa,
        revenue_generated - cost as net_profit
    from source
)

select * from renamed
