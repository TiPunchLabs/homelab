# Deployed services

## Overview

```
PROXMOX VE (192.168.1.100)
│
├── BASTION (bastion-60 / 192.168.1.60)
│   ├── GitLab Runner (shell executor, systemd)
│   ├── Terraform + Ansible (operational execution)
│   └── pass + GPG (secrets management)
│
├── DOCKHOST (dockhost-90 / 192.168.1.90)
│   ├── Docker Engine
│   ├── Portainer Agent ──► Managed by Portainer (local machine)
│   └── GitLab Runner (Docker executor)
│
└── KUBECLUSTER (192.168.1.40-42)
    ├── Control Plane (kubecluster-40)
    │   └── etcd, API Server, Controller Manager, Scheduler
    └── Workers (kubecluster-41, kubecluster-42)
        └── Kubelet, Kube-proxy, Containerd
```

---

## Dockhost (dockhost-90)

### Specifications

| Parameter | Value |
|-----------|--------|
| VMID | 9090 |
| IP | 192.168.1.90 |
| OS | Ubuntu 24.04 (cloud-init) |
| vCPU | 3 |
| RAM | 10 GB |
| Disk | 100 GB SSD |
| SSH | `ssh dockhost-90` (user: ansible) |

### Deployed Ansible roles

The playbook `dockhost/ansible/deploy.yml` runs the following roles:

| Role | Tag | Description |
|------|-----|-------------|
| `motd` | `motd` | Custom Message of the Day |
| `docker` | `docker` | Docker Engine + Docker Compose installation |
| `portainer_agent` | `portainer-agent` | Portainer Agent for centralized management |
| `postgresql` | `postgresql` | PostgreSQL 17.4 (port 5432) |
| `security_hardening` | `security-hardening` | SSH hardening, UFW, system security |
| `gitlab_runner` | `gitlab-runner` | GitLab Runner (Docker executor) |

### Portainer Agent

Portainer Agent to manage Docker remotely from the Portainer instance on the local machine.

```
Portainer (local machine) ──► Portainer Agent (dockhost-90:9001)
                                    │
                                    ▼
                              Docker Engine
```

**Details**:
- Image: `portainer/agent:2.33.3` (pinned by SHA256 digest)
- Exposed port: `9001`
- Volumes: Docker socket + Docker volumes
- Network: `vm-docker-90-net` (bridge)
- Installation: `/opt/portainer-agent/docker-compose.yml`

### GitLab Runner (Docker executor)

GitLab CI runner for the **tipunchlabs/homelab** project.

**Details**:
- Executor: Docker
- Installation: `/opt/gitlab-runner/docker-compose.yml` + `config/config.toml`
- Token: stored in Ansible Vault

**Required vault variable**: `vault_gitlab_runner_token` in `dockhost/ansible/group_vars/dockhost/vault/config.yml`

**Deployment**:
1. Register the runner on GitLab (project or group token)
2. Encrypt the token with `ansible-vault encrypt` in the vault file
3. Deploy with `ansible-playbook ansible/deploy.yml --tags gitlab-runner`
4. Verify in GitLab > Settings > CI/CD > Runners

### Security Hardening

Security configuration applied to the VM:
- SSH: key-based authentication only, root login disabled
- UFW: deny incoming by default, open ports: SSH (22), Portainer Agent (9001)
- Authorized users configured via Ansible Vault

### Pre-tasks

Before role execution, the playbook creates:
- `app_data` group for applications
- `/app/data/` directory (owner: root, group: app_data, mode: 0770)

---

## Bastion (bastion-60)

### Specifications

| Parameter | Value |
|-----------|--------|
| VMID | 9060 |
| IP | 192.168.1.60 |
| OS | Ubuntu 24.04 (cloud-init) |
| vCPU | 2 |
| RAM | 2 GB |
| Disk | 25 GB SSD |
| SSH | `ssh bastion-60` (user: ansible) |

### Deployed Ansible roles

The playbook `bastion/ansible/deploy.yml` runs the following roles:

| Role | Tag | Description |
|------|-----|-------------|
| `motd` | `motd` | Custom Message of the Day |
| `security_hardening` | `security-hardening` | SSH + UFW hardening |
| `tooling` | `tooling` | Python, uv, Terraform, direnv, pass, GPG, git clone homelab |
| `ssh_keys` | `ssh-keys` | SSH key deployment + config for all hosts |
| `gitlab_runner` | `gitlab-runner` | Native GitLab Runner (shell executor, systemd) |

### GitLab Runner (shell executor)

Native runner installed directly on the VM (no Docker).

**Details**:
- Executor: Shell (bash)
- Service: systemd (`gitlab-runner.service`)
- User: `ansible`
- Working directory: `/opt/gitlab-runner`
- Config: `/opt/gitlab-runner/config.toml`

