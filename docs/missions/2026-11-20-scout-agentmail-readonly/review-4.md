VERDICT: CHANGES_REQUESTED
Version: 1182fb53e31bb6c26268f3e7fde8bd37f874458a
Reviewer: codex

## Status of F7, F8 and earlier findings

- **F7: partially fixed.** The original permission-removal → writable transcript → directory repair → restart case now stays blocked for the parent and compressed child. The real constructor opens and syncs `taint.state` before the failure; lockdown overwrites that open descriptor instead of depending on creating or renaming a file in the failed directory. R7 with the real constructor passes, as does the new image test using Hermes' own SessionDB. The other-filesystem startup branch refuses tools in the supplied test. However, the all-writes-fail branch still loses the restriction across restart; I independently reproduced that disclosed residual, including a transcript row written meanwhile. Report §F/§M and D5 now describe it honestly, and the owner has **not** accepted it in the supplied decision log. Additionally, short writes are incorrectly acknowledged as durable (F9), and operator recovery has an unsafe ordering (F10). The unconditional lifetime requirement is therefore still unmet.
- **F8: fixed for TCP establishment and the established connection.** The custom backend resolves once, recomputes remaining time before every candidate, tracks the socket before `connect`, and caps that candidate's timeout. It stops after expiry; an unrecognized client-pool layout fails before `stream` is called. The timeout-honouring regression passes with three attempts and no fourth. R8's original fake, which ignores its supplied timeout, now takes 0.788 s with timeouts 0.562 / 0.312 / 0.062 s; its final overrun is a limitation of that fake, not proof that a real socket ignores the cap. DNS remains an explicitly disclosed exception to a complete wall-clock bound.
- **F1–F6: no regression detected in the previously passing cases.** No expiry/eviction returns; last-slot message IDs still attach to the reserved record; write-failure/cancellation paths still invoke lockdown; system prompt, prefix and data remain within the context cap. F1/F4's full lifetime guarantee remains limited by F7/F9. F2's TCP gap is repaired by F8. F3 and F6 remain fixed in their tested scope, including real TLS handshake/header/body aborts and peer-observed closure.

Independent counts: **113 plugin tests passed**; **6 image tests passed**. All **8 F7/F8 tests pass** on 1182fb5. Against b22ba76 with the final new tests transplanted unchanged into a temporary extraction, **6 fail and 2 pass**; the extra failure beyond the executor's earlier 5-fail/2-pass comparison is the subsequently added unknown-layout test. Of those failures, `f7_04` checks the improved recovery log only; it is not a durable-refusal regression. Image comparison: **1 failed / 5 passed** on b22ba76, versus **6 passed** on this version.

The changed F6 socket-pair tests replace the new backend factory to inject the same ready stream; they retain the same TLS server, deadline, exception, elapsed-time and connection-closure assertions. Loopback cases exercise the real new backend. F2's fake client gained the required pool attribute; its fake-clock trickling-response assertion is unchanged. These adaptations do not weaken the behaviours previously checked.

## Findings

