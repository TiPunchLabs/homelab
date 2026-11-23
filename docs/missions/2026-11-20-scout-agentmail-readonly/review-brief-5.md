# Review brief 5 — SCOUT-MAIL-01 (pilotage → Codex) — LAST CYCLE

- Mission: `homelab/2026-11-20-scout-agentmail-readonly`, mission folder `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01/docs/missions/2026-11-20-scout-agentmail-readonly/`.
- Owner decisions 2026-11-23 (mission.md §7): cycle 5 beyond the cap, scoped to F9 and F10 of `review-4.md`; **D5 accepted by the owner** (all-writes-fail residual: lockdown held in memory until restart, operator retires Scout sessions before any restart). Do not flag D5 itself as a defect; check it is reported as owner-accepted (not as fixed) and that the recovery procedure makes that acceptance safe. Merge, deployment and enabling stay owner decisions.
- Read first: `review-4.md` (F9, F10, R9, R10, reservations), `report.md` (review-4 section, §F, §I), `evidence/m9-post-review-4-tests.md`.
- Version under review (exact code SHA): `18af8373aca7cf18098ea55748f9f839d1b4189a`. Correction diff: `git -C /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01 diff 1182fb5 18af8373aca7cf18098ea55748f9f839d1b4189a`. Branch HEAD `b80890a` adds `4b7f403` (runbook order, ADR, matrix) and `b80890a` (mission docs). Full feature diff: `3d7bf18..18af8373aca7cf18098ea55748f9f839d1b4189a`.
- Draft MR !109 (do not comment, do not push). Cycle: **5 (last)**. Output: `review-5.md` only.

## Focus

1. F9 fixed at the root: every state write checked and completed (short write = failure → not-persisted path + warning); short/invalid/unknown existing state treated as restricted at startup and never overwritten with ARMED; rerun your R9 on 18af8373aca7cf18098ea55748f9f839d1b4189a; new tests fail on 1182fb5 and pass on 18af8373aca7cf18098ea55748f9f839d1b4189a (scratch extraction outside the worktree, removed at the end). Check no regression of F7 normal repair case and F1–F8.
2. F10 fixed: runbook §8 (and §6 consistency) gives a safe order — stop inbound/active processing, retire all Scout sessions while protection is loaded or the gateway is stopped, only then unload hooks / clear markers / apply a restarting deployment; staging vs restarting apply distinguished; the test that checks the order really checks it. Rerun R10.
3. Docs (ADR, matrix, report §F/§I) consistent with code; D5 recorded as owner-accepted residual; no overstatement.
4. Regressions and secrets as in review 4: plugin suite, image tests, full hermes suite (kafeine lab deselected, writable ANSIBLE_LOCAL_TEMP/REMOTE_TEMP under /tmp); `hermes_scout_mail_enabled` still false; vault header only, never decrypt. Quote exact counts. No network, hermes-31, AgentMail or model calls.

## Required format of review-5.md

```
VERDICT: PASS | PASS_WITH_RESERVATIONS | CHANGES_REQUESTED
Version: 18af8373aca7cf18098ea55748f9f839d1b4189a
Reviewer: codex
```

Then status of F9, F10 (and any regression of F1–F8), new findings from F11 with command + result on this SHA, the AC1–AC12 table, and the reservations the owner must know before merging and enabling.
