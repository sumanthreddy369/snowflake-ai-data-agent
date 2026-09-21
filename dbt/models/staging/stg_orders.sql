select
    order_id,
    customer_id,
    product_id,
    order_ts,
    quantity,
    unit_price,
    quantity * unit_price as line_total,
    order_status
from {{ source('silver', 'orders') }}
