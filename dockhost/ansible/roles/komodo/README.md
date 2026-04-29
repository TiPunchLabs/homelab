# Role: komodo

Deploy [Komodo](https://komo.do) Core + MongoDB + Periphery on dockhost
(all three containers on the same host for the POC).

## Mental Model

```
┌──────────────────────────────────────────────────────────┐
│ dockhost                                                 │
│                                                          │
│  ┌─────────┐   ws://core:9120   ┌──────────────────┐     │
│  │  Core   │◀──────────────────▶│    Periphery     │     │
│  │  :9120  │                    │  (docker agent)  │     │
│  └─────────┘                    └──────────────────┘     │
│       │                                   │              │
│       │ mongo:27017                       │ docker.sock  │
│       ▼                                   ▼              │
│  ┌─────────┐                    ┌──────────────────┐     │
│  │  Mongo  │                    │ /var/run/docker  │     │
│  └─────────┘                    └──────────────────┘     │
│                                                          │
│  /etc/komodo/ ← Periphery root (stacks + cloned repos)   │
└──────────────────────────────────────────────────────────┘
```

## Required Vault secrets

Add to `homelab/dockhost/ansible/group_vars/dockhost/vault/config.yml`:

```yaml
vault_komodo_db_password: "..."          # MongoDB root password
vault_komodo_admin_password: "..."       # First admin user (username: admin)
vault_komodo_webhook_secret: "..."       # HMAC secret for Git webhook auth
vault_komodo_jwt_secret: "..."           # JWT signing secret
```

Generate them with:

```bash
openssl rand -base64 32
```

## Playbook usage

```yaml
- hosts: dockhost
  become: true
  roles:
    - komodo
```

Override defaults in `group_vars/dockhost.yml` if needed (e.g., `komodo_host`).

## POC — pedagogical checklist

After `ansible-playbook` succeeds, log in to `http://dockhost:9120`
with `admin` / `{{ vault_komodo_admin_password }}` and run each scenario in order.

### Scenario 1 — Initial sync (manual)

- [ ] In Komodo UI, check that Server **dockhost** is connected (green)
- [ ] Add a Git provider: GitLab → paste a read-only deploy token for `homelab-gitops`
- [ ] Create Stack **poc-hello**:
      - Repo: `homelab-gitops`
      - File path: `poc-hello/compose.yaml`
      - Auto-sync: **OFF** for this step
- [ ] Click *Deploy* manually → container `poc-hello-whoami` starts
- [ ] Verify: `curl http://dockhost:8090` returns `Hostname: poc-hello-whoami`

**Learning**: Git holds the desired state; Komodo applies it on demand.

### Scenario 2 — Auto-sync on commit

- [ ] Toggle Stack's *Auto-sync* **ON** (poll interval: 1 min for POC)
- [ ] In the repo, edit `poc-hello/compose.yaml`, change `WHOAMI_NAME: "hello-auto-sync"`
- [ ] `git commit -am "..."` + `git push`
- [ ] Wait ≤ 1 min → Komodo UI shows new commit SHA, redeploys
- [ ] `curl http://dockhost:8090` → new `WHOAMI_NAME` visible

**Learning**: commit = deployment trigger, no CI push needed.

### Scenario 3 — Container killed (live-state drift)

- [ ] On dockhost: `docker stop poc-hello-whoami`
- [ ] Komodo Stack page shows container as *exited* / *unhealthy*
- [ ] Depending on config, Komodo either alerts or redeploys

**Learning**: Komodo observes live state continuously, not just at sync time.

### Scenario 4 — Manual file edit on host (config drift)

- [ ] On dockhost: `vim /etc/komodo/stacks/poc-hello/compose.yaml` → change a port
- [ ] In Komodo UI: Stack marked **Unsynced** (Git ≠ disk)
- [ ] Click *Sync* → Komodo overwrites the local edit with the Git version

**Learning**: ad-hoc edits are ephemeral; Git always wins.

### Scenario 5 — Rollback via `git revert`

- [ ] `git log` → find the commit from scenario 2
- [ ] `git revert <sha>` → push
- [ ] Komodo redeploys the previous env var

**Learning**: rollback is a commit, not a separate procedure.

### Scenario 6 — Webhook (instant sync)

- [ ] In GitLab repo Settings → Webhooks → add:
      URL: `http://dockhost:9120/listener/gitlab/<stack-id>`
      Token: `{{ vault_komodo_webhook_secret }}`
      Trigger: push
- [ ] Commit + push → Komodo syncs within seconds (not the 1-min poll)

**Learning**: pulling can be pushed-to-notify; the agent still pulls, but doesn't wait.

### Cleanup

- [ ] Stack **poc-hello** → Destroy from UI
- [ ] Keep `poc-hello/` folder in repo as reference for future docs
