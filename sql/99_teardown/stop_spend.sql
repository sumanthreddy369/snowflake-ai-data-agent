-- Stop-spend controls for a trial (or any) account. Run as ACCOUNTADMIN.
-- Three levels, from gentle to final. Running the whole file applies levels
-- 0 and 1 only; level 2 is commented out on purpose because it deletes data.
--
-- A trial account with no payment method is suspended (not billed) when the
-- trial ends. These controls protect the trial credits themselves from being
-- used up early by something left running.

-- ============================================================ LEVEL 0: CAP
-- Run once, first. Caps ALL warehouse spend in the account per month:
-- notify at 80%, hard-stop every warehouse at 100%.
-- Limit: resource monitors cover warehouses only. Serverless features
-- (Cortex Analyst/Search/Agents, Snowpipe, serverless tasks) are not capped
-- by this -- level 1 below stops those.
CREATE RESOURCE MONITOR IF NOT EXISTS TRIAL_SPEND_CAP
  WITH CREDIT_QUOTA = 50
  FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS
    ON 80 PERCENT DO NOTIFY
    ON 100 PERCENT DO SUSPEND_IMMEDIATE;

ALTER ACCOUNT SET RESOURCE_MONITOR = TRIAL_SPEND_CAP;

-- Warehouses suspend themselves after 60 idle seconds.
ALTER WAREHOUSE IF EXISTS COMPUTE_WH SET AUTO_SUSPEND = 60;
ALTER WAREHOUSE IF EXISTS ANALYST_WH SET AUTO_SUSPEND = 60;

-- ============================================================ LEVEL 1: PAUSE
-- Stops everything that runs on a schedule or costs credits while idle.
-- Keeps all data; resume later by reversing each statement.

-- Scheduled tasks (sql/03_silver, sql/04_documents) -- each wakes a warehouse.
ALTER TASK IF EXISTS MARKET_AGENT.SILVER.MERGE_TRADES_TASK SUSPEND;
ALTER TASK IF EXISTS MARKET_AGENT.SILVER.MERGE_BARS_TASK SUSPEND;
ALTER TASK IF EXISTS MARKET_AGENT.SILVER.MERGE_SYMBOLS_TASK SUSPEND;
ALTER TASK IF EXISTS MARKET_AGENT.SILVER.MERGE_NEWS_TASK SUSPEND;

-- Alerts (sql/11_monitoring) -- each runs on a schedule.
ALTER ALERT IF EXISTS MARKET_AGENT.GOVERNANCE.SILVER_INGESTION_STALLED SUSPEND;
ALTER ALERT IF EXISTS MARKET_AGENT.GOVERNANCE.DELAY_POLICY_DETACHED SUSPEND;
ALTER ALERT IF EXISTS MARKET_AGENT.GOVERNANCE.PIPELINE_TASK_FAILED SUSPEND;
ALTER ALERT IF EXISTS MARKET_AGENT.GOVERNANCE.GOLD_STALE_FOR_ANALYSTS SUSPEND;

-- Auto-ingest pipes (sql/01_ingest).
ALTER PIPE IF EXISTS MARKET_AGENT.BRONZE.SYMBOLS_PIPE SET PIPE_EXECUTION_PAUSED = TRUE;
ALTER PIPE IF EXISTS MARKET_AGENT.BRONZE.BARS_BACKFILL_PIPE SET PIPE_EXECUTION_PAUSED = TRUE;
ALTER PIPE IF EXISTS MARKET_AGENT.BRONZE.NEWS_PIPE SET PIPE_EXECUTION_PAUSED = TRUE;

-- Cortex Search costs credits for as long as it exists, even with no queries.
-- Dropping it is the reliable stop; recreate it from sql/04_documents later.
DROP CORTEX SEARCH SERVICE IF EXISTS MARKET_AGENT.SILVER.NEWS_SEARCH_SERVICE;

-- Check: nothing should be left in state 'started' / 'RUNNING'.
SHOW TASKS IN ACCOUNT;
SHOW WAREHOUSES;

-- ============================================================ LEVEL 2: REMOVE
-- Final cleanup -- deletes the project's data. Uncomment only when you're
-- done with the project for good. (Also run `terraform destroy` in
-- infra/terraform to remove the GCP bucket and Pub/Sub.)
--
-- DROP DATABASE IF EXISTS MARKET_AGENT;
-- DROP WAREHOUSE IF EXISTS ANALYST_WH;
-- DROP RESOURCE MONITOR IF EXISTS ANALYST_AGENT_MONITOR;
-- DROP INTEGRATION IF EXISTS MARKET_AGENT_GCS_INT;
-- DROP INTEGRATION IF EXISTS MARKET_AGENT_GCS_NOTIFY_INT;
-- DROP INTEGRATION IF EXISTS MARKET_AGENT_EMAIL_INT;
