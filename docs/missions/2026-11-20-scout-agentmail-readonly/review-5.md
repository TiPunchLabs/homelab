VERDICT: CHANGES_REQUESTED
Version: 18af8373aca7cf18098ea55748f9f839d1b4189a
Reviewer: codex

## Status of F9, F10 and previous findings

- **F9: fixed.** `_write_block` accounts for every returned byte count, rejects stalled/invalid counts, fsyncs and verifies the complete readback. Short writes that eventually complete are valid persisted writes; incomplete/unverified writes take the fallback/warning path. New-state creation uses a fully written temporary file and a non-replacing link. Existing state is never rewritten at startup; anything other than the exact armed block remains restrictive. My original R9 now returns `state_recognized_locked=True`, with parent and compressed-child tools blocked after repair/restart. The malformed-state and interrupted-write regressions pass, including the real Hermes SessionDB image case.
- **F10: ordering repaired, recovery completeness still fails F11.** §6 distinguishes staging from applying. §8.1 now orders Hold → Repair → Stage → Retire → Clear → Apply → Verify; retirement precedes removing markers or unloading/restarting. The rewritten synthetic test really traverses those document steps and checks protection at each stage, an improvement over its previous comment-only retirement. However, its Retire handler uses unconditional SQL deletion of synthetic messages, whereas the actual procedure discovers IDs through a filtered CLI list. The real CLI can say “No sessions found” while old Scout sessions remain. That breaks the recovery's retirement postcondition, independently of the corrected ordering.
- **F1–F8: no regression detected in the established cases.** Permanent provenance, reserved result IDs, context accounting, cancellation/failure handling, per-profile scoping and TCP/TLS deadlines retain passing coverage. The ordinary F7 permission-repair case stays restricted. **D5 is owner-accepted, not fixed and not raised as a defect here.** Its all-writes-fail limitation and pre-restart retirement obligation are recorded as accepted in mission §7, report §F/§I/§N and the runbook. F11 below uses a fully persisted lockdown, so it does not depend on D5's failure mode.

Independent targeted results: **125 plugin tests passed**, **7 image tests passed**, and **20 F7–F10 instances passed**. Against 1182fb5 with its reviewed f55c226 runbook and the final tests copied unchanged into a temporary extraction: **12 failed / 8 passed**; image comparison **1 failed / 6 passed**. These match the reported red/green evidence. F9's old failures include lost restrictions and missing warnings; the two recovery-test failures reflect the missing ordered §8.1 in the old document.

## Findings

- **F11 [major] docs/guides/runbook-scout-mail.md:133 — The recovery's “sessions list is empty” check does not establish that every Scout session has been retired.** The pinned Hermes CLI's `sessions list` calls `list_sessions_rich` without enabling archived or hidden rows. Its default listing is also limited to 20 and excludes tool-source rows; increasing that limit alone does not fix the hidden/archive filters. I created one hidden and one archived Telegram session in Scout's real profile SessionDB, each with synthetic mail-derived history. The exact documented command, `hermes -p job-search sessions list`, exited 0 and printed **“No sessions found.”** Both sessions and both messages remained. After the documented Clear step and plugin reconstruction for Apply, the existing hidden session and its compressed child returned **no tool veto**. The lockdown had been fully persisted beforehand: this is **not** the owner-accepted D5 residual. The new synthetic recovery test cannot catch it because `test_scout_mail.py:1551` deletes every synthetic message directly instead of testing CLI discovery/deletion. This fails AC9's safe recovery and the subsequent-context boundary it is meant to preserve under AC2. **Expected fix:** inventory all profile session rows, including hidden/archived contexts and applicable lineages, retire them through supported Hermes operations that preserve its active-turn guards, and verify an authoritative zero-session postcondition before clearing protection. Do not substitute a larger CLI limit for complete enumeration. Add a real SessionDB/CLI recovery regression with hidden and archived sessions. Evidence: R11 below, `docker run --rm --network none …` → exit 0 on the mounted reviewed code: durable lockdown true; CLI exit 0 / no sessions found; **2 sessions and 2 messages remain**; parent/child vetoes both `None`. No real session or privileged operation was touched. The runbook is the requested 4b7f403 documentation revision, identical at HEAD.

## Acceptance criteria

`NOT_VERIFIED` includes demonstrated defects, identified explicitly, and unavailable checks. The verdict is caused by F11, not by D5, intentionally unavailable live evaluation or lack of production access.

