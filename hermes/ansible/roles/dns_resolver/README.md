# Role: dns_resolver

Local split-horizon resolver on hermes-30. `.internal` is pinned to the Pi-hole;
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
3. only then writes the netplan override and applies it;
4. verifies end-to-end through `getent` (the real path: nsswitch → resolved →
   dnsmasq), not through `dig`, which would bypass resolved.

Step 2 is the guard rail: if it fails, netplan has not been touched and the VM
still resolves exactly as before.

## Terraform side

`hermes/terraform/main.tf` keeps `vm_dns_servers = ["192.168.10.71"]` — **bootstrap
only**. Do not point it at `127.0.0.1`: on first boot dnsmasq does not exist yet.

> ⚠️ A change to `initialization {}` does **not** reach a running guest without
> `terraform apply -replace=...`. The Ansible role is what fixes existing VMs.

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
