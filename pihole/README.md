```
 ██████╗ ██╗      ██╗  ██╗ ██████╗ ██╗     ███████╗
 ██╔══██╗██║      ██║  ██║██╔═══██╗██║     ██╔════╝
 ██████╔╝██║█████╗███████║██║   ██║██║     █████╗
 ██╔═══╝ ██║╚════╝██╔══██║██║   ██║██║     ██╔══╝
 ██║     ██║      ██║  ██║╚██████╔╝███████╗███████╗
 ╚═╝     ╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚══════╝
```

# Pi-hole - DNS Server & Ad-Blocking Automation

![Stars](https://img.shields.io/github/stars/TiPunchLabs/homelab?style=social) ![Last Commit](https://img.shields.io/github/last-commit/TiPunchLabs/homelab) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

This project automates the deployment of a Pi-hole DNS server on Proxmox using Terraform for LXC container provisioning and Ansible for Pi-hole installation and configuration.

## Project Architecture

The project deploys a Pi-hole DNS server with the following capabilities:

### Deployed Services

- **Pi-hole** - Network-wide DNS server with ad-blocking (native install, CLI v6)

### Infrastructure Stack

1. **Terraform**: LXC container provisioning on Proxmox (via `proxmox_lxc_template` module)
2. **Ansible**: Pi-hole installation and configuration

### DNS Configuration

| Domain             | Target IP      | Description              |
|--------------------|----------------|--------------------------|
| proxmox.internal   | 192.168.1.70   | Proxmox web UI (via Caddy) |
| kandidat.internal  | 192.168.1.70   | Kandidat app (via Caddy)   |
| vpngate.internal   | 192.168.1.70   | VPN gateway (via Caddy)    |

Upstream DNS servers: `1.1.1.1`, `8.8.8.8`

## Prerequisites

- Terraform (>= 1.11.0)
- Ansible
- Proxmox account with appropriate permissions
- An Ubuntu 24.04 LXC template on Proxmox

## Usage

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
- CTID: 1071
- IP: 192.168.1.71
- Unprivileged: yes

### 2. Service Deployment with Ansible

1. Navigate to the `ansible/` directory
2. Configure variables in:

   - `group_vars/pihole/vault/pihole.yml` (encrypted with ansible-vault)
   - `group_vars/pihole/all/main.yml`
3. Run the playbook:

   ```bash
   ansible-playbook deploy.yml
   ```
4. Deploy specific services using tags:

   ```bash
   # Deploy only MOTD
   ansible-playbook deploy.yml --tags motd

   # Deploy only Pi-hole
   ansible-playbook deploy.yml --tags pihole
   ```

### Available Ansible Tags

- `motd` - Deploy custom MOTD with ASCII art banner
- `security-hardening` - SSH hardening and UFW firewall (ports 22/tcp, 53/tcp, 53/udp, 80/tcp)
- `pihole` - Install and configure Pi-hole DNS with local records

## Security

Sensitive files are encrypted with Ansible Vault. A pre-commit hook verifies that files in the `vault/` directory are properly encrypted.

To edit vault files:

```bash
ansible-vault edit ansible/group_vars/pihole/vault/pihole.yml
```

### Firewall Rules (UFW)

| Port    | Protocol | Description            |
|---------|----------|------------------------|
| 22      | tcp      | SSH access             |
| 53      | tcp      | DNS                    |
| 53      | udp      | DNS                    |
| 80      | tcp      | Pi-hole web interface  |

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
│   │   └── pihole/               # Group variables
│   │       ├── all/main.yml      # Open variables
│   │       └── vault/            # Encrypted variables
│   └── roles/                    # Ansible roles
│       ├── motd/                 # Custom MOTD banner
│       ├── security_hardening/   # SSH + UFW hardening
│       └── pihole/               # Pi-hole DNS installation
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
