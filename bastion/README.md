```
 ██████╗  █████╗ ███████╗████████╗██╗ ██████╗ ███╗   ██╗
 ██╔══██╗██╔══██╗██╔════╝╚══██╔══╝██║██╔═══██╗████╗  ██║
 ██████╔╝███████║███████╗   ██║   ██║██║   ██║██╔██╗ ██║
 ██╔══██╗██╔══██║╚════██║   ██║   ██║██║   ██║██║╚██╗██║
 ██████╔╝██║  ██║███████║   ██║   ██║╚██████╔╝██║ ╚████║
 ╚═════╝ ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
```

# Bastion - Ansible & Terraform Executor

![Stars](https://img.shields.io/github/stars/TiPunchLabs/homelab?style=social) ![Last Commit](https://img.shields.io/github/last-commit/TiPunchLabs/homelab) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

This project automates the deployment of a bastion host on Proxmox using Terraform for infrastructure provisioning and Ansible for tooling installation and configuration. The bastion centralizes the execution of Ansible playbooks and Terraform commands for the entire homelab infrastructure.

## Project Architecture

The project deploys a hardened bastion VM with the following components:

### Deployed Components

- **GitLab Runner** - Shell executor registered as a systemd service
- **SSH Keys** - Deployed keys and SSH config for accessing all homelab hosts
- **Tooling** - Python (uv), Terraform, direnv, git

### Infrastructure Stack

1. **Terraform**: VM provisioning on Proxmox
2. **Ansible**: Tools installation and configuration

## Prerequisites

- Terraform (>= 1.11.0)
- Ansible
- Proxmox account with appropriate permissions
- A Proxmox VM template (template ID 9001 by default)

## Usage

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

- CPU: 2 cores
- RAM: 2048 MB (2 GB)
- Disk: 25 GB SSD
- Template ID: 9001
- VM Base ID: 9060

### 2. Service Deployment with Ansible

1. Navigate to the `ansible/` directory
2. Configure variables in:

   - `group_vars/bastion/vault/config.yml` (encrypted with ansible-vault)
   - `group_vars/bastion/all/main.yml`
3. Run the playbook:

   ```bash
   ansible-playbook deploy.yml
   ```
4. Deploy specific components using tags:

   ```bash
   # Deploy only MOTD
   ansible-playbook deploy.yml --tags motd

   # Deploy multiple components
   ansible-playbook deploy.yml --tags "tooling,ssh-keys"
   ```

### Available Ansible Tags

- `motd` - Deploy custom MOTD with ASCII art banner
- `security-hardening` - SSH hardening and UFW firewall configuration
- `tooling` - Install Python (uv), Terraform, direnv, git
- `ssh-keys` - Deploy SSH keys and SSH config
- `gitlab-runner` - Install and configure GitLab Runner (shell executor, systemd)

## Security

Sensitive files are encrypted with Ansible Vault. A pre-commit hook verifies that files in the `vault/` directory are properly encrypted.

To edit vault files:

```bash
ansible-vault edit ansible/group_vars/bastion/vault/config.yml
```

## Code Management

The project includes pre-commit configuration for:

- Shell script formatting
- Ansible syntax checking
- Terraform validation
- Ensuring sensitive files are encrypted

To install hooks:

```bash
pre-commit install
```

## File Structure

```
.
├── ansible/                      # Ansible configuration
│   ├── ansible.cfg               # Global Ansible config
│   ├── deploy.yml                # Main playbook
│   ├── inventory.yml             # Host inventory
│   ├── group_vars/
│   │   └── bastion/              # Group variables
│   │       ├── all/main.yml      # Role variables
│   │       └── vault/            # Encrypted variables
│   └── roles/                    # Ansible roles
│       ├── motd/                 # Custom MOTD banner
│       ├── security_hardening/   # SSH + UFW hardening
│       ├── tooling/              # Python, uv, Terraform, direnv, git
│       ├── ssh_keys/             # SSH keys and config deployment
│       └── gitlab_runner/        # GitLab Runner (shell executor)
├── terraform/
│   ├── main.tf                   # Terraform main configuration
│   ├── providers.tf              # Provider configuration
│   ├── variables.tf              # Variable definitions
│   └── outputs.tf                # Output definitions
└── README.md                     # This file
```

## Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## Contributing

Contributions are welcome! Please feel free to submit a [Pull Request](https://github.com/TiPunchLabs/homelab/pulls).

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
