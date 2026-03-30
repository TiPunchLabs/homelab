# Proxmox LXC Container Provisioning

## Context

The homelab infrastructure uses a two-stage pattern (Terraform + Ansible) to provision and configure KVM virtual machines on Proxmox VE.
A reusable Terraform module `proxmox_vm_template` handles VM creation via the `bpg/proxmox` provider, cloning from a custom Ubuntu 24.04 cloud-init template (ID 9001).
Ansible then configures the VMs (services, hardening, tooling).

Currently, **no LXC container support exists** in the project.
The goal is to add LXC container provisioning following the same patterns, starting with a Caddy reverse proxy as the first use case.

------

## Goals

- Create a reusable Terraform module `proxmox_lxc_template` for LXC container provisioning
- Follow the same two-stage pattern: Terraform (provisioning) then Ansible (configuration)
- Ensure containers are accessible by the `ansible` user (SSH + sudo NOPASSWD)
- Use official LXC templates downloaded via Terraform (no custom template build)
- Deploy Caddy as the first project consuming the new module

------

## Non-Goals

- Replacing existing KVM VMs with LXC containers
- Building custom LXC templates (use official Ubuntu templates)
- Docker-in-LXC support (nesting enabled by default, but not a primary goal)

------

## Design

### 1. Reusable Terraform Module — `modules/proxmox_lxc_template/`

A new module mirroring `proxmox_vm_template`, adapted for LXC containers.

**Files:**

```text
modules/proxmox_lxc_template/
├── main.tf          # proxmox_virtual_environment_container + remote-exec provisioner
├── variables.tf     # Module inputs
└── outputs.tf       # ct_ips_output, ct_names, ct_ids
```

**Resource:** `proxmox_virtual_environment_container`

**Variables:**

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `project_description` | string | — | Project description |
| `ct_target_node` | string | `"proxmox"` | Proxmox node name |
| `ct_count` | number | `1` | Number of containers |
| `ct_name_prefix` | string | `"generic-ct"` | Name prefix |
| `ct_baseid` | number | — | Starting CTID |
| `ct_ip_start` | number | — | Last IP octet start |
| `ct_template_file_id` | string | — | LXC template (e.g. `local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst`) |
| `ct_os_type` | string | `"ubuntu"` | OS type for Proxmox |
| `ct_cpu_cores` | number | `1` | CPU cores |
| `ct_memory` | number | `512` | RAM in MiB |
| `ct_disk_size` | number | `8` | Rootfs size in GB |
| `ct_disk_storage` | string | `"local-lvm"` | Datastore for rootfs |
| `ct_ssh_keys` | list(string) | — | SSH public keys for root (copied to ansible user) |
| `ct_root_password` | string | — | Root password (from Vault) |
| `ct_unprivileged` | bool | `true` | Unprivileged container |
| `ct_nesting` | bool | `true` | Enable nesting feature |
| `ct_started` | bool | `true` | Start after creation |
| `ct_start_on_boot` | bool | `true` | Start on Proxmox boot |
| `ct_gateway` | string | `"192.168.1.1"` | Default gateway |
| `ct_netmask` | string | `"24"` | Subnet mask |
| `ct_dns_domain` | string | `"local"` | DNS domain |
| `ct_dns_servers` | list(string) | `["1.1.1.1", "8.8.8.8"]` | DNS servers |
| `ct_ssh_private_key_path` | string | — | Path to SSH private key for remote-exec provisioner |

**Key differences with `proxmox_vm_template`:**

- No `clone` block — uses `operating_system.template_file_id` directly
- No `qemu-guest-agent` — not applicable to LXC
- `initialization.user_account` configures root only (LXC limitation)
- `remote-exec` provisioner creates the `ansible` user post-creation
- `features.nesting` enabled by default
- Tags include `lxc` in addition to `terraform` and the name prefix
- `ct_root_password` is passed to `initialization.user_account.password` (marked `sensitive = true`)
- No `stop_on_destroy` equivalent — destroying a running container requires `terraform apply` with `ct_started = false` first, or Proxmox handles it gracefully

**Outputs:**

- `ct_ips_output` — computed IPs (same formula as VM module)
- `ct_names` — container names
- `ct_ids` — container IDs

### 2. Ansible User Bootstrap — `remote-exec` Provisioner

After container creation, a `remote-exec` provisioner connects as `root` (via SSH key) and prepares the `ansible` user:

```hcl
provisioner "remote-exec" {
  inline = [
    "useradd -m -s /bin/bash ansible",
    "echo 'ansible ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ansible",
    "chmod 440 /etc/sudoers.d/ansible",
    "mkdir -p /home/ansible/.ssh",
    "cp /root/.ssh/authorized_keys /home/ansible/.ssh/",
    "chown -R ansible:ansible /home/ansible/.ssh",
    "chmod 700 /home/ansible/.ssh && chmod 600 /home/ansible/.ssh/authorized_keys"
  ]

  connection {
    type     = "ssh"
    user     = "root"
    host     = "${join(".", slice(split(".", var.ct_gateway), 0, 3))}.${var.ct_ip_start + count.index}"
    private_key = file(var.ct_ssh_private_key_path)
  }
}
```

