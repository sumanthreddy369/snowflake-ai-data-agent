-- Guardrail: OHLC sanity check. A bar where high isn't the max of
-- open/high/low/close (or low isn't the min) is a data bug, not market
-- volatility -- that distinction is exactly why this is a hard test (fails
-- the build) while the is_suspect flag in fct_bars is a soft flag (fails
-- nothing, just surfaces for review). dbt singular tests return failing
-- rows; any row returned here fails `dbt test`.

select *
from {{ ref('fct_bars') }}
where high < low
   or high < open
   or high < close
   or low > open
   or low > close
   or open <= 0
   or close <= 0
   or volume < 0
