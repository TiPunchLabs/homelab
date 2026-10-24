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

  vm_cpu_cores = 4
  vm_memory    = 8192
  # Plancher du ballooning (2026-10-16) : hermes-30 est la seule VM
  # ballonnee de pve ; a 2048, pvestatd l'y ramenait des que l'hote passait 80 %
  # (35 a 84 % du temps selon Komodo). 3584 laisse ~2 Gio a l'invite avec deux
  # gateways. Applique a chaud par `qm set 9030 --balloon 3584`, pas par
  # Terraform : bpg v0.96 redemarrerait la VM pour ce changement
  # (reboot_after_update = true par defaut).
  #
  # 4096 (M4-MEM.2A, 2026-10-23) : place pour un quatrieme gateway. Sans
  # `memory` dans hotplug, bpg classe toute modif memoire « reboot requis » ;
  # a false il pousse la config et avertit au lieu de redemarrer.
  #
  # Etat au 2026-10-23 : plancher 4096 configure ET effectif, maximum 8192,
  # aucun redemarrage. L'apply ne change que la config : hote au-dessus de
  # 80 %, pvestatd ne remonte pas un ballon sous son nouveau plancher, il est
  # reste a 3584. Rendu effectif par un `balloon 4096` ponctuel lance a la main
  # par l'administrateur dans le moniteur QEMU (`qm monitor 9030`). Apres tout
  # changement de plancher, verifier `qm status 9030 --verbose` (balloon contre
  # balloon_min), pas seulement `qm config`.
  vm_memory_floating     = 4096
  vm_reboot_after_update = false

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

  # DNS de BOOTSTRAP uniquement. Le role Ansible `dns_resolver` installe ensuite
  # dnsmasq et bascule le systeme sur 127.0.0.1 — voir le README de ce role.
  #
  # Un seul serveur, volontairement. La liste precedente etait
  # ["192.168.10.71", "1.1.1.1"], justifiee par : « le basculement n'a lieu que
  # sur timeout/SERVFAIL, jamais sur NXDOMAIN, donc .internal reste correct tant
  # que Pi-hole repond ». La premisse est juste, la conclusion est fausse : la
  # bascule de systemd-resolved est COLLANTE. Un seul timeout du Pi-hole a
  # deplace la resolution vers 1.1.1.1 definitivement, et une fois la-bas
  # .internal repondait NXDOMAIN — une reponse valide, qui ne provoque aucun
  # retour en arriere. Constate le 2026-08-23 : plus aucun nom .internal ne
  # resolvait depuis hermes-30, sans qu'aucun service ne soit tombe.
  #
  # ⚠️ Ne PAS pointer sur 127.0.0.1 ici : au premier boot dnsmasq n'existe pas
  # encore, le provisioning n'aurait aucune resolution.
  vm_dns_servers = ["192.168.10.71"]

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
