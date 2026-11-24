# Review brief 2 — SCOUT-MAIL-01 (pilotage → Codex)

- Mission: `homelab/2026-11-20-scout-agentmail-readonly`
- Mission folder: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01/docs/missions/2026-11-20-scout-agentmail-readonly/`
- Read first: `review-1.md` (your findings F1–F3 on 78ee2ee), `report.md` §K (executor's fixes and tests), then `owner-brief.md` and `mission.md` (AC1–AC12) as needed.
- Version under review (exact SHA): `edcd9fe70508f51ad2d06bc84ea3322f11ad5c12`
- Correction diff: `git -C /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01 diff 78ee2ee edcd9fe` (21 files, +1711/−98). Later commit `2a12a2a` only adds mission docs. Full feature diff: `3d7bf18..edcd9fe`.
- Draft MR !109 (do not comment, do not push). CI on the branch: pipeline 3096025993 success (pilot observation via glab; not re-checkable offline).
- Cycle: 2 of max 3.
- Output: write `review-2.md` in the mission folder, nothing else.

## Focus

1. F1, F2, F3: is each fixed on edcd9fe, at the root (not only for the tested case)? Do the new tests fail on 78ee2ee and pass on edcd9fe (run them against both if feasible, e.g. `git worktree add` in a scratch path or `git stash`-free checkout in a temp dir — never modify the mission worktree)?
2. Regressions introduced by the fixes: the new taint/session record (F1) — persistence location, permissions, growth bound and behaviour when full (report says a "record full" operator path exists), concurrency across Scout-mail / Scout-normal / Nora / Kaféine, no global registry mutation; streaming ceiling (F2) — cancellation releases the connection, no partial body reaches the model; context cap (F3) — counts system prompt + prefix, enforced before model invocation.
3. Removed setting `retention_days`: no remaining reference in role defaults, templates, docs, tests.
4. Report claims in §K and the AC table match the code on edcd9fe.

## Rules

- Run the deterministic tests yourself on edcd9fe (`uv run pytest hermes/tests …` as the report states) and quote exact counts. No network, no hermes-31 access, no AgentMail, no model calls.
- Behavioral (live model) evaluation and AgentMail smoke test remain NOT_VERIFIED by design (owner inputs Q1–Q4 pending); judge only whether that is reported honestly.

## Required format of review-2.md

```
VERDICT: PASS | PASS_WITH_RESERVATIONS | CHANGES_REQUESTED
Version: edcd9fe70508f51ad2d06bc84ea3322f11ad5c12
Reviewer: codex
```
Then: status of F1–F3 (fixed / partially / not, with evidence), new findings `F<k> [blocker|major|minor] file:line — problem — expected fix` (continue numbering at F4) each with command + result on this SHA, then the AC1–AC12 table (AC, status, proof).
