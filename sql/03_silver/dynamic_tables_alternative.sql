-- Alternative pattern, NOT used in the main pipeline -- shown for breadth.
--
-- streams_and_tasks.sql builds Silver with the manual CDC pattern (a Stream
-- to see what changed, a Task to MERGE it) because that's more explicit
-- about the underlying mechanics -- useful to demonstrate you understand CDC,
-- not just that you can call an API. Dynamic Tables are Snowflake's newer,
-- declarative alternative: you write the target SELECT and a freshness
-- target, and Snowflake figures out the incremental refresh plan itself.
--
-- Neither is "more correct." Dynamic Tables trade control (you can't easily
-- customize the merge/dedupe logic the way MERGE INTO lets you) for less
-- code and no Stream/Task objects to manage. This file reimplements the
-- SYMBOLS table (the simplest of the three Silver tables -- no dedupe-by-
-- latest-timestamp logic needed) as a Dynamic Table, so both patterns exist
-- side by side for comparison.

CREATE OR REPLACE DYNAMIC TABLE MARKET_AGENT.SILVER.SYMBOLS_DT
  TARGET_LAG = '15 minutes'
  WAREHOUSE = COMPUTE_WH
  COMMENT = 'Same output as SILVER.SYMBOLS, built declaratively instead of via Stream+Task -- see this file''s header comment.'
AS
SELECT
  symbol,
  TRIM(company_name) AS company_name,
  INITCAP(TRIM(sector)) AS sector,
  UPPER(TRIM(exchange)) AS exchange,
  IFF(LOWER(TRIM(is_active)) IN ('true', '1', 'yes', 'active'), TRUE, FALSE) AS is_active
FROM MARKET_AGENT.BRONZE.RAW_SYMBOLS
QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY _loaded_at DESC) = 1;
