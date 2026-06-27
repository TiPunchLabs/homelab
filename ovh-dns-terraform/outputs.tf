output "portail_fqdn" {
  description = "Public FQDN of the client portal."
  value       = "${var.portail_subdomain}.${var.dns_zone}"
}

output "dynhost_login" {
  description = "DynHost login the updater (Livebox/ddclient) must use."
  value       = ovh_domain_zone_dynhost_login.portail.login
}
