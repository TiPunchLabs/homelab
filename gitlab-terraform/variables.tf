# =============================================================================
# GitLab Project Variables
# =============================================================================
# These variables configure the GitLab project managed by Terraform.
# Sensitive values should be passed via environment variables or tfvars files.
# =============================================================================

variable "gitlab_token" {
  description = "GitLab Personal Access Token with api scope. Set via TF_VAR_gitlab_token environment variable."
  type        = string
  sensitive   = true
}

variable "gitlab_namespace_id" {
  description = "GitLab namespace (group) ID where the project will be created."
  type        = number
}

variable "project_name" {
  description = "Name of the GitLab project."
  type        = string
  default     = "homelab"
}

variable "project_description" {
  description = "Short description displayed on the project page."
  type        = string
  default     = "Homelab infrastructure as code - Proxmox, Docker (dockhost), Kubernetes (kubecluster), Bastion"
}

variable "github_mirror_token" {
  description = "GitHub Personal Access Token (Fine-grained, contents:write) for push mirroring. Set via TF_VAR_github_mirror_token environment variable."
  type        = string
  sensitive   = true
}

variable "github_mirror_owner" {
  description = "GitHub organization or user owning the mirror repository."
  type        = string
  default     = "TiPunchLabs"
}

variable "visibility_level" {
  description = "Project visibility: 'public', 'internal', or 'private'."
  type        = string
  default     = "public"

  validation {
    condition     = contains(["public", "internal", "private"], var.visibility_level)
    error_message = "Visibility must be 'public', 'internal', or 'private'."
  }
}
