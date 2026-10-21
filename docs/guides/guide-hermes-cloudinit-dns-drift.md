# 🧭 Guide: Closing the hermes-30 cloud-init DNS drift

> **Objective**: make Terraform, Proxmox and the guest agree on hermes-30's
> cloud-init DNS **without** changing how the guest resolves names today.
>
> **Prerequisites**: LAN access to `pve` and `hermes-30`; vault password; the
> preconditions of Chapter 3 all green. Every step needs an explicit human
> go — nothing here is run by CI.
>
> **Duration**: ~20 min for stages 1 and 2, no reboot. Stage 3 (Terraform) runs
> once this branch is merged (§5.3).

> **Status on 2026-10-20 — ✅ CLOSED**:
>
> | Stage | State |
> |---|---|
> | 1 — Ansible guards | ✅ executed and verified on hermes-30 (2026-10-19) |
> | 2 — Proxmox `qm set` | ✅ executed and verified; Proxmox instance-id now `75b6756e...` (2026-10-19) |
> | 3 — Terraform | ✅ state reconciled by `apply` of a reviewed `-refresh-only` plan (serial 4 → 5, 2026-10-19) |
> | Chapter 7 — reboot | ✅ `qm reboot 9030` on 2026-10-20 12:05 AST — all checks PASS, Telegram confirmed by the user |
>
> Follow-ups (not part of this fix): deferred deletion of snapshot `pre-ch7`
> (§7.4), the `degraded done` deprecation notice (§7.3), Renovate MR !60, and
> the absence of any backup of hermes-30.

## Table of contents

1. Mental Model
2. Chapter 1: The drift
3. Chapter 2: Historical evidence
4. Chapter 3: Preconditions
5. Chapter 4: Baseline
6. Chapter 5: Deploy
7. Chapter 6: Verify
8. Chapter 7: The reboot with the new instance-id
9. Rollback
10. Remaining risks
11. Resources

------

## 🧠 Mental Model

```
 Terraform config ──── ["192.168.10.71"]                 (code, since aaa5a94)
 Terraform state  ──── ["192.168.10.71"]                refreshed by stage 3 (serial 5, 2026-10-19)
 Proxmox qm config ─── 192.168.10.71                    aligned by stage 2 (2026-10-19)
 Guest (netplan) ───── 127.0.0.1 → dnsmasq             (dns_resolver role, kept across the 2026-10-20 reboot)

 qm set --nameserver ──► user/network-data change
                     ──► instance-id = sha1(user . network) changes
                     ──► next boot: cloud-init thinks "new instance"
                           ├─ re-renders netplan with nameservers   ✗ → guard 1 (Ansible)
                           ├─ regenerates SSH host keys             ✗ → guard 2 (Ansible)
                           └─ apt dist-upgrade (package_upgrade)    ✗ → --ciupgrade 0 (Proxmox)
```

Three stages, strictly in this order, each one gated:

