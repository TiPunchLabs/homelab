# Evidence — tests after review 3 (code 1182fb53e31bb6c26268f3e7fde8bd37f874458a)

Executor: Claude Opus 5.5, 2026-11-23, worktree `.worktrees/homelab-mail01`, Python venv of the worktree, httpx 0.28.1, httpcore 1.0.9 (same versions in `nousresearch/hermes-agent:v0.22.5`, checked with `docker run --rm --network none … python -c "import httpx, httpcore"`).

## Red on b22ba76, green on 1182fb5

Scratch tree: `git archive b22ba76 hermes/ansible/roles/hermes_agent/files/plugins hermes/tests/fixtures/scout_mail` extracted under the session scratchpad; the current `test_scout_mail.py`, `test_scout_mail_image.py`, `fixtures/scout_mail/image_lab.py` and role `defaults/main.yml` (identical to b22ba76) copied in. No compatibility change: the new F7 tests build the plugin through the real constructor, which exists on both versions.

Command: `.venv/bin/python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail.py -q -k "f7_ or f8_" --tb=line`

- b22ba76: 5 failed, 2 passed.
  - test_f7_01 (directory 0500 with real permissions, transcript row written to `state.db` in the profile home, directory repaired to 0700, restart, compressed history, compressed child): `pre_tool_call` returned None after restart (tool allowed). Review 3 R7.
  - test_f7_02 (lockdown file creation and ledger rename both refused): tool allowed after restart.
  - test_f7_03 (ledger directory reported on another filesystem than the profile home): tool allowed at start.
  - test_f7_04 (nothing writable, not even the state block): in-process refusal already held on b22ba76; it fails only on the log line, which did not tell the operator to retire Scout's sessions before restarting.
  - test_f8_01 (immediate DNS, four TCP candidates whose connect honours its timeout and fails, 0.6 s left, real `Transport`/HTTPX/httpcore): `BudgetExceeded` after 1.04 s, 4 attempts each with the same initial timeout. Review 3 R8.
  - Passing on b22ba76 as well (behaviour kept): test_f7_05 (operator recovery lifts the lockdown), test_f8_02 (a refused candidate falls back to the next one, TLS verified for `api.agentmail.to` on loopback).
- 1182fb5: 8 passed (`-k "f7_ or f8_"`, adds test_f8_03: unknown httpx/httpcore layout fails closed without connecting).

In-image (Hermes' own `hermes_state.SessionDB`, `--network none`, UID 10000): `test_scout_mail_image.py::test_f7_06_real_session_db_repaired_directory_keeps_tools_refused`.
- b22ba76 plugin: 1 failed (`tool_after_restart` None), 5 passed.
- 1182fb5 plugin: 6 passed. Values: blocked before restart, no `taint.lockdown` file (directory 0500), 1 transcript row written by SessionDB, tool and compressed-child tool blocked after repair and rebuild.

Review 3 R8 script rerun verbatim on 1182fb5 (fake socket sleeps 0.25 s whatever its timeout): `0.788 3 [0.563, 0.312, 0.062] 1 0` (elapsed, attempts, per-attempt timeouts, http_calls, model_calls). On b22ba76 the review observed `1.038 4`, same timeout reused. No fourth candidate now; the remaining overrun is the fake ignoring its last 0.062 s timeout.

## Changed existing tests

- test_f6_01 (socket-pair cases) and test_f6_02: the stream injection moved from patching `httpcore SyncBackend.connect_tcp` to replacing `transport._deadline_backend` (helper `_connect_through`), because the plugin now uses its own backend. Same server, TLS and assertions; the loopback cases now go through the new connect path.
- test_f2_01: its fake `httpx.Client` gained a `_transport._pool._network_backend` attribute, since the backend now refuses a client without that layout (test_f8_03).

## Suites on 1182fb5

- `.venv/bin/python -m pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q`: 113 passed in 28.3 s.
- `hermes/tests/test_scout_mail_image.py`: 6 passed in 10.3 s.
- Full suite: `ANSIBLE_LOCAL_TEMP=<scratch>/ans-local ANSIBLE_REMOTE_TEMP=<scratch>/ans-remote uv run --no-sync pytest -p no:cacheprovider hermes/tests -q -rs --durations=15 -k "not (test_m7_kafeine and test_lab_)"`: 879 collected, 841 passed, 0 failed, 27 skipped, 11 deselected, 1,279 s, exit 0.
  - Skips: 27, all "nousresearch/hermes-agent:v2026.8.18 not available locally".
  - Deselected: the 11 `test_m7_kafeine.py` lab tests (known hang, unchanged file, see the review 2 evidence).
  - The run started on the working tree before two lint-only edits that are in 1182fb5: a docstring line wrap in `__init__.py` and, in `test_scout_mail.py`, `socket.timeout` replaced by its alias `TimeoutError` with an unused import removed. The plugin suite (113 passed) and the F7/F8 selection (8 passed) were re-run after those edits.
- Lint: `uv tool run ruff check --line-length 120 --select E,F,W,B,UP` on the plugin, its tests and the image lab: 9 findings, all on lines that predate this change (7 E501 in tests, 1 E501 in the image test, 1 UP017).
- pre-commit at commit time: passed (gitleaks included).
