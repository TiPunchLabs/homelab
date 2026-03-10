# Architecture du Homelab

## Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              RESEAU LOCAL (192.168.1.0/24)                        │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────┐    ┌──────────────────────────────┐    ┌────────────────┐  │
│  │   POSTE LOCAL   │    │         PROXMOX VE           │    │  NAS SYNOLOGY  │  │
│  │  192.168.1.x       │    │         192.168.1.26            │    │  192.168.1.93     │  │
│  │                 │    │                              │    │                │  │
│  │  - Caddy Proxy  │    │  ┌────────────────────────┐  │    │  - Stockage    │  │
│  │  - Docker local │    │  │ bastion-60  192.168.1.60  │  │    │  - Backups     │  │
│  │  - Dev tools    │    │  │ GitLab Runner (shell)   │  │    │  - Media       │  │
│  │                 │    │  ├────────────────────────┤  │    └────────────────┘  │
│  └────────┬────────┘    │  │ dockhost-50 192.168.1.50  │  │                        │
│           │             │  │ Docker, GitLab Runner   │  │                        │
│           │             │  ├────────────────────────┤  │                        │
│           │             │  │ kubecluster-40 .40     │  │                        │
│           │             │  │ kubecluster-41 .41     │  │                        │
│           │             │  │ kubecluster-42 .42     │  │                        │
│           │             │  └────────────────────────┘  │                        │
│           │             └──────────────────────────────┘                        │
│           │                                                                      │
│           │             ┌─────────────────────────────────┐                     │
│           │             │   RESEAU VAGRANT (192.168.122.0/24)│                     │
│           │             │                                 │                     │
│           └─────────────│  k8s-controlplan  192.168.122.70   │                     │
│                         │  k8s-node1        192.168.122.71   │                     │
│                         │  k8s-node2        192.168.122.72   │                     │
│                         └─────────────────────────────────┘                     │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Composants principaux

### 1. Proxmox VE (Hyperviseur)

**Adresse**: 192.168.1.26
**Interface web**: https://192.168.1.26:8006
**SSH**: `ssh pve` (user: root)

Proxmox Virtual Environment est l'hyperviseur principal qui heberge toutes les VMs de production.

**Caracteristiques**:
- Virtualisation KVM
- Conteneurs LXC
- Stockage local et distant
- API REST pour automatisation (provider Terraform bpg/proxmox)

**Template de base**:
- ID: **9001**
- Nom: `ubuntu-2404-cloudinit-template`
- OS: Ubuntu 24.04 Server (cloud-init)

### 2. NAS Synology

**Adresse**: 192.168.1.93
**Interface DSM**: http://192.168.1.93:5000
**SSH**: `ssh nas` (user: xgueret)

Stockage reseau pour sauvegardes, fichiers partages et media.

### 3. Poste local

Le poste de travail local execute:
- **Caddy** : Reverse proxy pour les domaines .local
- **Docker** : Services de developpement
- **Vagrant/libvirt** : Cluster Kubernetes local

---

## Architecture des VMs Proxmox

### Schema des VMs

```
PROXMOX VE (192.168.1.26)
│
├── Template: ubuntu-2404-cloudinit-template (ID: 9001)
│
├── BASTION (Plan de controle)
│   └── bastion-60 (ID: 9060) ─── 192.168.1.60
│       ├── GitLab Runner (shell executor, systemd)
│       ├── Terraform + Ansible
│       └── pass + GPG (secrets management)
│
├── DOCKHOST (Docker services)
│   └── dockhost-50 (ID: 9050) ─── 192.168.1.50
│       ├── Docker Engine
│       ├── Portainer Agent
│       └── GitLab Runner (Docker executor)
│
└── KUBECLUSTER (Kubernetes kubeadm)
    ├── kubecluster-40 (ID: 9040) ─── 192.168.1.40 [Control Plane]
    ├── kubecluster-41 (ID: 9041) ─── 192.168.1.41 [Worker 1]
    └── kubecluster-42 (ID: 9042) ─── 192.168.1.42 [Worker 2]
```

### Specifications des VMs

