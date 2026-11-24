# M3 post-change tests, second run

Scope: second post-change run of the hermes test suite, executed after fixes to the job-search declaration wiring. The first post-change run is recorded in `docs/missions/2026-11-20-scout-agentmail-readonly/evidence/m3-post-change-tests.md`.

## Context

- Worktree: `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`
- Git HEAD (short): `3d7bf18`
- `git status --short | wc -l`: 18 (captured before this evidence file was written)
- Run start, UTC: 2026-11-20T14:25:44Z
- Evidence written, UTC: 2026-11-20 14:55 UTC (approximate)
- Operations: read-only with respect to the repository. No repository file was edited, no commit made, nothing installed. The only file written is this evidence file.

## Commands

Per-file test run, executed from the worktree root for each `hermes/tests/test_*.py` (sorted, 19 files):

```bash
timeout 1200 .venv/bin/python -m pytest <file> -q -p no:cacheprovider -rfEs 2>&1 | tail -25
```

Lint:

```bash
.venv/bin/ansible-lint hermes/ansible/roles/hermes_agent/tasks/scout_mail.yml hermes/ansible/roles/hermes_agent/tasks/main.yml hermes/ansible/roles/hermes_agent/defaults/main.yml hermes/ansible/group_vars/hermes/all/main.yml 2>&1 | tail -15
```

Full (untruncated) per-file logs were kept outside the repository for skip extraction, in the session scratchpad.

## Per-file results

Durations are the pytest-reported run time.

| File | Passed | Failed | Skipped | Errors | Duration |
|---|---|---|---|---|---|
| test_dns_resolver_cloud_init.py | 11 | 0 | 0 | 0 | 0.60s |
| test_hermes_checks.py | 68 | 0 | 0 | 0 | 0.04s |
| test_inventory.py | 15 | 0 | 0 | 0 | 1.58s |
| test_kscout01_compact_lookup.py | 28 | 0 | 0 | 0 | 0.06s |
| test_m1_operations.py | 20 | 0 | 0 | 0 | 33.41s |
| test_m2_cafe_ia.py | 93 | 0 | 0 | 0 | 67.56s |
| test_m331_web_tools.py | 3 | 0 | 10 | 0 | 0.08s |
| test_m4_scout.py | 63 | 0 | 10 | 0 | 59.85s |
| test_m5_nora.py | 71 | 0 | 5 | 0 | 60.64s |
| test_m5_recovery.py | 65 | 0 | 0 | 0 | 324.99s |
| test_m63_multiplex.py | 78 | 0 | 5 | 0 | 484.02s |
| test_m66_retirement.py | 31 | 0 | 0 | 0 | 0.95s |
| test_m7_kafeine.py | 47 | 0 | 0 | 0 | 427.33s |
| test_role_tasks.py | 28 | 0 | 0 | 0 | 37.56s |
| test_scout03_kandidat.py | 81 | 0 | 0 | 0 | 182.80s |
| test_scout04_search_budget.py | 17 | 0 | 0 | 0 | 9.33s |
| test_scout_mail.py | 74 | 0 | 0 | 0 | 15.48s |
| test_scout_mail_image.py | 5 | 0 | 0 | 0 | 9.71s |
| test_scout_mail_role.py | 11 | 0 | 0 | 0 | 36.21s |

Every file exited with return code 0.

## Totals

- Collected and executed: 839
- Passed: 809
- Failed: 0
- Skipped: 30
- Errors: 0
- Sum of pytest-reported durations: about 1752 s (about 29 min)

## Failures

None. No failed or errored test id occurred, so no single-id rerun was required.

## Skip reasons

Skips are grouped by reason. Counts are per collected test-run skip entries as printed by `-rfEs`.

- `nousresearch/hermes-agent:v2026.8.18 not available locally`: 27 skips
  - test_m4_scout.py: 10 (lines 677, 686 x4, 696, 706, 711, 718, 729)
  - test_m331_web_tools.py: 10 (lines 178, 185 x4, 196, 208, 214, 223, 233)
  - test_m5_nora.py: 5 (lines 812, 820, 826, 835, 847)
  - test_m63_multiplex.py: 2 (line 476)
- `vault password unavailable: effective inventory not resolvable here`: 3 skips
  - test_m63_multiplex.py: 3 (lines 684, 696, 702)

Interpretation: 27 skipped tests need the pinned Hermes container image, which is not present locally. 3 tests need the Ansible vault password, which is not available in this session. These tests were not executed, so their assertions are not verified by this run.

## Ansible lint

Command: `.venv/bin/ansible-lint hermes/ansible/roles/hermes_agent/tasks/scout_mail.yml hermes/ansible/roles/hermes_agent/tasks/main.yml hermes/ansible/roles/hermes_agent/defaults/main.yml hermes/ansible/group_vars/hermes/all/main.yml`

Result: `Passed: 0 failure(s), 0 warning(s) in 14 files processed of 14 encountered. Last profile that met the validation criteria was 'production'.` Exit code 0.

Non-blocking environment warnings were printed: PATH altered to include the worktree `.venv/bin`, and duplicate collection versions found in `.venv` and `~/.ansible/collections` (community.docker 5.0.5 vs 4.6.0, community.general 12.3.0 vs 11.4.7, community.library_inventory_filtering_v1 1.1.5 vs 1.1.1). The lint verdict is not affected by these warnings.

## Side note

A stray empty directory `/home/xgueret/tmp` was created during this session by a mistaken `mkdir -p` path (outside the repository). It was not removed, because deletion requires user confirmation under the safe-delete policy. It can be removed with `trash /home/xgueret/tmp` on confirmation.
