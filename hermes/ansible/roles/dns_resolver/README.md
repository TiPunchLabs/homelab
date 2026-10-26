# Role: dns_resolver

Local split-horizon resolver on the Hermes host (hermes-31; first built for
hermes-30, destroyed in M6.6.C). `.internal` is pinned to the Pi-hole;
everything else goes to public resolvers.

## Mental Model

```
        before (broken)                       after
   ┌──────────────────┐                 ┌──────────────────┐
   │ systemd-resolved │                 │ systemd-resolved │
   │  192.168.10.71   │ sticky failover │    127.0.0.1     │ single upstream
   │  1.1.1.1         │ → switched and  └────────┬─────────┘ → no failover
   └──────────────────┘   stayed there           │              logic left
                                        ┌────────▼─────────┐
                                        │     dnsmasq      │
                                        │ .internal → Pi-hole (pinned)
                                        │ everything else → 1.1.1.1 / 8.8.8.8
                                        └──────────────────┘
```

## Why this role exists

On 2026-08-23, **no `.internal` name resolved from hermes-30**. The Pi-hole was
healthy the whole time — `dig kandidat.internal @192.168.10.71` answered
correctly. `systemd-resolved` had simply switched to its second server and
stayed there.

The old config was `DNS=192.168.10.71 1.1.1.1`, believed to be a safe fallback.
It is not a split-horizon configuration — it is a **domain-blind, sticky
failover list**:

- one timeout from the Pi-hole moves resolution to `1.1.1.1` **permanently**;
- from there `.internal` returns **NXDOMAIN**, a *valid* answer, so nothing ever
  switches back;
- no service goes down. Only internal names quietly vanish.

`systemd-resolved` cannot fix this itself. Per-domain routing (`Domains=~internal`)
requires **per-link** DNS servers (`man resolved.conf`), and this VM has a single
interface fed by cloud-init. So the routing has to live somewhere else.

## The trade accepted

`server=/internal/` in dnsmasq is **pinned by domain**. It never falls back to a
public resolver — so if dns-71 goes down, `.internal` becomes *unavailable*
rather than *wrongly NXDOMAIN*.

That is the point: a loud failure instead of a silent one.

## Task order matters

dnsmasq must answer **before** netplan points the system at it. The role:

1. installs and configures dnsmasq, starts it;
2. **proves** it answers, by querying `127.0.0.1` directly;
3. pins cloud-init (see below) so that a later instance-id change cannot undo
   step 4;
4. only then strips `nameservers` from `50-cloud-init.yaml`, writes the netplan
   override and applies it;
5. verifies end-to-end through `getent` (the real path: nsswitch → resolved →
   dnsmasq), not through `dig`, which would bypass resolved.

Step 2 is the guard rail: if it fails, netplan has not been touched and the VM
still resolves exactly as before.

## Cloud-init guard

Stripping `nameservers` only holds while cloud-init believes it is on the same
instance. Proxmox computes the NoCloud instance-id as
`sha1(user-data . network-data)`, so **any** cloud-init change on the VM
(`qm set --nameserver`, `--sshkeys`, `--ciupgrade`, or a `terraform apply` on
`initialization {}`) gives a new id. At the next boot cloud-init would then:

| Per-instance module | Effect without the guard | Guard |
|---|---|---|
| network rendering | rewrites `50-cloud-init.yaml` **with** `nameservers`; netplan merges → two DNS servers on the link | `99-disable-network-config.cfg` |
| `ssh` | deletes and regenerates the SSH host keys | `99-preserve-ssh-host-keys.cfg` |
| `package_update_upgrade_install` | `apt dist-upgrade` during boot (Proxmox user-data carries `package_upgrade: true`) | **not in this role** — user-data outranks `cloud.cfg.d`; switched off on the Proxmox side for hermes-30 (`qm set 9030 --ciupgrade 0`, see the guide); **not set on hermes-31** (`qm config 9031` has no `ciupgrade` key, 2026-10-26) |
| others (`users_groups`, `apt_configure`, `locale`, `set_passwords`...) | re-run with the same inputs, no expected change | — |

Both files live in `/etc/cloud/cloud.cfg.d/` and only exist on VMs this role
has run on, i.e. **after** their first boot. A fresh clone of template 9001
still gets its network rendered and its own host keys generated — the template
build (`proxmox/`, virt-customize) is untouched.

> ⚠️ With network rendering disabled, `/etc/netplan` is the only source of
> truth. It matches the NIC by MAC (hermes-31: `bc:24:11:18:12:c8`, pinned in
> Proxmox `net0`). A plan that replaces the network device would leave the VM without
> network at the next boot — rebuild instead.

## Terraform side

`hermes/terraform-31/main.tf` keeps `vm_dns_servers = ["192.168.10.71"]` — **bootstrap
only**. Do not point it at `127.0.0.1`: on first boot dnsmasq does not exist yet.

> ⚠️ A change to `initialization {}` does not reach a **running** guest, but it
> does reach it at the **next boot**, through the instance-id change described
> above. Lay the cloud-init guard before aligning Proxmox. Procedure:
> [`docs/guides/guide-hermes-cloudinit-dns-drift.md`](../../../../docs/guides/guide-hermes-cloudinit-dns-drift.md).

## Usage

```bash
cd hermes
ansible-playbook ansible/deploy.yml --tags dns
```

## Rollback

```bash
rm /etc/netplan/99-dns-local.yaml
netplan apply
```

The VM returns to the cloud-init resolver.

To also hand the network and host keys back to cloud-init:

```bash
rm /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
rm /etc/cloud/cloud.cfg.d/99-preserve-ssh-host-keys.cfg
```

Effective at the next instance-id change only; nothing happens at a plain reboot.
