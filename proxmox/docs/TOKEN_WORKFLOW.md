# Proxmox Token Generation Workflow

## Overview

This document describes the workflow for creating and managing Proxmox roles, users, and API tokens using Ansible automation.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Ansible Control Node                                    │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ roles/configure/tasks/                            │  │
│  │   setup_roles_users_tokens.yml                    │  │
│  └────────────────┬──────────────────────────────────┘  │
│                   │                                      │
│                   ├─ Copy: token_setup.json             │
│                   ├─ Copy: setup_roles_users_tokens.sh  │
│                   └─ Execute: script on Proxmox         │
└─────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│ Proxmox VE Server                                        │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ /tmp/setup_roles_users_tokens.sh                  │  │
│  │  └─ Reads: /tmp/token_setup.json                  │  │
│  │  └─ Uses: GEN_PASS env variable                   │  │
│  └────────────────┬──────────────────────────────────┘  │
│                   │                                      │
│                   │ For each token in JSON:              │
│                   ├─ 1. Create Role (pveum role add)    │
│                   ├─ 2. Create User (pveum user add)    │
│                   ├─ 3. Assign Role (pveum aclmod)      │
│                   └─ 4. Generate Token (pveum token add)│
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Output: /root/.{token_name}_token                 │  │
│  │  - terraform token → /root/.terraform_token       │  │
│  │  - ansible token → /root/.ansible_token           │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Configuration Files

### 1. Token Setup Configuration (`token_setup.json`)

Location: `ansible/roles/configure/files/token_setup.json`

This JSON file defines all tokens to be created:

```json
{
  "token_setup": [
    {
      "name": "terraform",
      "ugid": "terraform-prov@pve",
      "role": "TerraformProv",
      "comment": "Terraform token",
      "expire": 0,
      "privsep": 0,
      "privileges": [...]
    }
  ]
}
```

**Fields:**
- `name`: Token identifier (used for file naming)
- `ugid`: Proxmox user ID format: `username@realm`
- `role`: Role name to create/assign
- `comment`: Token description
- `expire`: Expiration timestamp (0 = never expires)
- `privsep`: Privilege separation (0 = inherit all user privileges)
- `privileges`: Array of Proxmox privileges

### 2. Ansible Task (`setup_roles_users_tokens.yml`)

Location: `ansible/roles/configure/tasks/setup_roles_users_tokens.yml`

This task orchestrates the token generation:

1. Copies `token_setup.json` to `/tmp/` on Proxmox
2. Copies `setup_roles_users_tokens.sh` to `/tmp/` with execute permissions
3. Executes the script with `GEN_PASS` environment variable

## Workflow Steps

### Step 1: Role Creation

```bash
pveum role add <ROLE> -privs "<PRIVILEGES>"
```

**Example:**
```bash
pveum role add TerraformProv -privs "Datastore.AllocateSpace Datastore.Audit ..."
```

**Idempotency:** Script checks if role exists before creation

### Step 2: User Creation

```bash
pveum user add <UGID> --password "<GEN_PASS>"
```

**Example:**
```bash
pveum user add terraform-prov@pve --password "secure_password"
```

**Idempotency:** Script checks if user exists before creation

### Step 3: Role Assignment

```bash
pveum aclmod / -user <UGID> -role <ROLE>
```

**Example:**
```bash
pveum aclmod / -user terraform-prov@pve -role TerraformProv
```

Assigns role to user at root path (`/`) for full access.

**Idempotency:** Script checks if ACL already exists

### Step 4: Token Generation

```bash
pveum user token add <UGID> <TOKEN_NAME> \
  -expire <EXPIRE> \
  -privsep <PRIVSEP> \
  -comment "<COMMENT>" \
  -o json > /root/.<TOKEN_NAME>_token
```

**Example:**
```bash
pveum user token add terraform-prov@pve terraform \
  -expire 0 \
  -privsep 0 \
  -comment "Terraform token" \
  -o json > /root/.terraform_token
```

**Output format:**
```json
{
  "full-tokenid": "terraform-prov@pve!terraform",
  "info": {
    "comment": "Terraform token",
    "expire": 0,
    "privsep": 0
  },
  "value": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

**Idempotency:** Script checks if token exists before creation

## Usage

### Running the Playbook

```bash
# Run full configuration including token setup
ansible-playbook deploy.yml --tags "setup_roles_users_tokens"

