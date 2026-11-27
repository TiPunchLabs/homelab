# Report — homelab/2026-11-24-scout-self-cron (SCOUT-CRON)

Verdict: PARTIAL (cycle 5b: review-5.md, PASS_WITH_RESERVATIONS on 4181f66, minor F10 and F11 fixed, see « Answers to review 5 »; every test reading SOUL.md passes, the full suite was again stopped by low memory and is not verified; cycle 5: review-4.md, CHANGES_REQUESTED on e8ae092, F8/F9 fixed structurally, see « Answers to review 4 »; unit, role and image tests pass, the full suite was stopped by low memory and must be re-run; cycle 4: review-3.md, CHANGES_REQUESTED on 4e8e279, F8 fixed, see « Answers to review 3 »; cycle 2: review-2-claude.md, CHANGES_REQUESTED on 392e02d, F6 and F7 fixed, see « Answers to review 2 »; cycle 1: review-1.md on 5a1fb5a, F1–F5 fixed, see « Answers to review 1 »)
Version: 5d9f0a0 (branch `feat/scout-self-cron`, pushed; cycle 0: 8ea5783 plugin, 3f22db6 role/config/SOUL/checks, 20e4e70 tests, 5cff2b9 docs, 5a1fb5a test alignment; cycle 1: 659c8a2 fix, 975fa5b tests, 392e02d docs; cycle 2: 1d6dc94 fix, 7e39898 tests, 4e8e279 docs; cycle 4: e8ae092 fix, tests and docs; cycle 5: 4181f66 structural fix, tests and docs; cycle 5b: 5d9f0a0 SOUL compaction; this report is committed on top and changes nothing else)
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
- Cycle 1 (Codex review 1): the owner's approval is now bound to one tool call, one job version and one set of arguments, and re-checked at the real save. To do that, scout_cron replaces `cronjob_manage` in Scout's profile only; this needs the operator grant `tools.override`. Create reservations belong to their own call, and the job count is checked again at the save. Every explicit value Hermes would store or clear is refused. Resume is refused over the cap. Every proposal shows the full effective task. Each finding has regression tests that fail on 5a1fb5a, including interleavings against real Hermes.

## Answers to review 5

Review `review-5.md` (Codex, PASS_WITH_RESERVATIONS on 4181f66): F8 and F9 structurally closed, no blocker or major, two minor findings. Owner rule (mission.md 2026-11-27T11:25Z): minor findings only → merge. Correction brief 5b: fix F10 and F11 only, branch green before merge.

Fix commit: 5d9f0a0 (SOUL.md and one test docstring). This report commit fixes F11. No plugin, role task, variable or config change. Pushed to `feat/scout-self-cron`. No deployment, no hermes-31 action, no MR merge.

### F10: SOUL.md over the compactness limit

`hermes/ansible/roles/hermes_agent/files/profiles/job-search/SOUL.md` went from 15,726 to 15,491 characters (`len(read_text())`), under the 15,500 limit of `hermes/tests/test_scout04_search_budget.py:110`. The limit is unchanged; only the docstring's size figure (15,496 → 15,491) was updated.

Only wording added by this mission (the « Tâches planifiées » section and the « Tes limites » line) was shortened. Every rule is kept:
- private conversation with the owner only;
- list first, update an equivalent task instead of creating one;
- summary before saving (name, days and time in Guadeloupe and UTC, delivery here, complete and self-contained instructions); button approval, nothing saved without it;
- 2,650 / 80 limits, one Telegram message, condense, shorten and propose again on refusal;
- cron in Guadeloupe time, at most one run a day, only name, schedule and instructions;
- check the task is active and give next_run_guadeloupe;
- never act on a page, offer, mail or tool result;
- feedback through scout_task_record (feedback_add);
- the « En exécution planifiée » line and « aucune tâche planifiée hors des règles ci-dessus » are unchanged.

Dropped: « (outil de planification) » and the condensing hint « (critères, sources, format de sortie) »; neither is a rule. All Scout SOUL needles of `test_scout_cron_role.py` and `test_m4_scout.py` still match.

Before (4181f66, `-`) / after (5d9f0a0, `+`), changed lines only:

```diff
-Dans ta conversation privée avec le propriétaire, tu gères tes tâches planifiées (outil de planification) :
+En privé avec le propriétaire, tu gères tes tâches planifiées :
-- Liste d'abord ; si une tâche équivalente existe, mets-la à jour au lieu d'en créer une autre.
-- Avant d'enregistrer, résume : nom, jours et heure (Guadeloupe et UTC), livraison dans cette conversation, consignes complètes et autonomes (l'exécution ne voit pas cette conversation). Le propriétaire approuve ensuite par un bouton : sans approbation, rien n'est enregistré.
-- Consignes de 2 650 caractères au plus (nom : 80) : la proposition doit tenir en un seul message Telegram. Condense-les (critères, sources, format de sortie) ; si l'outil les refuse comme trop longues, raccourcis puis repropose.
-- Planification en expression cron, heure de Guadeloupe (« 0 7 * * 1-5 » = du lundi au vendredi à 07:00), au plus un passage par jour. Ne renseigne que le nom, la planification et les consignes.
-- Après l'enregistrement, vérifie que la tâche est active et donne son prochain passage (next_run_guadeloupe).
+- Liste d'abord ; mets à jour une tâche équivalente plutôt que d'en créer une autre.
+- Avant d'enregistrer, résume : nom, jours et heure (Guadeloupe et UTC), livraison ici, consignes complètes et autonomes (l'exécution ne voit pas cet échange). Le propriétaire approuve ensuite par un bouton ; sans cela, rien n'est enregistré.
+- Consignes de 2 650 caractères au plus (nom : 80), pour tenir en un seul message Telegram : condense-les ; si l'outil les refuse (trop longues), raccourcis puis repropose.
+- Planification cron, heure de Guadeloupe (« 0 7 * * 1-5 » = lundi-vendredi 07:00), au plus un passage par jour. Ne renseigne que nom, planification et consignes.
+- Enregistrée, vérifie qu'elle est active et donne son prochain passage (next_run_guadeloupe).
-- Un retour du propriétaire sur une tâche s'enregistre avec scout_task_record (feedback_add).
+- Retour du propriétaire sur une tâche : scout_task_record (feedback_add).
-Tu disposes de la recherche et de la lecture Web, de ta mémoire, de tes skills, de la recherche dans tes conversations passées, d'une liste de tâches, des seuls outils Kandidat décrits plus haut et de la gestion de tes tâches planifiées selon les règles ci-dessus. Rien d'autre :
+Tu disposes de la recherche et de la lecture Web, de ta mémoire, de tes skills, de la recherche dans tes conversations passées, d'une liste de tâches, des seuls outils Kandidat décrits plus haut et de tes tâches planifiées (règles ci-dessus). Rien d'autre :
```

