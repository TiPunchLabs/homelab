# Pi-hole DNS sur LXC dns-71

> **Objectif** : Deployer un serveur DNS local (Pi-hole) sur un LXC dedie pour resoudre les domaines `.internal` du homelab et fournir du ad-blocking aux clients VPN.
>
> **Prerequis** : Module Terraform LXC (`modules/proxmox_lxc_template/`), sous-projet caddy-70 deploye, VPN WireGuard operationnel.

------

## 1. Contexte

Les domaines `.internal` (proxmox.internal, kandidat.internal, vpngate.internal) sont actuellement resolus via `/etc/hosts` sur le laptop. Les clients VPN mobiles (Android) n'ont aucun moyen de resoudre ces domaines car ils utilisent des DNS publics (1.1.1.1, 8.8.8.8) configures dans WireGuard.

Un serveur DNS local centralise la resolution `.internal` pour tous les clients (laptop, mobile, VMs) et offre en bonus le blocage publicitaire via Pi-hole.

------

## 2. Architecture

```
┌──────────┐  VPN   ┌────────────┐  DNS query   ┌──────────┐
│ Clients  │ ─────► │ vpngate-50 │ ───────────► │ dns-71   │
│ (laptop, │  WG    │ (WireGuard)│  .internal   │ (Pi-hole)│
│ android) │        └────────────┘               └────┬─────┘
└──────────┘                                          │
                                                      │ resolve
                                          ┌───────────┴───────────┐
                                          │ proxmox.internal      │
                                          │ kandidat.internal     │──► 192.168.1.70 (caddy)
                                          │ vpngate.internal      │
                                          └───────────────────────┘
                                          │ tout le reste         │──► 1.1.1.1 / 8.8.8.8
                                          └───────────────────────┘
```

**Flux DNS** :
1. Le client VPN envoie une requete DNS a `192.168.1.71` (dns-71)
2. Pi-hole verifie si le domaine est dans `custom.list` (entrees `.internal`)
3. Si oui → repond avec l'IP locale (192.168.1.70 pour les backends Caddy)
4. Si non → forward vers les upstream DNS (1.1.1.1, 8.8.8.8), avec filtrage pub

------

## 3. Specs LXC dns-71

| Parametre | Valeur |
|-----------|--------|
| CTID | 1071 |
| IP | 192.168.1.71 |
| Hostname | dns-71 |
| CPU | 1 core |
| RAM | 512 MiB |
| Disk | 8 GB SSD (local-lvm) |
| OS | Ubuntu 24.04 |
| Mode | Unprivileged + nesting |
| Start on boot | Oui |

------

## 4. Structure sous-projet `pihole/`

Pattern two-stage identique a `caddy/` :

```
pihole/
├── ansible.cfg
├── ansible/
│   ├── deploy.yml
│   ├── inventory.yml
│   ├── group_vars/pihole/
│   │   ├── all/main.yml          # Variables securite + pihole
│   │   └── vault/pihole.yml      # Mot de passe admin Pi-hole (chiffre)
│   └── roles/
│       ├── motd/
│       │   ├── defaults/main.yml
│       │   ├── tasks/main.yml
│       │   └── templates/motd.j2
│       ├── security_hardening/
│       │   ├── handlers/main.yml
│       │   └── tasks/
│       │       ├── main.yml
│       │       ├── ssh.yml
│       │       └── ufw.yml
│       └── pihole/
│           ├── defaults/main.yml
│           ├── handlers/main.yml
│           ├── tasks/main.yml
│           └── templates/
│               ├── setupVars.conf.j2
│               └── custom.list.j2
└── terraform/
    ├── main.tf
    ├── providers.tf
    ├── variables.tf
    └── outputs.tf
```

------

## 5. Terraform

### 5.1 `pihole/terraform/main.tf`

Reutilise le module `proxmox_lxc_template` (meme pattern que caddy) :

- Download du template Ubuntu 24.04 LXC
- Module `pihole_ct` avec CTID 1071, IP .71, 1 core, 512 MiB, 8 GB

### 5.2 `pihole/terraform/providers.tf`

Identique a `caddy/terraform/providers.tf` (bpg/proxmox v0.96.0).

### 5.3 `pihole/terraform/variables.tf`

Memes variables que caddy : `pm_api_url`, `pm_api_token_id`, `pm_api_token_secret`, `ct_root_password`, `ct_started`.

### 5.4 `pihole/terraform/outputs.tf`

Output `ct_ips` depuis le module.

------

## 6. Ansible

### 6.1 `ansible/deploy.yml`

```yaml
- name: Configure dns-71
  hosts: pihole
  become: true
  roles:
    - role: motd
      tags: [motd]
    - role: security_hardening
      tags: [security-hardening]
    - role: pihole
      tags: [pihole]
```

### 6.2 `ansible/inventory.yml`

```yaml
all:
  children:
    pihole:
      hosts:
        dns-71:
          ansible_host: dns-71
```

### 6.3 `group_vars/pihole/all/main.yml`

**Securite** (identique a caddy) :
- `security_ssh_hardening: true`
- `security_allow_users: "ansible"`
- `security_disable_root_login: true`
- UFW : deny incoming, allow outgoing

**Ports ouverts** :
- 22/tcp (SSH)
- 53/tcp (DNS)
- 53/udp (DNS)
- 80/tcp (interface web Pi-hole)

