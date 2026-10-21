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
