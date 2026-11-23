VERDICT: CHANGES_REQUESTED
Version: b22ba76472d3884e24a2954e40ec7e2b4793b040
Reviewer: codex

## Status of previous findings

| Finding | Status | Evidence on b22ba76 |
|---|---|---|
| F1 — provenance/session restrictions expire | **Partially fixed** | No expiry or eviction remains. Original elapsed-time, eviction and compression tests pass in the 105-test plugin suite. Reserved result records fix the capacity boundary. The lifetime guarantee still fails when no lockdown can be persisted and permissions recover before restart (F7). |
| F2 — streaming outlives the wall-clock budget | **Partially fixed** | Body deadline checks and the live-descriptor watchdog now work over TLS. However, the budget is not enforced across TCP address candidates before a connection succeeds (F8), independently of the disclosed DNS-resolution exception. |
| F3 — context cap excludes instructions | **Fixed** | All F3 instances pass; system prompt, prefix and JSON data are counted before model invocation. Independent fixture totals: 4,460 / 17,201 / 19,977 characters; model request bytes: 5,028 / 18,821 / 22,448. |
| F4 — unpersisted session restriction lost on restart | **Partially fixed** | Persistent lockdown file, rename fallback and startup writability probe work in the new tests. They cover a writable directory with failed ledger writes and a directory that stays unwritable. They do not cover a directory repaired before restart; the same original tool-restoration defect remains there (F7). |
| F5 — last result slot loses delivered IDs | **Fixed for the reported capacity/delivery cases** | `record_result` returns a reserved record handle; `attach_ids` updates that record after each delivered part without consuming another slot. Exact default-capacity, post-delivery write-failure and cancellation regressions pass. Unrecordable delivery invokes the same lockdown mechanism whose all-writes-fail limitation is F7; this is not an unconditional durability guarantee. |
| F6 — HTTPS watchdog holds detached TCP socket | **Fixed** | Watchdog tracks descriptor plus device/inode identity, duplicates and checks identity before shutdown, and disarms in `finally`. Eight real HTTPX/httpcore/SSL deadline cases pass: handshake, trickled headers, trickled body and stalled body over both loopback TCP and a Unix socket pair. They assert `BudgetExceeded`, no returned partial response and server-observed connection closure. The fast HTTPS response test also passes. F8 concerns connection establishment before descriptor tracking, not TLS descriptor transfer. |

Independent regression comparison: transplant b22ba76's test file into a temporary `git archive edcd9fe hermes` extraction, adding only `plugin.guarded = set()` to the helper for the old implementation's removed attribute. Result: **9 failed, 7 passed, 89 deselected in 18.92s** on edcd9fe; **16 passed, 89 deselected in 8.49s** unchanged on b22ba76. The nine old-code failures are behavioral: four F4 cases, three F5 cases and both HTTPS trickled-header cases. Other HTTPS modes also passed on the old implementation, as the executor reports. The complete plugin suite independently passes: **105 passed in 28.42s**.

## Findings

- **F7 [blocker] hermes/ansible/roles/hermes_agent/files/plugins/scout_mail/__init__.py:198 — Repairing an unwritable ledger directory before restart erases the only restriction while an actionable transcript can survive.** If both creating `taint.lockdown` and renaming the ledger fail, `_lockdown` retains only `self.locked`. A later constructor sets that boolean to false and probes current writability (`__init__.py:76-81`); it cannot distinguish a repaired directory from one that never lost a security record. With a compressed history lacking a fingerprint/marker, the same session and its compressed child regain tools. This is explicitly disclosed in report §F/§L, but disclosure does not satisfy AC2's required subsequent-turn boundary. The suggested mitigation that Hermes needs the same filesystem to persist its transcript is insufficient: permissions can deny writes to `plugin-data/scout_mail/` while `state.db` remains writable. Runbook §8's startup-writability row (`docs/guides/runbook-scout-mail.md:120`) says repair and restart without retiring affected sessions, reproducing the unsafe recovery. **Expected fix:** establish durable evidence before permitting a tainted actionable context, or require a conservative restart/recovery policy that cannot resume potentially affected sessions after loss of security persistence; do not rely on successfully writing another file in the failed directory. Add permission-denial → transcript persistence → directory repair → compression/restart → parent/child-tool regressions. Align recovery instructions and the report's blanket “all fixed” claim. Evidence: R7 below, exit 0 on this SHA, both locally and inside the pinned image: blocked before restart, no durable lockdown, transcript write succeeds, then parent/child tool decisions are `None`. No privileged operation was executed.

