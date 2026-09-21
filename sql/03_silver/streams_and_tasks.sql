-- Step 3: Silver — clean, dedupe, standardize via Streams + Tasks.
-- A Stream tracks what changed in Bronze since it was last consumed; a Task on a
-- schedule MERGEs those changes into Silver with type casting, dedupe, and
-- standardization applied.

CREATE SCHEMA IF NOT EXISTS RETAIL_AGENT.SILVER;

CREATE TABLE IF NOT EXISTS RETAIL_AGENT.SILVER.ORDERS (
  order_id        VARCHAR PRIMARY KEY,
  customer_id     VARCHAR NOT NULL,
  product_id      VARCHAR NOT NULL,
  order_ts        TIMESTAMP_NTZ,
  quantity        NUMBER,
  unit_price      NUMBER(10, 2),
  order_status    VARCHAR,
  _updated_at     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS RETAIL_AGENT.SILVER.CUSTOMERS (
  customer_id     VARCHAR PRIMARY KEY,
  full_name       VARCHAR,
  email           VARCHAR,
  signup_date     DATE,
  region          VARCHAR,
  _updated_at     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS RETAIL_AGENT.SILVER.PRODUCTS (
  product_id      VARCHAR PRIMARY KEY,
  product_name    VARCHAR,
  category        VARCHAR,
  list_price      NUMBER(10, 2),
  _updated_at     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Streams: one per Bronze table, capturing inserts since last consumed.
CREATE STREAM IF NOT EXISTS RETAIL_AGENT.BRONZE.RAW_ORDERS_STREAM
  ON TABLE RETAIL_AGENT.BRONZE.RAW_ORDERS;

CREATE STREAM IF NOT EXISTS RETAIL_AGENT.BRONZE.RAW_CUSTOMERS_STREAM
  ON TABLE RETAIL_AGENT.BRONZE.RAW_CUSTOMERS;

CREATE STREAM IF NOT EXISTS RETAIL_AGENT.BRONZE.RAW_PRODUCTS_STREAM
  ON TABLE RETAIL_AGENT.BRONZE.RAW_PRODUCTS;

-- Tasks: dedupe by taking the latest row per natural key (QUALIFY + ROW_NUMBER),
-- cast types, and MERGE into Silver. Root task drives the schedule; downstream
-- tasks fire in sequence via AFTER so a single ingest wave flows through cleanly.

CREATE TASK IF NOT EXISTS RETAIL_AGENT.SILVER.MERGE_ORDERS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('RETAIL_AGENT.BRONZE.RAW_ORDERS_STREAM')
AS
MERGE INTO RETAIL_AGENT.SILVER.ORDERS AS tgt
USING (
  SELECT
    order_id,
    customer_id,
    product_id,
    TRY_TO_TIMESTAMP_NTZ(order_ts) AS order_ts,
    TRY_TO_NUMBER(quantity) AS quantity,
    TRY_TO_DECIMAL(unit_price, 10, 2) AS unit_price,
    UPPER(TRIM(order_status)) AS order_status
  FROM RETAIL_AGENT.BRONZE.RAW_ORDERS_STREAM
  WHERE order_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.order_id = src.order_id
WHEN MATCHED THEN UPDATE SET
  customer_id = src.customer_id, product_id = src.product_id, order_ts = src.order_ts,
  quantity = src.quantity, unit_price = src.unit_price, order_status = src.order_status,
  _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (order_id, customer_id, product_id, order_ts, quantity, unit_price, order_status)
  VALUES (src.order_id, src.customer_id, src.product_id, src.order_ts, src.quantity, src.unit_price, src.order_status);

CREATE TASK IF NOT EXISTS RETAIL_AGENT.SILVER.MERGE_CUSTOMERS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('RETAIL_AGENT.BRONZE.RAW_CUSTOMERS_STREAM')
AS
MERGE INTO RETAIL_AGENT.SILVER.CUSTOMERS AS tgt
USING (
  SELECT
    customer_id,
    TRIM(full_name) AS full_name,
    LOWER(TRIM(email)) AS email,
    TRY_TO_DATE(signup_date) AS signup_date,
    INITCAP(TRIM(region)) AS region
  FROM RETAIL_AGENT.BRONZE.RAW_CUSTOMERS_STREAM
  WHERE customer_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.customer_id = src.customer_id
WHEN MATCHED THEN UPDATE SET
  full_name = src.full_name, email = src.email, signup_date = src.signup_date,
  region = src.region, _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (customer_id, full_name, email, signup_date, region)
  VALUES (src.customer_id, src.full_name, src.email, src.signup_date, src.region);

CREATE TASK IF NOT EXISTS RETAIL_AGENT.SILVER.MERGE_PRODUCTS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('RETAIL_AGENT.BRONZE.RAW_PRODUCTS_STREAM')
AS
MERGE INTO RETAIL_AGENT.SILVER.PRODUCTS AS tgt
USING (
  SELECT
    product_id,
    TRIM(product_name) AS product_name,
    INITCAP(TRIM(category)) AS category,
    TRY_TO_DECIMAL(list_price, 10, 2) AS list_price
  FROM RETAIL_AGENT.BRONZE.RAW_PRODUCTS_STREAM
  WHERE product_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.product_id = src.product_id
WHEN MATCHED THEN UPDATE SET
  product_name = src.product_name, category = src.category, list_price = src.list_price,
  _updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT
  (product_id, product_name, category, list_price)
  VALUES (src.product_id, src.product_name, src.category, src.list_price);

-- Tasks are created suspended by default; resume them once you've verified logic.
ALTER TASK RETAIL_AGENT.SILVER.MERGE_ORDERS_TASK RESUME;
ALTER TASK RETAIL_AGENT.SILVER.MERGE_CUSTOMERS_TASK RESUME;
ALTER TASK RETAIL_AGENT.SILVER.MERGE_PRODUCTS_TASK RESUME;
