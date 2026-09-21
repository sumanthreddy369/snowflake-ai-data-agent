select
    merchant_id,
    merchant_name,
    mcc_category,
    risk_tier
from {{ ref('stg_merchants') }}
