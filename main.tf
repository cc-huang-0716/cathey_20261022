terraform {
  required_version = ">= 1.6, < 2.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}


variable "project_id" {
  description = "Existing, billing-enabled Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
  default     = "asia-east1"
}

variable "service_name" {
  type    = string
  default = "market-brief"
}

variable "repository_id" {
  type    = string
  default = "market-brief"
}

variable "container_image" {
  description = "Bootstrap application image; use a commit tag or digest, not latest. CI manages later releases."
  type        = string
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID; prevents repository name reuse attacks."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be a numeric GitHub repository ID."
  }
}

variable "github_owner_id" {
  description = "Numeric GitHub user/organization ID."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must be a numeric GitHub owner ID."
  }
}

variable "public_access" {
  description = "Allow unauthenticated visitors; intended for the public interview demo."
  type        = bool
  default     = true
}


locals {
  services = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])
}

resource "google_project_service" "api" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.repository_id
  description   = "Market Brief application container images"
  format        = "DOCKER"
  docker_config {
    immutable_tags = true
  }
  depends_on = [google_project_service.api]
}

resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-runtime"
  display_name = "Market Brief runtime (no project roles)"
  depends_on   = [google_project_service.api]
}

resource "google_service_account" "deployer" {
  account_id   = "${var.service_name}-deployer"
  display_name = "Market Brief GitHub Actions deployer"
  depends_on   = [google_project_service.api]
}

resource "google_cloud_run_v2_service" "app" {
  name                = var.service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "30s"
    max_instance_request_concurrency = 40
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.container_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      env {
        name  = "CACHE_TTL_SECONDS"
        value = "300"
      }
      env {
        name  = "MAX_STALE_SECONDS"
        value = "3600"
      }
      startup_probe {
        initial_delay_seconds = 0
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 10
        http_get {
          path = "/health"
          port = 8080
        }
      }
      liveness_probe {
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3
        http_get {
          path = "/health"
          port = 8080
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.api]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.public_access ? 1 : 0
  name     = google_cloud_run_v2_service.app.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_artifact_registry_repository_iam_member" "writer" {
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "runtime_user" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "market-brief-github"
  display_name              = "Market Brief GitHub Actions"
  depends_on                = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }
  attribute_condition = "assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_owner_id}' && assertion.ref == 'refs/heads/main'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_identity" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}


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
