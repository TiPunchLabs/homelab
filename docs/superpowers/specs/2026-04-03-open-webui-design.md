# Open WebUI on dockhost-90 — Design Spec

## Context

Open WebUI is currently deployed locally via a separate Ansible project (`ansible-docker-apps`). The goal is to migrate it to dockhost-90 in the homelab monorepo, connected to Ollama on the local workstation (192.168.1.101) and using the existing PostgreSQL instance on dockhost-90 for its database.

## Decision

- New `open_webui` Ansible role in `dockhost/ansible/roles/`
- Open WebUI listens on `0.0.0.0:8080`, Caddy reverse proxies `openwebui.internal`
- Ollama backend: `http://192.168.1.101:11434` (workstation LAN IP)
- Database: PostgreSQL on dockhost-90 via `db-net` Docker network
- DNS via Pi-hole, reverse proxy via Caddy

---

## Architecture

```
Client (VPN) → Pi-hole DNS → openwebui.internal = 192.168.1.70
                              → Caddy (caddy-70) reverse_proxy
                              → http://192.168.1.90:8080
                              → Open WebUI (dockhost-90)
                              → Ollama (192.168.1.101:11434)
                              → PostgreSQL (dockhost-90, db-net)
```

---

## 1. Open WebUI Role (`dockhost/ansible/roles/open_webui/`)

### Structure

```
open_webui/
├── defaults/main.yml
├── tasks/main.yml
├── templates/
│   └── docker-compose.yml.j2
└── handlers/main.yml
```

### Defaults (`defaults/main.yml`)

| Variable | Value | Description |
|----------|-------|-------------|
| `open_webui_image` | `ghcr.io/open-webui/open-webui` | Docker image |
| `open_webui_image_tag` | `v0.8.3` | Image version |
| `open_webui_image_digest` | `sha256:21c24dc456da582a365751803057cd25de9a24ee99e8ba9715b0184936ba7988` | Pinned digest |
| `open_webui_install_dir` | `/opt/open-webui` | Compose file location |
| `open_webui_data_dir` | `/app/data/open-webui` | Persistent data volume |
| `open_webui_http_port` | `8080` | HTTP port |
| `open_webui_bind_address` | `0.0.0.0` | Listen on all interfaces (Caddy access) |
| `open_webui_ollama_base_url` | `http://192.168.1.101:11434` | Ollama API on workstation |
| `open_webui_db_container` | `postgresql` | PostgreSQL container name |
| `open_webui_db_name` | `open_webui` | Database name |
| `open_webui_db_user` | `open_webui` | Database user |
| `open_webui_db_superuser` | `postgres` | PostgreSQL superuser |

### Docker Compose (`templates/docker-compose.yml.j2`)

- Image: `ghcr.io/open-webui/open-webui:<tag>@<digest>`
- Container name: `open-webui`
- Restart: always
- Ports: `0.0.0.0:8080:8080`
- Environment:
  - `OLLAMA_BASE_URL`: Ollama API endpoint
  - `DATABASE_URL`: PostgreSQL connection string via `db-net`
  - `WEBUI_SECRET_KEY`: JWT secret from vault
- Volumes:
  - `/app/data/open-webui:/app/backend/data` (uploads, cache)
- Network: `db-net` (external, shared with PostgreSQL/kandidat)

### Tasks (`tasks/main.yml`)

**PostgreSQL setup (same pattern as kandidat):**
1. Check if PostgreSQL user `open_webui` exists
2. Create user if not exists (with vault password)
3. Check if database `open_webui` exists
4. Create database if not exists (UTF8, owned by `open_webui`)

**Deployment:**
5. Create install directory `/opt/open-webui`
6. Create data directory `/app/data/open-webui`
7. Deploy docker-compose template (notify handler)
8. Start with `docker_compose_v2` (state: present, recreate: auto)
9. Wait for Open WebUI ready (HTTP check on `http://localhost:8080/`, retries: 10, delay: 5)

### Handlers (`handlers/main.yml`)

- **Restart open-webui**: `docker_compose_v2` state: restarted

---

## 2. Caddy Update (`caddy/ansible/group_vars/caddy/all/main.yml`)

New backend entry:

```yaml
- name: openwebui
  domain: openwebui.internal
  upstream: http://192.168.1.90:8080
  tls_insecure_skip_verify: false
```

---

## 3. Pi-hole Update (`pihole/ansible/group_vars/pihole/all/main.yml`)

New DNS record:

```yaml
- ip: 192.168.1.70
  domain: openwebui.internal
```

---

## 4. Dockhost Updates

### deploy.yml

New role added after `portainer`:

```yaml
- role: open_webui
  tags:
    - open-webui
```

Tag `open-webui` added to `db-net` pre_task (alongside `postgresql`, `kandidat`).

### group_vars/dockhost/all/main.yml

New section:

```yaml
# Open WebUI
open_webui_ollama_base_url: "http://192.168.1.101:11434"
```

### security_open_ports

Add port 8080:

```yaml
- { port: 8080, proto: tcp, comment: "Open WebUI" }
```

### Vault

New variables:
- `vault_open_webui_db_password` — PostgreSQL password for open_webui user
- `vault_open_webui_secret_key` — JWT secret key for Open WebUI

---

## 5. Deployment Order

1. `cd dockhost && ansible-playbook ansible/deploy.yml --tags open-webui`
2. `cd pihole && ansible-playbook ansible/deploy.yml --tags pihole`
3. `cd caddy && ansible-playbook ansible/deploy.yml --tags caddy`

After all three: `http://openwebui.internal` accessible through Caddy.

---

## Out of Scope

- Ollama deployment on dockhost (stays on workstation)
- Open WebUI user/model pre-configuration (done via web UI)
- TLS between Caddy and Open WebUI (private LAN)
- Migration of data from local SQLite to PostgreSQL

> **Document created on**: 2026-04-03
> **Author**: Xavier Gueret
> **Version**: 1.0
