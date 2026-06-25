# kandidat — Migration Ansible → full GitOps (Komodo) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kandidat` a 100 % GitOps deployment driven by Komodo (no Ansible deploy role), with `https://kandidat.internal` up and verifiable, and **zero data loss** (DB dump/restore + reused host bind mount for files).

**Architecture:** kandidat becomes a self-contained Komodo Stack (`kandidat/compose.yaml` in the GitLab repo `tipunchlabs/homelab-gitops`): the app container + its **own dedicated** `postgres:16`. The kandidat CI loses its Ansible `deploy` stage and gains a `bump` stage that opens an auto-merged MR on the GitOps repo (tag → `$SHA`); a CI job in `homelab-gitops` then triggers Komodo to redeploy by calling its `/listener` endpoint from the **internal self-hosted runner** (`bastion-60`) — Komodo is never exposed to the Internet. Caddy + Pi-hole (shared infra) are untouched.

**Tech Stack:** Docker Compose, Komodo (Core + Periphery), GitLab CI, PostgreSQL 16, Terraform (GitLab provider), Ansible (cleanup only).

## Global Constraints

- **Language:** English everywhere in code/files/comments (per user CLAUDE.md). The design spec is in French; produced artifacts and commit messages are English.
- **No data loss:** prod DB must be `pg_dump`'d before any teardown and `pg_restore`'d into the dedicated DB; file data (`/app/data/kandidat/candidatures/*.md`) preserved by reusing the host bind mount. Never delete `/app/data/kandidat`.
- **Branch protection:** `main` on `tipunchlabs/homelab-gitops` is **MR-only, no force-push**. All writes go through a branch + MR.
- **Secrets:** never commit secrets. `compose.yaml` references `${SECRET_KEY}` / `${DB_PASSWORD}` interpolated by Komodo Core. `.env.example` holds placeholders only.
- **Commits:** Conventional Commits. **Never auto-commit** without the user asking — each task's commit step is executed only on the user's go (the plan shows the exact command).
- **Deletions:** use `trash`, never `rm -rf`; confirm before deleting.
- **kandidat image registry:** `registry.gitlab.com/tipunchlabs/kandidat`.
- **homelab-gitops project id:** `81629969`.
- **dockhost:** `192.168.10.90`; shared postgres container name = `postgresql`; kandidat published port `8000`.

---

## Phase overview

| Phase | What | Who | Reversible? |
|---|---|---|---|
| **1. Artefacts** | Create GitOps files + rewrite CI `deploy`→`bump` (committed, not yet deployed) | 🤖 Claude | Yes (git) |
| **2. Bascule** | Backup → push repo → create Stack → runner trigger → cutover → restore → verify | 👤 **TOI** (detailed runbook) | Backup makes it safe |
| **3. Cleanup** | Remove Ansible kandidat role + vault keys, fix docs | 🤖 Claude + 👤 push/vault | Yes (git) — do **after** Phase 2 verified |

> **Legend used throughout:** **👤 TOI** = manual action you perform (exact command / UI clicks / expected output given). **🤖 CLAUDE** = file changes in a repo. **⚙️ AUTO** = Komodo/CI triggers it.

---

# PHASE 1 — Artefacts (🤖 CLAUDE)

These tasks only create/modify files in working copies and commit them. **Nothing is deployed** until Phase 2. Phase 1 is safe to do up front.

---

### Task 1: GitOps Stack files for kandidat

**Files:**
- Create: `02-infrastructure/homelab-gitops/kandidat/compose.yaml`
- Create: `02-infrastructure/homelab-gitops/kandidat/.env.example`

**Interfaces:**
- Produces: a Komodo file-based Stack at path `kandidat/compose.yaml` consuming Komodo secrets `SECRET_KEY` and `DB_PASSWORD`. Service `kandidat` listens on host `8000`; service `db` is reachable in-stack as host `db:5432`, database/user/password = `kandidat`/`kandidat`/`${DB_PASSWORD}`.

- [ ] **Step 1: Write `compose.yaml`**

```yaml
# kandidat — FastAPI/Flask app + dedicated PostgreSQL. Komodo file-based Stack.
#
# Internal URL : https://kandidat.internal  (via Caddy -> http://192.168.10.90:8000)
# State        : PostgreSQL in a dedicated container (volume kandidat-db) +
#                markdown files on a host bind mount (/app/data/kandidat).
#
# Secrets are NOT stored here. They live in Komodo Core (UI -> Settings -> Secrets)
# and are interpolated as ${VAR} at deploy time. See .env.example for the full list.

services:
  kandidat:
    image: registry.gitlab.com/tipunchlabs/kandidat:main
    container_name: kandidat
    restart: always
    ports:
      - "8000:8000"
    environment:
      SECRET_KEY: "${SECRET_KEY}"
      KANDIDAT_ENV: "prod"
      FT_DATA_DIR: "/app/data"
      DATABASE_URL: "postgresql://kandidat:${DB_PASSWORD}@db:5432/kandidat"
    volumes:
      # Reused host bind mount — preserves existing candidatures/*.md across the cutover.
      - "/app/data/kandidat:/app/data"
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    networks:
      - kandidat-net

  db:
    image: postgres:16
    container_name: kandidat-db
    restart: always
    environment:
      POSTGRES_DB: "kandidat"
      POSTGRES_USER: "kandidat"
      POSTGRES_PASSWORD: "${DB_PASSWORD}"
    volumes:
      - "kandidat-db:/var/lib/postgresql/data"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U kandidat -d kandidat"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - kandidat-net

volumes:
  kandidat-db:

networks:
  kandidat-net:
    name: kandidat-net
```

