# Open WebUI on dockhost-90 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Open WebUI on dockhost-90 with PostgreSQL backend and Ollama on workstation, accessible at `openwebui.internal` via Caddy.

**Architecture:** New `open_webui` Ansible role in dockhost. Open WebUI connects to PostgreSQL via `db-net` Docker network and to Ollama on `192.168.1.101:11434` via LAN. Caddy (caddy-70) reverse proxies `openwebui.internal`, Pi-hole (dns-71) provides DNS.

**Tech Stack:** Ansible, Docker Compose, Open WebUI v0.8.3, PostgreSQL, Caddy, Pi-hole

**Spec:** `docs/superpowers/specs/2026-04-03-open-webui-design.md`

---

## File Map

### Created

| File | Responsibility |
|------|---------------|
| `dockhost/ansible/roles/open_webui/defaults/main.yml` | Image version, directories, port, DB config |
| `dockhost/ansible/roles/open_webui/tasks/main.yml` | PostgreSQL setup + deploy |
| `dockhost/ansible/roles/open_webui/templates/docker-compose.yml.j2` | Open WebUI compose definition |
| `dockhost/ansible/roles/open_webui/handlers/main.yml` | Restart handler |

### Modified

| File | Change |
|------|--------|
| `dockhost/ansible/deploy.yml` | Add `open_webui` role + tag `db-net` pre_task |
| `dockhost/ansible/group_vars/dockhost/all/main.yml` | Add open_webui vars + UFW port |
| `caddy/ansible/group_vars/caddy/all/main.yml` | Add `openwebui` backend |
| `pihole/ansible/group_vars/pihole/all/main.yml` | Add `openwebui.internal` DNS record |
| `dockhost/ansible/group_vars/dockhost/vault/config.yml` | Add vault secrets |

---

## Task 1: Create feature branch

- [ ] **Step 1: Create and switch to feature branch**

```bash
cd /home/xgueret/Workspace/02-infrastructure/homelab
git checkout main
git pull
git checkout -b feat/open-webui
```

- [ ] **Step 2: Verify branch**

Run: `git branch --show-current`
Expected: `feat/open-webui`

---

## Task 2: Create Open WebUI role — defaults and handler

**Files:**
- Create: `dockhost/ansible/roles/open_webui/defaults/main.yml`
- Create: `dockhost/ansible/roles/open_webui/handlers/main.yml`

- [ ] **Step 1: Create role directory structure**

```bash
mkdir -p dockhost/ansible/roles/open_webui/{defaults,tasks,templates,handlers}
```

- [ ] **Step 2: Write defaults/main.yml**

```yaml
---
# Image Docker Open WebUI
open_webui_image: "ghcr.io/open-webui/open-webui"
open_webui_image_tag: "v0.8.3"
open_webui_image_digest: "sha256:21c24dc456da582a365751803057cd25de9a24ee99e8ba9715b0184936ba7988"

# Repertoires sur l'hote
open_webui_install_dir: "/opt/open-webui"
open_webui_data_dir: "/app/data/open-webui"

# Port HTTP (accessible depuis le LAN prive, Caddy fait le reverse proxy)
open_webui_http_port: 8080
open_webui_bind_address: "0.0.0.0"

# Ollama backend (poste local sur le LAN)
open_webui_ollama_base_url: "http://192.168.1.101:11434"

# PostgreSQL (conteneur existant sur dockhost)
open_webui_db_container: "postgresql"
open_webui_db_name: "open_webui"
open_webui_db_user: "open_webui"
open_webui_db_superuser: "postgres"
```

- [ ] **Step 3: Write handlers/main.yml**

```yaml
---
- name: Restart open-webui
  community.docker.docker_compose_v2:
    project_src: "{{ open_webui_install_dir }}"
    state: restarted
  register: open_webui_restart_result
```

- [ ] **Step 4: Commit**

```bash
git add dockhost/ansible/roles/open_webui/defaults/main.yml \
        dockhost/ansible/roles/open_webui/handlers/main.yml
git commit -m "infra(open-webui): ajouter defaults et handler du role open_webui"
```

---

## Task 3: Create Open WebUI Docker Compose template

**Files:**
- Create: `dockhost/ansible/roles/open_webui/templates/docker-compose.yml.j2`

- [ ] **Step 1: Write docker-compose.yml.j2**

