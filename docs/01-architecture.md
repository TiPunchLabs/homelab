# Homelab Architecture

## Overview

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              LOCAL NETWORK (192.168.1.0/24)                       │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────┐    ┌──────────────────────────────┐    ┌────────────────┐  │
│  │   LOCAL MACHINE │    │         PROXMOX VE           │    │  NAS SYNOLOGY  │  │
│  │  192.168.1.x       │    │         192.168.1.100            │    │  192.168.1.93     │  │
│  │                 │    │                              │    │                │  │
│  │  - Caddy Proxy  │    │  ┌────────────────────────┐  │    │  - Storage     │  │
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
│           │             │   VAGRANT NETWORK (192.168.122.0/24)│                     │
│           │             │                                 │                     │
│           └─────────────│  k8s-controlplan  192.168.122.70   │                     │
│                         │  k8s-node1        192.168.122.71   │                     │
│                         │  k8s-node2        192.168.122.72   │                     │
│                         └─────────────────────────────────┘                     │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Main components

### 1. Proxmox VE (Hypervisor)

**Address**: 192.168.1.100
**Web interface**: https://192.168.1.100:8006
**SSH**: `ssh pve` (user: ansible)

Proxmox Virtual Environment is the main hypervisor hosting all production VMs.

**Features**:
- KVM virtualization
- LXC containers
- Local and remote storage
- REST API for automation (Terraform provider bpg/proxmox)

**Base template**:
- ID: **9001**
- Name: `ubuntu-2404-cloudinit-template`
- OS: Ubuntu 24.04 Server (cloud-init)

### 2. NAS Synology

**Address**: 192.168.1.93
**DSM interface**: http://192.168.1.93:5000
**SSH**: `ssh nas` (user: xgueret)

Network storage for backups, shared files, and media.

### 3. Local machine

The local workstation runs:
- **Caddy**: Reverse proxy for .local domains
- **Docker**: Development services
- **Vagrant/libvirt**: Local Kubernetes cluster

---

## Proxmox VM architecture

### VM diagram

```
PROXMOX VE (192.168.1.100)
│
├── Template: ubuntu-2404-cloudinit-template (ID: 9001)
│
├── BASTION (Control plane)
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

### VM specifications

| VM | vCPU | RAM | Disk | Usage |
|----|------|-----|--------|-------|
| bastion-60 | 2 | 2 GB | 25 GB | Bastion, GitLab Runner (shell) |
| dockhost-50 | 3 | 10 GB | 100 GB | Docker services (Portainer, GitLab Runner) |
| kubecluster-40 | 2 | 4 GB | 35 GB | K8s Control Plane |
| kubecluster-41 | 1 | 3.5 GB | 30 GB | K8s Worker |
| kubecluster-42 | 1 | 3.5 GB | 30 GB | K8s Worker |

---

## Caddy reverse proxy architecture

Caddy runs locally and routes traffic to the various backends.

```
                    ┌─────────────────────────────────────┐
                    │         CADDY REVERSE PROXY         │
                    │      (Docker - host network mode)   │
                    │           Ports 80, 443             │
                    └──────────────────┬──────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
        ▼                              ▼                              ▼
┌───────────────────┐    ┌─────────────────────────┐    ┌─────────────────────┐
│  DOCKER SERVICES  │    │   NETWORK EQUIPMENT     │    │   K8S CLUSTER       │
│  (host.docker.    │    │                         │    │   (Vagrant)         │
│   internal)       │    │                         │    │                     │
├───────────────────┤    ├─────────────────────────┤    ├─────────────────────┤
│ syncthing:8384    │    │ nas: 192.168.1.93:5000  │    │ traefik:30928       │
│ portainer:9000    │    │ proxmox: 192.168.1.100   │    │ prometheus:30928    │
│ excalidraw:8082   │    │          :8006 (HTTPS)  │    │ grafana:30928       │
│ openwebui:8080    │    │                         │    │ alertmanager:30928  │
│ n8n:5678          │    │                         │    │                     │
└───────────────────┘    └─────────────────────────┘    └─────────────────────┘
```

**Configuration**: `~/caddy-proxy/Caddyfile`

---

## Vagrant Kubernetes architecture

Local Kubernetes cluster for testing and development.

```
┌────────────────────────────────────────────────────────────┐
│              LIBVIRT NETWORK (192.168.122.0/24)             │
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
│  │ Exposed services:     │  │                       │    │
│  │ Traefik, Prometheus   │  │                       │    │
│  │ Grafana, AlertManager │  │                       │    │
│  └───────────────────────┘  └───────────────────────┘    │
│                                                            │
└────────────────────────────────────────────────────────────┘

