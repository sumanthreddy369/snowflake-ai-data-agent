select
    t.transaction_id,
    t.customer_id,
    t.merchant_id,
    date_trunc('day', t.transaction_ts) as date_key,
    t.transaction_ts,
    t.amount,
    t.transaction_status,
    t.is_fraud
from {{ ref('stg_transactions') }} t
where t.transaction_status != 'REVERSED'
