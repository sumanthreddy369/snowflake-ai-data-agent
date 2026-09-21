-- Step 2: Bronze — raw data lands untouched.
-- Deliberately permissive typing (VARCHAR) since Bronze should never reject a row
-- for a data-quality reason; that's Silver's job.

CREATE TABLE IF NOT EXISTS BANK_AGENT.BRONZE.RAW_TRANSACTIONS (
  transaction_id    VARCHAR,
  customer_id       VARCHAR,
  merchant_id       VARCHAR,
  transaction_ts    VARCHAR,   -- raw string; parsed/cast in Silver
  amount            VARCHAR,
  transaction_status VARCHAR,  -- e.g. APPROVED, DECLINED, REVERSED
  is_fraud          VARCHAR,   -- raw flag from the fraud model/label source
  _loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file      VARCHAR DEFAULT METADATA$FILENAME
);

CREATE TABLE IF NOT EXISTS BANK_AGENT.BRONZE.RAW_CUSTOMERS (
  customer_id       VARCHAR,
  full_name         VARCHAR,
  email             VARCHAR,
  ssn               VARCHAR,   -- sensitive; masked from Gold onward, see 07_governance
  account_open_date VARCHAR,
  region            VARCHAR,
  _loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file      VARCHAR DEFAULT METADATA$FILENAME
);

CREATE TABLE IF NOT EXISTS BANK_AGENT.BRONZE.RAW_MERCHANTS (
  merchant_id       VARCHAR,
  merchant_name     VARCHAR,
  mcc_category      VARCHAR,   -- merchant category code group, e.g. GROCERY, TRAVEL
  risk_tier         VARCHAR,   -- LOW / MEDIUM / HIGH, feeds fraud-rate breakdowns
  _loaded_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file      VARCHAR DEFAULT METADATA$FILENAME
);
