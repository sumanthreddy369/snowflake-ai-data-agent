-- Step 1: Ingest — Snowpipe
-- Auto-ingests files landing in an external stage into Bronze raw tables.
-- Swap the URL/credentials for your real cloud storage location.
-- Domain: bank card transactions, account holders, and merchants.

CREATE DATABASE IF NOT EXISTS BANK_AGENT;
CREATE SCHEMA IF NOT EXISTS BANK_AGENT.BRONZE;

CREATE FILE FORMAT IF NOT EXISTS BANK_AGENT.BRONZE.CSV_STANDARD
  TYPE = 'CSV'
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null');

-- Replace STORAGE_INTEGRATION and URL with your actual cloud storage setup.
CREATE STAGE IF NOT EXISTS BANK_AGENT.BRONZE.RAW_STAGE
  URL = 's3://<your-bucket>/raw/'
  STORAGE_INTEGRATION = <your_storage_integration>
  FILE_FORMAT = BANK_AGENT.BRONZE.CSV_STANDARD;

-- One pipe per source table. Each pipe auto-ingests new files matching its pattern
-- into the corresponding Bronze table (created in 02_bronze/bronze_tables.sql).

CREATE PIPE IF NOT EXISTS BANK_AGENT.BRONZE.TRANSACTIONS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO BANK_AGENT.BRONZE.RAW_TRANSACTIONS
  FROM @BANK_AGENT.BRONZE.RAW_STAGE/transactions/
  FILE_FORMAT = BANK_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*transactions.*[.]csv';

CREATE PIPE IF NOT EXISTS BANK_AGENT.BRONZE.CUSTOMERS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO BANK_AGENT.BRONZE.RAW_CUSTOMERS
  FROM @BANK_AGENT.BRONZE.RAW_STAGE/customers/
  FILE_FORMAT = BANK_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*customers.*[.]csv';

CREATE PIPE IF NOT EXISTS BANK_AGENT.BRONZE.MERCHANTS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO BANK_AGENT.BRONZE.RAW_MERCHANTS
  FROM @BANK_AGENT.BRONZE.RAW_STAGE/merchants/
  FILE_FORMAT = BANK_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*merchants.*[.]csv';

-- After creating each pipe, register its notification_channel (SHOW PIPES) with
-- your cloud provider's event notifications (e.g. S3 -> SQS) to trigger ingestion.
