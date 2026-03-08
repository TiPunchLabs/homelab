# Documentation Homelab IaC

Documentation technique du projet homelab - Infrastructure as Code pour Proxmox VE.

## Sommaire

| Document | Description |
|----------|-------------|
| [01-architecture.md](01-architecture.md) | Architecture globale, VMs, reseau, stack technique |
| [02-services.md](02-services.md) | Services deployes (dockhost, kubecluster, proxmox) |
| [03-commandes.md](03-commandes.md) | Commandes Terraform, Ansible, SSH, qualite du code |
| [04-troubleshooting.md](04-troubleshooting.md) | Resolution de problemes courants |

## References

| Document | Description |
|----------|-------------|
| [references/ip-addresses.md](references/ip-addresses.md) | Plan d'adressage IP, VMs, ports, config SSH |

## Sources de verite

La documentation est alignee sur les fichiers de code suivants :

| Donnee | Source |
|--------|--------|
| Specs VM dockhost | `dockhost/terraform/main.tf` |
| Specs VM kubecluster | `kubecluster/terraform/main.tf` |
| Services dockhost | `dockhost/ansible/deploy.yml` + roles |
| Services kubecluster | `kubecluster/ansible/deploy.yml` + roles |
| Config SSH | `~/.ssh/config` |
| Secrets | `*/ansible/group_vars/*/vault/` |
