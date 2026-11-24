# Owner questions — SCOUT-MAIL-01 (grouped, 2026-11-20)

None of these block fixture work. The feature ships disabled by default (`hermes_scout_mail_enabled: false`); they are needed only for the read-only smoke test, the live behavioral evaluation and the production enablement.

Searched before asking (non-secret discovery, no inference from names):
- Repository: `git grep -i agentmail` on `origin/main` 3d7bf18 — no match.
- hermes-31, variable NAMES only (no values) in `/opt/data/.env`, `/opt/data/profiles/job-search/.env`, `/etc/hermes/.env` — no AgentMail variable; no `agentmail` string in Scout's or the managed `config.yaml`.
- The Ansible vault is encrypted and was not read.

## Q1 — Inbox identifier (non-secret)

Status: ANSWERED 2026-11-21 by the owner: `scout-emploi@agentmail.to`, standard region `api.agentmail.to`, confirmed by the owner: a read call on `https://api.agentmail.to` returned 200 for this inbox (US region). Set in clear text as `hermes_scout_mail_inbox_id` in `hermes/ansible/group_vars/hermes/all/main.yml`; `hermes_scout_mail_enabled` stays `false`. The role default `hermes_scout_mail_agentmail_host` is already `api.agentmail.to` (`roles/hermes_agent/defaults/main.yml:246`), so no host override is set.

Which AgentMail inbox must Scout read? Give the exact `inbox_id` (AgentMail uses the inbox email address as its id, for example `name@agentmail.to`) and the region (`api.agentmail.to` or EU `api.agentmail.eu`).

Recommendation: put it in clear text in `hermes/ansible/group_vars/hermes/all/main.yml` as `hermes_scout_mail_inbox_id` (an address is an identifier, like the Telegram allowlist), or tell pilotage and it will be added on the branch. If you consider the address private, put it in the vault instead as `vault_hermes_scout_mail_inbox_id`; the code accepts both.

## Q2 — Key scope (decides whether the existing key is acceptable)

Status: ANSWERED 2026-11-21 by the owner (« la clef et le vault sont ok »): a dedicated key was created with the command below, inbox-scoped to `scout-emploi@agentmail.to`, permissions `inbox_read` + `message_read` only; a read call on `https://api.agentmail.to` returned 200. Not independently verified by the executor (no key access).

AgentMail keys are whitelist-scoped. If `permissions` is omitted at creation, the key gets ALL permissions, including `message_send` and `message_delete`. A key named "readonly" proves nothing. Please check in the AgentMail console or API how the existing key was created:

- Scope: is it inbox-scoped to the inbox of Q1? It must not be organization- or pod-scoped.
- Permissions: only `inbox_read` and `message_read` should be true.

Recommendation: create a dedicated replacement key, scoped to the inbox and read-only, from your own terminal. Never paste a key in chat. The API endpoint is documented at https://docs.agentmail.to/api-reference/inboxes/api-keys/create; your org-level admin key is used only for this one call:

```bash
# Run in your own terminal. Prints the new key once; it goes straight into pass.
ORG_KEY="$(pass show agentmail/admin-key)"   # or paste interactively; never commit
INBOX_ID='<inbox id from Q1>'
curl -sS --proto '=https' --max-redirs 0 \
  -X POST "https://api.agentmail.to/v0/inboxes/${INBOX_ID}/api-keys" \
  -H "Authorization: Bearer ${ORG_KEY}" -H 'Content-Type: application/json' \
  -d '{"name":"scout-readonly","permissions":{"inbox_read":true,"message_read":true}}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])' \
  | pass insert -m agentmail/scout-readonly
unset ORG_KEY
```

Then tell pilotage: "key created, inbox-scoped, permissions inbox_read+message_read" (no value).

## Q3 — Secret provisioning (exact step, owner-run)

Status: DONE 2026-11-21 by the owner: `vault_hermes_job_search_agentmail_api_key` added to `hermes/ansible/group_vars/hermes/vault/config.yml`. Committed encrypted in `225fc3a` (first line `$ANSIBLE_VAULT;1.1;AES256`, never decrypted by the executor). `hermes_scout_mail_enabled` stays `false`. The read smoke test (runbook step 6) stays for after merge and deployment, at the owner's call.

The plugin reads `AGENTMAIL_API_KEY` from Scout's profile `.env` only. Ansible writes that file key by key, mode 0600, `no_log`. The vault variable to add is `vault_hermes_job_search_agentmail_api_key`:

```bash
cd ~/Workspace/02-infrastructure/homelab   # or the worktree after merge
ansible-vault edit hermes/ansible/group_vars/hermes/vault/config.yml
# add one line (value from: pass show agentmail/scout-readonly):
#   vault_hermes_job_search_agentmail_api_key: "<value>"
```

Recommendation: provision the key only after merge and immediately before enablement (runbook step 3). It stays unused while `hermes_scout_mail_enabled` is false.

## Q4 — Live behavioral evaluation and read smoke test (optional now)

No model credential was legitimately available to the executor: the DeepSeek key exists only in the vault and on hermes-31, and a local credential check was denied. Behavioral evaluation is therefore NOT_VERIFIED. If you want it before merge, run this from your own terminal (synthetic fixtures only, at most 40 calls, local harness, no AgentMail access):

```bash
cd /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01
DEEPSEEK_API_KEY="$(pass show <your deepseek entry>)" \
  uv run python hermes/tests/scout_mail_live_eval.py --max-calls 40 \
  --out docs/missions/2026-11-20-scout-agentmail-readonly/evidence/m4-live-eval.json
```

The AgentMail read smoke test (list and get only) needs Q1 to Q3 first; it is in the runbook (step 6).