| AC | Status | Proof on the reviewed version |
|---|---|---|
| AC1 | NOT_VERIFIED | Discovery/API evidence remains present with dated references. Local pinned-image source and actual CLI/SessionDB behaviours independently inspected. Actual hermes-31 version/config hashes, current provider documentation and permission/read-state facts not retrieved under the offline brief. |
| AC2 | NOT_VERIFIED | Normal mail path stays tool-less with trusted direct delivery and later-turn restrictions; F9 repair independently verified. D5 accepted as specified. **F11 leaves old contexts alive when the documented recovery clears their protection**, even following a fully persisted lockdown. |
| AC3 | NOT_VERIFIED | Matrix has **71 test-column references, all existing**, and separates code enforcement from behaviour. It reports D5 as accepted rather than repaired. Recovery's claim to retire every Scout session is not supported by the actual CLI inventory (F11). |
| AC4 | NOT_VERIFIED | **125 plugin / 7 image tests pass**; **20 focused tests pass**, with independent old/new red/green comparison. The recovery model checks ordering and refusal but replaces actual retirement with `delete from messages`; it omits the real CLI filters exposed by R11. No model behaviour inferred from deterministic output. |
| AC5 | VERIFIED | Plugin tests cover concurrency, cancellation, exceptions and retry. Image tests exercise Scout-only command/hooks, no global registry mutation, **400 concurrent decisions** across Scout-mail/clean Scout/Nora/Kaféine, denied callers and history/ledger privacy. Actual live Telegram busy dispatch remains a stated limitation. |
| AC6 | NOT_VERIFIED | Field/byte/count/retry/context ceilings and TCP/TLS deadline regressions pass. Fixture contexts **4,460 / 17,201 / 19,977 chars**, request bytes **5,028 / 18,821 / 22,448**, two reply parts each. Complete wall-clock ceiling still excludes blocking DNS, explicitly disclosed; no new transport defect found. |
| AC7 | NOT_VERIFIED | Synthetic key redaction/routing tests pass; secret wiring unchanged (`no_log`, 0600 environment file). Key-pattern scan matches only synthetic definitions. Vault header checked only; no decryption/password/key access. Actual vault contents/provider scope, production logs and CI artifacts not independently inspected. |
| AC8 | NOT_VERIFIED | Fresh selected full suite: **849 passed, 27 skipped, 16 deselected, zero failures in 1,283.35 s** (892 collected). Includes current-image multiplex/Kandidat labs and all selected profile/mail tests. Skips require older image v2026.8.18; exclusions are 11 authorized Kaféine lab hangs and 5 vault/header-reading cases. No SOUL/profile-content/Kandidat gates/tool matrix/cron changes introduced by this correction; defaults and group-vars mail switches remain false. Repository-wide lint/hooks not rerun; executor evidence remains attributed. |
| AC9 | NOT_VERIFIED | Staging/applying split and Hold/Retire/Clear/Apply order repaired. Required preflight, rollback, revocation, synthetic owner tests and idempotence steps remain documented. **F11 invalidates Retire's empty-list postcondition**; park/unpark and live recovery are not exercised by the synthetic model. |
| AC10 | VERIFIED | Report/evidence honestly keep live behavioural evaluation and AgentMail smoke **NOT_VERIFIED**, with reason and owner command. Zero reviewer provider/model calls. Q1–Q3 and key scope remain owner-attested. |
| AC11 | NOT_VERIFIED | Local named commit and documentation-only successors verified. MR !109, remote CI and production hashes remain pilot/executor observations; no network refresh, push, comment, merge or deployment. |
| AC12 | VERIFIED | Report has PARTIAL verdict, correct code Version, architecture, enforcement/behaviour split, tests, limits, risks, secret/readiness state and owner decisions. D5 is explicitly accepted, not claimed fixed; recovery's synthetic-test/CLI limitation is disclosed. Own counts reproduce the targeted evidence. F11 is an additional result to carry into the owner handoff. |

## Commands run

