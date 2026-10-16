-- Step 12: identity for GitHub Actions CI/CD. Run once as ACCOUNTADMIN.
--
-- A dedicated SERVICE user with key-pair auth, so no person's credentials are
-- stored in GitHub, and two narrow roles:
--   CI_RUNNER   -- pull requests: builds and tests in a throwaway database
--                  made of zero-copy clones of Silver; can't touch MARKET_AGENT
--                  objects beyond reading Silver.
--   TRANSFORMER -- merges to master (after approval): runs dbt against the
--                  real database, exactly as a human dbt run would.
-- DEFAULT_SECONDARY_ROLES = () because the first live run showed secondary
-- roles can leak access across roles (docs/snowflake-results.md, bug 4).
--
-- Replace <public-key-body> with the contents of the CI key's .pub file
-- (without the BEGIN/END lines). The private key goes only into the GitHub
-- secret SNOWFLAKE_CI_PRIVATE_KEY.

CREATE ROLE IF NOT EXISTS CI_RUNNER;
GRANT CREATE DATABASE ON ACCOUNT TO ROLE CI_RUNNER;      -- the throwaway CI database
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE CI_RUNNER;
GRANT USAGE ON DATABASE MARKET_AGENT TO ROLE CI_RUNNER;
GRANT USAGE ON SCHEMA MARKET_AGENT.SILVER TO ROLE CI_RUNNER;
GRANT SELECT ON ALL TABLES IN SCHEMA MARKET_AGENT.SILVER TO ROLE CI_RUNNER;     -- needed to clone
GRANT SELECT ON FUTURE TABLES IN SCHEMA MARKET_AGENT.SILVER TO ROLE CI_RUNNER;
GRANT ROLE CI_RUNNER TO ROLE SYSADMIN;

CREATE USER IF NOT EXISTS CI_DEPLOY
  TYPE = SERVICE
  DEFAULT_ROLE = CI_RUNNER
  DEFAULT_WAREHOUSE = COMPUTE_WH
  DEFAULT_SECONDARY_ROLES = ()
  RSA_PUBLIC_KEY = '<public-key-body>'
  COMMENT = 'GitHub Actions CI/CD (snowflake-ci.yml, snowflake-cd.yml). Key-pair only.';

GRANT ROLE CI_RUNNER TO USER CI_DEPLOY;
GRANT ROLE TRANSFORMER TO USER CI_DEPLOY;
