# 🌐 Migration réseau homelab : 192.168.1.0/24 → 192.168.10.0/24

> **Objectif** : basculer l'ensemble du homelab (Proxmox + 8 VMs/LXCs + IaC) du subnet historique `192.168.1.0/24` vers le nouveau subnet `192.168.10.0/24` à la suite d'un changement de box opérateur.
>
> **Prérequis** :
> - Proxmox déjà accessible en `192.168.10.100`
> - Box opérateur en `192.168.10.1` (gateway + DNS pendant la transition)
> - Pool DHCP de la box reconfiguré sur `192.168.10.200-250` (libère la plage statique infra)
> - Laptop opérateur connecté au WiFi `WE-600E` ou `WE-600E-5G` pour être dans le même subnet
>
> **Durée estimée** : 2 à 3 heures hors imprévus.
>
> **Rédigé le** : 2026-04-28
> **Auteur** : Xavier Gueret
> **Version** : 1.0

## 📖 Contexte

La box opérateur a changé. Le nouveau LAN est `192.168.10.0/24`, gateway `192.168.10.1`. L'IP physique du Proxmox a été migrée manuellement vers `192.168.10.100` (déjà fait). Toutes les VMs et LXCs gérées par cette infrastructure ont leur IP figée par cloud-init au premier boot et restent configurées en `192.168.1.x` — donc actuellement injoignables.

Cette migration vise à :
1. Mettre à jour l'IaC (Terraform + Ansible) pour refléter le nouveau plan d'adressage.
2. Reconfigurer chaque OS invité in-place (sans destroy/recreate) pour préserver les volumes Docker, l'état etcd K8s, les clés WireGuard server, le runner GitLab et le store `pass`/GPG du bastion.
3. Re-converger via Ansible pour aligner la conf OS sur l'IaC.

## 🎯 Plan d'adressage cible

| Host | Type | Avant | Après |
|---|---|---|---|
| Box opérateur (gateway) | — | 192.168.1.1 | **192.168.10.1** |
| Pool DHCP | — | (default box) | **192.168.10.200 → 192.168.10.250** |
| pve (Proxmox) | hyperviseur | 192.168.1.100 | **192.168.10.100** ✅ déjà fait |
| kubebeast-40 | VM (control plane) | 192.168.1.40 | 192.168.10.40 |
| kubebeast-41 | VM (worker) | 192.168.1.41 | 192.168.10.41 |
| kubebeast-42 | VM (worker) | 192.168.1.42 | 192.168.10.42 |
| vpngate-50 | VM | 192.168.1.50 | 192.168.10.50 |
| bastion-60 | VM | 192.168.1.60 | 192.168.10.60 |
| caddy-70 | LXC | 192.168.1.70 | 192.168.10.70 |
| dns-71 (pihole) | LXC | 192.168.1.71 | 192.168.10.71 |
| dockhost-90 | VM | 192.168.1.90 | 192.168.10.90 |
| Ollama (laptop) | service externe | 192.168.1.101 | 192.168.10.101 |

**Règle** : on conserve les derniers octets — seul le 3e octet change (`1` → `10`).

------

## 🏗️ Approche retenue : in-place reconfiguration

### Pourquoi pas un destroy/recreate Terraform

Détruire les VMs effacerait :
- Volumes Docker de `dockhost-90` (Postgres, kandidat, miniboard, Komodo état, Open WebUI, Excalidraw…)
- État etcd du control plane K8s
- Clés WireGuard server (forçant la régénération de tous les clients VPN)
- Store `pass` + clés GPG du bastion
- Enregistrement du GitLab Runner (token consommé)

### Méthode

| Cible | Technique |
|---|---|
| **VMs** | Console noVNC Proxmox → édition `/etc/netplan/50-cloud-init.yaml` → `netplan apply` |
| **LXCs** | Depuis l'hôte Proxmox → `pct set <ctid> -net0 ...` → `pct reboot` |

Pour les VMs, on désactive aussi l'override cloud-init pour éviter qu'un reboot ultérieur ne réécrase la conf manuelle.

------

## 🔄 Phasage

```
Phase 1 — Préparation IaC (laptop)         ← aucune VM touchée
   ↓
Phase 2 — Bascule réseau VM/LXC            ← console Proxmox
   ↓
Phase 3 — Re-convergence Ansible           ← Ansible depuis le laptop
   ↓
Phase 4 — Commit / MR / merge
   ↓
Phase 5 — Reprise du WIP Komodo (post-merge)
```

------

### Phase 1 — Préparation IaC

#### 1.1 Pré-flight Git

