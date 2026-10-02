"""
Dagster assets: the glue between Alpaca, GCS, Snowflake, dbt and the Cortex
Agent. Each asset wraps an existing tool or SQL file rather than
reimplementing it -- the SQL files in sql/, the dbt project, and the
streaming/ backfill scripts stay the single source of truth.

What Dagster owns vs what it deliberately doesn't:
  - Owns: deploy order across files (encoded as asset dependencies, so it
    can't drift like the README run order did), dbt runs, semantic layer and
    agent deploys, batch backfills, and cross-system checks (checks.py).
  - Doesn't own: the minute-by-minute Bronze -> Silver MERGEs. Those stay in
    Snowflake Tasks (sql/03_silver), next to the data, where a 1-minute
    schedule costs nothing to orchestrate. Dagster deploys them and watches
    TASK_HISTORY instead of running them.

Required env vars: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE, GCS_BUCKET, GCP_PROJECT, ONCALL_EMAIL; ALPACA_API_KEY
and ALPACA_API_SECRET for the backfill assets.
"""

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from dagster import AssetExecutionContext, AssetKey, AssetSpec, Config, asset, multi_asset
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, dbt_assets, get_asset_key_for_model
from dagster_snowflake import SnowflakeResource

from .project import REPO_ROOT, dbt_project

SETUP = "snowflake_setup"
SERVE = "agent_serving"
BACKFILL = "batch_backfill"


def run_sql_file(context: AssetExecutionContext, snowflake: SnowflakeResource, relpath: str) -> None:
    """Run one repo SQL file as-is, filling the deploy-specific placeholders."""
    sql = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    sql = sql.replace("<your-bucket>", os.environ.get("GCS_BUCKET", "<your-bucket>"))
    sql = sql.replace("<your-gcp-project>", os.environ.get("GCP_PROJECT", "<your-gcp-project>"))
    sql = sql.replace("<oncall-email>", os.environ.get("ONCALL_EMAIL", "<oncall-email>"))
    if "<your-" in sql or "<oncall-email>" in sql:
        raise ValueError(f"{relpath} still has unfilled placeholders; set GCS_BUCKET, GCP_PROJECT, ONCALL_EMAIL")
    with snowflake.get_connection() as conn:
        cursors = conn.execute_string(sql, remove_comments=True)
    context.log.info("ran %s (%d statements)", relpath, len(cursors))


# ---------------------------------------------------------------- Snowflake setup
# Dependencies below encode the real order: 02 -> 03/04 -> 01 -> 07 -> 09 ->
# dbt -> semantic view -> agent. sql/01 runs after 02 and 04 because its file
# format lives in BRONZE and its pipes load RAW_* tables created there.

@asset(group_name=SETUP, description="sql/02_bronze: database, BRONZE schema, RAW_* tables.")
def bronze_tables(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "sql/02_bronze/bronze_tables.sql")


@multi_asset(
    group_name=SETUP,
    specs=[AssetSpec(AssetKey(["silver", t]), deps=[bronze_tables],
                     description=f"SILVER.{t.upper()}, kept fresh by Snowflake Tasks (sql/03_silver).")
           for t in ("trades", "bars", "symbols")],
)
def silver_tables(context: AssetExecutionContext, snowflake: SnowflakeResource):
    run_sql_file(context, snowflake, "sql/03_silver/streams_and_tasks.sql")


@asset(group_name=SETUP, deps=[bronze_tables],
       description="sql/04_documents: RAW_NEWS -> SILVER.NEWS -> Cortex Search service.")
def news_search_service(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "sql/04_documents/documents_and_search.sql")


@asset(group_name=SETUP, deps=[bronze_tables, news_search_service],
       description="sql/01_ingest: GCS stage, integrations, auto-ingest pipes into RAW_*.")
def ingest_pipes(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "sql/01_ingest/snowpipe_setup.sql")


@asset(group_name=SETUP, deps=[AssetKey(["silver", t]) for t in ("trades", "bars", "symbols")],
       description="sql/07_governance: roles, GOLD/STAGING schemas, DELAYED_DATA_POLICY.")
def governance(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "sql/07_governance/rbac_and_masking.sql")


@asset(group_name=SETUP, deps=[governance],
       description="sql/09_guardrails: agent warehouse, credit monitor, audit log.")
def guardrails(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "sql/09_guardrails/cost_and_access_guardrails.sql")


# -------------------------------------------------------------------- dbt (Gold)

