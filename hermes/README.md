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
                                    hermes-30  (192.168.10.30)
                              ┌──────────────────────────────────────┐
                              │  UFW: 22/tcp · 9119/tcp from .70     │
   caddy-70 ──────────────────┼─► hermes-dashboard   0.0.0.0:9119    │
   https://hermes.internal    │   hermes (gateway)   127.0.0.1:8642  │
   (internal CA, basic auth)  │        │                             │
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
| Image | `nousresearch/hermes-agent:v2026.8.18` (Docker Hub, **pinned**) |
| Containers | `hermes` (gateway) · `hermes-dashboard` |
| Network mode | `host` — see [Why host networking](#-why-host-networking) |
| Inference | DeepSeek direct (`https://api.deepseek.com/v1`), model `deepseek-v4-flash` |
| Data volume | `/opt/hermes/data` → `/opt/data`, owned by `ansible` (UID 1000) |
| Dashboard | `https://hermes.internal` via Caddy, username/password auth |

### VM Specs

- CPU: 4 cores (type `host`) | RAM: 8192 MB (ballooning min 2048) | Disk: 32 GB SSD
- Template ID: 9001 | VMID: 9030 | IP: 192.168.10.30
- Disk: `discard=on`, `ssd=1`, `iothread=1` with a `virtio-scsi-single` controller
- Autostart on node boot (`on_boot`, startup order 10 / up 30 / down 60)
- DNS: Pi-hole `192.168.10.71` + `1.1.1.1` fallback, search domain `internal`

## 📋 Prerequisites

- Terraform (>= 1.11.0)
- Ansible
- Proxmox account with appropriate permissions
- A Proxmox VM template (template ID 9001 by default)
- A DeepSeek API key

## 🛠️ Usage

### 1. VM Provisioning with Terraform

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

> ⚠️ **Changing `initialization {}` does not reach a running guest.** `terraform plan`
> reports `update in-place` for DNS or user changes, and reports success — but
> cloud-init only renders `/etc/netplan/50-cloud-init.yaml` at first boot and never
> reads it again. The IaC declares compliance while the machine disagrees. Force a
> rebuild instead:
>
> ```bash
> terraform apply -replace='module.hermes_vm.proxmox_virtual_environment_vm.vm[0]'
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
ansible-playbook ansible/deploy.yml

# Or a single layer
ansible-playbook ansible/deploy.yml --tags motd
ansible-playbook ansible/deploy.yml --tags security-hardening
ansible-playbook ansible/deploy.yml --tags docker
ansible-playbook ansible/deploy.yml --tags hermes
```

### 4. Publish the name and the route

The hostname and the reverse-proxy vhost live in **other sub-projects**:

```bash
cd ../pihole && ansible-playbook ansible/deploy.yml --tags pihole   # hermes.internal → .70
cd ../caddy  && ansible-playbook ansible/deploy.yml --tags caddy    # vhost → .30:9119
```

> Order matters: the UFW rule allowing `192.168.10.70` is created by step 3, before
> Caddy ever tries to reach the dashboard.

## 🔐 Security

| Control | Implementation |
|---|---|
| Firewall | UFW default deny in — `22/tcp` (any) + `9119/tcp` (**from `192.168.10.70` only**) |
| Gateway API | Binds `127.0.0.1:8642`; `API_SERVER_KEY` as defense in depth |
| Dashboard | Username/password, session-signing secret, TLS terminated by Caddy |
| Secrets | Ansible Vault → managed `.env` (`0640 root:1000`, read-only mount) — the agent can read it, **not rewrite it**; never in `config.yaml` |
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

Ansible writes **nothing** into the data volume. Its configuration goes to
`/opt/hermes/managed`, mounted read-only on `/etc/hermes` — Hermes' *managed
scope* layer. Its keys are deep-merged **on top** of the volume's `config.yaml`
and win **at the leaf**.

| | Owner | Enforcement |
|---|---|---|
| `/opt/hermes/managed/{config.yaml,.env}` | Ansible | `root:1000`, mode `0640`, mounted `:ro` |
| `/opt/hermes/data/**` | the agent | writable by UID 1000 |

The role removes the superseded `/opt/hermes/data/.env` — but only as its **last
task**, gated on the managed-scope assertion having passed. That file is what the
agent falls back on if the managed layer is not applied; removing it any earlier
would take the safety net away before knowing the trapeze holds. `config.yaml` in
the volume is deliberately kept: it carries no secret and now belongs to the
agent.

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
│   ├── deploy.yml                              # Main playbook
│   ├── inventory.yml
│   ├── requirements.yml                        # community.docker, ansible.posix
│   ├── group_vars/hermes/
│   │   ├── all/main.yml                        # Tunables
│   │   └── vault/config.yml                    # Encrypted secrets
│   └── roles/
│       ├── motd/
│       ├── security_hardening/                 # SSH + UFW (supports per-rule `src`)
│       ├── docker/                             # Engine + Compose + log rotation
│       └── hermes_agent/
│           ├── defaults/main.yml
│           ├── tasks/main.yml
│           ├── handlers/main.yml
│           └── templates/
│               ├── docker-compose.yml.j2
│               ├── config.yaml.j2              # Managed layer — no secrets
│               └── hermes.env.j2               # Managed layer — secrets, 0640
├── terraform/
│   ├── main.tf, providers.tf, variables.tf, outputs.tf
├── ansible.cfg
└── README.md                                   # This file
```

## 🔧 Troubleshooting

### The agent answers but ignores DeepSeek

A malformed `providers:` block does **not** raise an error — Hermes silently falls
back to the `auto` provider. Always check what was actually resolved:

```bash
ssh hermes-30 'sudo docker exec hermes hermes status'
#   Model:     deepseek-v4-flash
#   Provider:  DeepSeek
#   DeepSeek   ✓ sk-d...
```

### `hermes status` reports `.env file: ✗ not found`

**Expected — not a fault.** That line reports the *user-scope* `.env`, which the
role deliberately removed: the secrets live in the managed layer now. What
matters is the two lines below it:

```
  .env file:    ✗ not found        <- normal
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
ssh hermes-30 'sudo docker compose -f /opt/hermes/docker-compose.yml ps'
ssh hermes-30 'sudo ss -tlnp | grep -E "8642|9119"'
ssh hermes-30 'sudo ufw status numbered'
ssh hermes-30 'sudo docker logs hermes --tail 50'
```

## 📚 Documentation

- [Hermes Agent — official documentation](https://github.com/nousresearch/hermes-agent)
- [`../docs/references/ip-addresses.md`](../docs/references/ip-addresses.md) — addressing plan and `.internal` records
- [`../caddy/README.md`](../caddy/README.md) — reverse proxy and per-backend flags
- [`../pihole/README.md`](../pihole/README.md) — `.internal` DNS

## ⚠️ Known Gaps

- **No backup of `/opt/hermes/data`.** It is the only directory on this VM whose
  loss would be irreversible — memory, skills, sessions, cron, `SOUL.md`.
- **AppArmor userns**: Ubuntu 24.04 restricts unprivileged user namespaces. Moot
  while the Docker daemon runs as root; it would resurface with rootless or nested
  containers. Apply `kernel.apparmor_restrict_unprivileged_userns=0` **on a
  confirmed symptom only** — it lowers a kernel protection.

## 👥 Contributors

- **Author**: Xavier GUERET
  [![GitHub](https://img.shields.io/github/followers/TiPunchLabs?style=social)](https://github.com/TiPunchLabs)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/TiPunchLabs/homelab/blob/main/LICENSE) file for details.
