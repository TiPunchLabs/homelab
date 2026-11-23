# Evidence — tests after review 4 (code 18af8373aca7cf18098ea55748f9f839d1b4189a)

Executor: Claude Opus 5.5, 2026-11-23, worktree `.worktrees/homelab-mail01`, Python venv of the worktree, httpx 0.28.1, httpcore 1.0.9, image `nousresearch/hermes-agent:v0.22.5` (local).

## Red on 1182fb5, green on 18af837

Scratch tree under the session scratchpad: `git archive 1182fb5 hermes/ansible/roles/hermes_agent hermes/tests`, plus `git show f55c226:docs/guides/runbook-scout-mail.md` at `docs/guides/runbook-scout-mail.md` (the runbook reviewed with 1182fb5). The current `test_scout_mail.py`, `test_scout_mail_image.py` and `fixtures/scout_mail/image_lab.py` are copied in unchanged. No compatibility edits.

Command: `.venv/bin/python -m pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q -k "f7_ or f8_ or f9_ or f10_" --tb=line -rA` (run from the scratch root).

- 1182fb5: 12 failed, 8 passed.
  - test_f9_01_short_state_writes_are_completed: `store.locked()` False after a 3-byte write reported as 3 (review R9).
  - test_f9_02 [stalls], [over_reports], [raises_midway]: no `NOT persisted` log (the false success took the ordinary success path).
  - test_f9_03 [empty], [short-locked], [short-armed], [unpadded-locked], [garbage], [armed-plus-tail]: `pre_tool_call` returned None after restart (tool allowed; `arm()` overwrote the block with `armed`).
  - test_f7_05_operator_recovery_in_runbook_order_never_hands_tools_to_an_old_session and test_f10_01_runbook_recovery_retires_sessions_before_unloading_or_restarting: `runbook section 8.1 (recovery order) missing`.
  - Passing on both (behaviour kept): test_f7_01 to test_f7_04, test_f8_01 to test_f8_03, test_f9_04_fresh_state_block_is_complete_and_linked_once.
- 18af837: 20 passed for the same selection.

In-image (Hermes' own `hermes_state.SessionDB`, `--network none`, UID 10000): `test_scout_mail_image.py`.
- 1182fb5 plugin: 1 failed (`test_f9_05_real_session_db_short_state_write_keeps_tools_refused`: `state_locked` False), 6 passed.
- 18af837: 7 passed.

Review 4 R9 script rerun verbatim on the fix (`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -u -`), exit 0:

```text
current_blocked= True lockdown_file= False state_recognized_locked= True transcript_rows= 1
scout_mail lockdown state present or unrecognized at start; Scout refused until the operator intervenes (runbook, section 8.1)
after_restart_parent= {'action': 'block', ...} child= {'action': 'block', ...}
```

On 1182fb5 the review observed `state_recognized_locked= False` and `None` for both.

## Changed existing tests

- test_f7_05 was rewritten (renamed `test_f7_05_operator_recovery_in_runbook_order_never_hands_tools_to_an_old_session`): it now reads the step names of runbook §8.1 and executes them in document order against a synthetic `state.db`. It still checks that removing both markers lifts the lockdown for a new session. No other existing test changed.

## Suites on 18af837

- `.venv/bin/python -m pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q`: 125 passed in 28.7 s.
- `hermes/tests/test_scout_mail_image.py`: 7 passed in 10.0 s.
- Full suite: `ANSIBLE_LOCAL_TEMP=<scratch>/ans-local ANSIBLE_REMOTE_TEMP=<scratch>/ans-remote uv run --no-sync pytest -p no:cacheprovider hermes/tests -q -rs --durations=15 -k "not (test_m7_kafeine and test_lab_)"`: 892 collected, 854 passed, 0 failed, 27 skipped, 11 deselected, 1,251 s, exit 0.
  - Skips: 27, all "nousresearch/hermes-agent:v2026.8.18 not available locally".
  - Deselected: the 11 `test_m7_kafeine.py` lab tests (known hang, unchanged file).
  - The run was on the working tree whose code and tests equal 18af837 (committed after the run, without further edits to them). The runbook read by test_f10_01 / test_f7_05 was already in its final form; ADR, matrix and report were edited during the run (no test reads them).
- Lint: `uv tool run ruff check --line-length 120 --select E,F,W,B,UP` on the plugin, its tests and the image lab: 9 findings, all on lines that predate this change (7 E501 in tests, 1 E501 in the image test, 1 UP017).
- pre-commit at commit time: passed (gitleaks included).
