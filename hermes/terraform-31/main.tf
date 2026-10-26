# hermes-31 : VM Hermes v0.22.5 (migration M6). Etat Terraform propre a ce
# repertoire. hermes-30 et sa racine ../terraform ont ete retirees en M6.6.
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

  # Dimensionne quand pve n'avait que ~2,4 Gio libres avec hermes-30 en
  # service : 4096 fixe, sans ballooning. Creee arretee, demarree par `qm start 9031` (M6.3.C) ;
  # vm_started = true par defaut depuis M6.3.D.
  vm_cpu_cores = 2
  vm_memory    = 4096

  # Une modif non hotpluggable avertit au lieu de redemarrer la VM en service
  # (bpg redemarre sinon, reboot_after_update = true par defaut).
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

  # DNS de BOOTSTRAP, un seul serveur, volontairement : la bascule de
  # systemd-resolved vers un second serveur est collante, et .internal y
  # repondrait NXDOMAIN (constate sur hermes-30 le 2026-08-23). Le role
  # `dns_resolver` bascule ensuite sur dnsmasq (127.0.0.1) ; ne pas pointer
  # 127.0.0.1 ici, dnsmasq n'existe pas au premier boot. Voir
  # docs/guides/guide-hermes-cloudinit-dns-drift.md.
  vm_dns_servers = ["192.168.10.71"]
  vm_dns_domain  = "internal"

  # hermes-31 remplace hermes-30 depuis M6.3.D (detruite en M6.6.C) :
  # demarrage au boot du noeud.
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
