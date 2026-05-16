-- Campaign performance fact table: results + campaign metadata
with results as (
    select * from {{ ref('stg_campaign_results') }}
),

campaigns as (
    select * from {{ ref('stg_campaigns') }}
),

joined as (
    select
        r.result_id,
        r.campaign_id,
        r.date,
        r.impressions,
        r.clicks,
        r.conversions,
        r.cost,
        r.revenue_generated,
        r.ctr,
        r.conversion_rate,
        r.roas,
        r.cpa,
        r.net_profit,
        -- Campaign metadata
        c.campaign_name,
        c.channel,
        c.start_date,
        c.end_date,
        c.budget,
        c.target_audience,
        c.campaign_type,
        c.duration_days,
        -- Budget utilization
        case when c.budget > 0 then r.cost::float / c.budget else 0 end as daily_budget_pct,
        -- Date relative to campaign
        r.date - c.start_date as campaign_day
    from results r
    left join campaigns c on r.campaign_id = c.campaign_id
)

select * from joined