- **F8 [major] hermes/ansible/roles/hermes_agent/files/plugins/scout_mail/transport.py:103 — TCP connection attempts can exceed the absolute deadline before the watchdog has a descriptor to abort.** Tracking occurs only on `connection.connect_tcp.complete`. Installed httpcore 1.0.9 delegates connection establishment to Python `socket.create_connection` (`httpcore/_backends/sync.py:188-216`), which iterates all returned addresses and applies the same initial timeout to each (`socket.py:840-860`). While candidates are failing, the watchdog can mark expiry but has no target; subsequent candidates continue. This is distinct from DNS resolution itself being slow: R8 makes `getaddrinfo` return immediately. **Expected fix:** enforce the remaining absolute budget during address iteration and the active connect operation, with no new candidate after expiry; retain the verified TLS/header/body enforcement. Add a deterministic multiple-address regression with immediate DNS and bounded failed connects, and correct the “only name resolution” limitation in ADR/runbook/matrix/report. This fails AC6 and the claimed cancellation-worker duration bound. Evidence: R8 below, exit 0 through the real plugin `Transport`/HTTPX/httpcore/stdlib connect loop: a **0.6-second remaining budget takes 1.038 seconds**, with **four connect attempts reusing one timeout**, one counted HTTP operation and zero model calls. All wire operations are synthetic; no DNS/network/provider call occurred.

## Acceptance criteria

`NOT_VERIFIED` includes reproduced failures (identified explicitly) and unavailable checks. The verdict is based on F7/F8, not on intentionally unavailable live evaluations or the sandbox limitations.

| AC | Status | Proof on the reviewed version |
|---|---|---|
| AC1 | NOT_VERIFIED | Discovery and AgentMail evidence have source references and dated URLs. Local image digest is `sha256:49b70739d2e8b4206fabf8b089f88337db73f8edaccb93e64b0836694ef10a03`; its session persistence source independently places the DB at the active profile's `state.db`. Actual hermes-31 version/config hashes, provider permission metadata/read side effects and current external documentation not accessed under the offline brief. |
| AC2 | NOT_VERIFIED | Fresh tool-less model context, fixed read transport, direct renderer delivery and subsequent-turn hooks inspected; no global registry mutation added. **F7 defeats the lifetime restriction after a supported filesystem failure/recovery.** Feature remains disabled, but report does not present this as an unresolved architectural blocker and says all findings are fixed. |
| AC3 | NOT_VERIFIED | Matrix covers T1–T13, tags enforcement versus behavior and has **57 test-column references, all resolving to existing test functions**. F7's residual is disclosed. T11/ADR/runbook omit the independently reproduced pre-connect deadline exception (F8), so the stated enforcement is incomplete. |
| AC4 | NOT_VERIFIED | **105 plugin tests pass**, including actual operations, deny decisions, persistence, cancellation and the 16 review-2 regressions. Old/new comparison independently matches the reported 9-fail/7-pass → 16-pass transition. R7/R8 demonstrate missing required failure/lifetime and resource-bound cases. Live behavior is not inferred from deterministic fixtures. |
| AC5 | NOT_VERIFIED | Cancellation, exception/retry and concurrent-request tests pass in the plugin suite; the broad run includes the five passing mail-image tests (profile-only loading, no global registry mutation, 400 concurrent decisions, access denials and history/ledger privacy). No cross-profile/global-registry mutation introduced by the correction. Cancellation before delivery intentionally leaves a worker until transport completes, whose claimed absolute duration bound still has F8. Real Telegram busy dispatch remains an enablement check, not established by direct hooks. |
| AC6 | NOT_VERIFIED | F3/context and F6/active TLS transport fixed; fixture totals reproduced. Real TLS deadline tests return no partial body and verify peer closure. **F8 fails the complete request deadline before TCP connection completion.** DNS remains a separate disclosed limitation. |
| AC7 | NOT_VERIFIED | Local role secret controls and sentinel tests are covered by the runs below; secret names, `no_log` and 0600 environment-file wiring inspected. Branch key-pattern scan matches only synthetic mail/model fixtures. Vault header is `$ANSIBLE_VAULT;1.1;AES256`; 225fc3a changes only that encrypted file, unchanged at HEAD. No decryption, password retrieval or real key inspection. This does not verify the vault's contents, real key scope, production logs or CI artifacts. |
| AC8 | NOT_VERIFIED | Broad run: **19 failed, 782 passed, 27 skipped, 16 deselected, 26 errors**; affected runners attempt read-only `~/.ansible/tmp`. With writable local/remote scratch, reruns give **2 passed** (timezone cases), **52 passed / 2 skipped** (multiplex outside lab), **31 passed** (retirement), **26 passed** (multiplex lab). All 19 failures and 26 setup errors are covered by passing reruns: **827 unique selected cases passed across runs**, with 27 skipped and 16 deselected; not a clean single invocation. Correction changes only the intended inbox identifier in declarations; Scout remains disabled with `plugins.enabled: []`; no SOUL/profile content, Kandidat gates/tool matrix or cron drafts changed. Repository lint/hooks not rerun; executor evidence remains attributed. |
| AC9 | NOT_VERIFIED | Runbook includes variables, deploy/check/idempotence, key revocation, kill switch, rollback, synthetic owner mail and owner-visible versus trace checks. Lock-file recovery correctly distinguishes an empty marker from a renamed ledger. **The unwritable-directory repair/restart branch is unsafe for an already affected transcript (F7)** and timeout claims omit F8. No deployment procedure executed. |
| AC10 | VERIFIED | Reporting obligation satisfied: `evidence/m4-live-eval.md` and report state NOT_VERIFIED, zero of 40 calls, reason and owner command. AgentMail smoke and live behavior remain **NOT_VERIFIED by design**. Q1–Q3 are recorded as owner-answered, including owner-attested key scope; that is not independent reviewer/provider verification. |
| AC11 | NOT_VERIFIED | Local commits and documentation-only differences checked. MR !109, remote pipeline state and unchanged hermes-31 hashes remain pilot/executor evidence; reviewer made no network/host call, push, MR comment, merge or deployment. |
| AC12 | NOT_VERIFIED | Report has PARTIAL verdict, exact code Version and required architecture/evidence/risks/owner-input sections. §L's old/new test counts independently match. §F honestly discloses the F4 persistence residual and pending live checks, but “All are fixed” and “only name resolution” still overstate the integrated result (F7/F8). Report/evidence reviewed at documentation HEAD 97a09c4; code/design/runbook/matrix verified identical to b22ba76. |

