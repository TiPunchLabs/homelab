# 🧭 Guide: Closing the hermes-30 cloud-init DNS drift

> **Objective**: make Terraform, Proxmox and the guest agree on hermes-30's
> cloud-init DNS **without** changing how the guest resolves names today.
>
> **Prerequisites**: LAN access to `pve` and `hermes-30`; vault password; the
> preconditions of Chapter 3 all green. Every step needs an explicit human
> go — nothing here is run by CI.
>
> **Duration**: ~20 min for stages 1 and 2, no reboot. Stage 3 (Terraform) is
> **blocked** until the memory divergence is resolved (§1.3).

## Table of contents

1. Mental Model
2. Chapter 1: The drift
3. Chapter 2: Historical evidence
4. Chapter 3: Preconditions
5. Chapter 4: Baseline
6. Chapter 5: Deploy
7. Chapter 6: Verify
8. Chapter 7: The next reboot
9. Rollback
10. Remaining risks
11. Resources

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
                           ├─ re-renders netplan with nameservers   ✗ → guard 1 (Ansible)
                           ├─ regenerates SSH host keys             ✗ → guard 2 (Ansible)
                           └─ apt dist-upgrade (package_upgrade)    ✗ → --ciupgrade 0 (Proxmox)
```

Three stages, strictly in this order, each one gated:

```
 Stage 1 — Ansible   lay the guards on the guest        this branch, independent of M2
 Stage 2 — Proxmox   qm set --nameserver --ciupgrade 0   only after stage 1 is verified
 Stage 3 — Terraform plan, then apply -refresh-only      BLOCKED until §1.3 is resolved
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
- that reboot happens **with a new instance-id** — every effect of Chapter 7 at
  once, in the middle of an apply;
- bpg ≥ 0.75 no longer manages `ciupgrade`, so Terraform alone could not even
  switch the boot-time upgrade off.

### 1.3 ⛔ Blocking condition: the memory divergence

| Where | `vm_memory_floating` |
|---|---|
| `main` (`bae2686`) and this branch | `2048` |
| `feat/hermes-cafe-ia` (`9ef229c`, not merged) | `3584` |
| Production (`qm config 9030`) | `balloon: 3584` |

This branch deliberately stays on `main` and is **not** rebased onto the M2
branch. Consequence: a plan from this branch shows a second, unrelated change
(`floating 3584 → 2048`) that bpg would apply **with a reboot**.

> ⛔ **No Terraform operation** — not even `plan` used as a go signal, and never
> `apply` — until `main` carries `vm_memory_floating = 3584`, i.e. until
> `9ef229c` is merged. Stages 1 and 2 do not depend on it.

Also note that the hermes Terraform state and `.terraform/` are local and
gitignored: they live in the **main checkout** (`homelab/hermes/terraform/`),
not in a worktree. Stage 3 runs there, on an up-to-date `main`.

------

## 📜 Chapter 2: Historical evidence

This fix does not invent a mechanism. It **codifies** a protection that has
been running by hand on two VMs for six months.

### 2.1 🗓️ The 2026-04-28 network migration

During the `192.168.1.x → 192.168.10.x` renumbering, the guests were edited in
place (netplan) instead of being re-provisioned. To stop cloud-init from
rewriting that netplan, the same file was laid manually on each VM:

- design: `docs/superpowers/specs/2026-04-28-network-migration-192-168-10-design.md:147`;
- plan: `docs/superpowers/plans/2026-04-28-network-migration-192-168-10.md:386, 418, 606, 669, 750`;
- generic procedure: `docs/guides/guide-vm-reconfig-via-qemu-agent.md:245, 315`.

Proxmox `ipconfig0` was **not** updated at the time — see Chapter 10.

### 2.2 🔍 Observed on 2026-10-16 (read-only)

| VM | `99-disable-network-config.cfg` | cloud-init at the last boot (2026-10-09) | SSH key guard |
|---|---|---|---|
| dockhost-90 | ✅ `network: {config: disabled}`, 28 bytes, 2026-04-28 | `network config is disabled by system_cfg` | ❌ |
| vpngate-50 | ✅ same file, same date | `network config is disabled by system_cfg` | ❌ |
| bastion-60 | ❓ VM stopped, not inspected | — | ❓ |
| hermes-30 | ❌ created 2026-08-20, after the migration | — | ❌ |