The runner executes the `sync-bastion` job which synchronizes the `~/homelab` clone on the bastion on each push to `main`.

### Installed tooling

| Tool | Usage |
|-------|-------|
| **Terraform** | Infrastructure provisioning |
| **Ansible** (via uv) | Configuration and deployment |
| **pass** + GPG | Secrets management (GPG key without passphrase) |
| **direnv** | Auto-activation of venv and variables |
| **git** | `~/homelab` clone for operational execution |

---

## Kubecluster (kubecluster-40/41/42)

### Specifications

| Node | Role | VMID | IP | vCPU | RAM | Disk |
|------|------|------|-----|------|-----|--------|
| kubecluster-40 | Control Plane | 9040 | 192.168.1.40 | 2 | 4 GB | 35 GB |
| kubecluster-41 | Worker | 9041 | 192.168.1.41 | 1 | 3.5 GB | 30 GB |
| kubecluster-42 | Worker | 9042 | 192.168.1.42 | 1 | 3.5 GB | 30 GB |

### Deployed Ansible roles

The playbook `kubecluster/ansible/deploy.yml` contains 3 plays:

**Play 1: all nodes** (`hosts: all`)

| Role | Tag | Description |
|------|-----|-------------|
| `motd` | `motd` | Message of the Day |
| `cfg_nodes` | `cfg_nodes` | Node system configuration |
| `inst_runc` | `inst_runc` | runc installation |
| `inst_cni` | `inst_cni` | CNI plugins installation |
| `cfg_containerd` | `cfg_containerd` | containerd configuration |
| `inst_cri_tools` | `inst_cri_tools` | CRI tools installation (crictl) |
| `cfg_kubeadm_kubelet_kubectl` | `cfg_kubeadm_kubelet_kubectl` | kubeadm, kubelet, kubectl installation |

**Play 2: control plane** (`hosts: control_plane_nodes`)

| Role | Tag | Description |
|------|-----|-------------|
| `init_kubeadm` | `init_kubeadm` | Cluster initialization with kubeadm |
| `kubectl_cheat_sheet` | `kubectl_cheat_sheet` | kubectl aliases and completion |

**Play 3: workers** (`hosts: worker_nodes`)

| Role | Tag | Description |
|------|-----|-------------|
| `join_workers` | `join_workers` | Workers joining the cluster |

### Inventory

```yaml
kubecluster:
  children:
    control_plane_nodes:
      hosts:
        kubecluster-40:
    worker_nodes:
      hosts:
        kubecluster-41:
        kubecluster-42:
```

---

## Proxmox (hypervisor configuration)

### Specifications

| Parameter | Value |
|-----------|--------|
| IP | 192.168.1.100 |
| OS | Proxmox VE 9 (Debian Trixie) |
| SSH | `ssh pve` (user: ansible) |
| Web UI | https://192.168.1.100:8006 |

### Deployed Ansible roles

The playbook `proxmox/ansible/deploy.yml` configures the Proxmox hypervisor:

**Role `configure`**:

| Tag | Description |
|-----|-------------|
| `essentials` | No-subscription apt repos, base packages |
| `security_ssh_hardening` | SSH hardening, ansible user creation, key deployment |
| `setup_roles_users_tokens` | Proxmox API roles, users and tokens creation |
| `setup_storage` | Storage configuration (partitions, mounting, Proxmox addition) |
| `generate_vm_template` | Ubuntu Cloud-Init VM template generation |

**Role `manage`**:

| Tag | Description |
|-----|-------------|
| `display_token` | Display existing API tokens |

### API Tokens

The `setup_roles_users_tokens` tag creates two API tokens:

| Token ID | Role | Usage |
|----------|------|-------|
| `terraform-prov@pve!terraform` | `TerraformProv` | VM provisioning via Terraform |
| `ansible-prov@pve!ansible` | `AnsibleProv` | VM management via Ansible |

The secrets are stored in `pass`:
- `pass show proxmox/terraform-token-id` / `proxmox/terraform-token-secret`
- `pass show proxmox/ansible-token-id` / `proxmox/ansible-token-secret`

### Bootstrap

First execution (before SSH key deployment):

```bash
cd proxmox
ansible-playbook ansible/deploy.yml -u root --ask-pass --tags "security_ssh_hardening" \
  -e 'ansible_ssh_extra_args="-o PreferredAuthentications=password -o IdentitiesOnly=yes"'
```

> After bootstrap, root SSH access is disabled. Use `ansible@192.168.1.100` + `sudo -i`.

---

## Docker image security

All Docker images are pinned by **SHA256 digest** to ensure integrity:

```yaml
# Example
image: portainer/agent:2.33.3@sha256:1da68e0e...
```

The CI runs a **Trivy** scan (v0.69.3) on all images extracted from Jinja2 templates, with severity `HIGH,CRITICAL`.