- **F9 [major] hermes/ansible/roles/hermes_agent/files/plugins/scout_mail/taint.py:194 — A short state-block write is treated as a persisted lockdown, then cleared on restart.** `os.pwrite`'s byte count is ignored. After a three-byte write, `fsync` and `st_nlink > 0` mark persistence successful even though the block does not equal `_LOCKED`. When the directory cannot create `taint.lockdown`, that false success suppresses the rename fallback and emits the ordinary success log instead of the “NOT persisted” warning. `locked()` returns false for the malformed block (`taint.py:223`), and `arm()` overwrites any non-exact `_LOCKED` contents with `_ARMED` (`taint.py:171-173`). After directory repair and restart, the parent and compressed child regain tools while their transcript exists. This is additional to the disclosed branch where writes raise errors: here writing returns successfully, so neither the operator nor the next process is told the security record is uncertain. It fails AC2/AC4's lifetime/failure requirement. **Expected fix:** check and complete state writes, treat short/invalid/unknown existing state as restricted rather than clean, and do not overwrite ambiguous existing state during startup. Add short-write and malformed-state restart regressions. Evidence: R9 below, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -` → exit 0 on this SHA: current-process block true, no lockdown file, stored state not recognized as locked, one transcript row, then parent and child vetoes both `None`. The normal original-R7 control stays blocked.

- **F10 [major] docs/guides/runbook-scout-mail.md:119 — Recovery unloads the protection and restarts before retiring potentially tainted sessions.** Step 2 says disable via the kill switch; step 3 deletes sessions; step 4 stops the gateway. The same runbook's §6 (`:89`) defines that kill switch as replaying Ansible, causing one gateway restart and unloading the plugin. Thus the documented recovery first makes existing sessions available with ordinary Scout tools and without the taint hooks, before deleting them. The unpersisted-lockdown row (`:120`) says “Do NOT restart first” but directs the operator through those same steps 1–3, which include the restart. This is inconsistent with both the code's in-memory-only fallback and the report's requirement to retire sessions before any restart, and fails AC9's safe recovery requirement. **Expected fix:** give an explicit order that first prevents inbound/active processing, retires all affected Scout contexts while protection remains effective or the gateway is stopped, and only then unloads hooks, clears markers or starts the gateway. Distinguish staging a configuration change from applying a restarting deployment. Validate that ordered procedure; `test_f7_05` only removes marker files after a comment saying sessions were retired, and does not execute or verify retirement/order. Evidence: R10's static check below → exit 0, `recovery_disables_before_retirement=True`, `kill_switch_restarts_and_unloads_hooks=True`; `rg -n` resolves both instructions. Documentation is the explicitly requested f55c226 revision, identical at HEAD; code remains 1182fb5. No deployment or real session deletion was attempted.

## Acceptance criteria

`NOT_VERIFIED` includes demonstrated defects, identified below, and unavailable checks. Intentionally unavailable live tests and production access do not themselves cause this verdict.

| AC | Status | Proof on the reviewed version |
|---|---|---|
| AC1 | NOT_VERIFIED | Discovery/API evidence exists with dated references; local pinned image is exercised by six passing tests, including real Hermes SessionDB. Actual hermes-31 version/hashes, provider scope/read side effects and current remote documentation were not retrieved under this offline brief. |
| AC2 | NOT_VERIFIED | Fresh tool-less summary context and direct rendering remain isolated from ordinary Scout operations. Original F7 permission-recovery case now passes. **The disclosed unpersistable restriction and newly reproduced short-write case (F9) still allow parent/child tools after restart.** D5 remains an owner decision, not a granted waiver. |
| AC3 | NOT_VERIFIED | Current matrix covers T1–T13, distinguishes enforcement/behaviour and has **64 test-column references, all existing**. DNS and the nothing-writable residual are now disclosed. The new state-block guarantee omits short/invalid-state handling (F9), and recovery is inconsistent (F10). |
| AC4 | NOT_VERIFIED | **113 plugin tests and 6 image tests pass**; old/new F7/F8 comparison independently reproduced. Assertions cover actual requests, denials, persistence and TLS closure. R9 exposes a missing short-write/restart case. The all-writes-fail test asserts in-process refusal and a warning, not survival across restart; R7b demonstrates that limit. |
| AC5 | VERIFIED | Plugin suite covers concurrent requests, cancellation, exception then retry. Image suite verifies Scout-only hooks/command, no global tool registration, **400 concurrent decisions** across tainted/clean Scout, Nora and Kaféine, plus access denials/history privacy. No new global registry mutation. This is deterministic/image evidence, not a live Telegram busy-path test; worker cancellation/DNS limitations remain as reserved below. |
| AC6 | NOT_VERIFIED | Socket-stage limits verified: F8 candidate budget, existing F6 real TLS handshake/header/body aborts, no returned partial body, unknown-layout denial, response/field/count/retry and total-context tests pass. Fixture contexts **4,460 / 17,201 / 19,977** and request bytes **5,028 / 18,821 / 22,448** independently reproduced. An unconditional end-to-end wall-clock ceiling is still not established because blocking DNS is explicitly outside it; this is a disclosed limitation, not a new F8 finding. |
| AC7 | NOT_VERIFIED | Sentinel/redaction tests pass in the plugin suite; role secret controls remain unchanged (`no_log`, 0600 environment file, key by name in its own host's header). Key-pattern scan returns only synthetic fixture definitions. Vault header verified only; no decryption/key/password access. Actual vault content/scope, production logs and CI artifacts are not independently checked. |
| AC8 | NOT_VERIFIED | Fresh selected full suite: **836 passed, 27 skipped, 16 deselected, zero failures in 1,277.79 s** (879 collected). Includes real current-image multiplex/Kandidat labs and mail wiring/image tests. Skips require older image v2026.8.18; exclusions are 11 known Kaféine lab hangs and 5 vault/header-reading cases detailed below. Correction changes only plugin persistence/transport and their tests/image fixture; no profile/SOUL/Kandidat gates/tool matrix/cron content changed. Feature remains `false` in defaults and group vars, Scout's plugin list empty. Full repository lint/hooks not rerun; executor's results remain attributed. |
| AC9 | NOT_VERIFIED | Required deployment/check/idempotence/rollback/revocation/owner-test material remains present. New recovery now calls for deleting every Scout session and clearing both state markers, but its **execution order fails F10**. `sessions delete <id> --yes` exists in the pinned CLI; help was checked without deleting real data. |
| AC10 | VERIFIED | Report and live-eval evidence honestly state **NOT_VERIFIED**, zero live model calls, reason and owner command. AgentMail read smoke remains owner-run after merge/deployment. Q1–Q3/key scope are owner assertions, not independent reviewer/provider verification. |
| AC11 | NOT_VERIFIED | Local commit sequence and unchanged source versus the named SHA verified. Draft MR !109, CI state and unchanged production hashes remain pilot/executor evidence; no remote refresh, push, comment, merge or deployment by reviewer. |
| AC12 | NOT_VERIFIED | Report has PARTIAL verdict, correct code SHA, required sections and explicit D5. Header/§F/§M no longer claim unconditional completion or hide DNS; original F7/F8 test claims are substantially reproduced with the final-test-count qualification above. State persistence and safe recovery still require correction for F9/F10; “same filesystem” is correctly described as an argument rather than a guarantee in the report. |

## Commands run

Working directory: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`. `uv` commands use `PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/scout-review4-uv UV_OFFLINE=1`, `--no-sync`, and pytest `-p no:cacheprovider`. Ansible local/remote temporary directories are explicitly under `/tmp`. No source checkout, stash, worktree registration, registry edit or permission escalation; scratch old-version extraction is automatically removed.

