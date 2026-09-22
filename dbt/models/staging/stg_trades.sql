select
    trade_id,
    symbol,
    price,
    size,
    exchange_code,
    conditions,
    trade_ts,
    price * size as notional
from {{ source('silver', 'trades') }}
