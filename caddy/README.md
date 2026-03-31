```
  ██████╗ █████╗ ██████╗ ██████╗ ██╗   ██╗
 ██╔════╝██╔══██╗██╔══██╗██╔══██╗╚██╗ ██╔╝
 ██║     ███████║██║  ██║██║  ██║ ╚████╔╝
 ██║     ██╔══██║██║  ██║██║  ██║  ╚██╔╝
 ╚██████╗██║  ██║██████╔╝██████╔╝   ██║
  ╚═════╝╚═╝  ╚═╝╚═════╝ ╚═════╝    ╚═╝
```

# 🚀 Caddy - Reverse Proxy Automation

![Stars](https://img.shields.io/github/stars/TiPunchLabs/homelab?style=social) ![Last Commit](https://img.shields.io/github/last-commit/TiPunchLabs/homelab) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

This project automates the deployment of a Caddy reverse proxy on Proxmox using Terraform for LXC container provisioning and Ansible for Caddy installation and configuration.

## 🌐 Project Architecture

The project deploys a Caddy reverse proxy that handles traffic for internal services:

### Reverse Proxy Backends

- **proxmox.internal** - Proxmox VE web interface (https://192.168.1.100:8006)
- **kandidat.internal** - Kandidat application (http://192.168.1.90:8000)
- **vpngate.internal** - WireGuard VPN management interface (http://192.168.1.50:51821)

### Infrastructure Stack

1. **Terraform**: LXC container provisioning on Proxmox
2. **Ansible**: Caddy installation and configuration

## 📋 Prerequisites

- Terraform (>= 1.11.0)
- Ansible
- Proxmox account with appropriate permissions
- An Ubuntu 24.04 LXC template

## 🛠️ Usage

### 1. LXC Provisioning with Terraform

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

**LXC Configuration:**

- CPU: 1 core
- RAM: 512 MiB
- Disk: 8 GB SSD
- CTID: 1070
- IP: 192.168.1.70
- Unprivileged: yes

### 2. Service Deployment with Ansible

1. Navigate to the `ansible/` directory
2. Configure variables in:

   - `group_vars/caddy/all/main.yml`
3. Run the playbook:

   ```bash
   ansible-playbook deploy.yml
   ```
4. Deploy specific services using tags:

   ```bash
   # Deploy only MOTD
   ansible-playbook deploy.yml --tags motd

   # Deploy security hardening
   ansible-playbook deploy.yml --tags security-hardening

   # Deploy Caddy reverse proxy
   ansible-playbook deploy.yml --tags caddy
   ```

### 🔑 Available Ansible Tags

- `motd` - Deploy custom MOTD with ASCII art banner
- `security-hardening` - SSH hardening and UFW firewall (ports 22/tcp, 80/tcp, 443/tcp)
- `caddy` - Install and configure Caddy reverse proxy

## 🔒 Security

Sensitive files are encrypted with Ansible Vault. A pre-commit hook verifies that files in the `vault/` directory are properly encrypted.

To edit vault files:

```bash
ansible-vault edit ansible/group_vars/caddy/vault/main.yml
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
│   │   └── caddy/                # Group variables
│   │       └── all/main.yml      # Caddy backends & security config
│   └── roles/                    # Ansible roles
│       ├── motd/                 # Custom MOTD banner
│       ├── security_hardening/   # SSH + UFW hardening
│       └── caddy/                # Caddy reverse proxy
├── terraform/
│   ├── main.tf                   # Terraform main configuration
│   ├── providers.tf              # Provider configuration
│   ├── variables.tf              # Variable definitions
│   └── outputs.tf                # Output definitions
└── README.md                     # This file
```

## 👥 Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## 👥 Contributing

Contributions are welcome! Please feel free to submit a [Pull Request](https://github.com/TiPunchLabs/homelab/pulls).

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
