module "hermes_vm" {

  source = "../../modules/proxmox_vm_template"

  providers = {
    proxmox = proxmox
  }

  vm_count       = 1
  vm_template_id = 9001
  vm_name_prefix = "hermes"
  vm_baseid      = 9030
  vm_ip_start    = 30

  vm_cpu_cores       = 4
  vm_memory          = 8192
  vm_memory_floating = 2048

  # 32 Go : local-lvm est en thin provisioning et deja a ~67 % d'occupation.
  # Agrandir plus tard est non destructif (qm resize + growpart), pas l'inverse.
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

  # DNS : Pi-hole (dns-71) sert la zone .internal du homelab, indispensable si
  # l'agent joint des services par leur nom. 1.1.1.1 en repli : le basculement
  # n'a lieu que sur timeout/SERVFAIL, jamais sur NXDOMAIN, donc .internal reste
  # correct tant que Pi-hole repond. Pi-hole forwarde lui-meme le trafic public.
  vm_dns_servers = ["192.168.10.71", "1.1.1.1"]

  # "internal" plutot que le defaut "local", reserve au mDNS (RFC 6762).
  # Autorise les noms courts : `ping komodo` -> komodo.internal.
  vm_dns_domain = "internal"

  # L'agent tourne 24/7 : demarrage automatique au boot du noeud.
  vm_on_boot = true
  vm_startup = {
    order      = 10
    up_delay   = 30
    down_delay = 60
  }

  vm_started          = var.vm_started
  vm_ssh_keys         = [trimspace(file("~/.ssh/id_vm_proxmox_rsa.pub"))]
  project_description = "VM for hermes project - Hermes AI agent"

}
