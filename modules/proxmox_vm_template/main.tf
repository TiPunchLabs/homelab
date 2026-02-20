terraform {
  required_version = ">= 1.11.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.93.0"
    }
  }
}

resource "proxmox_virtual_environment_vm" "vm" {
  count       = var.vm_count
  name        = "${var.vm_name_prefix}-${var.vm_ip_start + count.index}"
  description = var.project_description
  node_name   = var.vm_target_node
  vm_id       = var.vm_baseid + count.index
  tags        = ["terraform", var.vm_name_prefix]
  started     = var.vm_started

  # Cleanup options (v0.87.0+)
  stop_on_destroy = true

  clone {
    vm_id   = var.vm_template_id
    full    = true
    retries = 5
  }

  agent {
    enabled = true
    timeout = "1s" # Don't wait for agent if permissions are missing
  }

  cpu {
    cores = var.vm_cpu_cores
    type  = "host"
  }

  memory {
    dedicated = var.vm_memory
  }

  disk {
    datastore_id = var.vm_disk0_storage
    interface    = "scsi0"
    size         = var.vm_disk0_size
    file_format  = "raw"
  }

  initialization {
    dns {
      domain  = var.vm_dns_domain
      servers = var.vm_dns_servers
    }

    ip_config {
      ipv4 {
        address = "${join(".", slice(split(".", var.vm_gateway), 0, 3))}.${var.vm_ip_start + count.index}/${var.vm_netmask}"
        gateway = var.vm_gateway
      }
    }
  }

  vga {
    type = "std"
  }

  lifecycle {
    ignore_changes = [
      # Ignore changes to cpu.units as it's now server-computed (v0.89.0)
      cpu[0].units,
    ]
  }
}

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