## Commands run

Working directory: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`. For `uv` commands: `PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/scout-review3-uv UV_OFFLINE=1`; `--no-sync` prevents dependency resolution/downloads and `-p no:cacheprovider` prevents pytest cache writes. Ansible scratch paths below are under `/tmp`. No source checkout, stash, registry edit or permission escalation.

- `git rev-parse HEAD` → exit 0, `97a09c42c721a83921699226ef0b0f774d3a001c`. Initial `git status --short` → exit 0, only pre-existing untracked `review-brief-3.md`.
- `git diff --quiet b22ba76 HEAD -- hermes ':!hermes/ansible/group_vars/hermes/vault/config.yml'` and comparison of `docs/adr/hermes.md`, `docs/guides/runbook-scout-mail.md`, `docs/references/scout-mail-threat-model.md` → exit 0, no code/test/design differences. Later differences are mission docs and encrypted vault only. An initial comparison excluded the wrong vault path and displayed ciphertext; corrected exclusion used thereafter. No vault decryption or secret value was obtained.
- `git diff --check edcd9fe b22ba76` and `git diff --check 3d7bf18 b22ba76` → exit 0, clean. Correction source/tests/docs read directly; review 1/2, brief, owner brief, mission, §F/§L and m7 evidence read.
- `git diff 53c0f8c^ 53c0f8c -- hermes/ansible/group_vars/hermes/all/main.yml hermes/tests/test_scout_mail_role.py` → exit 0, only inbox ID filled and one test expectation aligned. `hermes_scout_mail_enabled: false` and Scout's empty plugin list preserved. Commit also updates mission docs, not additional product scope.
- `git diff-tree --no-commit-id --name-only -r 225fc3a` → exit 0, only `hermes/ansible/group_vars/hermes/vault/config.yml`; `head -n 1` of that file → exit 0, required vault header. `git diff --quiet 225fc3a HEAD -- <same path>` → exit 0. No `ansible-vault`, password script or effective-inventory test invoked.
- `git grep -I -l -E '(^|[^[:alnum:]_])(am_[A-Za-z0-9_-]{24,}|sk-[A-Za-z0-9_-]{24,}|glpat-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,})|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' HEAD -- ':!**/vault/**'` → exit 0, only `test_scout_mail.py` and `test_scout_mail_role.py`, defining synthetic sentinel/fake keys. Earlier broader prefix scan also matched substrings of three Telegram test-function names; inspected as identifiers, not keys. Only file paths/classifications were printed for credential-like matches. This is a bounded pattern check, not proof against every possible secret format.
- `git grep -n retention_days b22ba76 -- hermes docs/adr docs/guides docs/references` → exit 1, no active references. Historical mission evidence is not active configuration.
- `timeout -s INT -k 5 55 uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -rs` → exit 0, **105 passed in 28.42s**. Previous review's async stall did not reproduce in this environment.
- `.venv/bin/python -u -` scratch regression orchestration: extract `git archive edcd9fe hermes` under a `TemporaryDirectory`, transplant the new test file, add only `plugin.guarded = set()` to `make_plugin` for old-code compatibility; child command `python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail.py -q --tb=line -k 'f4_ or f5_ or f6_'` → pytest exit 1, **9 failed, 7 passed, 89 deselected in 18.92s**. Orchestrator exits 0 after printing the child's exit. Temporary tree removed automatically; mission worktree unmodified.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -k 'f4_ or f5_ or f6_' --durations=10` → exit 0, **16 passed, 89 deselected in 8.49s** (overlaps the 105 passes). Eight HTTPS deadline cases each complete in about 1.00–1.06 s; exact default-capacity case about 0.24 s.
- A preliminary broad-suite invocation set `ANSIBLE_VAULT_PASSWORD_FILE=/dev/null` as an extra guard; Ansible rejected the empty password source even for synthetic localhost plays. Interrupted, exit 130, no completed-suite count. Isolated `test_scout_mail_role.py -q -x --tb=short` with that override → exit 1, **1 failed in 0.42s**, `Invalid vault password was provided from file (/dev/null)`. Override removed; instead, actual vault-resolving tests were explicitly deselected before running them. This setup error is not a product regression and caused no decryption.
- `ANSIBLE_REMOTE_TEMP=/tmp/scout-review3-ansible timeout -s INT -k 5 1500 uv run --no-sync pytest -p no:cacheprovider hermes/tests -q -rs --durations=10 -k 'not (test_m7_kafeine and test_lab_) and not test_effective_ and not test_t15_effective_value_is_cafe_ia_then_job_search and not test_n01_prerequisites_are_never_created'` → exit 1, **19 failed, 782 passed, 27 skipped, 16 deselected, 26 errors in 898.09s** (870 collected). Custom Ansible runners in `test_m1_operations.py`, `test_m63_multiplex.py` and `test_m66_retirement.py` still use default local temp; failures/setup errors report `DEFAULT_LOCAL_TMP`, `[Errno 30] Read-only file system: /home/xgueret/.ansible/tmp/…`. They are not claimed as product regressions; affected reruns with a writable local-temp override follow. The 27 skips need image v2026.8.18; the five mail-image tests, all 105 plugin tests and 11 mail role tests pass in this run. No claim of a clean single full-suite invocation is made.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_m1_operations.py -q -x --tb=short` with the remote-temp override only → exit 1, **1 failed, 10 passed in 0.35s**; timezone test cannot create `/home/xgueret/.ansible/tmp/ansible-local-…`: `[Errno 30] Read-only file system`.
- `ANSIBLE_LOCAL_TEMP=/tmp/scout-review3-local ANSIBLE_REMOTE_TEMP=/tmp/scout-review3-ansible uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_m1_operations.py -q -k test_timezone_pre_tasks_pass_check_mode_without_changing_anything` → exit 0, **2 passed, 18 deselected in 1.70s**. No permission escalation.
- Same writable local/remote-temp overrides, `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_m63_multiplex.py -q -x --tb=short -k 'not test_effective_ and not test_lab_'` → exit 0, **52 passed, 2 skipped, 29 deselected in 52.69s**. Covers the non-lab multiplex failures of the broad run; three vault tests and 26 lab cases deselected.
- Same writable local/remote-temp overrides, `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_m66_retirement.py -q --tb=short` → exit 0, **31 passed in 1.02s**.
- Same writable local/remote-temp overrides, `timeout -s INT -k 5 600 uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_m63_multiplex.py -q -rs --tb=short -k test_lab_` → exit 0, **26 passed, 57 deselected in 370.69s**. Covers every multiplex lab setup error from the broad run. Combined with the affected-file reruns above, all 45 originally failing/erroring cases pass; counting each selected case once gives **827 passed**, not the sum of overlapping run totals. The 27 image skips and 16 deliberate exclusions remain.
- `uv run --no-sync python hermes/tests/scout_mail_fixture_run.py` → exit 0; summary contexts/request bytes as F3 table; median local fixture processing **1.24 / 1.81 / 6.47 ms**, two reply parts each. Excludes network/model latency.
- Python AST comparison of the threat matrix's test-column references with `hermes/tests/test_*.py` functions → exit 0, **57 references, none missing**. Broader prose contains abbreviated ranges and filenames, not additional missing test functions.
- `docker image inspect nousresearch/hermes-agent:v0.22.5 --format '{{.Id}}'` → exit 0, digest above. Short `docker run --rm --network none --entrypoint python …` source/signature inspection → exit 0, active profile DB path in `gateway/session_persistence.py:151,211,223`, transcript writes in `gateway/run_turn_persistence.py:285,467-517`; real `hermes_state.SessionDB` API inspected locally. No production container inspected or changed.
- R7 local synthetic fixture and R7 image reproduction below → exit 0 each. Image run uses UID 10000, a fresh temporary home, read-only plugin mount, `--network none`, and `--rm`; no model or privileged operation.
- R8 first direct-backend probe → exit 0, **0.321 s for 0.15 s**. Full `Transport.list_messages` reproduction below → exit 0, **1.038 s for 0.6 s**, four candidates, same timeout reused, `http_calls=1`, `model_calls=0`; immediate fake DNS and socket operations only.

## Reproductions of remaining failures

### R7 — directory recovery before restart

Local command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -`, with the following synthetic fixture. No monkeypatch to ledger, hook or persistence failure logic is needed; actual directory permissions cause the failure. Compression history is supplied synthetically, as in the existing compression regressions; no model is called.

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, 'hermes/tests')
import test_scout_mail as t

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    p = t.make_plugin(root)
    p.store.record_result(t.OWNER, ['9001'], [t.render.MARKER + '\n' + t.INJECTED])
    directory = p.store._path.parent
    directory.chmod(0o500)
    try:
        p.pre_llm_call(session_id='S', user_message=t.render.MARKER + '\n' + t.INJECTED)
        print('before_restart_blocked=', p.pre_tool_call(tool_name='web_search', session_id='S') is not None)
        print('durable_lockdown_exists=', p.store._lock_path.exists())
        (p.home / 'compressed-transcript-fixture.txt').write_text('Résumé compressé synthétique.')
        print('sibling_transcript_write_succeeded=', True)
    finally:
        directory.chmod(0o700)
    p = t._restart(root)  # real constructor, same profile home
    p.pre_llm_call(session_id='S', user_message='suite', conversation_history=[
        {'role': 'assistant', 'content': 'Résumé compressé synthétique.'}])
    print('after_repair_restart_tool=', p.pre_tool_call(tool_name='web_search', session_id='S'))
    p.pre_llm_call(session_id='S-child', parent_session_id='S', user_message='suite')
    print('after_repair_child_tool=', p.pre_tool_call(tool_name='web_search', session_id='S-child'))
    print('after_repair_dispatch=', p.pre_gateway_dispatch(event=t.event('Bonjour')))
