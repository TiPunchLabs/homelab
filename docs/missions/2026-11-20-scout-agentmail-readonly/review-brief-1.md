# Review brief 1 — SCOUT-MAIL-01 (pilotage → Codex)

- Mission: `homelab/2026-11-20-scout-agentmail-readonly`
- Mission folder: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01/docs/missions/2026-11-20-scout-agentmail-readonly/`
- Read first: `owner-brief.md` (authoritative spec), `mission.md` (AC1–AC12), `report.md` (executor, Verdict PARTIAL), `owner-questions.md`, `evidence/`.
- Version under review (exact SHA): `78ee2eee3593f25f792793d855dd30cdbc0e6efb`
- Diff: `git -C /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01 diff 3d7bf18 78ee2ee` (26 files, +3438/−3). Later commits `1b27f9f`, `a9e4a81` only add mission docs/evidence.
- Draft MR: !109 (do not comment on it, do not push).
- Cycle: 1 of max 3.
- Output: write `review-1.md` in the mission folder, nothing else.

## Focus (owner brief)

1. Permission bypass: can the mail path reach any non-read AgentMail operation, another inbox, another host, or any Scout tool (Web, Kandidat, files, shell, delegation, memory)? Is the inbox bound in trusted config; are ownership checks on message ids real?
2. Mail-to-privileged-context handoff: can mail-derived text (summary included) enter Scout's ordinary conversation history or context and influence a later privileged turn? Check the actual Hermes code paths (file:line), not the design note.
3. Multi-profile concurrency: no global registry mutation; isolation across Scout-mail / Scout-normal / Nora / Kaféine, including cancellation and exceptions.
4. Secrets: key only in the component that needs it; no leak in prompts, logs, tracebacks, Ansible diff (`no_log`), fixtures, evidence, report.
5. Unintended writes: no mailbox state change (read flags, labels), no persistence of raw mail, no SOUL/config/memory/Kandidat writes; production unchanged.
6. Also: hard limits enforced before model invocation; SSRF/egress (redirects, no URL/attachment fetch); Telegram rendering (escaping, link previews off); tests assert real effects (operations, denied calls, network attempts, persistence) rather than wording; claims in `report.md` match the code.

## Rules

- Run the deterministic tests yourself on the SHA (`uv run pytest hermes/tests …` as the report states) and quote exact counts. No network, no hermes-31 access, no AgentMail, no model calls.
- Behavioral (live model) evaluation is NOT_VERIFIED by design (no credential); judge only whether that is reported honestly.

## Required format of review-1.md

```
VERDICT: PASS | PASS_WITH_RESERVATIONS | CHANGES_REQUESTED
Version: 78ee2eee3593f25f792793d855dd30cdbc0e6efb
Reviewer: codex
```
Then findings `F<k> [blocker|major|minor] file:line — problem — expected fix`, each with evidence (command + result on this SHA), then an AC1–AC12 table (AC, status, proof).
