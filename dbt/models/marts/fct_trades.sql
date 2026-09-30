-- Row Access Policy is attached here, not in sql/07_governance: this model is
-- materialized as a table, which dbt rebuilds with CREATE OR REPLACE on every
-- run -- and that silently drops any policy a one-time ALTER TABLE attached.
-- Re-applying it as a post-hook means every rebuild comes back governed.
{{ config(
    post_hook="alter table {{ this }} add row access policy {{ this.database }}.{{ this.schema }}.DELAYED_DATA_POLICY on (trade_ts)"
) }}

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