- Read AGENTS, review brief 4, review-3 context, report §F/§M/D5, m8 evidence, mission's extra-cycle decision, relevant source/test diffs, ADR/matrix and runbook. Owner authorization is one additional review/correction cycle, not acceptance of D5, merge or deployment.
- `git rev-parse HEAD` → exit 0, `e9c7a72e2c70da36aa63342ee8314a06569de961`. Initial `git status --short` → exit 0, only pre-existing untracked `review-brief-4.md`.
- `git diff --quiet 1182fb5 HEAD -- hermes` → exit 0, executed source/tests match the named code SHA, including the encrypted vault file. `git diff --quiet f55c226 HEAD -- docs/adr/hermes.md docs/guides/runbook-scout-mail.md docs/references/scout-mail-threat-model.md` → exit 0. Later changes are the documentation revisions specifically requested for this review; they are not attributed to the code commit.
- `git diff --check b22ba76 1182fb5` and `git diff --check 3d7bf18 1182fb5` → exit 0. Correction source read with the encrypted vault excluded; only names/statistics inspected for its historical encrypted change, never ciphertext contents/decryption in this review.
- `head -n 1 hermes/ansible/group_vars/hermes/vault/config.yml` → exit 0, `$ANSIBLE_VAULT;1.1;AES256`.
- `git grep -I -l -E '(^|[^[:alnum:]_])(am_[A-Za-z0-9_-]{24,}|sk-[A-Za-z0-9_-]{24,}|glpat-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,})|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' HEAD -- ':!**/vault/**'` → exit 0, only `test_scout_mail.py` and `test_scout_mail_role.py`, known synthetic fixture definitions; no matched values printed. Bounded pattern scan, not proof against every secret format.
- `git grep -n 'hermes_scout_mail_enabled:' 1182fb5 -- hermes/ansible/group_vars/hermes/all/main.yml hermes/ansible/roles/hermes_agent/defaults/main.yml` → exit 0, both false. `git diff --name-only 3d7bf18 1182fb5 -- hermes/ansible/roles/hermes_agent/files/profiles` → exit 0, empty. `git grep -n retention_days 1182fb5 -- hermes docs/adr docs/guides docs/references` → exit 1, no active references.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -rs` → exit 0, **113 passed in 28.59s**.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -k 'f7_ or f8_' --tb=short` → exit 0, **8 passed, 105 deselected in 0.68s** (overlaps the 113).
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail_image.py -q -rs` → exit 0, **6 passed in 10.47s**, local pinned image, `--network none`.
- `docker image inspect nousresearch/hermes-agent:v0.22.5 --format '{{.Id}}'` → exit 0, `sha256:49b70739d2e8b4206fabf8b089f88337db73f8edaccb93e64b0836694ef10a03`. Local package metadata → exit 0, HTTPX **0.28.1**, httpcore **1.0.9**.
- `.venv/bin/python -u -` scratch red comparison: `git archive b22ba76 hermes/ansible/roles/hermes_agent hermes/tests`, extracted with `tarfile` under `TemporaryDirectory`; replace only `test_scout_mail.py`, `test_scout_mail_image.py`, `fixtures/scout_mail/image_lab.py` with the reviewed versions, without compatibility edits. Child `python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail.py -q --tb=line -k 'f7_ or f8_'` → exit 1, **6 failed, 2 passed, 105 deselected in 1.26s**. F7_01/02/03 fail authorization/startup denial, F7_04 fails recovery-log assertion only, F8_01 exceeds budget, F8_03 reaches forbidden stream. The earlier executor's seven-case red run excluded the later unknown-layout case.
- Same scratch tree, `python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail_image.py -q --tb=line` → exit 1, **1 failed, 5 passed in 10.41s**: real SessionDB repaired-directory regression returns no tool veto after restart. Orchestrator exits 0 after printing child exits; temporary tree removed.
- `ANSIBLE_LOCAL_TEMP=/tmp/scout-review4-local ANSIBLE_REMOTE_TEMP=/tmp/scout-review4-remote timeout -s INT -k 5 1500 uv run --no-sync pytest -p no:cacheprovider hermes/tests -q -rs --durations=10 -k 'not (test_m7_kafeine and test_lab_) and not test_effective_ and not test_t15_effective_value_is_cafe_ia_then_job_search and not test_n01_prerequisites_are_never_created'` → exit 0, **836 passed, 27 skipped, 16 deselected in 1,277.79s** (879 collected). Every selected case passes on the final code. This overlaps the targeted runs; counts are not added together. The 27 skips require older image v2026.8.18; exclusions prevent known hanging labs and real vault resolution/header-reading tests. Slowest fixtures: current-image multiplex **359.56s**, Kandidat **170.91s**. No permission escalation or credential resolution required.
- `uv run --no-sync python -` capturing JSON from `scout_mail_fixture_run.py` → exit 0; contexts/request sizes as AC6, two reply parts per summary batch, median local processing **1.24 / 1.80 / 6.64 ms**. No model/network latency included.
- AST comparison of matrix test-column names against actual pytest functions → exit 0, **64 references, none missing**.
- R7 controls/residual, R8 and R9 probes below, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -` → exit 0 each. Synthetic mail/transcript and socket/storage doubles only; no model, provider or privileged operation executed.
- R9 repeated with real Hermes `SessionDB` inside `docker run --rm --network none -u 10000 -e HERMES_HOME=/tmp/scout-review4-r9 -v <worktree>/hermes/ansible/roles/hermes_agent/files/plugins:/plugin:ro --entrypoint python nousresearch/hermes-agent:v0.22.5 -c <script>` → exit 0, same short-write failure: one real transcript row, state not locked, parent/child vetoes absent after repair and rebuild. Container is ephemeral; no production state mounted.
- `docker run --rm --network none -u 10000 -e HERMES_HOME=/tmp/scout-review4 --entrypoint hermes nousresearch/hermes-agent:v0.22.5 sessions delete --help` → exit 0, positional `session_id` and `--yes` supported. This verifies syntax only, not the unsafe recovery sequence; no actual session deleted.
- `rg -n 'Kill switch|restart|Retire|retire|NOT persisted|Do NOT|disable' docs/guides/runbook-scout-mail.md` → exit 0; lines 89, 119–121 establish F10. Python check of those actual rows → exit 0, both R10 booleans true as printed below. No production command executed.

