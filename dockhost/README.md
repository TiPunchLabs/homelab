```
 ██████╗  ██████╗  ██████╗██╗  ██╗██╗  ██╗ ██████╗ ███████╗████████╗
 ██╔══██╗██╔═══██╗██╔════╝██║ ██╔╝██║  ██║██╔═══██╗██╔════╝╚══██╔══╝
 ██║  ██║██║   ██║██║     █████╔╝ ███████║██║   ██║███████╗   ██║
 ██║  ██║██║   ██║██║     ██╔═██╗ ██╔══██║██║   ██║╚════██║   ██║
 ██████╔╝╚██████╔╝╚██████╗██║  ██╗██║  ██║╚██████╔╝███████║   ██║
 ╚═════╝  ╚═════╝  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝
```

# 🚀 Dockhost - Multi-Service Platform Automation

![Stars](https://img.shields.io/github/stars/TiPunchLabs/homelab?style=social) ![Last Commit](https://img.shields.io/github/last-commit/TiPunchLabs/homelab) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

This project automates the deployment of a multi-service platform on Proxmox using Terraform for infrastructure provisioning and Ansible for service deployment and configuration.

## 🌐 Project Architecture

The project deploys a complete containerized infrastructure with the following services:

### Deployed Services

Each service is its own Ansible role, deployed in this order by `deploy.yml`:

| Service | Role / tag | Description |
|---------|-----------|-------------|
| MOTD | `motd` | Custom login banner (ASCII art) |
| Docker | `docker` | Docker Engine + Compose plugin |
| Portainer CE | `portainer` | Docker management UI (`portainer/portainer-ce`) |
| Komodo Periphery | `komodo` | GitOps agent — reconciles the `homelab-gitops` repo into running containers |
| PostgreSQL | `postgresql` | Shared database, on the `db-net` Docker network |
| kandidat | `kandidat` | App `kandidat` (image from the GitLab registry, on `db-net`) |
| Open WebUI | `open-webui` | LLM frontend; backend Ollama reached via `ollama.internal`, state in PostgreSQL |
| Excalidraw | `excalidraw` | Self-hosted virtual whiteboard |
| miniboard | `miniboard` | Dashboard (image from the GitLab registry) |

> ℹ️ The `security_hardening` role exists but is an **empty placeholder** (not wired
> into `deploy.yml` yet) — see the homelab root `CLAUDE.md` backlog.

### Infrastructure Stack

1. **Terraform**: VM provisioning on Proxmox
2. **Ansible**: Service installation and configuration
3. **Docker**: Containerization platform (services run as Compose stacks)
4. **Caddy** (LXC `caddy-70`) + **Pi-hole** (`dns-71`): reverse proxy and `.internal`
   DNS in front of these services — not part of this VM, see
   [`../caddy/`](../caddy/) and [`../pihole/`](../pihole/)

## 📋 Prerequisites

- Terraform (>= 1.11.0)
- Ansible
- Proxmox account with appropriate permissions
- A Proxmox VM template (template ID 9001 by default)

## 🛠️ Usage

### 1. VM Provisioning with Terraform

1. Navigate to the `terraform/` directory
2. Create a `terraform.tfvars` file with your Proxmox credentials
3. Run:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

Example `terraform.tfvars`:

```hcl
pm_api_url           = "https://your-proxmox-server:8006/api2/json"
pm_api_token_id      = "your-user@pam!token-name"
pm_api_token_secret  = "your-token-secret"
```

**VM Configuration:**

- CPU: 3 cores
- RAM: 10240 MB (10 GB)
- Disk: 100 GB SSD
- Template ID: 9001
- VM Base ID: 9090

### 2. Service Deployment with Ansible

1. Navigate to the `ansible/` directory
2. Configure variables in:

   - `group_vars/dockhost/vault/main.yml` (encrypted with ansible-vault)
   - Individual role variables in `roles/*/vars/main.yml`
3. Run the playbook:

   ```bash
   ansible-playbook deploy.yml
   ```
4. Deploy specific services using tags:

   ```bash
   # Deploy only MOTD
   ansible-playbook deploy.yml --tags motd

   # Deploy multiple services
   ansible-playbook deploy.yml --tags "docker,portainer"
   ```

### 🔑 Available Ansible Tags

| Tag | Action |
|-----|--------|
| `motd` | Custom MOTD with ASCII art banner |
| `docker` | Install Docker Engine and Compose |
| `portainer` | Deploy Portainer CE |
| `komodo` | Deploy Komodo Periphery (GitOps agent) |
| `postgresql` | Deploy PostgreSQL (`db-net`) |
| `kandidat` | Deploy the `kandidat` app |
| `open-webui` | Deploy Open WebUI (note the hyphen, not `open_webui`) |
| `excalidraw` | Deploy Excalidraw |
| `miniboard` | Deploy miniboard |

## 🔒 Security

Sensitive files are encrypted with Ansible Vault. A pre-commit hook verifies that files in the `vault/` directory are properly encrypted.

To edit vault files:

```bash
ansible-vault edit ansible/group_vars/dockhost/vault/main.yml
```

## 💻 Code Management

The project includes pre-commit configuration for:

- Shell script formatting
- Ansible syntax checking
- Terraform validation
- Ensuring sensitive files are encrypted

To install hooks:

```bash
pre-commit install
```

## 📂 File Structure

```
.
├── ansible/                      # Ansible configuration
│   ├── ansible.cfg               # Global Ansible config
│   ├── deploy.yml                # Main playbook
│   ├── inventory.yml             # Host inventory
│   ├── group_vars/
│   │   └── dockhost/              # Group variables
│   │       └── vault/            # Encrypted variables
│   └── roles/                    # Ansible roles
│       ├── motd/                 # Custom MOTD banner
│       ├── docker/               # Docker Engine + Compose
│       ├── portainer/            # Portainer CE
│       ├── komodo/               # Komodo Periphery (GitOps agent)
│       ├── postgresql/           # PostgreSQL (db-net)
│       ├── kandidat/             # kandidat app
│       ├── open_webui/           # Open WebUI (LLM frontend)
│       ├── excalidraw/           # Excalidraw whiteboard
│       ├── miniboard/            # miniboard dashboard
│       └── security_hardening/   # Placeholder (empty, not in deploy.yml)
├── terraform/
│   ├── main.tf                   # Terraform main configuration
│   ├── variables.tf              # Variable definitions
│   └── outputs.tf                # Output definitions
├── docs.md                       # Documentation technique detaillee
└── README.md                     # This file
```


## 📚 Documentation

- [Documentation technique detaillee](docs.md) — Specs VM, capacite, reseau, securite, workflow de deploiement

## 👥 Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## 👥 Contributing

Contributions are welcome! Please feel free to submit a [Pull Request](https://github.com/TiPunchLabs/homelab/pulls).

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
