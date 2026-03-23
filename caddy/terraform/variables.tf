variable "pm_api_url" {
  description = "Proxmox API URL"
  type        = string
}

variable "pm_api_token_id" {
  description = "Proxmox API token ID"
  type        = string
  sensitive   = true
}

variable "pm_api_token_secret" {
  description = "Proxmox API token secret"
  type        = string
  sensitive   = true
}

variable "ct_started" {
  description = "Whether the container should be started (true) or stopped (false)"
  type        = bool
  default     = true
}

variable "ct_root_password" {
  description = "Root password for the LXC container"
  type        = string
  sensitive   = true
}
