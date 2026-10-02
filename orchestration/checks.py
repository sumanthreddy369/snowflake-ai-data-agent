"""
Guardrail checks that run after the assets they protect (and on their own
schedule in definitions.py). Each one maps to a problem in
knowledge/problem_catalog.yaml.

These overlap on purpose with the Snowflake ALERTs in sql/11_monitoring:
alerts keep firing if Dagster itself is down, and these checks block
downstream deploys (a failed ERROR check stops the semantic view and agent
from deploying on top of ungoverned or stale data).
"""

from dagster import AssetCheckResult, AssetCheckSeverity, AssetKey, asset_check
from dagster_dbt import get_asset_key_for_model
from dagster_snowflake import SnowflakeResource

from .assets import gold_models

FCT_BARS = get_asset_key_for_model([gold_models], "fct_bars")
FCT_TRADES = get_asset_key_for_model([gold_models], "fct_trades")

# Same definition as MARKET_AGENT.GOVERNANCE.IS_MARKET_OPEN() in
# sql/11_monitoring; weekdays 9:30-16:00 ET. Exchange holidays aren't modelled
# yet (catalog A2), so a holiday reads as "open" and may raise a false stale.
MARKET_OPEN_SQL = """
    DAYOFWEEKISO(CONVERT_TIMEZONE('UTC', 'America/New_York', SYSDATE())) <= 5
    AND TO_TIME(CONVERT_TIMEZONE('UTC', 'America/New_York', SYSDATE()))
        BETWEEN '09:30:00'::TIME AND '16:00:00'::TIME
"""


def _scalar(snowflake: SnowflakeResource, sql: str):
    with snowflake.get_connection() as conn:
        return conn.cursor().execute(sql).fetchone()[0]


def _policy_attached(snowflake: SnowflakeResource, table: str) -> AssetCheckResult:
    n = _scalar(snowflake, f"""
        SELECT COUNT(*) FROM TABLE(MARKET_AGENT.INFORMATION_SCHEMA.POLICY_REFERENCES(
            ref_entity_name => 'MARKET_AGENT.GOLD.{table}', ref_entity_domain => 'table'))
        WHERE policy_name = 'DELAYED_DATA_POLICY'""")
    return AssetCheckResult(
        passed=n == 1,
        severity=AssetCheckSeverity.ERROR,
        metadata={"policy_references": n},
        description="0 means the agent can see real-time prices it isn't licensed for.",
    )


@asset_check(asset=FCT_TRADES, blocking=True,
             description="Catalog E4: DELAYED_DATA_POLICY still attached after the dbt rebuild.")
def fct_trades_policy_attached(snowflake: SnowflakeResource) -> AssetCheckResult:
    return _policy_attached(snowflake, "FCT_TRADES")


@asset_check(asset=FCT_BARS, blocking=True,
             description="Catalog E4: DELAYED_DATA_POLICY still attached after the dbt rebuild.")
def fct_bars_policy_attached(snowflake: SnowflakeResource) -> AssetCheckResult:
    return _policy_attached(snowflake, "FCT_BARS")


@asset_check(asset=FCT_BARS,
             description="Catalog F6/O1: during market hours, Gold bars are no older than the freshness budget.")
def fct_bars_fresh(snowflake: SnowflakeResource) -> AssetCheckResult:
    # Runs as the deploy/monitor role, which sees policy-filtered rows like
    # any non-entitled role: the 15-minute delay + 5-minute Gold refresh +
    # margin gives the 30-minute budget (docs/production-readiness.md).
    with snowflake.get_connection() as conn:
        is_open, lag = conn.cursor().execute(f"""
            SELECT {MARKET_OPEN_SQL},
                   DATEDIFF('second', MAX(bar_ts), SYSDATE()) / 60.0
            FROM MARKET_AGENT.GOLD.FCT_BARS""").fetchone()
    if not is_open:
        return AssetCheckResult(passed=True, metadata={"market_open": False},
                                description="Market closed; freshness not evaluated.")
    return AssetCheckResult(
        passed=lag is not None and lag <= 30,
        severity=AssetCheckSeverity.WARN,
        metadata={"market_open": True, "visible_lag_minutes": float(lag) if lag is not None else -1.0},
    )


@asset_check(asset=AssetKey(["silver", "bars"]),
             description="Catalog O2/C1: every parseable Bronze bar from the last day reached Silver once.")
def bronze_to_silver_bars_reconciled(snowflake: SnowflakeResource) -> AssetCheckResult:
    with snowflake.get_connection() as conn:
        bronze, silver = conn.cursor().execute("""
            SELECT
              (SELECT COUNT(DISTINCT symbol, TRY_TO_TIMESTAMP_NTZ(bar_ts))
                 FROM MARKET_AGENT.BRONZE.RAW_BARS
                WHERE TRY_TO_TIMESTAMP_NTZ(bar_ts) >= DATEADD('day', -1, SYSDATE())
                  AND TRY_TO_TIMESTAMP_NTZ(bar_ts) < DATEADD('minute', -5, SYSDATE())),
              (SELECT COUNT(*) FROM MARKET_AGENT.SILVER.BARS
                WHERE bar_ts >= DATEADD('day', -1, SYSDATE())
                  AND bar_ts < DATEADD('minute', -5, SYSDATE()))""").fetchone()
    # The last 5 minutes are excluded: the 1-minute MERGE task may not have run yet.
    return AssetCheckResult(
        passed=bronze == silver,
        severity=AssetCheckSeverity.WARN,
        metadata={"bronze_distinct_bars": bronze, "silver_bars": silver, "missing": bronze - silver},
    )


@asset_check(asset=AssetKey(["silver", "trades"]),
             description="Catalog D2: no Bronze -> Silver task failed in the last hour.")
def silver_tasks_healthy(snowflake: SnowflakeResource) -> AssetCheckResult:
    failures = _scalar(snowflake, """
        SELECT COUNT(*) FROM TABLE(MARKET_AGENT.INFORMATION_SCHEMA.TASK_HISTORY(
            SCHEDULED_TIME_RANGE_START => DATEADD('hour', -1, CURRENT_TIMESTAMP()),
            ERROR_ONLY => TRUE))""")
    return AssetCheckResult(passed=failures == 0, severity=AssetCheckSeverity.ERROR,
                            metadata={"failed_task_runs_last_hour": failures})


all_checks = [fct_trades_policy_attached, fct_bars_policy_attached, fct_bars_fresh,
              bronze_to_silver_bars_reconciled, silver_tasks_healthy]
