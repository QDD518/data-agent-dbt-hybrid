{# MetricFlow requires a time spine table with day-level granularity.
   This generates dates covering the full range of our order data (2025-06 to 2026-05). #}

SELECT
    date_day
FROM
    {{ ref('dates') }}
WHERE
    date_day BETWEEN '2025-01-01' AND '2026-12-31'
