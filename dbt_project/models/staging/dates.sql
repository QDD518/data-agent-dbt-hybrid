{# Time spine seed model — generates all dates from 2025-01-01 to 2026-12-31.
   Used by MetricFlow for time-based metric calculations and cumulative metrics. #}

SELECT
    generate_series(
        '2025-01-01'::date,
        '2026-12-31'::date,
        '1 day'::interval
    ) AS date_day
