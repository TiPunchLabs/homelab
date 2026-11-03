```
 ██╗  ██╗██╗   ██╗██████╗ ███████╗ ██████╗██╗     ██╗   ██╗███████╗████████╗███████╗██████╗
 ██║ ██╔╝██║   ██║██╔══██╗██╔════╝██╔════╝██║     ██║   ██║██╔════╝╚══██╔══╝██╔════╝██╔══██╗
 █████╔╝ ██║   ██║██████╔╝█████╗  ██║     ██║     ██║   ██║███████╗   ██║   █████╗  ██████╔╝
 ██╔═██╗ ██║   ██║██╔══██╗██╔══╝  ██║     ██║     ██║   ██║╚════██║   ██║   ██╔══╝  ██╔══██╗
 ██║  ██╗╚██████╔╝██████╔╝███████╗╚██████╗███████╗╚██████╔╝███████║   ██║   ███████╗██║  ██║
 ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝╚══════╝ ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
```

# KubeCluster - Kubernetes Cluster Automation

![Status](https://img.shields.io/badge/Status-Dormant-lightgrey)

This project automates the deployment of a Kubernetes cluster on Proxmox using Terraform for infrastructure provisioning and Ansible for cluster configuration.

## Current status: dormant

Owner decision R1 (B6, 2026-11-03): the cluster is dormant.

- No Kubernetes VM exists on Proxmox, and no Kubernetes cluster is running. VMIDs
  9040, 9041 and 9042 were checked absent cluster-wide on 2026-11-03.
- The Terraform and Ansible code is kept as the definition of a possible future
  cluster. It is not a description of running infrastructure.
- The previous local state was an orphan: it described VMs that no longer existed,
  under old module addresses (`kubebeast_*`), node `pve` and `192.168.1.40-42`. It was
  archived outside the repository (`~/.local/share/homelab-tfstate-backup/kubecluster/`,
  owner workstation) and must not be restored or refreshed. `terraform/` has no
  state file.
- VMIDs 9040-9042 and `192.168.10.40-42` stay reserved for kubecluster in the
  addressing plan. Check that they are still free at reactivation time.

> ⚠️ **Warning**: do not run `terraform apply` in `terraform/` without an explicit
> reactivation decision. On the empty state, a plan shows 3 creates (11 GiB of RAM in
> total). `vm_started = false` (the default) only leaves the VMs stopped: it does not
> stop Terraform from creating all three.

Before any reactivation:

1. Check host memory: the 3 VMs need 4096 + 2 x 3584 MiB, and the Proxmox host was
   close to full in 2026-11.
2. Check that VMIDs 9040-9042 and IPs `192.168.10.40-42` are free.
3. Decide the cloud-init `ciupgrade` policy. Template 9001 has no `ciupgrade`, so
   Proxmox applies its default `1`: an unattended package upgrade at first boot. The
   module does not set `initialization.upgrade`.
4. Put the cloud-init guards in place (see
   [`docs/backlog/cloud-init-guards-and-network-drift.md`](../docs/backlog/cloud-init-guards-and-network-drift.md)).
5. Review an owner plan (credentials through `scripts/with-secrets proxmox`) showing
   exactly the expected 3 creates before any apply.

## Project Architecture

The project deploys a complete Kubernetes cluster with:

### Cluster Topology

- **1 Control Plane Node** - Kubernetes master node
- **2 Worker Nodes** - Kubernetes worker nodes

### Infrastructure Stack

1. **Terraform**: VM provisioning on Proxmox
2. **Ansible**: Kubernetes installation and configuration
3. **kubeadm**: Kubernetes cluster bootstrapping
4. **containerd**: Container runtime
5. **CNI**: Container Network Interface

## Prerequisites

- Terraform (>= 1.11.0)
- Ansible
- Proxmox account with appropriate permissions
- A Proxmox VM template (template ID 9001 by default)

> 💡 **Provider**: `terraform/providers.tf` pins `bpg/proxmox` `0.119.0`, like the other
> roots. The quarantine on `0.96.0` was lifted on 2026-11-03 after an empty-state plan
> comparison of both versions (3 creates each, schema differences only, including the
> accepted `initialization.upgrade`). The pin change deploys nothing. See the root
> README, section "Proxmox provider version".

## Usage

### 1. VM Provisioning with Terraform

Only after a reactivation decision (see "Current status: dormant"). Credentials are
injected per command from the owner terminal; `pm_api_url` comes from the root `.envrc`.

```bash
cd kubecluster/terraform
terraform init
../../scripts/with-secrets proxmox -- terraform plan -out=kubecluster.tfplan
# apply only after reviewing the plan, and only with a reactivation decision
../../scripts/with-secrets proxmox -- terraform apply kubecluster.tfplan
```

**VM configuration (declared in `terraform/main.tf`, not deployed):**

| Node | Role | CPU | RAM | Disk | VMID | IP |
|------|------|-----|-----|------|------|-----|
| kubecluster-40 | Control Plane | 2 cores | 4096 MB | 35 GB | 9040 | 192.168.10.40 |
| kubecluster-41 | Worker | 1 core | 3584 MB | 30 GB | 9041 | 192.168.10.41 |
| kubecluster-42 | Worker | 1 core | 3584 MB | 30 GB | 9042 | 192.168.10.42 |

- Template ID: 9001
- Kubernetes Version: 1.34.0

### 2. Kubernetes Deployment with Ansible

1. Configure variables in `ansible/group_vars/kubecluster/`
2. Run the playbook:

   ```bash
   ansible-playbook ansible/deploy.yml
   ```

3. Deploy specific components using tags:

   ```bash
   # Configure all nodes (prerequisites)
   ansible-playbook ansible/deploy.yml --tags cfg_nodes

   # Install containerd
   ansible-playbook ansible/deploy.yml --tags cfg_containerd

   # Install kubeadm, kubelet, kubectl
   ansible-playbook ansible/deploy.yml --tags cfg_kubeadm_kubelet_kubectl

   # Initialize control plane
   ansible-playbook ansible/deploy.yml --tags init_kubeadm

   # Join worker nodes
   ansible-playbook ansible/deploy.yml --tags join_workers
   ```

### Available Ansible Tags

| Tag                         | Description                              |
| --------------------------- | ---------------------------------------- |
| `motd`                      | Custom Message of the Day (ASCII art)    |
| `cfg_nodes`                 | Configure nodes (packages, kernel, etc.) |
| `inst_runc`                 | Install runc                             |
| `inst_cni`                  | Install CNI plugins                      |
| `cfg_containerd`            | Configure containerd runtime             |
| `inst_cri_tools`            | Install CRI tools (crictl)               |
| `cfg_kubeadm_kubelet_kubectl` | Install kubeadm, kubelet, kubectl      |
| `init_kubeadm`              | Initialize Kubernetes control plane      |
| `kubectl_cheat_sheet`       | Configure kubectl aliases and completion |
| `join_workers`              | Join worker nodes to cluster             |

## Security

Sensitive files are encrypted with Ansible Vault. A pre-commit hook verifies that files in the `vault/` directory are properly encrypted.

To edit vault files:

```bash
ansible-vault edit ansible/group_vars/kubecluster/vault/main.yml
```

## Code Management

The project uses [uv](https://github.com/astral-sh/uv) for Python dependency management.

### Setup

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Install pre-commit hooks
uv run pre-commit install
```

### Pre-commit Hooks

The project includes pre-commit configuration for:

- Shell script formatting
- Ansible syntax checking
- Terraform validation
- Ensuring sensitive files are encrypted

```bash
# Run all hooks manually
uv run pre-commit run --all-files
```

## File Structure

```
.
├── ansible/                      # Ansible configuration
│   ├── deploy.yml                # Main playbook
│   ├── inventory.yml             # Host inventory
│   ├── group_vars/
│   │   └── kubecluster/            # Group variables
│   │       ├── all/              # Non-sensitive vars
│   │       └── vault/            # Encrypted variables
│   └── roles/                    # Ansible roles
│       ├── motd/                 # Message of the Day (ASCII art)
│       ├── cfg_nodes/            # Node configuration
│       ├── inst_runc/            # runc installation
│       ├── inst_cni/             # CNI installation
│       ├── cfg_containerd/       # containerd configuration
│       ├── inst_cri_tools/       # CRI tools installation
│       ├── cfg_kubeadm_kubelet_kubectl/  # Kubernetes tools
│       ├── init_kubeadm/         # Control plane init
│       ├── kubectl_cheat_sheet/  # kubectl helpers
│       └── join_workers/         # Worker node joining
├── terraform/
│   ├── main.tf                   # Terraform main configuration
│   ├── variables.tf              # Variable definitions
│   └── outputs.tf                # Output definitions
├── modules/
│   └── proxmox_vm_template/      # Reusable VM module
├── scripts/
│   └── ansible-vault-pass.sh     # Vault password script
└── README.md                     # This file
```

## Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
