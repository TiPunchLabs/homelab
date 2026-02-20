# 🚀 Automated Proxmox Deployment with Ansible & Terraform

![Stars](https://img.shields.io/github/stars/TiPunchLabs/homelab?style=social) ![Last Commit](https://img.shields.io/github/last-commit/TiPunchLabs/homelab) ![Status](https://img.shields.io/badge/Status-Active-brightgreen) ![Proxmox VE](https://img.shields.io/badge/Proxmox%20VE-9-orange?logo=proxmox&logoColor=white)

[toc]

## 📋 Description

This repository provides secure and automated configuration of a **Proxmox VE** server using **Ansible** and **Terraform**. It also manages GitHub repositories for configuration publishing.

## ✨ Features include:

- 🔐 SSH security hardening
- 👤 Proxmox roles, users, and token creation
- 🐧 Ubuntu Cloud-Init VM templates
- 🌐 GitHub repository provisioning with Terraform

## 📁 Project Structure

```bash
.
├── ansible
│   ├── ansible.cfg
│   ├── host_vars
│   │   └── pve
│   ├── inventory.yml
│   ├── playbook.yml
│   ├── roles
│   │   ├── configure
│   │   └── manage
│   └── SHA256SUMS
├── check_ansible_vault.sh
├── LICENSE
├── README.md
├── requirements.txt
└── terraform
    └── github
        ├── data_sources.tf
        ├── main.tf
        ├── outputs.tf
        ├── providers.tf
        ├── terraform.tfstate
        ├── terraform.tfvars
        └── variables.tf
```

## ✅ Requirements

- 🐍 Ansible
- 🌍 Terraform
- 🔐 SSH access to your Proxmox instance
- 🐙 GitHub access with a personal token

## 📦 Installing dependencies

```bash
pip install -r requirements.txt
pre-commit install
```

## 🔧 Environment Configuration

### Configure Environment Variables

Copy the example environment file and customize it:

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` and set your values:

- `SSH_USER`: SSH user for VM connections (default: ansible)
- `SSH_KEY_FILE`: Path to SSH public key (default: ~/.ssh/proxmox.pub)
- `PROXMOX_IP`: Your Proxmox server IP address
- `GEN_PASS`: Password for Proxmox users (store in Ansible Vault)
- `CLOUD_INIT_ROOT_PASSWD`: Root password for VM templates

⚠️ **Security Note:** Never commit `.env` to version control!

### 📚 Additional Documentation

- [Token Generation Workflow](docs/TOKEN_WORKFLOW.md) - Complete guide for Proxmox API tokens

## 🧩 1. Installing Proxmox on my Acer XC-605 PC

### 1.1. Download the Proxmox ISO

```bash
mkdir -p ~/Worspace/tmp/proxmox
cd ~/Worspace/tmp/proxmox
```

### 1.2. Download the archive and SHA256 file

```bash
wget https://enterprise.proxmox.com/iso/proxmox-ve_9.0-1.iso
wget https://enterprise.proxmox.com/iso/SHA256SUMS
```

### 1.3. Verify the SHA-256 hash

```bash
cat SHA256SUMS | grep proxmox-ve_9.0-1.iso | sha256sum -c
# Output:
# proxmox-ve_9.0-1.iso: OK
```

## 💽 2. Install Proxmox with Ventoy

📝 See [Ventoy official site](https://www.ventoy.net/en/index.html) or [Ubuntu-fr doc](https://doc.ubuntu-fr.org/ventoy)

If you have a USB drive with Ventoy, simply copy the ISO:

```bash
cp ~/Workspace/tmp/proxmox/proxmox-ve_9.0-1.iso /media/$USER/Ventoy
```

### 2.1. BIOS/UEFI Settings

> ℹ️ At startup, press the `Delete` key to access the BIOS menu

- ❌ **Disable Secure Boot**
- ✅ Enable **VT-x/Virtualization**

👉 Use the USB drive with Ventoy on your Acer XC-605 to boot and install Proxmox

> ⌨️ At startup, press **F12** to access the boot menu

### 2.2. Troubleshooting Installation

💡 If you encounter an issue during Proxmox 9 installation (see [Proxmox forum thread](https://forum.proxmox.com/threads/proxmox-ve-8-2-install-failing.153913/)):

➡️ At the installation menu, press `e` to edit boot options.
➡️ At the line starting with `linux`, append:

```bash
nomodeset
```

press **`F10`**

Then proceed with installation 🎉

## 🔑 3. SSH Configuration on my Linux workstation

### 3.1. Generate a key pair

```bash
ssh-keygen -t rsa -b 4096 -f ~/.ssh/proxmox -C "root@x.x.x.x"
```

> ℹ️ Include a passphrase if necessary
> 📁 Check keys:

```bash
ls -al ~/.ssh
```

### 3.2. Copy the key to Proxmox

```bash
ssh-copy-id -i ~/.ssh/proxmox.pub root@x.x.x.x
```

### 3.3. Activate ssh-agent (optional)

```bash
eval $(ssh-agent)
ssh-add ~/.ssh/proxmox
ssh root@x.x.x.x
```

### 3.4. Get the repository

```bash
cd ~/Workspace/
git clone <REPO_URL>
cd proxmox
cd ansible
```

> Make sure Python venv is activated and Ansible is installed

## 🚀 4. Usage

### 4.1. Configure Inventory

Edit the file:

```bash
ansible/inventory.yml
```

Add your Proxmox host.

### 4.2. Vaulted Secrets

Passwords and IPs are encrypted in:

```bash
ansible/host_vars/<host>/vault/main.yml
```

> (i) check all with pre-commit
>
> ```+-
> pre-commit run --all-files
> ```

### 4.3 Run the playbook with the following tag to configure the ansible user on the target server

```bash
ansible-playbook -u root playbook.yml --tags "security_ssh_hardening"
```

### 4.4 Then run the playbook without the `-u root` parameter

```
ansible-playbook playbook.yml
```

## 📚 **Enjoy your automated Proxmox setup!** 😎

---

## 👥 Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a [Pull Request](https://github.com/TiPunchLabs/homelab/pulls).

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
