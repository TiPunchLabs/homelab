module "pihole_ct" {
  source = "../../modules/proxmox_lxc_template"

  providers = {
    proxmox = proxmox
  }

  ct_count                = 1
  ct_name_prefix          = "dns"
  ct_baseid               = 1071
  ct_ip_start             = 71
  ct_cpu_cores            = 1
  ct_memory               = 512
  ct_disk_size            = 8
  ct_template_file_id     = "local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
  ct_ssh_keys             = [trimspace(file("~/.ssh/id_vm_proxmox_rsa.pub"))]
  ct_root_password        = var.ct_root_password
  ct_ssh_private_key_path = "~/.ssh/id_vm_proxmox_rsa"
  ct_started              = var.ct_started
  project_description     = "LXC container for Pi-hole DNS"
}
