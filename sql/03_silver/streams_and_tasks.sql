-- Step 3: Silver — clean, dedupe, standardize via Streams + Tasks.
-- A Stream tracks what changed in Bronze since it was last consumed; a Task on a
-- schedule MERGEs those changes into Silver with type casting, dedupe, and
-- standardization applied.

CREATE SCHEMA IF NOT EXISTS MARKET_AGENT.SILVER;

CREATE TABLE IF NOT EXISTS MARKET_AGENT.SILVER.TRADES (
  trade_id          VARCHAR PRIMARY KEY,
  symbol            VARCHAR NOT NULL,
  price             NUMBER(12, 4),
  size              NUMBER,
  exchange_code     VARCHAR,
  conditions        VARCHAR,
  trade_ts          TIMESTAMP_NTZ,
  _updated_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS MARKET_AGENT.SILVER.BARS (
  symbol            VARCHAR NOT NULL,
  bar_ts            TIMESTAMP_NTZ NOT NULL,
  open              NUMBER(12, 4),
  high              NUMBER(12, 4),
  low               NUMBER(12, 4),
  close             NUMBER(12, 4),
  volume            NUMBER,
  vwap              NUMBER(12, 4),
  trade_count       NUMBER,
  _updated_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  PRIMARY KEY (symbol, bar_ts)
);

CREATE TABLE IF NOT EXISTS MARKET_AGENT.SILVER.SYMBOLS (
  symbol            VARCHAR PRIMARY KEY,
  company_name      VARCHAR,
  sector            VARCHAR,
  exchange          VARCHAR,
  is_active         BOOLEAN,
  _updated_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Streams: one per Bronze table, capturing inserts since last consumed.
CREATE STREAM IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_TRADES_STREAM
  ON TABLE MARKET_AGENT.BRONZE.RAW_TRADES;

CREATE STREAM IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_BARS_STREAM
  ON TABLE MARKET_AGENT.BRONZE.RAW_BARS;

CREATE STREAM IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_SYMBOLS_STREAM
  ON TABLE MARKET_AGENT.BRONZE.RAW_SYMBOLS;

-- Tasks: dedupe by taking the latest row per natural key (QUALIFY + ROW_NUMBER),
-- cast types, and MERGE into Silver. Trades and bars run on a short interval
-- since they're the real-time path; symbols run less often since it's reference
-- data backfilled in batch.

CREATE TASK IF NOT EXISTS MARKET_AGENT.SILVER.MERGE_TRADES_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */1 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('MARKET_AGENT.BRONZE.RAW_TRADES_STREAM')
AS
MERGE INTO MARKET_AGENT.SILVER.TRADES AS tgt
USING (
  SELECT
    trade_id,
    symbol,
    TRY_TO_DECIMAL(price, 12, 4) AS price,
    TRY_TO_NUMBER(size) AS size,
    exchange_code,
    conditions,
    TRY_TO_TIMESTAMP_NTZ(trade_ts) AS trade_ts
  FROM MARKET_AGENT.BRONZE.RAW_TRADES_STREAM
  WHERE trade_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY trade_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.trade_id = src.trade_id
WHEN MATCHED THEN UPDATE SET
  symbol = src.symbol, price = src.price, size = src.size, exchange_code = src.exchange_code,
  conditions = src.conditions, trade_ts = src.trade_ts, _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (trade_id, symbol, price, size, exchange_code, conditions, trade_ts)
  VALUES (src.trade_id, src.symbol, src.price, src.size, src.exchange_code, src.conditions, src.trade_ts);

CREATE TASK IF NOT EXISTS MARKET_AGENT.SILVER.MERGE_BARS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */1 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('MARKET_AGENT.BRONZE.RAW_BARS_STREAM')
AS
MERGE INTO MARKET_AGENT.SILVER.BARS AS tgt
USING (
  SELECT
    symbol,
    TRY_TO_TIMESTAMP_NTZ(bar_ts) AS bar_ts,
    TRY_TO_DECIMAL(open, 12, 4) AS open,
    TRY_TO_DECIMAL(high, 12, 4) AS high,
    TRY_TO_DECIMAL(low, 12, 4) AS low,
    TRY_TO_DECIMAL(close, 12, 4) AS close,
    TRY_TO_NUMBER(volume) AS volume,
    TRY_TO_DECIMAL(vwap, 12, 4) AS vwap,
    TRY_TO_NUMBER(trade_count) AS trade_count
  FROM MARKET_AGENT.BRONZE.RAW_BARS_STREAM
  WHERE symbol IS NOT NULL AND bar_ts IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol, bar_ts ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.symbol = src.symbol AND tgt.bar_ts = src.bar_ts
WHEN MATCHED THEN UPDATE SET
  open = src.open, high = src.high, low = src.low, close = src.close, volume = src.volume,
  vwap = src.vwap, trade_count = src.trade_count, _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (symbol, bar_ts, open, high, low, close, volume, vwap, trade_count)
  VALUES (src.symbol, src.bar_ts, src.open, src.high, src.low, src.close, src.volume, src.vwap, src.trade_count);

CREATE TASK IF NOT EXISTS MARKET_AGENT.SILVER.MERGE_SYMBOLS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('MARKET_AGENT.BRONZE.RAW_SYMBOLS_STREAM')
AS
MERGE INTO MARKET_AGENT.SILVER.SYMBOLS AS tgt
USING (
  SELECT
    symbol,
    TRIM(company_name) AS company_name,
    INITCAP(TRIM(sector)) AS sector,
    UPPER(TRIM(exchange)) AS exchange,
    IFF(LOWER(TRIM(is_active)) IN ('true', '1', 'yes', 'active'), TRUE, FALSE) AS is_active
  FROM MARKET_AGENT.BRONZE.RAW_SYMBOLS_STREAM
  WHERE symbol IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.symbol = src.symbol
WHEN MATCHED THEN UPDATE SET
  company_name = src.company_name, sector = src.sector, exchange = src.exchange,
  is_active = src.is_active, _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (symbol, company_name, sector, exchange, is_active)
  VALUES (src.symbol, src.company_name, src.sector, src.exchange, src.is_active);

-- Tasks are created suspended by default; resume them once you've verified logic.
ALTER TASK MARKET_AGENT.SILVER.MERGE_TRADES_TASK RESUME;
ALTER TASK MARKET_AGENT.SILVER.MERGE_BARS_TASK RESUME;
ALTER TASK MARKET_AGENT.SILVER.MERGE_SYMBOLS_TASK RESUME;