```yaml
{{ ansible_managed | comment }}

services:
  open-webui:
    image: {{ open_webui_image }}:{{ open_webui_image_tag }}@{{ open_webui_image_digest }}
    container_name: open-webui
    restart: always
    ports:
      - "{{ open_webui_bind_address }}:{{ open_webui_http_port }}:8080"
    environment:
      OLLAMA_BASE_URL: "{{ open_webui_ollama_base_url }}"
      DATABASE_URL: "{{ vault_open_webui_database_url }}"
      WEBUI_SECRET_KEY: "{{ vault_open_webui_secret_key }}"
    volumes:
      - "{{ open_webui_data_dir }}:/app/backend/data"
    networks:
      - db-net

networks:
  db-net:
    external: true
```

- [ ] **Step 2: Commit**

```bash
git add dockhost/ansible/roles/open_webui/templates/docker-compose.yml.j2
git commit -m "infra(open-webui): ajouter template docker-compose Open WebUI"
```

---

## Task 4: Create Open WebUI role — tasks (PostgreSQL setup + deploy)

**Files:**
- Create: `dockhost/ansible/roles/open_webui/tasks/main.yml`

- [ ] **Step 1: Write tasks/main.yml**

```yaml
---
# ============================================================
# PostgreSQL — creation user et base de donnees
# ============================================================
- name: Check if PostgreSQL user exists
  community.docker.docker_container_exec:
    container: "{{ open_webui_db_container }}"
    command: >-
      psql -U {{ open_webui_db_superuser }} -tAc
      "SELECT 1 FROM pg_roles WHERE rolname='{{ open_webui_db_user }}'"
  register: open_webui_pg_user_check
  changed_when: false

- name: Create PostgreSQL user for open_webui
  community.docker.docker_container_exec:
    container: "{{ open_webui_db_container }}"
    command: >-
      psql -U {{ open_webui_db_superuser }} -c
      "CREATE USER {{ open_webui_db_user }} WITH PASSWORD '{{ vault_open_webui_db_password }}';"
  no_log: true
  when: open_webui_pg_user_check.stdout | trim != "1"

- name: Check if PostgreSQL database exists
  community.docker.docker_container_exec:
    container: "{{ open_webui_db_container }}"
    command: >-
      psql -U {{ open_webui_db_superuser }} -tAc
      "SELECT 1 FROM pg_database WHERE datname='{{ open_webui_db_name }}'"
  register: open_webui_pg_db_check
  changed_when: false

- name: Create PostgreSQL database for open_webui
  community.docker.docker_container_exec:
    container: "{{ open_webui_db_container }}"
    command: >-
      psql -U {{ open_webui_db_superuser }} -c
      "CREATE DATABASE {{ open_webui_db_name }} OWNER {{ open_webui_db_user }} ENCODING 'UTF8';"
  when: open_webui_pg_db_check.stdout | trim != "1"

# ============================================================
# Deploiement Open WebUI
# ============================================================
- name: Create install directory
  ansible.builtin.file:
    path: "{{ open_webui_install_dir }}"
    state: directory
    owner: root
    group: root
    mode: '0755'

- name: Create data directory
  ansible.builtin.file:
    path: "{{ open_webui_data_dir }}"
    state: directory
    owner: root
    group: root
    mode: '0755'

- name: Copy docker compose file
  ansible.builtin.template:
    src: docker-compose.yml.j2
    dest: "{{ open_webui_install_dir }}/docker-compose.yml"
    owner: root
    group: root
    mode: '0600'
  notify: Restart open-webui

- name: Deploy open-webui with Docker Compose
  community.docker.docker_compose_v2:
    project_src: "{{ open_webui_install_dir }}"
    state: present
    recreate: auto
    remove_orphans: true

- name: Wait for Open WebUI to be ready
  ansible.builtin.uri:
    url: "http://localhost:{{ open_webui_http_port }}/"
    status_code: 200
  register: open_webui_ready
  retries: 10
  delay: 5
  until: open_webui_ready.status == 200
```

- [ ] **Step 2: Commit**

```bash
git add dockhost/ansible/roles/open_webui/tasks/main.yml
git commit -m "infra(open-webui): ajouter tasks deploiement et setup PostgreSQL"
```

---

## Task 5: Update dockhost deploy.yml and group_vars

**Files:**
- Modify: `dockhost/ansible/deploy.yml:25-27,43-44`
- Modify: `dockhost/ansible/group_vars/dockhost/all/main.yml:19,26`

- [ ] **Step 1: Update deploy.yml — add open-webui tag to db-net pre_task**

In `dockhost/ansible/deploy.yml`, add `open-webui` to the tags of the db-net pre_task (line 25-27):

