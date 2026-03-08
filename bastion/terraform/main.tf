module "bastion_vm" {

  source = "../../modules/proxmox_vm_template"

  providers = {
    proxmox = proxmox
  }

  vm_count            = 1
  vm_template_id      = 9001
  vm_disk0_size       = 25
  vm_cpu_cores        = 2
  vm_memory           = 2048
  vm_name_prefix      = "bastion"
  vm_baseid           = 9060
  vm_ip_start         = 60
  vm_started          = var.vm_started
  vm_ssh_keys         = [trimspace(file("~/.ssh/id_vm_proxmox_rsa.pub"))]
  project_description = "VM for bastion project - Ansible & Terraform Executor"

}
