# Mission: SCOUT-MAIL-01 — read-only AgentMail for Scout with enforced isolation

- Mission id: `homelab/2026-11-20-scout-agentmail-readonly`
- Pilot: Claude Code `pilotage` (agent-workflow, Herdr workspace w2D)
- Owner brief: 2026-11-20, verbatim in `owner-brief.md` next to this file. **It is the authoritative specification**; this file adds the workflow framing, acceptance-criteria mapping, limits and hand-off rules. If the two seem to disagree, the brief wins and you record the conflict in `report.md`.
- Worktree: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`, branch `feat/scout-agentmail-readonly` from `origin/main` `3d7bf18` (created by pilotage, upstream unset). Work only in this worktree. Do not touch the main checkout (`homelab/` has untracked `AGENTS.md`, `docs/missions/` belonging to the owner) or the other worktrees.
- Executor: this separate Claude Code session. Reviewer: Codex, **routed by pilotage** (you do not start a reviewer yourself). Review cap: 3 (= 2 correction cycles).

## 1. Expected result

A reviewable draft MR on GitLab `tipunchlabs/homelab` that lets the owner, from Scout's private Telegram conversation, ask Scout to list or summarize the job-search emails of exactly one configured AgentMail inbox, in French, with mail content structurally unable to reach Scout's privileged tools (Web, Kandidat, files, shell, delegation, memory) on that turn or any later one. Plus: threat model + enforcement matrix, tests, operator runbook (deploy preflight, check mode, rollback, kill switch, key revocation, post-deploy owner test), and `report.md`. Production unchanged.

## 2. Authorizations (from the owner brief, 2026-11-20)

Authorized without asking:
- Reading the repository, the installed Hermes source/pinned version, AgentMail and OWASP primary docs (context7 first, then WebFetch).
- Read-only SSH inspection of hermes-31 (config, versions, file hashes, process list, logs as counts/metadata). No restart, no file write on the host.
- Local implementation, fixtures, tests, lint; local `ansible-playbook --syntax-check` / `--check --diff` only if it neither decrypts a secret nor changes a host (otherwise skip and say so).
- Commit on `feat/scout-agentmail-readonly`, **push that branch and open a draft MR** (brief: « Commit and push the scoped branch and open a draft MR when available under repository policy »). Check `git remote -v` first (GitLab: `git@gitlab.com:tipunchlabs/homelab.git`).
- A small, bounded live adversarial model evaluation **with synthetic fixtures only**, through a local harness (not the production gateway), using the model/provider Scout is configured with, if a credential is legitimately available to you without decrypting the vault. Budget: at most 40 model calls in total for the whole mission, each bounded in tokens; record model id, version, settings, call traces (no secrets). If no credential is available: mark behavioral evaluation `NOT_VERIFIED` and prepare the exact owner command; never substitute string assertions.
- AgentMail **read-only** smoke test against the dedicated inbox **only after** its identity (inbox id/address) and key scope are confirmed and the key is provisioned by the owner. List/get only. Never send, reply, draft, label, mark read, delete, or call any write/admin endpoint, even to "test denial".

Not authorized (owner decisions, out of this mission): merge; production deployment (any `ansible-playbook` without `--check`, Hermes gateway restart, container restart); `ansible-vault` decrypt/edit or reading a denied vault password; sending email or Telegram messages; mutating the mailbox; touching Kandidat data; activating cron drafts; Hermes upgrade; HomeLab cleanup (including the KSR leftovers); a second bot.

## 3. Owner questions (do not ask the owner directly)

Inbox id/address and secret location are not given. First discover non-secret configuration locally (repo vars, host config, non-secret files). **Never infer the inbox from a name.** If something is still missing (inbox identifier, how/where the key is to be provisioned, whether the key has restricted scope), write it in `owner-questions.md` in this folder — one grouped block, each item with your recommendation and the exact secure provisioning command the owner would run (never ask for a secret value in chat) — tell pilotage in one line in your turn output, and **continue fixture-based work**. Pilotage relays to the owner and writes the answer back into this file's decisions log.

## 4. Acceptance criteria

| AC | Criterion | Verification |
| --- | --- | --- |
| AC1 | Discovery: actual Hermes version on hermes-31 vs repo pin; deployed Scout/Nora/Kaféine config hashes vs repo; how Hermes registers tools per profile and per request (global registry or not), how conversation history is built and persisted, how MCP tools and `readOnlyHint` are used; AgentMail exact operations, scopes/permissions model, read side effects (e.g. does `get message` mark read), pagination, rate limits, redirect/host behavior | `evidence/d1-discovery.md` with file:line in installed Hermes source and doc URLs + retrieval dates |
| AC2 | Design decision: chosen architecture with justification, explicitly answering: where untrusted mail is interpreted, what capabilities that context has, how its output reaches Telegram, and whether mail-derived text can enter Scout's ordinary history and influence a later privileged turn (and how that is prevented or neutralized). Rejected alternatives in one line each. If Hermes cannot provide the boundary: disabled prototype + precise architectural blocker | `docs/` design note in the repo + section in `report.md` |
| AC3 | Threat model + enforcement matrix (asset, attack path, control, enforcement location, test, residual risk) covering indirect prompt injection, excessive agency, information disclosure, memory poisoning, unsafe output rendering, SSRF, resource exhaustion; each control tagged *enforced in code* vs *behavioral* | matrix file in the repo; every "test" cell points to an existing test id |
| AC4 | Brief validation cases 1–10 implemented as tests asserting executed operations, denied calls, network attempts, persistence (not refusal wording); deterministic tests separated from live model evals | pytest output with exact counts; case → test id table in `report.md` |
| AC5 | Per-request isolation proven (no global registry mutation): concurrency, cancellation, exception then retry, across Scout-mail / Scout-normal / Nora / Kaféine | dedicated tests (case 8) |
| AC6 | Hard limits configurable and enforced before model invocation (response bytes, MIME, messages/request, pages, body/subject length, total context, model calls, retries, wall-clock); defaults justified by a representative fixture run with measured sizes/timings | fixture-run numbers in `report.md` |
| AC7 | Secrets: existing secret pattern (vault var name(s) only, 0600 files, `no_log`), sentinel-credential redaction test, no raw mail/key in Git, CI, Ansible diff, report | test + `git grep` of sentinels + diff review |
| AC8 | Existing behavior preserved: existing hermes/profile/MCP tests and repo checks pass; Kandidat gates, Scout Web/job-search, Nora, Kaféine configs unchanged except the minimal intended change; cron drafts untouched. Unrelated intermittent failures (known: intermittent `hermes/tests` failure from KSR) documented, not hidden | test outputs, diff of role defaults/templates |
| AC9 | Operator runbook: required variable names, effective exposed tools, preflight, `--check --diff`, deploy, kill switch, rollback to prior profile behavior, key revocation, post-deploy owner test (summarize inbox; injected test mail cannot trigger Web/Kandidat/send; Nora/Kaféine normal; second Ansible run idempotent), owner procedure to place a synthetic email; owner-visible behavior vs tool-trace evidence distinguished | runbook file in the repo |
| AC10 | Behavioral eval: small adversarial live run with documented model/version/settings and traces, or `NOT_VERIFIED` with the reason and owner command | `evidence/` + `report.md` |
| AC11 | Branch pushed, draft MR opened (or precise blocker), CI state recorded; production unchanged (verified: hermes-31 config hashes after = before) | MR URL, pipeline id/status, hash comparison |
| AC12 | `report.md` per brief (objective, verdict PASS/PARTIAL/BLOCKED, architecture, enforced vs behavioral controls, evidence and limits, risks, Git/MR/CI, production changes = none, secret provisioning status, deployment readiness, essential owner decisions), with header lines `Verdict:` and `Version:` = commit SHA of the delivered branch head | file |

No OWASP certification claim; no claim of complete injection prevention.

## 5. Steps

| Step | Goal | Deliverable |
| --- | --- | --- |
| M1 | Discovery (AC1). Start from the homelab `CLAUDE.md`/`AGENTS.md`, `hermes/` role and tests, the KSR release mission (`/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-ksr/docs/missions/2026-11-14-kandidat-scout-release/`) and the paused state-inventory evidence (`/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-etat/docs/missions/2026-11-20-hermes-scout-etat/evidence/`, uncommitted, read-only for you — re-verify, do not trust). Write `owner-questions.md` as soon as a real gap is known | `evidence/d1-discovery.md` |
| M2 | Design + threat model + enforcement matrix (AC2, AC3). Stop condition: if the only possible design needs a production-affecting decision not covered in §2 (e.g. a Hermes upgrade or patching vendored Hermes code in a way that changes other profiles), write it in `owner-questions.md`, then continue with the disabled-prototype path | design note, matrix |
| M3 | Implementation + fixtures + tests (AC4–AC8) | code, tests, outputs |
| M4 | Runbook, behavioral eval (AC9, AC10) | runbook, evidence |
| M5 | Commit, push, draft MR, CI, `report.md` (AC11, AC12). Then stop and say in one line: report ready, Version = <sha> | `report.md` |
| M6 | Codex review routed by pilotage; corrections in this same session on request | `review-N.md` (Codex) |

M1→M5 without waiting, except for real owner questions (§3), which do not block fixture work.

## 6. Hygiene

- Model economy (owner decision 2026-11-16): keep design, security reasoning and product code on your session model; delegate mechanical work (running test suites, collecting command output, hashing, log counting, doc retrieval summaries, evidence manifests) to Sonnet or Haiku subagents. List each delegation (task, subagent model) in `report.md` and confirm your own session model.
- Privacy: Scout serves the owner's job search. No real email content, contact, company from the owner's search, transcript or secret in Git, evidence or report: synthetic fixtures only; metadata/counts for anything live. Private notes if ever needed: `~/.local/share/homelab-reports/scout-agentmail/` (0600), pointed to only.
- Host commands: short, bounded, read-only, `nice` for anything heavy; no process left behind. Local servers or harnesses you start, you stop.
- Token budget: keep discovery reads targeted (grep, line ranges); do not re-read large files repeatedly.
- Git: Conventional Commits; no commit on `main`; do not rewrite history of other branches; do not delete worktrees or branches.

## 7. Decisions log

- 2026-11-20 — Owner brief SCOUT-MAIL-01 received (verbatim `owner-brief.md`). Authorizes development, push of the scoped branch and a draft MR; excludes merge, production deploy, email sending, subscriptions.
- 2026-11-20 — Pilot framing: worktree `homelab-mail01` / branch `feat/scout-agentmail-readonly` from `origin/main` 3d7bf18; live model eval capped at 40 calls, synthetic fixtures, local harness only; Codex review routed by pilotage (cap 3).
- 2026-11-23 — Owner decision after review-3 (CHANGES_REQUESTED on b22ba76, cap 3/3 reached): « faire f7 f8 et finaliser la mission ». Authorizes one extra correction cycle (4, beyond the cap) scoped to F7 and F8 of `review-3.md`, their documentation (runbook §8, ADR/matrix, report §F/§L claims), and a 4th Codex review. Merge of MR !109, deployment and enabling stay owner decisions.
- 2026-11-23 — Owner decisions after review-4 (CHANGES_REQUESTED on 1182fb5): (a) one more correction cycle (5, beyond the cap) scoped to F9 (short state write treated as persisted lockdown) and F10 (runbook recovery order) of `review-4.md`, then a 5th and last Codex review; (b) D5 accepted: the residual where no write at all is possible on the volume (lockdown held in memory until restart, operator must retire Scout sessions before any restart) is an accepted risk, provided the runbook recovery order is corrected (F10). Merge, deployment and enabling stay owner decisions.
- 2026-11-23 — Owner decision after review-5 (CHANGES_REQUESTED on 18af837): « 6ᵉ cycle ». Authorizes one more correction cycle (6) scoped to F11 of `review-5.md` (recovery inventory must cover every Scout session, hidden/archived included, tested through the real Hermes CLI), then a 6th Codex review. Merge, deployment and enabling stay owner decisions. Owner also discussed a later V2 « controlled bridge » (structured, code-validated fields from the isolated reader + owner confirmation per action): out of this mission's scope, separate mission if requested.
