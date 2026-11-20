# M3 post-change verification evidence

Date (UTC): 2026-11-20, test run started 13:39 UTC, report written 14:15 UTC
HEAD: 3d7bf18 (`git rev-parse --short HEAD`)
Branch: feat/scout-agentmail-readonly
Worktree: /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01

Scope: read-only verification. No commit, no install, no ansible-playbook run against a real host. One mutating action: pre-commit end-of-file-fixer rewrote two whitespace-only trailing blank lines (see section 6).

## 1. Hermes test suite, per file

Command, per file F (sorted `ls hermes/tests/test_*.py`):

    timeout 1200 .venv/bin/python -m pytest F -q -p no:cacheprovider -rfEs 2>&1 | tail -25

Full outputs kept in the scratchpad, not in the repository.

| File | Passed | Failed | Skipped | Errors | pytest duration |
|---|---|---|---|---|---|
| test_dns_resolver_cloud_init.py | 11 | 0 | 0 | 0 | 0.54s |
| test_hermes_checks.py | 68 | 0 | 0 | 0 | 0.04s |
| test_inventory.py | 15 | 0 | 0 | 0 | 1.62s |
| test_kscout01_compact_lookup.py | 28 | 0 | 0 | 0 | 0.06s |
| test_m1_operations.py | 20 | 0 | 0 | 0 | 34.50s |
| test_m2_cafe_ia.py | 93 | 0 | 0 | 0 | 66.89s |
| test_m331_web_tools.py | 3 | 0 | 10 | 0 | 0.08s |
| test_m4_scout.py | 60 | 3 | 10 | 0 | 49.20s |
| test_m5_nora.py | 70 | 1 | 5 | 0 | 62.53s |
| test_m5_recovery.py | 65 | 0 | 0 | 0 | 323.72s |
| test_m63_multiplex.py | 77 | 1 | 2 | 3 | 425.80s |
| test_m66_retirement.py | 31 | 0 | 0 | 0 | 0.91s |
| test_m7_kafeine.py | 46 | 1 | 0 | 0 | 419.87s |
| test_role_tasks.py | 28 | 0 | 0 | 0 | 36.51s |
| test_scout03_kandidat.py | 80 | 1 | 0 | 0 | 170.08s |
| test_scout04_search_budget.py | 17 | 0 | 0 | 0 | 8.98s |
| test_scout_mail.py | 74 | 0 | 0 | 0 | 15.57s |
| test_scout_mail_image.py | 5 | 0 | 0 | 0 | 9.44s |
| test_scout_mail_role.py | 10 | 0 | 0 | 0 | 21.03s |

Totals: passed 801, failed 7, skipped 27, errors 3, total collected 838. Every file exited with its pytest summary; no per-file timeout was hit.

## 2. Failures and single-id reruns

Each failing or erroring id was rerun once with `.venv/bin/python -m pytest <nodeid> -q -p no:cacheprovider -rfEs`.

| # | Node id | First run | Rerun | Reproduced |
|---|---|---|---|---|
| 1 | hermes/tests/test_scout03_kandidat.py::test_t04_failed_check_then_retry_restarts_once | FAILED | 1 failed in 1.47s | yes |
| 2 | hermes/tests/test_m5_nora.py::test_n08_profile_declarations_are_unchanged_since_m4 | FAILED | 1 failed in 0.11s | yes |
| 3 | hermes/tests/test_m63_multiplex.py::test_lab_every_declared_key_applies_and_reads_back | FAILED | 1 failed in 367.63s | yes |
| 4 | hermes/tests/test_m63_multiplex.py::test_effective_hermes_31 | ERROR (setup) | 1 error in 1.10s | yes |
| 5 | hermes/tests/test_m63_multiplex.py::test_effective_hermes_31_differs_from_the_declarations_by_the_overlay_only | ERROR (setup) | 1 error in 1.09s | yes |
| 6 | hermes/tests/test_m63_multiplex.py::test_effective_inventory_resolves_hermes_31_only | ERROR (setup) | 1 error in 1.15s | yes |
| 7 | hermes/tests/test_m4_scout.py::test_s03_dedicated_vault_references | FAILED | 1 failed in 0.08s | yes |
| 8 | hermes/tests/test_m4_scout.py::test_s05_context_reaches_config_set_verbatim_and_never_the_output | FAILED | 1 failed in 0.50s | yes |
| 9 | hermes/tests/test_m4_scout.py::test_s09_deployed_profiles_probed_but_not_the_candidate | FAILED | 1 failed in 2.56s | yes |
| 10 | hermes/tests/test_m7_kafeine.py::test_k02_nora_and_scout_hints_unchanged | FAILED | 1 failed in 0.10s | yes |

All 10 reproduced. Failure reasons (first lines, observed):

