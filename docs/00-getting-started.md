# Getting started

> **Objective**: Deploy a fully functional homelab from a bare Proxmox VE server to a production-ready environment with bastion, Docker services, and Kubernetes cluster.
>
> **Prerequisites**: A physical server with Proxmox VE installed, a local workstation running Linux, and basic knowledge of SSH, Ansible, and Terraform.

## Mental model

```
LOCAL WORKSTATION                    PROXMOX VE (192.168.1.100)
┌──────────────────┐                ┌──────────────────────────────────┐
│ pass (GPG)       │   1. Bootstrap │                                  │
│ SSH keys         │───────────────►│  SSH hardening + ansible user    │
│ uv + direnv      │   (root)       │  API tokens → stored in pass    │
│ Terraform        │                │  VM template (cloud-init)        │
│ Ansible          │                │                                  │
│                  │   2. Provision │  ┌────────────────────────────┐  │
│                  │───────────────►│  │ bastion-60  (.60)          │  │
│                  │   (terraform)  │  │ → ansible, terraform, pass │  │
│                  │                │  │ → GitLab Runner (shell)    │  │
│                  │   3. Configure │  ├────────────────────────────┤  │
│                  │───────────────►│  │ dockhost-90 (.50)          │  │
│                  │   (ansible)    │  │ → Docker, Portainer        │  │
│                  │                │  │ → GitLab Runner (docker)   │  │
│                  │                │  ├────────────────────────────┤  │
│                  │                │  │ kubecluster-40/41/42       │  │
│                  │                │  │ → Kubernetes (kubeadm)     │  │
│                  │                │  └────────────────────────────┘  │
└──────────────────┘                └──────────────────────────────────┘

Order: Proxmox → Bastion → Dockhost / Kubecluster
       (each VM: Terraform provision → Ansible configure)
```

---

## Table of contents

