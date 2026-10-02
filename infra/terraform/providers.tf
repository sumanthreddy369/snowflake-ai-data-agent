provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

provider "snowflake" {
  organization_name = var.snowflake_organization_name
  account_name      = var.snowflake_account_name
  user              = var.snowflake_user
  authenticator     = "SNOWFLAKE_JWT"
  private_key       = file(var.snowflake_private_key_path)
  role              = "ACCOUNTADMIN"
}
