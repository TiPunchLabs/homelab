VERDICT: CHANGES_REQUESTED
Version: edcd9fe70508f51ad2d06bc84ea3322f11ad5c12
Reviewer: codex

## Previous findings

- **F1: partially fixed.** `taint.py` removes expiry and eviction, bounds persisted results/fingerprints/sessions, writes atomically with mode 0600, and caches reads without pruning. The original eviction, elapsed-time and compression regressions pass. However, the new failure paths do not preserve the complete boundary: an unpersisted restriction disappears on restart (F4), and the final available result slot permits delivery without recording the delivered message IDs (F5). Thus the root requirement, restrictions lasting as long as actionable content, is not yet satisfied.
- **F2: partially fixed.** The stream loop now checks the absolute budget and refuses to return an expired or oversized partial body. The original fake-clock body-trickle regression passes. However, the watchdog captures the pre-TLS socket, which Python detaches during HTTPS setup; it cannot interrupt the active TLS connection (F6). Tests using plain HTTP do not cover either production endpoint's HTTPS transport. Cancellation still leaves the worker running until transport completes; its claimed duration bound inherits F6.
- **F3: fixed.** `summarize.py:83-105` reserves the system prompt, prefix and JSON wrapper before allocating data space, and measures the sum of the final message contents. `config.py` rejects caps below 4,000. All five F3 test instances pass, including inspection of the submitted model request. The fixture run independently reproduces total contexts of 4,460 / 17,201 / 19,977 characters and request sizes of 5,028 / 18,821 / 22,448 bytes. Enforcement occurs while constructing messages, before `transport.complete` in `service.py:222-224`.

Nine focused test instances (`r05`, `f1_01`, `f1_02`, `f2_01`, `f3_*`) pass unchanged on edcd9fe and fail against 78ee2ee. Direct transplantation initially produces mostly API incompatibilities, so a second scratch-only run supplies the old constructor's required retention argument, exposes the existing literal user prefix under the new constant name, and removes the fake client's assertion that the new trace extension exists. Those adaptations leave the old implementation's behavior unchanged; all nine then fail on expiration, eviction/compression, missing deadline exception, incorrect total-context accounting or acceptance of the old minimum. This is meaningful red/green evidence for those cases, not proof of the additional guarantees in §K. The other new tests are subject to the execution limits below.

## Findings

- **F4 [blocker] hermes/ansible/roles/hermes_agent/files/plugins/scout_mail/__init__.py:175 — Failed session persistence protects only the current process.** `_restrict` catches a write failure and puts the session in `self.guarded`, initialized empty at each plugin construction. There is no persisted failure flag or subsequent denial for that session after restart. A readable old ledger does not itself indicate the missed restriction. After compression removes recognizable text, the same session regains every tool. This fails AC2 and the persistence portion of AC4; §K's description of the in-memory guard omits its lifetime limit. **Expected fix:** make failure to persist a restriction prevent reuse of the affected transcript and descendants across restart, or durably fail closed until those contexts are retired. Add a write-failure → compression → restart → subsequent-tool regression, and correct the architecture/matrix/report claims. Evidence: R4 below, exit 0 on this SHA: `before_restart_blocked=True`, `after_restart_tool=None`.

- **F5 [blocker] hermes/ansible/roles/hermes_agent/files/plugins/scout_mail/__init__.py:120 — Capacity can be exhausted between the two provenance writes, after which a delivered result's IDs are silently lost.** The pre-delivery write at line 104 consumes one result slot with no IDs. If that was the last slot, posting succeeds but the second `record_result` raises `LedgerFull`, caught only as a warning. The command returns success. `pre_gateway_dispatch` checks session capacity only, so a reply to the delivered ID with a short, marker-free quote is accepted; the later tool hook also permits it. This loses the ID-based protection precisely where a short quote needs it. It is a reply to an actual delivered result, not a free-standing owner paraphrase. This fails AC2/AC4 and contradicts the full-ledger fail-closed claims. **Expected fix:** reserve sufficient capacity before delivery and persist returned IDs by updating the reserved record; handle post-delivery persistence failures with a durable conservative restriction. Add boundary tests with exactly one result slot remaining and with a failed second write. Evidence: R5 below, exit 0 with the unchanged default `MAX_RESULTS=20000`: one part delivered, `command_return=None`, `delivered_id_recorded=False`, `dispatch=None`, `tool=None`.