Working directory: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`. `uv` commands use `PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/scout-review5-uv UV_OFFLINE=1`, `--no-sync`, and pytest `-p no:cacheprovider`. Ansible local/remote temporary paths are under `/tmp`. No permission escalation, source checkout/stash, worktree registration or registry mutation.

- Read AGENTS, brief 5, review-4 findings/context, mission §7, report §F/§I/§N, m9 evidence, correction source/tests, ADR/matrix and runbook. The owner explicitly accepted D5 on condition of corrected recovery; that accepted residual is not classified as a new defect.
- `git rev-parse HEAD` → exit 0, `b80890a23c393ecfcc0758ae62de0d0e004e8fa5`. Initial `git status --short` → exit 0, only pre-existing untracked `review-brief-5.md`.
- `git diff --quiet 18af837 HEAD -- hermes` → exit 0, executed code/tests equal the named SHA. `git diff --quiet 4b7f403 HEAD -- docs/adr/hermes.md docs/guides/runbook-scout-mail.md docs/references/scout-mail-threat-model.md` → exit 0. Code reviewed at 18af837; later requested documentation assessed at 4b7f403/b80890a, not misattributed to the code commit.
- `git diff --check 1182fb5 18af837` and `git diff --check 3d7bf18 18af837` → exit 0, clean. Source correction diff inspected directly; changes are persistence/startup handling and associated tests/image fixture, with later docs separately identified.
- `head -n 1 hermes/ansible/group_vars/hermes/vault/config.yml` → exit 0, `$ANSIBLE_VAULT;1.1;AES256`. No vault contents/decryption/password retrieval.
- `git grep -I -l -E '(^|[^[:alnum:]_])(am_[A-Za-z0-9_-]{24,}|sk-[A-Za-z0-9_-]{24,}|glpat-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,})|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' HEAD -- ':!**/vault/**'` → exit 0, only `test_scout_mail.py` and `test_scout_mail_role.py`, known synthetic fixture definitions; no credential values printed. This is a bounded pattern check, not proof against every secret format.
- `git grep -n 'hermes_scout_mail_enabled:' 18af837 -- hermes/ansible/group_vars/hermes/all/main.yml hermes/ansible/roles/hermes_agent/defaults/main.yml` → exit 0, both false. `git diff --name-only 3d7bf18 18af837 -- hermes/ansible/roles/hermes_agent/files/profiles` → exit 0, no profile-content changes. `git grep -n retention_days 18af837 -- hermes docs/adr docs/guides docs/references` → exit 1, no active references.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -rs` → exit 0, **125 passed in 28.53s**.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail_image.py -q -rs` → exit 0, **7 passed in 10.73s**, local pinned image, `--network none`.
- `docker image inspect nousresearch/hermes-agent:v0.22.5 --format '{{.Id}}'` → exit 0, `sha256:49b70739d2e8b4206fabf8b089f88337db73f8edaccb93e64b0836694ef10a03`; local package metadata confirms HTTPX **0.28.1**, httpcore **1.0.9**.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -k 'f7_ or f8_ or f9_ or f10_' --tb=short` → exit 0, **20 passed, 105 deselected in 0.70s** (overlaps the 125).
- Scratch red comparison via `.venv/bin/python -u -`: extract `git archive 1182fb5 hermes/ansible/roles/hermes_agent hermes/tests` under `TemporaryDirectory`; place `git show f55c226:docs/guides/runbook-scout-mail.md` at the matching scratch path; transplant only the final `test_scout_mail.py`, `test_scout_mail_image.py` and image lab unchanged. Child `python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail.py -q --tb=line -k 'f7_ or f8_ or f9_ or f10_'` → exit 1, **12 failed, 8 passed, 105 deselected in 1.01s**. Failures match m9 evidence: short-write state, incomplete-write warning cases, malformed-state restarts and missing ordered recovery section.
- Same scratch tree, `python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail_image.py -q --tb=line` → exit 1, **1 failed, 6 passed in 10.53s**: real SessionDB short-write restriction lost. Orchestrator exits 0 after reporting child exits; temporary extraction removed automatically. No compatibility edits or mission-worktree source changes.
- `ANSIBLE_LOCAL_TEMP=/tmp/scout-review5-local ANSIBLE_REMOTE_TEMP=/tmp/scout-review5-remote timeout -s INT -k 5 1500 uv run --no-sync pytest -p no:cacheprovider hermes/tests -q -rs --durations=10 -k 'not (test_m7_kafeine and test_lab_) and not test_effective_ and not test_t15_effective_value_is_cafe_ia_then_job_search and not test_n01_prerequisites_are_never_created'` → exit 0, **849 passed, 27 skipped, 16 deselected in 1,283.35s** (892 collected). The 27 skips require older image v2026.8.18; 11 Kaféine lab cases and 5 vault/header-reading cases are excluded deliberately. Slowest current-image fixtures: multiplex **367.96s**, Kandidat **171.45s**. This overlaps targeted runs; pass counts are not added together. No permission escalation or vault resolution needed.
- Original R9 rerun, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -` → exit 0: three-byte writes completed, `state_recognized_locked=True`, one synthetic transcript row, parent/child blocked after repair/restart. Uses actual constructor and real 0500 permissions; no wire/model operation.
- R10 recheck against actual §8.1 → exit 0, `['Hold','Repair','Stage','Retire','Clear','Apply','Verify']`, `retire_before_clear_apply=True`. The two focused recovery tests pass; this establishes ordering, not actual CLI inventory completeness.
- Python AST comparison of matrix test-column names with pytest functions → exit 0, **71 references, none missing**.
- `uv run --no-sync python -` capturing JSON from `scout_mail_fixture_run.py` → exit 0, contexts/request bytes as AC6, two reply parts, summary median local processing **1.24 / 1.83 / 6.53 ms**. Excludes model/network latency.
- Short source inspections inside `docker run --rm --network none --entrypoint python nousresearch/hermes-agent:v0.22.5 …` → corrected command exits 0. Initial guessed `hermes_cli/sessions.py` path did not exist (exit 1); discovered and inspected `hermes_cli/sessions_cmd.py`, `subcommands/sessions.py` and actual SessionDB methods instead. No external documentation or host access.
- Pinned CLI/source: `sessions_cmd.py:287-307` calls `list_sessions_rich` without archived/hidden overrides and prints “No sessions found” for an empty filtered result; parser `subcommands/sessions.py:38-40` defaults to 20. `SessionDB.list_sessions_rich` defaults include `include_archived=False`, `include_hidden=False`, `include_children=False`. Real delete uses active-write/runtime guards (`sessions_cmd.py:643-658`); a failed/blocked deletion must not be bypassed.
- CLI-only R11 probe in a fresh image/profile → exit 0, exact documented list command exits 0 / “No sessions found”, while both hidden/archived sessions and their messages remain. Integrated R11 below → exit 0, fully persisted lockdown, false empty-list check, two remaining sessions/messages, then absent parent/child veto after Clear/Apply. No production data/container mounted.
- Separate R11 positive control in another fresh image/profile → exit 0: both synthetic session IDs are initially visible to the exact same CLI command; after only setting the hidden/archive flags, that command exits 0 / “No sessions found”, with both rows still present. This excludes a wrong-profile/database explanation for the false empty result.

## R9/R10 verification and the new R11 reproduction

R9 was rerun with the original three-byte `pwrite` double: healthy constructor, recorded synthetic provenance, ledger directory 0500, `pre_llm_call`, synthetic transcript write, repair to 0700, constructor rebuild and summary-only parent/child turns. Output:

```text
current_blocked= True lockdown_file= False state_recognized_locked= True transcript_rows= 1
after_restart_parent_blocked= True child_blocked= True
```

The new write loop and readback are responsible for the changed result; existing malformed state is kept restrictive rather than rewritten. The fault cases that cannot complete still warn, and incomplete contents stay restricted. The unchanged all-writes-fail case is D5, accepted by the owner and described honestly.

R10's old ordering defect is repaired. The rewritten test now walks actual document step names and checks that remaining synthetic sessions retain a veto, that Clear/Apply follow retirement, and that a fresh context can use tools afterward. Its gap is the mapping of Retire to actual Hermes: `test_scout_mail.py:1551` directly executes `delete from messages`, so it has no archived/hidden sessions table or CLI visibility filters.

R11 used the actual pinned CLI and real SessionDB in a fresh network-disabled container. Command envelope:

```text
docker run --rm --network none -u 10000
  -e HERMES_HOME=/tmp/scout-review5-r11
  -v <worktree>/hermes/ansible/roles/hermes_agent/files/plugins:/plugin:ro
  --entrypoint python nousresearch/hermes-agent:v0.22.5 -c <script>
