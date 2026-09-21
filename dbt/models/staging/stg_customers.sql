select
    customer_id,
    full_name,
    email,
    ssn,
    account_open_date,
    region
from {{ source('silver', 'customers') }}
