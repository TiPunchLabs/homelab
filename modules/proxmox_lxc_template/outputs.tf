output "ct_ips_output" {
  description = "IPs of the created containers (computed from configuration)"
  value = [
    for i in range(var.ct_count) :
    "${join(".", slice(split(".", var.ct_gateway), 0, 3))}.${var.ct_ip_start + i}"
  ]
}

output "ct_names" {
  description = "Names of the created containers"
  value       = [for ct in proxmox_virtual_environment_container.ct : ct.description]
}

output "ct_ids" {
  description = "IDs of the created containers"
  value       = [for ct in proxmox_virtual_environment_container.ct : ct.vm_id]
}
