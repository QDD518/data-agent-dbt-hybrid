-- Monthly Cohort Retention Analysis
-- Tracks what % of customers who first purchased in month N return in months N+1, N+2, etc.
with orders as (
    select
        customer_id,
        order_date,
        date_trunc('month', order_date) as order_month,
        net_amount
    from {{ ref('fact_orders') }}
    where status = 'Completed'
),

-- First purchase month per customer
first_purchase as (
    select
        customer_id,
        min(date_trunc('month', order_date)) as cohort_month
    from orders
    group by customer_id
),

-- All customer-month pairs with purchases
customer_months as (
    select distinct
        o.customer_id,
        o.order_month,
        fp.cohort_month,
        -- Month index: 0 = cohort month, 1 = next month, etc.
        (extract(year from o.order_month) - extract(year from fp.cohort_month)) * 12
        + (extract(month from o.order_month) - extract(month from fp.cohort_month)) as month_index
    from orders o
    join first_purchase fp on o.customer_id = fp.customer_id
),

-- Cohort size: count of customers in each cohort month
cohort_size as (
    select
        cohort_month,
        count(distinct customer_id) as total_customers
    from first_purchase
    group by cohort_month
),

-- Retained customers per cohort per month
cohort_retention as (
    select
        cm.cohort_month,
        cm.month_index,
        count(distinct cm.customer_id) as retained_customers
    from customer_months cm
    group by cm.cohort_month, cm.month_index
)

select
    cr.cohort_month,
    cr.month_index,
    cr.retained_customers,
    cs.total_customers as cohort_size,
    -- Retention rate: % of original cohort still active
    round(cr.retained_customers::numeric / cs.total_customers * 100, 2) as retention_pct,
    -- Month label for readability
    case
        when cr.month_index = 0 then 'Month 0 (Acquisition)'
        when cr.month_index = 1 then 'Month 1'
        when cr.month_index = 2 then 'Month 2'
        when cr.month_index = 3 then 'Month 3'
        when cr.month_index = 4 then 'Month 4'
        when cr.month_index = 5 then 'Month 5'
        else 'Month ' || cr.month_index
    end as month_label
from cohort_retention cr
join cohort_size cs on cr.cohort_month = cs.cohort_month
order by cr.cohort_month, cr.month_index
