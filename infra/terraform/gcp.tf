# Batch landing zone. Backfill CSVs go to gs://<bucket>/raw/<feed>/; each new
# object publishes an event to Pub/Sub, and Snowpipe (via the notification
# integration in snowflake.tf) loads it into Bronze.

resource "google_storage_bucket" "raw" {
  name                        = var.gcs_bucket_name
  location                    = var.gcp_region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Raw files are reloadable from Alpaca; keep 90 days, then let them go.
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_pubsub_topic" "raw_events" {
  name = "${var.gcs_bucket_name}-raw-events"
}

# GCS publishes object events as its own Google-managed service agent, which
# needs publish rights on the topic.
data "google_storage_project_service_account" "gcs_agent" {}

resource "google_pubsub_topic_iam_member" "gcs_can_publish" {
  topic  = google_pubsub_topic.raw_events.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${data.google_storage_project_service_account.gcs_agent.email_address}"
}

resource "google_storage_notification" "raw_created" {
  bucket             = google_storage_bucket.raw.name
  topic              = google_pubsub_topic.raw_events.id
  payload_format     = "JSON_API_V1"
  event_types        = ["OBJECT_FINALIZE"]
  object_name_prefix = "raw/"
  depends_on         = [google_pubsub_topic_iam_member.gcs_can_publish]
}

resource "google_pubsub_subscription" "snowpipe" {
  name                 = "${var.gcs_bucket_name}-snowpipe"
  topic                = google_pubsub_topic.raw_events.id
  ack_deadline_seconds = 60
}

# Cross-cloud wiring: Snowflake creates its own GCP service accounts for each
# integration. Granting them here replaces the manual "run DESC INTEGRATION,
# then grant in the GCP console" steps.
resource "google_storage_bucket_iam_member" "snowflake_reads_bucket" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.snowflake_storage_sa}"
}

resource "google_pubsub_subscription_iam_member" "snowflake_reads_events" {
  subscription = google_pubsub_subscription.snowpipe.id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${snowflake_notification_integration.gcs_events.gcp_pubsub_service_account}"
}

resource "google_project_iam_member" "snowflake_monitors_subscription" {
  project = var.gcp_project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${snowflake_notification_integration.gcs_events.gcp_pubsub_service_account}"
}
