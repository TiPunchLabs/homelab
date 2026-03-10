# Commandes de reference

## Proxmox

### Deploiement complet

```bash
cd proxmox
ansible-playbook ansible/deploy.yml
```

### Par tag

```bash
# Hardening SSH du serveur Proxmox
ansible-playbook ansible/deploy.yml --tags "configure"

# Verification des tokens API
ansible-playbook ansible/deploy.yml --tags "manage"
```

---

## Dockhost

### Provisionnement (Terraform)

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

### Par tag

```bash
# MOTD uniquement
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
ssh dockhost-50
docker ps
docker compose -f /opt/portainer-agent/docker-compose.yml ps
docker compose -f /opt/gitlab-runner/docker-compose.yml ps
```

---

## Bastion

### Provisionnement (Terraform)

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

### Par tag

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

### Provisionnement (Terraform)

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

### Par tag

```bash
# Configuration systeme des noeuds
ansible-playbook ansible/deploy.yml --tags cfg_nodes

# Installation containerd
ansible-playbook ansible/deploy.yml --tags cfg_containerd

# Initialisation kubeadm (control plane)
ansible-playbook ansible/deploy.yml --tags init_kubeadm

# Jonction des workers
ansible-playbook ansible/deploy.yml --tags join_workers

# Cheat sheet kubectl
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

### Chiffrer un fichier

```bash
ansible-vault encrypt <fichier>
```

### Dechiffrer temporairement

```bash
ansible-vault decrypt <fichier>
# Ne pas oublier de re-chiffrer avant commit !
ansible-vault encrypt <fichier>
```

### Editer un fichier chiffre

```bash
ansible-vault edit <fichier>
```

### Voir le contenu sans dechiffrer

```bash
ansible-vault view <fichier>
```

Le mot de passe vault est recupere automatiquement via `pass show ansible/vault` (script `scripts/ansible-vault-pass.sh`).

---

## Terraform

### Commandes communes

```bash
# Initialiser le provider
terraform init

# Voir les changements prevus
terraform plan

# Appliquer les changements
terraform apply

# Detruire l'infrastructure
terraform destroy

# Formater le code
terraform fmt -recursive

# Valider la syntaxe
terraform validate
```

### Variables d'environnement

Les credentials Terraform sont exportes via `direnv` depuis `.envrc` :

```bash
# Variables automatiquement disponibles dans le shell
TF_VAR_pm_api_url      # URL API Proxmox
TF_VAR_pm_api_token_id  # Token ID
TF_VAR_pm_api_token_secret  # Token secret
```

---

## Qualite du code

### Pre-commit (tous les hooks)

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

## Acces SSH

| Cible | Commande | User |
|-------|----------|------|
| Proxmox | `ssh pve` | root |
| Bastion | `ssh bastion-60` | ansible |
| Dockhost | `ssh dockhost-50` | ansible |
| K8s Control Plane | `ssh kubecluster-40` | ansible |
| K8s Worker 1 | `ssh kubecluster-41` | ansible |
| K8s Worker 2 | `ssh kubecluster-42` | ansible |
| NAS Synology | `ssh nas` | xgueret |

Configuration : `~/.ssh/config`
