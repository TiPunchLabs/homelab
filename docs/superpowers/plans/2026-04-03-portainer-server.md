# Portainer Server on dockhost-90 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Portainer CE Server on dockhost-90 with automated API bootstrap, accessible at `portainer.internal` via Caddy reverse proxy.

**Architecture:** New `portainer` Ansible role replaces `portainer_agent`. Portainer Server listens on `127.0.0.1:9000`, Caddy (caddy-70) reverse proxies `portainer.internal` to it, Pi-hole (dns-71) provides DNS resolution. Admin account and local Docker endpoint are bootstrapped via Portainer API post-deploy.

**Tech Stack:** Ansible, Docker Compose, Portainer CE 2.27.4, Caddy, Pi-hole

**Spec:** `docs/superpowers/specs/2026-04-03-portainer-server-design.md`

---

## File Map

### Created

| File | Responsibility |
|------|---------------|
| `dockhost/ansible/roles/portainer/defaults/main.yml` | Image version, directories, port defaults |
| `dockhost/ansible/roles/portainer/tasks/main.yml` | Deploy + cleanup old agent + API bootstrap |
| `dockhost/ansible/roles/portainer/templates/docker-compose.yml.j2` | Portainer CE Server compose definition |
| `dockhost/ansible/roles/portainer/handlers/main.yml` | Restart handler |

### Modified

| File | Change |
|------|--------|
| `dockhost/ansible/deploy.yml` | Replace `portainer_agent` role with `portainer` |
| `dockhost/ansible/group_vars/dockhost/all/main.yml` | Remove `security_portainer_agent`, add portainer vars |
| `caddy/ansible/group_vars/caddy/all/main.yml` | Add `portainer` backend to `caddy_backends` |
| `pihole/ansible/group_vars/pihole/all/main.yml` | Add `portainer.internal` DNS record |

### Deleted

| File | Reason |
|------|--------|
| `dockhost/ansible/roles/portainer_agent/` | Replaced by `portainer` role |

---

## Task 1: Create feature branch

- [ ] **Step 1: Create and switch to feature branch**

```bash
cd /home/xgueret/Workspace/02-infrastructure/homelab
git checkout -b feat/portainer-server
```

- [ ] **Step 2: Verify branch**

Run: `git branch --show-current`
Expected: `feat/portainer-server`

---

## Task 2: Create Portainer role — defaults and handler

**Files:**
- Create: `dockhost/ansible/roles/portainer/defaults/main.yml`
- Create: `dockhost/ansible/roles/portainer/handlers/main.yml`

- [ ] **Step 1: Create role directory structure**

```bash
mkdir -p dockhost/ansible/roles/portainer/{defaults,tasks,templates,handlers}
```

- [ ] **Step 2: Write defaults/main.yml**

```yaml
---
# Image Docker Portainer CE
portainer_image: "portainer/portainer-ce"
portainer_image_tag: "2.27.4"
portainer_image_digest: "sha256:e65b9b55c16c32f6abcbd1440a4fff020739973f0e41d6a99088d200a6014bfe"

# Repertoires sur l'hote
portainer_install_dir: "/opt/portainer"
portainer_data_dir: "/app/data/portainer"

# Port HTTP (bind localhost uniquement, Caddy fait le reverse proxy)
portainer_http_port: 9000
portainer_bind_address: "127.0.0.1"

# API base URL (utilise par les tasks de bootstrap)
portainer_api_url: "http://localhost:{{ portainer_http_port }}/api"
```

- [ ] **Step 3: Write handlers/main.yml**

```yaml
---
- name: Restart portainer
  community.docker.docker_compose_v2:
    project_src: "{{ portainer_install_dir }}"
    state: restarted
  register: portainer_restart_result
```

- [ ] **Step 4: Commit**

```bash
git add dockhost/ansible/roles/portainer/defaults/main.yml \
        dockhost/ansible/roles/portainer/handlers/main.yml
git commit -m "infra(portainer): ajouter defaults et handler du role portainer"
```

---

## Task 3: Create Portainer Docker Compose template

**Files:**
- Create: `dockhost/ansible/roles/portainer/templates/docker-compose.yml.j2`

- [ ] **Step 1: Write docker-compose.yml.j2**

```yaml
services:
  portainer:
    image: {{ portainer_image }}:{{ portainer_image_tag }}@{{ portainer_image_digest }}
    container_name: portainer
    restart: always
    ports:
      - "{{ portainer_bind_address }}:{{ portainer_http_port }}:9000"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock"
      - "{{ portainer_data_dir }}:/data"
    networks:
      - vm-docker-90-net

networks:
  vm-docker-90-net:
    driver: bridge
```

- [ ] **Step 2: Commit**

```bash
git add dockhost/ansible/roles/portainer/templates/docker-compose.yml.j2
git commit -m "infra(portainer): ajouter template docker-compose Portainer CE"
```

