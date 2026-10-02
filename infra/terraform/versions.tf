# Account-level infrastructure for snowflake-ai-data-agent: the GCP side of
# the batch path (bucket, Pub/Sub, IAM) and the Snowflake objects that sit
# above any single schema (database, warehouse, credit monitor, roles,
# integrations). Tables, streams, tasks, policies and grants on data objects
# stay in sql/ and dbt/ -- see docs/production-readiness.md for the split.

terraform {
  required_version = ">= 1.6"

  required_providers {
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 2.0"
    }
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }

  # Local state by default so `terraform validate` and a first trial-account
  # apply need nothing else. For shared use, keep state in GCS instead (create
  # the state bucket by hand first -- it can't manage itself):
  #
  # backend "gcs" {
  #   bucket = "<your-terraform-state-bucket>"
  #   prefix = "snowflake-ai-data-agent"
  # }
}
