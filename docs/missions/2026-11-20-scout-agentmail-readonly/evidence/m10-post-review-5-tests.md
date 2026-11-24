# Evidence — tests after review 5 (code a1f91a8d0d011caa4d05aee40ee655cbfa8c3bd0)

Executor: Claude Opus 5.5, 2026-11-23, worktree `.worktrees/homelab-mail01`, Python venv of the worktree, image `nousresearch/hermes-agent:v0.22.5` (local, `--network none`, UID 10000). Synthetic profiles only; no hermes-31 access.

## Pinned CLI facts used by the fix (probed in throwaway containers)

Fresh `HERMES_HOME`, profile `job-search`, rows created with Hermes' own `SessionDB`: 25 telegram sessions, one hidden, one archived, one `source=tool`.
- `hermes -p job-search sessions list`: exit 0, 23 lines (header, rule, 20 rows, truncation note); hidden, archived and tool rows absent (review 5 R11).
- `hermes -p job-search sessions export - --format jsonl` (no filter): exit 0, 28 rows, all of the above; each row carries `archived` and `hidden`. Source: `sessions_cmd.py` `_cmd_export` → `export_all` → `search_sessions(source=None, limit=100000)`, no archived/hidden/source filter.
- `sessions stats`: `Total sessions: 27` (non-archived, `session_count()` adds `archived = 0`), `Total messages: 28` (unfiltered `COUNT(*)`).
- On a profile without `state.db`: export prints `No sessions found.`, stats `Total sessions: 0 / Total messages: 0`.
- `sessions delete <id> --yes`: exit 0 `Deleted session …`; unknown id exit 1; guarded row (`exclude_active_write_guards=True`) exit 1 `Cannot delete active session …`. Deleting a compression parent left its continuation child as its own row (deleted on the next pass).

## Red on 18af837, green on a1f91a8

Scratch tree: `git archive 18af837 hermes/ansible/roles/hermes_agent hermes/tests`, plus `git show 4b7f403:docs/guides/runbook-scout-mail.md` (the runbook reviewed with 18af837); current `test_scout_mail.py`, `test_scout_mail_image.py`, `test_scout_mail_role.py`, `fixtures/scout_mail/image_lab.py` and `fixtures/scout_mail/fake_hermes_sessions.py` copied in unchanged.

Command: `.venv/bin/python -m pytest -p no:cacheprovider <scratch>/hermes/tests/test_scout_mail.py -q --tb=line -k "f7_ or f8_ or f9_ or f10_ or f11_"`.
- 18af837 + 4b7f403 runbook: 9 failed, 18 passed. Failed: test_f7_05 and the seven test_f11_01..05 instances (`retire` module absent), test_f10_01 (`retire.py --delete` not in the Retire step; the step relies on `sessions list`).
- Same tree with only `retire.py` added, so that only the documented procedure differs: 2 failed, 25 passed. test_f7_05 executes the 4b7f403 Retire literally (delete what `sessions list` shows until it prints `No sessions found.`) and fails with `step Apply: old session S-ARCHIVED would get tools`; test_f10_01 fails on the Retire text.
- a1f91a8 + a8b5347 runbook: 27 passed for the same selection.

In-image, `test_scout_mail_image.py`:
- 18af837 plugin: 1 failed (`test_f11_06_real_cli_retires_hidden_archived_tool_and_compressed_sessions`: `scout_mail/retire.py missing`, after its first assertions passed: durable lockdown, and the real `sessions list` hiding S-HIDDEN, S-ARCHIVED, S-TOOL, the compression parent and rows past 20), 7 passed.
- a1f91a8: 8 passed (131 s; each CLI call starts a Hermes process).

test_f11_06 lab values on a1f91a8 (fresh `HERMES_HOME=/tmp/retire-data`, 29 sessions: 24 telegram, hidden, archived, tool, compression parent `P` ended `compression` and its child `P-C`; lockdown fully persisted):

```text
{"sessions": 29, "durable_lockdown": true,
 "list_hides": ["P", "S-ARCHIVED", "S-HIDDEN", "S-TOOL", "S00", "S01", "S02", "S03", "S04"],
 "retire_script": true, "inventory_exit": 3, "inventory_ids": 29,
 "guarded_exit": 2, "guarded_remaining": ["S-HIDDEN"], "locked_after_refusal": true,
 "final_exit": 0, "remaining_sessions": 0, "remaining_messages": 0, "final_inventory_exit": 0,
 "printed_mail_text": false, "fresh_session_tool": null}
```

`guarded_*`: a live compression lock on S-HIDDEN (`try_acquire_compression_lock`, holder without pid, TTL 300 s); `retire.py --delete` deleted the 28 others, reported the refusal and exited 2; the lockdown was still on disk and S-HIDDEN still refused. After `release_compression_lock`, a second run exited 0 with 0 sessions and 0 messages (Hermes' `SessionDB`). Then Clear and Apply; a new session gets tools.

## Changed existing tests

- test_f7_05: Retire now runs whatever §8.1 step 4 prescribes through the CLI (fake CLI `fixtures/scout_mail/fake_hermes_sessions.py`, which mirrors the pinned filters above) instead of `delete from messages`. The synthetic store holds hidden, archived, tool and compressed mail-derived sessions and 24 others.
- test_f10_01: the Retire step must name `retire.py --delete` and its exit condition, and must not use `sessions list`.
- test_role_01: the deployed plugin file list includes `retire.py`.

## Suites on a1f91a8

- `.venv/bin/python -m pytest -p no:cacheprovider hermes/tests/test_scout_mail.py -q`: 132 passed.
- `hermes/tests/test_scout_mail_image.py`: 8 passed. `hermes/tests/test_scout_mail_role.py`: 11 passed.
- Full suite: `ANSIBLE_LOCAL_TEMP=<scratch>/ans-local ANSIBLE_REMOTE_TEMP=<scratch>/ans-remote timeout -s INT -k 5 2400 uv run --no-sync pytest -p no:cacheprovider hermes/tests -q -rs --durations=15 -k "not (test_m7_kafeine and test_lab_)"`: 900 collected, 862 passed, 0 failed, 27 skipped, 11 deselected, 1,431.87 s, exit 0.
  - Skips: 27, all "nousresearch/hermes-agent:v2026.8.18 not available locally".
  - Deselected: the 11 `test_m7_kafeine.py` lab tests (known hang, unchanged file).
  - Slowest setups: m63 multiplex lab 375.9 s, scout03 Kandidat lab 172.7 s, scout_mail image lab 130.3 s.
  - The run started on the working tree before the two commits; pre-commit briefly stashed unstaged files during each commit. No failure resulted; the F7–F11 selection (27 passed) and the plugin suite (132 passed) were also run on the committed code.
- Lint: `uv tool run ruff check --line-length 120 --select E,F,W,B,UP` on the plugin, its tests, the image lab and the fake CLI: 12 findings, all on lines predating this change (7 E501 + 1 UP017 in `test_scout_mail.py`, 1 E501 in the image test, 3 E501 in `test_scout_mail_role.py`, the file now included in the run); none in `retire.py` or the fake CLI.
- Matrix: 92 backticked test references in the threat model, all existing except the four pre-existing range shorthands (`test_c5_01`..`test_c5_05`, `test_f1_01`..`test_f1_05`).
- pre-commit at both commits: passed (gitleaks included).
