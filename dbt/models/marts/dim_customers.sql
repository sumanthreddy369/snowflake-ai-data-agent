select
    customer_id,
    full_name,
    email,
    signup_date,
    region
from {{ ref('stg_customers') }}
