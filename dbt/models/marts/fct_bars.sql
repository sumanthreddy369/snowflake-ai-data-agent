select
    symbol,
    date_trunc('day', bar_ts) as date_key,
    bar_ts,
    open,
    high,
    low,
    close,
    volume,
    vwap,
    trade_count,
    bar_return,
    -- Trailing 30-bar volatility: stddev of minute-over-minute returns.
    -- This is the "volatility" the semantic layer's measure refers to.
    stddev(bar_return) over (
        partition by symbol order by bar_ts
        rows between 29 preceding and current row
    ) as rolling_volatility_30
from {{ ref('stg_bars') }}
