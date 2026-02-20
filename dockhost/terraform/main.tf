module "dockhost_vm" {

  source = "../../modules/proxmox_vm_template"

  providers = {
    proxmox = proxmox
  }

  vm_count            = 1
  vm_template_id      = 9001
  vm_disk0_size       = 100
  vm_cpu_cores        = 3
  vm_memory           = 10240
  vm_name_prefix      = "dockhost"
  vm_baseid           = 9090
  vm_ip_start         = 90
  vm_started          = var.vm_started
  project_description = "VM for dockhost project - All Docker apps"

}
