# Portainer Server on dockhost-90 — Design Spec

## Context

dockhost-90 currently runs a `portainer_agent` role that deploys only the Portainer Agent (port 9001), designed to be managed by an external Portainer Server. The goal is to replace this with a full Portainer CE Server deployed locally, with automated initial configuration via the Portainer API, exposed through Caddy reverse proxy at `portainer.internal`.

## Decision

- **Option A selected**: single `portainer` role replacing `portainer_agent`
- Portainer Server listens on `127.0.0.1:9000` (HTTP only, Caddy handles external access)
- Admin account and local Docker endpoint bootstrapped via Portainer API
- DNS resolution via Pi-hole, reverse proxy via Caddy

---

## Architecture

```
Client (VPN) → Pi-hole DNS → portainer.internal = 192.168.1.70
                              → Caddy (caddy-70) reverse_proxy
                              → http://192.168.1.90:9000
                              → Portainer CE Server (dockhost-90)
                              → Docker socket (local management)
```

---

## 1. Portainer Role (`dockhost/ansible/roles/portainer/`)

### Structure

```
portainer/
├── defaults/main.yml
├── tasks/main.yml
├── templates/
│   └── docker-compose.yml.j2
└── handlers/main.yml
```

### Defaults (`defaults/main.yml`)

| Variable | Value | Description |
|----------|-------|-------------|
| `portainer_image` | `portainer/portainer-ce` | Docker image |
| `portainer_image_tag` | `2.27.4` | Latest stable version |
| `portainer_image_digest` | `sha256:...` | Pinned digest |
| `portainer_install_dir` | `/opt/portainer` | Compose file location |
| `portainer_data_dir` | `/app/data/portainer` | Persistent data volume |
| `portainer_http_port` | `9000` | HTTP API/UI port |
| `portainer_bind_address` | `127.0.0.1` | Listen only on localhost |

### Docker Compose (`templates/docker-compose.yml.j2`)

- Image: `portainer/portainer-ce:<tag>@<digest>`
- Container name: `portainer`
- Restart: always
- Ports: `127.0.0.1:9000:9000`
- Volumes:
  - `/var/run/docker.sock:/var/run/docker.sock` (Docker management)
  - `/app/data/portainer:/data` (persistent state)
- Network: `vm-docker-90-net` (bridge)
- Command flags: `--http-disabled=false`

### Tasks (`tasks/main.yml`)

1. **Cleanup old agent** — check if `/opt/portainer/agent/docker-compose.yml` exists, tear down compose stack and remove directory if present
2. **Create install directory** — `/opt/portainer` (root, 0755)
3. **Create data directory** — `/app/data/portainer` (root, 0755)
4. **Deploy docker-compose template** — notify restart handler
5. **Start Portainer** — `docker_compose_v2` (state: present, recreate: auto)
6. **Wait for API** — poll `http://localhost:9000/api/status` (retries: 10, delay: 3s)
7. **Check admin exists** — GET `http://localhost:9000/api/users/admin/check`
8. **Create admin user** — POST `http://localhost:9000/api/users/admin/init` with `vault_portainer_admin_username` / `vault_portainer_admin_password` (skip if admin already exists)
9. **Get auth token** — POST `http://localhost:9000/api/auth` (needed for endpoint registration)
10. **Check endpoints** — GET `http://localhost:9000/api/endpoints` with auth token
11. **Register local Docker endpoint** — POST `http://localhost:9000/api/endpoints` with type=1 (Docker), URL=`unix:///var/run/docker.sock` (skip if endpoint already exists)

Steps 7-11 are idempotent — they check state before acting.

### Handlers (`handlers/main.yml`)

- **Restart portainer**: `docker_compose_v2` state: restarted

---

## 2. Caddy Update (`caddy/ansible/group_vars/caddy/all/main.yml`)

New backend entry added to `caddy_backends`:

```yaml
- name: portainer
  domain: portainer.internal
  upstream: http://192.168.1.90:9000
  tls_insecure_skip_verify: false
  tls_internal: false
```

Plain HTTP upstream — no TLS between Caddy and dockhost on the private LAN.

---

## 3. Pi-hole Update (`pihole/ansible/group_vars/pihole/all/main.yml`)

New DNS record added to `pihole_local_records`:

```yaml
- ip: 192.168.1.70
  domain: portainer.internal
```

Points to Caddy IP, same pattern as all `.internal` domains.

---

## 4. Dockhost Cleanup

### Removed

- `dockhost/ansible/roles/portainer_agent/` — entire directory deleted
- `security_portainer_agent` block from `group_vars/dockhost/all/main.yml`
- UFW port 9001 entry from `security_open_ports`

### Modified

- `deploy.yml` — replace `portainer_agent` role with `portainer` (tag: `portainer`)
- `group_vars/dockhost/all/main.yml` — add portainer variables section

### Added to Vault

- `vault_portainer_admin_username` — admin username
- `vault_portainer_admin_password` — admin password

---

## 5. Deployment Order

1. `cd dockhost && ansible-playbook ansible/deploy.yml --tags portainer` — deploy server + bootstrap API
2. `cd caddy && ansible-playbook ansible/deploy.yml --tags caddy` — add reverse proxy entry
3. `cd pihole && ansible-playbook ansible/deploy.yml --tags pihole` — add DNS record

After all three steps: `portainer.internal` is accessible through Caddy.

---

## Out of Scope

- TLS between Caddy and Portainer (private LAN, VPN-secured)
- Portainer Business Edition features
- Multi-host Portainer agent deployment
- Portainer LDAP/OAuth integration

> **Document created on**: 2026-04-03
> **Author**: Xavier Gueret
> **Version**: 1.0