This ensures Ansible can connect as `ansible` immediately after `terraform apply`.

### 3. LXC Template Download — Terraform Resource

Each project that consumes the module downloads the official LXC template in its own `main.tf`:

```hcl
resource "proxmox_virtual_environment_download_file" "lxc_template" {
  content_type = "vztmpl"
  datastore_id = "local"
  node_name    = "proxmox"
  url          = "http://download.proxmox.com/images/system/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
}
```

The downloaded template ID is passed to the module as `ct_template_file_id`.

### 4. Network and ID Conventions

| Element | KVM VMs (existing) | LXC Containers (new) |
|---------|--------------------|----------------------|
| VMID/CTID range | 9000+ | 1000+ |
| IP range | 192.168.1.40-.69 | 192.168.1.70-.89 |
| Tags | `terraform`, `<prefix>` | `terraform`, `lxc`, `<prefix>` |
| Module | `proxmox_vm_template` | `proxmox_lxc_template` |

**ID convention:** CTID = 1000 + last IP octet (e.g., IP .70 → CTID 1070), mirroring the VM convention where VMID = 9000 + last IP octet.

**Provider version:** The module uses the same constraint as the VM module (`>= 0.93.0, < 1.0.0`). Consumer projects pin to `0.96.0` in their `providers.tf`. Both `proxmox_virtual_environment_container` and `proxmox_virtual_environment_download_file` are supported since early versions of the bpg provider.

### 5. First Consumer — Caddy Project

**Directory structure:**

```text
caddy/
├── ansible/
│   ├── deploy.yml
│   ├── inventory.yml
│   ├── group_vars/caddy/
│   │   └── main.yml
│   └── roles/
│       ├── motd/
│       └── caddy/
└── terraform/
    ├── main.tf
    ├── providers.tf
    ├── variables.tf
    └── outputs.tf
```

**Container specs:**

- Count: 1
- CTID: 1070
- IP: 192.168.1.70
- CPU: 1 core
- RAM: 512 MiB
- Disk: 8 GB on `local-lvm`
- Unprivileged: yes
- Nesting: yes
- Template: `ubuntu-24.04-standard` (downloaded via Terraform)

**Ansible playbook (`deploy.yml`):**

1. Role `motd` — message of the day
2. Role `security_hardening` — SSH hardening and UFW (consistent with other projects, especially important for a reverse proxy)
3. Role `caddy` — install and configure Caddy reverse proxy

**Terraform (`main.tf`):**

1. `proxmox_virtual_environment_download_file` — download Ubuntu 24.04 LXC template
2. Module `../../modules/proxmox_lxc_template` — create the container

------

## Provisioning Flow

```text
terraform apply
  │
  ├─ 1. Download ubuntu-24.04 LXC template
  │     (proxmox_virtual_environment_download_file)
  │
  ├─ 2. Create container CTID 1070, IP 192.168.1.70
  │     (proxmox_virtual_environment_container via module)
  │
  └─ 3. remote-exec provisioner (as root):
        → useradd ansible
        → sudo NOPASSWD
        → copy SSH authorized_keys

ansible-playbook -i inventory.yml deploy.yml
  │
  ├─ 1. Role: motd
  ├─ 2. Role: security_hardening
  └─ 3. Role: caddy
```

------

## Files to Create

| File | Purpose |
|------|---------|
| `modules/proxmox_lxc_template/main.tf` | Container resource + remote-exec provisioner |
| `modules/proxmox_lxc_template/variables.tf` | Module input variables |
| `modules/proxmox_lxc_template/outputs.tf` | Module outputs |
| `caddy/terraform/main.tf` | Template download + module call |
| `caddy/terraform/providers.tf` | Provider config (same as other projects) |
| `caddy/terraform/variables.tf` | Project-specific variables |
| `caddy/terraform/outputs.tf` | Project outputs |
| `caddy/ansible/deploy.yml` | Ansible playbook |
| `caddy/ansible/inventory.yml` | Ansible inventory |
| `caddy/ansible/group_vars/caddy/main.yml` | Caddy variables |
| `caddy/ansible/roles/motd/` | MOTD role (reuse or symlink) |
| `caddy/ansible/roles/security_hardening/` | SSH hardening + UFW (reuse from bastion) |
| `caddy/ansible/roles/caddy/` | Caddy installation role |

------

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| `remote-exec` fails if SSH not ready | Terraform's connection block has a built-in timeout (default 5 min); increase to `timeout = "2m"` if needed |
| IP collision between VMs and LXC | Non-overlapping ranges enforced: VMs .40-.69, LXC .70-.89 |
| Provider bug with LXC warnings (issue #2700) | Pin provider version, test with current setup |
| Unprivileged container limits | Nesting enabled; if specific use cases need privileged, override `ct_unprivileged = false` |
