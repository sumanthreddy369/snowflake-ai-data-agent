-- Step 11: Monitoring and alerting that lives inside Snowflake.
-- These ALERTs run on Snowflake's own scheduler, so they keep firing when the
-- orchestrator (orchestration/, Dagster) is down -- monitoring shouldn't depend
-- on the thing it monitors. orchestration/checks.py runs overlapping checks
-- that additionally block deploys. Each alert maps to a runbook entry in
-- docs/runbook.md and a problem in knowledge/problem_catalog.yaml.
--
-- Placeholders: <oncall-email> must be a verified email of a user in this
-- account (SYSTEM$SEND_EMAIL only delivers to verified addresses).

CREATE NOTIFICATION INTEGRATION IF NOT EXISTS MARKET_AGENT_EMAIL_INT
  TYPE = EMAIL
  ENABLED = TRUE
  ALLOWED_RECIPIENTS = ('<oncall-email>');

-- One definition of "market open" shared by every alert. Weekdays 9:30-16:00
-- ET; exchange holidays aren't modelled yet (catalog A2), so a holiday can
-- raise a false staleness alert.
CREATE OR REPLACE FUNCTION MARKET_AGENT.GOVERNANCE.IS_MARKET_OPEN()
  RETURNS BOOLEAN
  AS
  $$
    DAYOFWEEKISO(CONVERT_TIMEZONE('UTC', 'America/New_York', SYSDATE())) <= 5
    AND TO_TIME(CONVERT_TIMEZONE('UTC', 'America/New_York', SYSDATE()))
        BETWEEN '09:30:00'::TIME AND '16:00:00'::TIME
  $$;

-- SEV-1: live ingestion stalled. Silver bars older than 5 minutes while the
-- market is open means the feed, Kafka, Snowpipe Streaming or the MERGE task
-- has stopped (catalog A1, B1, D2). Silver isn't policy-protected, so this
-- measures true lag, not the 15-minute delayed view.
CREATE ALERT IF NOT EXISTS MARKET_AGENT.GOVERNANCE.SILVER_INGESTION_STALLED
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '5 MINUTE'
  IF (EXISTS (
    SELECT 1
    WHERE MARKET_AGENT.GOVERNANCE.IS_MARKET_OPEN()
      AND (SELECT MAX(bar_ts) FROM MARKET_AGENT.SILVER.BARS) < DATEADD('minute', -5, SYSDATE())
  ))
  THEN CALL SYSTEM$SEND_EMAIL('MARKET_AGENT_EMAIL_INT', '<oncall-email>',
    '[SEV-1] market-agent: live ingestion stalled',
    'SILVER.BARS has no bar newer than 5 minutes during market hours. See docs/runbook.md#silver-ingestion-stalled');

-- SEV-1: governance broken. The delay policy is missing from a fact table, so
-- the agent can see real-time prices it isn't licensed for (catalog E4).
CREATE ALERT IF NOT EXISTS MARKET_AGENT.GOVERNANCE.DELAY_POLICY_DETACHED
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '15 MINUTE'
  IF (EXISTS (
    SELECT 1
    WHERE (SELECT COUNT(*) FROM TABLE(MARKET_AGENT.INFORMATION_SCHEMA.POLICY_REFERENCES(
             ref_entity_name => 'MARKET_AGENT.GOLD.FCT_TRADES', ref_entity_domain => 'table'))) = 0
       OR (SELECT COUNT(*) FROM TABLE(MARKET_AGENT.INFORMATION_SCHEMA.POLICY_REFERENCES(
             ref_entity_name => 'MARKET_AGENT.GOLD.FCT_BARS', ref_entity_domain => 'table'))) = 0
  ))
  THEN CALL SYSTEM$SEND_EMAIL('MARKET_AGENT_EMAIL_INT', '<oncall-email>',
    '[SEV-1] market-agent: DELAYED_DATA_POLICY detached',
    'A Gold fact table has no row access policy; real-time data is exposed. See docs/runbook.md#delay-policy-detached');

-- SEV-2: a Bronze -> Silver or news task failed in the last 15 minutes
-- (catalog D2). Repeated failures auto-suspend the task, which then shows up
-- as SILVER_INGESTION_STALLED.
CREATE ALERT IF NOT EXISTS MARKET_AGENT.GOVERNANCE.PIPELINE_TASK_FAILED
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '15 MINUTE'
  IF (EXISTS (
    SELECT 1 FROM TABLE(MARKET_AGENT.INFORMATION_SCHEMA.TASK_HISTORY(
      SCHEDULED_TIME_RANGE_START => DATEADD('minute', -15, CURRENT_TIMESTAMP()),
      ERROR_ONLY => TRUE))
  ))
  THEN CALL SYSTEM$SEND_EMAIL('MARKET_AGENT_EMAIL_INT', '<oncall-email>',
    '[SEV-2] market-agent: pipeline task failed',
    'A task failed in the last 15 minutes. See docs/runbook.md#pipeline-task-failed');

-- SEV-2: Gold is stale for analysts. The alert owner sees the policy-filtered
-- view like any non-entitled role, so the budget is 15 min delay + 5 min Gold
-- refresh + margin = 30 minutes (docs/production-readiness.md).
CREATE ALERT IF NOT EXISTS MARKET_AGENT.GOVERNANCE.GOLD_STALE_FOR_ANALYSTS
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '10 MINUTE'
  IF (EXISTS (
    SELECT 1
    WHERE MARKET_AGENT.GOVERNANCE.IS_MARKET_OPEN()
      AND (SELECT MAX(bar_ts) FROM MARKET_AGENT.GOLD.FCT_BARS) < DATEADD('minute', -30, SYSDATE())
  ))
  THEN CALL SYSTEM$SEND_EMAIL('MARKET_AGENT_EMAIL_INT', '<oncall-email>',
    '[SEV-2] market-agent: Gold stale for analysts',
    'FCT_BARS visible data is older than 30 minutes during market hours. See docs/runbook.md#gold-stale-for-analysts');

-- Alerts are created suspended. RESUME is idempotent, so re-running is safe.
ALTER ALERT MARKET_AGENT.GOVERNANCE.SILVER_INGESTION_STALLED RESUME;
ALTER ALERT MARKET_AGENT.GOVERNANCE.DELAY_POLICY_DETACHED RESUME;
ALTER ALERT MARKET_AGENT.GOVERNANCE.PIPELINE_TASK_FAILED RESUME;
ALTER ALERT MARKET_AGENT.GOVERNANCE.GOLD_STALE_FOR_ANALYSTS RESUME;

-- Credit spend is already capped by ANALYST_AGENT_MONITOR (sql/09_guardrails),
-- which notifies at 75% and suspends at 100%.
