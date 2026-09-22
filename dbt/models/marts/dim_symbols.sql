select
    symbol,
    company_name,
    sector,
    exchange,
    is_active
from {{ ref('stg_symbols') }}
