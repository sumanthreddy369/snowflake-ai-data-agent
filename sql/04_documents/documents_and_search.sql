-- Step 4b: Documents + Cortex Search -- the RAG branch of the pipeline.
-- Runs in parallel to the structured trades/bars branch (Bronze/Silver here
-- mirror sql/02_bronze and sql/03_silver's pattern exactly), and feeds
-- Cortex Search instead of dbt/Gold, since Cortex Search indexes text
-- directly rather than joining star-schema tables.

CREATE SCHEMA IF NOT EXISTS MARKET_AGENT.BRONZE;  -- no-op if already created by 02_bronze

CREATE TABLE IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_NEWS (
  news_id       VARCHAR,
  headline      VARCHAR,
  summary       VARCHAR,
  content       VARCHAR,
  symbols       VARCHAR,   -- comma-joined tickers this article mentions
  source        VARCHAR,
  url           VARCHAR,
  published_at  VARCHAR,   -- raw string; parsed/cast in Silver
  _loaded_at    TIMESTAMP_NTZ DEFAULT SYSDATE(),
  _source_file  VARCHAR DEFAULT METADATA$FILENAME
);

CREATE TABLE IF NOT EXISTS MARKET_AGENT.SILVER.NEWS (
  news_id       VARCHAR PRIMARY KEY,
  headline      VARCHAR,
  summary       VARCHAR,
  content       VARCHAR,
  symbols       VARCHAR,
  source        VARCHAR,
  url           VARCHAR,
  published_at  TIMESTAMP_NTZ,
  _updated_at   TIMESTAMP_NTZ DEFAULT SYSDATE()
);

CREATE STREAM IF NOT EXISTS MARKET_AGENT.BRONZE.RAW_NEWS_STREAM
  ON TABLE MARKET_AGENT.BRONZE.RAW_NEWS;

CREATE TASK IF NOT EXISTS MARKET_AGENT.SILVER.MERGE_NEWS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON */15 * * * * UTC'
  WHEN SYSTEM$STREAM_HAS_DATA('MARKET_AGENT.BRONZE.RAW_NEWS_STREAM')
AS
MERGE INTO MARKET_AGENT.SILVER.NEWS AS tgt
USING (
  SELECT
    news_id, headline, summary, content, symbols, source, url,
    TRY_TO_TIMESTAMP_NTZ(published_at) AS published_at
  FROM MARKET_AGENT.BRONZE.RAW_NEWS_STREAM
  WHERE news_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY news_id ORDER BY _loaded_at DESC) = 1
) AS src
ON tgt.news_id = src.news_id
WHEN MATCHED THEN UPDATE SET
  headline = src.headline, summary = src.summary, content = src.content,
  symbols = src.symbols, source = src.source, url = src.url,
  published_at = src.published_at, _updated_at = SYSDATE()
WHEN NOT MATCHED THEN INSERT
  (news_id, headline, summary, content, symbols, source, url, published_at)
  VALUES (src.news_id, src.headline, src.summary, src.content, src.symbols, src.source, src.url, src.published_at);

ALTER TASK MARKET_AGENT.SILVER.MERGE_NEWS_TASK RESUME;

-- Cortex Search indexes `content` for semantic retrieval, and carries
-- `symbols`, `source`, `url`, `published_at` as filterable attributes so the
-- agent can answer "what's the recent news on AAPL" and cite a real URL.
-- TARGET_LAG controls how fresh the index is relative to Silver -- 1 hour is
-- reasonable for news (unlike prices, headlines don't need <1min freshness).
CREATE CORTEX SEARCH SERVICE IF NOT EXISTS MARKET_AGENT.SILVER.NEWS_SEARCH_SERVICE
  ON content
  ATTRIBUTES symbols, source, url, published_at, headline
  WAREHOUSE = COMPUTE_WH
  TARGET_LAG = '1 hour'
  EMBEDDING_MODEL = 'snowflake-arctic-embed-l-v2.0'
  AS (
    SELECT content, symbols, source, url, published_at, headline
    FROM MARKET_AGENT.SILVER.NEWS
  );
