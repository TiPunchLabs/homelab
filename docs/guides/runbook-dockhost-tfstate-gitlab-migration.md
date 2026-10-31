# 🧳 Runbook — Dockhost Terraform state migration to GitLab-managed state

> **Status**: ✅ **migration EXECUTED 2026-10-31 02:50Z** (S1–S8, evidence
> `~/.local/share/homelab-tfstate-backup/dockhost/migration-20261030T224942`). The record is in
> chapter 9. Still pending: owner merge of MR !81, then S10. Chapter 5 is kept as the historical procedure: **do not run it again**.
>
> ⛔ **FORBIDDEN: `terraform apply` on the known network drift** (`ipconfig0` 192.168.1.90 → 192.168.10.90).
> The plan shows 1 change: it is known drift, not a change to apply (see chapter 8).
> **Target**: local state of `dockhost/terraform` (VM 9090) → GitLab-managed state,
> project `tipunchlabs/homelab` (id `80082616`), state name `dockhost`.
> **Code**: MR !81 (`infra/dockhost-tfstate-gitlab`), adds `backend "http"` to
> `dockhost/terraform/providers.tf`. **Merge only after step S8 and the S9 review.**
> **Contains no secret.** Credentials reach Terraform only through `scripts/with-secrets`,
> scoped to one process, from an owner terminal.

## Table of contents

1. Mental Model
2. Facts (read-only evidence)
3. Decisions
4. Preconditions
5. Execution
6. Acceptance criteria
7. Rollback
8. Out of scope
9. Execution record (2026-10-31)

------

## 🧠 Chapter 1: Mental Model

```
 bastion-60 disk (stopped)      laptop backup (0400)            GitLab project 80082616
 ┌──────────────────────┐ copy  ┌─────────────────────────┐     ┌──────────────────────┐
 │ terraform.tfstate    │─────► │ ...from-bastion-60.     │     │ state "dockhost"     │
 │ serial 1, TF 1.11.4  │ 10-16 │ 2026-10-16  (never      │     │ (does not exist yet) │
 │ canonical, inactive  │       │ modified)               │     └──────────▲───────────┘
 └──────────────────────┘       └────────────┬────────────┘                │
                                  install -m 600                init -migrate-state
                                             ▼                  -force-copy
                                 dockhost/terraform/terraform.tfstate ─────┘
                                 (temporary, moved out after verification)
```

One writer at a time: the laptop. Local and HTTP locks cannot coordinate, so
the freeze in P8 is procedural.

Credential flow (security model of MR !82):

```
 owner terminal (new window, no Herdr, no agent)
   └─ direnv exec $H           → .envrc: TF_HTTP_USERNAME, TF_VAR_pm_api_url (non-sensitive)
        └─ scripts/with-secrets <profiles>   → pass → TF_HTTP_PASSWORD / TF_VAR_pm_api_token_*
             └─ exec terraform ...           → secrets live in this process only
```

| Who | Runs | Credentials |
|---|---|---|
| Claude Code | P1–P8, P11, read-only GitLab/Proxmox metadata, offline gate tests | none (SSH keys and `glab` auth only; never `pass`, never `with-secrets`) |
| Owner | P0, P9, P10, D-TOKEN check, chapter 5, S9 merge, S10, chapter 7 | `scripts/with-secrets` profiles `tfstate`, `proxmox`, per command |
| Codex | review of this runbook and of the evidence directory `$E` (S9) | none, launched from a shell that passed the P0 checks |

Never run a credentialed step from Claude Code, Codex, a Herdr pane or any
session started before MR !82: old processes may still carry inherited credentials.

------

## 📖 Chapter 2: Facts (read-only evidence, 2026-10-30)