Two conclusions:

- the guard **works on this exact stack** (template 9001, PVE 9.1.1, NoCloud):
  it is not a theoretical setting;
- hermes-30 lacks it only because the guard lived in a runbook, not in code.
  Created after the migration, it never received it.

### 2.3 ✅ What this change adds

| | Before | After |
|---|---|---|
| Network guard | manual, 2 VMs, outside the repo | Ansible (`dns_resolver`), hermes-30 only, re-applied at each run |
| SSH host key guard | none anywhere | Ansible, hermes-30 only |
| Boot-time `dist-upgrade` | on for every VM | off for 9030 only (`--ciupgrade 0`) |

The YAML is written block-style (`network:\n  config: disabled`) instead of the
manual inline form; both parse to the same value. Generalizing to the other VMs
is a separate effort: [`docs/backlog/cloud-init-guards-and-network-drift.md`](../backlog/cloud-init-guards-and-network-drift.md).

------

## ✅ Chapter 3: Preconditions

All must be true before stage 1. Values recorded on 2026-10-16.

| # | Check | Command | Expected |
|---|---|---|---|
| P1 | Proxmox cloud-init inputs unchanged | `ssh pve 'sudo /usr/sbin/qm cloudinit pending 9030'` | only `cur` lines; `nameserver: 192.168.10.71 1.1.1.1` |
| P2 | `ciupgrade` not set (default 1) | `ssh pve 'sudo /usr/sbin/qm config 9030 \| grep ciupgrade'` | no output |
| P3 | Guest and Proxmox agree on the instance-id | `ssh hermes-30 'cat /run/cloud-init/.instance-id'` and `ssh pve 'sudo /usr/sbin/qm cloudinit dump 9030 meta'` | both `73c90b4ec3002c9cc64c363a2cc223584ad64f13` |
| P4 | No guard yet on the guest | `ssh hermes-30 'ls /etc/cloud/cloud.cfg.d/'` | `05_logging.cfg 90_dpkg.cfg 99-proxmox.cfg README` |
| P5 | Guest resolver in target state | `ssh hermes-30 'resolvectl dns eth0'` | `127.0.0.1` only |
| P6 | NIC MAC unchanged | `ssh pve 'sudo /usr/sbin/qm config 9030 \| grep ^net0'` | `virtio=BC:24:11:C4:2D:D7` |
| P7 | Branch is clean and local | `git status; git log origin/main..HEAD` | clean; only this fix's commits |
| P8 | Playbook parses, tasks in order | `cd hermes && ansible-playbook ansible/deploy.yml --syntax-check --list-tasks --tags dns` | the two guard tasks listed **before** `Strip the nameservers...` |
| P9 | Inventory and vault readable | `cd hermes && ansible-inventory --graph && ansible-inventory --host hermes-30 >/dev/null` | group `hermes` → `hermes-30` only; no decryption error |

> 💡 **Note**: `--tags dns` also runs the two timezone `pre_tasks` (tagged with
> every role). They are idempotent: `ok` expected, `America/Guadeloupe` already
> set. The M2 branch changes neither those tasks nor any `dns_*` variable, so
> running stage 1 from this branch does not roll back anything M2 deployed.

If any precondition differs, **stop**: the drift has moved since this audit.

------

## 📊 Chapter 4: Baseline (before any change)

```bash
# Host keys — reference values recorded on 2026-10-16
ssh hermes-30 'for k in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$k"; done'
#   SHA256:hRIeWXzjV9aW6d2qxtarcTnFUxZ1KYm0X8tUkEF5hcg (ECDSA)
#   SHA256:cctlNVjXKZ/eD2AUktIhQRPhKrKxfb+APbHvifUpV+U (ED25519)
#   SHA256:zV4Yh9o6mmFToFKPHJQfDiAD7lJmT/qcKBpnlLUx2nI (RSA)

# Network and resolver
ssh hermes-30 'sudo netplan get; stat -c "%y %n" /etc/netplan/*.yaml'
```

