# Names match the CREATE ... IF NOT EXISTS statements in sql/, so the SQL
# still runs standalone on an account without Terraform, and becomes a no-op
# for these objects after `terraform apply`. Settings must stay identical in
# both places until the SQL copies are removed (see docs/production-readiness.md).

resource "snowflake_database" "market_agent" {
  name    = "MARKET_AGENT"
  comment = "Real-time equities data + AI agent. Managed by Terraform (infra/terraform)."
}

# Same settings as sql/09_guardrails: small and short-fused, so a bad
# natural-language question can only burn the agent's own budget.
resource "snowflake_warehouse" "analyst" {
  name                                = "ANALYST_WH"
  warehouse_size                      = "XSMALL"
  auto_suspend                        = 60
  auto_resume                         = "true"
  initially_suspended                 = true
  statement_timeout_in_seconds        = 30
  statement_queued_timeout_in_seconds = 15
  resource_monitor                    = snowflake_resource_monitor.analyst.name
  comment                             = "Dedicated to Cortex Analyst / ANALYST_AGENT."
}

resource "snowflake_resource_monitor" "analyst" {
  name                      = "ANALYST_AGENT_MONITOR"
  credit_quota              = var.analyst_monthly_credit_quota
  frequency                 = "MONTHLY"
  start_timestamp           = "IMMEDIATELY"
  notify_triggers           = [75]
  suspend_trigger           = 100
  suspend_immediate_trigger = 110
}

locals {
  # Functional roles from sql/07_governance and sql/09_guardrails.
  roles = {
    LOADER         = "Ingestion identity (streaming + batch backfill)."
    TRANSFORMER    = "dbt runs as this role."
    ANALYST_AGENT  = "Cortex Analyst / Agent queries as this role -- delayed data only."
    BI_READER      = "Human dashboard/BI users -- delayed data only."
    REALTIME_DESK  = "Entitled role: sees true real-time prices."
    AUDIT_REVIEWER = "Reads the agent audit log, nothing else."
  }
}

resource "snowflake_account_role" "functional" {
  for_each = local.roles
  name     = each.key
  comment  = each.value
}

# Every functional role rolls up to SYSADMIN, so objects these roles create
# stay manageable by administrators (catalog problem S2: orphaned ownership).
resource "snowflake_grant_account_role" "to_sysadmin" {
  for_each         = local.roles
  role_name        = snowflake_account_role.functional[each.key].name
  parent_role_name = "SYSADMIN"
}

resource "snowflake_storage_integration_gcs" "raw" {
  name                      = "MARKET_AGENT_GCS_INT"
  enabled                   = true
  storage_allowed_locations = ["gcs://${google_storage_bucket.raw.name}/raw/"]
}

locals {
  # GCP service account Snowflake created for this integration.
  snowflake_storage_sa = snowflake_storage_integration_gcs.raw.describe_output[0].service_account
}

# GCS auto-ingest needs this: Snowpipe on GCS reads object-created events from
# a Pub/Sub subscription through a notification integration, and every
# AUTO_INGEST pipe must name it (INTEGRATION = 'MARKET_AGENT_GCS_NOTIFY_INT'
# in sql/01_ingest).
resource "snowflake_notification_integration" "gcs_events" {
  name                         = "MARKET_AGENT_GCS_NOTIFY_INT"
  enabled                      = true
  notification_provider        = "GCP_PUBSUB"
  gcp_pubsub_subscription_name = google_pubsub_subscription.snowpipe.id
}
