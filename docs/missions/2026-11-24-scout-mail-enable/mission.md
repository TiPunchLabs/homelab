# Mission — Enable and deploy Scout mail (`/courriels`)

- Mission id: `homelab/2026-11-24-scout-mail-enable`
- Worktree: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mailon`, branch `feat/scout-mail-enable` from `origin/main` `4355209` (MR !109 merged).
- Reference: `docs/guides/runbook-scout-mail.md` (§1–§4, §6, §8.1). Previous mission: `docs/missions/2026-11-20-scout-agentmail-readonly/` (on the main checkout, untracked).
- Pilot: pilotage (Claude Code). Executor: one Claude Code session in this worktree. Owner: Xavier.

## Owner approval (quoted)

2026-11-24, owner: « go pour activer et déployer ». Covers ONE action on this mission: the enabling commit below and its deployment to `hermes-31` with `--tags hermes`. Merging the enabling branch into `main` is a separate owner decision (asked after the Telegram test).

## Expected result

Scout (profile `job-search`) answers `/courriels` in Telegram with a read-only digest of `scout-emploi@agentmail.to`; Nora (`default`) and Kaféine (`cafe-ia`) are unchanged. The owner then runs the Telegram test (runbook §4 rows 1–5) himself.

## Steps

- E1 Commit (one commit, Conventional Commits): in `hermes/ansible/group_vars/hermes/all/main.yml` set `hermes_scout_mail_enabled: true` and `plugins.enabled: [scout_mail]` in Scout's declaration. `hermes_scout_mail_inbox_id` is already `scout-emploi@agentmail.to`; the vault key `vault_hermes_job_search_agentmail_api_key` is already present (owner, 2026-11-21). Nothing else changes.
- E2 Offline checks: `uv run pytest hermes/tests -q` (image tests only if `nousresearch/hermes-agent:v0.22.5` is present locally; say so either way). Exact counts.
- E3 Before state (read-only): runbook §2 step 5 sha256 command, plus gateway health, `served_profiles`, container restart count/start time.
- E4 Check mode: `ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes --check --diff` from `hermes/`. Proceed to E5 only if the changes are exactly the expected ones (plugin files, `settings.json`, hidden AgentMail key in Scout's `.env`, nothing for `default`/`cafe-ia`, no toolset change). Anything else → stop, write `report.md` (Verdict BLOCKED) and the line below.
- E5 Deploy: same command without `--check`; one multiplexed gateway restart expected; the playbook's `hermes_checks.py scout-mail` must pass. Then a second run: `changed=0` expected.
- E6 After state (read-only): plugin present only for `job-search`, `settings.json` `enabled: true` (print only that key), `head -c 6 plugin-data/scout_mail/taint.state` = `armed` once Scout has loaded it, gateway healthy, 3 bots connected, `served_profiles` lists all three, `grep -c "scout_mail" profiles/{default,cafe-ia}/logs/agent.log` unchanged.
- E7 Push the branch and open a GitLab MR (draft, not merged). `report.md` in this folder, pushed with the branch.

## Acceptance criteria

| AC | Verification |
|---|---|
| AC1 single enabling commit, only the two values changed | `git show --stat` + diff in report |
| AC2 offline tests pass | pytest counts |
| AC3 check-mode diff matches runbook §3 | excerpt in report |
| AC4 deploy OK, `hermes_checks.py scout-mail` OK, second run `changed=0` | play recap excerpts |
| AC5 Scout loads the plugin, others don't; ledger armed | E6 outputs |
| AC6 no regression: 3 bots connected, gateway healthy | E6 outputs |

## Limits and security (hard)

- Never display, decrypt, view or edit the vault (`ansible-vault view/edit/decrypt` forbidden); the playbook reads it through `vault_password_file` only. Never print `.env` contents, the API key or `settings.json` beyond the `enabled` key.
- No call to AgentMail yourself, no mail sent, no Telegram message sent. The Telegram test is the owner's.
- No other hosts, tags or profiles; no `docker restart` by hand; the only restart is the playbook's.
- If anything fails after E5 started (deploy error, check failure, lockdown log), do NOT replay, roll back or disable on your own: the runbook §8.1 order applies (sessions retired before any disable). Stop, record the state, report BLOCKED.
- Commit only E1 and the mission files; no merge; no force push. Git remote must be `git@gitlab.com:tipunchlabs/homelab.git`.
- Model economy: mechanical checks may go to a cheaper subagent; list delegations in the report.

## Report

`report.md` (English): `Verdict:` PASS | PARTIAL | BLOCKED, `Version:` <enabling commit SHA>, AC table with evidence, before/after state, deployment time (UTC), what the owner must test in Telegram, rollback reminder (runbook §6 + §8.1). End your turn with the line: `report ready, Version = <sha>`.

## Pilot decisions

- No Codex review for this mission: a two-value configuration change of a design reviewed six times (MR !109); verification is the playbook's checks plus E6. The owner can ask for one.

## Decisions log

- 2026-11-24T16:20Z pilot, D1 (report BLOCKED on 88c8cf9, `test_role_04` pins the disabled state): option A. One test-only commit on this branch makes `test_role_04` follow the switch (`plugins.enabled == (["scout_mail"] if enabled else [])`, no hard `is False`), every other assertion kept. AC1 becomes "one enabling config commit + one test commit"; rollback = revert of the config commit alone, test still green after it. Reversible, no production effect, inside the owner's GO « activer et déployer »; the GO still covers E4–E6. Also note: the first `--tags hermes` run brings the whole plugin (MR !109 was never deployed), as runbook §1 expects.