```
 Stage 1 — Ansible   lay the guards on the guest        ✅ done 2026-10-19
 Stage 2 — Proxmox   qm set --nameserver --ciupgrade 0   ✅ done 2026-10-19
 Stage 3 — Terraform plan, then apply -refresh-only      ✅ done 2026-10-19, bpg 0.96.0
 Chapter 7 — qm reboot 9030 with the new instance-id      ✅ done 2026-10-20
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

### 1.3 ✅ Resolved: the memory divergence

| Where | `vm_memory_floating` |
|---|---|
| `main` since MR !61 (`cd9e06f`, `fix/hermes-memory-floor`) | `3584` |
| This branch (rebased onto `cd9e06f`) | `3584` |
| Production (`qm config 9030`) | `balloon: 3584` |

Until 2026-10-19, `main` carried `2048` while production ran `3584`: a plan would
have shown an unrelated `floating 3584 → 2048` change that bpg applies **with a
reboot**. MR !61 brought the floor to `main` on its own, without the rest of M2.
This branch was rebased onto it and contains no M2 change.

Also note that the hermes Terraform state and `.terraform/` are local and
gitignored: they live in the **main checkout** (`homelab/hermes/terraform/`),
not in a worktree. Stage 3 runs there, on an up-to-date `main`.

### 1.4 ⚠️ Provider upgrade pending: Renovate MR !60

MR !60 (Renovate, open) bumps `bpg/proxmox` from `0.96.0` to `0.117.0` in every
`providers.tf`, `hermes/terraform/` included. Every plan in this guide was
audited with `0.96.0`.

If !60 is merged before stage 3, a `plan` mixes two unrelated sources of change:
the DNS reconciliation and 21 minor versions of provider behavior (new defaults,
attribute normalization, schema changes). An unexpected diff could then not be
attributed — and bpg applies some VM changes **with a reboot**.

> ⛔ **Run stage 3 with `0.96.0`**, before !60 is merged. If !60 lands first,
> treat its plan on hermes as a separate review: any diff → stop, no apply,
> no `-refresh-only`.

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

All must be true before stage 1. Values recorded on 2026-10-16, re-checked
all green on 2026-10-19 just before stage 1. P1–P4 now describe the state
**before** the fix: after stage 2 they no longer hold (see Chapter 6).

| # | Check | Command | Expected |
|---|---|---|---|
| P1 | Proxmox cloud-init inputs unchanged | `ssh pve 'sudo /usr/sbin/qm cloudinit pending 9030'` | only `cur` lines; `nameserver: 192.168.10.71 1.1.1.1` |
| P2 | `ciupgrade` not set (default 1) | `ssh pve 'sudo /usr/sbin/qm config 9030 \| grep ciupgrade'` | no output |
| P3 | Guest and Proxmox agree on the instance-id | `ssh hermes-30 'cat /run/cloud-init/.instance-id'` and `ssh pve 'sudo /usr/sbin/qm cloudinit dump 9030 meta'` | both `73c90b4ec3002c9cc64c363a2cc223584ad64f13` |
| P4 | No guard yet on the guest | `ssh hermes-30 'ls /etc/cloud/cloud.cfg.d/'` | `05_logging.cfg 90_dpkg.cfg 99-proxmox.cfg README` |
| P5 | Guest resolver in target state | `ssh hermes-30 'resolvectl dns eth0'` | `127.0.0.1` only |
| P6 | NIC MAC unchanged | `ssh pve 'sudo /usr/sbin/qm config 9030 \| grep ^net0'` | `virtio=BC:24:11:C4:2D:D7` |
| P7 | Branch is clean and local | `git status; git log origin/main..HEAD` | clean; only this fix's commits |
| P8 | Playbook parses, tasks in order | `cd hermes && ansible-playbook ansible/deploy.yml --syntax-check` then `ansible-playbook ansible/deploy.yml --list-tasks --tags dns` | `playbook: ansible/deploy.yml`, then the two guard tasks listed **before** `Strip the nameservers...` |
| P9 | Inventory and vault readable | `cd hermes && ansible-inventory --graph && ansible-inventory --host hermes-30 >/dev/null` | group `hermes` → `hermes-30` only; no decryption error |

> 💡 **Note**: `--tags dns` also runs the two timezone `pre_tasks` (tagged with
> every role). They are idempotent: `ok` expected, `America/Guadeloupe` already
> set. The M2 branch changes neither those tasks nor any `dns_*` variable, so
> running stage 1 from this branch does not roll back anything M2 deployed.

> ⚠️ **Warning**: run the two P8 commands separately. Combined,
> `--syntax-check` wins and `--list-tasks` prints nothing: the order check
> silently does not happen.

> 💡 **Note**: in a git worktree, `.envrc` (gitignored) is absent, so direnv
> does not activate `.venv` and `ansible-playbook` may resolve to another
> install. Check `which ansible-playbook` → `<repo>/.venv/bin/` before P8.

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

> ✅ **Executed 2026-10-19**: dry run then real run, both `changed=2` (the two
> `cloud.cfg.d` files, laid 19:22 AST), `failed=0`, no `netplan apply`, dnsmasq
> not restarted, final assert green. Loader check: `{'config': 'disabled'} False`.

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

> ✅ **Executed 2026-10-19**. `qm set` has no dry run: the resulting
> instance-id was first predicted by rebuilding user-data and network-data from
> `qm cloudinit dump` (sha1 of both, each **without** the trailing newline the CLI
> adds). Predicted and actual Proxmox instance-id:
> `75b6756e73e189a59cacadd1ab132970521a3337`. `pending` showed only the two
> expected values; the VM kept running.

### 5.3 ✅ Stage 3 — Terraform (reconciled)

Gates:

- §1.3 resolved — ✅ `main` has `vm_memory_floating = 3584` (MR !61);
- this branch merged;
- provider still `0.96.0` — MR !60 not merged yet (§1.4).

From the main checkout, on an up-to-date `main`:

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

> ✅ **Executed 2026-10-19** (bpg `0.96.0`, MR !60 not merged). `plan` → `No
> changes`. `plan -refresh-only` showed `floating 2048 → 3584`, `dns -1.1.1.1`
> plus expected computed noise (`ipv4/ipv6/mac_addresses`,
> `network_interface_names`, `cpu.flags null → []`). The saved plan file was
> applied: serial 4 → 5, lineage unchanged, Proxmox and guest untouched. A plain
> `plan` then returned `No changes`.

------

## ✅ Chapter 6: Verify

After stage 1, and again after stage 2:

```bash
ssh hermes-30 '
  resolvectl dns                                   # Link eth0: 127.0.0.1 only
  sudo grep "^DNS=" /run/systemd/network/10-netplan-eth0.network   # DNS=127.0.0.1 (root-only file)
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
| Proxmox instance-id (`qm cloudinit dump 9030 meta`, after stage 2) | `75b6756e...` |
| `terraform plan` (stage 3 only) | `No changes` |