**Variables Pi-hole** :
- `pihole_upstream_dns`: `["1.1.1.1", "8.8.8.8"]`
- `pihole_interface`: `eth0`
- `pihole_local_records` : liste des entrees `.internal`

```yaml
pihole_local_records:
  - ip: 192.168.1.70
    domain: proxmox.internal
  - ip: 192.168.1.70
    domain: kandidat.internal
  - ip: 192.168.1.70
    domain: vpngate.internal
```

### 6.4 `group_vars/pihole/vault/pihole.yml`

Chiffre avec Ansible Vault :
- `vault_pihole_admin_password` : mot de passe admin interface web

### 6.5 Role `motd/`

Copie du role caddy avec MOTD adapte (ASCII art Pi-hole, hostname dns-71).

### 6.6 Role `security_hardening/`

Identique a caddy (SSH hardening + UFW). Seuls les ports ouverts different (53/tcp, 53/udp, 80/tcp au lieu de 80/tcp, 443/tcp).

### 6.7 Role `pihole/`

#### `defaults/main.yml`

```yaml
pihole_install_dir: /etc/pihole
pihole_custom_list: /etc/pihole/custom.list
pihole_upstream_dns:
  - "1.1.1.1"
  - "8.8.8.8"
pihole_interface: eth0
pihole_local_records: []
```

#### `tasks/main.yml`

1. Installer les prerequis (`curl`, `git`)
2. Creer `/etc/pihole/`
3. Deployer `setupVars.conf` depuis le template (config non-interactive)
4. Telecharger et executer l'installeur Pi-hole (`curl -sSL https://install.pi-hole.net | bash /dev/stdin --unattended`)
5. Deployer `custom.list` avec les entrees `.internal`
6. Definir le mot de passe admin (`pihole -a -p {{ vault_pihole_admin_password }}`)
7. Activer et demarrer `pihole-FTL` (service systemd)

#### `handlers/main.yml`

- **Restart pihole-FTL** : redemarrer le service DNS Pi-hole
- **Update gravity** : `pihole -g` (mise a jour des listes de blocage)

#### `templates/setupVars.conf.j2`

Configuration non-interactive de Pi-hole :
- `PIHOLE_INTERFACE={{ pihole_interface }}`
- `PIHOLE_DNS_1={{ pihole_upstream_dns[0] }}`
- `PIHOLE_DNS_2={{ pihole_upstream_dns[1] }}`
- `QUERY_LOGGING=true`
- `INSTALL_WEB_SERVER=true`
- `INSTALL_WEB_INTERFACE=true`
- `LIGHTTPD_ENABLED=true`
- `BLOCKING_ENABLED=true`

#### `templates/custom.list.j2`

```
{% for record in pihole_local_records %}
{{ record.ip }} {{ record.domain }}
{% endfor %}
```

------

## 7. Modifications externes

### 7.1 WireGuard DNS — `vpngate/ansible/roles/wireguard/defaults/main.yml`

```yaml
# Avant
wg_easy_default_dns: "1.1.1.1, 8.8.8.8"

# Apres
wg_easy_default_dns: "192.168.1.71"
```

Les clients VPN utiliseront dns-71 comme serveur DNS principal. Pi-hole forward les requetes non-locales vers 1.1.1.1 / 8.8.8.8.

### 7.2 Plan d'adressage IP — `docs/references/ip-addresses.md`

Ajouter `dns-71 | 192.168.1.71 | LXC Pi-hole DNS`.

### 7.3 SSH config bastion — `bastion/ansible/roles/ssh_keys/`

Ajouter `dns-71` dans la config SSH du bastion pour permettre l'acces depuis le bastion.

### 7.4 laptop-bootstrap — `roles/bootstrap/vars/main/ip_hosts.yml`

Supprimer les 3 entrees `.internal` migrees precedemment (proxmox.internal, kandidat.internal, vpngate.internal). Le DNS Pi-hole s'en charge maintenant. Le laptop recevra le DNS via WireGuard.

------

## 8. Ports UFW

| Port | Proto | Usage |
|------|-------|-------|
| 22 | tcp | SSH |
| 53 | tcp | DNS |
| 53 | udp | DNS |
| 80 | tcp | Interface web Pi-hole |

------

## 9. ADR

Un fichier `docs/adr/pihole.md` avec :

**ADR-001 : Pi-hole natif (pas Docker)**

| Critere | Pi-hole natif (choisi) | Pi-hole Docker |
|---------|----------------------|----------------|
| Coherence | Pattern LXC natif (comme caddy-70) | Docker dans LXC = complexe (nesting, cgroups) |
| Ressources | ~50 MiB RAM | ~150 MiB RAM (overhead Docker) |
| Installation | Script officiel + setupVars.conf | docker-compose.yml |
| Mise a jour | `pihole -up` | Pull image Docker |

------

## 10. Decisions de design

| Decision | Choix | Raison |
|----------|-------|--------|
| Hebergement | LXC dedie (dns-71) | Separation des responsabilites, cout negligeable |
| Service | Pi-hole natif | Coherent avec pattern LXC, leger, UI web + ad-blocking |
| Scope DNS | 3 backends .internal uniquement | Scope minimal, extensible plus tard |
| Upstream DNS | 1.1.1.1, 8.8.8.8 | DNS publics rapides pour les requetes non-locales |
| Admin password | Ansible Vault | Secret, coherent avec les conventions du projet |
| Distribution DNS | Via WireGuard `wg_easy_default_dns` | Tous les clients VPN recoivent automatiquement dns-71 |