## Reproductions and qualifications

### R7: original permission case fixed; all-writes-fail residual remains

The real-constructor control creates provenance while healthy, changes the ledger directory to 0500, calls `pre_llm_call` with the marker, writes a synthetic transcript row to the sibling `state.db`, restores 0700 and constructs a new plugin on the same home. It then supplies summary-only history and parent/child IDs, as in the prior compression tests. Output:

```text
R7 original blocked= True lockdown_file= False transcript_rows= 1
R7 original after_restart_parent_blocked= True child_blocked= True
```

Using the real constructor matters: the older local `make_plugin` helper bypasses constructor initialization/arming. The image control and new F7 tests use the actual constructor, and independently exercise the required healthy-start → later-failure lifecycle.

For the disclosed all-writes-fail branch, after normal construction/reservation the probe patches `taint.os.pwrite`, `open` and `replace` to raise `OSError(5, 'synthetic I/O error')`, then calls `pre_llm_call`. A synthetic SQLite transcript insert succeeds (SQLite's file I/O is not the patched Python `os` functions). After restoring the operations and reconstructing the plugin, marker-free summary history and the compressed child are supplied:

```text
scout_mail lockdown (session restriction not recorded) NOT persisted:
  retire Scout's sessions before any restart (runbook, section 8)
R7 nothing-writable current_blocked= True transcript_rows= 1
R7 nothing-writable after_restart_parent= None child= None
```

This confirms the report's residual, not a claim that an entire read-only filesystem accepts writes. A state-file I/O failure and a writable transcript on the same device are not mutually exclusive. The same-device check alone cannot establish the lifetime guarantee. D5 explicitly asks the owner whether to accept this; the extra-cycle authorization does not answer it.

### R9: short state write falsely acknowledged as durable

Run from the worktree with `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -`:

```python
import os, sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, 'hermes/tests')
import test_scout_mail as t
from scout_mail import taint

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    p = t._restart(root)  # actual constructor: state block opened while healthy
    p.store.record_result(t.OWNER, ['9001'], [t.render.MARKER + '\n' + t.INJECTED])
    directory = p.store._path.parent
    real_pwrite = os.pwrite
    def partial(fd, data, offset):
        return real_pwrite(fd, data[:3], offset)  # successful short write, return count 3
    directory.chmod(0o500)
    try:
        with patch.object(taint.os, 'pwrite', partial):
            p.pre_llm_call(session_id='S', user_message=t.render.MARKER + '\n' + t.INJECTED)
        print('current_blocked=', p.pre_tool_call(tool_name='web_search', session_id='S') is not None,
              'lockdown_file=', p.store._lock_path.exists(), 'state_recognized_locked=', p.store.locked(),
              'transcript_rows=', t._persist_transcript(p.home, 'S', t.INJECTED))
    finally:
        directory.chmod(0o700)
    p = t._restart(root)
    p.pre_llm_call(session_id='S', user_message='suite', conversation_history=[
        {'role': 'assistant', 'content': 'Résumé compressé.'}])
    p.pre_llm_call(session_id='C', parent_session_id='S', user_message='suite')
    print('after_restart_parent=', p.pre_tool_call(tool_name='web_search', session_id='S'),
          'child=', p.pre_tool_call(tool_name='web_search', session_id='C'))
```

Observed, exit 0:

```text
scout_mail lockdown (session restriction not recorded): Scout refused until the operator intervenes
current_blocked= True lockdown_file= False state_recognized_locked= False transcript_rows= 1
after_restart_parent= None child= None
```

The short-write double writes actual bytes and returns their actual count; the implementation ignores that count. This is a storage-fault injection, not an assertion that every filesystem short-writes this block. It exercises a different branch from an exception/no-write, and demonstrates why existing malformed state cannot be treated as clean on startup.

The independent image repetition replaces `_persist_transcript` with `hermes_state.SessionDB(db_path=home/'state.db')`, `create_session('S', source='telegram')` and `append_message('S', 'user', MARKER+' synthetic message')`, while preserving the same three-byte `pwrite` injection, real 0500 permission change and real constructor rebuild. Output:

```text
R9 image blocked_before_restart True
R9 image transcript_rows 1
R9 image state_locked False
R9 image parent None
R9 image child None
```

### R8: exact old fake versus a timeout-honouring control

The prior four-address R8 double was rerun with the same unconditional `sleep(.25)` per `connect`, through the real `Transport.list_messages`. Output: **0.788 s**, **3 attempts**, timeouts **[0.562, 0.312, 0.062]**, **1 HTTP call, 0 model calls**. Its final call sleeps longer than the timeout it is given. The new timeout-honouring `f8_01` passes with the same 0.6 s budget; no fourth candidate starts. This supports F8's fix rather than reclassifying the old double's unavoidable overrun as a new defect.

The real TLS tests still verify exception, response non-return and peer closure; socket-pair injection only changes the backend factory interception point. DNS remains blocking and outside this guarantee, explicitly documented in §F/§M, ADR, matrix and runbook.

### R10: recovery order in the delivered documentation

Python selects the `| Lockdown:` table row, compares the positions of `2. Disable` and `3. Retire`, and checks §6's kill-switch row for `one gateway restart` plus `plugin not loaded`. Output, exit 0:

```text
recovery_disables_before_retirement= True
kill_switch_restarts_and_unloads_hooks= True
```

The additional warning not to restart cannot make those ordered instructions consistent. Clearing markers in `test_f7_05` proves that operator removal lifts lockdown; its comment about prior session retirement does not validate the actual procedure.

## Not checked

- No hermes-31 inspection, external documentation/provider/model call, AgentMail read smoke, key-scope verification, vault decryption/password retrieval, MR/CI refresh, push, comment, merge or deployment. Live behaviour and read smoke remain NOT_VERIFIED by design. Local loopback/Unix-socket tests and network-disabled ephemeral image containers use synthetic fixtures only.
- Four vault-resolving tests are excluded before execution: `test_t15_effective_value_is_cafe_ia_then_job_search` and three `test_effective_*` cases; the Nora test that reads the whole encrypted file is also excluded. Direct vault inspection is header-only. The 11 known hanging Kaféine lab tests are excluded per brief.
- Actual safe session-retirement/recovery on a live gateway, busy Telegram dispatch, renderer/link-preview behaviour, production log routing, deployed key/CI artifact redaction and post-deploy idempotence remain owner verification. CLI help and marker-removal unit tests do not substitute for that procedure.
- Repository-wide lint/syntax/pre-commit hooks not rerun. The executor notes that its full-suite run preceded two declared lint-only edits; this review's fresh tests execute the final code itself.

## Reservations for the owner

- This extra cycle was authorized to address F7/F8; no further cycle, merge, deployment or enablement is authorized by this review. F8 is repaired in the tested socket stages. F7's normal permission-recovery case is repaired, but D5 is still undecided and F9 adds a false-persistence failure. Keep the feature disabled until the owner resolves the remaining boundary and recovery requirements.
- An already opened descriptor avoids ordinary later directory/file permission checks. It does not guarantee a full state write, protect against every I/O fault, or make a transcript on the same filesystem necessarily unwritable. Do not equate the same-device check with durable security persistence under every fault.
- Recovery now requires deleting every Scout session because affected sessions cannot be reliably identified, and exports/history may contain untrusted mail-derived text. The current documented order must be corrected before use (F10). Restoring exported/archived mail history must not silently confer ordinary Scout privileges.
- Blocking DNS can exceed the nominal 75 s request ceiling. Cancellation leaves its worker to finish the bounded socket operation or resolver; no claim of immediate wire cancellation or unconditional end-to-end duration should be made.
- The backend uses private HTTPX/httpcore pool layout, tested against 0.28.1/1.0.9; the unknown-layout guard prevents the tested fallback connection. Re-run tests on a dependency/Hermes upgrade, including successful fallback, TLS verification and deadline/closure assertions.
- Key scope/provisioning are owner-attested; encryption metadata is not content verification. Live behavioural quality, actual busy-path/rendering/preview/log checks, AgentMail read smoke and idempotent deployment remain pending owner steps. No production change was made by the reviewer.
