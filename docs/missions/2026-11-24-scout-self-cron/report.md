# Report — homelab/2026-11-24-scout-self-cron (SCOUT-CRON)

Verdict: PASS
Version: 5a1fb5a (branch `feat/scout-self-cron`; commits 8ea5783 plugin, 3f22db6 role/config/SOUL/checks, 20e4e70 tests, 5cff2b9 docs, 5a1fb5a test alignment; this report is committed on top)
MR: https://gitlab.com/tipunchlabs/homelab/-/merge_requests/111 (draft, source branch kept on merge)
Executor: Claude Code, model Claude Opus 5.5 (`claude-opus-5-5`). Delegations: none. Every search, test run, log parse, security design and enforcement code was done by the executor model; no subagent was used.

## Executive summary

- Objective: in a Telegram conversation with the owner, Scout creates, updates in place, lists, pauses, resumes and deletes its own scheduled tasks. Guards G1–G6 apply. Unattended runs keep a per-task record and deduplicate.
- Done:
  - new plugin `scout_cron`, enabled for Scout only;
  - Scout config: per-platform tools, cron toolsets narrowed (D9), timezone `America/Guadeloupe` on Scout only;
  - Scout SOUL rules;
  - role task with a switch-consistency guard;
  - post-deploy check `hermes_checks.py scout-schedule`, and a per-platform `toolsets` check;
  - unit, role and image tests: two image labs, with `tool_search` off as on hermes-31 and on (Hermes default);
  - runbook; README M4.4 section rewritten.
- Not done, by design: no deployment, no restart, nothing written on hermes-31; check mode only (E3).
- Every acceptance criterion is verified by tests on the real Hermes v0.22.5 image, except Telegram's own transport and button rendering. Both are faked in the lab and listed under owner tests.

## Initial state and scope

- Base `origin/main` 975e302. Branch `feat/scout-self-cron`. Worktree `.worktrees/homelab-scoutcron`.
- hermes-31, read-only inspection on 2026-11-24:
  - Scout has no `jobs.json`, and neither do default and cafe-ia. Scout's ticker is alive. No ESTOP.
  - Scout config: `timezone`, `approvals`, `cron`, `command_allowlist` and `memory` unset; `plugins.enabled: [scout_mail]`; `cronjob` in `agent.disabled_toolsets`.
  - Live Scout SOUL sha256 `7dc753fe…`, identical to the repo SOUL at 975e302.
- Excluded: deployment, restarts, any write on hermes-31, Telegram messages, mail, Kandidat writes, and any change to Scout memory approval (requirement c).

## Work performed

Created:
- `hermes/ansible/roles/hermes_agent/files/plugins/scout_cron/`:
  - `__init__.py`: hooks, tool, command;
  - `policy.py`: pure decision on cronjob_manage arguments;
  - `schedule.py`: daily-cap rule and next runs;
  - `ledger.py`: alerted-vacancy ledger;
  - `config.py`: bounded settings;
  - `hermes_port.py`: every Hermes internal used, in one place;
  - `plugin.yaml`.
- `hermes/ansible/roles/hermes_agent/tasks/scout_cron.yml`.
- Tests: `hermes/tests/test_scout_cron.py`, `test_scout_cron_role.py`, `test_scout_cron_image.py`, plus fixtures `hermes/tests/fixtures/scout_cron/fake_llm.py` (scripted OpenAI-compatible model on 127.0.0.1) and `image_lab.py`.
- `docs/guides/runbook-scout-cron.md`, `docs/missions/2026-11-24-scout-self-cron/design.md`, `report.md`.

Modified:
- `group_vars/hermes/all/main.yml`:
  - `hermes_scout_cron_enabled: true`;
  - Scout: `plugins.enabled: [scout_mail, scout_cron]`, `timezone: America/Guadeloupe`;
  - telegram list + `cronjob`, `scout_task_record`;
  - cron list = `web, skills, kandidat, scout_task_record`;
  - api_server/cli literal lists, unchanged in content;
  - `known_plugin_toolsets.{api_server,cli}: [scout_task_record]`;
  - `cronjob` removed from Scout's deny list;
  - SOUL predecessor `7dc753fe…` added.
