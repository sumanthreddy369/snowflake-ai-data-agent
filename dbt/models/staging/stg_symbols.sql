select
    symbol,
    company_name,
    sector,
    exchange,
    is_active
from {{ source('silver', 'symbols') }}