Location: ~/vagrant-k8s-cluster/
```

---

## Technology stack

### Infrastructure as Code

| Tool | Usage |
|-------|-------|
| **Terraform** (>= 1.11.0) | VM provisioning on Proxmox |
| **Provider bpg/proxmox** (>= 0.93.0) | Proxmox API |
| **Ansible** (>= 13.2.0) | Service configuration and deployment |
| **Ansible Vault** | Secrets management (via `pass`) |

### Containerization

| Tool | Usage |
|-------|-------|
| **Docker** + **Docker Compose** | Runtime and orchestration (dockhost) |
| **Kubernetes** (kubeadm) | Cluster orchestration (kubecluster) |
| **Containerd** | K8s runtime |

### Networking

| Tool | Usage |
|-------|-------|
| **Caddy** | Local reverse proxy (.local) |

---

## IaC project structure

```
~/homelab/
│
├── .gitlab-ci.yml               # CI: ansible-lint, terraform, shellcheck, trivy
├── .pre-commit-config.yaml      # Pre-commit hooks
├── pyproject.toml               # Python dependencies (uv)
├── .envrc                       # direnv: secrets via pass
│
├── modules/
│   └── proxmox_vm_template/     # Shared Terraform module
│       ├── main.tf              # Resource proxmox_virtual_environment_vm
│       ├── variables.tf         # 17 variables (vm_*, project_description)
│       └── outputs.tf
│
├── scripts/
│   ├── ansible-vault-pass.sh    # Retrieves vault password via pass
│   └── check_ansible_vault.sh   # Pre-commit: verifies vault encryption
│
├── proxmox/                     # Hypervisor configuration
│   └── ansible/
│       ├── deploy.yml           # Tags: security_ssh_hardening, generate_vm_template
│       └── roles/
│           ├── configure/       # SSH, tokens, storage, VM templates
│           └── manage/          # Token verification
│
├── dockhost/                    # Docker services VM
│   ├── terraform/               # Provisioning (1 VM)
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
├── bastion/                     # Bastion VM (control plane)
│   ├── terraform/               # Provisioning (1 VM)
│   └── ansible/
│       ├── deploy.yml           # Tags: motd, security-hardening, tooling, ssh-keys, gitlab-runner
│       └── roles/
│           ├── motd/
│           ├── security_hardening/
│           ├── tooling/
│           ├── ssh_keys/
│           └── gitlab_runner/
│
└── kubecluster/                 # Kubernetes cluster (3 VMs)
    ├── terraform/               # Provisioning (1 CP + 2 workers)
    └── ansible/
        ├── deploy.yml           # 3 plays: all, control_plane, workers
        └── roles/               # 10 ordered roles
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

## Deployment workflow

### Two-stage deployment pattern

```
1. TERRAFORM                    2. ANSIBLE                     3. VERIFICATION
   (Provisioning)                  (Configuration)                (Tests)

┌─────────────────────┐       ┌─────────────────────┐       ┌─────────────────────┐
│ cd <project>/terraform│       │ cd <project>          │       │ ssh <vm>            │
│ terraform init      │  ───► │ ansible-playbook     │  ───► │ docker ps           │
│ terraform plan      │       │   ansible/deploy.yml │       │ systemctl status    │
│ terraform apply     │       │                     │       │                     │
└─────────────────────┘       └─────────────────────┘       └─────────────────────┘

        │                             │
        ▼                             ▼
   Creates the VM                 Configures:
   on Proxmox                     - Packages
   with cloud-init                - Docker / Kubernetes
   (user ansible +                - Services
    SSH key)                      - Security
```

### Typical pipeline (dockhost)

```bash
# 1. Provisioning
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

## Security

### Secrets management

| Tool | Usage |
|-------|-------|
| **pass** (password-store) | Key, token, and password storage |
| **Ansible Vault** | Encryption of sensitive variables in the repo |
| **direnv (.envrc)** | Export of `TF_VAR_*` from `pass` |
| **GitLab CI/CD Variables** | CI/CD secrets |

**Vault password**: `pass show ansible/vault` (via `scripts/ansible-vault-pass.sh`)

### SSH access

- Key-based authentication only
- Separate keys per service/equipment
- Centralized configuration in `~/.ssh/config`
- Cloud-init user: `ansible` (passwordless sudo)

### CI/CD Security

- Vault files: encryption verification in CI
- Hardcoded secrets scanning in code
- Trivy scan of Docker images (severity HIGH+CRITICAL)
- Docker images pinned by SHA256 digest