```

Script (the settings stub enables the actual constructor without creating a repository settings file; no service/model call is made):

```python
import subprocess, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, '/plugin')
import scout_mail
from scout_mail.config import parse_settings
from hermes_state import SessionDB

assert subprocess.run(['hermes', 'profile', 'create', 'job-search', '--no-alias'],
                      capture_output=True).returncode == 0
home = Path('/tmp/scout-review5-r11/profiles/job-search')
scout_mail.load_settings = lambda path: parse_settings({
    'enabled': True, 'profile': 'job-search', 'inbox_id': 'synthetic@agentmail.to',
    'owner_user_ids': ['111']})
p = scout_mail._Plugin(SimpleNamespace(), home)
db = SessionDB(db_path=home / 'state.db')
for sid in ('S-HIDDEN', 'S-ARCHIVED'):
    db.create_session(sid, source='telegram')
    db.append_message(sid, 'user', 'synthetic mail-derived instruction')
db.set_session_hidden('S-HIDDEN', True)
db.set_session_archived('S-ARCHIVED', True)
p._lockdown('synthetic recovery test')
print('durable_lockdown', p.store.locked())
print('before_recovery_blocked', p.pre_tool_call(tool_name='web_search', session_id='S-HIDDEN') is not None)

# Retire's exact inventory/empty-list check: it reports no IDs to delete.
r = subprocess.run(['hermes', '-p', 'job-search', 'sessions', 'list'], capture_output=True, text=True)
print('retire_check_exit', r.returncode)
print('retire_check', r.stdout.strip())

