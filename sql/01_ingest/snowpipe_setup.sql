-- Step 1: Ingest — Snowpipe
-- Auto-ingests files landing in an external stage into Bronze raw tables.
-- Swap the URL/credentials for your real cloud storage location.

CREATE DATABASE IF NOT EXISTS RETAIL_AGENT;
CREATE SCHEMA IF NOT EXISTS RETAIL_AGENT.BRONZE;

CREATE FILE FORMAT IF NOT EXISTS RETAIL_AGENT.BRONZE.CSV_STANDARD
  TYPE = 'CSV'
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null');

-- Replace STORAGE_INTEGRATION and URL with your actual cloud storage setup.
CREATE STAGE IF NOT EXISTS RETAIL_AGENT.BRONZE.RAW_STAGE
  URL = 's3://<your-bucket>/raw/'
  STORAGE_INTEGRATION = <your_storage_integration>
  FILE_FORMAT = RETAIL_AGENT.BRONZE.CSV_STANDARD;

-- One pipe per source table. Each pipe auto-ingests new files matching its pattern
-- into the corresponding Bronze table (created in 02_bronze/bronze_tables.sql).

CREATE PIPE IF NOT EXISTS RETAIL_AGENT.BRONZE.ORDERS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO RETAIL_AGENT.BRONZE.RAW_ORDERS
  FROM @RETAIL_AGENT.BRONZE.RAW_STAGE/orders/
  FILE_FORMAT = RETAIL_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*orders.*[.]csv';

CREATE PIPE IF NOT EXISTS RETAIL_AGENT.BRONZE.CUSTOMERS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO RETAIL_AGENT.BRONZE.RAW_CUSTOMERS
  FROM @RETAIL_AGENT.BRONZE.RAW_STAGE/customers/
  FILE_FORMAT = RETAIL_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*customers.*[.]csv';

CREATE PIPE IF NOT EXISTS RETAIL_AGENT.BRONZE.PRODUCTS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO RETAIL_AGENT.BRONZE.RAW_PRODUCTS
  FROM @RETAIL_AGENT.BRONZE.RAW_STAGE/products/
  FILE_FORMAT = RETAIL_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*products.*[.]csv';

-- After creating each pipe, register its notification_channel (SHOW PIPES) with
-- your cloud provider's event notifications (e.g. S3 -> SQS) to trigger ingestion.