1. test_t04: `assert (2 != 0 and 'NO-GO: kandidat' in '...')`. The ansible-playbook run returned rc=2 (`ok=2 changed=2 failed=1`) and the expected `NO-GO: kandidat` message is absent from stdout.
2. test_n08: `assert {'name': 'job...', ...} == {'name': 'job...', ...}`. Differing items: job-search `env` now contains `AGENTMAIL_API_KEY: "{{ vault_hermes_job_search_agentmail_api_key if hermes_scout_mail_enabled | bool else '' }}"`, and `config` now includes `plugins.enabled: "{{ ['scout_mail'] if hermes_scout_mail_enabled | bool else [] }}"`. The test expects the M4 declarations (only TAVILY_API_KEY).
3. test_lab_every_declared_key...: `AssertionError: {'job-search:plugins.enabled': 1}` / `assert {0, 1} == {0}`. A `plugins.enabled` key on job-search is applied with value 1 while the expected set is {0}.
4-6. test_effective_*: setup error at `hermes/ansible/roles/hermes_agent/tasks/validate.yml:137` ("Assert that each profile env value is set"): `[ERROR]: Task failed: Action failed: Profil n°1 : une cle de env est vide.` The play summary reports `failed=1` for hermes-31 (target host name as printed by the test fixture; whether a real host was contacted was not checked).
7. test_s03: `assert {'TAVILY_API_...'} == {'TAVILY_API_...'}`. Left side contains one extra key, `AGENTMAIL_API_KEY` (same declaration change as item 2).
8. test_s05: ansible-playbook (test-local play.yml) fails with `[ERROR]: Task failed: 'hermes_scout_mail_enabled' is undefined`.
9. test_s09: `assert not True` / `any(...)` over deployed profiles: the probe for job-search is reported as present when the test expects it absent (candidate not deployed).
10. test_k02: same differing `env` / `config` items as item 2.

Observed relation: all 10 failing ids touch the job-search profile declarations (`AGENTMAIL_API_KEY`, `plugins.enabled` gated on `hermes_scout_mail_enabled`) introduced by the uncommitted scout_mail change in `hermes/ansible/roles/hermes_agent/defaults/main.yml` and `hermes/ansible/group_vars/hermes/all/main.yml`. Hypothesis, not verified: the tests encode the pre-change M4/M7 declarations and need updating, or the new declarations leak into profiles where scout_mail is disabled. This report does not establish which is correct.

## 3. Skipped tests

All 27 skips have the same reason: `nousresearch/hermes-agent:v2026.8.18 not available locally` (Docker image absent on this workstation).

| File | Skipped |
|---|---|
| test_m331_web_tools.py | 10 |
| test_m4_scout.py | 10 |
| test_m5_nora.py | 5 |
| test_m63_multiplex.py | 2 |

Skips are environmental, not failures. The image-dependent checks were not executed.

## 4. ansible-lint

Command (repo root):

    .venv/bin/ansible-lint hermes/ansible/roles/hermes_agent/tasks/scout_mail.yml hermes/ansible/roles/hermes_agent/tasks/main.yml hermes/ansible/roles/hermes_agent/defaults/main.yml hermes/ansible/group_vars/hermes/all/main.yml

Result: `Passed: 0 failure(s), 0 warning(s) in 14 files processed of 14 encountered. Last profile that met the validation criteria was 'production'.` Exit 0.

Non-blocking environment warnings: collection version mismatches between `.venv` site-packages and `~/.ansible/collections` (community.docker 5.0.5 vs 4.6.0, community.general 12.3.0 vs 11.4.7, community.library_inventory_filtering_v1 1.1.5 vs 1.1.1). Not run from `hermes/` since the repo-root run passed.

## 5. ansible-playbook syntax check

Command (from `hermes/`):

    ../.venv/bin/ansible-playbook ansible/deploy.yml --syntax-check

Result: `playbook: ansible/deploy.yml`, exit 0. No vault decryption was needed and none was attempted.

## 6. pre-commit (changed and new files, no manual fix)

Scope: `git status --porcelain -uall` minus `docs/missions/`, 6 modified tracked files and 25 untracked files (plugins/scout_mail/*, tasks/scout_mail.yml, tests/fixtures/scout_mail/*, tests/scout_mail_*.py, tests/test_scout_mail*.py, docs/guides/runbook-scout-mail.md, docs/references/scout-mail-threat-model.md).

Command:

    .venv/bin/pre-commit run --files <scope>

Hook results:

| Hook | Result |
|---|---|
| fix end of files | Failed (auto-modified 2 files, see below) |
| trim trailing whitespace | Passed |
| check yaml | Passed |
| check for merge conflicts | Passed |
| check for added large files | Passed |
| Detect hardcoded secrets (hook id `gitleaks`) | Passed, no findings reported |
| shfmt | Skipped (no files) |
| ShellCheck | Skipped (no files) |
| Ansible Lint | Passed |
| Check Ansible Vault Encryption | Skipped (no files) |
| GitLab CI Lint | Skipped (no files) |
| Terraform fmt / validate / tflint | Skipped (no files) |

Exit code: 1 (caused by the end-of-file-fixer modification).

Auto-fixed files (whitespace only, left in place):
- docs/adr/hermes.md: diff went from 54 to 53 added lines (trailing blank line removed).
- hermes/ansible/roles/hermes_agent/defaults/main.yml: diff went from 17 to 16 added lines (trailing blank line removed).

`git diff --stat` after the fix: 6 files changed, 185 insertions(+), against 187 before the fix. Untracked files were not modified by the hook report; the hook reported only the two files above.

Gitleaks: no finding reported, so no rule id or file:line to record.

## 7. Limitations

- Test results describe the working tree as it was at 13:39 to 14:10 UTC, including uncommitted changes listed in section 6.
- The 27 skipped tests were not executed (Docker image missing locally).
- Root cause of the 10 failures was not investigated; section 2 only records observed assertions.
- Nothing was committed, pushed, installed, or run against a real host.
