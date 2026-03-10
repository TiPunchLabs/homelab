# Services deployes

## Vue d'ensemble

```
PROXMOX VE (192.168.1.26)
│
├── BASTION (bastion-60 / 192.168.1.60)
│   ├── GitLab Runner (shell executor, systemd)
│   ├── Terraform + Ansible (execution operationnelle)
│   └── pass + GPG (secrets management)
│
├── DOCKHOST (dockhost-50 / 192.168.1.50)
│   ├── Docker Engine
│   ├── Portainer Agent ──► Gere par Portainer (poste local)
│   └── GitLab Runner (Docker executor)
│
└── KUBECLUSTER (192.168.1.40-42)
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
| IP | 192.168.1.50 |
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
| `postgresql` | `postgresql` | PostgreSQL 17.4 (port 5432) |
| `security_hardening` | `security-hardening` | Hardening SSH, UFW, securite systeme |
| `gitlab_runner` | `gitlab-runner` | GitLab Runner (Docker executor) |

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

### GitLab Runner (Docker executor)

Runner GitLab CI pour le projet **tipunchlabs/homelab**.

**Details** :
- Executor : Docker
- Installation : `/opt/gitlab-runner/docker-compose.yml` + `config/config.toml`
- Token : stocke dans Ansible Vault

**Variable vault requise** : `vault_gitlab_runner_token` dans `dockhost/ansible/group_vars/dockhost/vault/config.yml`

**Deploiement** :
1. Enregistrer le runner sur GitLab (token de projet ou groupe)
2. Chiffrer le token avec `ansible-vault encrypt` dans le fichier vault
3. Deployer avec `ansible-playbook ansible/deploy.yml --tags gitlab-runner`
4. Verifier dans GitLab > Settings > CI/CD > Runners

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

## Bastion (bastion-60)

### Specifications

| Parametre | Valeur |
|-----------|--------|
| VMID | 9060 |
| IP | 192.168.1.60 |
| OS | Ubuntu 24.04 (cloud-init) |
| vCPU | 2 |
| RAM | 2 GB |
| Disque | 25 GB SSD |
| SSH | `ssh bastion-60` (user: ansible) |

### Roles Ansible deployes

Le playbook `bastion/ansible/deploy.yml` execute les roles suivants :

| Role | Tag | Description |
|------|-----|-------------|
| `motd` | `motd` | Message of the Day personnalise |
| `security_hardening` | `security-hardening` | Hardening SSH + UFW |
| `tooling` | `tooling` | Python, uv, Terraform, direnv, pass, GPG, git clone homelab |
| `ssh_keys` | `ssh-keys` | Deploiement cles SSH + config pour tous les hosts |
| `gitlab_runner` | `gitlab-runner` | GitLab Runner natif (shell executor, systemd) |

### GitLab Runner (shell executor)

Runner natif installe directement sur la VM (pas de Docker).

**Details** :
- Executor : Shell (bash)
- Service : systemd (`gitlab-runner.service`)
- User : `ansible`
- Working directory : `/opt/gitlab-runner`
- Config : `/opt/gitlab-runner/config.toml`

Le runner execute le job `sync-bastion` qui synchronise le clone `~/homelab` sur le bastion a chaque push sur `main`.

### Tooling installe

| Outil | Usage |
|-------|-------|
| **Terraform** | Provisionnement infrastructure |
| **Ansible** (via uv) | Configuration et deploiement |
| **pass** + GPG | Gestion des secrets (cle GPG sans passphrase) |
| **direnv** | Auto-activation venv et variables |
| **git** | Clone `~/homelab` pour execution operationnelle |

---

## Kubecluster (kubecluster-40/41/42)

### Specifications

| Node | Role | VMID | IP | vCPU | RAM | Disque |
|------|------|------|-----|------|-----|--------|
| kubecluster-40 | Control Plane | 9040 | 192.168.1.40 | 2 | 4 GB | 35 GB |
| kubecluster-41 | Worker | 9041 | 192.168.1.41 | 1 | 3.5 GB | 30 GB |
| kubecluster-42 | Worker | 9042 | 192.168.1.42 | 1 | 3.5 GB | 30 GB |

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
- **Web UI** : https://192.168.1.26:8006

---

## Securite des images Docker

Toutes les images Docker sont pinnees par **digest SHA256** pour garantir l'integrite :

```yaml
# Exemple
image: portainer/agent:2.33.3@sha256:1da68e0e...
```

Le CI execute un scan **Trivy** (v0.69.3) sur toutes les images extraites des templates Jinja2, avec severite `HIGH,CRITICAL`.