- **F6 [major] hermes/ansible/roles/hermes_agent/files/plugins/scout_mail/transport.py:99 — The deadline watchdog targets a detached socket on HTTPS.** The trace callback saves only `connection.connect_tcp.complete`'s socket. Installed httpcore 1.0.9 subsequently calls `SyncStream.start_tls`, which wraps that socket and returns a new stream (`httpcore/_backends/sync.py:144-170`; `_sync/connection.py:155-157`). Python 3.12's `ssl.SSLSocket._create` explicitly calls `sock.detach()` (`ssl.py:978`); ownership of the descriptor moves to the SSLSocket. The watchdog's shutdown of the old socket therefore raises an error that `_shutdown` suppresses. It never targets the active TLS socket. Body checks detect expiry only after a chunk returns; header reads happen before that loop, so trickling headers can keep resetting the operation timeout beyond the wall-clock ceiling. Both allowlisted services use HTTPS. This fails AC6 and leaves cancellation cleanup/duration unverified under AC5. **Expected fix:** enforce an absolute deadline on the active connection throughout TLS setup, headers and body, including blocked operations; verify connection release and absence of partial model input. Add HTTPS handshake/header/body regressions rather than relying on HTTP-only servers, and correct §K, runbook and matrix timing claims. Evidence: R6 below, exit 0, through real HTTPX 0.28.1/httpcore 1.0.9 with only socket/TLS doubles: a 0.15-second deadline returned `BudgetExceeded` after **0.671 seconds**, with **1 raw-socket shutdown attempt, 0 TLS-socket shutdown attempts, 16 header reads**. This is an offline transport reproduction, not a live TLS benchmark.

## Acceptance criteria

`NOT_VERIFIED` includes demonstrated failures, explicitly identified below, as well as unavailable external/runtime checks. Executor evidence is not counted as independently rerun evidence.

| AC | Status | Proof on the reviewed version |
|---|---|---|
| AC1 | NOT_VERIFIED | Discovery and AgentMail evidence files exist, with pinned-version/source references and dated documentation. Read-only fixed-inbox list/get transport inspected. Installed Hermes runtime, deployed hashes, provider scope/read side effects and current external docs were not independently retrieved: no network or hermes-31 access under this brief; Docker socket denied. |
| AC2 | NOT_VERIFIED | ADR-002 describes a fresh tool-less summary context, direct Telegram delivery and persistent subsequent-turn veto. Direct-path separation remains in code; **F4/F5 violate the subsequent-turn boundary**. Actual Hermes dispatch/history integration unavailable. |
| AC3 | NOT_VERIFIED | Threat matrix and code/test mappings updated, but T3/T13's permanent provenance/fail-closed guarantees and T11's duration guarantee remain contradicted by F4–F6. |
| AC4 | NOT_VERIFIED | Completed plugin subset: **73 passed, 16 deselected**; focused old/new comparison: **9 failed on old / 9 passed on new** as qualified above. Reproductions R4–R6 expose missing scenarios. Four loopback tests cannot create sockets, and the complete asynchronous plugin run stalls. No live-model result inferred from deterministic output. |
| AC5 | NOT_VERIFIED | Per-request service counters and existing synchronous concurrent-request test pass in the 73-test subset. One shared `TaintStore` preserves 40 concurrently recorded sessions. No global tool registration/mutation found in plugin changes. Actual Scout-mail/Scout-normal/Nora/Kaféine image integration skipped; cancellation test not completed. F6 invalidates reliance on the deadline for worker completion. |
| AC6 | NOT_VERIFIED | **F3 fixed; F6 still fails the hard transport duration bound.** Field/byte/count/retry tests pass in the completed subset. Fixture totals and request bytes independently reproduced as above; these timings exclude network and model latency. Expired/oversized stream bodies raise before a `RawResponse` is returned, but prompt deadline release of a TLS connection is not established. |
| AC7 | NOT_VERIFIED | **11 Ansible wiring tests passed** within the 122-test run, including fake-key redaction and key-file permissions; deterministic sentinel tests pass in the plugin subset. Scratch ledger file 0600, containing directory 0700; persisted data is IDs/hashes/timestamps. No apparent real-mail/secret addition in the correction diff. Production logs, actual CI artifacts and successful Telegram gateway delivery logs not inspected. |
| AC8 | NOT_VERIFIED | Completed role/check/search tests: **122 passed, 7 skipped**; Kandidat: **60 passed, 21 skipped**; Scout declaration/config subset: **24 passed, 49 deselected**. Correction diff changes no profile declarations, SOUL, Kandidat policy/tool matrix or cron drafts. Full repository suite, lint/hooks and all image behavior not rerun. Report's **827 passed / 27 skipped** is executor evidence, not this review's count. |
| AC9 | VERIFIED | Runbook contains variables, preflight, check/deploy/idempotence, synthetic owner mail procedure, kill switch, rollback, revocation and owner-visible versus trace checks. Added ledger-full operator procedure exists. F5/F6 require correcting its fail-closed and duration guarantees; archiving explicitly loses provenance and must not be treated as preserving the boundary for old digests/transcripts. No deployment executed. |
| AC10 | VERIFIED | Reporting requirement satisfied: `evidence/m4-live-eval.md` and report explicitly state **NOT_VERIFIED**, zero live calls, missing authorized credential/settings and owner command. Live behavior and AgentMail smoke test remain **NOT_VERIFIED by design**, pending Q1–Q4. |
| AC11 | NOT_VERIFIED | Git identifies the named implementation commit and later documentation-only commit. MR !109, pipeline 3096025993 success and production hashes remain pilot/executor observations; no external access, push, comment, merge or deployment by reviewer. |
| AC12 | NOT_VERIFIED | Report has PARTIAL verdict, exact Version, required sections, risks, owner inputs and explicit unavailable live checks. Later documentation's §K honestly records tests/resolver and preview limitations, but its assertion that all three findings are fixed and its permanent veto/hard deadline claims overstate this implementation (F4–F6). The §K and m6 evidence documents were read at HEAD 2a12a2a; code and non-mission design/runbook/matrix were verified identical to edcd9fe. |

