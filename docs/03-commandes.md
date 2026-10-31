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

# GitLab Runner
ansible-playbook ansible/deploy.yml --tags gitlab-runner
```

### Verification

```bash
ssh dockhost-90
docker ps
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

`.envrc` (direnv) exports non-sensitive configuration only (`PROXMOX_IP`, `TF_VAR_pm_api_url`,
`TF_VAR_github_owner`, `TF_VAR_gitlab_namespace_path`, `TF_HTTP_USERNAME`).

Credentials are never exported into the shell. Run credentialed commands through
`scripts/with-secrets`, from an owner terminal:

```bash
scripts/with-secrets <profile>[,<profile>...] -- <command> [args...]

# Profiles -> Terraform directories
#   proxmox   bastion, dockhost, hermes/terraform-31, kubecluster, vpngate
#   lxc       caddy, pihole (proxmox + LXC root password)
#   gitlab    gitlab-terraform
#   github    TF_VAR_github_token (github-terraform has no Terraform source in this checkout)
#   ovh       ovh-dns-terraform
#   tfstate   GitLab HTTP state backend, e.g. proxmox,tfstate (reuses gitlab/terraform-token;
#             needs TF_HTTP_USERNAME from .envrc; backend declared on the dockhost tfstate branch)
#   vault     ANSIBLE_VAULT_PASSWORD (rarely needed, see below)

cd dockhost/terraform
../../scripts/with-secrets proxmox -- terraform plan
```

Ansible Vault needs no profile: `scripts/ansible-vault-pass.sh` falls back to `pass ansible/vault`.
Playbooks that read `TF_VAR_pm_api_*` (e.g. hermes `m2-preflight.yml`) run under the `proxmox` profile.
Use a path to the script that matches your working directory. Keep `$VAR` references inside
`sh -c '...'` so they expand in the child, not in the calling shell.

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