- `defaults/main.yml`: scout_cron defaults, off.
- `tasks/main.yml`: deploy include, and the post-restart `scout-schedule` check.
- `tasks/profile_multiplex.yml`: the `toolsets` check receives one allowlist per platform.
- `tasks/scout_mail.yml`: its switch assertion admits `scout_cron` next to `scout_mail`. Without this the deploy would have failed.
- `files/hermes_checks.py`:
  - new `scout-schedule` mode and `scout_cron_errors`;
  - `toolset_errors`/`tool_errors` accept per-platform allowlists;
  - the `toolsets` mode computes exposure as a gateway session sees it (`HERMES_GATEWAY_SESSION=1`);
  - the `scout-mail` registry diff ignores scout_cron's own toolset.
- `files/profiles/job-search/SOUL.md`: « Tâches planifiées » section; « Tes limites » updated (14,289 → 15,496 characters).
- Role README: M4.4 section replaced; cron-safety notes.
- `hermes/cron-drafts/job-search.yml`: marked historical.
- `CLAUDE.md`: SCOUT-CRON note.
- Existing tests aligned on the deliberate changes (list under Deviations).

Executed:
- `uv run pytest` equivalents (`.venv/bin/python -m pytest hermes/tests`);
- `pre-commit run` (ansible-lint, gitleaks, yaml: passed);
- `ruff` (safe fixes only);
- the check-mode playbook (E3).

Pushed: branch `feat/scout-self-cron`; draft MR !111. Nothing merged, nothing deployed.

## Design as implemented (summary)

- G1:
  - Config: `cronjob` and `scout_task_record` on Scout's telegram only; `known_plugin_toolsets` keeps the plugin toolset off api_server/cli, since plugin toolsets are on by default.
  - Hermes denies `cronjob` in every cron run (`cron.allow_agent_scheduling` false).
  - The plugin blocks `cronjob_manage` unless all of these hold: profile job-search, no cron execution or marker, platform telegram, chat type `dm`, user and chat in the owner allowlist.
  - The record tool's handler enforces its context: cron actions only inside a cron execution, using that execution's job id; `feedback_add` only in the owner chat.
- G2:
  - For create, update, remove, resume and `feedback_add`, the plugin first calls every other plugin's `pre_tool_call` callback directly. If one vetoes, it posts nothing and blocks.
  - Otherwise it posts the verbatim proposal, split at line boundaries below 3,500 characters per message, then returns `approve` with a ≤ 450-character card and the rule key `scout_cron:<random>`.
  - Hermes' gateway approval gate does the rest: button, 300 s timeout, silence = refusal.
  - `/yolo` or `approvals.mode: off` → block.
  - Fail closed on any error.
- G3: policy on the arguments and the stored jobs:
  - N = 5 jobs, paused included, plus pending creates;
  - Hermes `parse_schedule` must give a 5-field cron with a fixed minute and hour;
  - `deliver` omitted or `origin`; G1 makes origin the owner's DM;
  - prompt ≤ 6,000 characters, name ≤ 80, unique name;
  - forbidden fields refused;
  - `run`/`run_now`/`trigger` refused;
  - a per-execution call cap in cron: 40 calls, 20 web.
- G4: scout_mail's veto wins over approval (Hermes precedence), and requirement (a) is met: scout_cron posts nothing when another hook vetoes.
- G5:
  - The journal is Hermes' notepad key `journal`, injected at the start of every run, with a 3,000-character cap. Owner feedback is notepad key `feedback`, 1,500 characters, under approval.
  - The ledger is `plugin-data/scout_cron/ledger/<job_id>.json`: 0600, 16-hex hashes of normalized URLs, 180 days, 5,000 entries. It is deleted when the owner removes the job through Scout.