## Commands run

Working directory: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`. No source checkout, stash, dependency sync, registry change or permission escalation. Pytest cache disabled; Python bytecode disabled. Only scratch fixtures/old-version extraction under `/tmp` and this review output were written by reviewer commands.

For `uv` commands: `PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR=/tmp/scout-review2-uv UV_OFFLINE=1`; role tests also set `ANSIBLE_REMOTE_TEMP=/tmp/scout-review2-ansible`.

- `git rev-parse HEAD` → exit 0, `2a12a2a078b13c93c1c1855fea73793c30e7c0b2`.
- `git status --short` before output creation → exit 0, only the pre-existing untracked `review-brief-2.md`.
- `git diff --exit-code edcd9fe HEAD -- hermes docs/adr/hermes.md docs/guides/runbook-scout-mail.md docs/references/scout-mail-threat-model.md` → exit 0, no differences; executed code/tests are the named version.
- `git diff --check 3d7bf18 edcd9fe` → exit 0, clean. Read correction diff, targeted numbered source, design/runbook/matrix, review 1, report including §K, owner brief, mission and m6 evidence.
- `git grep -n retention_days edcd9fe -- hermes docs/adr docs/guides docs/references` → exit 1, no matches. A separate search excluding mission documents also found none; historical mission evidence is not active configuration/documentation.
- `timeout -s INT -k 5 45 uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -rs` → exit 137 after stall; 17 progress dots, **no completed-suite count**. No 89-pass claim is made. An initial inline async delivery reproduction also stalled and was interrupted, exit 130; the bounded synchronous reproductions below supply usable evidence instead.
- `timeout -s INT -k 3 35 uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -rs -k 'not c5 and not c7_13 and not c9_01 and not c8_02 and not f1_03 and not f1_04 and not f1_05'` → exit 1, **73 passed, 4 failed, 12 deselected in 1.41s**. All four failures are `_serve` → `socket.socket`: `PermissionError: [Errno 1] Operation not permitted` (`f2_02` ×3 and `f2_03`); classified NOT_VERIFIED, not product failures.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -k 'not c5 and not c7_13 and not c9_01 and not c8_02 and not f1_03 and not f1_04 and not f1_05 and not f2_02 and not f2_03'` → exit 0, **73 passed, 16 deselected in 0.86s**.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -k 'f1_01 or f1_02 or f2_01 or f3 or r05'` → exit 0, **9 passed, 80 deselected in 0.34s** (overlaps the 73 passes; not added to their count).
- `.venv/bin/python -u -` scratch old-version comparison: extract `git archive 78ee2eee3593f25f792793d855dd30cdbc0e6efb hermes` using `tarfile` into a temporary directory, transplant only edcd9fe's `test_scout_mail.py`, invoke `python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail.py -q --tb=line -k 'f1_01 or f1_02 or f2_01 or f3 or r05'` → pytest exit 1, **9 failed, 80 deselected in 0.19s**. Mostly constructor/import/trace-interface failures; not counted as behavioral proof.
- Repeat scratch extraction/transplant with the three compatibility adaptations described above and `pytest.main` using the same selection → pytest exit 1, **9 failed, 80 deselected in 0.18s**. Behavioral failures: expiry/eviction/compressed-child veto missing, no `BudgetExceeded` on trickling response, all total-context assertions fail, old minimum accepted. Both orchestration scripts exited 0 after printing the child's exit 1. No mission worktree source changed.
- `timeout -s INT -k 5 90 uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout_mail_role.py hermes/tests/test_scout_mail_image.py hermes/tests/test_hermes_checks.py hermes/tests/test_kscout01_compact_lookup.py hermes/tests/test_scout04_search_budget.py -q -rs` → exit 0, **122 passed, 7 skipped in 38.41s**. Five mail-image skips and two search-budget image skips.
- `timeout -s INT -k 3 60 uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_scout03_kandidat.py -q -rs` → exit 0, **60 passed, 21 skipped in 7.61s**; skips require the image.
- `uv run --no-sync pytest -p no:cacheprovider hermes/tests/test_m4_scout.py -q -k 's01 or s03_config or s04 or s06 or s08'` → exit 0, **24 passed, 49 deselected in 0.09s**.
- `docker image inspect nousresearch/hermes-agent:v0.22.5 --format '{{.Id}}'` → exit 1, `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`. Generic test skips saying "not available locally" do not establish image absence.
- `uv run --no-sync python hermes/tests/scout_mail_fixture_run.py` → exit 0, totals/request sizes reproduced above; summary-batch median local processing **1.27 / 1.83 / 6.47 ms**, two reply parts each.
- `.venv/bin/python -u -` single-store concurrency/permissions probe, `ThreadPoolExecutor(max_workers=4)` recording 40 distinct sessions → exit 0, **40 retained**, file **0600**, containing directory **0700**. This does not establish locking across multiple store instances or gateway processes.
- R4/R5 and R6 below, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -` → exit 0 each, reproduced the findings on the unchanged named code. Synthetic fixtures only; no model/provider/network operation or privileged tool executed.

