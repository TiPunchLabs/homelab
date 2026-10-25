# hermes-31 : VM cible de la migration Hermes v0.22.5 (M6). Etat Terraform
# propre a ce repertoire : hermes-30 (../terraform) n'est jamais touche d'ici.
#
# Pas de 9040/.40 : plage reservee a kubecluster (voir
# docs/references/ip-addresses.md).
module "hermes_31_vm" {

  source = "../../modules/proxmox_vm_template"

  providers = {
    proxmox = proxmox
  }

  vm_count       = 1
  vm_template_id = 9001
  vm_name_prefix = "hermes"
  vm_baseid      = 9031
  vm_ip_start    = 31

  # pve n'a que ~2,4 Gio libres avec hermes-30 en service : 4096 fixe, sans
  # ballooning. Creee arretee, demarree par `qm start 9031` (M6.3.C) ;
  # vm_started = true par defaut depuis M6.3.D.
  vm_cpu_cores = 2
  vm_memory    = 4096

  # Comme hermes-30 : une modif non hotpluggable avertit au lieu de redemarrer
  # la VM en service.
  vm_reboot_after_update = false

  vm_disk0_size     = 32
  vm_disk0_discard  = "on"
  vm_disk0_ssd      = true
  vm_disk0_iothread = true

  # Sans virtio-scsi-single, Proxmox ignore silencieusement iothread.
  vm_scsi_hardware = "virtio-scsi-single"

  vm_network_devices = [
    {
      bridge   = "vmbr0"
      model    = "virtio"
      firewall = true
    }
  ]

  # DNS de bootstrap, un seul serveur : meme raison que hermes-30, voir
  # ../terraform/main.tf.
  vm_dns_servers = ["192.168.10.71"]
  vm_dns_domain  = "internal"

  # hermes-31 remplace hermes-30 (M6.3.D) : demarrage au boot du noeud, meme
  # sequence que hermes-30. A n'appliquer qu'avec hermes-30 en on_boot = false,
  # sinon un reboot de pve les demarre toutes les deux.
  vm_on_boot = true
  vm_startup = {
    order      = 10
    up_delay   = 30
    down_delay = 60
  }

  vm_started          = var.vm_started
  vm_ssh_keys         = [trimspace(file("~/.ssh/id_vm_proxmox_rsa.pub"))]
  project_description = "VM for hermes project - Hermes AI agent v0.22.5 (migration M6)"

}