# Clear, then Apply (new plugin construction), as in the delivered recovery model.
for name in ('taint.lockdown', 'taint.state'):
    (p.store._path.parent / name).unlink(missing_ok=True)
p = scout_mail._Plugin(SimpleNamespace(), home)
print('remaining_sessions', sum(db.get_session(sid) is not None for sid in ('S-HIDDEN', 'S-ARCHIVED')))
print('remaining_messages', sum(len(db.get_messages(sid)) for sid in ('S-HIDDEN', 'S-ARCHIVED')))
p.pre_llm_call(session_id='S-HIDDEN', user_message='suite', conversation_history=[
    {'role': 'assistant', 'content': 'Résumé compressé synthétique.'}])
p.pre_llm_call(session_id='C', parent_session_id='S-HIDDEN', user_message='suite')
print('resumed_session_tool', p.pre_tool_call(tool_name='web_search', session_id='S-HIDDEN'))
print('child_tool', p.pre_tool_call(tool_name='web_search', session_id='C'))
```

Observed, exit 0:

```text
durable_lockdown True
before_recovery_blocked True
retire_check_exit 0
retire_check No sessions found.
remaining_sessions 2
remaining_messages 2
resumed_session_tool None
child_tool None
```

There is no storage fault here: lockdown was fully persisted. No privileged operation executes; the probe checks the missing veto on existing history. Compression is supplied synthetically as in the delivered lineage tests, not through a live model. The preceding CLI-only probe independently produced the same false empty result without loading the plugin.

Positive-control output from a separate fresh profile, using the same SessionDB and list command before and after setting only the two flags:

```text
R11 control exits 0
R11 control both_initial_ids_visible True
R11 filtered exits 0
R11 filtered output No sessions found.
R11 rows_still_present 2
```

## Not checked

- No hermes-31, AgentMail/model/provider, external documentation, live Telegram message/busy dispatch, MR/CI refresh, merge/deployment/enablement, or vault password/decryption. Local loopback and Unix-socket tests and `--network none` ephemeral containers use synthetic fixtures only.
- Four vault-resolving tests are deselected before execution: `test_t15_effective_value_is_cafe_ia_then_job_search` and three `test_effective_*` cases. The Nora test that reads the encrypted file beyond its header is also deselected. The 11 known hanging Kaféine lab tests are excluded as authorized.
- Live park/unpark, production gateway recovery, actual production session retirement, provider key scope/content, production logging/CI-artifact redaction, Telegram preview settings and post-deploy idempotence remain owner checks. R11 operates only on a fresh throwaway profile.
- Repository-wide lint/syntax/pre-commit hooks not rerun. No claim that executor evidence is an independent reviewer run.

## Reservations before merging and enabling

- **D5 acceptance is honored.** The all-writes-fail branch remains accepted and explicitly documented as in-memory until restart; it is not a new finding or a request to reopen that decision. F11 is a distinct, fully persisted-lockdown recovery error. The retirement procedure must actually cover all contexts before its protection is cleared.
- F9's complete-write/readback and ambiguous-state handling now address the reported persistence defect. F10's restart ordering is improved and genuinely tested at the modelled level. Do not equate that synthetic test with an executed real-CLI retirement procedure.
- Current-image recovery must respect Hermes' active-turn guards: do not directly delete live database rows to make a count reach zero. Find and retire all relevant profile contexts through supported operations, holding effective protection until the authoritative inventory is empty. Hidden/archive filters cannot be worked around merely by increasing `--limit`.
- Every accepted recovery deletes Scout history unless exported. Treat exports, old digests and archived mail-derived content as untrusted; do not re-import them into a privileged context. Complete profile retirement and live park/unpark need validation before enabling.
- DNS is still outside the nominal 75-second socket-stage deadline. Cancelled workers finish their current socket/resolver work; no immediate cancellation or unconditional end-to-end time guarantee is claimed.
- HTTPX/httpcore private pool integration is tested against pinned versions and fails closed for the tested unknown layout. Preserve upgrade tests, TLS hostname verification, closure and candidate-deadline checks.
- This is the last authorized cycle. No further cycle, push, MR comment, merge, deployment or enablement is authorized by this review. The feature remains off. Live evaluation/read smoke, actual gateway/rendering/log checks, key-scope confirmation and idempotent deployment remain owner decisions/steps.
