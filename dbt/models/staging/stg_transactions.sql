select
    transaction_id,
    customer_id,
    merchant_id,
    transaction_ts,
    amount,
    transaction_status,
    is_fraud
from {{ source('silver', 'transactions') }}