Both runs (after stage 1, after stage 2) were green on 2026-10-19.

------

## 🔁 Chapter 7: The reboot with the new instance-id

### 7.1 🔁 How to reboot (reproducible)

Only a reboot **through Proxmox** rebuilds the cloud-init drive: `qm reboot`
stops QEMU, and `vm_start` → `apply_cloudinit_config` regenerates the ISO. QEMU
runs without `-no-reboot`, so `sudo reboot` inside the guest keeps the same
process and the old drive — every check would pass without testing anything.

```bash
ssh pve 'sudo /usr/sbin/qm reboot 9030 --timeout 180'   # never `sudo reboot` in the guest
```

Capture a baseline first (host key fingerprints, `wc -l /var/log/cloud-init.log`
= `N`, sha256 of the watched files) and read only log lines after `N`.

### 7.2 ✅ Checks (reproducible)

Run Chapter 6 again, plus:

```bash
N=<cloud-init.log line count captured before the reboot>
ssh hermes-30 "
  cat /run/cloud-init/.instance-id                       # C1a: 75b6756e73e189a59cacadd1ab132970521a3337
  sudo blkid /dev/sr0                                    # C1b: UUID dated the day of the reboot
  ls /var/lib/cloud/instances/                           # C1c: old and new instance directories
  sudo tail -n +\$((N+1)) /var/log/cloud-init.log | grep 'previous iid found'   # C1d: first line = OLD id
  cloud-init status --long | head -7                     # C1e: status done, errors []
  sudo tail -n +\$((N+1)) /var/log/cloud-init.log | grep -c 'network config is disabled'   # >= 1
  sudo tail -n +\$((N+1)) /var/log/cloud-init.log | grep -cE 'Generating public/private|Package upgrade'   # 0
  sudo sha256sum /etc/netplan/*.yaml                     # identical to the baseline
"
ssh pve 'sudo /usr/sbin/qm cloudinit pending 9030 | grep -E "^(new|del)"'   # nothing pending
```

> ⚠️ **Warning**: `/var/lib/cloud/data/previous-instance-id` is **not** evidence
> of the old instance. cloud-init writes it at every stage: `init-local` records
> the old id, then `init` (network stage), two seconds later, reads the id that
> was just switched and overwrites the file with the **new** id. After the
> reboot both files hold `75b6756e...`. The transition is proven by the first
> `previous iid found to be <old id>` line after `N` and by the two directories
> under `/var/lib/cloud/instances/`.

### 7.3 📜 Observed on 2026-10-20 (historical record, not a guarantee)

`qm reboot 9030 --timeout 180` at 12:05:37 AST: `qmreboot OK`, `qmstart OK`
(12:05:44), SSH back at 12:06:12. A disk-only snapshot `pre-ch7` was taken at
11:52:57, just before.

