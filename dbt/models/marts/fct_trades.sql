select
    trade_id,
    symbol,
    date_trunc('day', trade_ts) as date_key,
    trade_ts,
    price,
    size,
    notional,
    exchange_code
from {{ ref('stg_trades') }}
