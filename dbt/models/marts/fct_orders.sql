select
    o.order_id,
    o.customer_id,
    o.product_id,
    date_trunc('day', o.order_ts) as date_key,
    o.order_ts,
    o.quantity,
    o.unit_price,
    o.line_total,
    o.order_status
from {{ ref('stg_orders') }} o
where o.order_status != 'CANCELLED'
