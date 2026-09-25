-- Guardrails that cut across the pipeline rather than belonging to one step:
-- cost control, blast-radius limiting, and an immutable audit trail for
-- every question the AI agent answers. This is what turns "the agent has a
-- Row Access Policy" (sql/07_governance) into something a real ops team
-- would actually sign off on running unattended.

-- 1) Isolate the agent's compute from everything else. If a bad NL question
-- generates an expensive query, it should only ever burn the agent's own
-- budget, never contend with or blow through the budget for ingestion/dbt.
CREATE WAREHOUSE IF NOT EXISTS ANALYST_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 30
  STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 15
  COMMENT = 'Dedicated to Cortex Analyst / ANALYST_AGENT. Deliberately small, deliberately short-fused.';

GRANT USAGE ON WAREHOUSE ANALYST_WH TO ROLE ANALYST_AGENT;

-- 2) Hard credit cap. Even a warehouse this small can run up a bill if
-- something loops; a Resource Monitor is the backstop that doesn't depend on
-- the query timeout above actually working as intended.
CREATE RESOURCE MONITOR IF NOT EXISTS ANALYST_AGENT_MONITOR
  WITH CREDIT_QUOTA = 10
  FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS
    ON 75 PERCENT DO NOTIFY
    ON 100 PERCENT DO SUSPEND
    ON 110 PERCENT DO SUSPEND_IMMEDIATE;

ALTER WAREHOUSE ANALYST_WH SET RESOURCE_MONITOR = ANALYST_AGENT_MONITOR;

-- 3) Immutable audit trail. Every question asked through agent/cortex_client.py
-- writes one row here (see that file) -- ANALYST_AGENT can INSERT but never
-- UPDATE/DELETE, so the log can't be quietly edited after the fact by the
-- same role whose behavior it's recording.
CREATE SCHEMA IF NOT EXISTS MARKET_AGENT.GOVERNANCE;

CREATE TABLE IF NOT EXISTS MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG (
  audit_id        VARCHAR DEFAULT UUID_STRING(),
  asked_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
  role_name       VARCHAR DEFAULT CURRENT_ROLE(),
  question        VARCHAR,
  generated_sql   VARCHAR,
  request_id      VARCHAR,
  is_ambiguous    BOOLEAN
);

GRANT USAGE ON SCHEMA MARKET_AGENT.GOVERNANCE TO ROLE ANALYST_AGENT;
GRANT INSERT ON TABLE MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG TO ROLE ANALYST_AGENT;
-- Deliberately no UPDATE/DELETE grant to ANALYST_AGENT -- append-only by design.

-- A compliance/reviewer role gets read access to the log without being able
-- to touch the data the log describes.
CREATE ROLE IF NOT EXISTS AUDIT_REVIEWER;
GRANT USAGE ON DATABASE MARKET_AGENT TO ROLE AUDIT_REVIEWER;
GRANT USAGE ON SCHEMA MARKET_AGENT.GOVERNANCE TO ROLE AUDIT_REVIEWER;
GRANT SELECT ON TABLE MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG TO ROLE AUDIT_REVIEWER;

-- 4) Periodic access review. Run this by hand (or on a schedule) and confirm
-- the only privileges ANALYST_AGENT ever holds are SELECT (Gold tables) and
-- INSERT (the audit log above) -- never CREATE/UPDATE/DELETE/DROP on
-- anything. A role picking up a write grant it shouldn't have is exactly the
-- kind of drift this query is meant to catch before it becomes an incident.
-- SHOW GRANTS TO ROLE ANALYST_AGENT;
