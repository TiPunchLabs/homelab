# =============================================================================
# GitHub Repository Variables
# =============================================================================
# These variables configure the GitHub repository managed by Terraform.
# Sensitive values should be passed via environment variables or tfvars files.
# =============================================================================

variable "github_token" {
  description = "GitHub Personal Access Token (PAT) with repo permissions. Use a fine-grained token for better security. Set via TF_VAR_github_token environment variable."
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub username or organization that owns the repository."
  type        = string
}

variable "repository_name" {
  description = "Name of the GitHub repository (without owner prefix)."
  type        = string
  default     = "homelab"
}

variable "repository_description" {
  description = "Short description displayed on the repository page."
  type        = string
  default     = "Homelab infrastructure as code - Proxmox, Docker (dockhost), Kubernetes (kubecluster)"
}

variable "visibility" {
  description = "Repository visibility: 'public' (visible to everyone) or 'private' (restricted access)."
  type        = string
  default     = "public"

  validation {
    condition     = contains(["public", "private"], var.visibility)
    error_message = "Visibility must be 'public' or 'private'."
  }
}
