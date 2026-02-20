# Variables de configuration du provider Proxmox
variable "pm_api_url" {
  type        = string
  description = "URL de l'API Proxmox (ex: https://pve.example.com:8006)"
}

variable "pm_api_token_id" {
  type        = string
  description = "Identifiant du token API Proxmox (format: user@realm!tokenname)"
  sensitive   = true
}

variable "pm_api_token_secret" {
  type        = string
  description = "Secret du token API Proxmox"
  sensitive   = true
}

variable "vm_started" {
  description = "Whether the VM should be started (true) or stopped (false)"
  type        = bool
  default     = false
}
