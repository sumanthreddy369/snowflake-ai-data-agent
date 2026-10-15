-- Exploratory data analysis in Snowflake, run against the loaded layers.
-- Sections follow the order an analyst would work in: what's there, is it
-- trustworthy, what does it say, and does the pipeline reconcile.
-- Results and screenshots: docs/snowflake-results.md.

-- ============================================================ 1. Inventory
-- EDA-1: rows per table in every layer
SELECT 'BRONZE.RAW_SYMBOLS' AS table_name, COUNT(*) AS row_count FROM MARKET_AGENT.BRONZE.RAW_SYMBOLS
UNION ALL SELECT 'BRONZE.RAW_BARS',    COUNT(*) FROM MARKET_AGENT.BRONZE.RAW_BARS
UNION ALL SELECT 'BRONZE.RAW_TRADES',  COUNT(*) FROM MARKET_AGENT.BRONZE.RAW_TRADES
UNION ALL SELECT 'BRONZE.RAW_NEWS',    COUNT(*) FROM MARKET_AGENT.BRONZE.RAW_NEWS
UNION ALL SELECT 'SILVER.SYMBOLS',     COUNT(*) FROM MARKET_AGENT.SILVER.SYMBOLS
UNION ALL SELECT 'SILVER.BARS',        COUNT(*) FROM MARKET_AGENT.SILVER.BARS
UNION ALL SELECT 'SILVER.TRADES',      COUNT(*) FROM MARKET_AGENT.SILVER.TRADES
UNION ALL SELECT 'SILVER.NEWS',        COUNT(*) FROM MARKET_AGENT.SILVER.NEWS
UNION ALL SELECT 'GOLD.DIM_SYMBOLS',   COUNT(*) FROM MARKET_AGENT.GOLD.DIM_SYMBOLS
UNION ALL SELECT 'GOLD.FCT_BARS',      COUNT(*) FROM MARKET_AGENT.GOLD.FCT_BARS
UNION ALL SELECT 'GOLD.FCT_TRADES',    COUNT(*) FROM MARKET_AGENT.GOLD.FCT_TRADES
ORDER BY table_name;

-- ============================================================ 2. Data quality
-- EDA-2: nulls, duplicates and time coverage in Silver bars
SELECT COUNT(*)                                             AS bars,
       COUNT(DISTINCT symbol, bar_ts)                       AS distinct_symbol_minutes,
       COUNT(*) - COUNT(DISTINCT symbol, bar_ts)            AS duplicate_bars,
       COUNT_IF(open IS NULL OR close IS NULL)              AS null_prices,
       COUNT_IF(volume IS NULL)                             AS null_volume,
       MIN(bar_ts)                                          AS first_bar_utc,
       MAX(bar_ts)                                          AS last_bar_utc
FROM MARKET_AGENT.SILVER.BARS;

-- EDA-3: OHLC rules that must always hold (expect zero violations)
SELECT COUNT_IF(high < low)                       AS high_below_low,
       COUNT_IF(high < GREATEST(open, close))     AS high_below_open_or_close,
       COUNT_IF(low  > LEAST(open, close))        AS low_above_open_or_close,
       COUNT_IF(open <= 0 OR close <= 0)          AS non_positive_prices
FROM MARKET_AGENT.SILVER.BARS;

-- EDA-4: completeness -- every symbol should have 390 one-minute bars per session
SELECT symbol, date_key, COUNT(*) AS bars, 390 - COUNT(*) AS missing_minutes
FROM MARKET_AGENT.GOLD.FCT_BARS
GROUP BY symbol, date_key
ORDER BY symbol;

-- ============================================================ 3. What the data says
-- EDA-5: per-symbol session summary (open, close, return, range, volume)
SELECT symbol,
       MIN_BY(open, bar_ts)                                                   AS session_open,
       MAX_BY(close, bar_ts)                                                  AS session_close,
       ROUND((MAX_BY(close, bar_ts) - MIN_BY(open, bar_ts))
             / MIN_BY(open, bar_ts) * 100, 3)                                 AS session_return_pct,
       MIN(low)                                                               AS session_low,
       MAX(high)                                                              AS session_high,
       ROUND((MAX(high) - MIN(low)) / MIN(low) * 100, 3)                      AS range_pct,
       SUM(volume)                                                            AS total_volume