```

Observed: `True`, `False`, `True`, `None`, `None`, `None`. Constructor logs settings unavailable in the isolated fixture, as `_restart` does in the delivered regression tests; hook/store construction and decisions are the real implementation.

Independent image confirmation uses the real `hermes_state.SessionDB`, not the sibling text file. Command envelope:

```text
docker run --rm --network none -u 10000 -e HERMES_HOME=/tmp/scout-review3
  -v <worktree>/hermes/ansible/roles/hermes_agent/files/plugins:/plugin:ro
  --entrypoint python nousresearch/hermes-agent:v0.22.5 -c <script>
```

The script imports the read-only mounted plugin, constructs `_Plugin(SimpleNamespace(), home)` at `/tmp/scout-review3/profiles/job-search`, reserves synthetic provenance, opens `SessionDB(db_path=home/'state.db')`, and calls `create_session('S', source='telegram')`. With the ledger directory at 0500, it taints `S`, then calls `db.append_message('S', 'user', MARKER+' synthetic message')`. It restores 0700, reconstructs the plugin and repeats the summary-only parent/child hook sequence above. Output:

```text
blocked_before_restart True
actual_Hermes_DB_rows_while_directory_unwritable 1
durable_lockdown_exists False
tool_after_repair_restart None
child_tool_after_repair_restart None
```

This verifies transcript persistence remains possible on the same filesystem. It does not claim to have run a live gateway or model-driven compression.

### R8 — immediate DNS, repeated failed TCP candidates

Command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -`. Real plugin `Transport`, HTTPX, httpcore and Python `create_connection`; only address lookup and the socket operations are doubled. The 0.6-second remaining budget satisfies `Transport`'s 0.5-second pre-request check and models the remaining tail of a request, not a below-minimum configuration.