### F11: stale report text

Updated in this report:
- « Owner tests in Telegram after deployment », test 1: Scout condenses the instructions to 2,650 at most; the proposal is one message, never split; instructions over the limit are refused with a French « raccourcir » message and no card. It used to say 2 messages above 3,500 characters.
- « Recommended next action »: now names review 5, this version and the merge rule. It used to name a re-review at 4e8e279.
- Same stale text fixed in « Design as implemented (summary) »: G2 (one checked message instead of a split below 3,500) and G3 (2,650 / 80 displayed, 40-character expression, instead of 6,000).

Older « Answers to review N » sections are kept as history of each cycle.

### Tests on 5d9f0a0

Memory before the runs: 10 GB available (`free -g`), so the full suite was run, niced.

- Targeted, `nice -n 10 uv run --no-sync pytest` on every test file reading SOUL.md plus the cron files: `test_scout04_search_budget.py`, `test_scout_cron.py`, `test_scout_cron_role.py`, `test_m4_scout.py`, `test_m7_kafeine.py`, `test_scout03_kandidat.py`, `test_kscout01_compact_lookup.py`, `test_role_tasks.py`, `test_m63_multiplex.py`, `test_m5_recovery.py`, `test_m1_operations.py`, `test_m2_cafe_ia.py`, `test_hermes_checks.py`, `test_m5_nora.py`: 863 passed, 17 skipped, 2,098.69 s, exit 0. Run on the working tree identical to 5d9f0a0's `hermes/`.
- Full suite: started 12:59:53 AST on 5d9f0a0 (`nice -n 10 uv run --no-sync pytest hermes/tests -q -p no:cacheprovider -rf`) with 10 GB available, then stopped by Claude Code about 5 minutes in because the laptop ran critically low on memory (other local containers: litellm, open-webui, localstack, portainer, mailpit, postgres). No result was printed; not restarted, per the stop notice. NOT_VERIFIED.
- Coverage argument, not a substitute: review 5's full run on 4181f66 had 1 failed (F10, this compactness test), 1,195 passed, 27 skipped. 5d9f0a0 changes only SOUL.md and a docstring, and every test file that reads SOUL.md passed above.

## Answers to review 4

Review `review-4.md` (Codex, CHANGES_REQUESTED on e8ae092):
- F8 is not closed;
- F9 [major]: splitting creates a task list across two lines (`-\n[ ] ...`); Hermes' whole-message rich detector matches it, while the line checks miss it.

The owner approved a 5th cycle with a structural fix (mission.md, 2026-11-27T05:50Z), following `correction-brief-5.md`.

Fix commit: 4181f66. It changes:
- plugin, tests and lab;
- Scout's SOUL;
- runbook, role README, design.md and the role defaults comment.

No role task or configuration change. Pushed to `feat/scout-self-cron`. No deployment, no hermes-31 action, no MR merge.

### Structural fix: one message, never split, checked whole

The splitter is removed: `split_for_telegram`, the chunk numbering and the per-chunk loop are gone. Every post the plugin makes is one Telegram message.