Replace:

```yaml
      tags:
        - postgresql
        - kandidat
```

with:

```yaml
      tags:
        - postgresql
        - kandidat
        - open-webui
```

- [ ] **Step 2: Update deploy.yml — add open_webui role**

In `dockhost/ansible/deploy.yml`, after the `kandidat` role block (line 43-44), add:

```yaml
    - role: open_webui
      tags:
        - open-webui
```

- [ ] **Step 3: Update group_vars — add open_webui vars and UFW port**

In `dockhost/ansible/group_vars/dockhost/all/main.yml`, after the existing `security_open_ports` entries (line 19), add:

```yaml
  - { port: 8080, proto: tcp, comment: "Open WebUI" }
```

After the Portainer section (line 25), add:

```yaml

# ============================================================
# 🌐 Open WebUI - Role open_webui
# ============================================================
open_webui_ollama_base_url: "http://192.168.1.101:11434"
```

- [ ] **Step 4: Commit**

```bash
git add dockhost/ansible/deploy.yml \
        dockhost/ansible/group_vars/dockhost/all/main.yml
git commit -m "infra(open-webui): mettre a jour deploy.yml et group_vars pour role open_webui"
```

---

## Task 6: Add Caddy backend for openwebui.internal

**Files:**
- Modify: `caddy/ansible/group_vars/caddy/all/main.yml`

- [ ] **Step 1: Add openwebui backend to caddy_backends list**

In `caddy/ansible/group_vars/caddy/all/main.yml`, after the `pihole` backend entry, add:

```yaml
  - name: openwebui
    domain: openwebui.internal
    upstream: http://192.168.1.90:8080
    tls_insecure_skip_verify: false
```

- [ ] **Step 2: Commit**

```bash
git add caddy/ansible/group_vars/caddy/all/main.yml
git commit -m "infra(caddy): ajouter backend openwebui.internal"
```

---

## Task 7: Add Pi-hole DNS record for openwebui.internal

**Files:**
- Modify: `pihole/ansible/group_vars/pihole/all/main.yml`

- [ ] **Step 1: Add DNS record to pihole_local_records**

In `pihole/ansible/group_vars/pihole/all/main.yml`, after the `pihole.internal` entry, add:

```yaml
  - ip: 192.168.1.70
    domain: openwebui.internal
```

- [ ] **Step 2: Commit**

```bash
git add pihole/ansible/group_vars/pihole/all/main.yml
git commit -m "infra(pihole): ajouter enregistrement DNS openwebui.internal"
```

---

## Task 8: Add Open WebUI credentials to Ansible Vault

**Files:**
- Modify: `dockhost/ansible/group_vars/dockhost/vault/config.yml` (encrypted)

- [ ] **Step 1: Edit vault file to add Open WebUI secrets**

```bash
cd /home/xgueret/Workspace/02-infrastructure/homelab
ansible-vault edit dockhost/ansible/group_vars/dockhost/vault/config.yml
```

Add these variables (choose strong passwords):

```yaml
vault_open_webui_db_password: "<strong-password>"
vault_open_webui_secret_key: "<random-secret-key>"
vault_open_webui_database_url: "postgresql+psycopg://open_webui:<same-password>@postgresql:5432/open_webui"
```

Note: the `@postgresql` hostname works because Open WebUI and PostgreSQL share the `db-net` Docker network.

- [ ] **Step 2: Commit**

```bash
git add dockhost/ansible/group_vars/dockhost/vault/config.yml
git commit -m "infra(open-webui): ajouter credentials dans le vault"
```

---

## Task 9: Lint and validate

- [ ] **Step 1: Run ansible-lint on dockhost**

```bash
ansible-lint dockhost/ansible/
```

Expected: no errors on the open_webui role files.

- [ ] **Step 2: Run pre-commit on all changed files**

```bash
pre-commit run --all-files
```

Expected: all checks pass.

- [ ] **Step 3: Fix any lint issues and commit**

If issues found, fix and commit:

```bash
git add -A
git commit -m "chore(open-webui): corriger erreurs lint"
```

---

## Deployment Checklist (post-merge, manual)

1. `cd dockhost && ansible-playbook ansible/deploy.yml --tags open-webui`
2. `cd pihole && ansible-playbook ansible/deploy.yml --tags pihole`
3. `cd caddy && ansible-playbook ansible/deploy.yml --tags caddy`
4. Verify: open `http://openwebui.internal` in browser (via VPN)
5. Verify: Ollama models visible in Open WebUI settings
