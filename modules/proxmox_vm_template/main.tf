terraform {
  required_version = ">= 1.11.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.93.0, < 1.0.0"
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
  on_boot     = var.vm_on_boot

  # null => controleur herite du template
  scsi_hardware = var.vm_scsi_hardware

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
    floating  = var.vm_memory_floating
  }

  disk {
    datastore_id = var.vm_disk0_storage
    interface    = "scsi0"
    size         = var.vm_disk0_size
    file_format  = "raw"
    discard      = var.vm_disk0_discard
    ssd          = var.vm_disk0_ssd
    iothread     = var.vm_disk0_iothread
  }

  # Liste vide => aucun bloc emis, les interfaces du clone sont conservees.
  dynamic "network_device" {
    for_each = var.vm_network_devices
    content {
      bridge   = network_device.value.bridge
      model    = network_device.value.model
      firewall = network_device.value.firewall
    }
  }

  # null => aucun bloc emis, la VM reste hors sequence de demarrage du noeud.
  dynamic "startup" {
    for_each = var.vm_startup == null ? [] : [var.vm_startup]
    content {
      order      = startup.value.order
      up_delay   = startup.value.up_delay
      down_delay = startup.value.down_delay
    }
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

    user_account {
      username = var.vm_ssh_user
      keys     = var.vm_ssh_keys
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
