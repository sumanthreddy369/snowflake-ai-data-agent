-- Step 2: Bronze — raw data lands untouched.
-- Domain: real-time equities market data (Alpaca IEX feed: trades + minute bars),
-- plus a reference table of the symbols being tracked.
-- Deliberately permissive typing (VARCHAR) since Bronze should never reject a row
-- for a data-quality reason; that's Silver's job.

CREATE DATABASE IF NOT EXISTS MARKET_AGENT;
CREATE SCHEMA IF NOT EXISTS MARKET_AGENT.BRONZE;

CREATE TABLE IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_TRADES (
  trade_id          VARCHAR,
  symbol            VARCHAR,
  price             VARCHAR,
  size              VARCHAR,
  exchange_code     VARCHAR,   -- e.g. "V" = IEX
  conditions        VARCHAR,   -- raw trade condition codes, comma-joined
  trade_ts          VARCHAR,   -- raw ISO8601 string; parsed/cast in Silver
  _loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file      VARCHAR DEFAULT METADATA$FILENAME
);

CREATE TABLE IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_BARS (
  symbol            VARCHAR,
  bar_ts            VARCHAR,   -- start of the 1-minute bar, raw ISO8601 string
  open              VARCHAR,
  high              VARCHAR,
  low               VARCHAR,
  close             VARCHAR,
  volume            VARCHAR,
  vwap              VARCHAR,
  trade_count       VARCHAR,
  _loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file      VARCHAR DEFAULT METADATA$FILENAME
);

CREATE TABLE IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_SYMBOLS (
  symbol            VARCHAR,
  company_name      VARCHAR,
  sector            VARCHAR,
  exchange          VARCHAR,
  is_active         VARCHAR,
  _loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file      VARCHAR DEFAULT METADATA$FILENAME
);
