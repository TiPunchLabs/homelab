variable "github_token" {
  description = "GitHub Personal Access Token"
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub username or organization name"
  type        = string
}

variable "repository_name" {
  description = "The name of the GitHub repository"
  type        = string
  default     = "proxmox"
}

variable "repository_description" {
  description = "A description for the GitHub repository"
  type        = string
  default     = "Ansible playbooks and Terraform configurations for managing a Proxmox homelab"
}

variable "visibility" {
  description = "The visibility of the GitHub repository"
  type        = string
  default     = "public"

  validation {
    condition     = contains(["public", "private"], var.visibility)
    error_message = "Visibility must be 'public' or 'private'."
  }
}
