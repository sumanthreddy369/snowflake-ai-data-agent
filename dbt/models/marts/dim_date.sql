-- Simple generated date spine covering observed bar dates.
-- Swap for dbt-utils' date_spine() macro if the package is available.
--
-- Two fixes from the first live Snowflake run: QUALIFY only accepts window
-- functions (error 000992), so the bound is a plain WHERE; and SEQ4() is not
-- guaranteed gap-free, so day offsets come from ROW_NUMBER() instead.
with bounds as (
    select
        date_trunc('day', min(bar_ts)) as min_date,
        date_trunc('day', max(bar_ts)) as max_date
    from {{ ref('stg_bars') }}
),
offsets as (
    select row_number() over (order by seq4()) - 1 as day_offset
    from table(generator(rowcount => 5000))
),
spine as (
    select dateadd('day', o.day_offset, b.min_date) as date_day
    from offsets o
    cross join bounds b
    where dateadd('day', o.day_offset, b.min_date) <= b.max_date
)
select
    date_day as date_key,
    year(date_day) as year,
    month(date_day) as month,
    day(date_day) as day,
    dayname(date_day) as day_name,
    quarter(date_day) as quarter
from spine
