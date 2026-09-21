-- Step 8: Validate — manual SQL comparison
-- For each verified_query in the semantic model, keep a hand-checked SQL twin
-- here. Run the agent's answer and this query side by side; log any mismatch.

-- Mirrors "total_spend_last_30_days" in semantic_layer/semantic_model.yaml
SELECT SUM(amount) AS total_spend
FROM BANK_AGENT.GOLD.FCT_TRANSACTIONS
WHERE transaction_ts >= DATEADD('day', -30, CURRENT_DATE())
  AND transaction_status != 'REVERSED';

-- Mirrors "fraud_rate_by_merchant_category"
SELECT m.mcc_category,
       SUM(IFF(t.is_fraud, 1, 0)) / COUNT(DISTINCT t.transaction_id) AS fraud_rate
FROM BANK_AGENT.GOLD.FCT_TRANSACTIONS t
JOIN BANK_AGENT.GOLD.DIM_MERCHANTS m ON t.merchant_id = m.merchant_id
WHERE DATE_TRUNC('month', t.transaction_ts) = DATE_TRUNC('month', CURRENT_DATE())
GROUP BY m.mcc_category
ORDER BY fraud_rate DESC;

-- Mirrors "active_customers_by_region"
SELECT c.region, COUNT(DISTINCT t.customer_id) AS active_customers
FROM BANK_AGENT.GOLD.FCT_TRANSACTIONS t
JOIN BANK_AGENT.GOLD.DIM_CUSTOMERS c ON t.customer_id = c.customer_id
WHERE DATE_TRUNC('month', t.transaction_ts) = DATE_TRUNC('month', CURRENT_DATE())
  AND t.transaction_status = 'APPROVED'
GROUP BY c.region
ORDER BY active_customers DESC;

-- Add one block per new verified_query so the agent's answers stay auditable
-- against a query a human wrote and checked independently.