---

## Task 4: Create Portainer role — tasks (deploy + API bootstrap)

**Files:**
- Create: `dockhost/ansible/roles/portainer/tasks/main.yml`

- [ ] **Step 1: Write tasks/main.yml**

```yaml
---
# ============================================================
# Nettoyage ancien portainer_agent
# ============================================================
- name: Check if old portainer agent compose file exists
  ansible.builtin.stat:
    path: /opt/portainer/agent/docker-compose.yml
  register: portainer_agent_compose

- name: Tear down old portainer agent stack
  community.docker.docker_compose_v2:
    project_src: /opt/portainer/agent
    state: absent
    remove_orphans: true
  when: portainer_agent_compose.stat.exists

- name: Remove old portainer agent directory
  ansible.builtin.file:
    path: /opt/portainer/agent
    state: absent
  when: portainer_agent_compose.stat.exists

# ============================================================
# Deploiement Portainer CE Server
# ============================================================
- name: Create install directory
  ansible.builtin.file:
    path: "{{ portainer_install_dir }}"
    state: directory
    owner: root
    group: root
    mode: '0755'

- name: Create data directory
  ansible.builtin.file:
    path: "{{ portainer_data_dir }}"
    state: directory
    owner: root
    group: root
    mode: '0755'

- name: Copy docker compose file
  ansible.builtin.template:
    src: docker-compose.yml.j2
    dest: "{{ portainer_install_dir }}/docker-compose.yml"
    owner: root
    group: root
    mode: '0644'
  notify: Restart portainer

- name: Deploy portainer with Docker Compose
  community.docker.docker_compose_v2:
    project_src: "{{ portainer_install_dir }}"
    state: present
    recreate: auto
    remove_orphans: true
  register: portainer_deploy

- name: Wait for Portainer API to be ready
  ansible.builtin.uri:
    url: "{{ portainer_api_url }}/status"
    method: GET
    status_code: 200
  register: portainer_status
  retries: 10
  delay: 3
  until: portainer_status.status == 200

# ============================================================
# Bootstrap API — Admin user
# ============================================================
- name: Check if admin user already exists
  ansible.builtin.uri:
    url: "{{ portainer_api_url }}/users/admin/check"
    method: GET
    status_code: [200, 204, 404]
  register: portainer_admin_check

- name: Create admin user
  ansible.builtin.uri:
    url: "{{ portainer_api_url }}/users/admin/init"
    method: POST
    body_format: json
    body:
      username: "{{ vault_portainer_admin_username }}"
      password: "{{ vault_portainer_admin_password }}"
    status_code: 200
  when: portainer_admin_check.status == 404

# ============================================================
# Bootstrap API — Local Docker endpoint
# ============================================================
- name: Authenticate to Portainer API
  ansible.builtin.uri:
    url: "{{ portainer_api_url }}/auth"
    method: POST
    body_format: json
    body:
      username: "{{ vault_portainer_admin_username }}"
      password: "{{ vault_portainer_admin_password }}"
    status_code: 200
  register: portainer_auth

- name: Get existing endpoints
  ansible.builtin.uri:
    url: "{{ portainer_api_url }}/endpoints"
    method: GET
    headers:
      Authorization: "Bearer {{ portainer_auth.json.jwt }}"
    status_code: 200
  register: portainer_endpoints

- name: Register local Docker endpoint
  ansible.builtin.uri:
    url: "{{ portainer_api_url }}/endpoints"
    method: POST
    headers:
      Authorization: "Bearer {{ portainer_auth.json.jwt }}"
    body_format: form-urlencoded
    body:
      Name: "dockhost-90"
      EndpointCreationType: "1"
      URL: "unix:///var/run/docker.sock"
    status_code: 200
  when: portainer_endpoints.json | length == 0
```

- [ ] **Step 2: Commit**

```bash
git add dockhost/ansible/roles/portainer/tasks/main.yml
git commit -m "infra(portainer): ajouter tasks deploiement et bootstrap API"
```

---

## Task 5: Update dockhost deploy.yml and group_vars

**Files:**
- Modify: `dockhost/ansible/deploy.yml:36-38`
- Modify: `dockhost/ansible/group_vars/dockhost/all/main.yml:21-25`

- [ ] **Step 1: Update deploy.yml — replace portainer_agent with portainer**

In `dockhost/ansible/deploy.yml`, replace lines 36-38:

```yaml
    - role: portainer_agent
      tags:
        - portainer-agent
```

with:

```yaml
    - role: portainer
      tags:
        - portainer
```

- [ ] **Step 2: Update group_vars — remove security_portainer_agent, add portainer vars**

In `dockhost/ansible/group_vars/dockhost/all/main.yml`, replace lines 21-25:

```yaml
security_portainer_agent:
  enabled: true
  manager_ip: "{{ vault_portainer_manager_ip }}"
  port: 9001
```

with:

```yaml
# ============================================================
# 🐳 Portainer CE - Role portainer
# ============================================================
portainer_admin_username: "{{ vault_portainer_admin_username }}"
portainer_admin_password: "{{ vault_portainer_admin_password }}"
```

- [ ] **Step 3: Commit**

```bash
git add dockhost/ansible/deploy.yml \
        dockhost/ansible/group_vars/dockhost/all/main.yml
git commit -m "infra(portainer): mettre a jour deploy.yml et group_vars pour role portainer"
```

---

## Task 6: Delete old portainer_agent role

**Files:**
- Delete: `dockhost/ansible/roles/portainer_agent/` (entire directory)

- [ ] **Step 1: Remove portainer_agent role directory**

```bash
trash dockhost/ansible/roles/portainer_agent
```

- [ ] **Step 2: Verify removal**

Run: `ls dockhost/ansible/roles/portainer_agent 2>&1`
Expected: `No such file or directory`

- [ ] **Step 3: Commit**

```bash
git add dockhost/ansible/roles/portainer_agent
git commit -m "infra(portainer): supprimer ancien role portainer_agent"
```

---

## Task 7: Add Caddy backend for portainer.internal

**Files:**
- Modify: `caddy/ansible/group_vars/caddy/all/main.yml:30`

- [ ] **Step 1: Add portainer backend to caddy_backends list**

In `caddy/ansible/group_vars/caddy/all/main.yml`, after the `vpngate` backend entry (line 30), add:

```yaml
  - name: portainer
    domain: portainer.internal
    upstream: http://192.168.1.90:9000
    tls_insecure_skip_verify: false
```

This follows the same pattern as `kandidat` and `vpngate` — plain HTTP, no `tls_internal` (defaults to `false` in the Caddyfile template, so port 80).

- [ ] **Step 2: Commit**

```bash
git add caddy/ansible/group_vars/caddy/all/main.yml
git commit -m "infra(caddy): ajouter backend portainer.internal"
```

---

## Task 8: Add Pi-hole DNS record for portainer.internal

**Files:**
- Modify: `pihole/ansible/group_vars/pihole/all/main.yml:27`

- [ ] **Step 1: Add DNS record to pihole_local_records**

In `pihole/ansible/group_vars/pihole/all/main.yml`, after the `vpngate.internal` entry (line 27), add:

```yaml
  - ip: 192.168.1.70
    domain: portainer.internal
```

- [ ] **Step 2: Commit**

```bash
git add pihole/ansible/group_vars/pihole/all/main.yml
git commit -m "infra(pihole): ajouter enregistrement DNS portainer.internal"
```

---

## Task 9: Add Portainer credentials to Ansible Vault

**Files:**
- Modify: `dockhost/ansible/group_vars/dockhost/vault/config.yml` (encrypted)

- [ ] **Step 1: Edit vault file to add Portainer admin credentials**

```bash
cd /home/xgueret/Workspace/02-infrastructure/homelab
ansible-vault edit dockhost/ansible/group_vars/dockhost/vault/config.yml
```

Add these two variables (choose a strong password):

```yaml
vault_portainer_admin_username: "admin"
vault_portainer_admin_password: "<strong-password-here>"
```

Remove the now-unused `vault_portainer_manager_ip` variable.

- [ ] **Step 2: Commit**

```bash
git add dockhost/ansible/group_vars/dockhost/vault/config.yml
git commit -m "infra(portainer): ajouter credentials admin dans le vault"
```

---

## Task 10: Lint and validate

- [ ] **Step 1: Run ansible-lint on dockhost**

```bash
ansible-lint dockhost/ansible/
```

Expected: no errors on the portainer role files.

- [ ] **Step 2: Run ansible-lint on caddy**

```bash
ansible-lint caddy/ansible/
```

Expected: no errors.

- [ ] **Step 3: Run ansible-lint on pihole**

```bash
ansible-lint pihole/ansible/
```

Expected: no errors.

- [ ] **Step 4: Run pre-commit on all changed files**

```bash
pre-commit run --all-files
```

Expected: all checks pass.

- [ ] **Step 5: Fix any lint issues and commit**

If issues found, fix and commit:

```bash
git add -A
git commit -m "chore(portainer): corriger erreurs lint"
```

---

## Deployment Checklist (post-merge, manual)

These are run manually after the branch is merged to main:

1. `cd dockhost && ansible-playbook ansible/deploy.yml --tags portainer`
2. `cd pihole && ansible-playbook ansible/deploy.yml --tags pihole`
3. `cd caddy && ansible-playbook ansible/deploy.yml --tags caddy`
4. Verify: open `http://portainer.internal` in browser (via VPN)
