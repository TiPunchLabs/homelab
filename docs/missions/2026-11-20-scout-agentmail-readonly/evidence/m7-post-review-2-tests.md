# Evidence — tests after review 2 (code b22ba76472d3884e24a2954e40ec7e2b4793b040)

Executor: Claude Opus 5.5, 2026-11-21, worktree `.worktrees/homelab-mail01`, Python venv of the worktree, httpx 0.28.1, httpcore 1.0.9.

## Red on edcd9fe, green on b22ba76

Scratch tree: `git archive edcd9fe hermes` extracted under the session scratchpad, current `hermes/tests/test_scout_mail.py` copied in. One compatibility change in the scratch copy only: the test helpers `make_plugin` and `_no_init_plugin` also set `guarded = set()` (attribute removed by the fix). No source file of the worktree changed.

Command: `.venv/bin/python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail.py -q -k "f4_ or f5_ or f6_" --tb=line`

- edcd9fe: 9 failed, 7 passed.
  - test_f4_01, test_f4_02, test_f4_04: `pre_tool_call` returned None after restart (tool allowed).
  - test_f4_03: message not refused after restart (`None` instead of the registry rewrite).
  - test_f5_01: `is_result_message(OWNER, "9001")` False (delivered id lost at the last slot).
  - test_f5_02, test_f5_03: reply to the delivered message accepted (`None` instead of the registry rewrite).
  - test_f6_01[headers-loopback], test_f6_01[headers-socketpair]: "the exchange outlived the deadline" (worker still running after 6 s, 1 s deadline).
  - Passing on edcd9fe as well: test_f6_01 handshake, body and stall_body cases (both wires) and test_f6_02. The stall cases are already bounded by the per-operation timeout capped at the time left; the trickled body by the per-chunk check. Kept as HTTPS regressions.
- b22ba76: 16 passed (same selection, worktree).

## Suites on b22ba76

- `uv run pytest hermes/tests/test_scout_mail.py -q -p no:cacheprovider`: 105 passed in 27.74 s.
- `uv run pytest hermes/tests/test_scout_mail_image.py -q -rs`: 5 passed in 9.44 s (image nousresearch/hermes-agent:v0.22.5 present locally).
- `uv run pytest hermes/tests/test_scout_mail_role.py hermes/tests/test_role_tasks.py hermes/tests/test_m4_scout.py -q` (after the Q1 inbox id, commit 53c0f8c): 102 passed, 10 skipped.
- Full suite: `uv run pytest hermes/tests -q -p no:cacheprovider -rs --durations=15 -k "not (test_m7_kafeine and test_lab_)"`: 870 collected, 832 passed, 0 failed, 27 skipped, 11 deselected, 1,318 s, exit 0.
  - Skips: 27, all "nousresearch/hermes-agent:v2026.8.18 not available locally" (test_m331_web_tools, test_m4_scout, test_m5_nora, test_m63_multiplex).
  - Deselected: the 11 `test_m7_kafeine.py` lab tests. A first full run without deselection stopped progressing at `test_lab_kafeine_config_and_hint_apply` for more than 20 minutes (process in `hrtimer_nanosleep`, lab container `hermes-m7-lab-gw` up); a 200 s run of that file alone stopped at the same test. The file is not changed by this MR. The interrupted runs were stopped and the lab container removed.
  - Slowest: test_m63_multiplex lab setup 374.8 s, test_scout03_kandidat lab setup 177.5 s.
- Lint: `uv tool run ruff check --isolated --select E,F,W --line-length 120` on the plugin and its test file: 7 findings, all E501 on lines that predate review 2 (the same 7 on edcd9fe).
- pre-commit hooks at commit time: passed (ansible-lint, gitleaks, yaml, vault encryption check for 225fc3a).