Proposals (create, update, remove, resume, feedback):
- `_confirm` calls `policy.check_post` on the complete proposal, then posts it once.
- On `UnsafePost` nothing is posted: the binding and any reservation are dropped, and the call is refused before the approval card, with a French reason:
  - `MSG_LONG_POST` for size (shorten the instructions or the name);
  - `MSG_UNSAFE_POST` for a shape (table, task list, `<details>`, `$$`, ```` ``` ```` line).

`check_post` (policy.py) runs on the final, complete post:
- line checks, as before, also on `str.splitlines()` parts;
- Hermes' whole-message predicates on the whole string, copied verbatim with citations, through `hermes_rich()`. From Hermes v0.22.5 `TelegramAdapter._needs_rich_rendering`:
  - adapter.py:1340: `TABLE_SEPARATOR_RE`, from gateway/platforms/helpers.py:285, on every `content.splitlines()` line. The same regex drives `convert_table_to_bullets` (helpers.py:322), the table pass of `format_message`;
  - adapter.py:1342: `(?m)^\s*[-*]\s+\[[ xX]\]\s+` on the whole text. Its `\s+` crosses newlines, which is F9;
  - adapter.py:1344: `<details>`/`<summary>`;
  - adapter.py:1346: `$$`.
  Any match leads to a refusal.
- Hermes' fence pass, adapter.py:5683, applied to the whole post. It must find exactly the plugin's code blocks:
  - opened by a bare ```` ``` ```` with no lead-in prose and no language;
  - with the same bodies;
  - with no ```` ``` ```` left outside them.
- No `\r`, and no NUL: Hermes' placeholders are `\x00PH<n>\x00`, restored with `str.replace` (adapter.py:5648, 5727).
- Size: the rendered MarkdownV2 length in UTF-16 units must stay within `POST_BUDGET` = 4,000.
  - Hermes splits only above 4,096: `_send_text_locked` → `truncate_message(format_message(content), 4096, len_fn=utf16_len)`, adapter.py:3693. That leaves 96 units of margin.
  - `_cost` is an upper bound. Inside a code block, only `\` and `` ` `` are escaped (adapter.py:5679). Outside, `_escape_mdv2` escapes each special character at most once (adapter.py:378, 5724), and the other conversions only shorten.
  - The image lab checks this bound against the real formatter.

Other posts:
- Pause notice: if the stored name or reason does not fit, a short notice with the id only is posted.
- `/taches-scout <task>`:
  1. full view;
  2. else the same view without the journal and feedback bodies (sizes only);
  3. else a fixed line.
- Feedback proposal: the job's full instructions when the whole post fits one message; otherwise their size and fingerprint, marked « inchangées ». F5 named create, update, delete and resume; the cycle-1 test also covers feedback with short instructions, and passes.
- Update proposal: each name is shown once, the current one in the header (« Nom actuel ») and the new one in the recap (« Nouveau nom »). It used to be shown twice each. The F5 content is unchanged: changed and unchanged fields, the full effective instructions, schedule and delivery.

New text is refused earlier, in policy (`unsafe_shapes` now includes `hermes_rich`):
- create and update: name and instructions;
- feedback.

### The limit, derived from the worst case

Measure: instructions, name and feedback are now measured as displayed in a Telegram code block (`policy.display_size`):
- UTF-16 units: an emoji counts 2;
- plus `\` and `` ` `` counted twice, because Hermes escapes them inside the block.

For ordinary text this equals `len()`. Counting raw characters could not bound the worst case: 2,650 backslashes or emoji render as 5,300 units.

Worst-case inputs, all at the new upper bounds:
- names of 80 displayed units (`\` ×40, `` `\ `` ×20, 😀 ×40);
- schedule expressions of the new maximum, 40 characters, dense in escaped characters (`59 23 1-2,4-5,7-8,10-11,13-14,16-17 * *` and variants);
- instructions made of `\`, 😀, `x`, or mixed lines;
- each of the 7 weekdays as the start day, for the longest French day names in the « Prochains passages » lines;
- paused or not.

Actions:
- create;
- update changing name, schedule and instructions: current name, new name, before/after line and full recap;
- remove, with the full stored instructions;
- resume;
- feedback, with full-size stored instructions.

Derivation script `docs/missions/2026-11-24-scout-self-cron/derive-limits.py`, run from the worktree with `uv run --no-sync python`, binary search on the instruction size:
- Instructions: worst post at 2,681 = 4,000 units, from an update. At 2,682 it is 4,001.
- Feedback (instructions shown as size and fingerprint): worst post at 3,078 = 4,000 units. At 3,079 it is 4,001.

Chosen values (config.py):

| Limit | Default | Upper bound | Before |
|---|---|---|---|
| `max_prompt_chars` | 2,650 | 2,650 | default 6,000, bound 8,000 |
| `max_name_chars` | 80 | 80 | bound 120 |
| `feedback_chars` | 1,500 | 3,000 | bound 4,000 |
| schedule expression (`MAX_EXPR_CHARS`, code) | 40 | — | not capped |

2,650 is 31 below the derived 2,681. That gives slack beyond the 96-unit margin.

Refusal for instructions over the limit, in French: « les instructions font N caractères une fois affichées dans Telegram, maximum 2650 pour que la proposition tienne en un seul message : les raccourcir (résumer, retirer les répétitions) puis reproposer ».

Consequence for the owner:
- design.md notes that the owner's real request is about 3.4 k characters of conversation.
- Scout must now condense the saved instructions to 2,650 at most. Scout's SOUL now states this in French: « Consignes de 2 650 caractères au plus (nom : 80) … tenir en un seul message Telegram … si l'outil les refuse comme trop longues, raccourcis puis repropose ».
- Operator-made jobs above the limits, or with out-of-policy stored values, still fail closed: their proposals are refused when they do not fit, as before for every non-conforming field.

### Tests

Unit tests (`test_scout_cron.py`):
- `test_r3_f8_review_reproduction_now_fails_closed`: the review-3 F8 prompt (3,504) and the review-4 F9 prompt (3,506) are refused, with « maximum 2650 » and « raccourcir ». No post, no binding, nothing saved.
- `test_r3_f8_a_fence_or_rich_tail_inside_a_line_is_one_verbatim_message` (6 tails, up to the largest accepted size): exactly one message. The test-side oracle accepts it; this oracle includes Hermes' whole-message predicates, retyped. The hidden line appears only inside the code block.
- `test_r4_f9_cross_line_task_lists_are_refused_before_anything_is_posted` (6 forms: `-\n[ ] x`, `*\n[X] x`, whitespace across the checkbox boundary, the F9 hidden text): blocked for create and for feedback, with no post and no binding. `hermes_rich` reports « liste de cases à cocher ».
- `test_r4_check_post_applies_hermes_whole_message_predicates`: 10 unsafe whole posts are refused:
  - cross-line task list;
  - table on a U+2028 line;
  - `<details>`;
  - `$$`;
  - inner fence line;
  - unclosed fence;
  - lead-in opener;
  - language opener;
  - NUL placeholder;
  - CR.

  Oversize carries `size`.
- `test_r4_worst_case_accepted_proposal_is_one_message`: the derivation above as a test. Every case is one message with `rendered ≤ 4,000`, and the worst is above 3,900. Through the plugin: an update at the bounds, and feedback at 3,000 with full-size instructions (shown as size and fingerprint), each one post.
- `test_r4_limit_plus_one_is_refused_with_a_french_message`: displayed 2,651 is refused (`x`, emoji, backslash variants) and 2,650 is accepted. A name of 82 displayed is refused, and so is an expression over 40. Settings 2,651 / 81 / 3,001 are rejected.
- `test_r4_notice_and_command_stay_one_message_when_stored_text_is_too_long`.
- Removed: `test_pol_11` and the review-3 cut-position sweep, both tests of the removed splitter.
- Updated:
  - `pol_01`, `pol_03` and `r1_f4` for the new limit;
  - `r2_f6_feedback_and_long_text` (now one message);
  - `r2_f6_command_output` (compact view instead of truncation).

Image lab, Hermes v0.22.5 real formatter and detector:
- `test_r3_01`: the F8 and F9 reproductions, and the short F9 form, go through the real agent and approval flow. All are refused before anything is posted (`order == []`), and nothing is saved.
- `test_r4_01`: the largest accepted proposal (name `\` ×40, instructions `\` ×1,325) is exactly `post, card`. It is not rich, has no unescaped MarkdownV2 special outside code, keeps the instructions intact in the pre block, and the real formatted length is between 3,000 and 4,000 UTF-16 units.
- `test_r4_02`: parity on 1,222 posts:
  - the F8/F9 shapes and a seeded fuzz of 600 strings over `- * [ ] x X | : <details> </summary> $ ` \ U+2028 \f # > ~ _ ( ) 😀 é`;
  - each string both fenced as Scout's text and raw.

  The plugin's `hermes_rich` equals the real `_needs_rich_rendering` on every post. On every accepted post, the real `format_message` UTF-16 length is ≤ the plugin's bound, which is ≤ 4,000. Accepted fenced posts have no unescaped special character.
- `test_g2_01`, `test_g2_02` and `test_r2_03` now require exactly one proposal post. The lab's owner prompt is now about 2,500 characters (was about 4,580).
- The lab prints its JSON result in ASCII, because the corpus holds U+2028 and form feeds that broke stdout line splitting.

Proof on e8ae092:
- Unit: export of e8ae092 `hermes/` plus the new `test_scout_cron.py`, `-k "r3_ or r4_"`: 17 failed, 6 passed.
  - The 6 that pass are the U+2028-family separator tests, fixed in cycle 4.
  - 11 fail because the old code approves instead of refusing: the F8/F9 reproductions and the 6 F9 forms, plus the check_post, worst-case, limit and notice tests.
  - 6 (the tail tests) fail on the missing `display_size` helper. They test the new one-message guarantee, not the old bug.
- Image: old plugin with the new lab (in a scratch copy only, the parity step tolerates the missing helpers), `-k "r3_01 or r4_0 or g2_01 or g2_02 or r2_03"`: 12 of 12 failed.
  - In both labs the old plugin approves F9 and splits it into 3 messages. The third starts with the `-` / `[ ] ||hidden|| …` task list, which the real detector routes to the rich path.
  - Proposals take several posts.
  - `r4_02` cannot run there: `hermes_rich` is missing.

Results on 4181f66:
- unit + role: 201 passed;
- image: 122 passed (61 × 2 labs), 269.57 s;
- full suite: NOT COMPLETED. `nice -n 10 uv run --no-sync pytest hermes/tests -q -p no:cacheprovider -rf`, started 07:44:05 AST, was stopped by Claude Code at about 30 % of the run because the laptop was critically low on memory (about 6 GiB available, with unrelated containers running: litellm, open-webui, localstack and others). No failure appeared before the stop; no Hermes lab container was left behind. It was not restarted, per the stop notice. It must be re-run by the owner, or on request, before review 5 counts on it.

### Limits and reservations

- How the Telegram client renders the post is still an owner test. The lab proves what Hermes sends: one MarkdownV2 message, never the rich path.
- The copied predicates must be re-checked on any Hermes upgrade; `test_r4_02` does that on the pinned image.
- New refusal cases:
  - instructions over 2,650 as displayed;
  - names over 80 as displayed;
  - expressions over 40;
  - and any stored job whose proposal does not fit one message (operator-made or out-of-policy values).
- Review 3 and 4 reservations stand: the plugin-wide `tools.override`, the other-process write race, the pinned-image dependency, and the earlier owner follow-ups.
## Answers to review 3

Review `review-3.md` (Codex, CHANGES_REQUESTED on 4e8e279). It confirms F7 and F1–F5 fixed and raises F8 [major]. The owner approved a 4th cycle limited to F8 (mission.md, 2026-11-27T01:35Z). Fix commit: e8ae092 (plugin, tests, runbook G2 row, role README; nothing else). No role task, variable or config change. Not pushed.

### F8: splitting must not create a fence or another unsafe line

Root cause, confirmed in the v0.22.5 image (`plugins/platforms/telegram/adapter.py`):
- `format_message` closes a fenced block at the first line matching `^[ \t]*```[ \t]*\r?$` (any indent, only backticks).
- `unsafe_shapes` refused ``` only at the start of an input line, so `"a" * 3458 + "```"` was accepted. `split_for_telegram` cut that line to fit one message. The remainder, ```` ``` ````, became a whole line right after the reopened fence, so Hermes closed the block there, and the spoiler and link that followed were rendered as MarkdownV2.
- The same cut can create other unsafe lines: an indented fence, a table separator (rich path; on 4e8e279 a remainder `-|---|` also matched), a task-list item or `<details>`.
- Found while checking Hermes' rich detector for this fix: `_needs_rich_rendering` checks table separators on `content.splitlines()`, which also splits on U+2028, U+2029, `\x0b`, `\x0c`, `\x1c`–`\x1e` and `\x85`. Verified in the image: `_needs_rich_rendering("```\naaa |---|---|\n```")` is True. Plugin checks split on `\n` only, so such text was accepted and sent on the rich path. The final-post check below now catches it.

Fix (`policy.py`, `__init__.py`):
- `split_for_telegram` never cuts where the head piece or the remainder would itself be an unsafe line (`_unsafe_line`: fence, table separator, task list, `<details>`/`<summary>`); it moves the cut earlier instead.
- `check_post()` checks every final message, after numbering:
  - fences are only the plugin's own ```` ``` ```` lines, and they are balanced;
  - no other line is unsafe, also when cut as Hermes' `splitlines()` would cut it;
  - no `$$`, no CR;
  - rendered size within 4,096.
  `split_for_telegram` raises `UnsafePost` if any message fails, so no message is returned.
- `_confirm` splits the whole proposal before the first post. On `UnsafePost`, nothing is posted, the binding and any reservation are dropped, and the call is refused before the approval card with `MSG_UNSAFE_POST` (asks Scout to reformulate). This covers create, update, resume, remove and feedback, which all go through `_confirm`.
- Pause notice: if the stored name or reason cannot be split safely, a short notice with the job id only is posted. The pause still needs no approval.
- `/taches-scout`: if the list cannot be split safely, it returns a fixed refusal line and logs a warning.
- Not done: refusing every ``` run in new text (the review's optional extra defence). Accepted text is now shown verbatim or refused, so it was not needed.

Tests added (all fail on 4e8e279, all pass on e8ae092):
- Unit, `test_scout_cron.py` (14 cases). They use a test-side oracle `assert_post_safe`, independent of `policy.check_post`:
  - `test_r3_f8_review_reproduction_is_shown_verbatim_and_saved_exactly`: the review's prompt (3,458 `a` + ``` + `||hidden|| [link](https://example.invalid)`). It is approved and posted in at least 2 messages, each one safe. The hidden line appears only inside fences, the cut pieces rejoin to the original line, and the saved prompt equals the input.
  - `test_r3_f8_a_cut_at_any_position_never_makes_an_unsafe_piece` (5 tails: ```` ``` ````, indented ```` ``` ````, `|---|---|`, `- [ ] x`, `<details>`): every length 1–399 with a 120-unit limit. This puts the 1st to 4th piece boundary at every offset around the tail (2 to 5 messages seen). Each message is safe and the pieces rejoin to the line.
  - `test_r3_f8_unsafe_final_post_refused_before_any_post_or_approval`: `"a" + "`" * 3400` (every cut leaves a piece starting with ```). Result: block, no post, no binding, dispatch refused, nothing saved.
  - `test_r3_f8_line_separators_that_hermes_splits_on_are_refused_before_posting` (6 separators): blocked before posting.
  - `test_r3_f8_notice_and_command_fall_back_when_stored_text_cannot_be_split_safely`.
