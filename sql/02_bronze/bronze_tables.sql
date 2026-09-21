-- Step 2: Bronze — raw data lands untouched.
-- Deliberately permissive typing (VARCHAR/VARIANT-ish) since Bronze should never
-- reject a row for a data-quality reason; that's Silver's job.

CREATE TABLE IF NOT EXISTS RETAIL_AGENT.BRONZE.RAW_ORDERS (
  order_id        VARCHAR,
  customer_id     VARCHAR,
  product_id      VARCHAR,
  order_ts        VARCHAR,   -- raw string; parsed/cast in Silver
  quantity        VARCHAR,
  unit_price      VARCHAR,
  order_status    VARCHAR,
  _loaded_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file    VARCHAR DEFAULT METADATA$FILENAME
);

CREATE TABLE IF NOT EXISTS RETAIL_AGENT.BRONZE.RAW_CUSTOMERS (
  customer_id     VARCHAR,
  full_name       VARCHAR,
  email           VARCHAR,
  signup_date     VARCHAR,
  region          VARCHAR,
  _loaded_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file    VARCHAR DEFAULT METADATA$FILENAME
);

CREATE TABLE IF NOT EXISTS RETAIL_AGENT.BRONZE.RAW_PRODUCTS (
  product_id      VARCHAR,
  product_name    VARCHAR,
  category        VARCHAR,
  list_price      VARCHAR,
  _loaded_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  _source_file    VARCHAR DEFAULT METADATA$FILENAME
);
