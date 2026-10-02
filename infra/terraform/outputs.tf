output "gcs_raw_url" {
  description = "Stage URL used by sql/01_ingest (replace <your-bucket> with the bucket name)."
  value       = "gcs://${google_storage_bucket.raw.name}/raw/"
}

output "snowflake_storage_service_account" {
  description = "GCP service account Snowflake uses to read the bucket."
  value       = local.snowflake_storage_sa
}

output "snowflake_notification_service_account" {
  description = "GCP service account Snowflake uses to read Pub/Sub events."
  value       = snowflake_notification_integration.gcs_events.gcp_pubsub_service_account
}
