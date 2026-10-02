"""
Entry point: `dagster dev -m orchestration.definitions` (UI on localhost:3000)
or `dagster job execute -m orchestration.definitions -j deploy_job`.
"""

from datetime import timedelta

from dagster import (AssetSelection, Definitions, EnvVar, RunRequest, ScheduleEvaluationContext,
                     define_asset_job, load_assets_from_modules, schedule)
from dagster_dbt import DbtCliResource
from dagster_snowflake import SnowflakeResource

from . import assets
from .checks import all_checks
from .project import dbt_project

ET = "America/New_York"

all_assets = load_assets_from_modules([assets])

# Idempotent deploy of everything in Snowflake, in dependency order, followed
# by every check. Rerunning it is safe (all DDL is IF NOT EXISTS / OR REPLACE).
deploy_job = define_asset_job(
    "deploy_job",
    selection=AssetSelection.all() - AssetSelection.groups(assets.BACKFILL),
)

# Gold rebuild + the checks attached to Gold. A failed blocking check (policy
# not attached) fails the run, so nothing downstream deploys on top of it.
gold_refresh_job = define_asset_job(
    "gold_refresh_job", selection=AssetSelection.assets(assets.gold_models)
)

backfill_job = define_asset_job("backfill_job", selection=AssetSelection.groups(assets.BACKFILL))

# Checks only, no materialisation: the "is it healthy right now" sweep.
guardrail_checks_job = define_asset_job("guardrail_checks_job", selection=AssetSelection.all_asset_checks())


@schedule(job=gold_refresh_job, cron_schedule="*/5 9-16 * * 1-5", execution_timezone=ET)
def gold_refresh_market_hours(_context: ScheduleEvaluationContext):
    # Every 5 minutes in market hours: the Gold freshness budget behind the
    # agent's "15-minute delayed" promise (docs/production-readiness.md).
    return RunRequest()


@schedule(job=guardrail_checks_job, cron_schedule="*/15 * * * *", execution_timezone=ET)
def guardrail_checks_every_15_min(_context: ScheduleEvaluationContext):
    return RunRequest()


@schedule(job=backfill_job, cron_schedule="30 18 * * 1-5", execution_timezone=ET)
def nightly_backfill(context: ScheduleEvaluationContext):
    # After the close: re-pull the day from Alpaca REST so the batch path can
    # fill any gaps the live stream left (catalog A3, M4).
    day = context.scheduled_execution_time.date()
    window = {"start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat()}
    return RunRequest(
        run_key=f"backfill-{day.isoformat()}",
        run_config={"ops": {name: {"config": window}
                            for name in ("alpaca_bars_csv", "alpaca_news_csv", "gcs_raw_files")}},
    )


defs = Definitions(
    assets=all_assets,
    asset_checks=all_checks,
    jobs=[deploy_job, gold_refresh_job, backfill_job, guardrail_checks_job],
    schedules=[gold_refresh_market_hours, guardrail_checks_every_15_min, nightly_backfill],
    resources={
        "snowflake": SnowflakeResource(
            account=EnvVar("SNOWFLAKE_ACCOUNT"),
            user=EnvVar("SNOWFLAKE_USER"),
            password=EnvVar("SNOWFLAKE_PASSWORD"),
            role=EnvVar("SNOWFLAKE_ROLE"),
            warehouse=EnvVar("SNOWFLAKE_WAREHOUSE"),
            database="MARKET_AGENT",
        ),
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)