- Proof on 4e8e279 (export of 4e8e279 `hermes/` plus the new test file): `-k r3_` gives 14 failed. Every failure is behavioural (fence left open, unsafe piece `<details>` / `-|---|`, `approve` instead of `block`), not a missing helper.
- Image lab, Hermes' real `format_message` and `_needs_rich_rendering` (`image_lab.py`):
  - new turn `md_split`: the review's exact prompt through the real agent, plugin and approval flow (denied, nothing saved);
  - new `split_sweep`: the plugin's own splitter (limit 120) on each of the 5 tails for lengths 1–259, every message rendered by the real formatter.
  - `test_r3_01`: the posts are not rich and have no unescaped MarkdownV2 special character outside code (`mdv2_parts`). The hidden line is inside a pre block, and the line rejoins.
  - `test_r3_02`: the same checks for every sweep case, with 2, 3 and 4 messages covered.
  - The existing `test_r2_03` now also covers the `md_split` posts.
- Proof on 4e8e279's plugin with the new lab: `-k "r3_ or r2_03"` gives 6 failed, 114 deselected. In both labs `test_r2_03`, `test_r3_01` and `test_r3_02` fail, each with bare `|`, `[`, `]`… outside code. That is the review's spoiler and link leaking.

Results on e8ae092:
- unit + role: 193 passed (179 + 14).
- image: 120 passed (116 + 2 tests × 2 labs), 263.87 s.
- full suite: `uv run --no-sync pytest hermes/tests -q -p no:cacheprovider -rf`, 21:44:04 to 23:52:51 AST (7726.36 s): 1 failed, 1185 passed, 27 skipped, nothing deselected (1,213 collected = 1,195 + 18 new). The failure is the pre-existing date-sensitive `test_scout03_kandidat.py::test_l06_create_candidature_side_effects` (`'2026-11-27' == '2026-11-26'`; it fails on any commit when run between 20:00 and midnight AST). Review 3's own run of 4e8e279 passed it in daytime.