| VM | vCPU | RAM | Disque | Usage |
|----|------|-----|--------|-------|
| bastion-60 | 2 | 2 GB | 25 GB | Bastion, GitLab Runner (shell) |
| dockhost-50 | 3 | 10 GB | 100 GB | Docker services (Portainer, GitLab Runner) |
| kubecluster-40 | 2 | 4 GB | 35 GB | K8s Control Plane |
| kubecluster-41 | 1 | 3.5 GB | 30 GB | K8s Worker |
| kubecluster-42 | 1 | 3.5 GB | 30 GB | K8s Worker |

---

## Architecture du Reverse Proxy Caddy

Caddy s'execute en local et route le trafic vers les differents backends.

```
                    ┌─────────────────────────────────────┐
                    │         CADDY REVERSE PROXY         │
                    │      (Docker - mode host network)   │
                    │           Ports 80, 443             │
                    └──────────────────┬──────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        ▼                              ▼                              ▼
┌───────────────────┐    ┌─────────────────────────┐    ┌─────────────────────┐
│  SERVICES DOCKER  │    │   EQUIPEMENTS RESEAU    │    │   CLUSTER K8S       │
│  (host.docker.    │    │                         │    │   (Vagrant)         │
│   internal)       │    │                         │    │                     │
├───────────────────┤    ├─────────────────────────┤    ├─────────────────────┤
│ syncthing:8384    │    │ nas: 192.168.1.93:5000  │    │ traefik:30928       │
│ portainer:9000    │    │ proxmox: 192.168.1.26   │    │ prometheus:30928    │
│ excalidraw:8082   │    │          :8006 (HTTPS)  │    │ grafana:30928       │
│ openwebui:8080    │    │                         │    │ alertmanager:30928  │
│ n8n:5678          │    │                         │    │                     │
└───────────────────┘    └─────────────────────────┘    └─────────────────────┘
```

**Configuration**: `~/caddy-proxy/Caddyfile`

---

## Architecture Kubernetes Vagrant

Cluster Kubernetes local pour tests et developpement.

```
┌────────────────────────────────────────────────────────────┐
│              RESEAU LIBVIRT (192.168.122.0/24)             │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │           k8s-controlplan (192.168.122.70)         │   │
│  │  - API Server, Controller Manager, Scheduler, etcd │   │
│  └────────────────────────┬───────────────────────────┘   │
│              ┌────────────┴────────────┐                  │
│              ▼                         ▼                  │
│  ┌───────────────────────┐  ┌───────────────────────┐    │
│  │ k8s-node1             │  │ k8s-node2             │    │
│  │ (192.168.122.71)      │  │ (192.168.122.72)      │    │
│  │ Kubelet, Kube-proxy   │  │ Kubelet, Kube-proxy   │    │
│  │ Containerd            │  │ Containerd            │    │
│  │                       │  │                       │    │
│  │ Services exposes:     │  │                       │    │
│  │ Traefik, Prometheus   │  │                       │    │
│  │ Grafana, AlertManager │  │                       │    │
│  └───────────────────────┘  └───────────────────────┘    │
│                                                            │
└────────────────────────────────────────────────────────────┘

Emplacement: ~/vagrant-k8s-cluster/
```

---

## Stack technologique

### Infrastructure as Code

| Outil | Usage |
|-------|-------|
| **Terraform** (>= 1.11.0) | Provisionnement VMs sur Proxmox |
| **Provider bpg/proxmox** (>= 0.93.0) | API Proxmox |
| **Ansible** (>= 13.2.0) | Configuration et deploiement services |
| **Ansible Vault** | Gestion des secrets (via `pass`) |

### Containerisation

| Outil | Usage |
|-------|-------|
| **Docker** + **Docker Compose** | Runtime et orchestration (dockhost) |
| **Kubernetes** (kubeadm) | Orchestration cluster (kubecluster) |
| **Containerd** | Runtime K8s |

### Reseau

| Outil | Usage |
|-------|-------|
| **Caddy** | Reverse proxy local (.local) |

---

## Structure du projet IaC

