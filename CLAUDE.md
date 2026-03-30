# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Monorepo homelab regroupant l'Infrastructure as Code (IaC) pour un environnement Proxmox VE. Six sous-projets partageant des modules Terraform, des scripts et des conventions communes.

## Architecture globale

```
homelab/
├── .gitlab-ci.yml            # Pipeline CI GitLab (lint, security, deploy)
├── .github/                  # GitHub (miroir read-only, plus de CI)
├── .claude/                  # Configuration Claude Code commune
│   ├── settings.local.json
│   └── commands/             # Commandes partagees
├── modules/                  # Modules Terraform partages
│   ├── proxmox_vm_template/  # Module reutilisable de provisioning VM
│   └── proxmox_lxc_template/ # Module reutilisable de provisioning LXC
├── gitlab-terraform/         # Gestion du projet GitLab via Terraform
├── github-terraform/         # Gestion du repo GitHub via Terraform
├── scripts/                  # Scripts partages
│   ├── ansible-vault-pass.sh
│   └── check_ansible_vault.sh
├── proxmox/                  # Configuration hyperviseur Proxmox
├── dockhost/                 # VM Docker services
├── kubecluster/              # Cluster Kubernetes (3 VMs)
├── bastion/                  # VM Bastion (Ansible & Terraform executor)
├── vpngate/                  # VM VPN Gateway (WireGuard)
└── caddy/                    # LXC Caddy reverse proxy
```

---

## Sous-projet : proxmox/

### Description
Configuration et hardening du serveur Proxmox VE. Utilise **Ansible** pour la configuration serveur.

### Structure
```
proxmox/
├── ansible/
│   ├── inventory.yml
│   ├── deploy.yml               # Tags: security_ssh_hardening, setup_roles_users_tokens, setup_storage, generate_vm_template
│   ├── requirements.yml
│   ├── host_vars/pve/vault/       # Ansible Vault encrypted secrets
│   └── roles/
│       ├── configure/             # SSH, tokens, storage, VM templates
│       └── manage/                # Token verification
└── ansible.cfg
```

### Commandes cles
```bash
cd proxmox
ansible-playbook ansible/deploy.yml
ansible-playbook ansible/deploy.yml --tags "security_ssh_hardening"
ansible-playbook ansible/deploy.yml --tags "generate_vm_template"
```

---

## Sous-projet : dockhost/

### Description
VM Docker avec services conteneurises (Portainer, PostgreSQL, kandidat). Pattern **two-stage deployment** : Terraform pour le provisioning VM, Ansible pour l'installation des services.

### Structure
```
dockhost/
├── ansible/
│   ├── deploy.yml
│   ├── inventory.yml
│   ├── group_vars/dockhost/
│   │   ├── all/main.yml
│   │   └── vault/                 # Fichiers chiffres Ansible Vault
│   └── roles/
│       ├── docker/
│       ├── motd/
│       ├── portainer_agent/
│       ├── security_hardening/
│       ├── postgresql/            # PostgreSQL (Docker, reseau db-net)
│       └── kandidat/              # App kandidat (Docker, reseau db-net, registry GitLab)
├── terraform/
│   ├── main.tf, variables.tf, outputs.tf
└── ansible.cfg
```

### Specs VM
- CPU: 3 cores | RAM: 10 GB | Disk: 100 GB SSD
- Template ID: 9001 | VMID: 9090 | IP: 192.168.1.90

### Commandes cles
```bash
cd dockhost
ansible-playbook ansible/deploy.yml
ansible-playbook ansible/deploy.yml --tags docker
ansible-playbook ansible/deploy.yml --tags portainer_agent
ansible-playbook ansible/deploy.yml --tags postgresql
ansible-playbook ansible/deploy.yml --tags kandidat
```

---

## Sous-projet : kubecluster/

### Description
Cluster Kubernetes deploye avec kubeadm. Pattern **two-stage deployment** : Terraform pour le provisioning de 3 VMs, Ansible pour l'installation de Kubernetes.

### Topologie cluster

| Node | Role | CPU | RAM | Disk | VMID | IP |
|------|------|-----|-----|------|------|-----|
| kubecluster-40 | Control Plane | 2 cores | 4096 MB | 35 GB | 9040 | 192.168.1.40 |
| kubecluster-41 | Worker | 1 core | 3584 MB | 30 GB | 9041 | 192.168.1.41 |
| kubecluster-42 | Worker | 1 core | 3584 MB | 30 GB | 9042 | 192.168.1.42 |

### Structure
```
kubecluster/
├── ansible/
│   ├── deploy.yml                 # 3 plays (all, control_plane_nodes, worker_nodes)
│   ├── inventory.yml
│   ├── group_vars/kubecluster/
│   └── roles/                     # 10 roles ordonnes
│       ├── motd/
│       ├── cfg_nodes/
│       ├── inst_runc/
│       ├── inst_cni/
│       ├── cfg_containerd/
│       ├── inst_cri_tools/
│       ├── cfg_kubeadm_kubelet_kubectl/
│       ├── init_kubeadm/          # control_plane_nodes only
│       ├── kubectl_cheat_sheet/   # control_plane_nodes only
│       └── join_workers/          # worker_nodes only
├── terraform/
│   ├── main.tf, variables.tf, outputs.tf
└── ansible.cfg
```

### Commandes cles
```bash
cd kubecluster
ansible-playbook ansible/deploy.yml
ansible-playbook ansible/deploy.yml --tags cfg_nodes
ansible-playbook ansible/deploy.yml --tags init_kubeadm
ansible-playbook ansible/deploy.yml --tags join_workers
```

---

## Sous-projet : bastion/

