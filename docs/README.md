# Homelab IaC Documentation

Technical documentation for the homelab project - Infrastructure as Code for Proxmox VE.

## Getting started

| Document | Description |
|----------|-------------|
| [00-getting-started.md](00-getting-started.md) | **Full setup guide** — from bare Proxmox to production environment |

## Table of contents

| Document | Description |
|----------|-------------|
| [01-architecture.md](01-architecture.md) | Global architecture, VMs, network, tech stack |
| [02-services.md](02-services.md) | Deployed services (bastion, dockhost, kubecluster, proxmox) |
| [03-commandes.md](03-commandes.md) | Terraform, Ansible, SSH, code quality commands |
| [04-troubleshooting.md](04-troubleshooting.md) | Common problem resolution |

## References

| Document | Description |
|----------|-------------|
| [references/ip-addresses.md](references/ip-addresses.md) | IP addressing plan, VMs, ports, SSH config |

## ADR (Architecture Decision Records)

| Document | Description |
|----------|-------------|
| [adr/bastion.md](adr/bastion.md) | Bastion architecture decisions |
| [adr/caddy.md](adr/caddy.md) | Caddy architecture decisions |
| [adr/pihole.md](adr/pihole.md) | Pi-hole architecture decisions |
| [adr/proxmox.md](adr/proxmox.md) | Proxmox hypervisor architecture decisions |

## Guides

| Document | Description |
|----------|-------------|
| [guides/guide-wireguard-client-linux.md](guides/guide-wireguard-client-linux.md) | WireGuard client setup on Linux |

## Sources of truth

The documentation is aligned with the following code files:

| Data | Source |
|------|--------|
| Bastion VM specs | `bastion/terraform/main.tf` |
| Dockhost VM specs | `dockhost/terraform/main.tf` |
| Kubecluster VM specs | `kubecluster/terraform/main.tf` |
| Bastion services | `bastion/ansible/deploy.yml` + roles |
| Dockhost services | `dockhost/ansible/deploy.yml` + roles |
| Kubecluster services | `kubecluster/ansible/deploy.yml` + roles |
| Proxmox config | `proxmox/ansible/deploy.yml` + roles |
| CI/CD | `.gitlab-ci.yml` (GitLab CI only) |
| SSH config | `~/.ssh/config` |
| Secrets | `*/ansible/group_vars/*/vault/` + `*/ansible/host_vars/*/vault/` |