## Reproductions

### R4 and R5 — restart and exact default-capacity boundary

R4 creates a readable existing ledger, simulates a transient write failure, then reconstructs the plugin with the same home. R5 seeds 19,999 valid result records to reach the real default boundary without 19,999 disk rewrites. `asyncio.to_thread` is replaced only in this reproduction with direct execution to avoid the observed sandbox stall; ledger/delivery/hook logic is unchanged, and all HTTP operations use the existing fake backend.

```python
import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, 'hermes/tests')
import test_scout_mail as t
from scout_mail import taint
from scout_mail.taint import TaintStoreError

async def inline(fn, *a, **kw):
    return fn(*a, **kw)
asyncio.to_thread = inline

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    p = t.make_plugin(root)
    p.store.record_result(t.OWNER, ['9001'], ['synthetic known result'])
    def broken(_):
        raise TaintStoreError('ledger unwritable')
    p.store.taint_session = broken
    p.pre_llm_call(session_id='S', user_message=t.render.MARKER + ' synthetic mail')
    print('before_restart_blocked=', p.pre_tool_call(tool_name='web_search', session_id='S') is not None)
    p = t.make_plugin(root)
    p.pre_llm_call(session_id='S', user_message='suite', conversation_history=[
        {'role': 'assistant', 'content': 'Résumé compressé.'}])
    print('after_restart_tool=', p.pre_tool_call(tool_name='web_search', session_id='S'))

with tempfile.TemporaryDirectory() as d:
    svc, _, _ = t.make([t.mail('inj_body', 1)])
    posted = []
    p = t.make_plugin(Path(d), svc, posted)
    p.store._save({'version': 1, 'sessions': {}, 'results': [
        {'ts': 0, 'chat': t.OWNER, 'ids': [], 'fp': []}
        for _ in range(taint.MAX_RESULTS - 1)]})
    result = asyncio.run(p.command('', source=t.owner_source()))
    print('default_capacity=', taint.MAX_RESULTS, 'command_return=', result,
          'posted=', len(posted), 'delivered_id_recorded=', p.store.is_result_message(t.OWNER, '9001'))
    print('dispatch=', p.pre_gateway_dispatch(event=t.event(
        'oui fais-le', reply_id='9001', reply_text='court extrait')))
    p.pre_llm_call(session_id='S', user_message='[Replying to: "court extrait"] oui fais-le',
                  conversation_history=[])
    print('tool=', p.pre_tool_call(tool_name='web_search', session_id='S'))
```

