# 🗂️ HomeLab — Généralisation des protections Cloud-Init et correction des dérives réseau

> **Status**: 📋 backlog — identified 2026-10-16, **not started**, not scheduled.
> **Origin**: the hermes-30 DNS drift fix (`fix/hermes-cloudinit-dns-drift`) and
> the read-only audit of `proxmox/` that followed it.
> **Explicitly out of scope of that fix**: nothing below may be done as part of it.

## Table of contents

1. Mental Model
2. Why this is a separate effort
3. Findings
4. Scope
5. Open questions
6. Suggested order
7. Done when

------

## 🧠 Mental Model

```
            Proxmox (cloud-init inputs)     Guest (what actually runs)
 dockhost   ipconfig0 192.168.1.90   ✗ ≠   192.168.10.90   guard: network ✅ (manual)  keys ❌
 vpngate    ipconfig0 192.168.1.50   ✗ ≠   192.168.10.50   guard: network ✅ (manual)  keys ❌
 bastion    ipconfig0 192.168.1.60   ✗ ≠   192.168.10.60?  guard: ❓ (VM stopped)
 hermes     ipconfig0 192.168.10.30  ✓ =   192.168.10.30   guard: network + keys (Ansible, pending deploy)

 Any cloud-init change on a VM ──► new instance-id ──► next boot:
     network re-render (blocked by the guard, where present)
     SSH host keys regenerated   (no guard anywhere but hermes)
     apt dist-upgrade            (package_upgrade: true on every VM but hermes)
```

The guard is the de facto rule since 2026-04-28, but it lives in a runbook,
not in code. Each VM's safety depends on whether someone remembered it.

------

## 📖 Why this is a separate effort

The hermes fix is local: one VM, one role, one Proxmox command. Everything
below touches VMs with running services (Komodo, WireGuard, the GitLab
runner), different Terraform states (dockhost's lives on bastion-60) and
shared design decisions. Bundling it with the hermes fix would have turned a
reversible local change into a cross-cutting one.

------

## 🔍 Findings (read-only audit, 2026-10-16)

| # | Finding | Evidence | Risk |
|---|---|---|---|
| F1 | Proxmox `ipconfig0` still on `192.168.1.x`, gw `192.168.1.1`, nameservers `1.1.1.1 8.8.8.8`, searchdomain `local` for 9050, 9060, 9090 | `qm config`; guests on `192.168.10.x` since the 2026-04-28 migration | a Terraform apply that "fixes" it changes the instance-id → reboot (bpg `reboot_after_update`), new host keys, `dist-upgrade` |
| F2 | The network guard exists on dockhost-90 and vpngate-50 **by hand only** | `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg` (2026-04-28); not in any role; documented in `docs/superpowers/plans/2026-04-28-network-migration-192-168-10.md` | lost on rebuild; never applied to VMs created later (hermes-30 was the case) |
| F3 | No `ssh_deletekeys: false` on any VM but hermes | `ls /etc/cloud/cloud.cfg.d/` | silent host key change on the next instance-id change |
| F4 | `package_upgrade: true` on every VM (`ciupgrade` unset → default 1) | `/usr/share/perl5/PVE/QemuServer/Cloudinit.pm:162` | unplanned `dist-upgrade` at boot, Docker included (not pinned, not in unattended-upgrades origins) |
| F5 | `host_key_checking = False` in every `ansible.cfg`, no `known_hosts` entries for the VMs | `hermes/ansible.cfg`, `proxmox/ansible.cfg`, … | F3 would go unnoticed |
| F6 | bastion-60 stopped since 2026-10-16 (scenario A) | `qm list` | its guard state is unknown |
| F7 | LXCs 1070/1071 carry `nameserver 1.1.1.1 8.8.8.8`, searchdomain `local` | `qm`/`pct config` | no cloud-init: Proxmox rewrites `resolv.conf` at each start — a different mechanism, check before touching |

Pre-existing, not part of the drift, noted for completeness:

- `proxmox/ansible/roles/configure/tasks/tasks_generate_vm_template.yml:27` — no
  trailing `\`; observed harmless (lines 28–39 took effect on hermes-30), cause
  not verified;
- template 9001 description `test`;
- root `ansible.cfg` points to an `inventory.yml` that does not exist;
- `kubecluster/terraform` code without VMs on `pve`.


### 🔁 Re-audit dockhost-90 (read-only, 2026-10-30, Bastion+ M3.3)

F1–F4 confirmed unchanged on 9090:

- Proxmox `ipconfig0: gw=192.168.1.1,ip=192.168.1.90/24`; `qm cloudinit dump 9090 meta`
  gives instance-id `4b196b7b…3644`. The guest's `/var/lib/cloud/data/instance-id` has
  the same value, with a single directory under `/var/lib/cloud/instances/`, and all 28
  `previous iid` log lines carry that same id: no instance change since first boot.
- The guard `network: {config: disabled}` is still there (2026-04-28). Hand-edited
  `50-cloud-init.yaml` = `192.168.10.90/24`, gw `.10.1`, DNS `1.1.1.1 8.8.8.8`.
- No `ssh_deletekeys` guard; the user-data dump still has `package_upgrade: true`
  (`ciupgrade` unset).
- Terraform plan against a copy of the state backup: only `initialization.ip_config.ipv4`
  changes. Nameservers and search domain already match the HCL.
- The state is no longer a blocker for open question 5 once it is migrated to GitLab
  (`../guides/runbook-dockhost-tfstate-gitlab-migration.md`).

------

## 🎯 Scope

In:

- dockhost-90, vpngate-50, bastion-60;
- the stale `ipconfig0` values (F1);
- codifying the cloud-init guards (network, SSH host keys) for VMs already
  provisioned (F2, F3);
- a deliberate per-VM decision on the boot-time upgrade (F4);
- host key verification (F5).

Out:

- template 9001 and `proxmox/` template build — a fresh clone **must** still
  render its network and generate its own keys at first boot;
- hermes-30 (covered by its own fix);
- kubecluster (no VMs).

------

## ❓ Open questions

1. **Where does the guard live?** One shared role (needs a `roles_path` or a
   collection — none exists today) or a copy per project (current convention,
   duplication)?
2. **Align `ipconfig0` or leave it?** Aligning means one instance-id change per
   VM — acceptable only once F2–F4 are in place on that VM, and at a planned
   reboot.
3. **Boot-time upgrade policy**: `--ciupgrade 0` on every provisioned VM (as on
   hermes), or `manual_cache_clean: true` in the guard?
4. **Host keys**: populate `known_hosts` and switch `host_key_checking` on, or
   pin fingerprints another way?
5. **dockhost Terraform state** is on bastion-60: plan it from there, and only
   while bastion is up.

------

## 🧭 Suggested order

1. Inspect bastion-60 at its next start (F6) — read-only.
2. Codify the guards (F2, F3) per VM, with tests like `hermes/tests/test_dns_resolver_cloud_init.py`.
3. Decide F4 per VM; apply with the same `qm set` as `ipconfig0` to change
   the instance-id once.
4. Align `ipconfig0` (F1) one VM at a time; verify at a planned reboot.
5. F5 last, once the fingerprints are stable.

------

## ✅ Done when

- every provisioned VM has both guards **from code**, verified by
  `read_conf_with_confd`;
- `terraform plan` shows `No changes` for 9050, 9060, 9090;
- a planned reboot after the change shows `network config is disabled by
  system_cfg`, unchanged host key fingerprints and no boot-time `dist-upgrade`;
- template 9001 untouched.

> **Document created on**: 2026-10-16
> **Author**: Xavier Gueret, with Claude Code
> **Version**: 1.0
