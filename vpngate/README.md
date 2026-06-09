```
 ██╗   ██╗██████╗ ███╗   ██╗ ██████╗  █████╗ ████████╗███████╗
 ██║   ██║██╔══██╗████╗  ██║██╔════╝ ██╔══██╗╚══██╔══╝██╔════╝
 ██║   ██║██████╔╝██╔██╗ ██║██║  ███╗███████║   ██║   █████╗
 ╚██╗ ██╔╝██╔═══╝ ██║╚██╗██║██║   ██║██╔══██║   ██║   ██╔══╝
  ╚████╔╝ ██║     ██║ ╚████║╚██████╔╝██║  ██║   ██║   ███████╗
   ╚═══╝  ╚═╝     ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝  ╚══════╝
```

# VPNGate - WireGuard VPN Gateway Automation

![Stars](https://img.shields.io/github/stars/TiPunchLabs/homelab?style=social) ![Last Commit](https://img.shields.io/github/last-commit/TiPunchLabs/homelab) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

This project automates the deployment of a WireGuard VPN gateway on Proxmox using Terraform for infrastructure provisioning and Ansible for WireGuard installation and configuration.

## Project Architecture

The project deploys a secure VPN gateway using WireGuard via the wg-easy Docker container:

### Deployed Services

- **WireGuard (wg-easy)** - VPN server with web management UI

### Infrastructure Stack

1. **Terraform**: VM provisioning on Proxmox
2. **Ansible**: Service installation and configuration
3. **Docker**: Containerization platform (runs wg-easy)

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

- CPU: 1 core
- RAM: 512 MB
- Disk: 22 GB SSD
- Template ID: 9001
- VM Base ID: 9050
- IP: 192.168.10.50
- DNS: 192.168.10.71 (Pi-hole)

### 2. Service Deployment with Ansible

1. Navigate to the `ansible/` directory
2. Configure variables in:

   - `group_vars/vpngate/vault/main.yml` (encrypted with ansible-vault)
   - Individual role variables in `roles/*/vars/main.yml`
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

   # Deploy WireGuard
   ansible-playbook deploy.yml --tags wireguard
   ```

### Available Ansible Tags

- `motd` - Deploy custom MOTD with ASCII art banner
- `security-hardening` - SSH hardening and UFW firewall (ports 22/tcp, 51820/udp, 51821/tcp)
- `docker` - Install Docker and Docker Compose
- `wireguard` - Deploy WireGuard VPN server via wg-easy Docker container

## Security

Sensitive files are encrypted with Ansible Vault. A pre-commit hook verifies that files in the `vault/` directory are properly encrypted.

To edit vault files:

```bash
ansible-vault edit ansible/group_vars/vpngate/vault/main.yml
```

### Firewall Rules (UFW)

| Port | Protocol | Description |
|------|----------|-------------|
| 22 | TCP | SSH access |
| 51820 | UDP | WireGuard VPN |
| 51821 | TCP | wg-easy Web UI |

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
│   │   └── vpngate/              # Group variables
│   │       ├── all/main.yml      # Role configuration
│   │       └── vault/            # Encrypted variables
│   └── roles/                    # Ansible roles
│       ├── motd/                 # Custom MOTD banner
│       ├── docker/               # Docker installation
│       ├── security_hardening/   # SSH + UFW hardening
│       └── wireguard/            # WireGuard VPN (wg-easy)
├── terraform/
│   ├── main.tf                   # Terraform main configuration
│   ├── variables.tf              # Variable definitions
│   └── outputs.tf                # Output definitions
├── docs/
│   └── understanding-wireguard-role.md  # WireGuard role documentation
└── README.md                     # This file
```

## External access (Internet)

To reach `wg-easy` (UDP/51820 on `192.168.10.50`) from the Internet, two
port-forwarding rules must be in place because the homelab sits behind two
NAT layers (ISP box → mesh router → homelab LAN):

1. **ISP box (Livebox)**: `WAN UDP 51820 → 192.168.1.10:51820` (mesh router WAN IP)
2. **Mesh router (WERTMESH1800)**: `WAN UDP 51820 → 192.168.10.50:51820` (vpngate)

See [docs/references/ip-addresses.md → External access topology](../docs/references/ip-addresses.md#external-access-topology)
for the full diagram.

> ⚠️ **Generated client `.conf` quirk** — peers created via the wg-easy UI inherit
> the `WG_DEFAULT_DNS` value of the moment. Older peers may still ship with
> `DNS = 1.1.1.1, 8.8.8.8` instead of `DNS = 192.168.10.71` (Pi-hole). The
> tunnel will work, but `.internal` domains won't resolve. Fix by editing
> the client `wg0.conf` or regenerating the peer.

## Documentation

- [Understanding the WireGuard role](docs/understanding-wireguard-role.md) -- WireGuard role architecture and configuration details

## Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## Contributing

Contributions are welcome! Please feel free to submit a [Pull Request](https://github.com/TiPunchLabs/homelab/pulls).

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
