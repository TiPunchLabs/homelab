# =============================================================================
# OVH DNS — public records for the tipunchlabs.fr zone
# =============================================================================
# Secrets are injected via TF_VAR_* environment variables sourced from `pass`
# (see .envrc.example). Nothing sensitive is committed.
# =============================================================================

# --- OVH API credentials (scoped token, /domain/zone/tipunchlabs.fr/*) --------

variable "ovh_endpoint" {
  description = "OVH API endpoint. Set via TF_VAR_ovh_endpoint."
  type        = string
  default     = "ovh-eu"
}

variable "ovh_application_key" {
  description = "OVH API application key. Set via TF_VAR_ovh_application_key."
  type        = string
  sensitive   = true
}

variable "ovh_application_secret" {
  description = "OVH API application secret. Set via TF_VAR_ovh_application_secret."
  type        = string
  sensitive   = true
}

variable "ovh_consumer_key" {
  description = "OVH API consumer key. Set via TF_VAR_ovh_consumer_key."
  type        = string
  sensitive   = true
}

# --- Zone / record ------------------------------------------------------------

variable "dns_zone" {
  description = "OVH DNS zone managed here."
  type        = string
  default     = "tipunchlabs.fr"
}

variable "portail_subdomain" {
  description = "Subdomain exposed publicly for the client portal."
  type        = string
  default     = "portail-client"
}

variable "portail_current_ip" {
  description = "Initial public IPv4 for the DynHost record. Injected via TF_VAR_portail_current_ip (pass) — never hardcoded. The DynHost updater (Livebox or ddclient) keeps it current afterwards; Terraform ignores later drift."
  type        = string
}

# --- DynHost ------------------------------------------------------------------

variable "dynhost_login_suffix" {
  description = "Suffix concatenated to the zone to build the DynHost login (login = <suffix>.<zone>)."
  type        = string
  default     = "portail"
}

variable "dynhost_password" {
  description = "Password the DynHost updater uses to push IP changes. Set via TF_VAR_dynhost_password."
  type        = string
  sensitive   = true
}
