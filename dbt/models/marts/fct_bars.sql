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
    ) as rolling_volatility_30,
    -- Circuit-breaker flag: a >10% move in a single minute bar is unusual
    -- enough to warrant a human look before the agent treats it as fact.
    -- Flagged, not dropped -- a real move (e.g. earnings news) is legitimate
    -- data; a bad tick is a data bug. Either way, it shouldn't be silently
    -- trusted. See sql/08_validation for the monitoring query this feeds.
    abs(bar_return) > 0.10 as is_suspect
from {{ ref('stg_bars') }}