- G6: Nora, Kaféine, scout_mail, the Kandidat MCP policy and Scout's api_server/cli lists are unchanged. The role creates no job.

## Verification and evidence

Test counts (exact):

| Run | Command | Result |
|---|---|---|
| Baseline, base commit 975e302 in a git worktree | `python -m pytest hermes/tests -q` | 1 failed, 872 passed, 27 skipped (pre-existing failure: `test_m5_recovery.py::test_r10_closed_database_is_restored_with_its_sidecars_set_aside`) |
| Branch, full run on HEAD 5cff2b9 | `python -m pytest hermes/tests -q` | 1 failed, 1061 passed, 27 skipped. The failure was `test_m63_multiplex.py::test_multiplex_profile_shares_the_deployed_tasks[Verify that the declared tool restrictions]`: it requires the multiplexed toolsets task to equal profile.yml's, which stays frozen (test_n08) |
| Branch, after the fix 5a1fb5a (test-only change) | `python -m pytest hermes/tests/test_m63_multiplex.py -k "shares_the_deployed or tool_surface"` | 11 passed. The full suite was not re-run after this one-test change: expected 1062 passed, 27 skipped, 0 failed, not measured |
| New: offline unit | `test_scout_cron.py` | 92 passed |
| New: role/declarations | `test_scout_cron_role.py` | 11 passed |
| New: image lab | `test_scout_cron_image.py` | 86 passed (43 tests × 2 labs, tool_search off/auto) |

The run on the untouched base commit is the reference: everything passing there passes on the branch except the deliberately updated assertions listed under Deviations.

Acceptance criteria:

| AC | What was verified | Method / evidence | Status |
|---|---|---|---|
| AC1 G1 | Plugin, command and tools for Scout only; `cronjob` on telegram only; `scout_task_record` on telegram and cron only; api_server, cli, Nora and Kaféine cannot schedule; strangers and groups refused; cron runs cannot schedule or add feedback; record tool refused in chat | `test_g1_01`–`06` (image), `test_hook_02/03` (unit), `test_decl_01/02` (role); check `scout-schedule` returns 0 on the lab and 1 when the switch disagrees (`test_g3_06`) | VERIFIED |
| AC2 G2 | Denied → nothing saved; timeout → nothing saved; approved → saved exactly as shown (prompt text found in the posted proposal, `0 7 * * 1-5`, `07:00:00-04:00`, origin = owner DM); posts precede the card; single-use keys (5 distinct); `/yolo` refused before any post; update in place, same id; resume and feedback need the card; list and pause need none; no `command_allowlist` entry | `test_g2_01`–`09` (image, both labs), `test_hook_01/04/11` (unit). Enforcement type: code (plugin `pre_tool_call` + Hermes approval gate) | VERIFIED |
| AC3 G3 | Refused with nothing posted: `*/30 * * * *`, `every 2h`, `in 1h`, `0 7,19 * * *`, `telegram:999`, `all`, `failure_deliver`, `script`, `enabled_toolsets`, `no_agent`, `workdir`, 6,001-character prompt; 6th job refused (paused counted); duplicate name; `run`; web cap at 3 and total cap at 8 in a lab cron run | `test_g3_01`–`05` (image), `test_pol_03/05/06/09`, `test_hook_07/08` (unit) | VERIFIED |
| AC4 G4 | Tainted session (scout_mail taint set through its real `pre_llm_call` hook): create blocked, no proposal posted, no card, nothing saved, while under the job cap | `test_g4_01` (image), `test_hook_04` (unit) | VERIFIED |
| AC5 G5 | Two real cron executions of one job (`_execute_job_now`, the `hermes cron run` path, external worker process). Run 1 records 2 URLs and writes the journal. Run 2's prompt contains the journal; `check_alerted` returns the `www.`/trailing-slash/`utm_` variant as already alerted, and only the new URL as new; `journal_get` returns run 1's text. Ledger 0600, hashes only. Removal deletes the ledger. Cron toolsets have no memory, session_search, todo, clarify or cronjob | `test_g5_01`–`05` (image), `test_hook_10/13`, `test_led_*` (unit) | VERIFIED |
| AC6 G6 | Existing suite green apart from deliberate alignments; scout_mail and Kandidat tests green; `scout-mail` and per-platform `toolsets` checks pass for Scout, Kaféine and Nora on the image with hermes-31's `tool_search: off`; check-mode diff limited to the intended changes | Final counts above; `test_ac6_01`; E3 below | VERIFIED |
| AC7 restart | Fresh process: 5 jobs read back; nothing due; a real `tick()` fires nothing. A slot missed by more than the 2 h grace while down → exactly 1 run over two real ticks, then `next_run_at` moves to the next slot | `test_ac7_01` (image). An in-flight run killed by a restart is lost, not repeated (Hermes at-most-once, README « Cron safety ») | VERIFIED |
| AC8 runbook | Enable, owner Telegram test, operator inspect/pause/remove, rollback, limits | `docs/guides/runbook-scout-cron.md`; role README section rewritten | VERIFIED |