Limits and reservations (unchanged unless stated):
- How Telegram's own app renders the posts is still an owner test. The lab proves what Hermes sends, not what the client draws.
- A Scout proposal whose instructions can only be split unsafely is now refused, and Scout has to reformulate. This is a new, deliberate refusal case.
- Every reservation from review 3 stands: the plugin-wide `tools.override` grant, the concurrency window against another writer process, and the earlier owner follow-ups.

## Answers to review 2

Review `review-2-claude.md` (Claude fallback reviewer, owner-approved; CHANGES_REQUESTED on 392e02d). It confirms F1–F5 fixed and raises F6 [major] and F7 [minor]. Fix commits: 1d6dc94 (plugin only), 7e39898 (tests), 4e8e279 (runbook, role README). No role task, variable or config change in this cycle.

### F6: the owner must read exactly what is saved

Root cause, from Hermes v0.22.5 `plugins/platforms/telegram/adapter.py`:
- `send()` → `_send_text_locked` renders every post with `format_message` (Markdown → MarkdownV2).
- When the raw text has a table separator line, a task-list item, a `<details>`/`<summary>` line or `$$`, `send()` instead takes the rich path (`_needs_rich_rendering` → `sendRichMessage`): Telegram renders the raw Markdown server-side.
- `format_message` converts `||…||` into a spoiler, `[text](url)` into a link (URL hidden), `**>` into a collapsed quote, and `**`, `*`, `~~`, `#`. It never converts the body of a fenced block: it is stashed first, and only `\` and `` ` `` are escaped.
- The approval card is not affected: `_send_exec_approval_prompt` uses HTML parse mode and `_ea_escape` (html.escape).

Fix:
- `policy.verbatim()` puts text from the model or an operator in a code fence. It is used for:
  - the task name;
  - instructions (create, update, resume, remove);
  - feedback text;
  - an out-of-policy stored schedule or delivery;
  - the `/taches-scout` names, journal, feedback and policy issues;
  - the pause notice.
