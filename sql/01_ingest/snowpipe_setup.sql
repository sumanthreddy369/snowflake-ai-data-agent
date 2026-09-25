-- Step 1: Ingest — batch/backfill path, on Google Cloud Storage.
-- Live trades and bars arrive via streaming/ (Alpaca websocket -> Kafka ->
-- Snowpipe Streaming, see streaming/README.md). This file covers the batch
-- complement: backfilling historical bars (streaming/backfill_historical.py)
-- and the symbol reference table, which don't need to be real-time.
--
-- GCS chosen deliberately over S3 to diversify cloud experience: Snowflake's
-- GCS storage integration works identically in shape to its S3 one (a
-- STORAGE_INTEGRATION object plus a stage), but auth goes through a
-- Snowflake-managed GCP service account instead of an AWS IAM role — see
-- https://docs.snowflake.com/en/user-guide/data-load-gcs-config

CREATE FILE FORMAT IF NOT EXISTS MARKET_AGENT.BRONZE.CSV_STANDARD
  TYPE = 'CSV'
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null');

-- Create the GCS bucket first (e.g. gsutil mb gs://<your-bucket>), then this
-- integration. After creating it, run DESC STORAGE INTEGRATION and grant the
-- STORAGE_GCP_SERVICE_ACCOUNT it returns read access on the bucket in GCP IAM.
CREATE STORAGE INTEGRATION IF NOT EXISTS MARKET_AGENT_GCS_INT
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = GCS
  ENABLED = TRUE
  STORAGE_ALLOWED_LOCATIONS = ('gcs://<your-bucket>/raw/');

CREATE STAGE IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_STAGE
  URL = 'gcs://<your-bucket>/raw/'
  STORAGE_INTEGRATION = MARKET_AGENT_GCS_INT
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD;

-- Symbol reference data (from streaming/backfill_historical.py, which pulls
-- Alpaca's /v2/assets REST endpoint) rarely changes intraday, so it's loaded
-- as a batch file rather than streamed.
CREATE PIPE IF NOT EXISTS MARKET_AGENT.BRONZE.SYMBOLS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO MARKET_AGENT.BRONZE.RAW_SYMBOLS
  FROM @MARKET_AGENT.BRONZE.RAW_STAGE/symbols/
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*symbols.*[.]csv';

-- Historical daily/minute bars (from streaming/backfill_historical.py) for
-- backfilling history before the live feed started.
CREATE PIPE IF NOT EXISTS MARKET_AGENT.BRONZE.BARS_BACKFILL_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO MARKET_AGENT.BRONZE.RAW_BARS
  FROM @MARKET_AGENT.BRONZE.RAW_STAGE/bars_backfill/
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*bars.*[.]csv';

-- After creating each pipe, register its notification_channel (SHOW PIPES)
-- with a GCS Pub/Sub notification on the bucket to trigger ingestion —
-- see https://docs.snowflake.com/en/user-guide/data-load-snowpipe-auto-gcs