| Item | Value |
|---|---|
| Backup | `~/.local/share/homelab-tfstate-backup/dockhost/terraform.tfstate.from-bastion-60.2026-10-16`, mode 0400, mtime 2026-03-11, `sha256sum -c` OK (`e09104fb…0c41`) |
| State content | format 4, `terraform_version` 1.11.4, serial 1, lineage `99061ad6-d0cc-00e1-03a4-7f810b79ea1f` |
| Resources | 1: `module.dockhost_vm.proxmox_virtual_environment_vm.vm[0]`, `vm_id` 9090; output `vm_ips` |
| Secrets in state | none: cloud-init password empty (marked sensitive), one SSH **public** key |
| Baseline plan (TF 1.17.0, bpg 0.96.0, scratch copy, `-lock=false`) | exit 2, `0 to add, 1 to change, 0 to destroy`; only `initialization.ip_config.ipv4` 192.168.1.90/24 gw .1.1 → 192.168.10.90/24 gw .10.1; copy byte-identical after plan |
| bastion-60 (9060) | stopped, `onboot: 0`; runner 52153437 paused → no writer since 2026-10-16 |
| GitLab | `terraformStates.count = 0`; project public, but state read needs Developer+, write/lock needs Maintainer; only member = owner |
| Working dir | no `dockhost/terraform/terraform.tfstate*`, no `.terraform/terraform.tfstate` |
| Tooling | only Terraform 1.17.0 installed (mise `terraform = "latest"`) → use the absolute binary below |
| Provider | untracked lock file pins `bpg/proxmox` 0.96.0; Renovate MR !60 (→ 0.118.0) open, **must stay unmerged** during the window |
| Credentials | MR !82: `.envrc` holds config only (`TF_HTTP_USERNAME` included); `scripts/with-secrets` profile `tfstate` loads `TF_HTTP_PASSWORD` from `pass gitlab/terraform-token`, profile `proxmox` loads `TF_VAR_pm_api_token_id/secret` |
| Token incident | 2026-10-30 22:57Z: the values of `.envrc` secrets, including `gitlab/terraform-token` (PAT id 20891640), were printed into a Claude Code session. Rotation required (D-ROTATE) |

------

## 🎯 Chapter 3: Decisions