> ⚠️ **Warning**: every `ansible.cfg` sets `host_key_checking = False`, and
> `~/.ssh/known_hosts` has no entry for hermes-30. A changed host key would go
> unnoticed by Ansible: the fingerprints above are the only reference.

------

## 🛠️ Chapter 5: Deploy

### 5.1 📝 Stage 1 — lay the guards (Ansible)

```bash
cd hermes
ansible-playbook ansible/deploy.yml --tags dns --check --diff   # dry run
ansible-playbook ansible/deploy.yml --tags dns
```

Expected in both runs: exactly **two** `changed`, the new `cloud.cfg.d` files.
Everything else `ok`; no `netplan apply`; final assert green. Any other
`changed` → stop and investigate.

Check that cloud-init's own config loader sees the files, without rebooting:

```bash
ssh hermes-30 "sudo /usr/bin/python3 -c 'from cloudinit import util; \
  c = util.read_conf_with_confd(\"/etc/cloud/cloud.cfg\"); \
  print(c.get(\"network\"), c.get(\"ssh_deletekeys\"))'"
# expected: {'config': 'disabled'} False
```

> 💡 **Note**: `cloud-init query merged_system_cfg` is **not** a valid check
> here: instance-data is a snapshot written at boot, it will only show the new
> files after the next boot.

Go/no-go for stage 2: the check above prints the expected line **and** Chapter 6
passes (except the Terraform row).

### 5.2 📝 Stage 2 — align Proxmox (decision A: `--ciupgrade 0`)

Proxmox renders `package_upgrade: true` into user-data whenever `ciupgrade` is
unset or 1 (`/usr/share/perl5/PVE/QemuServer/Cloudinit.pm:162`). User-data
outranks `cloud.cfg.d`, so only Proxmox can switch it off. Setting both values
in **one** `qm set` changes the instance-id once, not twice.

```bash
ssh pve 'sudo /usr/sbin/qm set 9030 --nameserver 192.168.10.71 --ciupgrade 0'
ssh pve 'sudo /usr/sbin/qm cloudinit pending 9030'
ssh pve 'sudo /usr/sbin/qm config 9030 | grep -E "^(nameserver|ciupgrade|ipconfig0|net0|searchdomain)"'
```

Expected:

- `pending` shows the new `nameserver: 192.168.10.71` and `ciupgrade: 0`, and
  nothing else;
- `ipconfig0`, `net0` and `searchdomain` identical to the baseline;
- the VM keeps running. The cloud-init drive is regenerated at the next start;
  the guest is not affected before that.

> ⚠️ **Warning**: do not reboot hermes-30 to "test" this. The reboot is
> Chapter 7, at a planned moment.

### 5.3 ⛔ Stage 3 — Terraform (blocked)

Only once §1.3 is resolved (`main` has `vm_memory_floating = 3584`) **and** this
branch is merged. From the main checkout, on an up-to-date `main`:

```bash
cd hermes/terraform
terraform plan -lock=false
```

Expected: `No changes`. `ciupgrade` must not appear (bpg does not manage it).
Any planned change — memory, network device, anything — → stop, no apply.

Only then, persist the refreshed values into the local state (still dated
2026-08-20):

```bash
terraform apply -refresh-only    # review: state values only, no infrastructure action
```

------

## ✅ Chapter 6: Verify

After stage 1, and again after stage 2:

```bash
ssh hermes-30 '
  resolvectl dns                                   # Link eth0: 127.0.0.1 only
  grep "^DNS=" /run/systemd/network/10-netplan-eth0.network   # DNS=127.0.0.1
  getent hosts hermes.internal kandidat.internal   # internal, via resolved → dnsmasq
  getent hosts api.deepseek.com                    # public
  dig +short hermes.internal @127.0.0.1            # dnsmasq answers directly
  systemctl is-active dnsmasq systemd-resolved
  ls -l /etc/cloud/cloud.cfg.d/99-*.cfg
  for k in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$k"; done   # = Chapter 4
'
```

