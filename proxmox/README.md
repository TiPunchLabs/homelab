# 🚀 Proxmox — Configuration & Hardening

![Proxmox VE](https://img.shields.io/badge/Proxmox%20VE-9-orange?logo=proxmox&logoColor=white) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

> **Sous-projet du monorepo [homelab](https://github.com/TiPunchLabs/homelab)**
>
> Configuration et hardening du serveur Proxmox VE via **Ansible** (configuration serveur) et **Terraform** (gestion du repository GitHub).

## 📁 Structure

```bash
proxmox/
├── ansible/
│   ├── inventory.yml
│   ├── deploy.yml               # Tags: security_ssh_hardening, setup_roles_users_tokens,
│   │                               #        setup_storage, generate_vm_template
│   ├── requirements.yml
│   ├── STORAGE_SETUP.md
│   ├── host_vars/pve/vault/       # Secrets chiffres Ansible Vault
│   └── roles/
│       ├── configure/             # SSH, tokens, storage, VM templates
│       └── manage/                # Verification tokens
├── terraform/
│   ├── main.tf
│   ├── providers.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── docs/
│   └── TOKEN_WORKFLOW.md          # Guide generation tokens Proxmox API
├── ansible.cfg
└── .env.example
```

## ✨ Fonctionnalites

- 🔐 Hardening SSH du serveur Proxmox
- 👤 Creation roles, utilisateurs et tokens API Proxmox
- 💾 Configuration du stockage (disques, LVM)
- 🐧 Generation de templates VM Ubuntu Cloud-Init
- 🌐 Gestion du repository GitHub via Terraform

## ✅ Prerequis

- Ansible (installe via `uv` depuis la racine du monorepo)
- Terraform >= 1.11.0
- Acces SSH au serveur Proxmox
- `pass` configure pour les secrets (vault password via `scripts/ansible-vault-pass.sh`)

## 🚀 Utilisation

### Lancer le playbook complet

```bash
cd proxmox
ansible-playbook ansible/deploy.yml
```

### Lancer par tags

```bash
# Hardening SSH (premiere execution avec -u root)
ansible-playbook ansible/deploy.yml -u root --tags "security_ssh_hardening"

# Configuration roles/utilisateurs/tokens
ansible-playbook ansible/deploy.yml --tags "setup_roles_users_tokens"

# Configuration stockage
ansible-playbook ansible/deploy.yml --tags "setup_storage"

# Generation template VM
ansible-playbook ansible/deploy.yml --tags "generate_vm_template"
```

### Terraform (gestion GitHub)

```bash
cd proxmox/terraform
cp terraform.tfvars.example terraform.tfvars
# Editer terraform.tfvars avec vos valeurs
terraform init
terraform plan
terraform apply
```

## 🔐 Secrets

Les secrets sont chiffres avec Ansible Vault dans `ansible/host_vars/pve/vault/`. Le mot de passe vault est fourni via `pass show ansible/vault`.

## 📚 Documentation

- [Token Workflow](docs/TOKEN_WORKFLOW.md) — Guide complet pour les tokens API Proxmox
- [Storage Setup](ansible/STORAGE_SETUP.md) — Configuration du stockage

## 👥 Auteur

- **Xavier GUERET** — [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)