- Cron expressions are inline code (`` `0 7 * * 1-5` ``).
- `policy.unsafe_shapes()` refuses new text that could close a fence or select the rich path: a line starting with ```` ``` ````, a table separator, a task-list item, `<details>`/`<summary>`, `$$`, a carriage return. This applies to name and instructions (create, update) and feedback; Scout is told to reformulate. The private request contains none of these shapes.
- Text already stored (operator jobs, cron journal) is shown with a visible « · » before such a line, « $ $ » for `$$`, « ␍ » for a carriage return, and a note saying so.
- `split_for_telegram` is fence-aware:
  - a chunk ending inside a fence closes it, and the next one reopens it;
  - every chunk's rendered size is bounded in UTF-16 units, counting MarkdownV2 escapes (budget 3,500 for Telegram's 4,096);
  - a line longer than one message continues in the next one.
- `/taches-scout` returns its first chunk only, with a pointer to the per-task view.
- Side effect, found by the real formatter: before the fix, even an ordinary proposal showed `0 7 * * 1-5` with ` * * ` turned into italics. Expressions are now inline code.

### F7: pause reason

- `reason` must be a string of at most 200 characters (`MAX_REASON_CHARS`); otherwise the call is refused.
- After a successful pause, `manage` posts a notice to the owner: « ⏸️ Scout a mis en pause une tâche planifiée », with the task name and reason in code blocks, and how to resume it (with approval).
- Pause still needs no approval: it only stops runs.

### Tests

| Test | What it proves | On 392e02d |
|---|---|---|
| `test_r2_f6_create_and_update_show_model_text_only_in_fences` | Spoiler, link, collapsed quote, strike, heading, backticks in name and instructions: every line is inside a fence, never outside; fences balanced; rendered size bounded | FAILED |
| `test_r2_f6_feedback_and_long_text_stay_in_balanced_fences` | Feedback text; a 5,600-character all-escaped prompt over three or more messages | FAILED |
| `test_r2_f6_text_that_telegram_would_not_show_verbatim_is_refused` (7 cases) | ```` ``` ```` line, indented ```` ```python ````, table, task list, `<details>`, `$$`, `\r`: refused for create and feedback, nothing posted | 7 FAILED |
| `test_r2_f6_stored_operator_text_is_marked_never_rendered` | Remove of an operator job with fence and table lines: marked, note shown | FAILED |
| `test_r2_f6_command_output_fences_journal_feedback_and_names` | `/taches-scout`: journal, feedback and name fenced; long output truncated with balanced fences | FAILED |
| `test_r2_f7_pause_reason_capped_and_owner_told` | 201 and 100,000 characters, non-string: refused; valid reason: notice posted, verbatim | FAILED |
| `test_pol_11` (updated) | Split keeps every character, rendered size bounded | FAILED |
| Image `test_r2_01` | Through Hermes' real `format_message`: the Markdown-laden create, update and feedback proposals have no unescaped MarkdownV2 special character outside code entities; every instruction line and the name are inside pre blocks; no post takes the rich path | FAILED (`md_create`: entities outside code) |
| Image `test_r2_02` | Fence-breaker and table instructions refused before any post; no job saved | ERROR: the old plugin saved both jobs, the cap filled early, and the lab aborted (`KeyError: 'Remplissage 2'`) |
| Image `test_r2_03` | Every post of the lab (more than 30, both labs) goes through the real formatter: no unescaped special outside code, no rich path, rendered at most 4,096 UTF-16 units; the long owner proposal shows all its instructions in pre blocks | FAILED (plain `deny` proposal: unescaped `_ _` from ` * * `) |
| Image `test_r2_04` | `/taches-scout` output and the pause notice through the real formatter | FAILED (no notice) |
| Image `test_g2_06` (updated) | Pause now posts exactly one notice | FAILED |

How « fails on 392e02d » was measured:
- `git archive 392e02d hermes` was exported to the scratchpad (not a worktree), with the new test files and lab copied in.
- Unit, `-k "test_r2_ or pol_11"`: 13 failed, 0 passed.
- Image, `tool_search` off:
  - With the full new lab: the lab aborts (above).
  - With the two refusal scenarios removed so the lab completes: `test_r2_01`, `test_r2_03`, `test_r2_04` and `test_g2_06` fail.

Results on 4e8e279:
- `test_scout_cron.py` + `test_scout_cron_role.py`: 179 passed (166 + 13).
- `test_scout_cron_image.py`: 116 passed (58 per lab, `tool_search` off and auto).

### Full suite after the last product commit

- Command, from the worktree root at 4e8e279: `uv run pytest hermes/tests -q -p no:cacheprovider -o faulthandler_timeout=300 -rf`. Nothing deselected: the Kaféine gateway labs and both cron image labs are included.
- Started 20:26:58 AST (00:26 UTC, 26 Nov), ended 21:02:08 AST.
- Result: 1 failed, 1167 passed, 27 skipped, in 2109.24 s; exit code 1. Total 1195 = 1175 at 392e02d + 20 new items.
- The only failure is the pre-existing date-sensitive `test_scout03_kandidat.py::test_l06_create_candidature_side_effects` (`'2026-11-26' == '2026-11-25'`). The run started after 20:00 AST, when the UTC date of the fake server's container is already the next day. It is explained under « Answers to review 1 » and passed in the reviewer's run before 20:00. The test and its fixture are unchanged since 975e302.
- The report commit on top of 4e8e279 changes only `report.md`.

### Not done in this cycle

- No check mode: only plugin files changed, the role and configuration did not. The cycle-1 check mode, `changed=5` with the plugin code among the five, still describes what a deployment changes.
- Telegram's own client rendering stays an owner test. The lab proves what Hermes sends (MarkdownV2 text with no entity outside code); the runbook (owner test) tells the owner to deny any proposal that shows formatting outside a monospace block.
- `tools.override` is plugin-wide (review 2 reservation): any later scout_cron change could replace another built-in in Scout's scope without a config change. This is unchanged and recorded; review scout_cron changes with it in mind.

## Answers to review 1

Review `review-1.md` (Codex, CHANGES_REQUESTED on 5a1fb5a). Fix commits: 659c8a2 (plugin, role, config, deploy check), 975fa5b (tests), 392e02d (docs). No deployment; check mode only (below).

### Mechanism (root cause of F1)

- Hermes v0.22.5 runs nothing of a plugin between the approval tap and the dispatch:
  - `pre_tool_call` runs before the card, and Hermes does not re-run the policy after the tap (`hermes_cli/plugins.py`, `_resolve_block_from_details`);
  - tool-execution middleware wraps the whole pipeline, approval included (`agent/tool_executor.py`, `_hermes_pipeline` → `_authorized_dispatch`);
  - the only supported point after the tap is the tool handler.
- Hermes lets a plugin replace a built-in tool in its own profile scope, under an operator grant: `PluginContext.register_tool(override=True)`, gated by `plugin_capability_granted(..., "tools.override")` and stored with `registry.register(scope=<profile>)`.
- scout_cron now registers `cronjob_manage` (Hermes' own schema, toolset `cronjob`) with the handler `manage`, in Scout's scope only.
  - Scout config: `plugins.entries.scout_cron.granted_capabilities: [tools.override]`.
  - Without the grant, `guard_installed` stays false and every scheduling call is refused (fail closed).
  - The role refuses a switch and grant out of sync (`tasks/scout_cron.yml`).
  - The `scout-schedule` check now requires the override for job-search, and the built-in tool everywhere else.
- `pre_tool_call`, for a confirmed action, stores a binding keyed by `tool_call_id`. It holds:
  - the immutable job id;
  - a fingerprint: sha256 over id, name, prompt, deliver, origin, schedule, paused state, `enabled_toolsets`, `repeat.times` and every operator-only field (run bookkeeping excluded);
  - the canonical arguments to dispatch and the expected saved values;
  - the hook kwargs, a reservation flag and a 900 s expiry.
- `manage` runs after the tap, under the `tool_call_id` Hermes binds around the dispatch (`model_tools._approval_observability`). It:
  1. pops the binding (single use);
  2. re-checks profile, cron context, owner DM, `/yolo` and `approvals.mode: off`;
  3. under the plugin lock, re-evaluates the policy against the current store;
  4. requires the same job id, fingerprint and canonical arguments as bound;
  5. calls the other plugins' `pre_tool_call` again (scout_mail);
  6. calls Hermes' built-in handler with the canonical arguments only: immutable id, never a name.
- After a create, update or resume, `manage` re-reads the job. If it differs from the approval or does not conform, the job is paused and an error is returned.
- `feedback_add` goes through the same binding and re-checks, inside the plugin's own tool handler.
- A stale approval saves nothing. The tool result asks Scout to list the tasks and ask again, which produces a new proposal.

### Per finding

| Finding | Fix | Regression tests (fail on 5a1fb5a) |
|---|---|---|
| F1 approval not bound to the job, nor re-checked at execution; feedback resolves the name twice; taint while the card is pending | Mechanism above. scout_mail's veto and the `/yolo` and approvals-off state are re-checked at the save | Unit: `test_r1_f1_name_retargeted_after_approval_is_refused` (Codex's reproduction), `..._same_id_edited_after_approval_is_refused` (remove, resume, update), `..._hermes_gets_the_bound_id_and_canonical_arguments_once` (immutable id, single use, arguments modified after approval), `..._never_approved_call_saves_nothing`, `..._taint_or_yolo_during_the_pending_card_refuses_the_save`, `..._feedback_bound_to_the_job_version`, `..._saved_job_differing_from_the_approval_is_paused`. Image, real store, executor, approval gate and scout_mail, with the change made while the card is pending: `test_r1_02` (rename), `test_r1_03` (same id), `test_r1_04` (late taint, late `/yolo`), `test_r1_05` (feedback), `test_r1_01` (override in Scout only) |
| F2 a terminal outcome released another call's reservation | Reservations are bindings keyed by `tool_call_id`. `post_tool_call` (every terminal outcome) and `manage` release only their own call's. Expired ones (900 s) drop. The count is re-checked in `manage`, under the lock that also covers Hermes' save | Unit: `test_r1_f2_blocked_create_releases_only_its_own_reservation` (Codex's sequence), `..._count_is_checked_again_at_the_save`, `..._two_competing_approved_creates_never_exceed_the_cap`. Image: `test_r1_07` (an operator job saved during the card → « plafond 5 », nothing saved), `test_r1_09` (no binding survives its call: Hermes hands the same `tool_call_id` to the hook, the handler and the post hook) |
| F3 explicit empty override accepted, then saved | Field check by Hermes semantics (table below) instead of truthiness. Hermes only ever receives the canonical arguments, so a blank `prompt` on update is never forwarded (Hermes would clear the instructions) | Unit: `test_r1_f3_every_explicit_value_hermes_would_store_or_clear_is_refused` (24 fields × create/update), `test_r1_f3_create_dispatch_is_canonical`. Image: `test_g3_01[toolsets_empty]`, `[pinned_false]`, `test_r1_06` (blank prompt keeps the instructions) |
| F4 resume ignores the cap; sizes not checked on stored jobs | Resume is refused when the jobs plus live reservations exceed `max_jobs`; pause and remove stay allowed. `conformity_issues` checks the stored prompt and name sizes (an update that replaces the oversized field is allowed). It is used by resume, update, `/taches-scout` and `scout-schedule` | Unit: `test_r1_f4_resume_is_refused_while_over_the_cap` (excess store, lowered limit, pending), `test_r1_f4_conformity_checks_stored_sizes`. Image: `test_r1_08` |
| F5 proposals omit saved instructions, timezone or delivery | Every confirmed action shows the full effective instructions, the schedule (next three runs, Guadeloupe time and UTC) and the delivery: create, update, resume, remove and feedback. An update lists changed and unchanged fields with before → after. A paused job is marked as such | Unit: `test_r1_f5_every_confirmed_proposal_shows_the_effective_task`; `test_g2_02` (image) unchanged |

F3 audit, against `tools/cronjob_tools.py` v0.22.5:
- Always neutral: an absent key, or `None`.
- Fields Scout may not set: any other value is refused, because Hermes acts on it. Two exceptions are Hermes' own no-ops: `paused: false` (handler default) and `include_disabled` (read by `list` only).

  | Field | Value | What Hermes does with it |
  |---|---|---|
  | `enabled_toolsets` | `[]` | stores a zero-tool override |
  | `skills`, `skill` | `[]` | clear on update |
  | `script`, `workdir`, `failure_deliver`, `monitor*`, `context_from` | `''` | clear on update |
  | `pinned`, `no_agent`, `attach_to_session`, `continuity` | `false` | stored |
  | `repeat` | `0` | normalised count |

- Fields Scout may set:
  - `name`, `prompt`, `schedule`: `None` or blank means unchanged, and is not forwarded;
  - `deliver`: only `None`, `''` or `origin`, and never forwarded;
  - `job_id` becomes the immutable id.

Found and fixed during the cycle:
- Registering the override makes `cronjob` a plugin toolset, which Hermes enables by default on every platform where it is not "known" (`_enabled_plugin_toolsets`).
- The image lab caught it, through `test_g1_02` and the scout-mail check: `cronjob` appeared on cron, api_server and cli.
- Fix: `known_plugin_toolsets.{api_server,cli}: [scout_task_record, cronjob]` and `known_plugin_toolsets.cron: [cronjob]` (`test_decl_01`).
- The scout-mail check's registry diff now ignores `cronjob` as well; its exposure is judged by `scout-schedule`.

### Proof that the tests fail on 5a1fb5a

- Unit: 5a1fb5a's `hermes/` tree was exported to the scratchpad (`git archive 5a1fb5a hermes`; not a worktree), the new `test_scout_cron.py` copied in, and `pytest -k test_r1_` run.
  - Result: 56 failed, 6 passed of 62 items. Every test function fails.
  - The 6 passing items are F3 audit rows with non-empty values that 5a1fb5a already refused (`enabled_toolsets: ["web"]`, `repeat: 0`, `paused: true`, each for create and update). Every empty or false row fails.
- Image, 5a1fb5a's plugin with the new lab, `tool_search` off:
  - With the two new F3 rows, the old plugin accepted `enabled_toolsets: []` and `pinned: false` and saved both jobs. The cap was then reached early, and the lab stopped before the interleavings.
  - Without those rows, all 9 `test_r1_*` image tests fail. Observed on real Hermes:
    - rename during the card → `"Cron job 'Remplissage 0' removed."`, id `e298e69e9414`, which is the job renamed INTO that name (Codex's F1, reproduced end to end);
    - same-id edit → the update was saved over the operator's edit;
    - late taint → the removal was saved;
    - blank prompt → forwarded; Hermes then rejected the whole update (« Cron job has nothing to run »);
    - no override installed.
- On 392e02d: `test_scout_cron.py` 154 passed; `test_scout_cron_role.py` 13 passed; `test_scout_cron_image.py` 108 passed (54 per lab, `tool_search` off and auto).

### Kandidat date-sensitive failure

Pre-existing on 975e302; reproduced there.
- Cause: `test_scout03_kandidat.py::test_l06_create_candidature_side_effects` compares the host's `date.today()` with the date the fake Kandidat server takes from its own `date.today()` inside the container (UTC). Between 20:00 and 24:00 Guadeloupe time the two dates differ.
- On 975e302 (untouched base worktree), run at 22:11–22:14 AST (02:11 UTC, 25 Nov): failed, `assert '2026-11-25' == '2026-11-24'`. Same failure on the branch at 22:14–22:17.
- Neither file changed since 975e302. Not fixed here: out of scope, and it is a test-clock issue, not a Kandidat write path.
- Suggested fix, separate: compare with the container's date, or accept either calendar date.

### Full suite after the last product commit

- Command, from the worktree root at 392e02d: `uv run pytest hermes/tests -q -p no:cacheprovider -o faulthandler_timeout=300 -rf`. Nothing deselected: the Kaféine gateway labs and both cron image labs are included.
- Started 23:25:27 AST (03:25 UTC, 25 Nov), ended 00:02:22 AST.
- Result: 1 failed, 1147 passed, 27 skipped, in 2214.69 s; exit code 1.
- The only failure is the pre-existing `test_scout03_kandidat.py::test_l06_create_candidature_side_effects` (`'2026-11-25' == '2026-11-24'`), explained above.
- `test_m5_recovery.py::test_r10_closed_database_is_restored_with_its_sidecars_set_aside` passed. The cycle-0 baseline failure did not recur, as Codex also observed.
- The report commit on top of 392e02d changes only `report.md`.

### Check mode (cycle 1)

- Command, from `hermes/`, worktree venv, at 392e02d: `ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes --check --diff`.
- Result: `ok=84 changed=5 unreachable=0 failed=0 skipped=58`, the same five tasks as in E3:
  - SOUL predecessor replaced;
  - plugin directories;
  - plugin code (7 files, now cycle-1 content);
  - `settings.json`;
  - restart flag.
- The switch assertion, now including the grant, passed.
- Not shown in check mode (existing role behaviour: config reads are skipped): the new keys `plugins.entries.scout_cron.granted_capabilities` and `known_plugin_toolsets.cron`, and the extended `known_plugin_toolsets.{api_server,cli}`. The real run sets them with the other Scout keys before the single restart.
- No change for default (Nora) or cafe-ia (Kaféine). Nothing applied on hermes-31.

### Remaining limits of the fix

- The re-check and Hermes' save run under the plugin's lock, inside the gateway process. A write by another process in between is not excluded; the window is between the re-check and Hermes' write, both inside one handler call. Examples: the operator CLI, or the cron worker updating run bookkeeping, which the fingerprint ignores on purpose.
- New v0.22.5 internals are listed in `hermes_port.py`: the `_approval_tool_call_id` context variable, `registry.snapshot_registration` and `CRONJOB_SCHEMA`. `test_r1_09` and the image labs prove them; any image upgrade must re-run `test_scout_cron_image.py`.
- The approval card text itself is unchanged; the full text is in the posted proposal above it.

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
  - Otherwise it checks the complete proposal with `policy.check_post` (Hermes' whole-message predicates, fence pass, rendered size ≤ 4,000 UTF-16 units) and posts it as one Telegram message, never split; an unsafe or oversize proposal is refused before anything is posted (cycle 5). It then returns `approve` with a ≤ 450-character card and the rule key `scout_cron:<random>`.
  - Hermes' gateway approval gate does the rest: button, 300 s timeout, silence = refusal.
  - `/yolo` or `approvals.mode: off` → block.
  - Fail closed on any error.
- G3: policy on the arguments and the stored jobs:
  - N = 5 jobs, paused included, plus pending creates;
  - Hermes `parse_schedule` must give a 5-field cron with a fixed minute and hour;
  - `deliver` omitted or `origin`; G1 makes origin the owner's DM;
  - instructions ≤ 2,650 and name ≤ 80, both measured as displayed in Telegram (`policy.display_size`), unique name; schedule expression ≤ 40 characters (cycle 5);
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
| Cycle 1, full run on 392e02d | `uv run pytest hermes/tests -q -p no:cacheprovider -o faulthandler_timeout=300 -rf` | 1 failed, 1147 passed, 27 skipped, nothing deselected. The failure is the pre-existing date-sensitive `test_scout03_kandidat.py::test_l06` (fails identically on 975e302 between 20:00 and 24:00 AST) |
| Cycle 1: unit, role, image | `test_scout_cron.py`, `test_scout_cron_role.py`, `test_scout_cron_image.py` | 154, 13, 108 passed |
| Cycle 2, full run on 4e8e279 | same command | 1 failed, 1167 passed, 27 skipped, nothing deselected; the failure is the pre-existing date-sensitive `test_l06` (run after 20:00 AST) |
| Cycle 2: unit + role, image | `test_scout_cron.py`, `test_scout_cron_role.py`, `test_scout_cron_image.py` | 179, 116 passed |
| Cycle 5, full run on 4181f66 | `nice -n 10 uv run --no-sync pytest hermes/tests -q -p no:cacheprovider -rf` | NOT COMPLETED: stopped by Claude Code at about 30 % (low system memory), no failure before the stop; re-run required |
| Cycle 5: unit + role, image | `test_scout_cron.py`, `test_scout_cron_role.py`, `test_scout_cron_image.py` | 201, 122 passed |
| Cycle 5: new tests against e8ae092 | export of e8ae092 + new test files | unit `-k "r3_ or r4_"`: 17 failed (11 on behaviour, 6 on a missing helper), 6 passed (cycle-4 separator tests); image: 12 of 12 selected failed |
| Cycle 4, full run on e8ae092 | `uv run --no-sync pytest hermes/tests -q -p no:cacheprovider -rf` | 1 failed, 1185 passed, 27 skipped, nothing deselected, 7726.36 s; the failure is the pre-existing date-sensitive `test_l06` (run after 20:00 AST) |
| Cycle 4: unit + role, image | `test_scout_cron.py`, `test_scout_cron_role.py`, `test_scout_cron_image.py` | 193, 120 passed |
| Cycle 4: new tests against 4e8e279 | export of 4e8e279 + new test files | unit `-k r3_`: 14 of 14 failed; image `-k "r3_ or r2_03"`: 6 of 6 failed (bare MarkdownV2 specials) |
| Cycle 1: new tests against 5a1fb5a | export of 5a1fb5a + new test files | unit `test_r1_*`: 56 failed, 6 passed (non-empty audit rows already refused); image `test_r1_*`: 9 of 9 failed |

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
- (Closed in cycle 1, F1.) A taint that appears while an approval card is pending is now re-checked at the save: scout_cron calls scout_mail's veto again inside its `cronjob_manage` handler (`test_r1_04`, image).
- The cron worker process takes `HERMES_TIMEZONE` from the gateway environment, i.e. the default profile's `timezone` (unset today). Keep Nora's `timezone` unset or equal to Scout's (runbook §9).
- The plugin depends on v0.22.5 internals (`hermes_port.py`). Any image upgrade must re-run `test_scout_cron_image.py`.
- `/approve` by a stranger was not lab-tested (code evidence only).
- `deploy.yml` has no `schedule-window` gate. Once Scout has jobs, the operator must run the read-only check (runbook §3) before any deploy or restart.

## Repository and infrastructure state

- Branch `feat/scout-self-cron`, pushed; commits 8ea5783, 3f22db6, 20e4e70, 5cff2b9, 5a1fb5a, 98d627e (cycle 0 report), 659c8a2, 975fa5b, 392e02d (cycle 1), plus the cycle 1 report commit. Working tree clean after it, except Codex's own untracked `review-1.md` and `review-brief-1.md` (not committed by the executor).
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
   - Scout condenses the instructions to 2,650 characters at most (the private request is about 3,400), so the proposal fits one message;
   - one « 📋 Scout — proposition de tâche planifiée : créer … » message carries the full saved text, never split;
   - if Scout proposes instructions over the limit, the tool refuses them with a French « raccourcir » message and no card, and Scout shortens and proposes again;
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
2. In one commit: `hermes_scout_cron_enabled: false`, remove `scout_cron` from `plugins.enabled`, put `cronjob` back into Scout's deny list, set `plugins.entries.scout_cron.granted_capabilities: []` (the role never deletes a config key). The role refuses an inconsistent set.
3. Run check mode, then deploy.

To revert the whole MR instead, mind three things:
- the SOUL (the reverted SOUL is not re-seeded automatically);
- removing `timezone`, which shifts the wall-clock time of any remaining job by 4 h;
- the plugin files, which stay on disk, inert.

## Recommended next action

Review 5 (PASS_WITH_RESERVATIONS on 4181f66) is answered at 5d9f0a0 (cycle 5b: F10, F11). Next: the pilot merges MR !111 once the branch is green (owner rule, mission.md 2026-11-27T11:25Z). Then the owner's deployment decision (D-DEPLOY) and the owner Telegram tests above. Nothing is safe to execute on hermes-31 without that decision.