1. [Install Proxmox VE](#1-install-proxmox-ve)
2. [Prepare the local workstation](#2-prepare-the-local-workstation)
3. [Bootstrap Proxmox](#3-bootstrap-proxmox)
4. [Provision and configure Bastion](#4-provision-and-configure-bastion)
5. [Provision and configure Dockhost](#5-provision-and-configure-dockhost)
6. [Provision and configure Kubecluster](#6-provision-and-configure-kubecluster)
7. [Configure GitLab CI/CD](#7-configure-gitlab-cicd)
8. [Verification checklist](#8-verification-checklist)
9. [Appendix](#appendix)

---

## 1. Install Proxmox VE

### 1.1 Prepare a bootable USB with Ventoy

[Ventoy](https://www.ventoy.net/) lets you boot ISO files directly from a USB drive — no need to flash a new drive for each ISO.

```bash
# Download and extract Ventoy
wget https://github.com/ventoy/Ventoy/releases/download/v1.1.05/ventoy-1.1.05-linux.tar.gz
tar xzf ventoy-1.1.05-linux.tar.gz
cd ventoy-1.1.05

# Install Ventoy on your USB drive (replace /dev/sdX with your device)
sudo ./Ventoy2Disk.sh -i /dev/sdX
```

> **Warning**: This erases the USB drive. Double-check the device path with `lsblk` before running.

Then copy the Proxmox VE ISO onto the Ventoy partition:

```bash
# Download the ISO
wget https://enterprise.proxmox.com/iso/proxmox-ve_8.4-1.iso

# Mount the Ventoy partition and copy the ISO
mount /dev/sdX1 /mnt
cp proxmox-ve_8.4-1.iso /mnt/
umount /mnt
```

> **Note**: You can store multiple ISOs on the same Ventoy drive. On boot, Ventoy displays a menu to choose which ISO to launch.

### 1.2 Install Proxmox VE

Boot the server from the Ventoy USB drive, select the Proxmox VE ISO from the menu, and follow the installer.

> **Warning**: If the installer hangs on a black screen or shows graphical glitches, the GPU driver is likely incompatible with the installer's framebuffer. In the Proxmox boot menu, select **"Install Proxmox VE (Terminal UI)"** or edit the boot entry and add `nomodeset` to the kernel parameters. This disables kernel mode-setting and forces a basic video driver, which is enough to complete the installation. This is common on servers with older or unsupported GPUs (some NVIDIA, Matrox, Aspeed BMC).

During installation:
- Set the management IP to **192.168.1.100/24**
- Set the gateway to **192.168.1.1**
- Set DNS to **1.1.1.1** (or your preferred resolver)
- Set a root password (needed for bootstrap)

### 1.3 Verify access

After installation, confirm:

```bash
# Web interface (from browser)
https://192.168.1.100:8006

# SSH access (from local workstation)
ssh root@192.168.1.100
```

### 1.4 Network sanity check

On the Proxmox server, verify the network configuration:

```bash
# DNS resolution
ping -c 1 google.com

# Check resolv.conf points to a real resolver (NOT 127.0.0.1)
cat /etc/resolv.conf

# Check gateway is correct (should be 192.168.1.1, NOT 192.168.1.100)
ip route show default
```

> **Warning**: If `/etc/resolv.conf` points to `127.0.0.1` or the gateway is wrong, fix `/etc/network/interfaces` and restart networking before proceeding. See [04-troubleshooting.md](04-troubleshooting.md).

---

## 2. Prepare the local workstation

### 2.1 Required software

Install the following tools:

| Tool | Purpose | Install |
|------|---------|---------|
| **git** | Version control | `sudo apt install git` |
| **uv** | Python dependency manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **direnv** | Auto-load environment variables | `sudo apt install direnv` |
| **pass** | Password store (GPG-backed) | `sudo apt install pass` |
| **gnupg** | GPG encryption | `sudo apt install gnupg` |
| **terraform** | Infrastructure provisioning | [HashiCorp install guide](https://developer.hashicorp.com/terraform/install) |
| **pre-commit** | Git hooks | Installed via uv (see below) |

Add the direnv hook to your shell:

```bash
# For bash
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc
source ~/.bashrc

# For zsh
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
source ~/.zshrc
```

### 2.2 Clone the repository

```bash
git clone git@gitlab.com:tipunchlabs/homelab.git ~/homelab
cd ~/homelab
```

### 2.3 Install Python dependencies

```bash
uv sync
```

This creates a `.venv/` and installs Ansible, ansible-lint, and pre-commit.

### 2.4 Install pre-commit hooks

```bash
uv run pre-commit install
```

### 2.5 Install Ansible collections

```bash
cd proxmox && uv run ansible-galaxy collection install -r ansible/requirements.yml && cd ..
```

### 2.6 Generate SSH keys

Two SSH key pairs are needed:

```bash
# Key for Proxmox root access
ssh-keygen -t rsa -b 4096 -f ~/.ssh/proxmox -C "proxmox-root"

# Key for all VMs (cloud-init ansible user)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_vm_proxmox_rsa -C "proxmox-vms"
```

Copy the Proxmox root public key to the server (needed for post-bootstrap access):

```bash
ssh-copy-id -i ~/.ssh/proxmox.pub root@192.168.1.100
```

### 2.7 Configure SSH client

Add the following to `~/.ssh/config`:

```
Host pve
  HostName 192.168.1.100
  User ansible
  IdentityFile ~/.ssh/proxmox
  IdentitiesOnly yes

Host bastion-60
  HostName 192.168.1.60
  User ansible
  IdentityFile ~/.ssh/id_vm_proxmox_rsa
  IdentitiesOnly yes

Host dockhost-90
  HostName 192.168.1.90
  User ansible
  IdentityFile ~/.ssh/id_vm_proxmox_rsa
  IdentitiesOnly yes

Host kubecluster-40
  HostName 192.168.1.40
  User ansible
  IdentityFile ~/.ssh/id_vm_proxmox_rsa
  IdentitiesOnly yes

Host kubecluster-41
  HostName 192.168.1.41
  User ansible
  IdentityFile ~/.ssh/id_vm_proxmox_rsa
  IdentitiesOnly yes

Host kubecluster-42
  HostName 192.168.1.42
  User ansible
  IdentityFile ~/.ssh/id_vm_proxmox_rsa
  IdentitiesOnly yes
```

### 2.8 Set up GPG and password store

Initialize the password store with your GPG key:

```bash
# If you don't have a GPG key yet
gpg --full-generate-key

# Get your GPG key ID
gpg --list-keys --keyid-format long

# Initialize pass
pass init <YOUR_GPG_KEY_ID>
```

Insert the Ansible Vault password:

```bash
# Create a strong password for encrypting Ansible vault files
pass insert ansible/vault
```

### 2.9 Allow direnv

```bash
cd ~/homelab
direnv allow
```

> **Note**: At this point, direnv will fail on `pass` lookups for secrets that don't exist yet (Proxmox tokens, GitLab tokens). This is expected. They will be populated during the bootstrap steps.

---

## 3. Bootstrap Proxmox

The Proxmox bootstrap is a one-time procedure that transforms a fresh Proxmox VE install into a managed host.

### 3.1 Understand the bootstrap pattern

```
BEFORE BOOTSTRAP               AFTER BOOTSTRAP
─────────────────               ───────────────
SSH: root + password     →      SSH: ansible + key only
No API tokens            →      Terraform + Ansible tokens
Enterprise repos (401)   →      No-subscription repos
No VM template           →      ubuntu-2404-cloudinit-template
```

> **Warning**: The bootstrap must run as `root` with password authentication because the `ansible` user does not exist yet. After bootstrap, root SSH login is disabled and only key-based authentication is allowed.

### 3.2 Run SSH hardening (creates ansible user)

```bash
cd proxmox

ansible-playbook ansible/deploy.yml \
  -u root --ask-pass \
  --tags "security_ssh_hardening"
```

This task:
- Installs `sudo` and creates the `wheel` group
- Creates the `ansible` user with passwordless sudo
- Adds your public key (`~/.ssh/proxmox.pub`) to `ansible`'s authorized keys
- Disables empty password and password-based SSH login

> **Warning**: After this step, root password login is disabled. Make sure `ssh pve` works with the `ansible` user before proceeding.

### 3.3 Verify ansible user access

```bash
ssh pve
# Should connect as ansible@192.168.1.100 without password prompt
```

If this fails with `Permission denied (publickey)`, check that:
- `~/.ssh/proxmox` exists and matches the `.pub` deployed in step 3.2
- `ansible.cfg` has `private_key_file = ~/.ssh/proxmox`
- SSH agent is not overriding with wrong keys (`IdentitiesOnly=yes` prevents this)

### 3.4 Create API tokens

```bash
ansible-playbook ansible/deploy.yml --tags "setup_roles_users_tokens"
```

This creates two Proxmox API tokens:

| Token | User | Role | Purpose |
|-------|------|------|---------|
| `terraform-prov@pve!terraform` | terraform-prov | TerraformProv | VM provisioning (full VM lifecycle) |
| `ansible-prov@pve!ansible` | ansible-prov | AnsibleProv | VM power management and audit |

The token secrets are automatically stored in your local `pass` store:

```
proxmox/
├── terraform-token-id       # terraform-prov@pve!terraform
├── terraform-token-secret   # <secret value>
├── ansible-token-id         # ansible-prov@pve!ansible
└── ansible-token-secret     # <secret value>
```

After this step, reload direnv to pick up the new tokens:

```bash
cd ~/homelab
direnv allow
```

Verify:

```bash
echo $TF_VAR_pm_api_token_id
# Should output: terraform-prov@pve!terraform
```

### 3.5 Configure storage (optional)

If your Proxmox server has a secondary disk for backups/ISOs:

```bash
ansible-playbook ansible/deploy.yml --tags "setup_storage"
```

This formats `/dev/sdb`, mounts it to `/mnt/pve/hdd-storage`, and registers it in Proxmox for backup, ISO, and template content.

### 3.6 Generate the VM template

```bash
ansible-playbook ansible/deploy.yml --tags "generate_vm_template"
```

This creates the cloud-init VM template (ID **9001**) that all other VMs are cloned from:
- Downloads Ubuntu 24.04 Server cloud image (with SHA256 checksum verification)
- Customizes with `virt-customize`: installs qemu-guest-agent, configures GRUB serial console
- Creates the `ansible` user with your SSH public key baked in
- Converts the VM to a template

Verify in the Proxmox web UI: the template `ubuntu-2404-cloudinit-template` (ID 9001) should appear under the node.

### 3.7 Run a full deployment (optional)

To run all Proxmox tasks at once (idempotent):

```bash
ansible-playbook ansible/deploy.yml
```

---

## 4. Provision and configure Bastion

The bastion VM is the control plane — it runs Terraform and Ansible for the other VMs, holds all SSH keys and secrets, and executes the GitLab CI/CD pipeline.

### 4.1 Provision the VM

```bash
cd bastion/terraform
terraform init
terraform plan
terraform apply
```

This creates:
- **bastion-60** (VMID 9090, IP 192.168.1.60)
- 2 vCPU, 2 GB RAM, 25 GB disk
- Cloned from template 9001 with cloud-init (ansible user + SSH key)

Wait for the VM to boot and cloud-init to finish (~1-2 minutes), then verify:

```bash
ssh bastion-60
# Should connect as ansible@192.168.1.60
```

### 4.2 Prepare vault secrets

Before running the Ansible playbook, the vault file must contain all required secrets. Edit the encrypted vault:

```bash
cd bastion
ansible-vault edit ansible/group_vars/bastion/vault/main.yml
```

Required vault variables:

```yaml
# SSH keys (private key content)
vault_ssh_key_vm_proxmox: |
  -----BEGIN OPENSSH PRIVATE KEY-----
  <content of ~/.ssh/id_vm_proxmox_rsa>
  -----END OPENSSH PRIVATE KEY-----

vault_ssh_key_proxmox: |
  -----BEGIN OPENSSH PRIVATE KEY-----
  <content of ~/.ssh/proxmox>
  -----END OPENSSH PRIVATE KEY-----

# GPG key for pass on bastion
vault_gpg_private_key: |
  <output of: gpg --export-secret-keys --armor YOUR_KEY_ID>

vault_gpg_key_id: "YOUR_GPG_KEY_ID"

# Secrets to populate pass on bastion
vault_pass_ansible_vault: "<output of: pass ansible/vault>"
vault_pass_proxmox_api_token_id: "<output of: pass proxmox/terraform-token-id>"
vault_pass_proxmox_api_token_secret: "<output of: pass proxmox/terraform-token-secret>"
vault_pass_github_terraform_token: "<your GitHub PAT>"

# Security
vault_security_allow_users:
  - ansible

# GitLab Runner
vault_gitlab_runner_token: "<GitLab runner registration token>"
```

### 4.3 Configure the bastion

```bash
cd bastion
ansible-playbook ansible/deploy.yml
```

This runs 5 roles in order:

| Role | Tag | What it does |
|------|-----|--------------|
| **motd** | `motd` | Custom message of the day |
| **security_hardening** | `security-hardening` | SSH hardening + UFW firewall (port 22 only) |
| **tooling** | `tooling` | Installs git, uv, Terraform, direnv, pass + GPG, clones homelab repo |
| **ssh_keys** | `ssh-keys` | Deploys SSH private keys + config for all hosts |
| **gitlab_runner** | `gitlab-runner` | Installs GitLab Runner (shell executor, systemd service) |

### 4.4 Verify bastion is operational

```bash
ssh bastion-60

# Check tools
terraform version
ansible --version
pass show ansible/vault

# Check direnv loads secrets
cd ~/homelab
echo $TF_VAR_pm_api_token_id

# Check SSH to other hosts
ssh pve hostname       # Should print: proxmox
ssh dockhost-90        # Will fail until dockhost is provisioned (expected)

# Check GitLab Runner
sudo systemctl status gitlab-runner
```

---

## 5. Provision and configure Dockhost

The dockhost VM runs Docker services: Portainer agent, GitLab Runner (Docker executor), and PostgreSQL.

### 5.1 Provision the VM

From the local workstation (or from bastion):

```bash
cd dockhost/terraform
terraform init
terraform plan
terraform apply
```

This creates:
- **dockhost-90** (VMID 9090, IP 192.168.1.90)
- 3 vCPU, 10 GB RAM, 100 GB disk

Wait for boot + cloud-init, then verify:

```bash
ssh dockhost-90
```

### 5.2 Prepare vault secrets

```bash
cd dockhost
ansible-vault edit ansible/group_vars/dockhost/vault/main.yml
```

Required vault variables depend on the roles deployed (GitLab Runner token, Portainer config, etc.).

### 5.3 Configure dockhost

```bash
cd dockhost
ansible-playbook ansible/deploy.yml
```

Roles:

| Role | Tag | What it does |
|------|-----|--------------|
| **motd** | `motd` | Custom message of the day |
| **docker** | `docker` | Docker Engine + Docker Compose plugin |
| **portainer_agent** | `portainer-agent` | Portainer container management agent (port 9001) |
| **postgresql** | `postgresql` | PostgreSQL database container |
| **gitlab_runner** | `gitlab-runner` | GitLab Runner with Docker executor |

### 5.4 Verify dockhost

```bash
ssh dockhost-90

docker ps
# Should show running containers: portainer_agent, gitlab_runner, postgresql

docker compose -f /opt/portainer-agent/docker-compose.yml ps
docker compose -f /opt/gitlab-runner/docker-compose.yml ps
```

---

## 6. Provision and configure Kubecluster

The Kubernetes cluster consists of 1 control plane node and 2 worker nodes, deployed with kubeadm.

### 6.1 Provision the VMs

```bash
cd kubecluster/terraform
terraform init
terraform plan
terraform apply
```

This creates 3 VMs:

| VM | VMID | IP | Role |
|----|------|----|------|
| kubecluster-40 | 9040 | 192.168.1.40 | Control Plane (2 vCPU, 4 GB RAM, 35 GB) |
| kubecluster-41 | 9041 | 192.168.1.41 | Worker (1 vCPU, 3.5 GB RAM, 30 GB) |
| kubecluster-42 | 9042 | 192.168.1.42 | Worker (1 vCPU, 3.5 GB RAM, 30 GB) |

> **Note**: By default, `vm_started` is `false` for kubecluster. Set `vm_started = true` in `terraform.tfvars` or pass `-var 'vm_started=true'` to start the VMs.

Verify:

```bash
ssh kubecluster-40
ssh kubecluster-41
ssh kubecluster-42
```

### 6.2 Configure the cluster

```bash
cd kubecluster
ansible-playbook ansible/deploy.yml
```

The playbook runs 3 plays:

**Play 1 — All nodes** (kubecluster-40, 41, 42):

| Role | Tag | What it does |
|------|-----|--------------|
| **motd** | `motd` | Custom message of the day |
| **cfg_nodes** | `cfg_nodes` | Kernel params, swap disable, system config |
| **inst_runc** | `inst_runc` | Install runc container runtime |
| **inst_cni** | `inst_cni` | Install CNI plugins |
| **cfg_containerd** | `cfg_containerd` | Configure containerd |
| **inst_cri_tools** | `inst_cri_tools` | Install crictl and CRI tools |
| **cfg_kubeadm_kubelet_kubectl** | `cfg_kubeadm_kubelet_kubectl` | Install kubeadm, kubelet, kubectl |

**Play 2 — Control plane only** (kubecluster-40):

| Role | Tag | What it does |
|------|-----|--------------|
| **init_kubeadm** | `init_kubeadm` | Initialize the Kubernetes control plane |
| **kubectl_cheat_sheet** | `kubectl_cheat_sheet` | Deploy kubectl aliases and completions |

**Play 3 — Workers only** (kubecluster-41, 42):

| Role | Tag | What it does |
|------|-----|--------------|
| **join_workers** | `join_workers` | Join worker nodes to the cluster |

### 6.3 Verify the cluster

```bash
ssh kubecluster-40

kubectl get nodes
# NAME             STATUS   ROLES           AGE   VERSION
# kubecluster-40   Ready    control-plane   ...   v1.x.x
# kubecluster-41   Ready    <none>          ...   v1.x.x
# kubecluster-42   Ready    <none>          ...   v1.x.x

kubectl get pods -A
# All pods should be Running
```

---

## 7. Configure GitLab CI/CD

### 7.1 GitLab project setup

The project is hosted on GitLab (`gitlab.com/tipunchlabs/homelab`) with a read-only mirror on GitHub (`github.com/TiPunchLabs/homelab`).

### 7.2 CI/CD variables

In GitLab, go to **Settings > CI/CD > Variables** and add:

| Variable | Type | Protected | Masked | Description |
|----------|------|-----------|--------|-------------|
| `ANSIBLE_VAULT_PASSWORD` | Variable | Yes | Yes | Output of `pass ansible/vault` |

### 7.3 Runner registration

Two runners are used:

| Runner | Location | Executor | Purpose |
|--------|----------|----------|---------|
| **bastion-60** | bastion VM | Shell | Ansible/Terraform execution, bastion sync |
| **dockhost-90** | dockhost VM | Docker | Lint, security scans (isolated containers) |

Runner tokens are generated in GitLab (**Settings > CI/CD > Runners > New project runner**) and stored in the respective vault files.

### 7.4 Pipeline overview

The CI pipeline (`.gitlab-ci.yml`) runs 3 stages:

```
lint                    security                deploy
├── ansible-lint        ├── security-check      └── sync-bastion
├── terraform-lint      └── scan-docker-images      (main branch only)
└── shell-lint
```

- **ansible-lint**: Lints all Ansible code
- **terraform-lint**: Format check + validate all Terraform code
- **shell-lint**: Shellcheck all scripts
- **security-check**: Verifies vault encryption, no plaintext secrets
- **scan-docker-images**: Trivy scan on Docker images (HIGH/CRITICAL)
- **sync-bastion**: Pulls latest code on bastion (runs on `main` branch only, on bastion runner)

### 7.5 GitLab push mirror (optional)

The project can mirror to GitHub automatically. This is managed via Terraform in `gitlab-terraform/` and requires:
- A GitHub PAT stored in `pass github/gitlab-push-mirror-homelab`
- The `TF_VAR_github_mirror_token` variable in `.envrc`

---

## 8. Verification checklist

After completing all steps, verify each component:

### Proxmox

- [ ] Web UI accessible at `https://192.168.1.100:8006`
- [ ] `ssh pve` connects as `ansible` (no password prompt)
- [ ] Root SSH login is disabled
- [ ] API tokens exist: `pass proxmox/terraform-token-id`
- [ ] VM template 9001 visible in Proxmox UI

### Bastion

- [ ] `ssh bastion-60` connects successfully
- [ ] `terraform version` outputs >= 1.11.0
- [ ] `ansible --version` outputs >= 13.2.0
- [ ] `pass show ansible/vault` returns the vault password
- [ ] `cd ~/homelab && echo $TF_VAR_pm_api_token_id` returns the token ID
- [ ] `sudo systemctl status gitlab-runner` shows active

### Dockhost

- [ ] `ssh dockhost-90` connects successfully
- [ ] `docker ps` shows running containers
- [ ] Portainer Agent is reachable on port 9001
- [ ] GitLab Runner container is running

### Kubecluster

- [ ] All 3 nodes respond to SSH
- [ ] `kubectl get nodes` shows all nodes in `Ready` state
- [ ] `kubectl get pods -A` shows all system pods running

### CI/CD

- [ ] Push to `main` triggers the pipeline on GitLab
- [ ] All lint jobs pass
- [ ] Security check passes
- [ ] `sync-bastion` deploys to bastion on `main` branch merges

---

## Appendix

### A. Pass nomenclature

Complete password store structure:

```
~/.password-store/
├── ansible/
│   └── vault               # Ansible Vault password
├── proxmox/
│   ├── terraform-token-id      # terraform-prov@pve!terraform
│   ├── terraform-token-secret  # Terraform token secret
│   ├── ansible-token-id        # ansible-prov@pve!ansible
│   └── ansible-token-secret    # Ansible token secret
├── github/
│   ├── terraform-token         # GitHub PAT for Terraform provider
│   └── gitlab-push-mirror-homelab  # GitHub PAT for GitLab mirror
└── gitlab/
    ├── terraform-token         # GitLab PAT for Terraform provider
    └── tipunchlabs-group-id    # GitLab group numeric ID
```

### B. Environment variables (.envrc)

The `.envrc` file auto-exports these variables via direnv:

| Variable | Source | Used by |
|----------|--------|---------|
| `TF_VAR_pm_api_url` | Hardcoded | Terraform (Proxmox provider) |
| `TF_VAR_pm_api_token_id` | `pass proxmox/terraform-token-id` | Terraform (Proxmox provider) |
| `TF_VAR_pm_api_token_secret` | `pass proxmox/terraform-token-secret` | Terraform (Proxmox provider) |
| `TF_VAR_github_token` | `pass github/terraform-token` | Terraform (GitHub provider) |
| `TF_VAR_github_owner` | Hardcoded (`TiPunchLabs`) | Terraform (GitHub provider) |
| `TF_VAR_github_mirror_token` | `pass github/gitlab-push-mirror-homelab` | Terraform (GitLab mirror) |
| `TF_VAR_gitlab_token` | `pass gitlab/terraform-token` | Terraform (GitLab provider) |
| `TF_VAR_gitlab_namespace_id` | `pass gitlab/tipunchlabs-group-id` | Terraform (GitLab provider) |
| `ANSIBLE_VAULT_PASSWORD` | `pass ansible/vault` | Ansible Vault |
| `PROXMOX_IP` | Hardcoded (`192.168.1.100`) | Scripts |

### C. IP address quick reference

| Host | IP | VMID | SSH alias |
|------|----|------|-----------|
| Proxmox VE | 192.168.1.100 | — | `pve` |
| bastion-60 | 192.168.1.60 | 9060 | `bastion-60` |
| dockhost-90 | 192.168.1.90 | 9090 | `dockhost-90` |
| kubecluster-40 | 192.168.1.40 | 9040 | `kubecluster-40` |
| kubecluster-41 | 192.168.1.41 | 9041 | `kubecluster-41` |
| kubecluster-42 | 192.168.1.42 | 9042 | `kubecluster-42` |

### D. Troubleshooting quick links

| Problem | See |
|---------|-----|
| SSH connection refused | [04-troubleshooting.md — SSH](04-troubleshooting.md#ssh) |
| Terraform provider errors | [04-troubleshooting.md — Terraform](04-troubleshooting.md#terraform) |
| Ansible vault password not found | [04-troubleshooting.md — Ansible](04-troubleshooting.md#ansible) |
| Docker containers won't start | [04-troubleshooting.md — Docker](04-troubleshooting.md#docker-on-dockhost-90) |
| Kubernetes nodes not ready | [04-troubleshooting.md — Kubernetes](04-troubleshooting.md#kubernetes-kubecluster) |
| Pre-commit hooks fail | [04-troubleshooting.md — CI/CD](04-troubleshooting.md#cicd) |
