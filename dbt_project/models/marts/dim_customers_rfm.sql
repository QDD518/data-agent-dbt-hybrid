-- RFM Analysis: Recency, Frequency, Monetary segmentation
-- Uses the fact_orders table to compute per-customer metrics
with orders as (
    select
        customer_id,
        order_date,
        order_id,
        net_amount
    from {{ ref('fact_orders') }}
    where status = 'Completed'
),

customers as (
    select * from {{ ref('stg_customers') }}
),

-- Define reference date as most recent order date in the dataset
reference_date as (
    select max(order_date) as ref_date from orders
),

customer_metrics as (
    select
        o.customer_id,
        max(o.order_date) as last_order_date,
        (select ref_date from reference_date) - max(o.order_date) as recency_days,
        count(distinct o.order_id) as frequency,
        sum(o.net_amount) as monetary,
        -- Average order value
        sum(o.net_amount) / count(distinct o.order_id) as avg_order_value,
        -- Days since first purchase (customer lifetime)
        (select ref_date from reference_date) - min(o.order_date) as customer_lifetime_days
    from orders o
    group by o.customer_id
),

-- RFM Scoring (1-5 scale, 5 = best)
scored as (
    select
        cm.*,
        c.customer_name,
        c.city,
        c.region,
        c.segment,
        c.registered_date,
        -- Recency: lower is better → higher score
        ntile(5) over (order by cm.recency_days desc) as r_score,
        -- Frequency: higher is better
        ntile(5) over (order by cm.frequency asc) as f_score,
        -- Monetary: higher is better
        ntile(5) over (order by cm.monetary asc) as m_score
    from customer_metrics cm
    left join customers c on cm.customer_id = c.customer_id
),

-- Segment classification
segmented as (
    select
        *,
        r_score + f_score + m_score as rfm_total,
        -- High-value: top 20%, At-risk: good but recent gap, Loyal: frequent, New: recent but low freq
        case
            when r_score >= 4 and f_score >= 4 and m_score >= 4 then 'Champions'
            when r_score >= 4 and (f_score + m_score) >= 6 then 'Loyal Customers'
            when r_score >= 4 and (f_score + m_score) < 6 then 'New Customers'
            when r_score <= 2 and f_score >= 3 and m_score >= 3 then 'At Risk'
            when r_score <= 2 and f_score <= 2 and m_score <= 2 then 'Lost'
            when f_score >= 4 then 'Frequent Buyers'
            when m_score >= 4 then 'Big Spenders'
            else 'Needs Attention'
        end as rfm_segment
    from scored
)

select * from segmented
