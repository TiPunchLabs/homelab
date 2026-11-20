# M6 post review 1 tests

Scope: full hermes suite after the corrections for review 1 (F1, F2, F3).

- Worktree: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`
- Code under test: working tree later committed as `edcd9fe70508f51ad2d06bc84ea3322f11ad5c12` (identical content)
- Run: 2026-11-20T21:32:47Z to 2026-11-20T22:02:40Z, executor session (no subagent)
- Command, per file, sorted: `timeout 1200 .venv/bin/python -m pytest <file> -q -p no:cacheprovider -rfEs`

| File | Passed | Failed | Skipped |
|---|---|---|---|
| test_dns_resolver_cloud_init.py | 11 | 0 | 0 |
| test_hermes_checks.py | 68 | 0 | 0 |
| test_inventory.py | 15 | 0 | 0 |
| test_kscout01_compact_lookup.py | 28 | 0 | 0 |
| test_m1_operations.py | 20 | 0 | 0 |
| test_m2_cafe_ia.py | 93 | 0 | 0 |
| test_m331_web_tools.py | 3 | 0 | 10 |
| test_m4_scout.py | 63 | 0 | 10 |
| test_m5_nora.py | 71 | 0 | 5 |
| test_m5_recovery.py | 65 | 0 | 0 |
| test_m63_multiplex.py | 81 | 0 | 2 |
| test_m66_retirement.py | 31 | 0 | 0 |
| test_m7_kafeine.py | 47 | 0 | 0 |
| test_role_tasks.py | 28 | 0 | 0 |
| test_scout03_kandidat.py | 81 | 0 | 0 |
| test_scout04_search_budget.py | 17 | 0 | 0 |
| test_scout_mail.py | 89 | 0 | 0 |
| test_scout_mail_image.py | 5 | 0 | 0 |
| test_scout_mail_role.py | 11 | 0 | 0 |

Totals: 854 collected, 827 passed, 0 failed, 27 skipped, 0 errors. Every file exited 0.

Skips: all 27 are `nousresearch/hermes-agent:v2026.8.18 not available locally`. The 3 vault-dependent tests of `test_m63_multiplex.py` that skipped in `m3-post-change-tests-2.md` ran and passed this time.

Delta versus `m3-post-change-tests-2.md`: +15 tests in `test_scout_mail.py` (`test_f1_01`..`test_f1_05`, `test_f2_01`, `test_f2_02` x3, `test_f2_03`, `test_f3_01` x3, `test_f3_02`, `test_f3_03`); `test_r05_retention_prunes_old_results` replaced by `test_r05_nothing_expires_with_time`.

Other checks on the changed files: pre-commit (incl. gitleaks) passed at commit; `uv tool run ruff check --select E,F,W,B,UP --line-length 125` clean.

Fixture rerun (`evidence/m6-fixture-run-r1.json`): `model_context_chars` is now the TOTAL content sent to the model (system prompt + prefix + data): 4,460 / 17,201 / 19,977 for the three summary batches (previously data only: 3,258 / 15,999 / 19,971). The HTML-heavy batch stays at or below the 20,000 cap; request bytes 5,028 / 18,821 / 22,448.