```bash
cd /home/xgueret/Workspace/02-infrastructure/homelab
git stash push -u -m "wip-komodo-pre-network-migration"
git checkout -b chore/network-migration-192-168-10
```

Le `-u` inclut le dossier non tracké `dockhost/ansible/roles/komodo/`.

#### 1.2 Substitution `192.168.1.X` → `192.168.10.X`

Mêmes derniers octets partout. Fichiers concernés :

| # | Fichier | Lignes |
|---|---|---|
| 1 | `.envrc` | 13, 38 |
| 2 | `~/.ssh/config` | hôtes `vpngate-50, bastion-60, caddy-70, dns-71, dockhost-90, kubebeast-40/41/42` |
| 3 | `proxmox/ansible/inventory.yml` | 6 |
| 4 | `dockhost/ansible/inventory.yml` | 9 |
| 5 | `dockhost/ansible/group_vars/dockhost/all/main.yml` | 44 |
| 6 | `caddy/ansible/group_vars/caddy/all/main.yml` | 23, 28, 32, 36, 40, 44, 48, 52 |
| 7 | `pihole/ansible/group_vars/pihole/all/main.yml` | 22-36 (8 records) |
| 8 | `vpngate/ansible/roles/wireguard/defaults/main.yml` | 8 |
| 9 | `modules/proxmox_vm_template/variables.tf` | 64 |
| 10 | `modules/proxmox_lxc_template/variables.tf` | 107 |
| 11 | `docs/references/ip-addresses.md` | tout |

> ⚠️ **Note Komodo** : `dockhost/ansible/roles/komodo/defaults/main.yml` (komodo_host) fait partie du WIP stashed. Il sera traité en Phase 5.

#### 1.3 Vérification

```bash
grep -rn "192\.168\.1\.[0-9]" --include="*.yml" --include="*.yaml" --include="*.tf" --include="*.cfg" .envrc 2>/dev/null
# Aucun hit attendu en dehors de commentaires/exemples
```

------

### Phase 2 — Bascule réseau

Ordre par priorité fonctionnelle :

| # | Host | Type | Priorité | Raison |
|---|---|---|---|---|
| 1 | `dockhost-90` | VM | 🔴 Critique | Komodo + Postgres + apps |
| 2 | `dns-71` | LXC | 🟠 Haute | Restore résolution `.internal` |
| 3 | `caddy-70` | LXC | 🟠 Haute | Restore reverse proxy |
| 4 | `bastion-60` | VM | 🟡 Moyenne | GitLab Runner CI |
| 5 | `vpngate-50` | VM | 🟡 Moyenne | VPN (clients à régénérer ensuite) |
| 6 | `kubebeast-40` | VM | 🟢 Basse | Control plane K8s |
| 7 | `kubebeast-41` | VM | 🟢 Basse | Worker K8s |
| 8 | `kubebeast-42` | VM | 🟢 Basse | Worker K8s |

#### 2.1 Procédure VM (×6)

```bash
# 1. Console noVNC : Proxmox UI → VM → Console
# 2. Login (ansible ou root)
# 3. Désactiver l'override cloud-init (une fois)
echo 'network: {config: disabled}' | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

# 4. Éditer netplan
sudo nano /etc/netplan/50-cloud-init.yaml
```

Format cible (Ubuntu 24.04, `gateway4` est déprécié) :

```yaml
network:
  version: 2
  ethernets:
    eth0:
      addresses: [192.168.10.<N>/24]
      routes:
        - to: default
          via: 192.168.10.1
      nameservers:
        addresses: [192.168.10.1]
```

```bash
# 5. Appliquer
sudo netplan apply

# 6. Vérifier
ip a && ip r && ping -c 2 192.168.10.1

# 7. Depuis le laptop
ssh <host>
```

#### 2.2 Procédure LXC (×2)

```bash
# Depuis le laptop
ssh pve

# Lire la conf actuelle pour récupérer hwaddr et bridge
pct config 1070 | grep ^net0   # caddy
pct config 1071 | grep ^net0   # pihole

# Appliquer la nouvelle IP (remplacer <MAC> et <N>)
pct set <CTID> -net0 "name=eth0,bridge=vmbr0,hwaddr=<MAC>,ip=192.168.10.<N>/24,gw=192.168.10.1,type=veth,firewall=1"
pct reboot <CTID>

# Vérifier
pct exec <CTID> -- ip a
```

#### 2.3 Validation post-bascule (chaque hôte)

```bash
ping -c 2 <new-ip>
ssh <host> "hostname && ip -4 addr show eth0 | grep inet"
```

------

### Phase 3 — Re-convergence Ansible

