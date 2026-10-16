# 🧭 Guide: Closing the hermes-30 cloud-init DNS drift

> **Objective**: make Terraform, Proxmox and the guest agree on hermes-30's
> cloud-init DNS **without** changing how the guest resolves names today.
>
> **Prerequisites**: LAN access to `pve` and `hermes-30`; vault password; a branch
> that contains **both** this fix and the M2 ballooning change (`9ef229c`,
> `vm_memory_floating = 3584`) — see §1.3.
>
> **Duration**: ~20 min, no reboot required. The guard is only exercised at the
> next planned reboot (§5).

## Table of contents

1. Mental Model
2. Chapter 1: The drift
3. Chapter 2: Baseline
4. Chapter 3: Apply
5. Chapter 4: Verify
6. Chapter 5: The next reboot
7. Rollback
8. Remaining risks

------

## 🧠 Mental Model

```
 Terraform config ──── ["192.168.10.71"]                 (code, since aaa5a94)
 Terraform state  ──── ["192.168.10.71", "1.1.1.1"]  ┐
 Proxmox qm config ─── 192.168.10.71 1.1.1.1         ┘  never applied
 Guest (netplan) ───── 127.0.0.1 → dnsmasq             (dns_resolver role)

 qm set --nameserver ──► user/network-data change
                     ──► instance-id = sha1(user . network) changes
                     ──► next boot: cloud-init thinks "new instance"
                           ├─ re-renders netplan with nameservers   ✗ → guard 1
                           ├─ regenerates SSH host keys             ✗ → guard 2
                           └─ apt upgrade (package_upgrade: true)   ✗ → §3.2 decision
```

> **Analogy**: changing the cloud-init drive is like handing the VM a new birth
> certificate. Nothing happens while it is awake; at the next wake-up it believes
> it was just born, unless it has been told which birth rituals to skip.

------

## 🏗️ Chapter 1: The drift

### 1.1 🔍 What `terraform plan` shows

Audited 2026-10-16 (plan with `-lock=false`, bpg 0.96.0, PVE 9.1.1):

| Attribute | Value |
|---|---|
| `initialization[0].dns[0].servers` — config | `["192.168.10.71"]` |
| — state | `["192.168.10.71", "1.1.1.1"]` |
| — Proxmox `nameserver` | `192.168.10.71 1.1.1.1` |
| — guest effective DNS | `127.0.0.1` (dnsmasq) |

Single attribute, `1 to change`. Not a provider normalization: the code was changed
on 2026-08-23 and never applied, on purpose — the role fixed the guest instead.

### 1.2 ⚠️ Why `terraform apply` is not the fix

- bpg defaults to `reboot_after_update = true`: the apply would most likely reboot
  the VM;
- that reboot happens **with a new instance-id** — every effect of §5 at once,
  in the middle of an apply.

### 1.3 ⚠️ Branch and ballooning

`main` still carries `vm_memory_floating = 2048`; the M2 branch carries `3584`,
which matches production (`balloon: 3584`). A plan run from a branch **without**
`9ef229c` shows a second, unrelated change (`floating 3584 → 2048`) that bpg
would apply **with a reboot**. Only plan from a branch that has both changes, and
never apply from this one.

------

## 📊 Chapter 2: Baseline (before any change)

```bash
# Host keys — reference values recorded on 2026-10-16
ssh hermes-30 'for k in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$k"; done'
#   SHA256:hRIeWXzjV9aW6d2qxtarcTnFUxZ1KYm0X8tUkEF5hcg (ECDSA)
#   SHA256:cctlNVjXKZ/eD2AUktIhQRPhKrKxfb+APbHvifUpV+U (ED25519)
#   SHA256:zV4Yh9o6mmFToFKPHJQfDiAD7lJmT/qcKBpnlLUx2nI (RSA)

# Cloud-init identity — today guest and Proxmox agree
ssh hermes-30 'cat /run/cloud-init/.instance-id'      # 73c90b4e...
ssh pve 'sudo /usr/sbin/qm cloudinit dump 9030 meta'   # same id

# Network and resolver
ssh hermes-30 'sudo netplan get; resolvectl dns; ls /etc/cloud/cloud.cfg.d/'
```

------

## 🛠️ Chapter 3: Apply

### 3.1 📝 Lay the guard (Ansible)

```bash
cd hermes
ansible-playbook ansible/deploy.yml --tags dns --check --diff   # expect 2 new files only
ansible-playbook ansible/deploy.yml --tags dns
```

Expected: two `changed` on the new `cloud.cfg.d` files, **no** `netplan apply`
(both netplan files are already in their target state), final assert green.

Check that cloud-init's own config loader sees them, without rebooting:

```bash
ssh hermes-30 "sudo /usr/bin/python3 -c 'from cloudinit import util; \
  c = util.read_conf_with_confd(\"/etc/cloud/cloud.cfg\"); \
  print(c.get(\"network\"), c.get(\"ssh_deletekeys\"))'"
# expected: {'config': 'disabled'} False
```

> 💡 **Note**: `cloud-init query merged_system_cfg` is **not** a valid check
> here: instance-data is a snapshot written at boot, it will only show the new
> files after the next boot.

