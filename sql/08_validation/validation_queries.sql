-- Step 8: Validate — manual SQL comparison
-- For each verified_query in the semantic model, keep a hand-checked SQL twin
-- here. Run the agent's answer and this query side by side; log any mismatch.

-- Mirrors "total_revenue_last_30_days" in semantic_layer/semantic_model.yaml
SELECT SUM(line_total) AS revenue
FROM RETAIL_AGENT.GOLD.FCT_ORDERS
WHERE order_ts >= DATEADD('day', -30, CURRENT_DATE())
  AND order_status != 'CANCELLED';

-- Mirrors "active_customers_by_region"
SELECT c.region, COUNT(DISTINCT o.customer_id) AS active_customers
FROM RETAIL_AGENT.GOLD.FCT_ORDERS o
JOIN RETAIL_AGENT.GOLD.DIM_CUSTOMERS c ON o.customer_id = c.customer_id
WHERE DATE_TRUNC('month', o.order_ts) = DATE_TRUNC('month', CURRENT_DATE())
GROUP BY c.region
ORDER BY active_customers DESC;

-- Add one block per new verified_query so the agent's answers stay auditable
-- against a query a human wrote and checked independently.
