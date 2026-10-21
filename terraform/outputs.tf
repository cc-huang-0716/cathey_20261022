output "service_url" {
  value = google_cloud_run_v2_service.app.uri
}

output "artifact_registry_prefix" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}"
}

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "deploy_service_account" {
  value = google_service_account.deployer.email
}

output "github_actions_variables" {
  value = {
    GCP_PROJECT_ID                 = var.project_id
    GCP_REGION                     = var.region
    GCP_AR_REPOSITORY              = var.repository_id
    CLOUD_RUN_SERVICE              = var.service_name
    GCP_WORKLOAD_IDENTITY_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOY_SERVICE_ACCOUNT     = google_service_account.deployer.email
    DEPLOY_ENABLED                 = "true"
  }
}