Design §7 open points (requirement b):

| # | Point | Result |
|---|---|---|
| 1 | Plugin `check_fn` / tool-definition cache vs cron context | Not applicable: the plugin tool has no `check_fn`. Exposure is decided by the platform lists (verified per platform and profile) and the handler checks its context |
| 2 | `post_message` from `pre_tool_call`, before the card | VERIFIED: event order post…post, card (`test_g2_01/02`). The gateway runner and Telegram adapter are faked behind Hermes' real `plugin_messages` routing |
| 3 | Per-profile timezone under the multiplexed ticker | VERIFIED: `_profile_cron_scope`, multiplex mode on, decoy `HERMES_TIMEZONE=Asia/Tokyo` ignored; Scout `07:00-04:00`, Kaféine `07:00+00:00` (`test_tz_01`). Plugin next runs equal Hermes' `next_run_at` for 10 expressions (`test_tz_02`) |
| 4 | `pre_tool_call` in cron runs | VERIFIED: cron runs execute in Hermes' external worker process, where scout_cron's hooks load and see the execution identity; the run caps fire (`test_g3_05`) |
| 5 | `/approve` from a non-allowlisted user | Code evidence only: Telegram buttons go through `_claim_callback_state` → `_callback_authorized` → the gateway's user authorization (`plugins/platforms/telegram/adapter.py:4700-4790`, `:839`); text `/approve` comes from gateway messages, which are dropped for unauthorized users. Not lab-tested; owner test 7 covers the owner side |

None failed, so nothing was widened.

## Check mode (E3)

Command (from `hermes/`, worktree venv): `ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes --check --diff`. Result: `ok=84 changed=5 unreachable=0 failed=0 skipped=58`.

Changed in check mode:
1. `Replace the predecessor SOUL.md with the delivered one` (job-search): live `7dc753fe…` recognised as a predecessor. Diff `@@ -134,14 +134,27 @@`: the « Tâches planifiées » section and « Tes limites ».
2. `Create the scout_cron plugin directories`.
3. `Deploy the scout_cron plugin code`: 7 files.
4. `Deploy the scout_cron settings`: new `settings.json` = `enabled: true`, `profile: job-search`, the allowlisted owner id (already public in group_vars), `display_timezone: America/Guadeloupe`, `limits: {}`.
5. `Persist a pending gateway restart for scout_cron`: `done` → `pending`.

Expected but not shown in check mode, existing role behaviour: the profile config reads and `config set` are skipped. The real run will set `plugins.enabled`, `timezone`, the four `platform_toolsets.*`, `known_plugin_toolsets.*` and `agent.disabled_toolsets` for job-search, then restart the multiplexed gateway once.

