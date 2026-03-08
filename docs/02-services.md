# Services deployes

## Vue d'ensemble

```
PROXMOX VE (10.0.1.26)
│
├── DOCKHOST (dockhost-50 / 10.0.1.50)
│   ├── Docker Engine
│   ├── Portainer Agent ──► Gere par Portainer (poste local)
│   └── GitHub Actions Runner ──► Self-hosted pour <github-org>
│
└── KUBECLUSTER (10.0.1.40-42)
    ├── Control Plane (kubecluster-40)
    │   └── etcd, API Server, Controller Manager, Scheduler
    └── Workers (kubecluster-41, kubecluster-42)
        └── Kubelet, Kube-proxy, Containerd
```

---

## Dockhost (dockhost-50)

### Specifications

| Parametre | Valeur |
|-----------|--------|
| VMID | 9050 |
| IP | 10.0.1.50 |
| OS | Ubuntu 24.04 (cloud-init) |
| vCPU | 3 |
| RAM | 10 GB |
| Disque | 100 GB SSD |
| SSH | `ssh dockhost-50` (user: ansible) |

### Roles Ansible deployes

Le playbook `dockhost/ansible/deploy.yml` execute les roles suivants :

| Role | Tag | Description |
|------|-----|-------------|
| `motd` | `motd` | Message of the Day personnalise |
| `docker` | `docker` | Installation Docker Engine + Docker Compose |
| `portainer_agent` | `portainer-agent` | Agent Portainer pour gestion centralisee |
| `github_runner` | `github-runner` | Runner GitHub Actions self-hosted |
| `security_hardening` | - | Hardening SSH, UFW, securite systeme |

### Portainer Agent

Agent Portainer pour gerer Docker a distance depuis l'instance Portainer du poste local.

```
Portainer (poste local) ──► Portainer Agent (dockhost-50:9001)
                                    │
                                    ▼
                              Docker Engine
```

**Details** :
- Image : `portainer/agent:2.33.3` (pinnee par digest SHA256)
- Port expose : `9001`
- Volumes : socket Docker + volumes Docker
- Reseau : `vm-docker-90-net` (bridge)
- Installation : `/opt/portainer-agent/docker-compose.yml`

### GitHub Actions Runner

Runner self-hosted pour l'organisation **<github-org>** sur GitHub.

**Details** :
- Image : `myoung34/github-runner:2.332.0` (pinnee par digest SHA256)
- Scope : Organisation (`<github-org>`)
- Authentification : PAT classique (stocke dans Ansible Vault)
- Labels : `self-hosted,linux,docker,homelab`
- Mode : Persistent (non ephemere)
- Installation : `/opt/github-runner/docker-compose.yml`

**Variable vault requise** : `vault_github_runner_pat` dans `dockhost/ansible/group_vars/dockhost/vault/config.yml`

**Configuration GitHub** :
1. Creer un PAT classique avec scope `admin:org`
2. Chiffrer avec `ansible-vault encrypt` dans le fichier vault
3. Deployer avec `ansible-playbook ansible/deploy.yml --tags github-runner`
4. Verifier dans GitHub > Organisation > Settings > Actions > Runners

### Security Hardening

Configuration de securite appliquee sur la VM :
- SSH : authentification par cle uniquement, root login desactive
- UFW : deny incoming par defaut, ports ouverts : SSH (22), Portainer Agent (9001)
- Users autorises configures via Ansible Vault

### Pre-tasks

Avant l'execution des roles, le playbook cree :
- Groupe `app_data` pour les applications
- Repertoire `/app/data/` (owner: root, group: app_data, mode: 0770)

---

## Kubecluster (kubecluster-40/41/42)

### Specifications

| Node | Role | VMID | IP | vCPU | RAM | Disque |
|------|------|------|-----|------|-----|--------|
| kubecluster-40 | Control Plane | 9040 | 10.0.1.40 | 2 | 4 GB | 35 GB |
| kubecluster-41 | Worker | 9041 | 10.0.1.41 | 1 | 3.5 GB | 30 GB |
| kubecluster-42 | Worker | 9042 | 10.0.1.42 | 1 | 3.5 GB | 30 GB |

### Roles Ansible deployes

Le playbook `kubecluster/ansible/deploy.yml` contient 3 plays :

**Play 1 : tous les noeuds** (`hosts: all`)

| Role | Tag | Description |
|------|-----|-------------|
| `motd` | `motd` | Message of the Day |
| `cfg_nodes` | `cfg_nodes` | Configuration systeme des noeuds |
| `inst_runc` | `inst_runc` | Installation runc |
| `inst_cni` | `inst_cni` | Installation CNI plugins |
| `cfg_containerd` | `cfg_containerd` | Configuration containerd |
| `inst_cri_tools` | `inst_cri_tools` | Installation CRI tools (crictl) |
| `cfg_kubeadm_kubelet_kubectl` | `cfg_kubeadm_kubelet_kubectl` | Installation kubeadm, kubelet, kubectl |

**Play 2 : control plane** (`hosts: control_plane_nodes`)

| Role | Tag | Description |
|------|-----|-------------|
| `init_kubeadm` | `init_kubeadm` | Initialisation du cluster avec kubeadm |
| `kubectl_cheat_sheet` | `kubectl_cheat_sheet` | Aliases et completion kubectl |

**Play 3 : workers** (`hosts: worker_nodes`)

| Role | Tag | Description |
|------|-----|-------------|
| `join_workers` | `join_workers` | Jonction des workers au cluster |

### Inventaire

```yaml
kubecluster:
  children:
    control_plane_nodes:
      hosts:
        kubecluster-40:
    worker_nodes:
      hosts:
        kubecluster-41:
        kubecluster-42:
```

---

## Proxmox (configuration hyperviseur)

### Roles Ansible

Le playbook `proxmox/ansible/deploy.yml` configure l'hyperviseur Proxmox :

| Role | Tag | Description |
|------|-----|-------------|
| `configure` | `configure` | SSH hardening, tokens API, storage, templates VM |
| `manage` | `manage` | Verification des tokens et permissions |

### Acces

- **SSH** : `ssh pve` (user: root)
- **Web UI** : https://10.0.1.26:8006

---

## Securite des images Docker

Toutes les images Docker sont pinnees par **digest SHA256** pour garantir l'integrite :

```yaml
# Exemple
image: portainer/agent:2.33.3@sha256:1da68e0e...
```

Le CI execute un scan **Trivy** (v0.69.3) sur toutes les images extraites des templates Jinja2, avec severite `HIGH,CRITICAL`.
