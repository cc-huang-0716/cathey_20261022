terraform {
  required_version = ">= 1.6, < 2.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
  }
  # Local state is used for a single-person demo. For a team, configure a GCS
  # backend before running init; see docs/deployment.md.
}

provider "google" {
  project = var.project_id
  region  = var.region
}
