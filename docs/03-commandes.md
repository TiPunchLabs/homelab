# Command reference

## Proxmox

### Initial bootstrap (first execution)

```bash
cd proxmox
ansible-playbook ansible/deploy.yml -u root --ask-pass --tags "security_ssh_hardening" \
  -e 'ansible_ssh_extra_args="-o PreferredAuthentications=password -o IdentitiesOnly=yes"'
```

### Full deployment

```bash
cd proxmox
ansible-playbook ansible/deploy.yml
```

### By tag

```bash
# Essential packages (apt sources + base packages)
ansible-playbook ansible/deploy.yml --tags "essentials"

# SSH hardening
ansible-playbook ansible/deploy.yml --tags "security_ssh_hardening"

# API roles/users/tokens configuration
ansible-playbook ansible/deploy.yml --tags "setup_roles_users_tokens"

# Storage configuration
ansible-playbook ansible/deploy.yml --tags "setup_storage"

# VM template generation
ansible-playbook ansible/deploy.yml --tags "generate_vm_template"

# Display existing API tokens
ansible-playbook ansible/deploy.yml --tags "display_token"
```

---

## Dockhost

### Provisioning (Terraform)

```bash
cd dockhost/terraform
terraform init
terraform plan
terraform apply
```

### Configuration (Ansible)

```bash
cd dockhost
ansible-playbook ansible/deploy.yml
```

### By tag

```bash
# MOTD only
ansible-playbook ansible/deploy.yml --tags motd

# Docker Engine
ansible-playbook ansible/deploy.yml --tags docker

# Portainer Agent
ansible-playbook ansible/deploy.yml --tags portainer-agent

# GitLab Runner
ansible-playbook ansible/deploy.yml --tags gitlab-runner
```

### Verification

```bash
ssh dockhost-90
docker ps
docker compose -f /opt/portainer-agent/docker-compose.yml ps
docker compose -f /opt/gitlab-runner/docker-compose.yml ps
```

---

## Bastion

### Provisioning (Terraform)

```bash
cd bastion/terraform
terraform init
terraform plan
terraform apply
```

### Configuration (Ansible)

```bash
cd bastion
ansible-playbook ansible/deploy.yml
```

### By tag

```bash
# MOTD
ansible-playbook ansible/deploy.yml --tags motd

# Security hardening (SSH + UFW)
ansible-playbook ansible/deploy.yml --tags security-hardening

# Tooling (uv, Terraform, direnv, pass, git)
ansible-playbook ansible/deploy.yml --tags tooling

# SSH keys
ansible-playbook ansible/deploy.yml --tags ssh-keys

# GitLab Runner (shell executor)
ansible-playbook ansible/deploy.yml --tags gitlab-runner
```

---

## Kubecluster

### Provisioning (Terraform)

```bash
cd kubecluster/terraform
terraform init
terraform plan
terraform apply
```

### Configuration (Ansible)

```bash
cd kubecluster
ansible-playbook ansible/deploy.yml
```

### By tag

```bash
# Node system configuration
ansible-playbook ansible/deploy.yml --tags cfg_nodes

# containerd installation
ansible-playbook ansible/deploy.yml --tags cfg_containerd

# kubeadm initialization (control plane)
ansible-playbook ansible/deploy.yml --tags init_kubeadm

# Workers joining
ansible-playbook ansible/deploy.yml --tags join_workers

# kubectl cheat sheet
ansible-playbook ansible/deploy.yml --tags kubectl_cheat_sheet
```

### Verification

```bash
ssh kubecluster-40
kubectl get nodes
kubectl get pods -A
```

---

## Secrets (Ansible Vault)

### Encrypt a file

```bash
ansible-vault encrypt <file>
```

### Temporarily decrypt

```bash
ansible-vault decrypt <file>
# Don't forget to re-encrypt before committing!
ansible-vault encrypt <file>
```

### Edit an encrypted file

```bash
ansible-vault edit <file>
```

### View content without decrypting

```bash
ansible-vault view <file>
```

The vault password is automatically retrieved via `pass show ansible/vault` (script `scripts/ansible-vault-pass.sh`).

---

## Terraform

### Common commands

```bash
# Initialize the provider
terraform init

# Preview planned changes
terraform plan

# Apply changes
terraform apply

# Destroy infrastructure
terraform destroy

# Format code
terraform fmt -recursive

# Validate syntax
terraform validate
```

### Environment variables

Terraform credentials are exported via `direnv` from `.envrc`:

```bash
# Variables automatically available in the shell
TF_VAR_pm_api_url      # Proxmox API URL
TF_VAR_pm_api_token_id  # Token ID
TF_VAR_pm_api_token_secret  # Token secret
```

---

## Code quality

### Pre-commit (all hooks)

```bash
pre-commit run --all-files
```

### Ansible Lint

```bash
uv run ansible-lint proxmox/ansible/ bastion/ansible/ dockhost/ansible/ kubecluster/ansible/
```

### Terraform format + validation

```bash
terraform fmt -check -recursive
```

### Shellcheck

```bash
shellcheck -x -S warning scripts/*.sh
```

---

## SSH access

| Target | Command | User |
|-------|----------|------|
| Proxmox | `ssh pve` | ansible |
| Bastion | `ssh bastion-60` | ansible |
| Dockhost | `ssh dockhost-90` | ansible |
| K8s Control Plane | `ssh kubecluster-40` | ansible |
| K8s Worker 1 | `ssh kubecluster-41` | ansible |
| K8s Worker 2 | `ssh kubecluster-42` | ansible |

Configuration: `~/.ssh/config`
