-- Step 8: Validate — manual SQL comparison
-- For each verified_query in the semantic model, keep a hand-checked SQL twin
-- here. Run the agent's answer and this query side by side; log any mismatch.
-- Note: these will reflect the same 15-minute-delayed view as the agent unless
-- run as a REALTIME_DESK role — see sql/07_governance.

-- Mirrors "todays_return_by_symbol"
SELECT symbol,
       (MAX_BY(close, bar_ts) - MIN_BY(open, bar_ts)) / NULLIF(MIN_BY(open, bar_ts), 0) AS period_return
FROM MARKET_AGENT.GOLD.FCT_BARS
WHERE symbol = 'AAPL' AND date_key = CURRENT_DATE()
GROUP BY symbol;

-- Mirrors "highest_volatility_symbols_today"
SELECT symbol, AVG(rolling_volatility_30) AS volatility
FROM MARKET_AGENT.GOLD.FCT_BARS
WHERE date_key = CURRENT_DATE()
GROUP BY symbol
ORDER BY volatility DESC
LIMIT 10;

-- Mirrors "suspect_bars_today" -- the circuit-breaker monitoring query.
-- A nonzero result isn't necessarily a bug (real news moves prices >10% in a
-- minute sometimes), but every row here deserves a human look before trusting
-- any aggregate metric that includes it.
SELECT symbol, bar_ts, open, close, bar_return
FROM MARKET_AGENT.GOLD.FCT_BARS
WHERE date_key = CURRENT_DATE() AND is_suspect
ORDER BY ABS(bar_return) DESC;

-- Mirrors "total_volume_by_sector"
SELECT s.sector, SUM(b.volume) AS total_volume
FROM MARKET_AGENT.GOLD.FCT_BARS b
JOIN MARKET_AGENT.GOLD.DIM_SYMBOLS s ON b.symbol = s.symbol
WHERE b.date_key = CURRENT_DATE()
GROUP BY s.sector
ORDER BY total_volume DESC;

-- Add one block per new verified_query so the agent's answers stay auditable
-- against a query a human wrote and checked independently.