The scout_mail and scout_cron switch assertions passed. No change for default (Nora) or cafe-ia (Kaféine).

## Enforcement matrix

| Guard | Code or prompt | Where | Test |
|---|---|---|---|
| G1 platform/profile/owner chat | code | config lists, Hermes cron denylist, plugin `_common_gate`, handler context | g1_*, hook_02/03, decl_01/02 |
| G1 a run never schedules | code | Hermes (`cron.allow_agent_scheduling` false) + plugin | g1_05, hook_03 |
| G2 approval with exact text | code | plugin proposal + Hermes approval gate, single-use key, bypass refusal | g2_*, hook_01/04 |
| G2 summary before calling, list first, update in place | prompt (SOUL); duplicate-name refusal is code | SOUL « Tâches planifiées », policy | g3_04, pol_06 |
| G3 limits, fields, delivery, run refusal | code | policy | g3_*, pol_* |
| G3 per-run cost cap | code | plugin pre_tool_call in cron | g3_05, hook_08 |
| G4 tainted session | code | scout_mail veto, plugin pre-check | g4_01, hook_04 |
| G5 record read at start | code | Hermes notepad injection | g5_01 |
| G5 record written, dedup used | prompt (job instructions, SOUL, tool description); tool and storage are code | scout_task_record | g5_01 (mechanism) |
| G5 no widening, no Kandidat writes in cron | code | cron list, mcp_policy unchanged | g5_03, decl_01 |
| Next run in Guadeloupe time | code computes the values, prompt phrases them | transform_tool_result | g2_02/07, hook_12 |
| French output | prompt | SOUL | owner test |

## Deviations, risks and limitations

Deviations from design.md:
- The other-hooks veto check calls the other plugins' callbacks directly, not through Hermes' aggregator. The aggregator, re-entered from inside a `pre_tool_call` callback, skips the still-running callback and turns the skip into a block (observed on the image).
- The check mode is named `scout-schedule`, not `scout-cron`: `test_t17` forbids the token `cron` in role commands.
- `tasks/profile.yml` (non-multiplexed path, frozen since M4 by `test_n08`) is unchanged. Only `profile_multiplex.yml`, which hermes-31 uses, passes per-platform allowlists. A non-multiplexed deployment of this Scout declaration would fail its `toolsets` check.
- SOUL growth: +1,207 characters, about 300 tokens per model call. The cron-run details went into the `scout_task_record` tool description instead. The `test_b03` cap was raised from 14,300 to 15,500.
- The `toolsets` check now sets `HERMES_GATEWAY_SESSION=1` for every profile, the gateway's view. Kaféine and Nora still pass on the image.

Existing tests updated deliberately, each annotated « SCOUT-CRON » in the code:
- `test_m4_scout.py`: `m4_era()` undoes the SCOUT-CRON keys; `test_s04` and `test_s06`;
- `test_m331_web_tools.py::test_w01`;
- `test_kscout01_compact_lookup.py::test_c01`;
- `test_m7_kafeine.py::test_i05`;
- `test_scout04_search_budget.py::test_b01`, `test_b03`;
- `test_scout_mail_role.py::test_role_04`;
- `test_m63_multiplex.py`: lab passes the role's per-platform JSON; Scout's telegram expects `cronjob_manage`; the shared-task test admits exactly the per-platform argument in the multiplexed toolsets task.

Residual risks (stated, not solved):
- A page fetched during an approved run can steer that run. It is bounded:
  - read-only tools apart from the journal and the ledger;
  - 40 calls and 20 web calls;
  - delivery to the owner only.

  Search queries or fetched URLs can still carry the private context (`agent.environment_hint`). That was already true of any Scout session with web tools; scheduling makes it unattended and recurring.
