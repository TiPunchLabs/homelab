output "vm_ips_output" {
  description = "IPs of the created VMs (computed from configuration)"
  value = [
    for i in range(var.vm_count) :
    "${join(".", slice(split(".", var.vm_gateway), 0, 3))}.${var.vm_ip_start + i}"
  ]
}

output "vm_names" {
  description = "Names of the created VMs"
  value       = [for vm in proxmox_virtual_environment_vm.vm : vm.name]
}

output "vm_ids" {
  description = "IDs of the created VMs"
  value       = [for vm in proxmox_virtual_environment_vm.vm : vm.vm_id]
}
