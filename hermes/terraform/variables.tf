# Ces variables sont utilisées uniquement pour le provider
variable "pm_api_url" {
  type = string
}

variable "pm_api_token_id" {
  type      = string
  sensitive = true
}

variable "pm_api_token_secret" {
  type      = string
  sensitive = true
}

# false depuis M6.3.D : hermes-30 est arretee, un apply ne doit pas la relancer.
variable "vm_started" {
  description = "Whether the VM should be started (true) or stopped (false)"
  type        = bool
  default     = false
}