```
~/homelab/
│
├── .gitlab-ci.yml               # CI: ansible-lint, terraform, shellcheck, trivy
├── .pre-commit-config.yaml      # Pre-commit hooks
├── pyproject.toml               # Dependances Python (uv)
├── .envrc                       # direnv: secrets via pass
│
├── modules/
│   └── proxmox_vm_template/     # Module Terraform partage
│       ├── main.tf              # Resource proxmox_virtual_environment_vm
│       ├── variables.tf         # 17 variables (vm_*, project_description)
│       └── outputs.tf
│
├── scripts/
│   ├── ansible-vault-pass.sh    # Recupere le password vault via pass
│   └── check_ansible_vault.sh   # Pre-commit: verifie le chiffrement vault
│
├── proxmox/                     # Configuration hyperviseur
│   └── ansible/
│       ├── deploy.yml           # Tags: security_ssh_hardening, generate_vm_template
│       └── roles/
│           ├── configure/       # SSH, tokens, storage, VM templates
│           └── manage/          # Verification tokens
│
├── dockhost/                    # VM Docker services
│   ├── terraform/               # Provisionnement (1 VM)
│   └── ansible/
│       ├── deploy.yml           # Tags: motd, docker, portainer-agent, gitlab-runner
│       └── roles/
│           ├── motd/
│           ├── docker/
│           ├── portainer_agent/
│           ├── postgresql/
│           ├── security_hardening/
│           └── gitlab_runner/
│
├── bastion/                     # Bastion VM (plan de controle)
│   ├── terraform/               # Provisionnement (1 VM)
│   └── ansible/
│       ├── deploy.yml           # Tags: motd, security-hardening, tooling, ssh-keys, gitlab-runner
│       └── roles/
│           ├── motd/
│           ├── security_hardening/
│           ├── tooling/
│           ├── ssh_keys/
│           └── gitlab_runner/
│
└── kubecluster/                 # Cluster Kubernetes (3 VMs)
    ├── terraform/               # Provisionnement (1 CP + 2 workers)
    └── ansible/
        ├── deploy.yml           # 3 plays: all, control_plane, workers
        └── roles/               # 10 roles ordonnes
            ├── motd/
            ├── cfg_nodes/
            ├── inst_runc/
            ├── inst_cni/
            ├── cfg_containerd/
            ├── inst_cri_tools/
            ├── cfg_kubeadm_kubelet_kubectl/
            ├── init_kubeadm/
            ├── kubectl_cheat_sheet/
            └── join_workers/
```

---

## Flux de deploiement

### Pattern two-stage deployment

```
1. TERRAFORM                    2. ANSIBLE                     3. VERIFICATION
   (Provisionnement)               (Configuration)                (Tests)

┌─────────────────────┐       ┌─────────────────────┐       ┌─────────────────────┐
│ cd <projet>/terraform│       │ cd <projet>          │       │ ssh <vm>            │
│ terraform init      │  ───► │ ansible-playbook     │  ───► │ docker ps           │
│ terraform plan      │       │   ansible/deploy.yml │       │ systemctl status    │
│ terraform apply     │       │                     │       │                     │
└─────────────────────┘       └─────────────────────┘       └─────────────────────┘

        │                             │
        ▼                             ▼
   Cree la VM                    Configure:
   sur Proxmox                   - Packages
   avec cloud-init               - Docker / Kubernetes
   (user ansible +               - Services
    SSH key)                     - Securite
```

### Pipeline type (dockhost)

```bash
# 1. Provisionnement
cd dockhost/terraform
terraform init && terraform plan && terraform apply

# 2. Configuration
cd ..
ansible-playbook ansible/deploy.yml

# 3. Verification
ssh dockhost-50
docker ps
```

---

## Securite

### Gestion des secrets

| Outil | Usage |
|-------|-------|
| **pass** (password-store) | Stockage cles, tokens, mots de passe |
| **Ansible Vault** | Chiffrement des variables sensibles dans le repo |
| **direnv (.envrc)** | Export des `TF_VAR_*` depuis `pass` |
| **GitLab CI/CD Variables** | Secrets CI/CD |

**Vault password**: `pass show ansible/vault` (via `scripts/ansible-vault-pass.sh`)

### Acces SSH

- Authentification par cle uniquement
- Cles separees par service/equipement
- Configuration centralisee dans `~/.ssh/config`
- User cloud-init: `ansible` (sudo sans mot de passe)

### CI/CD Security

- Vault files: verification du chiffrement en CI
- Scan de secrets hardcodes dans le code
- Scan Trivy des images Docker (severite HIGH+CRITICAL)
- Images Docker pinnees par digest SHA256
