# Vertex AI (Model Garden) as the route to Claude for the glue agents
# (docs/glue-and-guardrails.md). Calling Claude through our own GCP project
# keeps billing, quotas and audit logs in the same cloud as the rest of the
# pipeline -- the pattern companies use instead of a separate vendor account.
#
# Enabling the API and creating the service account cost nothing. Model calls
# are billed per token. One step can't be automated here: enabling the Claude
# model in the Model Garden console (which includes accepting Anthropic's
# terms) is a human action.

resource "google_project_service" "vertex_ai" {
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

# Least privilege: the glue agents' identity can call models and nothing else
# in the project (no storage, no Pub/Sub, no IAM).
resource "google_service_account" "glue_agents" {
  account_id   = "market-agent-glue"
  display_name = "market-agent glue agents (Vertex AI model calls only)"
}

resource "google_project_iam_member" "glue_agents_vertex_user" {
  project = var.gcp_project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.glue_agents.email}"
}

output "glue_agents_service_account" {
  description = "Identity the glue agents use to call Claude on Vertex AI."
  value       = google_service_account.glue_agents.email
}