# Run all configuration tasks
ansible-playbook deploy.yml
```

### Viewing Generated Tokens

Use the `manage` role to display tokens:

```bash
ansible-playbook deploy.yml --tags "display_token"
```

This reads tokens from:
- `/root/.terraform_token`
- `/root/.ansible_token`

### Adding a New Token

1. Edit `token_setup.json`:

```json
{
  "token_setup": [
    {
      "name": "myapp",
      "ugid": "myapp-user@pve",
      "role": "MyAppRole",
      "comment": "My Application Token",
      "expire": 0,
      "privsep": 0,
      "privileges": [
        "VM.Allocate",
        "VM.Audit"
      ]
    }
  ]
}
```

2. Add token name to `manage/vars/main.yml`:

```yaml
manage_tokens:
  - terraform
  - ansible
  - myapp  # New token
```

3. Run playbook:

```bash
ansible-playbook deploy.yml --tags "setup_roles_users_tokens"
```

## Security Considerations

### 🔴 Current Limitations

1. **Tokens stored in plaintext**
   - Location: `/root/.{token_name}_token`
   - Risk: Accessible to anyone with root access
   - **Recommendation:** Implement secrets management (Vault, Bitwarden CLI)

2. **Password in environment variable**
   - `GEN_PASS` passed via environment
   - **Recommendation:** Use Ansible Vault for all passwords

3. **Root path permissions**
   - All tokens get ACL on `/` (root path)
   - **Recommendation:** Scope permissions to specific resources when possible

### ✅ Security Best Practices

1. **Use Ansible Vault for passwords:**

```bash
# Encrypt the vault file
ansible-vault encrypt host_vars/pve/vault/main.yml

# Add vault password to secure location
echo "your_vault_password" > ~/.vault/.vault_password
chmod 600 ~/.vault/.vault_password
```

2. **Set token expiration when appropriate:**

```json
{
  "expire": 1735689600  # Unix timestamp
}
```

3. **Enable privilege separation for restricted tokens:**

```json
{
  "privsep": 1  # Token has own privileges, not user's
}
```

4. **Use minimal required privileges:**

```json
{
  "privileges": [
    "VM.Audit"  # Read-only access example
  ]
}
```

## Proxmox Privileges Reference

Common privileges used in this project:

| Privilege | Description |
|-----------|-------------|
| `Datastore.AllocateSpace` | Allocate storage space |
| `VM.Allocate` | Create/remove VMs |
| `VM.Audit` | View VM status and configuration |
| `VM.Clone` | Clone VMs |
| `VM.Config.*` | Configure VM hardware (CPU, Memory, Disk, etc.) |
| `VM.PowerMgmt` | Start/stop/reset VMs |
| `VM.Migrate` | Migrate VMs between nodes |
| `Pool.Allocate` | Create/manage resource pools |
| `Sys.Audit` | View system status |
| `Sys.Modify` | Modify system configuration |
| `SDN.Use` | Use software-defined networking |

Full reference: https://pve.proxmox.com/pve-docs/pveum.1.html

## Troubleshooting

### Token not created

**Check script output:**
```bash
ansible-playbook deploy.yml --tags "setup_roles_users_tokens" -vvv
```

**Verify token exists on Proxmox:**
```bash
ssh root@proxmox "pveum user token list terraform-prov@pve"
```

### Permission denied errors

**Check role privileges:**
```bash
pveum role list -o json | jq '.[] | select(.roleid=="TerraformProv")'
```

**Check ACL assignments:**
```bash
pveum acl list | grep terraform-prov
```

### Token file not found

**Verify file exists:**
```bash
ssh root@proxmox "ls -la /root/.terraform_token"
```

**Regenerate token:**
```bash
ssh root@proxmox "rm /root/.terraform_token"
ansible-playbook deploy.yml --tags "setup_roles_users_tokens"
```

## Future Improvements

1. **Secrets Management Integration**
   - Integrate with HashiCorp Vault
   - Use Bitwarden CLI for token storage
   - Implement age/sops encryption

2. **Enhanced Idempotency**
   - Use native Ansible modules instead of shell scripts
   - Proper `changed_when` conditions
   - Fact gathering for existing tokens

3. **Token Rotation**
   - Automated token expiration and renewal
   - Notification before token expiry
   - Graceful token rotation workflow

4. **Audit Logging**
   - Log all token access
   - Track token usage metrics
   - Alert on suspicious activity

## References

- [Proxmox User Management](https://pve.proxmox.com/wiki/User_Management)
- [Proxmox API Tokens](https://pve.proxmox.com/wiki/Proxmox_VE_API#API_Tokens)
- [pveum Command Reference](https://pve.proxmox.com/pve-docs/pveum.1.html)