### 3.2 ⚠️ Decide on `package_upgrade` (open decision)

Proxmox user-data carries `package_upgrade: true` (`ciupgrade` defaults to 1).
User-data outranks `cloud.cfg.d`, so the role **cannot** neutralize it. At the
next reboot after §3.3, cloud-init would run an `apt upgrade` during boot
(Docker included). Choose one before §3.3:

| Option | Effect | Trade-off |
|---|---|---|
| A. `--ciupgrade 0` in the same `qm set` | user-data no longer asks for an upgrade | an extra Proxmox change; bpg ≥ 0.75 does not manage `upgrade`, so no new drift expected (check in §4) |
| B. `manual_cache_clean: true` in `cloud.cfg.d` | cloud-init never detects a new instance again: **no** per-instance module re-runs | broader; future cloud-init changes only reach the guest after `cloud-init clean` or a rebuild (already the de facto rule) |
| C. Accept it | one boot-time upgrade at the next reboot | uncontrolled upgrade window on a 24/7 agent |

### 3.3 📝 Align Proxmox

```bash
# Option A shown; drop --ciupgrade 0 for options B and C
ssh pve 'sudo /usr/sbin/qm set 9030 --nameserver 192.168.10.71 --ciupgrade 0'
ssh pve 'sudo /usr/sbin/qm cloudinit pending 9030'   # new nameserver shown, nothing else
```

No reboot: the cloud-init drive is regenerated at the next VM start.

### 3.4 🔍 Plan

```bash
cd hermes/terraform
terraform plan -lock=false
```

Expected: `No changes`. Then persist the refreshed values (balloon 3584 and the
DNS) into the local state, which still dates from 2026-08-20:

```bash
terraform apply -refresh-only    # review: only state values, no infrastructure action
```

------

## ✅ Chapter 4: Verify

```bash
ssh hermes-30 '
  resolvectl dns                                   # Link eth0: 127.0.0.1 only
  grep "^DNS=" /run/systemd/network/10-netplan-eth0.network   # DNS=127.0.0.1
  getent hosts hermes.internal kandidat.internal   # internal, via resolved → dnsmasq
  getent hosts api.deepseek.com                    # public
  dig +short hermes.internal @127.0.0.1            # dnsmasq answers directly
  systemctl is-active dnsmasq systemd-resolved
  ls -l /etc/cloud/cloud.cfg.d/99-*.cfg
  for k in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$k"; done   # = §2
'
ssh -o StrictHostKeyChecking=yes hermes-30 true    # no host key warning
```

| Check | Expected |
|---|---|
| Link DNS | `127.0.0.1` only |
| Internal / public resolution | both answer |
| dnsmasq | `active` |
| Host key fingerprints | identical to §2 |
| `terraform plan` | `No changes` |

------

## 🔁 Chapter 5: The next reboot

Not part of this change. When hermes-30 is next rebooted for another reason,
the instance-id changes for real. Run §4 again, plus:

```bash
ssh hermes-30 'cat /run/cloud-init/.instance-id'     # new id (≠ 73c90b4e...)
ssh hermes-30 'stat -c %y /etc/netplan/50-cloud-init.yaml'   # unchanged (2026-08-23)
ssh hermes-30 'grep -c nameservers /etc/netplan/50-cloud-init.yaml'   # 0
ssh hermes-30 'sudo grep -i "network config is disabled\|Generating public/private" /var/log/cloud-init.log | tail'
```

------

## 🔙 Rollback

| Step undone | Command |
|---|---|
| Proxmox alignment | `ssh pve 'sudo /usr/sbin/qm set 9030 --nameserver "192.168.10.71 1.1.1.1" --ciupgrade 1'` |
| Guard files | `ssh hermes-30 'sudo rm /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg /etc/cloud/cloud.cfg.d/99-preserve-ssh-host-keys.cfg'` |
| Code | revert the commit, then re-run `--tags dns` (it re-lays the files unless reverted) |

> ⚠️ **Warning**: restoring the old `nameserver` restores the old instance-id
> only if **every** other cloud-init input is identical. If a reboot already
> happened with the new id, rolling back changes the id once more — keep the
> guard files in place until Proxmox is settled.

------

## ⚠️ Remaining risks

- **NIC MAC change**: with network rendering disabled, netplan matches
  `bc:24:11:c4:2d:d7` only. A plan touching `network_device` must be refused.
- **`package_upgrade`** until §3.2 is decided.
- **Other per-instance modules** (`users_groups`, `apt_configure`, `locale`,
  `set_passwords`, `mounts`) re-run at the next new instance with the same inputs;
  no change expected, not proven until §5.
- **The other 8 machines** share the same mechanism but are out of scope.

------

## 📚 Resources

- `hermes/ansible/roles/dns_resolver/README.md` — role and guard
- cloud-init docs: *First boot determination* (`manual_cache_clean`), *Network
  configuration* (`network: {config: disabled}`), `cc_ssh` (`ssh_deletekeys`)
- PVE source: `PVE/QemuServer/Cloudinit.pm`, `nocloud_gen_metadata`

> **Document created on**: 2026-10-16
> **Author**: Xavier Gueret, with Claude Code
> **Version**: 1.0
