```
 ██╗  ██╗██╗   ██╗██████╗ ███████╗ ██████╗██╗     ██╗   ██╗███████╗████████╗███████╗██████╗
 ██║ ██╔╝██║   ██║██╔══██╗██╔════╝██╔════╝██║     ██║   ██║██╔════╝╚══██╔══╝██╔════╝██╔══██╗
 █████╔╝ ██║   ██║██████╔╝█████╗  ██║     ██║     ██║   ██║███████╗   ██║   █████╗  ██████╔╝
 ██╔═██╗ ██║   ██║██╔══██╗██╔══╝  ██║     ██║     ██║   ██║╚════██║   ██║   ██╔══╝  ██╔══██╗
 ██║  ██╗╚██████╔╝██████╔╝███████╗╚██████╗███████╗╚██████╔╝███████║   ██║   ███████╗██║  ██║
 ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝╚══════╝ ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
```

# KubeCluster - Kubernetes Cluster Automation

![Status](https://img.shields.io/badge/Status-Active-brightgreen)

This project automates the deployment of a Kubernetes cluster on Proxmox using Terraform for infrastructure provisioning and Ansible for cluster configuration.

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

| Node | Role | CPU | RAM | Disk | VMID | IP |
|------|------|-----|-----|------|------|-----|
| kubecluster-40 | Control Plane | 2 cores | 4096 MB | 35 GB | 9040 | 192.168.1.40 |
| kubecluster-41 | Worker | 1 core | 3584 MB | 30 GB | 9041 | 192.168.1.41 |
| kubecluster-42 | Worker | 1 core | 3584 MB | 30 GB | 9042 | 192.168.1.42 |

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
