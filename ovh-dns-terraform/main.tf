# =============================================================================
# Public DNS for the client portal — portail-client.tipunchlabs.fr
# =============================================================================
# Surgical: only the records below are managed. We deliberately do NOT use
# `ovh_domain_zone_import` (which would take over the whole zone and clobber the
# mail/Brevo records). Mail (MX, SPF, DKIM brevo1/2, DMARC) stays untouched.
# =============================================================================

# DynHost A record. The Orange public IP is dynamic, so the value is updated
# out-of-band by the DynHost updater (Livebox DynDNS tab or ddclient). Terraform
# seeds the initial IP and then ignores drift on it. (`ttl` is computed by OVH.)
#
# OVH gotcha: creating this record via the API does NOT deploy the zone — the SOA
# serial stays put and the name returns NXDOMAIN until a one-shot zone refresh:
#   POST /domain/zone/tipunchlabs.fr/refresh   (run once after the first apply)
# Later IP changes pushed by the DynHost updater auto-deploy, no refresh needed.
resource "ovh_domain_zone_dynhost_record" "portail" {
  zone_name  = var.dns_zone
  sub_domain = var.portail_subdomain
  ip         = var.portail_current_ip

  lifecycle {
    ignore_changes = [ip]
  }
}

# Credentials the updater authenticates with to push IP changes.
# Resulting login = "<dynhost_login_suffix>.<dns_zone>" (e.g. portail.tipunchlabs.fr).
resource "ovh_domain_zone_dynhost_login" "portail" {
  zone_name    = var.dns_zone
  sub_domain   = var.portail_subdomain
  login_suffix = var.dynhost_login_suffix
  password     = var.dynhost_password
}
