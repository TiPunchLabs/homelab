terraform {
  required_version = ">= 1.11.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = ">= 0.93.0, < 1.0.0"
    }
  }
}

resource "proxmox_virtual_environment_container" "ct" {
  count        = var.ct_count
  description  = var.project_description
  node_name    = var.ct_target_node
  vm_id        = var.ct_baseid + count.index
  tags         = ["terraform", "lxc", var.ct_name_prefix]
  started      = var.ct_started
  unprivileged = var.ct_unprivileged

  start_on_boot = var.ct_start_on_boot

  features {
    nesting = var.ct_nesting
  }

  operating_system {
    template_file_id = var.ct_template_file_id
    type             = var.ct_os_type
  }

  cpu {
    cores = var.ct_cpu_cores
  }

  memory {
    dedicated = var.ct_memory
  }

  disk {
    datastore_id = var.ct_disk_storage
    size         = var.ct_disk_size
  }

  initialization {
    dns {
      domain  = var.ct_dns_domain
      servers = var.ct_dns_servers
    }

    ip_config {
      ipv4 {
        address = "${join(".", slice(split(".", var.ct_gateway), 0, 3))}.${var.ct_ip_start + count.index}/${var.ct_netmask}"
        gateway = var.ct_gateway
      }
    }

    user_account {
      password = var.ct_root_password
      keys     = var.ct_ssh_keys
    }
  }

  network_interface {
    name = "eth0"
  }

  provisioner "remote-exec" {
    inline = [
      "useradd -m -s /bin/bash ansible",
      "echo 'ansible ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ansible",
      "chmod 440 /etc/sudoers.d/ansible",
      "mkdir -p /home/ansible/.ssh",
      "cp /root/.ssh/authorized_keys /home/ansible/.ssh/",
      "chown -R ansible:ansible /home/ansible/.ssh",
      "chmod 700 /home/ansible/.ssh && chmod 600 /home/ansible/.ssh/authorized_keys"
    ]

    connection {
      type        = "ssh"
      user        = "root"
      host        = "${join(".", slice(split(".", var.ct_gateway), 0, 3))}.${var.ct_ip_start + count.index}"
      private_key = file(var.ct_ssh_private_key_path)
    }
  }
}
