```
 ██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗
 ██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝
 ███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗
 ██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║
 ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║
 ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝
```

# 🚀 Hermes - AI Agent Host Automation

![Stars](https://img.shields.io/github/stars/TiPunchLabs/homelab?style=social) ![Last Commit](https://img.shields.io/github/last-commit/TiPunchLabs/homelab) ![Status](https://img.shields.io/badge/Status-Active-brightgreen)

This project automates the deployment of [Hermes Agent](https://github.com/nousresearch/hermes-agent) on Proxmox — Terraform provisions the VM, Ansible installs Docker and deploys the agent stack. Inference is offloaded to DeepSeek over HTTPS: no GPU, no PCI passthrough.

## 🌐 Project Architecture

```
                                    hermes-31  (192.168.10.31)
                              ┌──────────────────────────────────────┐
                              │  UFW: 22/tcp · 9119/tcp from .70     │
   caddy-70 ──────────────────┼─► hermes-dashboard   0.0.0.0:9119    │
   https://hermes.internal    │   hermes (gateway)   127.0.0.1:8642  │
                              │   └ one multiplexed gateway serving  │
                              │     default (Nora), cafe-ia (Kaféine)│
                              │     tech-watch (Néo¹), job-search    │
   (internal CA, basic auth)  │     (Scout); one Telegram bot each   │
                              │        │                             │
                              │        ├── /opt/hermes/managed  → /etc/hermes:ro
   dns-71 ────────────────────┤        │    ├── config.yaml  ← Ansible (root)
   hermes.internal → .70      │        │    └── .env         ← Ansible (Vault)
                              │        └── /opt/hermes/data   → /opt/data
                              │             ├── config.yaml  ← agent
                              │             └── memories/ skills/ sessions/
                              │                                      │
   dockhost-90 ◀──────────────┼─── komodo-periphery (outbound ws://) │
   komodo-core :9120          │        ↳ /var/run/docker.sock  :ro    │
   observes, cannot act       └──────────────────┬───────────────────┘
                                                 │ HTTPS
                                                 ▼
                                        api.deepseek.com
```

> ¹ **M7 (prepared, not deployed):** Néo is consolidated into Kaféine and
> removed from the repository declarations; hermes-31 keeps serving it until
> the M7.3 runbook parks it (`hermes -p tech-watch gateway stop`) **before**
> the deploy, then deletes it on a separate approval. Target: Nora, Kaféine,
> Scout. See [M7](ansible/roles/hermes_agent/README.md#m7--kaféine-consolidation-and-néo-retirement).

> 👁️ Komodo **observes** this host. The Docker socket is mounted read-only, so
> Periphery can read logs and stats but cannot start, stop or destroy anything —
> `hermes_agent` remains the sole controller of the stack. See
> [`roles/komodo_periphery/README.md`](ansible/roles/komodo_periphery/README.md).

### Deployed Roles

Each role is deployed in this order by `deploy.yml`:

| Role / tag | Description |
|---|---|
| `motd` | Custom login banner (ASCII art) |
| `security_hardening` / `security-hardening` | SSH hardening + UFW |
| `docker` | Docker Engine + Compose plugin, log rotation |
| `hermes_agent` / `hermes` | Hermes Agent stack (Docker Compose) |
| `dns_resolver` / `dns` | dnsmasq split-horizon — `.internal` pinned to Pi-hole |
| `internal_ca_trust` / `ca` | Trust Caddy's internal CA (host + containers) |
| `komodo_periphery` / `komodo-periphery` | Komodo agent — read-only observer |

> ⚠️ Tag names are **not** always the role name: `security-hardening` uses a hyphen,
> `hermes_agent` is tagged `hermes`, `komodo_periphery` is tagged
> `komodo-periphery`, `dns_resolver` is tagged `dns` and `internal_ca_trust` is
> tagged `ca`.

> 🔐 **Order matters**: `internal_ca_trust` fills the host CA bundle that
> `hermes_agent`'s compose mounts into the containers. Running them the other way
> round would mount a bundle without the internal CA. Same for `dns_resolver`:
> the agent reaches `api.deepseek.com` by name.

### Stack

| Component | Value |
|---|---|
| Image | `nousresearch/hermes-agent:v0.22.5` (Docker Hub, **pinned** in `host_vars/hermes-31`) |
| Gateway | one multiplexed gateway (`gateway-default`) serving the four profiles; three declared since M7 (Néo retired by the M7.3 runbook) |
| Containers | `hermes` (gateway) · `hermes-dashboard` |
| Network mode | `host` — see [Why host networking](#-why-host-networking) |
| Inference | DeepSeek direct (`https://api.deepseek.com/v1`), model `deepseek-v4-flash` |
| Data volume | `/opt/hermes/data` → `/opt/data`, owned by `ansible` (UID 1000) |
| Dashboard | `https://hermes.internal` via Caddy, username/password auth |

### VM Specs

- CPU: 2 cores | RAM: 4096 MB (fixed, no ballooning) | Disk: 32 GB SSD
- Template ID: 9001 | VMID: 9031 | IP: 192.168.10.31 | Terraform root: `terraform-31/`
- Disk: `discard=on`, `ssd=1`, `iothread=1` with a `virtio-scsi-single` controller
- Autostart on node boot (`on_boot`, startup order 10 / up 30 / down 60)
- DNS (cloud-init, bootstrap only): Pi-hole `192.168.10.71`, search domain `internal`;
  the `dns_resolver` role then switches the guest to dnsmasq on `127.0.0.1`

## 📋 Prerequisites

- Terraform (>= 1.11.0)
- Ansible
- Proxmox account with appropriate permissions
- A Proxmox VM template (template ID 9001 by default)
- A DeepSeek API key

## 🛠️ Usage

### 1. VM Provisioning with Terraform

```bash
cd terraform-31
terraform init
terraform plan
terraform apply
```

> 🪦 `terraform/` (hermes-30, VMID 9030) was retired in M6.6: the VM was destroyed
> by Terraform in M6.6.C (2026-10-26) and its root removed from Git in M6.6.D.1.

> ⚠️ **Changing `initialization {}` does not reach a running guest — until its next
> boot.** `terraform plan` reports `update in-place` for DNS or user changes. Nothing
> changes while the VM runs, but Proxmox derives the cloud-init instance-id from that
> content: at the next boot cloud-init sees a new instance and re-runs its
> per-instance modules (network, SSH host keys, `apt upgrade`). The `dns_resolver`
> role pins the first two; see
> [`docs/guides/guide-hermes-cloudinit-dns-drift.md`](../docs/guides/guide-hermes-cloudinit-dns-drift.md)
> before aligning Proxmox. To really re-provision from cloud-init, rebuild:
>
> ```bash
> terraform apply -replace='module.hermes_31_vm.proxmox_virtual_environment_vm.vm[0]'
> ```

### 2. Fill the vault (first deployment only)

```bash
ansible-vault edit ansible/group_vars/hermes/vault/config.yml
```

| Variable | Source |
|---|---|
| `vault_hermes_deepseek_api_key` | [DeepSeek console](https://platform.deepseek.com) |
| `vault_hermes_api_server_key` | `openssl rand -hex 32` |
| `vault_hermes_dashboard_password` | your choice |
| `vault_hermes_dashboard_secret` | `openssl rand -base64 32` |

> 🔑 The dashboard **will refuse to start** without a password and secret — Hermes
> declines any non-loopback bind with no auth provider registered.

### 3. Deployment with Ansible

```bash
# --limit is mandatory: deploy.yml refuses an implicit target
ansible-playbook ansible/deploy.yml --limit hermes-31

# Or a single layer
ansible-playbook ansible/deploy.yml --limit hermes-31 --tags motd
ansible-playbook ansible/deploy.yml --limit hermes-31 --tags security-hardening
ansible-playbook ansible/deploy.yml --limit hermes-31 --tags docker
ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes
```

> 🧬 The `m<N>-*.yml` and `profiles-preflight.yml` playbooks belong to the
> v0.20.4 model (one gateway per profile, hermes-30). They are kept as history
> and for their offline tests, and refuse a multiplexed host such as hermes-31.
> On hermes-31, `--tags hermes` itself checks the multiplexed topology and the
> Telegram connection of every declared profile after every run. Since M7,
> run `deploy.yml` only once Néo is parked (M7.3 runbook): a served but
> undeclared profile fails the exact topology check.

### 4. Publish the name and the route

The hostname and the reverse-proxy vhost live in **other sub-projects**:

```bash
cd ../pihole && ansible-playbook ansible/deploy.yml --tags pihole   # hermes.internal → .70
cd ../caddy  && ansible-playbook ansible/deploy.yml --tags caddy    # vhost → .31:9119
```

> Order matters: the UFW rule allowing `192.168.10.70` is created by step 3, before
> Caddy ever tries to reach the dashboard.

## 🔐 Security

| Control | Implementation |
|---|---|
| Firewall | UFW default deny in — `22/tcp` (any) + `9119/tcp` (**from `192.168.10.70` only**) |
| Gateway API | One multiplexed gateway, `127.0.0.1:8642` only (per-profile mirrors under `/p/<profile>/`); `API_SERVER_KEY` as defense in depth |
| Profiles | One multiplexed gateway, **one Telegram bot per profile** (distinct tokens, checked by `getMe`); Kaféine and Scout (and Néo until M7.3): no MCP (no Kandidat), no cron, restricted toolsets **verified tool by tool** on every platform, `skills.write_approval`. **Nora** is `default` itself (historical bot, `:8642`): tools limited to web (Tavily), memory under approval, todo, clarify; no session_search, skills, terminal, file or cron; Kandidat disabled — see [`roles/hermes_agent/README.md`](ansible/roles/hermes_agent/README.md) |
| Dashboard | Username/password, session-signing secret, TLS terminated by Caddy |
| Secrets | Ansible Vault → managed `.env` (`0640 root:1000`, read-only mount) — the agent can read it, **not rewrite it**; never in `config.yaml`. Exception: each profile's **Telegram bot token** lives in that profile's own `.env` (`0600`), written key by key — see [`roles/hermes_agent/README.md`](ansible/roles/hermes_agent/README.md) |
| Telegram | One shared allowlist, pinned in the managed layer for every profile; `*_ALLOW_ALL_USERS` pinned to `false` |
| Logs | Hermes redacts secrets in `logs/`; Docker caps them at 10 MB × 3 |

### 🌐 Why host networking

The upstream repo ships two Compose variants. They are **not** equivalent here:

| | `network_mode: host` | bridge + `ports:` |
|---|---|---|
| Docker NAT rules | none | created |
| UFW | ✅ applies normally | ❌ **bypassed** — ports reachable LAN-wide despite `deny` |
| `.internal` in the container | ✅ resolved via the host resolver | ❌ not inherited |

Docker inserts its DNAT rules **before** UFW's in the netfilter chain. Publishing
`9119` with `ports:` would expose it to the whole LAN while `ufw status` kept
displaying `deny` — a green light that lies. Hence `network_mode: host`.

### 🚧 The Ansible / agent boundary — per **key**, not per file

Ansible's configuration goes to `/opt/hermes/managed`, mounted read-only on
`/etc/hermes` — Hermes' *managed scope* layer. Its keys are deep-merged **on
top** of the volume's `config.yaml` and win **at the leaf**. The managed layer is
**global to every profile**: never put a per-profile value there.

| | Owner | Enforcement |
|---|---|---|
| `/opt/hermes/managed/{config.yaml,.env}` | Ansible | `root:1000`, mode `0640`, mounted `:ro` |
| `TELEGRAM_BOT_TOKEN` in `/opt/hermes/data/.env` (and later `profiles/<name>/.env`) | Ansible, **that key only** | `lineinfile`, `0600`, `no_log` |
| `SOUL.md` of an additional profile | seeded once by Ansible, then the agent/user | never overwritten |
| everything else in `/opt/hermes/data/**` | the agent | writable by UID 1000 |

> ⚠️ **Never delete a file the agent writes to.** The role once removed
> `/opt/hermes/data/.env` as "superseded"; on 2026-08-24 that silently killed the
> Telegram bot with a green playbook. Ansible owns **keys**, not files.

The earlier design drew the boundary **per file** — Ansible owned all of
`config.yaml`. That worked as long as the only other writers (`hermes setup`,
`hermes model`) touched the *same* keys, where overwriting is the correct
behaviour. It broke on the first writer to add a *different* key:
`hermes gateway setup` writes `platforms:`, which the next playbook run erased
without a word.

Verified on the pinned version — pinning `model.provider` while the agent owns
the rest:

```
model.provider  : deepseek                          ← pinned by Ansible
model.default   : modele-utilisateur                ← user value survives
platforms       : {"telegram": {"enabled": true}}   ← survives untouched
```

> ⚠️ **The directory mode is the critical parameter.** If the agent cannot
> traverse `/etc/hermes`, `stat()` raises and Hermes returns `None`, commented
> `# absent` — no log, no error, policy simply not applied. An *unreadable file*
> logs loudly; an *untraversable directory* is silent. The role asserts the layer
> is really applied after every deployment for exactly this reason.

> 💡 Adding a key to the managed layer makes it **unoverridable**. Declare only
> what Ansible must own — leave `platforms:` and anything a `hermes ... setup`
> wizard legitimately manages to the agent.

## 📂 File Structure

```
.
├── ansible/
│   ├── deploy.yml                              # Main playbook (--limit hermes-31)
│   ├── m1-*.yml ... m5-*.yml                   # historical v0.20.4: refuse a multiplexed host (no m3-*, removed in M7)
│   ├── profiles-preflight.yml                  # historical v0.20.4: idem
│   ├── inventory.yml                           # hermes-31 only
│   ├── host_vars/hermes-31/main.yml            # v0.22.5, multiplex, Telegram, Komodo Server
│   ├── requirements.yml                        # community.docker, ansible.posix
│   ├── group_vars/hermes/
│   │   ├── all/main.yml                        # Tunables
│   │   └── vault/config.yml                    # Encrypted secrets
│   └── roles/
│       ├── motd/
│       ├── security_hardening/                 # SSH + UFW (supports per-rule `src`)
│       ├── docker/                             # Engine + Compose + log rotation
│       └── hermes_agent/                       # see its README.md
│           ├── defaults/main.yml
│           ├── tasks/
│           │   ├── main.yml                    # stack + post-deploy checks
│           │   ├── validate.yml                # inventory guards, before any write
│           │   ├── env_keys.yml                # .env keys, one by one, no_log
│           │   ├── soul_seed.yml               # SOUL.md seeded once
│           │   ├── default_soul.yml            # live SOUL.md replaced once, predecessor checksum guard
│           │   ├── profile_multiplex.yml       # additional profiles on v0.22.5 (cafe-ia, job-search)
│           │   ├── profiles.yml, profile.yml   # additional profiles, v0.20.4 path (history)
│           │   └── profile_content.yml         # owned content, no bytecode
│           ├── handlers/main.yml
│           ├── filter_plugins/hermes_profiles.py
│           ├── files/
│           │   ├── hermes_checks.py            # checks run inside the container
│           │   └── profiles/
│           │       ├── cafe-ia/                # Kaféine — deployed (M2), consolidated SOUL.md (M7, not deployed)
│           │       └── job-search/             # Scout — deployed (M4.3)
│           └── templates/
│               ├── docker-compose.yml.j2
│               ├── config.yaml.j2              # Managed layer — no secrets
│               └── hermes.env.j2               # Managed layer — secrets, 0640
├── tests/                                      # uv run pytest hermes/tests -q
├── terraform-31/
│   ├── main.tf, providers.tf, variables.tf, outputs.tf
├── ansible.cfg
└── README.md                                   # This file
```

## 🔧 Troubleshooting

### The agent answers but ignores DeepSeek

A malformed `providers:` block does **not** raise an error — Hermes silently falls
back to the `auto` provider. Always check what was actually resolved:

```bash
ssh hermes-31 'sudo docker exec hermes hermes status'
#   Model:     deepseek-v4-flash
#   Provider:  DeepSeek
#   DeepSeek   ✓ sk-d...
```

### `hermes status` and the `.env file` line

That line reports the *user-scope* `/opt/data/.env`. Since mission M1 it exists
and holds the default bot's `TELEGRAM_BOT_TOKEN` (before M1 it was absent and the
line read `✗ not found`, which was normal too). Either way, what proves the
DeepSeek key resolved is the provider:

```
  Model:        deepseek-v4-flash
  Provider:     DeepSeek           <- this is what proves the key resolved
```

A genuine problem looks different: `Provider` falling back to `auto`, or the
DeepSeek line showing `✗ (not set)` under **API Keys**.

### The dashboard container refuses to start

```
Refusing to bind dashboard to 0.0.0.0 — the auth gate engages on
non-loopback binds, but no auth providers are registered.
```

The vault placeholders were never replaced. See [step 2](#2-fill-the-vault-first-deployment-only).

### `hermes.internal` does not resolve

The record lives in `pihole/`, not here. Check the client's resolver first — a
machine that does not use Pi-hole will never resolve `.internal`.

```bash
dig +short hermes.internal @192.168.10.71   # expected: 192.168.10.70
```

### TLS warning in the browser

`hermes.internal` is served with Caddy's **internal CA**. Trust Caddy's root CA on
the client machine, same as `portail-client.internal`.

### Useful checks

```bash
ssh hermes-31 'sudo docker compose -f /opt/hermes/docker-compose.yml ps'
ssh hermes-31 'sudo ss -tlnp | grep -E "8642|9119"'
ssh hermes-31 'sudo ufw status numbered'
ssh hermes-31 'sudo docker logs hermes --tail 50'
```

## 📚 Documentation

- [Hermes Agent — official documentation](https://github.com/nousresearch/hermes-agent)
- [`../docs/references/ip-addresses.md`](../docs/references/ip-addresses.md) — addressing plan and `.internal` records
- [`../caddy/README.md`](../caddy/README.md) — reverse proxy and per-backend flags
- [`../pihole/README.md`](../pihole/README.md) — `.internal` DNS

## ⚠️ Known Gaps

- **No backup of `/opt/hermes/data`.** It is the only directory on this VM whose
  loss would be irreversible — memory, skills, sessions, cron, `SOUL.md`. No
  backup or restore procedure for hermes-31 exists or has been tested.
- **No rollback VM.** hermes-30 (v0.20.4) was destroyed in M6.6.C (2026-10-26)
  with its disks, its two snapshots and the one-off M5 backup it held. Recovery
  means redeploying hermes-31 from `terraform-31/` and `deploy.yml`, which
  rebuilds the configuration and the declared profiles (three since M7) but **not**
  their data: memories, sessions and skills would start empty. This path has
  not been exercised end to end.
- **The dashboard does not reload default's config**: after a change to
  default's config, `docker restart hermes-dashboard` (M5.4).
- **AppArmor userns**: Ubuntu 24.04 restricts unprivileged user namespaces. Moot
  while the Docker daemon runs as root; it would resurface with rootless or nested
  containers. Apply `kernel.apparmor_restrict_unprivileged_userns=0` **on a
  confirmed symptom only** — it lowers a kernel protection.

## 👥 Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
