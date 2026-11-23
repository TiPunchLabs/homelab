# Review brief 3 — SCOUT-MAIL-01 (pilotage → Codex) — FINAL CYCLE

- Mission: `homelab/2026-11-20-scout-agentmail-readonly`
- Mission folder: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01/docs/missions/2026-11-20-scout-agentmail-readonly/`
- Read first: `review-2.md` (your findings on edcd9fe: F1/F2 partial, F3 fixed, F4–F6), `report.md` §L (executor's fixes and tests for review 2), §F residual risks; then `review-1.md`, `owner-brief.md`, `mission.md` (AC1–AC12) as needed.
- Version under review (exact code SHA): `b22ba76472d3884e24a2954e40ec7e2b4793b040`
- Correction diff: `git -C /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01 diff edcd9fe b22ba76` (15 files). Branch HEAD `97a09c4` adds on top: `53c0f8c` was before b22ba76 (inbox id + one test line), `225fc3a` (encrypted vault file only, owner-provisioned key), `97a09c4` (mission docs). Full feature diff: `3d7bf18..b22ba76`.
- Draft MR !109 (do not comment, do not push).
- Cycle: **3 of max 3 (final)**. After this review, any remaining gap goes to the owner.
- Output: write `review-3.md` in the mission folder, nothing else.

## Focus

1. F4, F5, F6 and the residual parts of F1, F2: fixed at the root on b22ba76, not only for the tested case? Do the new tests fail on edcd9fe and pass on b22ba76 (scratch checkout outside the mission worktree, e.g. `git worktree add` in a temp path, removed at the end)?
2. Lockdown/recovery path (report §F residual F4, runbook §8): persistence when the ledger directory refuses writes, start-up probe, operator recovery steps documented and consistent with the code.
3. HTTPS deadline (F6): the watchdog bounds the whole request including TLS setup and the streamed body; cancellation releases the connection; no partial body reaches the model.
4. Inbox id commit `53c0f8c`: only the clear-text identifier, `hermes_scout_mail_enabled` still `false`; no secret in clear in the repository (`git grep` on the branch for key-like strings; the vault file `225fc3a` must start with `$ANSIBLE_VAULT;1.1;AES256` — check the header only, **never decrypt it**).
5. Regressions across Scout-mail / Scout-normal / Nora / Kaféine and report claims in §L and the AC table vs code on b22ba76.

## Rules

- Run the deterministic tests yourself on b22ba76 (`uv run pytest hermes/tests …` as the report states; you may deselect the hanging `test_m7_kafeine` lab tests as the report does, and say so) and quote exact counts. No network, no hermes-31 access, no AgentMail, no model calls, no vault decryption.
- Behavioral (live model) evaluation and the AgentMail read smoke test remain NOT_VERIFIED by design (owner steps after merge); judge only whether that is reported honestly.

## Required format of review-3.md

```
VERDICT: PASS | PASS_WITH_RESERVATIONS | CHANGES_REQUESTED
Version: b22ba76472d3884e24a2954e40ec7e2b4793b040
Reviewer: codex
```

Then: status of F1–F6 (fixed / partially / not, with evidence), new findings `F<k> [blocker|major|minor] file:line — problem — expected fix` (continue numbering at F7) each with command + result on this SHA, the AC1–AC12 table (AC, status, proof), and the reservations the owner must know before merging and enabling.
