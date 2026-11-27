# Mission — Scout creates and manages its own scheduled tasks, safely

- Mission id: `homelab/2026-11-24-scout-self-cron`
- Worktree: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-scoutcron`, branch `feat/scout-self-cron` from `origin/main` `975e302` (MR !110 merged: Scout mail enabled and deployed).
- Pilot: pilotage (Claude Code). Executor: one Claude Code session in this worktree. Reviewer: Codex. Owner: Xavier.
- Repository is PUBLIC: no personal data in commits (see `owner-request.local.md`, excluded from git).

## Owner request (quoted, 2026-11-24)

« non je veux que scout puisse le faire ? quel est le risque » then, after the pilot's risk summary, « oui cadre la mission ». The use case: the owner sends Scout, in Telegram, a request to create or update a weekday job-alert task (text in `owner-request.local.md`, private) and Scout saves it, verifies it is active and gives its next run in Guadeloupe time.

## Context (pilot findings, verify them)

- Scout (`hermes_profile_job_search`, `hermes/ansible/group_vars/hermes/all/main.yml`) has `cronjob` in `agent.disabled_toolsets` (design decision D5: crons are created by the operator, M4.4). M4.4 never happened; `hermes/cron-drafts/job-search.yml` is inactive; no cron runs on hermes-31 (README « Cron drafts (M4.4, not created) », procedure stale since 2026-10-23).
- Cron platform toolsets for Scout today: `web`, `skills`, `memory`; MCP `kandidat` (read-only) declared for `cron` in `mcp_policy`. `memory.write_approval: true` → memory writes in an unattended run wait for an approval nobody gives. `session_search` is not in the cron toolsets (dedup of past alerts).
- Container clock is UTC; Guadeloupe is UTC−4 all year (no DST): 07:00 AST = 11:00 UTC.
- Scout mail plugin (`scout_mail`) already vetoes every tool in a mail-tainted session through a `pre_tool_call` hook (`docs/references/scout-mail-threat-model.md` T3/T6). Plugin hooks are therefore an available enforcement point.

## Threat model to address (summary given to the owner)

Scout reads untrusted text (job pages, employer sites, mail). With the ability to schedule, an injected instruction could become persistent and run daily unseen: Tavily quota and model cost, Telegram spam, exfiltration of the private context (`agent.environment_hint`) through queries or fetched URLs, a scheduled job creating further jobs. Limits that stay: no terminal, no files, Kandidat read-only in cron, delivery by Scout's bot.

## Expected result

In a Telegram conversation with the owner, Scout can create, update in place, list, pause, resume and delete its own scheduled tasks, under these guards (each enforced in code where Hermes allows it; say precisely which ones rely only on prompt/SOUL):

- G1 Scheduling tools exist only on the `telegram` platform of `job-search`; never in `cron`, `api_server` or `cli` runs, never in Nora (`default`) or Kaféine (`cafe-ia`). A scheduled run can never create or change a job.
- G2 Explicit owner confirmation in the conversation before every create/update/delete, showing name, schedule in Guadeloupe time and UTC, delivery target and the full saved instructions; no confirmation → nothing saved. Prefer a technical gate (plugin `pre_tool_call` hook or Hermes approval mechanism) over a SOUL rule.
- G3 Limits: at most N active jobs for Scout (propose N, default 5), at most one run per day per job, delivery only to the owner's allowlisted Telegram chat, bounded prompt size.
- G4 Mail-tainted sessions cannot schedule (already true via `scout_mail`; prove it with a test).
- G5 Unattended runs can keep a short persistent per-task record (read at start, updated at end) and avoid re-sending vacancies already alerted, without a human approval step and without widening anything else (no file/terminal). Propose the mechanism (e.g. scoped memory without approval for cron only, a plugin-owned ledger, `session_search` in cron, Kandidat read). Writes to Kandidat stay forbidden in cron.
- G6 Existing behaviour unchanged: Scout mail guards, Kandidat gates and tool matrices, Nora and Kaféine configs, no cron created by the deploy itself.

## Steps

- E0 Discovery (read-only): Hermes v0.22.5 (image `nousresearch/hermes-agent:v0.22.5` locally if present, else source) — `cronjob` toolset: tools and actions, schedule syntax and timezone support, storage (`jobs.json` per profile), delivery targets and how they are validated, whether a job stores its own toolsets/model, existing approval or hook points usable for G2/G3, behaviour after a gateway restart (README « restart » section). hermes-31: read-only state of Scout's `cron/` (job list, none expected). Write `design.md` (findings with file:line, design for G1–G6, what is code-enforced vs prompt-only, alternatives rejected). Material choices → list them as decisions with a recommendation.
- Checkpoint: stop after `design.md`, end your turn with `design ready`. The pilot reviews it and may ask the owner; do not implement before the pilot's go.
- E1 Implementation on the branch (Ansible role, group_vars, plugin or hook code, SOUL text if needed, `hermes_checks.py` deployment check for G1/G3), Conventional Commits.
- E2 Tests: unit tests plus image/lab tests on the real Hermes image (no hermes-31): create/update/list/pause/delete through Telegram-like turns, refusal without confirmation, refusal in cron/api_server/cli platforms and other profiles, limit N, daily cap, delivery restriction, tainted-session refusal, a scheduled run that writes and reads its record and deduplicates, restart persistence. Full suite `uv run pytest hermes/tests -q`, exact counts.
- E3 Check mode only: `ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes --check --diff` from `hermes/` — record the expected diff. No deployment.
- E4 Runbook: `docs/guides/runbook-scout-cron.md` (English and French as the repo's docs require; check the repo convention), with enable, owner Telegram test, inspect/pause/remove a job by the operator, rollback. Update the README's stale M4.4 section.
- E5 Push the branch, open a draft GitLab MR. `report.md` in this folder.

## Acceptance criteria

| AC | Verification |
|---|---|
| AC1 G1 platform scoping | config diff + lab tests per platform/profile |
| AC2 G2 confirmation gate | lab test: create without confirmation refused, with confirmation saved; enforcement type stated |
| AC3 G3 limits | lab tests: N+1th job refused, sub-daily schedule refused, foreign delivery target refused |
| AC4 G4 tainted session refused | lab test |
| AC5 G5 persistent record + dedup in unattended runs | lab test over ≥ 2 runs |
| AC6 G6 no regression | full suite counts; Scout mail, Kandidat, Nora, Kaféine tests green; check-mode diff limited to the intended changes |
| AC7 restart: jobs survive a gateway restart without an immediate extra run | lab test or Hermes evidence |
| AC8 runbook + rollback documented | files |

## Limits and security (hard)

- No deployment, no gateway/container restart, no `ansible-playbook` without `--check` on hermes-31, no cron created on hermes-31. Deployment is a separate owner decision after review.
- Never display, decrypt, view or edit the vault; never print `.env`, API keys, the environment hint or `settings.json` secrets.
- No Telegram message, no mail, no AgentMail call, no Kandidat write.
- Never commit `owner-request.local.md` nor copy personal criteria (location, background) into committed files, fixtures, logs or the MR.
- Git remote must be `git@gitlab.com:tipunchlabs/homelab.git`; no merge, no force push.
- Model economy: mechanical checks (test runs, log parsing, evidence) may go to a cheaper subagent; security design and enforcement code stay on your model. List delegations and your own model in the report.

## Report

`report.md` (English): `Verdict:` PASS | PARTIAL | BLOCKED, `Version:` <product commit SHA>, AC table with evidence, enforcement matrix (guard → code/prompt → test), check-mode diff summary, what the owner must test in Telegram after deploy, rollback. End your turn with the line: `report ready, Version = <sha>`.

## Review

Codex review after the report (max 3 cycles), brief by the pilot. Deployment and merge: owner decisions.

## Decisions log

- 2026-11-24 pilot: base `origin/main` 975e302 (includes the deployed Scout mail enablement, so a later deploy from this branch keeps mail on).
- 2026-11-24T19:34Z pilot, design.md (E0) reviewed: GO for E1-E5 with every recommendation D1-D13 as written (new plugin scout_cron with its own switch; native approval gate + verbatim proposal + nonce rule_key, fail closed on /yolo or approvals off; timezone America/Guadeloupe on Scout only, verified in E2; N=5 incl. paused; fixed minute+hour cron only; run/run_now/trigger blocked; field policy as G3; G5 via scout_task_record (notepad journal + plugin ledger); D9 narrow Scout cron toolsets to web, skills, kandidat, scout_task_record — pilot decision: no cron runs exist today, narrowing only, reversible, the owner is informed and may override before review; D10 feedback_add under G2; D11 cap 40/20; D12 catch_up_missed default; D13 runbook English only per repo convention). Extra requirements: (a) the proposal must never be posted when another hook (scout_mail taint) vetoes the call — test it; (b) any open point of design §7 that fails in E2 → stop and report, do not widen; (c) pre-existing finding « Scout memory writes without approval in Telegram sessions » is out of scope: record it in report.md as a follow-up for the owner, do not change it.
