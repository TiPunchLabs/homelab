module "vpngate_vm" {

  source = "../../modules/proxmox_vm_template"

  providers = {
    proxmox = proxmox
  }

  vm_count            = 1
  vm_template_id      = 9001
  vm_disk0_size       = 22
  vm_cpu_cores        = 1
  vm_memory           = 512
  vm_name_prefix      = "vpngate"
  vm_baseid           = 9050
  vm_ip_start         = 50
  vm_started          = var.vm_started
  vm_ssh_keys         = [trimspace(file("~/.ssh/id_vm_proxmox_rsa.pub"))]
  project_description = "VM for vpngate project - WireGuard VPN Server"

}
