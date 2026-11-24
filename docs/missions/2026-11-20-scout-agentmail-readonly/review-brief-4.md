# Review brief 4 — SCOUT-MAIL-01 (pilotage → Codex) — EXTRA FINAL CYCLE

- Mission: `homelab/2026-11-20-scout-agentmail-readonly`
- Mission folder: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01/docs/missions/2026-11-20-scout-agentmail-readonly/`
- Owner decision 2026-11-23 (mission.md §7): one extra correction cycle beyond the cap, scoped to F7 and F8 of `review-3.md`, then this review. Merge, deployment and enabling stay owner decisions.
- Read first: `review-3.md` (F7, F8, R7, R8, reservations), `report.md` §M (fixes and tests for review 3) and §F, `evidence/m8-post-review-3-tests.md`; then `mission.md` (AC1–AC12) and `owner-brief.md` as needed.
- Version under review (exact code SHA): `1182fb53e31bb6c26268f3e7fde8bd37f874458a`
- Correction diff: `git -C /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01 diff b22ba76 1182fb5`. Branch HEAD `e9c7a72` adds on top `f55c226` (ADR, matrix, runbook for F7/F8) and `e9c7a72` (mission docs). Full feature diff: `3d7bf18..1182fb5`.
- Draft MR !109 (do not comment, do not push).
- Cycle: **4 (extra, final)**. No further cycle without a new owner decision.
- Output: write `review-4.md` in the mission folder, nothing else.

## Focus

1. F7 fixed at the root: after loss of security persistence (lockdown file and rename both refused), a repaired directory + restart must not give tools back to a potentially affected session or its compressed child, with a writable Hermes transcript DB. Check the new design does not rely on writing another file in the failed directory, the "other filesystem" and "nothing writable" branches, and that legitimate operator recovery (test_f7_05, runbook §8) is safe and consistent with the code. Rerun your R7 on 1182fb5.
2. F8 fixed at the root: the remaining absolute budget bounds every TCP candidate and the active connect, no new candidate after expiry; the custom deadline backend keeps F6 behaviour (TLS handshake, headers, body, connection release, no partial body) and fails closed on an unknown httpx/httpcore layout. Rerun your R8 on 1182fb5.
3. New tests fail on b22ba76 and pass on 1182fb5 (scratch extraction outside the worktree, removed at the end). Changed existing tests (test_f6_01, test_f6_02, test_f2_01) still test the same behaviour, not a weakened one.
4. Docs (`f55c226`, `e9c7a72`): ADR, threat-model matrix, runbook §8 and report §F/§M match the code; no overstatement left ("all fixed", "only name resolution").
5. Regressions across Scout-mail / Scout-normal / Nora / Kaféine; `hermes_scout_mail_enabled` still `false`; no secret in clear (vault header check only, never decrypt).

## Rules

- Same rules as review 3: run the deterministic tests yourself on 1182fb5 (`uv run --no-sync pytest …`, kafeine lab tests may be deselected, writable `ANSIBLE_LOCAL_TEMP`/`ANSIBLE_REMOTE_TEMP` under /tmp) and quote exact counts. No network, no hermes-31, no AgentMail, no model calls, no vault decryption.
- Live behavioural evaluation and the AgentMail read smoke test remain NOT_VERIFIED by design (owner steps after merge); judge only whether that is reported honestly.

## Required format of review-4.md

```
VERDICT: PASS | PASS_WITH_RESERVATIONS | CHANGES_REQUESTED
Version: 1182fb53e31bb6c26268f3e7fde8bd37f874458a
Reviewer: codex
```

Then: status of F7, F8 (and any regression of F1–F6), new findings `F<k> [blocker|major|minor] file:line — problem — expected fix` (continue at F9) each with command + result on this SHA, the AC1–AC12 table (AC, status, proof), and the reservations the owner must know before merging and enabling.