```bash
direnv reload   # PROXMOX_IP et TF_VAR_pm_api_url

ansible-playbook dockhost/ansible/deploy.yml
ansible-playbook pihole/ansible/deploy.yml
ansible-playbook caddy/ansible/deploy.yml
ansible-playbook bastion/ansible/deploy.yml
ansible-playbook vpngate/ansible/deploy.yml
ansible-playbook kubecluster/ansible/deploy.yml
```

#### Smoke tests

| Test | Commande |
|---|---|
| Proxmox API | `curl -k https://192.168.10.100:8006/api2/json/version` |
| Pi-hole résolution `.internal` | `dig @192.168.10.71 portainer.internal +short` |
| Caddy reverse proxy | `curl -kI https://portainer.internal --resolve portainer.internal:443:192.168.10.70` |
| K8s | `kubectl get nodes` (sur control plane) |

#### Effets collatéraux à traiter

1. **Clients WireGuard** — tous les `.conf` distribués (téléphones, laptops) pointent vers l'ancien Endpoint. À régénérer + redistribuer manuellement après remise en route de `vpngate-50`.
2. **SSH known_hosts** — `ssh-keygen -R <ancienne-ip>` et `ssh-keygen -R <hostname>` si warning MITM.
3. **Komodo webhook** — uniquement si la définition Komodo Core utilisait l'IP nue de dockhost. Si c'est `komodo.internal` (hostname), rien à faire.

------

### Phase 4 — Commit / MR / merge

```bash
pre-commit run --all-files
ansible-lint dockhost/ansible/ caddy/ansible/ pihole/ansible/ bastion/ansible/ vpngate/ansible/ kubecluster/ansible/ proxmox/ansible/
terraform fmt -check -recursive

git add -A
git commit -m "chore(network): migrer infrastructure vers 192.168.10.0/24"
git push -u origin chore/network-migration-192-168-10
# Créer la MR sur GitLab → review → merge
```

------

### Phase 5 — Reprise du WIP Komodo

```bash
git checkout main && git pull
git stash pop

# Substitution dans les fichiers Komodo :
#   - dockhost/ansible/roles/komodo/defaults/main.yml (komodo_host)
#   - tout autre fichier dépoppé contenant 192.168.1.

git checkout -b feat/komodo
git add -A && git commit -m "infra(komodo): ajouter role Komodo Core"
ansible-playbook dockhost/ansible/deploy.yml --tags komodo
git push -u origin feat/komodo
```

------

## 🔧 Troubleshooting

| Symptôme | Cause probable | Action |
|---|---|---|
| VM injoignable après `netplan apply` | Override cloud-init non désactivé, ou `eth0` ≠ vrai nom NIC | Re-console, `ip link` pour le vrai nom, retoucher netplan |
| Pi-hole résout en 192.168.1.x | Records statiques pas rechargés | Re-run `ansible-playbook pihole/ansible/deploy.yml --tags pihole` |
| Caddy en 502 | Upstreams toujours en 192.168.1.x | Vérifier `caddy/ansible/group_vars/caddy/all/main.yml` puis re-run playbook |
| `terraform apply` veut tout recréer | Provider relit le nouvel endpoint mais state désaligné | `terraform refresh` puis `plan` ; ne pas `apply` un destroy/create surprise |
| Box redistribue `.100` ou `.101` à un client | Pool DHCP pas appliqué, ou bail toujours actif | Vérifier statut DHCP, déconnecter/reconnecter le client fautif |

------

## ✅ Critères de succès

- [ ] Proxmox API joignable sur `https://192.168.10.100:8006`
- [ ] Les 8 VMs/LXCs joignables via SSH par leur alias
- [ ] `dig @192.168.10.71 *.internal` retourne `192.168.10.70`
- [ ] Toutes les routes Caddy répondent (200/301/401 — pas 502/timeout)
- [ ] `kubectl get nodes` retourne 3 nodes Ready
- [ ] WireGuard server up, configs clients régénérées
- [ ] Tous les playbooks Ansible repassent en vert
- [ ] Aucune occurrence de `192.168.1.` dans les fichiers de config (hors commentaires)
- [ ] MR mergée sur `main`
- [ ] WIP Komodo dépopppé et committé séparément en Phase 5

------

## 📚 Ressources

- `docs/references/ip-addresses.md` — plan d'adressage de référence (à mettre à jour en premier)
- [Netplan Ubuntu 24.04 — `routes` syntax](https://netplan.readthedocs.io/en/stable/netplan-yaml/)
- [Proxmox `pct` man page](https://pve.proxmox.com/pve-docs/pct.1.html)

> **Document créé le** : 2026-04-28
> **Auteur** : Xavier Gueret
> **Version** : 1.0
