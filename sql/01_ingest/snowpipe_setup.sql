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

-- The bucket, Pub/Sub topic + subscription, and the GCP IAM grants for
-- Snowflake's service accounts are created by infra/terraform, which also
-- creates both integrations below. They're repeated here with IF NOT EXISTS
-- so this file still runs on an account set up without Terraform -- in that
-- case, create the GCP side by hand and grant the service accounts that
-- DESC STORAGE INTEGRATION / DESC NOTIFICATION INTEGRATION return.
CREATE STORAGE INTEGRATION IF NOT EXISTS MARKET_AGENT_GCS_INT
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = GCS
  ENABLED = TRUE
  STORAGE_ALLOWED_LOCATIONS = ('gcs://<your-bucket>/raw/');

-- On GCS (unlike S3) AUTO_INGEST pipes don't get their own queue: Snowpipe
-- reads object-created events from a Pub/Sub subscription through this
-- integration, and every pipe below must name it.
CREATE NOTIFICATION INTEGRATION IF NOT EXISTS MARKET_AGENT_GCS_NOTIFY_INT
  TYPE = QUEUE
  NOTIFICATION_PROVIDER = GCP_PUBSUB
  ENABLED = TRUE
  GCP_PUBSUB_SUBSCRIPTION_NAME = 'projects/<your-gcp-project>/subscriptions/<your-bucket>-snowpipe';

CREATE STAGE IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_STAGE
  URL = 'gcs://<your-bucket>/raw/'
  STORAGE_INTEGRATION = MARKET_AGENT_GCS_INT
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD;

-- Symbol reference data (from streaming/backfill_historical.py, which pulls
-- Alpaca's /v2/assets REST endpoint) rarely changes intraday, so it's loaded
-- as a batch file rather than streamed.
CREATE PIPE IF NOT EXISTS MARKET_AGENT.BRONZE.SYMBOLS_PIPE
  AUTO_INGEST = TRUE
  INTEGRATION = 'MARKET_AGENT_GCS_NOTIFY_INT'
  AS
  COPY INTO MARKET_AGENT.BRONZE.RAW_SYMBOLS
  FROM @MARKET_AGENT.BRONZE.RAW_STAGE/symbols/
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*symbols.*[.]csv';

-- Historical daily/minute bars (from streaming/backfill_historical.py) for
-- backfilling history before the live feed started.
CREATE PIPE IF NOT EXISTS MARKET_AGENT.BRONZE.BARS_BACKFILL_PIPE
  AUTO_INGEST = TRUE
  INTEGRATION = 'MARKET_AGENT_GCS_NOTIFY_INT'
  AS
  COPY INTO MARKET_AGENT.BRONZE.RAW_BARS
  FROM @MARKET_AGENT.BRONZE.RAW_STAGE/bars_backfill/
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*bars.*[.]csv';

-- News documents (from streaming/backfill_news.py or streaming/generate_sample_news.py)
-- feeding the RAG branch -- see sql/04_documents/documents_and_search.sql.
CREATE PIPE IF NOT EXISTS MARKET_AGENT.BRONZE.NEWS_PIPE
  AUTO_INGEST = TRUE
  INTEGRATION = 'MARKET_AGENT_GCS_NOTIFY_INT'
  AS
  COPY INTO MARKET_AGENT.BRONZE.RAW_NEWS
  FROM @MARKET_AGENT.BRONZE.RAW_STAGE/news/
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*news.*[.]csv';

-- No per-pipe registration step on GCS: the bucket's Pub/Sub notification
-- (infra/terraform/gcp.tf) feeds the subscription named in
-- MARKET_AGENT_GCS_NOTIFY_INT, and each pipe picks up events for its own path.
-- See https://docs.snowflake.com/en/user-guide/data-load-snowpipe-auto-gcs
--
-- Run order: this file references BRONZE.CSV_STANDARD's schema and the RAW_*
-- tables, so it runs after sql/02_bronze and sql/04_documents (RAW_NEWS),
-- despite its 01 prefix -- see README "Building and running".
