# 🚀 Proxmox — Configuration & Hardening

![Proxmox VE](https://img.shields.io/badge/Proxmox%20VE-9-orange?logo=proxmox&logoColor=white) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

> **Sous-projet du monorepo [homelab](https://github.com/TiPunchLabs/homelab)**
>
> Configuration et hardening du serveur Proxmox VE via **Ansible**.

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

## ✅ Prerequis

- Ansible (installe via `uv` depuis la racine du monorepo)
- Acces SSH au serveur Proxmox
- `pass` configure pour les secrets (vault password via `scripts/ansible-vault-pass.sh`)

## 🚀 Utilisation

### Lancer le playbook complet

```bash
cd proxmox
ansible-playbook ansible/deploy.yml
```

### Bootstrap initial (premiere execution)

Avant le deploiement de la cle SSH, l'agent SSH local propose trop de cles et le serveur refuse la connexion. Il faut forcer l'authentification par mot de passe :

```bash
ansible-playbook ansible/deploy.yml -u root --ask-pass --tags "security_ssh_hardening" \
  -e 'ansible_ssh_extra_args="-o PreferredAuthentications=password -o IdentitiesOnly=yes"'
```

Une fois le hardening SSH et la cle deployee, la configuration normale (`ansible.cfg`) reprend le dessus.

### Lancer par tags

```bash
# Packages essentiels (apt sources + packages de base)
ansible-playbook ansible/deploy.yml --tags "essentials"

# Hardening SSH
ansible-playbook ansible/deploy.yml --tags "security_ssh_hardening"

# Configuration roles/utilisateurs/tokens API
ansible-playbook ansible/deploy.yml --tags "setup_roles_users_tokens"

# Configuration stockage
ansible-playbook ansible/deploy.yml --tags "setup_storage"

# Generation template VM
ansible-playbook ansible/deploy.yml --tags "generate_vm_template"

# Afficher les tokens API existants
ansible-playbook ansible/deploy.yml --tags "display_token"
```

## 🔐 Secrets

Les secrets sont chiffres avec Ansible Vault dans `ansible/host_vars/pve/vault/`. Le mot de passe vault est fourni via `pass show ansible/vault`.

## 📚 Documentation

- [Token Workflow](docs/TOKEN_WORKFLOW.md) — Guide complet pour les tokens API Proxmox
- [Storage Setup](ansible/STORAGE_SETUP.md) — Configuration du stockage

## 👥 Auteur

- **Xavier GUERET** — [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)