| ID | Decision | State |
|---|---|---|
| D-TF | Terraform 1.17.0 | Accepted (M3.4). The migration writes `terraform_version` 1.17.0 into the remote state. Use 1.17.0 (absolute binary below) for migration, verification and rollback. Older binaries (bastion's 1.11.4, CI image 1.11) are untested against the migrated state and prohibited for this procedure. CI only runs `init -backend=false` and is unaffected |
| D-TOKEN | Credential for `TF_HTTP_PASSWORD` | Resolved: `pass gitlab/terraform-token` via profile `tfstate` (classic PAT, `api` scope, owner 600944 = Maintainer+). The same entry backs `TF_VAR_gitlab_token` |
| D-ENV | How the token reaches Terraform | Resolved by MR !82: `TF_HTTP_USERNAME` from the untracked `.envrc`; `TF_HTTP_PASSWORD` only from `scripts/with-secrets tfstate`. Never in `.envrc`, never exported in a shell, never `-backend-config=password=…` (persisted in `.terraform/terraform.tfstate`) |
| D-ROTATE | Rotate `gitlab/terraform-token` (exposed 2026-10-30) and update the pass entry | **CLOSED — Owner attestation, 2026-10-30** (`OWNER_ATTESTED`: new token created and used, old token revoked). Corroborating GitLab metadata, not an independent proof of the pass entry: PAT 20891640 `revoked: true`, last used 2026-10-30T22:54:58Z; PAT 29024653 active, `api`, user 600944, created 2026-10-31T02:27:15Z, last used 2026-10-31T02:59:29Z |
| D-GO | Execute chapter 5 | Given by the owner after D-ROTATE; chapter 5 executed 2026-10-31 (chapter 9) |
| D-LINEAGE | Remote lineage differs from the backup | **ACCEPTED by the owner**: `99061ad6-d0cc-00e1-03a4-7f810b79ea1f` → `4fbe2f5c-d50f-c5c8-45ac-541ce2521cb4`. Not to be reopened. Consequences in chapter 9 |

D-TOKEN check, owner terminal, after defining chapter 4's variables (`$H`). It prints metadata only, never the value. The token
reaches `curl` on stdin (`printf` is a shell builtin), never on a command line:

```bash
direnv exec "$H" "$H/scripts/with-secrets" tfstate -- sh -c \
  'printf "PRIVATE-TOKEN: %s\n" "$TF_HTTP_PASSWORD" | curl -sS -H @- https://gitlab.com/api/v4/personal_access_tokens/self' \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print({k:d.get(k) for k in ("id","name","scopes","active","revoked","created_at","expires_at","user_id")})'
```

Expect `id` ≠ 20891640, `created_at` after 2026-10-30T22:57Z, `active: True`,
`revoked: False`, `scopes` containing `api`, an expiry after the window, `user_id` 600944.
Claude can corroborate without the secret: `glab api personal_access_tokens/20891640`
must show `active: false` or `revoked: true`.

------

## 📝 Chapter 4: Preconditions (re-check immediately before chapter 5)

Open a **new terminal window** (not a Herdr pane, not a Claude Code or Codex shell),
check out the branch, then define the variables and helpers in that shell:

```bash
git -C ~/Workspace/02-infrastructure/homelab switch infra/dockhost-tfstate-gitlab
git -C ~/Workspace/02-infrastructure/homelab pull --ff-only

H=~/Workspace/02-infrastructure/homelab
W=$H/dockhost/terraform
T=~/.local/share/mise/installs/terraform/1.17.0/terraform
B=~/.local/share/homelab-tfstate-backup/dockhost/terraform.tfstate.from-bastion-60.2026-10-16
E=~/.local/share/homelab-tfstate-backup/dockhost/migration-$(date +%Y%m%dT%H%M%S)   # new, unique evidence dir

# Terraform with .envrc config and secrets scoped to this one process.
# $1 = with-secrets profiles: "tfstate" (GitLab state) or "proxmox,tfstate" (plan)
tfw() { local p=$1; shift; direnv exec "$H" "$H/scripts/with-secrets" "$p" -- "$T" "$@"; }

# Exit 0 only if the plan log is the known 0/1/0 ipconfig drift
check_plan() {
python3 - "$1" <<'EOF'
import re,sys
t=open(sys.argv[1]).read()
got=[l.strip() for l in t.splitlines() if re.match(r"\s+[~+-] ",l)]
exp=['~ update in-place','~ resource "proxmox_virtual_environment_vm" "vm" {','~ initialization {','~ ip_config {','~ ipv4 {',
     '~ address = "192.168.1.90/24" -> "192.168.10.90/24"','~ gateway = "192.168.1.1" -> "192.168.10.1"',
     '~ vm_ips = [','~ "192.168.1.90" -> "192.168.10.90",']
ok="Plan: 0 to add, 1 to change, 0 to destroy." in t and got==exp
print("plan_matches_baseline",ok); sys.exit(0 if ok else 1)
EOF
}

# Exit 0 only if state $2 keeps the lineage, resources and outputs of state $1
check_same() {
python3 - "$1" "$2" <<'EOF'
import json,sys
a,b=(json.load(open(p)) for p in sys.argv[1:])
res={"lineage":a["lineage"]==b["lineage"],"resources":a["resources"]==b["resources"],"outputs":a["outputs"]==b["outputs"],"format":b["version"]==4}
print(res,"serial",a["serial"],"->",b["serial"],"tf",a["terraform_version"],"->",b["terraform_version"])
sys.exit(0 if all(res.values()) else 1)
EOF
}
```

| # | Check | Command | Expected |
|---|---|---|---|
| P0 | Owner terminal independent and clean (names only) | `[ -z "${HERDR_ENV:-}${CLAUDECODE:-}" ] && echo independent`; `compgen -e \| grep -E '^(TF_HTTP_PASSWORD\|ANSIBLE_VAULT_PASSWORD\|GITLAB_TOKEN\|GITHUB_TOKEN\|TF_VAR_.*(token\|secret\|password\|key).*)$' \|\| echo none`; `[ -z "${TF_LOG:-}${TF_LOG_PATH:-}${TF_LOG_CORE:-}${TF_LOG_PROVIDER:-}" ] && echo nolog` | `independent`, `none`, `nolog` |
| P1 | bastion inactive | `ssh pve 'sudo qm status 9060; sudo qm config 9060 \| grep onboot'` | `stopped`, `onboot: 0` |
| P2 | Git | `git -C $H status --porcelain`; `git -C $H rev-parse HEAD origin/infra/dockhost-tfstate-gitlab`; `test -x $H/scripts/with-secrets` | empty; equal; present (branch contains main with MR !82) |
| P3 | MRs | `glab api projects/80082616/merge_requests/81` and `/60` | !81 draft, unmerged; !60 unmerged |
| P4 | No remote state | `glab api graphql -f query='{ project(fullPath:"tipunchlabs/homelab"){ terraformStates{ count } } }'` | `count: 0` |
| P5 | Backup integrity | `sha256sum -c $B.sha256` | `OK` |
| P6 | Clean working dir | `ls $W/terraform.tfstate* $W/.terraform/terraform.tfstate` | both absent |
| P7 | Tooling | `$T version`; `grep -A1 bpg/proxmox $W/.terraform.lock.hcl` | 1.17.0; 0.96.0 |
| P8 | Freeze | declared by the owner; `pgrep -af terraform` | no other dockhost Terraform run anywhere until S10 |
| P9 | Credentials reach the child, never printed | `direnv exec $H $H/scripts/with-secrets tfstate -- sh -c 'test -n "$TF_HTTP_USERNAME" && test -n "$TF_HTTP_PASSWORD" && echo SET'` | `SET` (also warms the gpg-agent cache before chapter 5) |
| P10 | Baseline plan (owner, profile `proxmox`) | block below | block ends without `STOP`: exit 2, `plan_matches_baseline True`, copy byte-identical to the backup (`cmp`) |
| P11 | Infra snapshot | `ssh pve 'sudo qm config 9090 \| grep ipconfig0'`; `ssh dockhost-90 uptime -s` | `ip=192.168.1.90/24`, uptime recorded |

P10, on a scratch copy built from `origin/main` (local backend; valid only while
!81 is unmerged):

```bash
(
set -euo pipefail
! git -C "$H" show origin/main:dockhost/terraform/providers.tf | grep 'backend "http"' || { echo "STOP: main has the backend"; exit 1; }
P=$(mktemp -d); chmod 700 "$P"; echo "scratch $P"
git -C "$H" archive origin/main dockhost/terraform modules | tar -x -C "$P"
cp "$W/.terraform.lock.hcl" "$P/dockhost/terraform/"
install -m 600 "$B" "$P/dockhost/terraform/terraform.tfstate"
cd "$P/dockhost/terraform"
direnv exec "$H" "$T" init -input=false -no-color > "$P/init.log" 2>&1
rc=0; tfw proxmox plan -lock=false -input=false -no-color -detailed-exitcode > "$P/plan.log" 2>&1 || rc=$?
[ "$rc" -eq 2 ] || { echo "STOP: plan exit $rc, expected 2"; exit 1; }
check_plan "$P/plan.log" || { echo "STOP: plan differs from baseline"; exit 1; }
cmp -s "$P/dockhost/terraform/terraform.tfstate" "$B" || { echo "STOP: scratch copy modified"; exit 1; }
sha256sum "$P/dockhost/terraform/terraform.tfstate" "$B"
)
```

Any deviation → stop, do not improvise.

------

## 🛠️ Chapter 5: Execution (owner GO required)

Run as one fail-fast subshell in the owner terminal where chapter 4's variables
and helpers are defined. Every gate exits non-zero and stops the run. S9 and S10
are manual, after review.

```bash
(
set -euo pipefail
stop() { echo "STOP at $1" >&2; exit 1; }

# S1 — independent shell, no Terraform logging, no exported credential; new evidence directory
[ -z "${HERDR_ENV:-}${CLAUDECODE:-}" ] || stop "S1 (agent or Herdr shell)"
[ -z "${TF_LOG:-}${TF_LOG_PATH:-}${TF_LOG_CORE:-}${TF_LOG_PROVIDER:-}" ] || stop "S1 (TF_LOG set)"
! compgen -e | grep -xE 'TF_HTTP_PASSWORD|TF_VAR_pm_api_token_secret' || stop "S1 (credential exported)"
mkdir -m 700 "$E" || stop S1

# S2 — place the state (temporary)
[ ! -e "$W/terraform.tfstate" ] || stop S2
install -m 600 "$B" "$W/terraform.tfstate"

# S3 — migrate (writes the GitLab state)
cd "$W"
tfw tfstate init -migrate-state -force-copy -input=false -no-color > "$E/init.log" 2>&1 || stop S3
grep -q 'Successfully configured the backend "http"' "$E/init.log" || stop S3

# S4 — backend record carries no credential (prints presence only, never values)
python3 - <<'EOF' || stop S4
import json,sys
b=json.load(open(".terraform/terraform.tfstate"))["backend"]; c=b["config"]
ok = b["type"]=="http" and c["address"]=="https://gitlab.com/api/v4/projects/80082616/terraform/state/dockhost"
leaked=bool(c.get("password"))
print("backend_ok",ok,"password_field_populated",leaked,"username_field_populated",bool(c.get("username")))
sys.exit(0 if ok and not leaked else 1)
EOF

# S5 — pull the remote and compare with the backup
tfw tfstate state pull > "$E/remote.json" || stop S5
chmod 400 "$E/remote.json"
check_same "$B" "$E/remote.json" || stop S5

# S6 — plan from the remote state (takes and releases the GitLab lock). NEVER apply.
rc=0; tfw proxmox,tfstate plan -input=false -no-color -detailed-exitcode > "$E/plan.log" 2>&1 || rc=$?
[ "$rc" -eq 2 ] || stop "S6 (plan exit $rc, expected 2)"
check_plan "$E/plan.log" || stop S6

# S7 — GitLab view: one state, unlocked
glab api graphql -f query='{ project(fullPath:"tipunchlabs/homelab"){ terraformStates{ count nodes{ name lockedAt latestVersion{ serial } } } } }' > "$E/gitlab-states.json" || stop S7
python3 - "$E/gitlab-states.json" <<'EOF' || stop S7
import json,sys
s=json.load(open(sys.argv[1]))["data"]["project"]["terraformStates"]
ok=s["count"]==1 and s["nodes"][0]["name"]=="dockhost" and s["nodes"][0]["lockedAt"] is None
print(s, "ok", ok); sys.exit(0 if ok else 1)
EOF

# S8 — move the temporary local files out of the repo (no deletion, no overwrite), then scan for leaks
for f in terraform.tfstate terraform.tfstate.backup; do
  if [ -e "$W/$f" ]; then
    [ ! -e "$E/$f.local-after-migration" ] || stop S8
    mv -n "$W/$f" "$E/$f.local-after-migration"
  fi
done
chmod 400 "$E"/*
sha256sum -c "$B.sha256" || stop S8
[ -z "$(git -C "$H" status --porcelain)" ] || stop "S8 (repo not clean)"
grc=0; grep -rIlE 'glpat-|PRIVATE-TOKEN' "$E" "$W/.terraform" || grc=$?
[ "$grc" -eq 1 ] || stop "S8 (credential pattern scan: match or error, grep exit $grc)"
# exact-value scan: the values reach grep on stdin (printf builtin), never on a command line.
# The child exits 0 only on grep "no match" (1); a match, a grep error or a with-secrets/pass failure all stop.
direnv exec "$H" "$H/scripts/with-secrets" proxmox,tfstate -- sh -c \
  'printf "%s\n" "$TF_HTTP_PASSWORD" "$TF_VAR_pm_api_token_secret" | grep -rIlF -f - "$1" "$2"; [ $? -eq 1 ]' sh "$E" "$W/.terraform" \
  || stop "S8 (exact-value scan: match, grep error or credential load failure)"
! compgen -e | grep -xE 'TF_HTTP_PASSWORD|TF_VAR_pm_api_token_secret' || stop "S8 (credential leaked into the shell)"
echo "S1-S8 PASSED — evidence in $E"
)
```

Manual, after the run:

- **S9**: Codex reviews `$E` (read-only, from a shell that passes P0; never from a
  `with-secrets` child). Then the owner marks MR !81 ready and merges it. The `main`
  pipeline must be green.
- **S10**: switch `$H` to an up-to-date `main` (`git switch main && git pull --ff-only`).
  In a new owner terminal, do **not** re-run chapter 4's first block as is: its
  `git switch` targets the migration branch (deleted at merge) and it would create a new `$E`.
  Define `H`, `W`, `T`, `B` and the three helpers from that block, and point `E` at the
  existing evidence directory:
  `E=~/.local/share/homelab-tfstate-backup/dockhost/migration-20261030T224942`; run P0.
  In `$W`, run `tfw tfstate init -input=false`. Then run
  `rc=0; tfw proxmox,tfstate plan -input=false -no-color -detailed-exitcode > "$E/plan-post-merge.log" 2>&1 || rc=$?`
  (a new file: `$E/plan.log` has been read-only since S8), then
  `if [ "$rc" -eq 2 ] && check_plan "$E/plan-post-merge.log"; then echo "S10 PASSED"; else echo "STOP at S10 (plan exit $rc)"; fi`.
  Only `S10 PASSED` ends the freeze.

If S3 fails: stop. Run the P4 query to learn whether a remote state was
created. Do not retry blindly. A stuck lock is released only with
`tfw tfstate force-unlock <ID>`, and that needs owner approval.

------

## ✅ Chapter 6: Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| AC1 | Remote `dockhost` exists; lineage `99061ad6…`; resources and outputs JSON-identical to the backup | S5, S7 |
| AC2 | Plan from the remote = 0/1/0, ipconfig only | S6 |
| AC3 | No lock held after the run | S7 `lockedAt: null` |
| AC4 | No secret in the repo, `.terraform/terraform.tfstate`, `$E` or the owner shell | S4; S8 pattern scan, exact-value scan and `compgen` check |
| AC5 | Backup unchanged | S8 `sha256sum -c` OK |
| AC6 | No `terraform.tfstate*` left in `$W` | `ls`; S8 `git status` clean |
| AC7 | Infrastructure untouched: `ipconfig0` still `192.168.1.90/24`, dockhost uptime unchanged, no apply in any log | P11 repeated |

> 💡 **Note**: these are the criteria as designed. AC1 as written (lineage `99061ad6…`,
> JSON-identical resources) is not met; the owner accepted the exception (D-LINEAGE).
> Results per criterion are in chapter 9.3.

**Definition of Done**: AC1–AC7 verified; Codex review PASS or
PASS_WITH_RESERVATIONS on the evidence; MR !81 merged by the owner; `main`
pipeline green; S10 plan identical; the bastion copy declared obsolete (it
disappears with VM 9060, after its own approval).

------

## 🔧 Chapter 7: Rollback

Rule: delete nothing until the destination is verified. `$B` is never modified.
All commands run in the owner terminal, with chapter 4's helpers, from `$W`.
Since 2026-10-31 the source of truth is the remote state (lineage `4fbe2f5c…`). Restore
precautions for the old-lineage files are in chapter 9.4.

1. Keep the freeze.
2. Snapshot the remote: `tfw tfstate state pull > "$E/remote-latest.json"`, chmod 400, record sha256.
3. Restore the configuration without the backend block: before merge, `git restore --source=origin/main -- providers.tf` (valid while `origin/main` has no backend); after merge, use a branch that reverts the backend commit `9c82604`.
4. `tfw tfstate init -migrate-state -force-copy -input=false`. This copies the remote back to a local `terraform.tfstate` and reconfigures `.terraform` for the local backend.
5. Verify: lineage, resources and outputs equal to `remote-latest.json` (lineage `4fbe2f5c…` since the migration), and plan = the same 0/1/0. All three conditions are in one chain; go to step 6 only after `R5 PASSED`:

   ```bash
   rc=0; tfw proxmox plan -input=false -no-color -detailed-exitcode > "$E/plan-rollback.log" 2>&1 || rc=$?
   if check_same "$E/remote-latest.json" "$W/terraform.tfstate" && [ "$rc" -eq 2 ] && check_plan "$E/plan-rollback.log"
   then echo "R5 PASSED"; else echo "STOP at R5 (state mismatch, or plan exit $rc / drift)"; false; fi
   ```
6. Only then retire the remote: `glab api -X DELETE projects/80082616/terraform/state/dockhost` (Maintainer). If `main` already has the backend block, also merge the revert.

------

## 📚 Chapter 8: Out of scope

- **Cloud-init `ipconfig0` drift** (the 1 change in the plan). ⛔ **FORBIDDEN:
  `terraform apply` on this known network drift.** Never fix it in this migration
  and never `apply` dockhost until that work is done. See
  [`../backlog/cloud-init-guards-and-network-drift.md`](../backlog/cloud-init-guards-and-network-drift.md):
  aligning it changes the NoCloud instance-id, and bpg `reboot_after_update = true`
  reboots dockhost (Komodo, kandidat, postgres).
- Other Terraform states (laptop-local, not bastion dependencies). bastion's own
  state stays local until the 9060 destroy.
- Renovate !60 (bpg 0.118.0): after the migration, as a separate change.
- Rotation of the other credentials exposed on 2026-10-30 (owner decision, outside this runbook).

------

## 📊 Chapter 9: Execution record (2026-10-31)

Statuses: `VERIFIED` (checked by command, with evidence), `OWNER_ATTESTED` (owner
statement, not independently proven), `ACCEPTED_WITH_EVIDENCE_LIMITATION`,
`NOT_VERIFIED`. Times in UTC. Evidence directory:
`E=~/.local/share/homelab-tfstate-backup/dockhost/migration-20261030T224942` (0700, files 0400).
The record was compiled read-only, without credentials (GitLab API through `glab`, ssh), on 2026-10-31.

### 9.1 📝 Steps

| Step | Evidence | Status |
|---|---|---|
| S1 | `$E` created 02:50:11Z (directory birth time; its mtime 03:00:13Z is the S8 move) | VERIFIED (`stat`) |
| S2–S3 | `init.log`: `Successfully configured the backend "http"`, bpg 0.96.0 from the lock file | VERIFIED |
| S4 | `.terraform/terraform.tfstate`: type `http`, address `…/80082616/terraform/state/dockhost`, `password` and `username` not populated | VERIFIED |
| S5 | `remote.json` pulled 02:50:17Z. The strict gate `check_same "$B" "$E/remote.json"` **fails** on this evidence (lineage, and `resources` because of `identity_schema_version`). Under chapter 5 the run stops here | VERIFIED (gate result) |
| S6–S8 | `plan.log` 02:59:31Z, `gitlab-states.json` 02:59:50Z, local files moved into `$E` 03:00:13Z, about 9 min after S5. They were therefore run after the S5 gate, outside the fail-fast subshell. The exact commands were not recorded. The owner accepted the S5 deviation (D-LINEAGE) | VERIFIED (artefacts); sequence OWNER_ATTESTED |
| S9 | Codex review of `$E` | see the M3.4 closure report |
| S10 | not executed (after the MR !81 merge) | pending |

### 9.2 🧬 State history and the lineage exception

| Copy | Lineage | TF | Serial | Use |
|---|---|---|---|---|
| bastion-60 disk, then `$B` (backup, sha256 `e09104fb…`) | `99061ad6…` | 1.11.4 | 1 | historical, read-only |
| `$E/terraform.tfstate.backup.local-after-migration` (written by TF 1.17.0 at S3) | `99061ad6…` | 1.17.0 | 1 | historical, read-only |
| `$E/terraform.tfstate.local-after-migration` | — | — | — | empty (0 bytes) |
| GitLab state `dockhost` (= `$E/remote.json`) | `4fbe2f5c-d50f-c5c8-45ac-541ce2521cb4` | 1.17.0 | 1 | **source of truth** |

- Resources: the remote differs from `$B` only by `instances[0].identity_schema_version: 0`, which TF 1.17 adds on re-serialization. Every resource attribute is identical, and `outputs` are identical (VERIFIED, structural diff).
- The remote equals the TF 1.17 local backup in `resources` and `outputs`. Only the lineage differs (VERIFIED). The cause of the new lineage was not established.
- On 2026-10-31, the live remote (`GET projects/80082616/terraform/state/dockhost`) equals `$E/remote.json` field for field. Its only version is serial 1 (02:50:14Z), so no write since the migration (VERIFIED).

Comparison instructions from now on:

- Reference for any future check: `$E/remote.json`, compared strictly with `check_same "$E/remote.json" <state>`.
- Comparing with `$B` is valid only modulo lineage and `identity_schema_version`:

```bash
STATE_JSON=$E/remote.json   # the state file to compare
python3 - "$B" "$STATE_JSON" <<'EOF'
import json,sys
def norm(d):
    r=json.loads(json.dumps(d["resources"]))
    for res in r:
        for i in res["instances"]: i.pop("identity_schema_version",None)
    return r
a,b=(json.load(open(p)) for p in sys.argv[1:])
ok=norm(a)==norm(b) and a["outputs"]==b["outputs"]
print("equivalent_modulo_lineage",ok); sys.exit(0 if ok else 1)
EOF
```

### 9.3 ✅ Acceptance results

| ID | Result | Evidence / limit |
|---|---|---|
| AC1 | VERIFIED with the accepted lineage exception | remote exists; resources equivalent (only `identity_schema_version` added); outputs identical; lineage changed (D-LINEAGE, accepted) |
| AC2 | VERIFIED (log); exit code NOT_VERIFIED | `plan.log`: `Plan: 0 to add, 1 to change, 0 to destroy.`, `check_plan` → `True`. The plan exit code was not kept in the evidence |
| AC3 | VERIFIED | `gitlab-states.json` 02:59:50Z `lockedAt: null`; still `null` on 2026-10-31 |
| AC4 | VERIFIED in part; D-ROTATE OWNER_ATTESTED | S4 VERIFIED; pattern scan of `$E` and `.terraform` clean (re-run read-only); the exact-value scan needs credentials and was not re-run (NOT_VERIFIED by the reviewer); D-ROTATE: chapter 3 |
| AC5 | VERIFIED | `sha256sum -c $B.sha256` OK, mode 0400, mtime 2026-03-12 02:32:38Z (2026-03-11 local time, as in chapter 2) |
| AC6 | VERIFIED | no `terraform.tfstate*` in `$W`; temporary files moved (not deleted) into `$E`; `git status` clean |
| AC7 | VERIFIED | `ipconfig0` still `192.168.1.90/24`; dockhost up since 2026-10-30 21:12:54 (= P11 baseline), cloud-init instance-id `4b196b7b…` and guest `192.168.10.90/24` unchanged; last Proxmox task on 9090 = `qmstart` 2026-10-30T21:12:47Z (pve restart, before the migration), last `terraform-prov@pve` task 2026-03-12; remote state never past serial 1; no CI job runs Terraform apply |

### 9.4 🔐 Restore precautions

- Old backups (`$B`, the `.backup.local-after-migration` copy, bastion-60's disk) carry lineage `99061ad6…`. **Never `state push` them onto the remote, and never use `-force`.** They are history, not restore points for the GitLab state.
- To restore the current state, use the remote itself, or `$E/remote.json` (lineage `4fbe2f5c…`).
- Restoring from `$B` would create a different state history. That needs a separate owner decision, a fresh plan, and the freeze.
- bastion-60 (9060) keeps an obsolete copy: never run Terraform for dockhost there. It disappears with 9060, after its own approval.
- Single-writer freeze stays in force until S10 has passed. Terraform 1.17.0 and bpg 0.96.0 only (Renovate !60 stays unmerged).

> **Document created on**: 2026-10-30
> **Author**: Xavier Gueret, with Claude Code
> **Version**: 2.4 (v2.3 at `0a62c25`: MR !82 model; v2.4 records the 2026-10-31 execution, D-ROTATE closed on owner attestation, D-LINEAGE exception, apply prohibition, restore precautions)
