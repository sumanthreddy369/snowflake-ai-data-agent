select
    symbol,
    bar_ts,
    open,
    high,
    low,
    close,
    volume,
    vwap,
    trade_count,
    (close - open) / nullif(open, 0) as bar_return
from {{ source('silver', 'bars') }}