Observed R4: `True`, then `None`. Observed R5: `20000`, `None`, `1`, `False`, then `None`, `None`. Separate executions established these outputs; an earlier reduced-capacity run (`MAX_RESULTS=1`) reproduced the same loss of IDs.

### R6 — HTTPS socket replacement and trickling headers

Real HTTPX/httpcore handles the request and trace events. Only TCP creation and TLS wrapping are doubled, modeling the descriptor transfer confirmed in the locally installed Python SSL source. Each header fragment arrives within the configured per-operation timeout, without any real socket or network access.

```python
import sys, time, ssl
from unittest.mock import patch
sys.path.insert(0, 'hermes/tests')
import test_scout_mail as t
from httpcore._backends.sync import SyncBackend, SyncStream

class Wire:
    def __init__(self):
        self.detached = False
        self.shutdowns = self.reads = 0
    def settimeout(self, value): pass
    def send(self, data): return len(data)
    def close(self): pass
    def shutdown(self, how):
        self.shutdowns += 1
        if self.detached:
            raise OSError('Bad file descriptor')
    def recv(self, size):
        time.sleep(.04)
        self.reads += 1
        if self.reads == 1:
            return b'HTTP/1.1 200 OK\r\nX-Test: a'
        if self.reads < 16:
            return b'a'
        return b'\r\nContent-Length: 2\r\n\r\n{}'

raw, tls = Wire(), Wire()
def wrap(ctx, sock, **kw):
    sock.detached = True
    return tls
start = time.monotonic()
deadline = start + .15
with patch.object(SyncBackend, 'connect_tcp', lambda *a, **kw: SyncStream(raw)), \
        patch.object(ssl.SSLContext, 'wrap_socket', wrap):
    try:
        t.transport.HttpxBackend().send('GET', 'https://api.agentmail.to/v0/x', {}, None,
            10, 10000, remaining=lambda: deadline - time.monotonic())
    except t.transport.BudgetExceeded:
        print(round(time.monotonic() - start, 3), raw.shutdowns, tls.shutdowns, tls.reads)
```

Observed: `0.671 1 0 16`. No partial body was returned; the defect is failure to abort the active connection at the deadline.

## Not checked

- Live behavioral evaluation, AgentMail smoke/key scope/read effects, remote documentation, MR/CI state or production hashes: explicitly outside this offline re-review. Their absence alone does not cause CHANGES_REQUESTED.
- Actual Hermes plugin scoping, gateway/busy dispatch, compression lineage, transcript persistence and successful Telegram rendering: Docker inaccessible. Direct-hook reproductions establish missing vetoes, not actual privileged operations in a running gateway.
- Complete asynchronous command/cancellation suite, four loopback transport tests, TLS handshake cancellation and real connection release: sandbox/stall limits stated above. No permissions widened. Report/executor results remain attributed.
- Full repository suite, repository lint/syntax/pre-commit hooks and production logs/CI artifacts: not rerun. No production or mailbox changes made.

## Reservations

- Persistence uses one atomic JSON file per Scout profile with finite entry counts; no time eviction remains. Locking is per `TaintStore` instance, not cross-process. The intended one-plugin-instance-per-profile runtime assumption could not be independently validated here. The in-memory fallback set has no explicit capacity, another reason to replace that fallback with a durable failure policy.
- DNS remains explicitly outside the watchdog's control, as disclosed in §K. F6 is an additional active-TLS defect, independent of that disclosed limitation.
- Telegram link previews remain unconfigured by the plugin; it relies on neutralized URLs. This is honestly disclosed as an enablement verification item, not newly claimed as fixed.
- `retention_days` is absent from active settings/defaults/templates/docs/tests. References describing its removal or recording the old finding in mission evidence are historical, not stale runtime settings.
- Keep the feature disabled pending the remaining boundary fixes and runtime verification. F3 and the original expiry/eviction cases are improved; they do not repair F4–F6.
