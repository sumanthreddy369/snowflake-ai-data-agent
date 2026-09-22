-- Step 1: Ingest — batch/backfill path.
-- Live trades and bars arrive via streaming/ (Alpaca websocket -> Kafka ->
-- Snowpipe Streaming, see streaming/README.md). This file covers the batch
-- complement: backfilling historical daily bars and the symbol reference table,
-- which don't need to be real-time.

CREATE FILE FORMAT IF NOT EXISTS MARKET_AGENT.BRONZE.CSV_STANDARD
  TYPE = 'CSV'
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  SKIP_HEADER = 1
  NULL_IF = ('', 'NULL', 'null');

-- Replace STORAGE_INTEGRATION and URL with your actual cloud storage setup.
CREATE STAGE IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_STAGE
  URL = 's3://<your-bucket>/raw/'
  STORAGE_INTEGRATION = <your_storage_integration>
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD;

-- Symbol reference data (from Alpaca's /v2/assets REST endpoint, exported to
-- CSV) rarely changes intraday, so it's loaded as a batch file rather than
-- streamed.
CREATE PIPE IF NOT EXISTS MARKET_AGENT.BRONZE.SYMBOLS_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO MARKET_AGENT.BRONZE.RAW_SYMBOLS
  FROM @MARKET_AGENT.BRONZE.RAW_STAGE/symbols/
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*symbols.*[.]csv';

-- Historical daily/minute bars (from Alpaca's /v2/stocks/bars REST endpoint,
-- exported to CSV) for backfilling history before the live feed started.
CREATE PIPE IF NOT EXISTS MARKET_AGENT.BRONZE.BARS_BACKFILL_PIPE
  AUTO_INGEST = TRUE
  AS
  COPY INTO MARKET_AGENT.BRONZE.RAW_BARS
  FROM @MARKET_AGENT.BRONZE.RAW_STAGE/bars_backfill/
  FILE_FORMAT = MARKET_AGENT.BRONZE.CSV_STANDARD
  PATTERN = '.*bars.*[.]csv';

-- After creating each pipe, register its notification_channel (SHOW PIPES) with
-- your cloud provider's event notifications (e.g. S3 -> SQS) to trigger ingestion.
