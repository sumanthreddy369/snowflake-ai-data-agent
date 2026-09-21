-- Step 3: Silver — clean, dedupe, standardize via Streams + Tasks.
-- A Stream tracks what changed in Bronze since it was last consumed; a Task on a
-- schedule MERGEs those changes into Silver with type casting, dedupe, and
-- standardization applied.

CREATE SCHEMA IF NOT EXISTS BANK_AGENT.SILVER;

CREATE TABLE IF NOT EXISTS BANK_AGENT.SILVER.TRANSACTIONS (
  transaction_id      VARCHAR PRIMARY KEY,
  customer_id         VARCHAR NOT NULL,
  merchant_id         VARCHAR NOT NULL,
  transaction_ts      TIMESTAMP_NTZ,
  amount              NUMBER(12, 2),
  transaction_status  VARCHAR,
  is_fraud            BOOLEAN,
  _updated_at         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS BANK_AGENT.SILVER.CUSTOMERS (
  customer_id         VARCHAR PRIMARY KEY,
  full_name           VARCHAR,
  email               VARCHAR,
  ssn                 VARCHAR,
  account_open_date   DATE,
  region              VARCHAR,
  _updated_at         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS BANK_AGENT.SILVER.MERCHANTS (
  merchant_id         VARCHAR PRIMARY KEY,
  merchant_name       VARCHAR,
  mcc_category        VARCHAR,
  risk_tier           VARCHAR,
  _updated_at         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Streams: one per Bronze table, capturing inserts since last consumed.
CREATE STREAM IF NOT EXISTS BANK_AGENT.BRONZE.RAW_TRANSACTIONS_STREAM
  ON TABLE BANK_AGENT.BRONZE.RAW_TRANSACTIONS;

CREATE STREAM IF NOT EXISTS BANK_AGENT.BRONZE.RAW_CUSTOMERS_STREAM
  ON TABLE BANK_AGENT.BRONZE.RAW_CUSTOMERS;

CREATE STREAM IF NOT EXISTS BANK_AGENT.BRONZE.RAW_MERCHANTS_STREAM
  ON TABLE BANK_AGENT.BRONZE.RAW_MERCHANTS;

-- Tasks: dedupe by taking the latest row per natural key (QUALIFY + ROW_NUMBER),
-- cast types, and MERGE into Silver.

CREATE TASK IF NOT EXISTS BANK_AGENT.SILVER.MERGE_TRANSACTIONS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('BANK_AGENT.BRONZE.RAW_TRANSACTIONS_STREAM')
AS
MERGE INTO BANK_AGENT.SILVER.TRANSACTIONS AS tgt
USING (
  SELECT
    transaction_id,
    customer_id,
    merchant_id,
    TRY_TO_TIMESTAMP_NTZ(transaction_ts) AS transaction_ts,
    TRY_TO_DECIMAL(amount, 12, 2) AS amount,
    UPPER(TRIM(transaction_status)) AS transaction_status,
    IFF(LOWER(TRIM(is_fraud)) IN ('true', '1', 'yes'), TRUE, FALSE) AS is_fraud
  FROM BANK_AGENT.BRONZE.RAW_TRANSACTIONS_STREAM
  WHERE transaction_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY transaction_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.transaction_id = src.transaction_id
WHEN MATCHED THEN UPDATE SET
  customer_id = src.customer_id, merchant_id = src.merchant_id, transaction_ts = src.transaction_ts,
  amount = src.amount, transaction_status = src.transaction_status, is_fraud = src.is_fraud,
  _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (transaction_id, customer_id, merchant_id, transaction_ts, amount, transaction_status, is_fraud)
  VALUES (src.transaction_id, src.customer_id, src.merchant_id, src.transaction_ts, src.amount, src.transaction_status, src.is_fraud);

CREATE TASK IF NOT EXISTS BANK_AGENT.SILVER.MERGE_CUSTOMERS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('BANK_AGENT.BRONZE.RAW_CUSTOMERS_STREAM')
AS
MERGE INTO BANK_AGENT.SILVER.CUSTOMERS AS tgt
USING (
  SELECT
    customer_id,
    TRIM(full_name) AS full_name,
    LOWER(TRIM(email)) AS email,
    REGEXP_REPLACE(ssn, '[^0-9]', '') AS ssn,
    TRY_TO_DATE(account_open_date) AS account_open_date,
    INITCAP(TRIM(region)) AS region
  FROM BANK_AGENT.BRONZE.RAW_CUSTOMERS_STREAM
  WHERE customer_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.customer_id = src.customer_id
WHEN MATCHED THEN UPDATE SET
  full_name = src.full_name, email = src.email, ssn = src.ssn,
  account_open_date = src.account_open_date, region = src.region, _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (customer_id, full_name, email, ssn, account_open_date, region)
  VALUES (src.customer_id, src.full_name, src.email, src.ssn, src.account_open_date, src.region);

CREATE TASK IF NOT EXISTS BANK_AGENT.SILVER.MERGE_MERCHANTS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('BANK_AGENT.BRONZE.RAW_MERCHANTS_STREAM')
AS
MERGE INTO BANK_AGENT.SILVER.MERCHANTS AS tgt
USING (
  SELECT
    merchant_id,
    TRIM(merchant_name) AS merchant_name,
    UPPER(TRIM(mcc_category)) AS mcc_category,
    UPPER(TRIM(risk_tier)) AS risk_tier
  FROM BANK_AGENT.BRONZE.RAW_MERCHANTS_STREAM
  WHERE merchant_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY merchant_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.merchant_id = src.merchant_id
WHEN MATCHED THEN UPDATE SET
  merchant_name = src.merchant_name, mcc_category = src.mcc_category, risk_tier = src.risk_tier,
  _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (merchant_id, merchant_name, mcc_category, risk_tier)
  VALUES (src.merchant_id, src.merchant_name, src.mcc_category, src.risk_tier);

-- Tasks are created suspended by default; resume them once you've verified logic.
ALTER TASK BANK_AGENT.SILVER.MERGE_TRANSACTIONS_TASK RESUME;
ALTER TASK BANK_AGENT.SILVER.MERGE_CUSTOMERS_TASK RESUME;
ALTER TASK BANK_AGENT.SILVER.MERGE_MERCHANTS_TASK RESUME;