| Check | Expected |
|---|---|
| Link DNS | `127.0.0.1` only |
| Internal / public resolution | both answer |
| dnsmasq | `active` |
| Guard files | both present, `root:root 0644` |
| Host key fingerprints | identical to Chapter 4 |
| Running instance-id | still `73c90b4e...` (unchanged until the next boot) |
| `terraform plan` (stage 3 only) | `No changes` |

------

## 🔁 Chapter 7: The next reboot

Not part of this change. When hermes-30 is next rebooted for another reason,
the instance-id changes for real. Run Chapter 6 again, plus:

```bash
ssh hermes-30 'cat /run/cloud-init/.instance-id'     # new id (≠ 73c90b4e...)
ssh hermes-30 'stat -c %y /etc/netplan/50-cloud-init.yaml'   # unchanged (2026-08-23)
ssh hermes-30 'grep -c nameservers /etc/netplan/50-cloud-init.yaml'   # 0
ssh hermes-30 'sudo grep -iE "network config is disabled|Generating public/private|dist-upgrade" /var/log/cloud-init.log | tail'
#   expected: "network config is disabled by system_cfg"; no key generation; no dist-upgrade
```

------

## 🔙 Rollback

Undo in **reverse order**, only as far as needed.

| Stage undone | Command | Effect |
|---|---|---|
| 3 — state refresh | none needed | `-refresh-only` writes state values only; the previous state is kept as `terraform.tfstate.backup` |
| 2 — Proxmox | `ssh pve 'sudo /usr/sbin/qm set 9030 --nameserver "192.168.10.71 1.1.1.1" --delete ciupgrade'` | restores the exact previous config (`ciupgrade` absent, not `1`) |
| 1 — guard files | `ssh hermes-30 'sudo rm /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg /etc/cloud/cloud.cfg.d/99-preserve-ssh-host-keys.cfg'` | cloud-init owns network and keys again at the next new instance |
| Code | revert the commit **before** re-running `--tags dns` | otherwise the role lays the files again |

Verify a stage-2 rollback with P1–P3 of Chapter 3: same `pending`, same
instance-id `73c90b4e...` in `qm cloudinit dump 9030 meta`.

> ⚠️ **Warning**: restoring the old values restores the old instance-id only if
> **every** other cloud-init input is identical. If a reboot already happened with
> the new id, rolling back changes the id once more — and without the guards that
> means netplan rewritten, new host keys and a `dist-upgrade`. Keep the guard
> files in place until Proxmox is settled: roll back stage 2 before stage 1,
> never the reverse.

------

## ⚠️ Remaining risks

| Risk | Scope | Mitigation |
|---|---|---|
| NIC MAC change: with rendering disabled, netplan matches `bc:24:11:c4:2d:d7` only | hermes-30 | refuse any plan touching `network_device`; rebuild instead |
| Other per-instance modules (`users_groups`, `apt_configure`, `locale`, `set_passwords`, `mounts`) re-run at the next new instance | hermes-30 | same inputs, no change expected; proven only at Chapter 7 |
| Ansible blind to host key changes (`host_key_checking = False`) | all projects | manual fingerprint check (Chapter 4); backlog |
| Memory divergence `main` ↔ M2 | Terraform on hermes | stage 3 blocked (§1.3) |
| Stale `ipconfig0` (`192.168.1.x`) on 9050, 9060, 9090; no SSH key guard; boot-time upgrade still on | other VMs, **out of scope** | [backlog](../backlog/cloud-init-guards-and-network-drift.md) |

------

## 📚 Resources

- `hermes/ansible/roles/dns_resolver/README.md` — role and guard
- `hermes/tests/test_dns_resolver_cloud_init.py` — guard content, order, scope
- cloud-init docs: *First boot determination*, *Network configuration*
  (`network: {config: disabled}`), `cc_ssh` (`ssh_deletekeys`)
- PVE source: `PVE/QemuServer/Cloudinit.pm` — `package_upgrade` (line 162),
  `nocloud_gen_metadata` (line 579)

> **Document created on**: 2026-10-16
> **Author**: Xavier Gueret, with Claude Code
> **Version**: 1.1 — decision A, historical evidence, explicit preconditions, Terraform gate