- A run can write steering text into its own journal (at most 3,000 characters, read by that job only). It is visible with `/taches-scout` and deleted with the job.
- A taint that appears while an approval card is pending is not re-checked before execution. This is a limit of scout_mail's per-call veto, and the window is the approval wait.
- The cron worker process takes `HERMES_TIMEZONE` from the gateway environment, i.e. the default profile's `timezone` (unset today). Keep Nora's `timezone` unset or equal to Scout's (runbook §9).
- The plugin depends on v0.22.5 internals (`hermes_port.py`). Any image upgrade must re-run `test_scout_cron_image.py`.
- `/approve` by a stranger was not lab-tested (code evidence only).
- `deploy.yml` has no `schedule-window` gate. Once Scout has jobs, the operator must run the read-only check (runbook §3) before any deploy or restart.

## Repository and infrastructure state

- Branch `feat/scout-self-cron`, pushed; commits 8ea5783, 3f22db6, 20e4e70, 5cff2b9, 5a1fb5a, plus the report commit. Working tree clean after the report commit.
- Draft MR !111 opened, not merged; `force_remove_source_branch` set to false.
- hermes-31: read-only commands and one check-mode playbook run. No file written, no restart, no job created.
- `owner-request.local.md` stays local (excluded by `.git/info/exclude`); its criteria are absent from every committed file (grep on all added lines).
- Local leftover: a detached git worktree of 975e302 at the session scratchpad `basewt` (used for the baseline run). Removal (`git worktree remove`) is pending the owner's OK, per the safe-delete rule.

## Decisions required

- D-DEPLOY: deploy or not. Options:
  - (a) after review, run check mode again, then deploy (one multiplexed restart), then a second run with `changed=0`;
  - (b) wait.

  Not blocked technically. Owner decision.
- D-D9: the owner may override D9, which narrows Scout's cron toolsets. Reverting it adds `memory`, `session_search`, `todo`, `clarify` back to `platform_toolsets.cron`. That restores unapproved memory writes and private-transcript search in unattended runs. Recommendation: keep D9.

## Follow-ups for the owner

- Requirement (c), out of scope and unchanged: Scout's Telegram, api_server and cli sessions write memory (`MEMORY.md`/`USER.md`, injected into every Scout session) without approval. Scout has no `memory.write_approval`, while Nora does. Proposed follow-up: `memory.write_approval: true` in Scout's declaration, a separate mission.

## Owner tests in Telegram after deployment

1. `/new`, then send the private request text (`owner-request.local.md`). Expected:
   - Scout lists tasks, then summarises;
   - a « 📋 Scout — proposition de tâche planifiée : créer … » message carries the full text, in 2 messages if over 3,500 characters;
   - then the approval card;
   - after « once », Scout confirms, the task is active, and the next run is given in Guadeloupe time (weekday 07:00).
2. `/taches-scout`: 1 / 5, active, next run.
3. Send the same request again: an update of the same task (card), never a second task.
4. Ask for every 30 minutes, or delivery to another account: refused, with no card.
5. Ask for something, then deny or let it time out: nothing saved.
6. After the first weekday run: the alert comes from Scout's bot; `/taches-scout <nom>` shows a journal and an alerted count.
7. Feedback through Scout: a card with the text, then it appears under « Retours ».

## Rollback

Runbook §7:
1. Pause or remove Scout's jobs.
2. In one commit: `hermes_scout_cron_enabled: false`, remove `scout_cron` from `plugins.enabled`, put `cronjob` back into Scout's deny list. The role refuses an inconsistent set.
3. Run check mode, then deploy.

To revert the whole MR instead, mind three things:
- the SOUL (the reverted SOUL is not re-seeded automatically);
- removing `timezone`, which shifts the wall-clock time of any remaining job by 4 h;
- the plugin files, which stay on disk, inert.

## Recommended next action

Codex review of MR !111, brief by the pilot. Then the owner's deployment decision (D-DEPLOY) and the owner Telegram tests above. Nothing is safe to execute on hermes-31 without that decision.
