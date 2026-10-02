variable "gcp_project_id" {
  description = "GCP project that owns the batch bucket and Pub/Sub topic."
  type        = string
}

variable "gcp_region" {
  description = "Region for the bucket; keep it close to the Snowflake account's region."
  type        = string
  default     = "us-central1"
}

variable "gcs_bucket_name" {
  description = "Globally unique bucket name. Files land under raw/{bars_backfill,symbols,news}/."
  type        = string
}

variable "snowflake_organization_name" {
  description = "Snowflake organization name (SELECT CURRENT_ORGANIZATION_NAME())."
  type        = string
}

variable "snowflake_account_name" {
  description = "Snowflake account name (SELECT CURRENT_ACCOUNT_NAME())."
  type        = string
}

variable "snowflake_user" {
  description = "User Terraform authenticates as. Needs ACCOUNTADMIN for integrations and resource monitors."
  type        = string
}

variable "snowflake_private_key_path" {
  description = "Path to the key-pair private key for snowflake_user. Key-pair, not password: see catalog problem S5."
  type        = string
}

variable "analyst_monthly_credit_quota" {
  description = "Hard monthly credit cap for the agent's warehouse. Must match sql/09_guardrails if that file is also run."
  type        = number
  default     = 10
}
