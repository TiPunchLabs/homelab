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
  # ballooning, et VM creee arretee (vm_started = false par defaut). La
  # demarrer seulement apres avoir verifie la memoire disponible sur l'hote.
  vm_cpu_cores = 2
  vm_memory    = 4096

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

  # Un reboot du noeud ne doit pas demarrer hermes-31 a cote de hermes-30 tant
  # que la bascule n'est pas faite. false explicite : laisse a null, bpg
  # applique on_boot = true.
  vm_on_boot = false

  vm_started          = var.vm_started
  vm_ssh_keys         = [trimspace(file("~/.ssh/id_vm_proxmox_rsa.pub"))]
  project_description = "VM for hermes project - Hermes AI agent v0.22.5 (migration M6)"

}