FROM MARKET_AGENT.GOLD.FCT_BARS
GROUP BY symbol
ORDER BY session_return_pct DESC;

-- EDA-6: distribution of one-minute returns (basis points)
SELECT symbol,
       ROUND(AVG(bar_return) * 1e4, 3)                         AS mean_bps,
       ROUND(STDDEV(bar_return) * 1e4, 3)                      AS stddev_bps,
       ROUND(MIN(bar_return) * 1e4, 3)                         AS worst_bps,
       ROUND(MAX(bar_return) * 1e4, 3)                         AS best_bps,
       ROUND(APPROX_PERCENTILE(bar_return, 0.05) * 1e4, 3)     AS p05_bps,
       ROUND(APPROX_PERCENTILE(bar_return, 0.95) * 1e4, 3)     AS p95_bps
FROM MARKET_AGENT.GOLD.FCT_BARS
GROUP BY symbol
ORDER BY stddev_bps DESC;

-- EDA-7: intraday pattern -- volume and volatility by hour of the session (ET)
SELECT HOUR(CONVERT_TIMEZONE('UTC', 'America/New_York', bar_ts)) AS hour_et,
       SUM(volume)                                               AS volume,
       ROUND(AVG(rolling_volatility_30) * 1e4, 3)                AS avg_volatility_bps
FROM MARKET_AGENT.GOLD.FCT_BARS
GROUP BY hour_et
ORDER BY hour_et;

-- EDA-8: price path per symbol, every 15 minutes (for a line chart)
SELECT symbol, bar_ts, close
FROM MARKET_AGENT.GOLD.FCT_BARS
WHERE MINUTE(bar_ts) % 15 = 0
ORDER BY symbol, bar_ts;

-- EDA-9: circuit-breaker flag -- bars with a >10% one-minute move
SELECT symbol, bar_ts, open, close, ROUND(bar_return * 100, 2) AS move_pct
FROM MARKET_AGENT.GOLD.FCT_BARS
WHERE is_suspect
ORDER BY ABS(bar_return) DESC;

-- ============================================================ 4. Reconciliation
-- EDA-10: trades rebuilt into minute bars vs the vendor's bars
WITH rebuilt AS (
  SELECT symbol, DATE_TRUNC('minute', trade_ts) AS bar_ts,
         COUNT(*) AS trades, SUM(size) AS trade_volume
  FROM MARKET_AGENT.GOLD.FCT_TRADES
  GROUP BY 1, 2
)
SELECT b.symbol,
       COUNT(*)                                        AS bars,
       COUNT_IF(r.trades = b.trade_count)              AS trade_count_matches,
       COUNT_IF(r.bar_ts IS NULL)                      AS bars_without_trades
FROM MARKET_AGENT.GOLD.FCT_BARS b
LEFT JOIN rebuilt r ON r.symbol = b.symbol AND r.bar_ts = b.bar_ts
GROUP BY b.symbol
ORDER BY b.symbol;

-- EDA-11: Bronze -> Silver -> Gold reconciliation for bars
SELECT (SELECT COUNT(*) FROM MARKET_AGENT.BRONZE.RAW_BARS)                      AS bronze_rows,
       (SELECT COUNT(DISTINCT symbol, TRY_TO_TIMESTAMP_NTZ(bar_ts))
          FROM MARKET_AGENT.BRONZE.RAW_BARS)                                     AS bronze_distinct,
       (SELECT COUNT(*) FROM MARKET_AGENT.SILVER.BARS)                          AS silver_rows,
       (SELECT COUNT(*) FROM MARKET_AGENT.GOLD.FCT_BARS)                        AS gold_rows;

-- ============================================================ 5. Documents
-- EDA-12: news coverage and tone per symbol
SELECT symbols                                                   AS symbol,
       COUNT(*)                                                  AS articles,
       COUNT_IF(headline ILIKE ANY ('%beats%', '%rise%', '%record%', '%upgrade%', '%strong%')) AS positive_headlines,
       COUNT_IF(headline ILIKE ANY ('%scrutiny%', '%disruption%', '%miss%', '%downgrade%', '%cut%')) AS negative_headlines,
       MIN(published_at)                                         AS first_article,
       MAX(published_at)                                         AS last_article
FROM MARKET_AGENT.SILVER.NEWS
GROUP BY symbols
ORDER BY articles DESC;