- [ ] **Step 2: Write `.env.example`**

```bash
# kandidat Komodo Stack — secret placeholders.
# Real values live in Komodo Core (Settings -> Secrets), NOT in git.
SECRET_KEY=replace-me-flask-secret-key
DB_PASSWORD=replace-me-postgres-password
```

- [ ] **Step 3: Validate YAML syntax**

Run: `yq '.services | keys' 02-infrastructure/homelab-gitops/kandidat/compose.yaml`
Expected: a list containing `kandidat` and `db`.

- [ ] **Step 4: Commit** (on user's go)

```bash
cd 02-infrastructure/homelab-gitops
git add kandidat/compose.yaml kandidat/.env.example
git commit -m "feat(kandidat): add GitOps Stack (app + dedicated postgres)"
```

> ⚠️ Note: this repo working copy is not yet a git clone of the remote — Phase 2 Task 6 sets that up. If `git` isn't initialized yet when running Phase 1, defer this commit to Phase 2 Task 6 (the files are created now regardless).

---

### Task 2: GitOps repo READMEs + correct the ecosystem docs

**Files:**
- Create/rewrite: `02-infrastructure/homelab-gitops/kandidat/README.md`
- Create: `02-infrastructure/homelab-gitops/README.md`
- Modify: `02-infrastructure/CLAUDE.md` (apps table row for kandidat)

**Interfaces:**
- Consumes: nothing.
- Produces: accurate docs reflecting kandidat = file-based GitOps Stack.

- [ ] **Step 1: Rewrite `kandidat/README.md`**

```markdown
# kandidat — GitOps Stack (Komodo, file-based)

**Status**: Active. kandidat is deployed on `dockhost` and reconciled by Komodo
Periphery from this repo. The Stack is **file-based**: its source of truth is
`kandidat/compose.yaml` here in git.

## What this Stack runs

- `kandidat` — the app (image `registry.gitlab.com/tipunchlabs/kandidat:<tag>`),
  published on host port `8000`, fronted by Caddy at `https://kandidat.internal`.
- `db` — a **dedicated** `postgres:16` (volume `kandidat-db`). Not shared.

## Data

- **Database**: dedicated postgres, volume `kandidat-db`.
- **Files**: candidatures markdown live on the host bind mount
  `/app/data/kandidat` (reused from the previous Ansible deployment).

## Secrets

`SECRET_KEY` and `DB_PASSWORD` are defined in Komodo Core (Settings -> Secrets)
and interpolated at deploy time. See `.env.example`.

## How it updates

The app repo (`tipunchlabs/kandidat`) CI `bump` stage opens an auto-merged MR
here that pins `services.kandidat.image` to the freshly built `:$SHA`. A Komodo
push-webhook then redeploys. Rollback = `git revert` the bump commit.

## Source

- Application code: [`../../01-projets/tipunchlabs/kandidat/`](../../01-projets/tipunchlabs/kandidat/)
  (out of scope of this repo — listed only as the downstream consumer).
```

- [ ] **Step 2: Create root `README.md`**

```markdown
# homelab-gitops

GitOps source of truth for workloads deployed on `dockhost` (192.168.10.90) by
**Komodo Periphery**. Each subdirectory is a Komodo Stack: a `compose.yaml`
(+ optional `.env.example`). Komodo pulls this repo and reconciles state;
`git` is the source of truth, rollback = `git revert`.

## Stacks

| Stack | Description | Status |
|---|---|---|
| [`kandidat/`](kandidat/) | Job-application manager (app + dedicated postgres) | Active |

## Conventions

- Secrets are **never** committed. They live in Komodo Core (Settings -> Secrets)
  and are interpolated as `${VAR}` at deploy time. Each Stack ships a
  `.env.example` listing the required variable names.
- `main` is protected (MR-only). Changes land via branch + merge request.

## Related

- Repo + deploy token + webhook are provisioned by
  [`../terraform/homelab-gitops/`](../terraform/homelab-gitops/).
```

- [ ] **Step 3: Correct the kandidat row in `02-infrastructure/CLAUDE.md`**

Find the apps table row for `kandidat` and set its manifest/status to file-based GitOps:

```markdown
| `kandidat` | [`../01-projets/tipunchlabs/kandidat/`](../01-projets/tipunchlabs/kandidat/) | `homelab-gitops/kandidat/compose.yaml` (file-based Komodo Stack) | Active |
```

Also update the coordination note if present so it no longer says kandidat is a UI-defined Stack.

- [ ] **Step 4: Verify no stale "UI Stack" / "Ansible" claims remain for kandidat**

Run: `grep -rn "UI Stack\|UI-defined\|Ansible" 02-infrastructure/CLAUDE.md 02-infrastructure/homelab-gitops/kandidat/README.md`
Expected: no line describing kandidat as UI-defined or Ansible-deployed.

- [ ] **Step 5: Commit** (on user's go)

```bash
cd 02-infrastructure
git add homelab-gitops/README.md homelab-gitops/kandidat/README.md CLAUDE.md
git commit -m "docs(kandidat): describe file-based GitOps Stack, fix apps table"
```

---

### Task 3: kandidat CI — drop Ansible `deploy`, add `bump`

**Files:**
- Modify: `01-projets/tipunchlabs/kandidat/.gitlab-ci.yml`

**Interfaces:**
- Consumes: CI vars `CI_REGISTRY_IMAGE`, `CI_COMMIT_SHORT_SHA`, `CI_API_V4_URL`, and **new** masked vars `HOMELAB_GITOPS_TOKEN` (write_repository + api on project `81629969`) and `HOMELAB_GITOPS_PROJECT_ID=81629969`.
- Produces: on every push to `main`, after `build` pushes `:$SHA`, an auto-merged MR on homelab-gitops pinning `services.kandidat.image` to `:$SHA`.

- [ ] **Step 1: Remove the `deploy` stage from `stages:`**

Change the `stages:` list (lines 1-7) to:

```yaml
stages:
  - lint
  - test
  - security
  - build
  - release
  - bump
```

- [ ] **Step 2: Delete the entire `deploy:` job**

Remove the whole block (current lines ~112-132, from the `# Deploy` comment header through the end of the `deploy:` job, including its `tags: [bastion]`, `script` Ansible call, `environment`, and `rules`).

- [ ] **Step 3: Add the `bump` job** (append at end of file)

```yaml
# =============================================================================
# Bump — pin the new image SHA in the GitOps repo via an auto-merged MR
# =============================================================================
bump:
  stage: bump
  image: alpine:3.20
  cache: {}
  before_script:
    - apk add --no-cache git curl yq
    - yq --version  # ensure mikefarah/yq (Go), which supports the `.path = "x"` set syntax
  script:
    - |
      set -euo pipefail
      GITOPS_HOST="gitlab.com"
      GITOPS_API_URL="https://${GITOPS_HOST}/api/v4"
      GITOPS_PATH="tipunchlabs/homelab-gitops"
      BRANCH="bump/kandidat-${CI_COMMIT_SHORT_SHA}"
      NEW_IMAGE="${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHORT_SHA}"

      git clone "https://oauth2:${HOMELAB_GITOPS_TOKEN}@${GITOPS_HOST}/${GITOPS_PATH}.git" gitops
      cd gitops
      git config user.email "ci@tipunchlabs"
      git config user.name "kandidat-ci"
      git checkout -b "${BRANCH}"

      # Guard: never create a broken stub — the compose file must already exist.
      test -f kandidat/compose.yaml || { echo "ERROR: kandidat/compose.yaml missing in homelab-gitops"; exit 1; }

      yq -i ".services.kandidat.image = \"${NEW_IMAGE}\"" kandidat/compose.yaml
      git add kandidat/compose.yaml

      if git diff --cached --quiet; then
        echo "Image already at ${NEW_IMAGE}, nothing to bump."; exit 0
      fi

      git commit -m "chore(kandidat): bump image to ${CI_COMMIT_SHORT_SHA}"
      git push origin "${BRANCH}"

      # Open the MR with auto-remove of the source branch.
      MR=$(curl -sf --request POST \
        --header "PRIVATE-TOKEN: ${HOMELAB_GITOPS_TOKEN}" \
        "${GITOPS_API_URL}/projects/${HOMELAB_GITOPS_PROJECT_ID}/merge_requests" \
        --data "source_branch=${BRANCH}" \
        --data "target_branch=main" \
        --data "remove_source_branch=true" \
        --data "title=chore(kandidat): bump image to ${CI_COMMIT_SHORT_SHA}")
      IID=$(echo "$MR" | yq -p=json '.iid')

      # Merge with a small retry — GitLab may need a moment to mark the MR mergeable
      # (main is MR-only; the token merges via API — no pipeline on the gitops repo).
      for attempt in 1 2 3; do
        if curl -sf --request PUT \
          --header "PRIVATE-TOKEN: ${HOMELAB_GITOPS_TOKEN}" \
          "${GITOPS_API_URL}/projects/${HOMELAB_GITOPS_PROJECT_ID}/merge_requests/${IID}/merge" \
          --data "should_remove_source_branch=true"; then
          echo "Merged MR !${IID} -> kandidat pinned to ${CI_COMMIT_SHORT_SHA}"; exit 0
        fi
        echo "Merge attempt ${attempt} failed, retrying in 5s..."; sleep 5
      done
      echo "ERROR: could not merge MR !${IID} after 3 attempts"; exit 1
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: on_success
```

- [ ] **Step 4: Validate the CI YAML**

Run: `yq '.stages, (.bump.stage)' 01-projets/tipunchlabs/kandidat/.gitlab-ci.yml`
Expected: stages list ends with `bump`; `.bump.stage` == `bump`. Confirm no `deploy:` key remains:
Run: `yq 'has("deploy")' 01-projets/tipunchlabs/kandidat/.gitlab-ci.yml` → `false`.

- [ ] **Step 5: Commit** (on user's go)

```bash
cd 01-projets/tipunchlabs/kandidat
git add .gitlab-ci.yml
git commit -m "ci: replace Ansible deploy with GitOps bump (auto-merged MR)"
```

> ⚠️ Do **not** push this to `main` yet. Pushing triggers the new pipeline (which expects the GitOps repo to already contain `kandidat/compose.yaml` and the Komodo Stack to exist). Push happens in Phase 2 Task 10, after the Stack is live.

---

# PHASE 2 — Bascule (👤 TOI — detailed runbook)

> Every step below is **yours to run**. Each gives the exact command, what to enter/click, and the expected output to confirm before moving on. **Do not skip the verification line of a step.**
>
> Set these shell vars once on dockhost (SSH in first): `ssh dockhost` then nothing else needed — commands assume you are on dockhost where the `postgresql` container runs, except where it says "local repo".

---

### Task 4: 👤 Back up the production database (BEFORE any teardown)

**Files:** none (produces a dump file you keep off-container).

- [x] **Step 1: Capture the currently-running image tag** (so you can pin/rollback if needed)

Run on dockhost:
```bash
docker inspect kandidat --format '{{.Config.Image}}'
```
Expected: something like `registry.gitlab.com/tipunchlabs/kandidat:<sha-or-main>`. Note it down.

- [x] **Step 2: Dump the kandidat database from the shared postgres container**

```bash
docker exec postgresql pg_dump -U postgres -d kandidat \
  --format=custom --no-owner --no-privileges \
  -f /tmp/kandidat.dump
docker cp postgresql:/tmp/kandidat.dump ~/kandidat-2026-06-16.dump
```

- [x] **Step 3: Verify the dump is readable and non-empty**

```bash
ls -lh ~/kandidat-2026-06-16.dump
docker exec postgresql pg_restore --list /tmp/kandidat.dump | head
```
Expected: file size > a few KB; `pg_restore --list` prints a table-of-contents (TABLE/SEQUENCE entries). If empty or errored, **stop** — do not proceed to teardown.

- [x] **Step 4: Record baseline row counts** (to compare after restore)

```bash
docker exec postgresql psql -U postgres -d kandidat -c \
  "SELECT 'candidatures' t, count(*) FROM candidatures
   UNION ALL SELECT 'contacts', count(*) FROM contacts;"
```
Expected: a small table of counts. **Write these numbers down** — Task 11 compares against them. (Adjust table names if the schema differs; list tables with `\dt`.)

- [x] **Step 5: Confirm the file data exists on the host** (will be reused as-is)

```bash
ls -R /app/data/kandidat/candidatures | head
```
Expected: directories with `*.md` files. These are **not** dumped — they stay on the host bind mount.

---

### Task 5: 👤 Add secrets + registry auth in Komodo Core

**Files:** none (Komodo UI, v2.1.2).

> 🧠 **Komodo model:** there is **no "Secrets" tab**. Secrets are **Variables marked as secret** (Settings → **Variables**, "Secret" column). They are interpolated into resource config (incl. the Stack's *Environment*) with **double brackets `[[NAME]]`** — not `${...}`. The `${...}` substitution happens one layer later, by docker compose, from that Environment.

- [x] **Step 1: Open Komodo Core UI** → `http://komodo.internal/settings` → **Variables** tab.

- [x] **Step 2: Create two secret Variables** (`+ New Variable`), each with the **Secret** flag enabled (reuse the exact values from the Ansible vault). Fill the **Description** column too:

  | Name | Value | Secret | Description |
  |---|---|---|---|
  | `SECRET_KEY` | value of `vault_kandidat_secret_key` | ✅ | `kandidat — Flask SECRET_KEY (sessions/CSRF). Consumed by the kandidat Stack via [[SECRET_KEY]].` |
  | `DB_PASSWORD` | value of `vault_kandidat_db_password` | ✅ | `kandidat — dedicated Postgres password (POSTGRES_PASSWORD + DATABASE_URL). Used by the kandidat Stack via [[DB_PASSWORD]].` |

> 💡 Read the current values from the encrypted vault, on your workstation:
> `cd 02-infrastructure/homelab/dockhost/ansible && ansible-vault view group_vars/dockhost/vault/config.yml` (vault password required), then copy `vault_kandidat_secret_key` and `vault_kandidat_db_password`.

- [x] **Step 3: Add GitLab Container Registry auth** so Komodo can pull the private kandidat image.

  Settings → **Providers** tab. It has **two separate sections**:
  - **Git Accounts** — already configured (`gitlab.com` / `komodo`), used to *clone* the repo. **Leave it untouched.**
  - **Registry Accounts** — this is the one to fill.

  Under **Registry Accounts** → **+ New Account**:

  | Field | Value |
  |---|---|
  | **Domain** | `registry.gitlab.com` |
  | **Username** | value of `vault_kandidat_registry_user` |
  | **Token** | value of `vault_kandidat_registry_password` |

  > ⚠️ The Domain is **`registry.gitlab.com`** (the Container Registry host), **not** `gitlab.com`. It must match the image prefix `registry.gitlab.com/tipunchlabs/kandidat` so Komodo applies these creds when pulling. Same credentials as the old Ansible `docker login registry.gitlab.com`.

- [x] **Step 4: Verify** both Variables show with **Secret** enabled (value masked), and the new **Registry Account** row `registry.gitlab.com` appears under Registry Accounts (not Git Accounts).

---

### Task 6: 👤 Bootstrap the GitOps repo (Section 0) — push the seed to `main`

**Files:** the working copy `02-infrastructure/homelab-gitops/`.

> ✅ **Already done by Phase 1:** `git init -b main`, `git remote add origin git@gitlab.com:tipunchlabs/homelab-gitops.git`, and the seed commits (`bc4a268` compose+.env.example, `fc7fa59` READMEs+root README) on local `main`. So Steps 1-3 of the original plan are complete.
>
> ✅ **Protection reality:** `main` allows **push for Maintainers** (`push_access_level=40`, `allow_force_push=false`). You are Owner/Maintainer, so you can push the initial seed **directly** — no branch+MR dance needed for bootstrap. (Ongoing image bumps still go through MRs, via the CI `bump` job.)

- [x] **Step 1: Commit the `.gitignore`** (it ignores real `.env` but keeps `.env.example`)

```bash
cd 02-infrastructure/homelab-gitops
git commit -m "chore: add .gitignore (ignore real .env, keep .env.example)"
```

- [x] **Step 2: Confirm only the intended files are tracked** — `poc-hello/` and `portail-client/` must stay untracked (D5: seed = kandidat only)

```bash
git ls-files          # expect: .gitignore, README.md, kandidat/{compose.yaml,.env.example,README.md}
git status --short    # poc-hello/ and portail-client/ shown as untracked — leave them
```

- [x] **Step 3: Push `main` directly** (allowed for Maintainers; first push to the empty repo)

```bash
git push -u origin main
```

- [x] **Step 4: Verify the content landed on the remote**

```bash
glab api projects/81629969/repository/files/kandidat%2Fcompose.yaml/raw?ref=main | head
```
Expected: the compose YAML prints.

---

### Task 7: 👤 Create + configure the Komodo Stack `kandidat`

**Files:** none (Komodo UI, v2.1.2). After **Stacks → New Stack** (name `kandidat`), open the Stack → **Config** tab → **GENERAL**, then fill the fields below. A fresh Stack shows **UNKNOWN / 0 Services / Config Missing** until configured + saved — that's expected.

- [x] **Step 1: Select Server** — pick the dockhost Periphery server (192.168.10.90). This is the deploy target.

- [x] **Step 2: Choose Mode** → **`Git Repo`** (the "pulled from a git repo" option = file-based GitOps).
  - *Not* `UI Defined` (compose pasted in UI) and *not* `Files on Server` (`files_on_host`).
  - Choosing `Git Repo` reveals the source fields below.

- [x] **Step 3: Git source** (fields appear after Step 2)

  | Field | Value |
  |---|---|
  | **Git Provider** | `gitlab.com` |
  | **Git Account** | `komodo` (the Git Account from Providers — clones the private repo) |
  | **Repo** | `tipunchlabs/homelab-gitops` |
  | **Branch** | `main` |

- [x] **Step 4: File location**

  | Field | Value |
  |---|---|
  | **Run Directory** | `kandidat` (Komodo `cd`s here before `docker compose up`) |
  | **File Paths** | `compose.yaml` (relative to Run Directory; empty → defaults to `compose.yaml`) |

- [x] **Step 5: Environment** — in the Stack's **Environment** section, paste exactly (Komodo interpolates `[[...]]` from the secret Variables, then compose substitutes `${...}` in `compose.yaml`):

  ```
  SECRET_KEY=[[SECRET_KEY]]
  DB_PASSWORD=[[DB_PASSWORD]]
  ```

- [x] **Step 6: Webhook + drift safety net**
  - Enable the Stack **Webhook** with **Auth = Gitlab**, **Resource Id = Id**, execution **`/deploy`** (you already did this). The trigger will come from the **internal runner** (Task 8), not from gitlab.com — same `/listener` endpoint, called from inside the LAN.
  - ⚠️ **Leave the "Webhook Secret" field BLANK** so it inherits the Core's global `KOMODO_WEBHOOK_SECRET` (already set via `vault_komodo_webhook_secret`). **Do not** type the literal string `KOMODO_WEBHOOK_SECRET` — that's the variable *name*, not its value. (If you set it earlier, clear it.)
  - **Drift safety net (recommended, agreed):** the Core already polls every hour (`KOMODO_RESOURCE_POLL_INTERVAL=1-hr`). If the Stack exposes a **Poll For Updates** toggle, enable it so the Stack re-syncs from git periodically even if a trigger is missed.

- [x] **Step 7: Save** the Stack config. Verify: the **Config Missing** badge clears, and the **Services** tab lists **2 services** (`kandidat`, `db`) parsed from the compose pulled out of git. ✅ DONE 2026-06-19 — clone fixed (Komodo Git Account `username=komodo` to match Stack `git_account`; GitLab deploy token `username=token`; new token value `gldt-py6…`). Services tab shows `kandidat` (RUNNING, observed Ansible container) + `db` (Unknown), `latest: 8eb1a7c`.

- [x] **Step 8: ⚠️ Do NOT click Deploy yet** — the old Ansible container still owns port 8000. Deploy happens in Task 9 after teardown. Just save the definition.

> 🆔 **Stack ID** is in the URL (`/stacks/<ID>`), e.g. `6a3332fda56f584190c16998`. It's already baked into the trigger job (`homelab-gitops/.gitlab-ci.yml`, `STACK_ID`). If your Stack ID differs, update that file in Task 8.

---

### Task 8: Wire the GitOps trigger via the internal self-hosted runner (no exposure)

**Decision (validated):** instead of exposing Komodo's `/listener` to gitlab.com (webhook + Cloudflare Tunnel), a CI job in `homelab-gitops` triggers Komodo **from inside the LAN** using the existing self-hosted runner `bastion-60`. This keeps Komodo private and is still **full GitOps**: the trigger lives in the GitOps repo's CI, so *any* push to its `main` (bump MR, manual edit, `git revert`) reconciles. The Cloudflare-Tunnel route is documented as a fallback in `~/Workspace/03-second-brain/_inbox/guide-komodo-cloudflare-tunnel.md`.

**Files:** `02-infrastructure/homelab-gitops/.gitlab-ci.yml` (🤖 created — job `trigger-komodo-kandidat`). No Terraform.

**Verified facts** (don't re-check): runner `bastion-60` (id `52153437`) is **not locked** (enable-able on other projects) but **`run_untagged=false`** → the job is tagged `bastion`. dockhost **UFW already opens 9120** (`Komodo Core UI + webhook listener`), so bastion (`192.168.10.60`) reaches `http://192.168.10.90:9120` directly — no Caddy, no TLS, no DNS. Komodo branch-filters on the payload, so the job sends `{"ref":"refs/heads/main"}`.

> ⏱️ **Timing:** do **A** and **B** now. The job file is already created; it gets **pushed in Task 11** (after cutover) so the very first trigger lands on an already-deployed Stack — never before Task 9.

- [x] **Step 1 — 👤 ACTION A: Enable the runner on `homelab-gitops`** ✅ DONE 2026-06-19 — `bastion-60` (#52153437) now under Assigned project runners on `homelab-gitops`, Online.
  GitLab → project **`tipunchlabs/homelab-gitops`** → **Settings → CI/CD → Runners** (expand). Under **Project runners → Available runners / Other available runners**, find **`bastion-60`** (`bastion-60 - shell executor for homelab deployments`) and click **Enable for this project**.
  - ✅ Verify: it now appears under **Assigned project runners** with a green (online) dot.
  - *(It's currently enabled on `kandidat`/`homelab`/`miniboard`; this just adds `homelab-gitops`.)*

- [x] **Step 2 — 👤 ACTION B: Add the masked CI variable `KOMODO_WEBHOOK_SECRET`** ✅ DONE 2026-06-19 — created on `homelab-gitops`, flags Protected + Masked, Environments All.
  First read the secret value from the Ansible Vault:

```bash
cd /home/xgueret/Workspace/02-infrastructure/homelab/dockhost
ansible-vault view ansible/group_vars/dockhost/vault/main.yml | grep komodo_webhook_secret
```

  Then GitLab → **`homelab-gitops`** → **Settings → CI/CD → Variables → Add variable**:
  - **Key**: `KOMODO_WEBHOOK_SECRET`
  - **Value**: the value you just read
  - **Type**: Variable · **Flags**: ✅ **Masked**, ✅ **Protected** (it only needs to run on the protected `main` branch)
  - **Save**.

- [ ] **Step 3 — 🤖 The trigger job (already created — just review)**
  File `homelab-gitops/.gitlab-ci.yml` defines `trigger-komodo-kandidat` (stage `deploy`, `tags: [bastion]`, `rules: main + changes: kandidat/**/*`). It POSTs to `http://192.168.10.90:9120/listener/gitlab/stack/6a3332fda56f584190c16998/deploy` with `X-Gitlab-Token: $KOMODO_WEBHOOK_SECRET` and a minimal push payload, asserting a 2xx.
  - ⚠️ **Do NOT push it yet** — it's committed/pushed in **Task 11 Step 1** (post-cutover). Pushing now would trigger a deploy while the old Ansible container still owns port 8000.
  - If your Stack ID is not `6a3332fda56f584190c16998`, edit `STACK_ID` in that file before Task 11.

> 🛟 **Fallback if the listener rejects the manual call** (e.g. branch-filter or payload parsing): switch the job to Komodo's API instead — generate an API key/secret in Komodo (Settings → API Keys), store them as masked CI vars, and `POST /execute` with a `DeployStack` body. Try the `/listener` path first (reuses the existing secret + Stack webhook config).

---

### Task 9: 👤 Cutover — stop Ansible deployment, deploy the Stack

- [x] **Step 1: Stop the old Ansible-managed container** (on dockhost) ✅ DONE 2026-06-20

```bash
docker compose -f /opt/kandidat/docker-compose.yml down
```
Expected: `kandidat` container stops/removed. Port 8000 is now free. (The shared `postgresql` container keeps running — your dump is already taken.)

- [x] **Step 2: Deploy the Komodo Stack** (Komodo UI → Stack `kandidat` → **Deploy**). ✅ DONE 2026-06-20
Expected: Komodo pulls the image and starts `kandidat` + `kandidat-db`. The `db` starts **empty**.

> 🔧 **Two compose fixes were needed during cutover** (committed + pushed to `homelab-gitops/main`):
> 1. `db` image `postgres:16` → **`postgres:17`** — prod dump is PG 17.4; restoring into PG16 is the unsupported newer→older direction and `pg_restore` rejects the archive.
> 2. `DATABASE_URL` `postgresql://` → **`postgresql+psycopg://`** — the image ships psycopg v3, not psycopg2 (matches the old Ansible `vault_kandidat_database_url`). Without it: `ModuleNotFoundError: No module named 'psycopg2'`.

- [x] **Step 3: Wait for `db` healthy** ✅ DONE 2026-06-20 — `kandidat-db` ready, `kandidat` RUNNING (gunicorn boots clean).

```bash
docker ps --filter name=kandidat-db --format '{{.Names}} {{.Status}}'
```
Expected: `kandidat-db ... (healthy)`.

> The app may be unhealthy/restarting until the DB is restored (next task) because tables/data are missing — that's expected and fine.

---

### Task 10: 👤 Restore the database into the dedicated postgres

- [x] **Step 1: Copy the dump into the new db container** ✅ DONE 2026-06-20 (used the fresh dump `~/kandidat-2026-06-19.dump`, taken just before cutover)

```bash
docker cp ~/kandidat-2026-06-19.dump kandidat-db:/tmp/kandidat.dump
```

- [x] **Step 2: Restore** ✅ DONE 2026-06-20 — no fatal errors; row counts match baseline (candidatures=28, contacts=8). Zero data loss confirmed.

```bash
docker exec kandidat-db pg_restore -U kandidat -d kandidat \
  --no-owner --role=kandidat --clean --if-exists /tmp/kandidat.dump
```
Expected: completes with no fatal errors (harmless `does not exist, skipping` notices from `--clean --if-exists` are fine).

- [x] **Step 3: Restart the app so it reconnects cleanly** (Komodo → redeploy `kandidat` service, or `docker restart kandidat`). ✅ DONE 2026-06-20 — app RUNNING after the psycopg fix + redeploy.
Expected: `kandidat` becomes healthy.

---

### Task 11: 👤 Push the kandidat CI change + verify the full GitOps loop

- [x] **Step 1: 👤 Install the GitOps trigger job on `homelab-gitops`** ✅ DONE 2026-06-20 — commit `4a24f9c` pushed to main; no pipeline created (job filtered out by `changes: kandidat/**/*`) = expected, no deploy.

```bash
cd /home/xgueret/Workspace/02-infrastructure/homelab-gitops
git add .gitlab-ci.yml
git commit -m "ci: add Komodo GitOps reconcile trigger (internal runner)"
git push origin main
```
Expected: pushed to `main`. The `trigger-komodo-kandidat` job is **skipped** on this push (its `changes: kandidat/**/*` filter doesn't match a `.gitlab-ci.yml`-only change) — that's intended, no deploy happens here. (Requires Task 8 A+B done first: runner enabled + `KOMODO_WEBHOOK_SECRET` variable set.)

- [x] **Step 2: 👤 (Optional) Sanity-check the trigger once, by hand** ✅ DONE 2026-06-20 — manual `curl` to `/listener` returned 200 but **no deploy** (dedup: `deployed_hash == latest_hash`). Verified the listener auths the secret correctly; a real deploy requires a new commit (proven in Step 3).

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  -H "X-Gitlab-Token: <KOMODO_WEBHOOK_SECRET value from Task 8>" \
  -H "X-Gitlab-Event: Push Hook" -H "Content-Type: application/json" \
  -d '{"ref":"refs/heads/main"}' \
  http://192.168.10.90:9120/listener/gitlab/stack/6a3332fda56f584190c16998/deploy
```
Expected: a **2xx** code, and a fresh **deploy event** in the Komodo UI for `kandidat`. A `401`/`403` = secret mismatch; a non-2xx with no deploy = branch-filter/payload → use the Task 8 fallback (Komodo API).

- [x] **Step 3: 👤 Push the Phase-1 kandidat CI change to main** (the commit from Task 3 — drives the full loop) ✅ DONE 2026-06-20 — followed GitHub Flow: moved the 2 commits to branch `feat/gitops-bump-trigger`, MR → merge on `main`. Merge pipeline `2616436457` (SHA `4fe9fa6e`) green: lint→test→security→build→**bump** all success.

```bash
cd /home/xgueret/Workspace/01-projets/tipunchlabs/kandidat
git push origin main
```
Expected: pipeline runs lint→test→security→build→**bump**. The `bump` job opens & auto-merges an MR on `homelab-gitops` pinning `kandidat:<new-sha>`. That merge = a push to `homelab-gitops/main` touching `kandidat/compose.yaml`.

- [x] **Step 4: Verify the bump landed** ✅ DONE 2026-06-20 — `homelab-gitops` merge `4a24f9c..bc8b8ac`; `kandidat/compose.yaml` line 12 = `image: registry.gitlab.com/tipunchlabs/kandidat:4fe9fa6e` (pinned). (yq also stripped 3 blank separator lines — cosmetic; DATABASE_URL/bind mount/env all intact.)

```bash
glab api projects/81629969/repository/files/kandidat%2Fcompose.yaml/raw?ref=main | grep image
```
Expected: `image: registry.gitlab.com/tipunchlabs/kandidat:<new-sha>` (pinned, not `:main`).

- [x] **Step 5: Verify the trigger fired and Komodo redeployed** ✅ DONE 2026-06-20 — Komodo UI → Updates: `kandidat · Deploy Stack · SUCCESS · 15:36:54 · Operator: **Git Webhook**` (not admin). Confirms the bump-merge push on `homelab-gitops` fired `trigger-komodo-kandidat` → `/listener` → automatic deploy of `:4fe9fa6e`. **Full GitOps loop proven.**

- [x] **Step 6: ✅ Verify the URL is up** ✅ DONE 2026-06-20 — app healthy: `localhost:8000 -> 200` on dockhost, container `kandidat` Up (healthy), gunicorn boots clean. `http://kandidat.internal -> 200` from the workstation (the `000` seen *from dockhost* is just dockhost's DNS/Caddy view, not a regression). HTTPS `kandidat.internal` TLS still deferred (Caddy, out of scope).

```bash
curl -k -s -o /dev/null -w '%{http_code}\n' https://kandidat.internal
```
Expected: `200`.

- [x] **Step 7: ✅ Verify data integrity** (compare to baseline from Task 4 Step 4) ✅ DONE 2026-06-20 — `candidatures=28`, `contacts=8` — **identical to baseline. Zero data loss.**

```bash
docker exec kandidat-db psql -U kandidat -d kandidat -c \
  "SELECT 'candidatures' t, count(*) FROM candidatures
   UNION ALL SELECT 'contacts', count(*) FROM contacts;"
```
Expected: **identical counts** to the baseline. Also confirm files: open the app, search a candidature whose `.md` exists, or `ls /app/data/kandidat/candidatures`.

- [ ] **Step 8: ✅ Verify rollback works** (optional but recommended): `git revert` the last bump commit on homelab-gitops via an MR → the merge pushes `kandidat/compose.yaml` → `trigger-komodo-kandidat` fires → Komodo redeploys the previous image. (This is the proof that the trigger lives in the GitOps repo = full GitOps.)

> **Gate:** Only proceed to Phase 3 once Steps 6 and 7 pass (URL 200 + counts match).

---

# PHASE 3 — Cleanup (🤖 CLAUDE + 👤 push/vault) — only after Phase 2 verified

---

### Task 12: Remove the Ansible kandidat deploy role + wiring

**Files:**
- Delete: `02-infrastructure/homelab/dockhost/ansible/roles/kandidat/` (whole dir)
- Modify: `02-infrastructure/homelab/dockhost/ansible/deploy.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: a `deploy.yml` with no reference to the `kandidat` role or its `db-net` tag.

- [ ] **Step 1: Remove the `kandidat` role from the `roles:` list in `deploy.yml`**

Delete these two lines (currently 46-48):

```yaml
    - role: kandidat
      tags:
        - kandidat
```

- [ ] **Step 2: Remove `kandidat` from the `db-net` network `tags:` in `deploy.yml`**

In the `Create shared Docker network for database services` task (lines 21-28), remove the `- kandidat` tag line so it reads:

```yaml
    - name: Create shared Docker network for database services
      community.docker.docker_network:
        name: db-net
        state: present
      tags:
        - postgresql
        - open-webui
```

- [ ] **Step 3: Delete the role directory** (use `trash`, confirm first)

```bash
trash 02-infrastructure/homelab/dockhost/ansible/roles/kandidat
```

- [ ] **Step 4: Verify no dangling references**

Run: `grep -rn "kandidat" 02-infrastructure/homelab/dockhost/ansible/deploy.yml 02-infrastructure/homelab/dockhost/ansible/roles/`
Expected: no matches (the role is gone, deploy.yml clean). The UFW rule for port 8000 in `group_vars/dockhost/all/main.yml` **stays** (Caddy needs it) — do not touch it.

- [ ] **Step 5: Commit** (on user's go)

```bash
cd 02-infrastructure/homelab
git add dockhost/ansible/deploy.yml
git rm -r dockhost/ansible/roles/kandidat
git commit -m "chore(dockhost): remove Ansible kandidat deploy role (now GitOps)"
```

---

### Task 13: 👤 Remove `vault_kandidat_*` secrets from the encrypted vault

**Files:** `02-infrastructure/homelab/dockhost/ansible/group_vars/dockhost/vault/config.yml` (ansible-vault encrypted — requires vault password).

- [ ] **Step 1: Edit the encrypted vault**

```bash
cd 02-infrastructure/homelab/dockhost/ansible
ansible-vault edit group_vars/dockhost/vault/config.yml
```

- [ ] **Step 2: Remove these keys** (now owned by Komodo): `vault_kandidat_secret_key`, `vault_kandidat_db_password`, `vault_kandidat_database_url`, `vault_kandidat_registry_user`, `vault_kandidat_registry_password`. Save & exit.

- [ ] **Step 3: Verify the role no longer needs them** (already deleted in Task 12) and that no other role references them:

```bash
grep -rn "vault_kandidat" 02-infrastructure/homelab/dockhost/ansible/
```
Expected: no matches.

- [ ] **Step 4: Commit the re-encrypted vault** (on user's go)

```bash
cd 02-infrastructure/homelab
git add dockhost/ansible/group_vars/dockhost/vault/config.yml
git commit -m "chore(vault): drop kandidat secrets (migrated to Komodo)"
```

> ⚠️ Do **not** delete `/app/data/kandidat` on dockhost, ever — those files are the live bind mount used by the Stack.

---

### Task 14: 👤 Push the homelab cleanup commits

- [ ] **Step 1: Push** (homelab repo — branch + PR if it has protection, else push per its workflow)

```bash
cd 02-infrastructure/homelab
git push
```
Expected: cleanup commits land. The next time `dockhost/ansible/deploy.yml` runs, it no longer manages kandidat.

- [ ] **Step 2: Final sanity** — confirm kandidat still serves after a Komodo poll cycle:

```bash
curl -k -s -o /dev/null -w '%{http_code}\n' https://kandidat.internal
```
Expected: `200`. Migration complete.

---

## Self-Review (against spec)

- **Spec coverage:** D1 dedicated postgres → Task 1 + restore Task 10. D2 bump via MR auto-merge → Task 3 + verify Task 11. D3 Claude artefacts / user ops → Phase split. D4 terraform location untouched → respected (Task 8 now uses an internal-runner CI trigger, no Terraform webhook; Cloudflare-Tunnel route kept as documented fallback). D5 seed = kandidat only → Task 6. D6 reused host bind mount → Task 1 compose + Task 4/11 file checks. Section 0 bootstrap → Task 6. Secrets Vault→Komodo → Task 5 + Task 13. Backup/restore → Tasks 4 & 10. Cutover order → Tasks 9-11. Cleanup → Tasks 12-14. CLAUDE.md/README correction → Task 2.
- **Placeholder scan:** image seed `:main` is intentional (bumped to `:SHA` on first push), not a placeholder; all commands concrete. Row counts use `candidatures`/`contacts` with a noted fallback (`\dt`) since the exact schema list isn't pinned in the spec.
- **Type/name consistency:** db service host = `db`, container = `kandidat-db`, db/user = `kandidat`, network = `kandidat-net`, volume = `kandidat-db`, dump file = `~/kandidat-2026-06-16.dump` — used consistently across Tasks 1/9/10/11. project id `81629969` consistent.

---

> **Plan derived from** `docs/superpowers/specs/2026-06-16-kandidat-gitops-migration-design.md`.
