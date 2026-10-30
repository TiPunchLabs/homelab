# 🧳 Runbook — Dockhost Terraform state migration to GitLab-managed state

> **Status**: ⏸️ ready, **NOT EXECUTED**. Every mutating step below needs explicit owner approval.
> **Target**: local state of `dockhost/terraform` (VM 9090) → GitLab-managed state,
> project `tipunchlabs/homelab` (id `80082616`), state name `dockhost`.
> **Code**: MR !81 (`infra/dockhost-tfstate-gitlab`), adds `backend "http"` to
> `dockhost/terraform/providers.tf`. **Merge only after step 9.**
> **Contains no secret.** Credentials are environment variables only.

## Table of contents

1. Mental Model
2. Facts (read-only evidence)
3. Decisions
4. Preconditions
5. Execution
6. Acceptance criteria
7. Rollback
8. Out of scope

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
| Provider | lock file pins `bpg/proxmox` 0.96.0; Renovate MR !60 (→ 0.118.0) open, **must stay unmerged** during the window |

------

## 🎯 Chapter 3: Decisions

| ID | Decision | State |
|---|---|---|
| D-TF | Terraform 1.17.0 | Provisionally accepted. Evidence: 1.17.0 reads this 1.11.4 state (baseline plan, format 4). The migration writes `terraform_version` 1.17.0 into the remote state. Policy: 1.17.0 (absolute binary below) for migration, verification and rollback; older binaries (bastion's 1.11.4, CI image 1.11) are untested against the migrated state and prohibited for this procedure. CI is unaffected, as it only runs `init -backend=false` |
| D-TOKEN | Credential for `TF_HTTP_PASSWORD` | **Open**. Classic token: `api` scope; fine-grained: Terraform State **Read, Create, Lock** (+ **Delete** for rollback step R6). User role Maintainer+ on 80082616 |
| D-ENV | How the token reaches Terraform | **Open**. Recommended: two lines in the untracked `homelab/.envrc` (same pattern as `TF_VAR_*`): `export TF_HTTP_USERNAME=<gitlab-user>` and `TF_HTTP_PASSWORD=$(pass <entry>)` + `export` |
| D-GO | Execute chapter 5 | **Open** |

Owner-side token check. It prints metadata only, never the value:

```bash
# Run in your own shell; prints name/scopes/expiry/user_id only
pass show <entry> | head -1 | sed 's/^/PRIVATE-TOKEN: /' \
  | curl -sS -H @- https://gitlab.com/api/v4/personal_access_tokens/self \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print({k:d.get(k) for k in ("name","scopes","active","revoked","expires_at","user_id")})'
```

Expect `active: True`, `revoked: False`, `scopes` containing `api` (classic), an
expiry after the window, and `user_id` of a Maintainer+ member (owner = 600944).

------

## 📝 Chapter 4: Preconditions (re-check immediately before chapter 5)

```bash
H=~/Workspace/02-infrastructure/homelab
W=$H/dockhost/terraform
T=~/.local/share/mise/installs/terraform/1.17.0/terraform
B=~/.local/share/homelab-tfstate-backup/dockhost/terraform.tfstate.from-bastion-60.2026-10-16
E=~/.local/share/homelab-tfstate-backup/dockhost/migration-$(date +%Y%m%dT%H%M%S)   # new, unique evidence dir
```

| # | Check | Command | Expected |
|---|---|---|---|
| P1 | bastion inactive | `ssh pve 'sudo qm status 9060; sudo qm config 9060 \| grep onboot'` | `stopped`, `onboot: 0` |
| P2 | Git | `git -C $H status --porcelain`; `git -C $H rev-parse HEAD origin/infra/dockhost-tfstate-gitlab` | empty; equal; branch contains the backend commit |
| P3 | MRs | `glab api projects/80082616/merge_requests/81` and `/60` | !81 draft, unmerged; !60 unmerged |
| P4 | No remote state | `glab api graphql -f query='{ project(fullPath:"tipunchlabs/homelab"){ terraformStates{ count } } }'` | `count: 0` |
| P5 | Backup integrity | `sha256sum -c $B.sha256` | `OK` |
| P6 | Clean working dir | `ls $W/terraform.tfstate* $W/.terraform/terraform.tfstate` | both absent |
| P7 | Tooling | `$T version`; `grep -A1 bpg/proxmox $W/.terraform.lock.hcl` | 1.17.0; 0.96.0 |
| P8 | Freeze | declared by the owner | no other dockhost Terraform run anywhere until step 9 |
| P9 | Credentials present, never printed | `direnv exec $H sh -c 'test -n "$TF_HTTP_USERNAME" && test -n "$TF_HTTP_PASSWORD" && echo SET'` | `SET` |
| P10 | Baseline plan | scratch copy of `$B`, `$T plan -lock=false -detailed-exitcode` | exit 2, 0/1/0, ipconfig only |
| P11 | Infra snapshot | `ssh pve 'sudo qm config 9090 \| grep ipconfig0'`; `ssh dockhost-90 uptime -s` | `ip=192.168.1.90/24`, uptime recorded |

Any deviation → stop, do not improvise.

> 💡 **Note**: in Claude Code's shell, `direnv exec` restores a stale PATH. Clear
> `DIRENV_DIFF DIRENV_DIR DIRENV_FILE DIRENV_WATCHES` and prepend the mise install paths first.

------

## 🛠️ Chapter 5: Execution (owner GO required)

Run as one fail-fast subshell in the shell where chapter 4's variables are set.
Every gate exits non-zero and stops the run. S9 and S10 are manual, after review.

```bash
(
set -euo pipefail
stop() { echo "STOP at $1" >&2; exit 1; }

# S1 — new evidence directory (fails if it already exists)
mkdir -m 700 "$E" || stop S1

# S2 — place the state (temporary)
[ ! -e "$W/terraform.tfstate" ] || stop S2
install -m 600 "$B" "$W/terraform.tfstate"

# S3 — migrate (writes the GitLab state)
cd "$W"
direnv exec "$H" "$T" init -migrate-state -force-copy -input=false -no-color > "$E/init.log" 2>&1 || stop S3
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
direnv exec "$H" "$T" state pull > "$E/remote.json" || stop S5
chmod 400 "$E/remote.json"
python3 - "$B" "$E/remote.json" <<'EOF' || stop S5
import json,sys
a,b=(json.load(open(p)) for p in sys.argv[1:])
res={"lineage":a["lineage"]==b["lineage"],"resources":a["resources"]==b["resources"],"outputs":a["outputs"]==b["outputs"],"format":b["version"]==4}
print(res,"serial",a["serial"],"->",b["serial"],"tf",a["terraform_version"],"->",b["terraform_version"])
sys.exit(0 if all(res.values()) else 1)
EOF

# S6 — plan from the remote state (takes and releases the GitLab lock). NEVER apply.
rc=0; direnv exec "$H" "$T" plan -input=false -no-color -detailed-exitcode > "$E/plan.log" 2>&1 || rc=$?
[ "$rc" -eq 2 ] || stop "S6 (plan exit $rc, expected 2)"
python3 - "$E/plan.log" <<'EOF' || stop S6
import re,sys
t=open(sys.argv[1]).read()
got=[l.strip() for l in t.splitlines() if re.match(r"\s+[~+-] ",l)]
exp=['~ update in-place','~ resource "proxmox_virtual_environment_vm" "vm" {','~ initialization {','~ ip_config {','~ ipv4 {',
     '~ address = "192.168.1.90/24" -> "192.168.10.90/24"','~ gateway = "192.168.1.1" -> "192.168.10.1"',
     '~ vm_ips = [','~ "192.168.1.90" -> "192.168.10.90",']
ok="Plan: 0 to add, 1 to change, 0 to destroy." in t and got==exp
print("plan_matches_baseline",ok); sys.exit(0 if ok else 1)
EOF

# S7 — GitLab view: one state, unlocked
glab api graphql -f query='{ project(fullPath:"tipunchlabs/homelab"){ terraformStates{ count nodes{ name lockedAt latestVersion{ serial } } } } }' > "$E/gitlab-states.json" || stop S7
python3 - "$E/gitlab-states.json" <<'EOF' || stop S7
import json,sys
s=json.load(open(sys.argv[1]))["data"]["project"]["terraformStates"]
ok=s["count"]==1 and s["nodes"][0]["name"]=="dockhost" and s["nodes"][0]["lockedAt"] is None
print(s, "ok", ok); sys.exit(0 if ok else 1)
EOF

# S8 — move the temporary local files out of the repo (no deletion, no overwrite)
for f in terraform.tfstate terraform.tfstate.backup; do
  if [ -e "$W/$f" ]; then
    [ ! -e "$E/$f.local-after-migration" ] || stop S8
    mv -n "$W/$f" "$E/$f.local-after-migration"
  fi
done
chmod 400 "$E"/*
sha256sum -c "$B.sha256" || stop S8
grc=0; grep -rIlE 'glpat-|PRIVATE-TOKEN' "$E" "$W/.terraform" || grc=$?
[ "$grc" -eq 1 ] || stop "S8 (credential scan: match or error, grep exit $grc)"
echo "S1-S8 PASSED — evidence in $E"
)
```

Manual, after the run:

- **S9**: Codex reviews `$E`. The owner marks MR !81 ready and merges it. The `main` pipeline must be green.
- **S10**: from an up-to-date `main` checkout, run in `$W`
  `direnv exec "$H" "$T" init -input=false`, then the S6 plan with its output in a
  new file (`$E/plan-post-merge.log`; `$E/plan.log` is read-only since S8), and
  run the S6 checker on that file. The result must be identical.

If S3 fails: stop. Run the P4 query to learn whether a remote state was
created. Do not retry blindly. A stuck lock is released only with
`$T force-unlock <ID>`, and that needs owner approval.

------

## ✅ Chapter 6: Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| AC1 | Remote `dockhost` exists; lineage `99061ad6…`; resources and outputs JSON-identical to the backup | S5, S7 |
| AC2 | Plan from the remote = 0/1/0, ipconfig only | S6 |
| AC3 | No lock held after the run | S7 `lockedAt: null` |
| AC4 | No secret in the repo, `.terraform/terraform.tfstate` or `$E` | S4; `grep -rIl -E 'glpat-\|PRIVATE-TOKEN' "$E" "$W/.terraform"` → nothing |
| AC5 | Backup unchanged | S8 `sha256sum -c` OK |
| AC6 | No `terraform.tfstate*` left in `$W` | `ls` |
| AC7 | Infrastructure untouched: `ipconfig0` still `192.168.1.90/24`, dockhost uptime unchanged, no apply in any log | P11 repeated |

**Definition of Done**: AC1–AC7 verified; Codex review PASS or
PASS_WITH_RESERVATIONS on the evidence; MR !81 merged by the owner; `main`
pipeline green; S10 plan identical; the bastion copy declared obsolete (it
disappears with VM 9060, after its own approval).

------

## 🔧 Chapter 7: Rollback

Rule: delete nothing until the destination is verified. `$B` is never modified.

1. Keep the freeze.
2. Snapshot the remote: `direnv exec "$H" "$T" state pull > "$E/remote-latest.json"`, chmod 400, record sha256.
3. Restore the configuration without the backend block: before merge, `git restore --source=main -- providers.tf` from `$W`; after merge, use a branch that reverts the backend commit.
4. `direnv exec "$H" "$T" init -migrate-state -force-copy -input=false`. This copies the remote back to a local `terraform.tfstate` and reconfigures `.terraform` for the local backend.
5. Verify: lineage `99061ad6…`, resources and outputs equal to `remote-latest.json`, plan = the same 0/1/0.
6. Only then retire the remote: `glab api -X DELETE projects/80082616/terraform/state/dockhost` (Maintainer). If `main` already has the backend block, also merge the revert.

------

## 📚 Chapter 8: Out of scope

- **Cloud-init `ipconfig0` drift** (the 1 change in the plan). Never fix it in
  this migration and never `apply` dockhost until that work is done. See
  [`../backlog/cloud-init-guards-and-network-drift.md`](../backlog/cloud-init-guards-and-network-drift.md):
  aligning it changes the NoCloud instance-id, and bpg `reboot_after_update = true`
  reboots dockhost (Komodo, kandidat, postgres).
- Other Terraform states (laptop-local, not bastion dependencies). bastion's own
  state stays local until the 9060 destroy.
- Renovate !60 (bpg 0.118.0): after the migration, as a separate change.

> **Document created on**: 2026-10-30
> **Author**: Xavier Gueret, with Claude Code
> **Version**: 2.2 (v1 was an unversioned scratch draft; v2.1 adds fail-fast gates after the M3.3 Codex review)