| Check | Result |
|---|---|
| Instance-id | `75b6756e...` active; log: `previous iid found to be 73c90b4e...` (init-local, 16:06:02 UTC) |
| Drive | UUID `2026-10-20-12-05-44-00`; nothing pending in Proxmox |
| Network guard | `network config is disabled by system_cfg` ×2 |
| Netplan, `ubuntu.sources`, `/etc/hosts`, dnsmasq, Hermes compose and managed config | sha256 identical to the baseline (13 files) — even though `apt_configure` re-ran |
| IP / route / DNS | `192.168.10.30/24`, default via `.1`, `DNS=127.0.0.1` only; internal and public names resolve |
| SSH host keys | the 3 fingerprints of Chapter 4, file mtimes unchanged (2026-08-20) |
| Upgrade | `package_update_upgrade_install` skipped; no apt run after the reboot |
| Kernel | `6.8.0-146` → `6.8.0-147` (pending update, accepted beforehand) |
| Hermes | 3 containers `Up`, gateway running, 2 Telegram `ESTAB`, profile `default` running, 3 crons with unchanged `Next run`, no catch-up run |
| Telegram | the user confirmed the bot answers |
| Terraform | `plan -refresh=false -lock=false` → `No changes`, state unchanged (serial 5) |
| cloud-init status | `done`, `errors: []`, `extended_status: degraded done` — see below |

**`degraded done`** comes only from two `DEPRECATED` recoverable entries (stages
`init` and `modules-final`): *"'user' of type string is deprecated in 22.2 and
scheduled to be removed in 27.2"*. The key is generated by Proxmox itself
(`PVE/QemuServer/Cloudinit.pm:141`, `user: <ciuser>`, qemu-server 9.0.30) from
`ciuser`, which Terraform sets through `user_account.username`; no `cicustom`.
The same notice is in the log of the first boot (2026-08-20, cloud-init 25.3)
and absent from the 12 same-instance boots in between: it is emitted when
user-data is processed for a **new** instance. No functional impact. Risk: only
once cloud-init ≥ 27.2 drops the key, and only at a new instance — `users:
[default]` would then fall back to the image's default user. Watch the
Proxmox/cloud-init release notes; nothing to change today.

### 7.4 📸 Snapshot `pre-ch7`

| | |
|---|---|
| Purpose | local undo point for the Chapter 7 reboot |
| Taken | 2026-10-20 11:52:57 AST, disk only (`--vmstate 0`), guest FS frozen by the agent |
| Parent | `base-clean` (2026-08-20, **pre-Hermes**: never a recovery point for this VM) |
| Limits | same thin pool as the disk: **not a backup**; LVM thin with no autoextend |
| Rollback effect | disk back to 11:52:57: everything Hermes wrote since (sessions, memory, cron state) is lost; Proxmox still serves `75b6756e...` at the next start |

Keep it temporarily. Deferred deletion, only when **all** of the following hold:

1. Hermes stable since the reboot (gateway running, Telegram `ESTAB`, no incident);
2. each of the 3 crons has run once after 2026-10-20 with `ok` (`hermes cron list`
   → `Last run`), i.e. after Saturday 2026-10-24 08:00 UTC at the earliest;
3. no incident recorded on hermes-30 since the reboot;
4. a **new explicit human authorization**.

```bash
ssh pve 'sudo /usr/sbin/qm listsnapshot 9030'          # pre-ch7 present, current is its child
ssh pve 'sudo /usr/sbin/qm delsnapshot 9030 pre-ch7'   # only after 1–4; never base-clean in the same step
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
| Other per-instance modules (`users_groups`, `apt_configure`, `locale`, `set_passwords`, `mounts`) re-run at each new instance | hermes-30 | re-ran on 2026-10-20 with no file change (§7.3); same proof needed after any cloud-init input change |
| Ansible blind to host key changes (`host_key_checking = False`) | all projects | manual fingerprint check (Chapter 4); backlog |
| Provider bump `0.96.0 → 0.117.0` (MR !60) | Terraform on hermes | separate review; first plan must be `No changes` (§1.4) |
| `ciupgrade` not modelled by bpg: a `-replace` would recreate 9030 with the default (`package_upgrade: true`) | hermes-30 | re-run `qm set 9030 --ciupgrade 0` after any rebuild |
| `user:` string deprecated (removal in cloud-init 27.2), generated by Proxmox | all VMs | watch release notes (§7.3) |
| No backup of hermes-30 at all; `pre-ch7` and `base-clean` are on the same thin pool | hermes-30 | separate backup effort |
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
> **Version**: 1.3 — 2026-10-20: stage 3 and Chapter 7 executed, C1 corrected (`previous-instance-id`), `degraded done` analysed, `pre-ch7` documented — closed
> (1.2 — 2026-10-19: stages 1–2 executed, memory gate lifted (MR !61), provider risk (MR !60), P8 split)
