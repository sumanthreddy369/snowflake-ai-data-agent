select
    customer_id,
    full_name,
    email,
    ssn,
    account_open_date,
    region
from {{ ref('stg_customers') }}