```python
import sys, socket, time
from unittest.mock import patch
sys.path.insert(0, 'hermes/tests')
import test_scout_mail as t

attempts = []
class CandidateSocket:
    def __init__(self, *a, **kw): pass
    def settimeout(self, value): self.timeout = value
    def bind(self, address): pass
    def close(self): pass
    def connect(self, address):
        attempts.append(self.timeout)
        time.sleep(.25)
        raise socket.timeout('synthetic connect timeout')
def addresses(*a, **kw):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.' + str(i), 443))
            for i in range(1, 5)]

start = time.monotonic()
budget = t.transport.Budget(start + .6, 18, 1)
with patch.object(socket, 'getaddrinfo', addresses), patch.object(socket, 'socket', CandidateSocket):
    try:
        t.transport.Transport(t.settings(), t.transport.HttpxBackend(), t.SECRETS.get, budget).list_messages(8, None)
    except t.transport.BudgetExceeded:
        print(round(time.monotonic() - start, 3), len(attempts),
              all(x == attempts[0] for x in attempts), budget.http_calls, budget.model_calls)
```

Observed: `1.038 4 True 1 0`. No partial body reaches the model; the failure is completion after the absolute deadline while connection attempts continue without a tracked descriptor.

## Not checked

- Live behavioral evaluation, AgentMail read smoke/permission metadata, real keys, hermes-31 version/hashes/log routing, Telegram busy-handler end-to-end behavior and live rendering/link previews: excluded by the brief or pending owner operation. No external network/provider/model/host call made. Loopback and Unix sockets were used only by synthetic offline tests.
- Four real vault-resolving tests were explicitly deselected: `test_t15_effective_value_is_cafe_ia_then_job_search` and the three `test_effective_*` cases in `test_m63_multiplex.py`. The Nora prerequisite test that reads the whole encrypted file was also deselected; direct vault inspection was limited to its header, apart from the accidental ciphertext diff noted above. No decryption or password retrieval occurred.
- The 11 known hanging Kaféine lab tests were deselected per brief; no unrelated lab repair attempted. Production ansible syntax/check/deploy, remote CI/MR refresh, pre-commit and full repository lint hooks not run.

