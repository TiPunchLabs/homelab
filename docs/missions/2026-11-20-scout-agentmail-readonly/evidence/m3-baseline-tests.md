# M3 baseline Hermes test suite

## Attempt history

- First attempt (uv with CPython 3.15, `rpds-py` build failure against PyO3 maximum 3.14) did not run; no pytest was executed in that attempt.
- The venv was then rebuilt on Python 3.12 by the executor. This run uses that venv.

## Command

    cd /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01
    timeout 1500 .venv/bin/python -m pytest hermes/tests -q -p no:cacheprovider --ignore-glob='hermes/tests/test_scout_mail*' -rfEs

Run wrapper: stdout+stderr redirected to a scratchpad log (`/tmp/claude-1000/-home-xgueret-Workspace-02-infrastructure--worktrees-homelab-mail01/e5b6f2c7-bbbb-470d-8c29-f986f88ecd63/scratchpad/full1.log`). The `| tail -80` form of the mission command was not used, so the full output was kept.

## Context

- Git HEAD (short): 3d7bf18
- Run start (UTC): 2026-11-20T13:08:41Z
- Python in venv: Python 3.12.12 (`.venv/bin/python -V`)
- Tests collected: 749 (collect-only, same command flags)
- Untracked test_scout_mail* files: none matched the ignore glob.
- Repository files modified by this run: none.

## Result

Status: TIMEOUT. The 1500 s limit (`timeout`, exit code 124) was reached at about 13:33:41Z before pytest printed its summary. No final pytest summary line exists for this run.

Last progress line before the kill (dots and letters, 711 of 749 tests reported):

    ...............................................................EXIT=124

Tests not executed in this run: 38 (collected indices 711 to 748, starting at `hermes/tests/test_scout03_kandidat.py::test_l01_declaration_applies_and_converges`).

## Failed or errored test ids

No summary was printed, so the ids below are inferred from the progress characters by position in collect-only order. This is an inference, not a pytest report.

- `hermes/tests/test_m5_recovery.py::test_r10_closed_database_is_restored_with_its_sidecars_set_aside` (progress char F, 1 occurrence)

Reason lines: not captured (no failure section was printed because the run did not finish). First 3 lines of reason: NOT_AVAILABLE.

Rerun (same flags, isolated, once):

- `test_r10_closed_database_is_restored_with_its_sidecars_set_aside`: 1 passed in 23.31s. Not reproduced.

The test that was in progress when the run stopped, `hermes/tests/test_scout03_kandidat.py::test_l01_declaration_applies_and_converges`, was rerun once in isolation: 1 passed in 173.84s (0:02:53). Not reproduced as a hang. The baseline stop is consistent with the whole suite exceeding the 25-minute limit; this is a hypothesis, not confirmed.

## Skipped tests

27 skipped in the progress output, all with the same reason. Grouped by file from the isolated rerun of the 27 mapped ids (`-rs`):

- Reason (all 27): `nousresearch/hermes-agent:v2026.8.18 not available locally`
- `hermes/tests/test_m331_web_tools.py`: 10 (lines 178, 185, 196, 208, 214, 223, 233)
- `hermes/tests/test_m4_scout.py`: 10 (lines 676, 685, 695, 705, 710, 717, 728)
- `hermes/tests/test_m5_nora.py`: 5 (lines 812, 820, 826, 835, 847)
- `hermes/tests/test_m63_multiplex.py`: 2 (line 476)

Caveat: the 27 skipped ids were mapped from progress-character positions; the grouping above is from running those mapped ids, and was not cross-checked against a full-run `-rs` summary.

## Side effects

- None in the repository. The venv at `.venv` was used as provided.
- Scratch files only, in the scratchpad directory.

## Next step required

Rerun the full suite with a longer limit or split it by file (for example by `hermes/tests/test_m5_recovery.py` and `hermes/tests/test_scout03_kandidat.py` separately) to obtain a real summary line, failure reasons and skip counts. Not done here.
