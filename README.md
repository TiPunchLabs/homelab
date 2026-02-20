```
 ██╗  ██╗ ██████╗ ███╗   ███╗███████╗██╗      █████╗ ██████╗
 ██║  ██║██╔═══██╗████╗ ████║██╔════╝██║     ██╔══██╗██╔══██╗
 ███████║██║   ██║██╔████╔██║█████╗  ██║     ███████║██████╔╝
 ██╔══██║██║   ██║██║╚██╔╝██║██╔══╝  ██║     ██╔══██║██╔══██╗
 ██║  ██║╚██████╔╝██║ ╚═╝ ██║███████╗███████╗██║  ██║██████╔╝
 ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝
```

# Homelab - Infrastructure as Code

![Status](https://img.shields.io/badge/Status-Active-brightgreen) ![Proxmox VE](https://img.shields.io/badge/Proxmox%20VE-9-orange?logo=proxmox&logoColor=white) ![Terraform](https://img.shields.io/badge/Terraform-%3E%3D1.11-blueviolet?logo=terraform) ![Ansible](https://img.shields.io/badge/Ansible-Automation-red?logo=ansible)

Monorepo for provisioning and managing a complete homelab infrastructure on **Proxmox VE** using **Terraform** and **Ansible**.

## Architecture

```
                        ┌──────────────┐
                        │   Proxmox VE │
                        │  Hypervisor  │
                        └──────┬───────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼───────┐ ┌─────▼──────┐ ┌───────▼────────┐
     │   dockhost      │ │ kubecluster│ │   (future VMs) │
     │   Docker apps   │ │ K8s cluster│ │                │
     │   1 VM          │ │ 3 VMs      │ │                │
     └────────────────┘ └────────────┘ └────────────────┘
```

## Sub-projects

| Directory | Description | VMs | Stack |
|-----------|-------------|-----|-------|
| [`proxmox/`](proxmox/) | Proxmox hypervisor configuration (SSH hardening, users, tokens, VM templates) | Host | Ansible |
| [`dockhost/`](dockhost/) | Docker-based services VM (Docker, Portainer, security hardening) | 1 | Terraform + Ansible |
| [`kubecluster/`](kubecluster/) | Kubernetes cluster (kubeadm, containerd, CNI) | 3 (1 CP + 2 workers) | Terraform + Ansible |

### Shared components

| Directory | Description |
|-----------|-------------|
| `modules/` | Reusable Terraform modules (`proxmox_vm_template`) |
| `github-terraform/` | GitHub repository management via Terraform |
| `scripts/` | Shared scripts (Ansible Vault password, pre-commit checks) |

## Prerequisites

- [Proxmox VE 9](https://www.proxmox.com/) with API token configured
- [Terraform](https://www.terraform.io/) >= 1.11.0
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- [direnv](https://direnv.net/) for environment management
- [pass](https://www.passwordstore.org/) for secrets management
- SSH access to Proxmox and VMs

## Quick Start

```bash
# Clone the repository
git clone git@github.com:TiPunchLabs/homelab.git
cd homelab

# Allow direnv (creates .venv via uv, loads secrets via pass)
direnv allow

# Install Python dependencies
uv sync

# Install pre-commit hooks
uv run pre-commit install

# Provision a sub-project (example: dockhost)
cd dockhost/terraform
terraform init
terraform plan
terraform apply

# Deploy services
cd ../..
cd dockhost
ansible-playbook ansible/deploy.yml
```

## Project Structure

```
homelab/
├── .github/                        # CI/CD, issue templates, dependabot
├── .claude/                        # Claude Code config & commands
├── .pre-commit-config.yaml         # Pre-commit hooks (shared)
├── .envrc                          # direnv: venv, TF_VAR, vault password
├── ansible.cfg                     # Default Ansible config
├── pyproject.toml                  # Python dependencies (uv)
│
├── modules/                        # Shared Terraform modules
│   └── proxmox_vm_template/        #   Reusable VM provisioning module
│
├── github-terraform/               # GitHub repo management (Terraform)
│
├── scripts/                        # Shared scripts
│   ├── ansible-vault-pass.sh       #   Vault password via pass
│   └── check_ansible_vault.sh      #   Pre-commit vault encryption check
│
├── proxmox/                        # Hypervisor configuration
│   ├── ansible/                    #   Roles: configure, manage
│   └── terraform/                  #   GitHub repo provisioning
│
├── dockhost/                       # Docker services VM
│   ├── ansible/                    #   Roles: docker, motd, portainer, security
│   └── terraform/                  #   VM provisioning (1 VM)
│
└── kubecluster/                    # Kubernetes cluster
    ├── ansible/                    #   Roles: kubeadm, containerd, CNI, workers
    └── terraform/                  #   VM provisioning (3 VMs)
```

## VM Overview

| VM | VMID | IP | CPU | RAM | Disk | Purpose |
|----|------|----|-----|-----|------|---------|
| dockhost-90 | 9090 | 192.168.1.90 | 3 cores | 10 GB | 100 GB | Docker services |
| kubecluster-40 | 9040 | 192.168.1.40 | 2 cores | 4 GB | 35 GB | K8s Control Plane |
| kubecluster-41 | 9041 | 192.168.1.41 | 1 core | 3.5 GB | 30 GB | K8s Worker |
| kubecluster-42 | 9042 | 192.168.1.42 | 1 core | 3.5 GB | 30 GB | K8s Worker |

## Secrets Management

Secrets are managed via [pass](https://www.passwordstore.org/) and [direnv](https://direnv.net/):

- **Terraform tokens**: `pass github/terraform-token` (injected as `TF_VAR_github_token`)
- **Ansible Vault password**: `pass ansible/vault` (used by `scripts/ansible-vault-pass.sh`)
- **Sensitive variables**: encrypted with Ansible Vault in `*/ansible/group_vars/*/vault/`

## CI/CD

GitHub Actions runs on every push/PR to `main`:

| Job | Description |
|-----|-------------|
| `lint-ansible` | Ansible lint on all sub-projects |
| `lint-terraform` | `terraform fmt` + `terraform validate` |
| `lint-shell` | ShellCheck on `scripts/` |
| `security-check` | Vault encryption + secret scanning |

## Contributing

1. Create a feature branch: `git checkout -b feat/my-feature`
2. Follow [Conventional Commits](https://www.conventionalcommits.org/)
3. Run checks: `pre-commit run --all-files`
4. Submit a Pull Request

## Author

**Xavier GUERET**

[![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