### Description
VM bastion centralisant l'execution des playbooks Ansible et commandes Terraform. Pattern **two-stage deployment** : Terraform pour le provisioning VM, Ansible pour l'installation des outils (uv, Terraform, direnv, git) et le deploiement des cles SSH. Les secrets sont injectes via variables d'environnement SSH (`SendEnv`).

### Structure
```
bastion/
├── ansible/
│   ├── deploy.yml
│   ├── inventory.yml
│   ├── group_vars/bastion/
│   │   ├── all/main.yml
│   │   └── vault/                 # Fichiers chiffres Ansible Vault
│   └── roles/
│       ├── motd/
│       ├── security_hardening/    # SSH + UFW
│       ├── tooling/               # Python, uv, Terraform, direnv, git
│       ├── ssh_keys/              # Deploy SSH keys + config (inclut gitlab.com)
│       └── gitlab_runner/         # GitLab Runner natif (shell executor, systemd)
├── terraform/
│   ├── main.tf, variables.tf, outputs.tf
└── ansible.cfg
```

### Specs VM
- CPU: 2 cores | RAM: 2 GB | Disk: 25 GB SSD
- Template ID: 9001 | VMID: 9060 | IP: 192.168.1.60

### Commandes cles
```bash
cd bastion
ansible-playbook ansible/deploy.yml
ansible-playbook ansible/deploy.yml --tags motd
ansible-playbook ansible/deploy.yml --tags security-hardening
ansible-playbook ansible/deploy.yml --tags tooling
ansible-playbook ansible/deploy.yml --tags ssh-keys
ansible-playbook ansible/deploy.yml --tags gitlab-runner
```

---

## Sous-projet : vpngate/

### Description
VM WireGuard VPN Gateway. Pattern **two-stage deployment** : Terraform pour le provisioning VM, Ansible pour l'installation de WireGuard et la generation des configs clients.

### Structure
```
vpngate/
├── ansible/
│   ├── deploy.yml
│   ├── inventory.yml
│   ├── group_vars/vpngate/
│   │   ├── all/main.yml
│   │   └── vault/                 # Fichiers chiffres Ansible Vault
│   └── roles/
│       ├── motd/
│       ├── security_hardening/    # SSH + UFW (ports 22/tcp, 51820/udp)
│       └── wireguard/             # WireGuard server + client config generation
├── terraform/
│   ├── main.tf, variables.tf, outputs.tf
├── docs/
│   └── understanding-wireguard-role.md
└── ansible.cfg
```

### Specs VM
- CPU: 1 core | RAM: 512 MB | Disk: 22 GB SSD
- Template ID: 9001 | VMID: 9050 | IP: 192.168.1.50

### Commandes cles
```bash
cd vpngate
ansible-playbook ansible/deploy.yml
ansible-playbook ansible/deploy.yml --tags motd
ansible-playbook ansible/deploy.yml --tags security-hardening
ansible-playbook ansible/deploy.yml --tags wireguard
```

---

## Sous-projet : caddy/

### Description
LXC container Caddy reverse proxy. Pattern **two-stage deployment** : Terraform pour le provisioning du conteneur LXC (via module `proxmox_lxc_template`), Ansible pour l'installation de Caddy.

### Structure
```
caddy/
├── ansible/
│   ├── deploy.yml
│   ├── inventory.yml
│   ├── group_vars/caddy/
│   │   └── all/main.yml
│   └── roles/
│       ├── motd/
│       ├── security_hardening/    # SSH + UFW (ports 22/tcp, 80/tcp, 443/tcp)
│       └── caddy/                 # Caddy reverse proxy (APT install + Caddyfile)
├── terraform/
│   ├── main.tf, providers.tf, variables.tf, outputs.tf
└── ansible.cfg
```

### Specs LXC
- CPU: 1 core | RAM: 512 MiB | Disk: 8 GB SSD
- CTID: 1070 | IP: 192.168.1.70 | Unprivileged: yes

### Commandes cles
```bash
cd caddy
ansible-playbook ansible/deploy.yml
ansible-playbook ansible/deploy.yml --tags motd
ansible-playbook ansible/deploy.yml --tags security-hardening
ansible-playbook ansible/deploy.yml --tags caddy
```

---

## Conventions communes

### Secrets
- **Ansible Vault** : Secrets chiffres dans `*/ansible/group_vars/*/vault/` ou `*/ansible/host_vars/*/vault/`
- **Vault password** : Via `pass show ansible/vault` (script `scripts/ansible-vault-pass.sh`)
- **Terraform credentials** : Via `TF_VAR_*` depuis `.envrc` + `pass`
- **Ne jamais commiter** de fichiers vault non chiffres ou de `.tfvars`

### Qualite du code
- Pre-commit hooks configures a la racine (`.pre-commit-config.yaml`)
- `ansible-lint` pour le code Ansible
- `terraform fmt` + `terraform validate` pour Terraform
- `shellcheck` + `shfmt` pour les scripts shell

### Convention de commit
- Format : `type(scope): description`
- Types : `infra`, `config`, `feat`, `fix`, `refactor`, `docs`, `chore`, `k8s`
- Description en francais, a l'imperatif

### Tooling
- **uv** : Gestion des dependances Python (pyproject.toml a la racine)
- **direnv** : Auto-active venv et exporte les variables (.envrc a la racine)
- **pass** : Password manager pour tous les secrets
- **GitLab** : Origin principal (`gitlab.com/tipunchlabs/homelab`)
- **GitHub** : Miroir read-only (`github.com/TiPunchLabs/homelab`), plus de CI
- **CI/CD** : GitLab CI uniquement (`.gitlab-ci.yml`)

### Tests avant commit
```bash
pre-commit run --all-files
ansible-lint proxmox/ansible/ dockhost/ansible/ kubecluster/ansible/ bastion/ansible/ vpngate/ansible/
terraform fmt -check -recursive
```
