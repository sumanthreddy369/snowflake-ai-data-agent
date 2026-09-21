-- Simple generated date spine covering observed transaction dates.
-- Swap for dbt-utils' date_spine() macro if the package is available.
with bounds as (
    select
        date_trunc('day', min(transaction_ts)) as min_date,
        date_trunc('day', max(transaction_ts)) as max_date
    from {{ ref('stg_transactions') }}
),
spine as (
    select
        dateadd('day', seq4(), (select min_date from bounds)) as date_day
    from table(generator(rowcount => 5000))
    qualify date_day <= (select max_date from bounds)
)
select
    date_day as date_key,
    year(date_day) as year,
    month(date_day) as month,
    day(date_day) as day,
    dayname(date_day) as day_name,
    quarter(date_day) as quarter
from spine