class GovernedDbtTranslator(DagsterDbtTranslator):
    """Every dbt model depends on governance: it creates the GOLD schema and the
    policy the fact models' post-hooks attach. Without this edge, a fresh
    deploy could run dbt before the policy exists."""

    def get_asset_spec(self, manifest, unique_id, project):
        spec = super().get_asset_spec(manifest, unique_id, project)
        if unique_id.startswith("model."):
            spec = spec.merge_attributes(deps=[governance.key])
        return spec


@dbt_assets(manifest=dbt_project.manifest_path, project=dbt_project,
            dagster_dbt_translator=GovernedDbtTranslator())
def gold_models(context: AssetExecutionContext, dbt: DbtCliResource):
    # `build` = run + test, so a failing dbt test stops downstream assets
    # (semantic view, agent) from deploying on bad data.
    yield from dbt.cli(["build"], context=context).stream()


# ------------------------------------------------------------- agent serving

@asset(group_name=SERVE,
       deps=[get_asset_key_for_model([gold_models], m) for m in ("fct_bars", "fct_trades", "dim_symbols")],
       description="semantic_layer/semantic_view.sql over the Gold tables.")
def semantic_view(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "semantic_layer/semantic_view.sql")


@asset(group_name=SERVE, deps=[semantic_view, news_search_service, guardrails],
       description="sql/10_agent: the Cortex Agent routing between analyst and search tools.")
def cortex_agent(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "sql/10_agent/cortex_agent.sql")


@asset(group_name=SERVE,
       deps=[guardrails, AssetKey(["silver", "bars"]),
             get_asset_key_for_model([gold_models], "fct_bars"),
             get_asset_key_for_model([gold_models], "fct_trades")],
       description="sql/11_monitoring: Snowflake ALERTs that page on-call even if Dagster is down.")
def monitoring_alerts(context: AssetExecutionContext, snowflake: SnowflakeResource) -> None:
    run_sql_file(context, snowflake, "sql/11_monitoring/alerts.sql")


# ---------------------------------------------------------------- batch backfill

class BackfillWindow(Config):
    start: str = (date.today() - timedelta(days=1)).isoformat()
    end: str = date.today().isoformat()


def _run_script(context: AssetExecutionContext, script: str, *args: str) -> None:
    cmd = [sys.executable, str(REPO_ROOT / "streaming" / script), *args]
    context.log.info("running %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT / "streaming")


def _out_dir(cfg: BackfillWindow) -> Path:
    d = REPO_ROOT / "streaming" / "data" / "backfill" / f"{cfg.start}_{cfg.end}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@asset(group_name=BACKFILL, description="Alpaca REST bars + symbol metadata for the window, as CSV.")
def alpaca_bars_csv(context: AssetExecutionContext, config: BackfillWindow) -> None:
    out = _out_dir(config)
    _run_script(context, "backfill_historical.py", "--start", config.start, "--end", config.end,
                "--timeframe", "1Min", "--bars-out", str(out / "bars.csv"),
                "--symbols-out", str(out / "symbols.csv"))


@asset(group_name=BACKFILL, description="Alpaca News API articles for the window, as CSV.")
def alpaca_news_csv(context: AssetExecutionContext, config: BackfillWindow) -> None:
    out = _out_dir(config)
    _run_script(context, "backfill_news.py", "--start", config.start, "--end", config.end,
                "--out", str(out / "news.csv"))


@asset(group_name=BACKFILL, deps=[alpaca_bars_csv, alpaca_news_csv, ingest_pipes],
       description="Uploads the window's CSVs to gs://<bucket>/raw/; Snowpipe auto-ingests from there.")
def gcs_raw_files(context: AssetExecutionContext, config: BackfillWindow) -> None:
    from google.cloud import storage  # imported here so the rest of the graph loads without it

    out = _out_dir(config)
    bucket = storage.Client(project=os.environ["GCP_PROJECT"]).bucket(os.environ["GCS_BUCKET"])
    # Prefixes and file-name patterns match the pipes in sql/01_ingest.
    for local, prefix, name in [("bars.csv", "bars_backfill", "bars"), ("symbols.csv", "symbols", "symbols"),
                                ("news.csv", "news", "news")]:
        blob = bucket.blob(f"raw/{prefix}/{name}_{config.start}_{config.end}.csv")
        blob.upload_from_filename(str(out / local))
        context.log.info("uploaded gs://%s/%s", bucket.name, blob.name)
