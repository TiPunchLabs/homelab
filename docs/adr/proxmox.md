# 🏗️ ADR — Proxmox (Hypervisor)

> **Living document** — This file gathers the Architecture Decision Records (ADR) for the proxmox sub-project.
> Each decision is numbered, dated, and immutable once accepted. To revisit a decision, create a new one that supersedes it.

------

## 📖 Table of contents

- [ADR-001 : SSH bootstrap with a dedicated ansible user](#adr-001--ssh-bootstrap-with-a-dedicated-ansible-user)
- [ADR-002 : No-subscription repos and apt management](#adr-002--no-subscription-repos-and-apt-management)
- [ADR-003 : API tokens stored in pass](#adr-003--api-tokens-stored-in-pass)
- [ADR-004 : Dynamic cloud image checksum](#adr-004--dynamic-cloud-image-checksum)

------

## ADR-001 : SSH bootstrap with a dedicated ansible user

| | |
|---|---|
| **Date** | 2026-03-10 |
| **Status** | Accepted |
| **Decision makers** | xgueret |

### Context

The Proxmox VE server requires an initial bootstrap to configure SSH access. Two possible approaches:

1. Use root permanently for Ansible.
2. Create a dedicated `ansible` user with sudo NOPASSWD, then disable root SSH access.

### Decision

**Create a dedicated `ansible` user, deploy its SSH key, then disable password auth and direct root access.**

### Justification

| Criterion | Dedicated user (chosen) | Permanent root |
|---------|---------------------|----------------|
| Security | Root inaccessible via SSH | Maximum attack surface |
| Auditability | Actions traced under the `ansible` user | Everything is root, no traceability |
| Consistency | Same pattern as bastion, dockhost, kubecluster | Exception for Proxmox |
| Sudo | NOPASSWD via `wheel` group | Not needed |

```
Bootstrap (one time only):
  workstation ──[root + password]──► proxmox
                                      │
                                      ├── creates ansible user
                                      ├── deploys SSH key
                                      └── disables password auth

After bootstrap:
  workstation ──[ansible + SSH key]──► proxmox (sudo -i for root)
```

### Consequences

- The bootstrap requires a special command: `ansible-playbook -u root --ask-pass --tags security_ssh_hardening`
- `ansible.cfg` configures `private_key_file = ~/.ssh/proxmox` and `IdentitiesOnly=yes` to avoid conflicts with the SSH agent
- Root SSH access is disabled after bootstrap — use `ssh ansible@pve` then `sudo -i`
- The Proxmox console (Web UI or IPMI) remains available in case of lockout

------

## ADR-002 : No-subscription repos and apt management

| | |
|---|---|
| **Date** | 2026-03-10 |
| **Status** | Accepted |
| **Decision makers** | xgueret |

### Context

Proxmox VE 9 enables the `enterprise.proxmox.com` repos (PVE + Ceph) by default, which require a paid license. Without a license, `apt update` fails with `401 Unauthorized`, blocking any package installation.

PVE 9 uses the deb822 format (`.sources`), not the legacy `.list` format.

### Decision

**Remove the enterprise repos and replace them with the no-subscription repos, in deb822 format.**

### Justification

| Criterion | No-subscription (chosen) | Enterprise |
|---------|--------------------------|------------|
| Cost | Free | Paid license |
| Stability | Tested updates, suitable for homelab | Enterprise production |
| Functionality | Identical (same packages) | Identical |
| Risk | Less validated updates | Official Proxmox support |

### Consequences

- Ansible removes `pve-enterprise.sources` and `ceph.sources` at bootstrap
- Ansible creates `pve-no-subscription.sources` and `ceph-no-subscription.sources`
- The apt cache uses `cache_valid_time: 3600` to avoid unnecessary refreshes
- If a Proxmox license is purchased, create a replacement ADR to restore the enterprise repos

------

## ADR-003 : API tokens stored in pass

| | |
|---|---|
| **Date** | 2026-03-10 |
| **Status** | Accepted |
| **Decision makers** | xgueret |

### Context

The playbook creates Proxmox API tokens (terraform, ansible) via `pveum user token add`. Initially, the secrets were written to files on the server (`/root/.terraform_token`, `/root/.ansible_token`).

Problems:
- Secrets in plain text on the server
- No tracked rotation/revocation
- Lost if the server is reinstalled

### Decision

**Capture the secrets from stdout, store them in `pass` locally, and write nothing on the server.**

### Justification

```
BEFORE:
  pveum token add ──► /root/.terraform_token (file on server)

AFTER:
  pveum token add ──► stdout ──► register Ansible
                                      │
                                      ▼
                               delegate_to: localhost
                                      │
                                      ▼
                               pass insert proxmox/terraform-token-secret
```

| Criterion | pass (chosen) | Server file (former) |
|---------|---------------|--------------------------|
| Security | GPG encrypted, on workstation | Plain text on the server |
| Backup | Included in the password store backup | Lost if server is reinstalled |
| Access | `pass show proxmox/terraform-token-secret` | SSH root + cat file |
| Consistency | Same pattern as all other project secrets | Exception |

### Consequences

- `pass` naming convention: `proxmox/{name}-token-id` and `proxmox/{name}-token-secret`
- The old `/root/.*_token` files are removed by the cleanup task
- `no_log: true` on the Ansible task to avoid logging secrets
- If the token is lost in `pass`, it must be recreated on Proxmox (`pveum user token remove` then rerun the playbook)

------

## ADR-004 : Dynamic cloud image checksum

| | |
|---|---|
| **Date** | 2026-03-10 |
| **Status** | Accepted |
| **Decision makers** | xgueret |

### Context

The VM template is created from an Ubuntu cloud image (`ubuntu-24.04-server-cloudimg-amd64.img`). The SHA256 checksum was hardcoded in Ansible variables. Ubuntu periodically updates its images at the same URL, invalidating the stored hash.

### Decision

**Use the remote `SHA256SUMS` file URL as checksum reference, instead of a hardcoded hash.**

### Justification

| Criterion | SHA256SUMS URL (chosen) | Hardcoded hash (former) |
|---------|-------------------------|------------------------|
| Maintenance | None — always up to date | Manual update at each Ubuntu release |
| Security | Automatic verification against the official Ubuntu file | Potentially outdated hash |
| Reliability | Clear failure if the SHA256SUMS file is unavailable | Failure on mismatch without explanation |

```yaml
# BEFORE
url_checksum: sha256:02dc186dc491514254df58df29a5877c93ca90ac790cc91a164ea90ed3a0bb05

# AFTER
url_checksum: sha256:https://cloud-images.ubuntu.com/releases/noble/release/SHA256SUMS
```

### Consequences

- The local `SHA256SUMS` file in the repo has been removed (unnecessary)
- `get_url` downloads the remote `SHA256SUMS` on each execution and verifies automatically
- If Ubuntu changes the format or URL of the `SHA256SUMS` file, the task will fail (low probability)
- Requires internet access from the Proxmox server at deployment time

------

<!-- Template for future ADRs:

## ADR-XXX : Decision title

| | |
|---|---|
| **Date** | YYYY-MM-DD |
| **Status** | Proposed / Accepted / Superseded by ADR-YYY |
| **Decision makers** | xgueret |

### Context

What problem or question arises?

### Decision

Which option was chosen?

### Justification

Why this option over another? (comparison table, diagram, arguments)

### Consequences

What are the effects of this decision? (positive, negative, points of attention)

-->