## Reservations and owner decisions after the final cycle

- **Final cycle reached.** F7/F8 remain for the owner; this review authorizes no fourth cycle, merge or enablement. Merging a disabled prototype is an owner's scope/risk decision. The current code must not be represented as meeting the complete subsequent-turn and absolute-duration requirements.
- F7's failure window is narrower than before: the durable marker/rename works when either operation can succeed; the startup probe blocks while the directory stays unwritable. The remaining repaired-before-restart case is nevertheless reproducible with real permissions and a writable Hermes transcript DB. At minimum, recovery must explicitly retire potentially affected contexts before restored permissions and restart can re-enable tools; current runbook's repair/restart-only row is insufficient.
- Normal TLS handshakes, headers and body are now bounded and connections released in the supplied tests. Cancelling the async command still lets its worker finish until the transport stops; it is not immediate cancellation of the wire. DNS plus F8's pre-connect gap limit the claimed worst-case worker duration.
- Ledger capacities remain finite with no expiry; archiving or removing taint hooks loses provenance for historical results and old contexts. `/new` must not be treated as making all archived/reimported mail trusted. The owner must preserve a conservative policy for those contexts when following rollback/recovery steps.
- Q1–Q3 are recorded as answered and the feature remains off. Encryption header and absence of obvious plaintext key patterns do not attest the encrypted variable value or provider-side scope; those remain owner assertions to confirm before enablement.
- Live behavior and AgentMail smoke remain honestly unverified, not silently replaced by refusal strings. Preserve the pending owner-run validation, actual gateway/busy dispatch, Telegram preview settings, log routing and idempotent second deployment checks. No production change was made by this review.
