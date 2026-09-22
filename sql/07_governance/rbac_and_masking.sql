-- Step 7: Governance — RBAC + Row Access Policy
-- Market data has no customer PII, so the governance story here isn't masking —
-- it's data licensing/entitlements, which is exactly how real market-data
-- vendors (exchanges, IEX, Nasdaq) actually gate access: a "real-time"
-- entitlement costs more and requires a subscriber agreement, while everyone
-- else gets a 15-minute-delayed view. This project models that with a Row
-- Access Policy instead of a masking policy.

-- Roles
CREATE ROLE IF NOT EXISTS LOADER;         -- ingestion identity (streaming + batch backfill)
CREATE ROLE IF NOT EXISTS TRANSFORMER;    -- dbt runs as this role
CREATE ROLE IF NOT EXISTS ANALYST_AGENT;  -- Cortex Analyst queries as this role — delayed data only
CREATE ROLE IF NOT EXISTS BI_READER;      -- human dashboard/BI users — delayed data only
CREATE ROLE IF NOT EXISTS REALTIME_DESK;  -- entitled role, e.g. a trading desk — sees true real-time data

GRANT USAGE ON DATABASE MARKET_AGENT TO ROLE LOADER;
GRANT USAGE, CREATE TABLE, CREATE STREAM, CREATE TASK ON SCHEMA MARKET_AGENT.BRONZE TO ROLE LOADER;

GRANT USAGE ON DATABASE MARKET_AGENT TO ROLE TRANSFORMER;
GRANT USAGE ON SCHEMA MARKET_AGENT.SILVER TO ROLE TRANSFORMER;
GRANT SELECT ON ALL TABLES IN SCHEMA MARKET_AGENT.SILVER TO ROLE TRANSFORMER;
GRANT CREATE SCHEMA ON DATABASE MARKET_AGENT TO ROLE TRANSFORMER;

GRANT USAGE ON DATABASE MARKET_AGENT TO ROLE ANALYST_AGENT;
GRANT USAGE ON SCHEMA MARKET_AGENT.GOLD TO ROLE ANALYST_AGENT;
GRANT SELECT ON ALL TABLES IN SCHEMA MARKET_AGENT.GOLD TO ROLE ANALYST_AGENT;
GRANT SELECT ON FUTURE TABLES IN SCHEMA MARKET_AGENT.GOLD TO ROLE ANALYST_AGENT;

GRANT USAGE ON DATABASE MARKET_AGENT TO ROLE BI_READER;
GRANT USAGE ON SCHEMA MARKET_AGENT.GOLD TO ROLE BI_READER;
GRANT SELECT ON ALL TABLES IN SCHEMA MARKET_AGENT.GOLD TO ROLE BI_READER;

GRANT USAGE ON DATABASE MARKET_AGENT TO ROLE REALTIME_DESK;
GRANT USAGE ON SCHEMA MARKET_AGENT.GOLD TO ROLE REALTIME_DESK;
GRANT SELECT ON ALL TABLES IN SCHEMA MARKET_AGENT.GOLD TO ROLE REALTIME_DESK;

-- Row Access Policy: any role without REALTIME_DESK sees trades/bars only once
-- they're at least 15 minutes old — the standard "delayed quote" entitlement
-- pattern real market-data vendors enforce. The Cortex Analyst agent explicitly
-- runs as ANALYST_AGENT, so it never sees true real-time prices unless someone
-- deliberately re-grants it REALTIME_DESK.
CREATE ROW ACCESS POLICY IF NOT EXISTS MARKET_AGENT.GOLD.DELAYED_DATA_POLICY
  AS (row_ts TIMESTAMP_NTZ) RETURNS BOOLEAN ->
    IS_ROLE_IN_SESSION('REALTIME_DESK')
    OR row_ts <= DATEADD('minute', -15, CURRENT_TIMESTAMP());

ALTER TABLE MARKET_AGENT.GOLD.FCT_TRADES
  ADD ROW ACCESS POLICY MARKET_AGENT.GOLD.DELAYED_DATA_POLICY ON (trade_ts);

ALTER TABLE MARKET_AGENT.GOLD.FCT_BARS
  ADD ROW ACCESS POLICY MARKET_AGENT.GOLD.DELAYED_DATA_POLICY ON (bar_ts);
