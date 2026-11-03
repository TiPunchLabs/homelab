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

Credentials are injected per command by `scripts/with-secrets` (reads `pass`);
no `terraform.tfvars` and no secret in the shell. Run from an owner terminal:

```bash
cd vpngate/terraform
../../scripts/with-secrets proxmox -- terraform plan
```

The local state (`terraform.tfstate`) is the only copy: back it up before any
apply.

**VM Configuration:**

- CPU: 1 core
- RAM: 512 MB
- Disk: 22 GB SSD
- Template ID: 9001
- VM Base ID: 9050
- IP: 192.168.10.50
- DNS (VM): 1.1.1.1, 8.8.8.8 (module default); VPN clients use Pi-hole `192.168.10.71`

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

### Public IP changes (known risk, accepted)

The ISP public IPv4 is dynamic and there is no dynamic DNS. Clients reach the
server through the public IPv4 written in their `Endpoint`, so **every
public IP change cuts every client** until its `Endpoint` is updated by hand.
Nothing changes on the server side.

- Symptom: client shows no recent handshake, `docker exec wg-easy wg show wg0
  latest-handshakes` shows nothing new for that peer, the server is healthy.
- Fix: update `Endpoint = <new public IPv4>:51820` in the client config.
- Seen on 2026-11-03: phone and PC fixed; the two other peers are **not
  updated yet**.
- `WG_HOST` (`wg_easy_host` ← `vault_public_endpoint`) still holds the
  previous public IPv4 **on purpose**. wg-easy v14 writes it as `Endpoint` in
  every client config and QR code it generates, for new **and** existing peers:
  a config downloaded or scanned from the UI today carries the old address and
  must be corrected by hand before use. Changing `WG_HOST` and setting up
  dynamic DNS were **declined by the owner for now** (2026-11-03).

## Operational state

- 2026-11-03 — **B5 done**: Proxmox `ipconfig0` aligned on `192.168.10.50/24`
  gw `192.168.10.1` by a guarded Terraform apply (bpg/proxmox 0.119.0); the
  next `terraform plan` returned `No changes` (rc 0). Cloud-init guards on the
  guest: `99-disable-network-config.cfg` (network) and
  `99-preserve-ssh-host-keys.cfg` (`ssh_deletekeys: false`), both manual, plus
  `ciupgrade 0` on Proxmox (`qm set`, root only, not modelled by Terraform).
  SSH host keys and netplan were preserved across the new cloud-init instance.
- Recovery points kept until the owner authorizes their removal: snapshot
  `pre-b5` (Proxmox) and `/root/*b5-pre*` archives on the guest (the WireGuard
  archive contains private keys).
- bpg 0.119 with `reboot_after_update = true` applies a non-hotpluggable
  change by guest-agent **shutdown then start**, not by the reboot API: a
  failed apply can leave the VM stopped (`qm start 9050`).

## Documentation

- [Understanding the WireGuard role](docs/understanding-wireguard-role.md) -- WireGuard role architecture and configuration details

## Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## Contributing

Contributions are welcome! Please feel free to submit a [Pull Request](https://github.com/TiPunchLabs/homelab/pulls).

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
