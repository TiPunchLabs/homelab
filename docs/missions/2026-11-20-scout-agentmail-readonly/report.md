# Report — homelab/2026-11-20-scout-agentmail-readonly (SCOUT-MAIL-01)

Verdict: PARTIAL
Version: b22ba76472d3884e24a2954e40ec7e2b4793b040

The verdict is PARTIAL because three required items are not verified:
- the live behavioral evaluation (AC10: no model credential was legitimately available);
- the AgentMail read smoke test (runbook step 6), after merge and deployment at the owner's call. Q1–Q3 are answered by the owner (inbox, scoped key, vault); the key scope is the owner's statement, not executor-verified;
- the independent review: review 1 (Codex, on 78ee2ee) returned F1–F3 (§K); review 2 (on edcd9fe) found F1/F2 partial and F4–F6 (§L). All are fixed in the Version above and await review 3 of 3.

Everything else is implemented and verified offline, including on the real Hermes v0.22.5 image. Production is unchanged.

## A. Executive summary

Objective: let the owner ask Scout, in its private Telegram chat, for a French summary of the job-search mail of exactly one AgentMail inbox. Mail content must be structurally unable to reach Scout's privileged tools (Web, Kandidat, memory, skills, session search, delegation, files, shell) on that turn or any later one.

Delivered on branch `feat/scout-agentmail-readonly` (draft MR, see §F):
- a Hermes user plugin `scout_mail`, deployed and enabled in Scout's profile only, disabled by default. It provides one gateway command, `/courriels [liste|suite|aide]`, and four guard hooks, and registers no tool;
- Ansible wiring (`tasks/scout_mail.yml`, kill switch, key handling, post-restart check `hermes_checks.py scout-mail`);
- ADR-002, threat model and enforcement matrix, operator runbook;
- 121 new tests: 105 deterministic plugin tests (15 added after review 1, 16 after review 2), 5 in the real Hermes v0.22.5 image, and 11 Ansible-wiring tests (parameter cases included).

Not achieved in this mission: live model evaluation, provider-side key scope verification, read smoke test, independent review, deployment (out of scope by design).

## B. Initial state and scope

- Worktree `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01`, branch `feat/scout-agentmail-readonly` from `origin/main` 3d7bf18.
- Runtime re-verified read-only: hermes-31 runs `Hermes Agent v0.22.5 (2026.9.24) · upstream bf0203a7`, equal to the repo pin. All profile config and SOUL hashes equal the repo/R1 baseline (`evidence/d1-discovery.md` §1).
- Excluded and not done: merge, deploy, gateway/container restart, vault decrypt, sending mail or Telegram messages, mailbox mutation, Kandidat data, cron drafts, Hermes upgrade, HomeLab cleanup, second bot.

## C. Architecture (AC2)

Full decision record: `docs/adr/hermes.md` ADR-002. Threat model: `docs/references/scout-mail-threat-model.md`.

Where untrusted mail is interpreted: only inside one model call with a fresh context.
- It is issued by trusted plugin code with `httpx` to `api.deepseek.com`: model `deepseek-v4-flash` (Scout's model), no `tools` key, one attempt, no redirects.
- The prompt is a fixed French system prompt plus one user message carrying the bounded batch as JSON data with opaque refs M1..Mn. There are no real ids, inbox, credentials, SOUL, memory or conversation in it.

What capabilities that context has: none. It produces JSON, which trusted code validates field by field: unknown or duplicate refs and fields are dropped and lengths are capped.

How output reaches Telegram:
- a trusted renderer neutralizes every untrusted string, so no link, bare domain, `@mention`, `/command`, `#tag` or markdown can form;
- it adds fixed French labels and the marker `📬 Courriels — contenu externe non fiable`;
- the plugin posts at most 3 parts directly to the owner's DM with `ctx.apost_message`.

Is the command authorized? Yes, enforced in code: profile `job-search`, platform telegram, chat type dm, user in the Telegram allowlist, chat id == user id. This comes on top of Hermes' own allowlist.

Can mail-derived text enter Scout's ordinary history and influence a later privileged turn? Not through the command: a plugin slash command runs in the gateway before any agent turn, and its reply is not written to the transcript. This is verified in Hermes source (`gateway/run_inbound.py:1242-1284`, `run_inbound_hooks.py:209-300`; `append_to_transcript` only in turn code) and in the image (`test_c5_07`, `state.db` row counts unchanged).

The owner can still carry it over. Discovery found that a Telegram reply injects the quoted text as `[Replying to: "…"]` (`gateway/run_inbound.py:1555-1563`). It is neutralized in code:
- `pre_gateway_dispatch` (runs at ingress inside Scout's scope, `run_inbound.py:215`): a reply to a recorded digest message id, or a reply or paste matching the marker or a 48-char folded fingerprint of a digest, is rewritten to `/courriels refus-reponse`. The agent never runs and the owner gets a fixed refusal;
- `pre_llm_call`: any turn whose message or history contains such text taints the session, and a compressed child session inherits the taint;
- `transform_tool_result`: a tool result containing such text (for example `session_search`) is replaced and the session tainted;
- `pre_tool_call`: every tool is vetoed in a tainted session, for good. `/new` starts clean.

The ledger stores message ids, 8-byte hashes and tainted session ids, never text (0600). It never expires or evicts an entry; it has hard capacities (20,000 results, 300,000 fingerprints, 100,000 sessions) and fails closed when one is reached: no new digest is delivered, an unrecordable session restriction is kept in memory, and all Scout messages are refused at session capacity. On any internal error the hooks fail closed.

No global registry mutation: the plugin is discovered per profile home and enabled in Scout's `plugins.enabled` only. Verified on the image: present for job-search, absent for default and cafe-ia, no toolset added, 400 concurrent decisions across 3 homes with 0 under-blocks and 0 over-blocks.

Rejected alternatives (one line each, detail in ADR-002):
- AgentMail MCP: 47 tools including send/delete, and a server-asserted `readOnlyHint`;
- a summary tool or MCP returning free text to Scout: mail text would land in privileged history;
- a temporary registry mutation: leaks across profiles and concurrent requests;
- a second bot: needs an owner decision;
- SOUL instructions alone: behavioral only;
- `call_llm`: unbounded retries and provider fallback;
- the official SDK: follows redirects by default.

## D. Enforced versus behavioral controls

ENFORCED, in code:
- no tool in the mail path; transport surface `list_messages`/`get_message`/`complete` only;
- AgentMail GET only, on a fixed host and one inbox (settings, never chat or model);
- message ids only from that inbox's list, ownership re-checked on get, path/traversal/control characters refused;
- redirects refused, TLS verified, `trust_env=False`; no link, image, attachment or raw fetch;
- byte, char, page, call, retry and deadline ceilings; the deadline holds during HTTP streaming (socket watchdog plus per-chunk check); the context cap covers system prompt, prefix and data; one model call;
- neutralized rendering; caller authorization;
- reply/paste refusal; session taint and tool veto; tool-result scrubbing;
- secrets per host only; fixed French errors; logs are counts only;
- fail-closed on missing key, invalid settings and ledger errors;
- Ansible: kill switch with mismatch refusal, key written/removed with `no_log` and 0600, settings validated, post-restart scoping check.

BEHAVIORAL (supplementary, no permission depends on it):
- the summarizer's system prompt (treat mail as data, no URLs, flag requests as uncertainties);
- JSON shape compliance (an invalid output falls back to metadata, with no second call).

OWNER PROCEDURE (not code):
- provider-side key scope (inbox-scoped, `inbox_read` + `message_read`);
- no paraphrase or retyping of mail content into ordinary Scout messages (residual, see §E).

## E. Verification and evidence

### Brief case to test mapping (AC4, AC5)

| Case | Tests (pytest ids) |
|---|---|
| 1 Normal French, accents, HTML newsletter, empty, multiple | `test_c1_01_french_alert_summarized_with_attribution`, `test_c1_02_html_newsletter_is_text_only_and_fetches_nothing`, `test_c1_03_empty_inbox`, `test_c1_04_several_messages_each_attributed` |
| 2 Injection in subject, display name, body, quoted history, filename; fake delimiters; owner/admin claims | `test_c2_injection_never_reaches_instructions_and_adds_no_operation[inj_subject, inj_display_name, inj_body, inj_quoted, inj_filename]`, `test_c2_fake_role_delimiters_are_data_not_messages` |
| 3 Kandidat export, exfiltration URL, send, shell, other inbox, delegate, persist | `test_c3_hostile_model_output_executes_nothing_and_renders_inert`, `test_c3_transport_has_no_write_or_generic_operation`, `test_c3_tainted_session_cannot_use_any_privileged_tool` |
| 4 Hidden HTML, tracking images, encoded/multilingual, malicious markdown; detector miss | `test_c4_hidden_html_dropped_and_no_resource_fetched`, `test_c4_encoded_text_is_never_decoded`, `test_c4_malicious_markdown_rendered_inert`, `test_c4_detector_miss_does_not_restore_privileges`, `test_r01_*`..`test_r03_*` |
| 5 Poisoned summary and follow-up turns | `test_c5_01_reply_to_result_is_refused_before_scout`, `test_c5_02_partial_quote_without_id_and_paste_are_refused`, `test_c5_03_busy_path_quote_taints_session_and_blocks_tools`, `test_c5_04_taint_survives_compression_and_new_session_is_clean`, `test_c5_05_session_search_cannot_reimport_mail_text`, `test_c5_06_command_reply_is_not_history_and_ledger_holds_no_text`, `test_c5_07_command_writes_no_session_history_and_ledger_is_private` (image), `test_c7_13_every_delivered_part_is_recorded` |
| 6 Cross-inbox ids, unknown tools, unexpected fields, readOnlyHint drift | `test_c6_01`..`test_c6_06` |
| 7 Oversized, malformed, pages, rate limits, retry loops; explicit partial results | `test_c7_01`..`test_c7_12` |
| 8 Concurrency, cancellation, exception then retry, Scout/Nora/Kaféine | `test_c8_01`..`test_c8_05`; image: `test_c8_06_concurrent_multi_profile_decisions_never_leak`, `test_c8_07_command_absent_elsewhere_and_fail_closed_in_scout`, `test_i01_plugin_loads_for_scout_only`, `test_i02_no_tool_added_to_the_global_registry` |
| 9 Secret redaction, log retention, sentinels | `test_c9_01`..`test_c9_04`, `test_r05_nothing_expires_with_time`, `test_role_02_enabled_requires_inbox_and_key_and_never_prints_the_key` |
| 10 Existing tests and repo checks | full suite, see below |
| Review 1 regressions | `test_f1_01`..`test_f1_05` (F1), `test_f2_01`..`test_f2_03` (F2), `test_f3_01`..`test_f3_03` (F3), see §K |

Ansible wiring: `test_role_01` … `test_role_06` (including `test_role_02b_switch_out_of_sync_with_declaration_is_refused`).

### Results

| Check | Command / location | Result | Status |
|---|---|---|---|
| New plugin tests (deterministic) | `.venv/bin/python -m pytest hermes/tests/test_scout_mail.py` | 105 passed in 27.7 s (74 before review 1, 89 before review 2) | VERIFIED |
| Real image tests (Hermes v0.22.5, `--network none`) | `hermes/tests/test_scout_mail_image.py` | 5 passed | VERIFIED |
| Ansible wiring tests (real `tasks/scout_mail.yml` on localhost, fake key) | `hermes/tests/test_scout_mail_role.py` | 11 passed | VERIFIED |
| Deploy-time check in the image (disabled / enabled / mismatch) | `hermes_checks.py scout-mail` run inside the image | "inactive everywhere" rc 0 / "active for job-search only" rc 0 / mismatch rc 1 | VERIFIED |
| Baseline, before any change (HEAD 3d7bf18) | `evidence/m3-baseline-tests.md` | 711 of 749 reported before the 25-min cap; 1 failure (`test_m5_recovery.py::test_r10_…`), not reproduced in isolation (intermittent) | PARTIAL (38 not executed) |
| Full suite after change, run 1 | `evidence/m3-post-change-tests.md` | 10 regressions from the first wiring (all reproduced), fixed (see §F) | superseded |
| Full suite after change, run 2 (code = 78ee2ee), per file | `evidence/m3-post-change-tests-2.md` | 839 collected: 809 passed, 0 failed, 30 skipped, 0 errors | superseded |
| Full suite after review 1 fixes (code = edcd9fe), per file | `evidence/m6-post-review-1-tests.md` | 854 collected: 827 passed, 0 failed, 27 skipped, 0 errors | superseded |
| Full suite after review 2 fixes (code = b22ba76) | `evidence/m7-post-review-2-tests.md`; `uv run pytest hermes/tests -q -rs -k "not (test_m7_kafeine and test_lab_)"` | 870 collected: 832 passed, 0 failed, 27 skipped, 11 deselected (hanging `test_m7_kafeine` lab, §F), 1,318 s | VERIFIED |
| Skips | same | 27 need image `v2026.8.18` (not local). The v0.22.5 image is now local, so its image tests ran (scout_mail image 5 passed; m63 and scout03 labs passed) | NOT_APPLICABLE |
| ansible-lint (production profile) | `.venv/bin/ansible-lint` on role tasks, defaults, group_vars | 0 failures, 0 warnings | VERIFIED |
| Syntax check | `ansible-playbook ansible/deploy.yml --syntax-check` | pass | VERIFIED |
| `--check --diff` against hermes-31 | — | not run: it would decrypt the vault and contact the host | NOT_VERIFIED |
| pre-commit (incl. gitleaks) on all changed files | `.venv/bin/pre-commit run --files …` and at commit | all passed; 2 end-of-file whitespace fixes applied | VERIFIED |
| Sentinel secrets in repo | `test_c9_04_sentinels_absent_from_git_tracked_content_except_this_file`; grep of mission docs | only in the test file that defines them | VERIFIED |
| Ruff (not a repo hook; user convention) | `uv tool run ruff check --select E,F,W,B,UP` | clean except 9 lines of 121–125 chars in tests | VERIFIED (style) |

Existing behavior preserved (AC8):
- the Scout declaration changes by one literal key, `plugins.enabled: []` (`m4_era` in `test_m4_scout.py` now strips it, like the SCOUT-03/04 keys);
- Nora's and Kaféine's declarations, the SOUL files, Kandidat MCP entries, the approval gates, the tool matrices and the cron drafts are unchanged (`test_role_04_*`, and the existing equality tests pass);
- `validate.yml` was not changed: the AgentMail key moved to `tasks/scout_mail.yml` precisely so the empty-env guard keeps its meaning.

### Hard limits and fixture run (AC6)

Defaults (`files/plugins/scout_mail/config.py` `Limits`; every override is bounded in code):

| Area | Ceiling |
|---|---|
| Messages per request | 8 |
| Pages per request | 1 |
| Bytes per AgentMail response | 256 KiB |
| HTML input per message | 200,000 chars |
| Field length | subject 160, sender 120, body 3,000 chars |
| Total model context | 20,000 chars: system prompt + prefix + data (minimum setting 4,000) |
| Model calls per request | 1 |
| Model output | 1,200 tokens |
| Retries | 1, only on 429 or 5xx, Retry-After at most 2 s |
| Timeouts | HTTP 10 s, model 40 s per network operation; wall clock 75 s, enforced during streaming (residual: DNS resolution, bounded by the system resolver) |
| Reply | 3 parts of 3,500 chars |

Fixture run (`hermes/tests/scout_mail_fixture_run.py`, `evidence/m3-fixture-run.json`; offline, so network and model latency are not included). The model-context column below is data only (pre-review); after F3 the TOTAL context is 4,460 / 17,201 / 19,977 chars and request bytes 5,028 / 18,821 / 22,448 (`evidence/m6-fixture-run-r1.json`):

| Batch (8 read) | Model context (chars) | Model request (bytes) | Reply (chars) | Parts | All shown | Local CPU (ms, median) |
|---|---|---|---|---|---|---|
| All synthetic fixtures (10 listed, 1 page of 8) | 3,258 | 5,028 | 3,446 | 2 | yes | 1.25 |
| 8 dense job alerts (~2.3 KB each) | 15,999 | 18,821 | 3,487 | 2 | yes | 1.86 |
| 8 HTML newsletters (~10 KB each) | 19,971 (at cap, bodies trimmed) | 23,786 | 3,823 | 2 | yes | 6.70 |

Justification:
- 8 dense alerts fit under the 20,000-char context, and only HTML-heavy batches hit it, trimmed explicitly;
- 2 Telegram parts suffice for 8 messages;
- worst-case model output (every field at its cap) still shows at least 4 of 8 and names the rest (`test_c7_12`);
- 75 s total leaves one AgentMail retry and a 40 s model call.

Bug found and fixed by this run: the first renderer read 8 messages but could show fewer in one 3,500-char message, and `suite` would then skip them. Rendering is now multipart with marked parts and explicit "non affichés" refs.

### Behavioral evaluation (AC10)

NOT_VERIFIED: 0 of 40 calls used. Reason and owner command: `evidence/m4-live-eval.md`. The harness (`hermes/tests/scout_mail_live_eval.py`) is ready: 12 synthetic cases, real DeepSeek, AgentMail faked, trace without the key. No string assertion was substituted.

### AgentMail facts (AC1)

`evidence/d1-agentmail-docs.md` (2026-11-20, WebFetch; context7 had no AgentMail entry in this session):
- the two operations used are list and get;
- get has no documented side effect, and there is no mark-read endpoint;
- the permission whitelist means omitting it grants ALL; inbox/pod/org scopes; 403 `missing_permission`/`forbidden`;
- 429 with Retry-After of about 1 s, no numeric rate limit documented;
- the SDK follows redirects by default.

## F. Deviations, risks and limitations

- Residual: if the owner paraphrases or retypes mail content (fewer than about 55 contiguous letters/digits, or reworded) into an ordinary Scout message, it is not detected. That is owner-authored input, not mail authority (`test_c4_detector_miss_does_not_restore_privileges`).
- Residual: a cancelled `/courriels` lets its worker thread finish in-flight HTTP calls, released at the latest at the 75 s deadline by the watchdog on the live (TLS) connection. It delivers and records nothing. A cancellation after a part was posted locks the feature down (§L).
- Residual: name resolution of the two fixed hosts happens before a socket exists and is bounded by the system resolver, not by the deadline watchdog.
- Operations: the ledger grows without expiry; at capacity `/courriels` stops delivering until the operator archives it together with `/new` (runbook §8). Archiving re-opens quoting of archived digests only where the marker is absent.
- Residual: the summary can be wrong or influenced by the mail. It is labeled "IA, non vérifiée" and is inert.
- Data flow: requested mail text goes to DeepSeek (Scout's existing provider). `/courriels liste` makes no model call.
- Dependency: the isolation relies on Hermes v0.22.5 plugin scoping and dispatch order. The image tests must be re-run before any Hermes upgrade.
- Busy path: a Telegram reply sent while Scout is mid-turn goes through Hermes' busy handler. That handler was not exercised end to end (no live gateway). Layer 2 (taint plus veto) covers it at unit level (`test_c5_03`).
- Not verified: the `scout_mail request …` log line landing in `profiles/job-search/logs/agent.log` (Hermes logger routing). The runbook uses it as evidence; confirm on first use.
- Availability trade-off: a corrupt or full ledger, or a lockdown (restriction or delivered id not recordable, uncertain delivery, hook fault, unwritable ledger directory), blocks Scout's tools, messages or new digests (fail closed) until the operator acts. Runbook §8 covers it.
- Residual (F4): if the ledger directory refuses both creating `taint.lockdown` and renaming the ledger, the lockdown is held in memory; after a restart the start-up probe keeps Scout refused while the directory stays unwritable. A directory that refused every write and recovered before the restart loses that lockdown.
- Test environment: with `nousresearch/hermes-agent:v0.22.5` now present locally, the 11 `test_m7_kafeine.py` lab tests run and hang in `test_lab_kafeine_config_and_hint_apply` (container up, test never returns). That file is untouched by this MR; the tests were deselected in the review 2 full run and not investigated further. The lab container left by the interrupted run was removed (`docker rm -f hermes-m7-lab-gw`).
- Settings change: `retention_days` was removed from the plugin settings (unused by the role); `model_context_max_chars` minimum raised from 2,000 to 4,000 so the fixed instructions always leave room for data.
- First deployment after merge (feature off) writes the inert plugin and `plugins.enabled: []`, causing one gateway restart (runbook §1).
- Known intermittent test: `test_m5_recovery.py::test_r10_closed_database_is_restored_with_its_sidecars_set_aside` failed once in the baseline run and passed in isolation (`evidence/m3-baseline-tests.md`).
- Process deviations:
  - the first baseline run failed because `uv` picked Python 3.15. The executor rebuilt the worktree `.venv` on 3.12 (gitignored);
  - two shell commands that touched credential variables were denied by permission policy and not retried;
  - `glab` returned 401, so the MR was created through git push options and CI was read from the public API (§G);
  - a subagent accidentally created an empty directory `/home/xgueret/tmp` outside the repository. It was left in place; removing it (`trash`) needs your confirmation;
  - the first post-change run found 10 regressions (an empty-env guard in `validate.yml`, declaration-equality tests, and a literal `job-search` inside `hermes_checks.py` that tripped a probe test). The fix moved the AgentMail key into `tasks/scout_mail.yml`, made `plugins.enabled` a literal plus a mismatch assert, and turned the check's owner into an argument. All 10 pass after the fix.

## G. Repository and infrastructure state

| Item | Value |
|---|---|
| Branch | `feat/scout-agentmail-readonly`, pushed, tracking `origin` (`git@gitlab.com:tipunchlabs/homelab.git`) |
| Delivered code commit (Version) | `b22ba76472d3884e24a2954e40ec7e2b4793b040` fix(hermes): verrouiller scout_mail durablement apres la revue 2, on top of `edcd9fe` (review 1 fixes) and `78ee2ee` feat(hermes): ajouter /courriels |
| Owner-input commits | `53c0f8c` chore(hermes): set the Scout mail inbox id (Q1, `test_role_04` aligned); `225fc3a` chore(hermes): provision the Scout read-only AgentMail key in the vault (Q3, encrypted file only) |
| Mission evidence commit | `1b27f9f` docs(missions): consigner la mission SCOUT-MAIL-01 et ses preuves |
| Report commits | `a9e4a81` (initial), `2a12a2a` (review 1); review 2 update follows this file (docs(missions)) |
| Draft MR | !109 https://gitlab.com/tipunchlabs/homelab/-/merge_requests/109 (draft: true, opened, target main, source branch kept). Created through git push options because `glab api user` returned 401 |
| CI | Pipeline 3094652113 on 1b27f9f (contains 78ee2ee): success. Jobs: scan-docker-images, gitleaks, security-check, shell-lint, runner-quota-tests, terraform-lint, ansible-lint all succeeded. Read from the public API. The pipeline does not run the hermes pytest suite; that suite was run locally (§E) |
| Merge | not done (out of scope) |
| Deployment | none; no `ansible-playbook` against any host, no restart |

Production changes: none. Verified read-only on hermes-31 at 2026-11-20T13:40Z:
- config hashes after = before: Nora 0f3f6948…, Scout 054ec615…, Kaféine c4bc5113…, managed fb2f043f…;
- SOUL hashes after = before: 7dc753fe…, a3b4e2c2…, b08468d8…;
- container started 2026-11-20T03:45:34Z with 0 restarts;
- `profiles/job-search/plugins` is empty and there is no `plugin-data`.

Secret provisioning: `vault_hermes_job_search_agentmail_api_key` added by the owner (Q3, 2026-11-21), committed encrypted in `225fc3a`. Nothing deployed: hermes-31 still has no AgentMail variable.

Deployment readiness: ready to merge as an inert feature after review 3. Q1–Q3 are answered (2026-11-21, section I); `hermes_scout_mail_enabled` stays `false`. Enabling remains an owner decision after merge: runbook §2–§4, then the read smoke test.

## H. Delegations and models

Executor session model: Claude Opus 5.5 (`claude-opus-5-5`). Design, security reasoning, product code and tests stayed on it.

| Task | Subagent model |
|---|---|
| AgentMail and OWASP doc retrieval and summary (`evidence/d1-agentmail-docs.md`) | Sonnet |
| Baseline test run, attempt 1 (blocked by Python 3.15) | Haiku |
| Baseline test run, attempt 2 (`evidence/m3-baseline-tests.md`) | Haiku |
| Post-change suite, ansible-lint, syntax-check, pre-commit (`evidence/m3-post-change-tests.md`) | Haiku |
| Post-change suite after fixes (`evidence/m3-post-change-tests-2.md`) | Haiku |
| Review 1 fixes, tests and full-suite run (`evidence/m6-post-review-1-tests.md`) | none (executor, Opus) |
| Review 2 fixes, tests, red/green comparison and full-suite run (`evidence/m7-post-review-2-tests.md`) | none (executor, Opus) |

## I. Decisions required (owner)

- D1 (Q1): ANSWERED 2026-11-21. Inbox `scout-emploi@agentmail.to`, region `api.agentmail.to` (US), confirmed by the owner's read call (HTTP 200 on `https://api.agentmail.to` for this inbox). Set as `hermes_scout_mail_inbox_id` in `hermes/ansible/group_vars/hermes/all/main.yml`, `hermes_scout_mail_enabled` kept `false`; the role host default is already `api.agentmail.to`. `test_role_04` (`hermes/tests/test_scout_mail_role.py:116`) now asserts this inbox id instead of `""`; the rest of the test is unchanged. Ansible-wiring tests rerun after the change (see owner-questions.md Q1).
- D2 (Q2): ANSWERED 2026-11-21. Dedicated key, inbox-scoped to `scout-emploi@agentmail.to`, `inbox_read` + `message_read` only, created with the owner-questions command; read call returned 200 (owner statement).
- D2b (Q3): DONE 2026-11-21. Key stored in the vault by the owner, committed encrypted (`225fc3a`).
- D3 (Q4, optional): run the live evaluation (40 calls max) before merge.
- D4: merge the draft MR after independent review; then decide on enablement (runbook §2–§4).

## J. Recommended next action

Pilotage routes Codex review 3 of 3 at the Version above. Focus: F4–F6 (§L), the lockdown recovery procedure (runbook §8) and the HTTPS deadline tests. No production action is safe or authorized before merge; enabling and the read smoke test are owner decisions after it.

## K. Review 1 (Codex, on 78ee2ee): findings, fixes, tests

Review: `review-1.md`, verdict CHANGES_REQUESTED. Fixes in `edcd9fe70508f51ad2d06bc84ea3322f11ad5c12`.

F1 [blocker] taint/session restriction expiry.
- Finding: `taint.py` pruned results after 60 records or 30 days and sessions after 30 days or 2,000 entries, so an old digest could be quoted or a restricted session regain tools.
- Fix: no time-based expiry and no eviction (`taint.py`). Hard capacities raise `LedgerFull`; the command then refuses delivery (`FULL_FR`), an unrecordable session restriction is kept in an in-memory guard checked by `pre_tool_call` and inherited by compressed children (`__init__.py` `_restrict`, `guarded`), and `pre_gateway_dispatch` refuses every message at session capacity. Reads use a stat-keyed cache. `retention_days` removed from settings. ADR-002, threat matrix (T3, T13) and runbook corrected.
- Tests: `test_f1_01_old_result_is_not_evicted_by_later_results` (the review's R1 with 300 later results: reply rewritten, paste rewritten, tool blocked), `test_f1_02_restriction_outlives_time_and_compression` (400 days, compressed history without marker, compressed child: blocked), `test_f1_03_full_result_capacity_refuses_delivery_and_keeps_old_provenance`, `test_f1_04_unrecordable_restriction_is_kept_in_memory_and_full_ledger_refuses`, `test_f1_05_ledger_write_error_during_taint_still_blocks_tools`, `test_r05_nothing_expires_with_time`. VERIFIED.

F2 [major] wall-clock ceiling during HTTP streaming.
- Finding: per-operation httpx timeouts allowed a trickling body to run 135 s against a 75 s deadline.
- Fix: `HttpxBackend.send` takes `remaining` (the request budget). It refuses to start with no time left, sets per-operation timeouts to at most the time left, re-checks after every chunk, and a watchdog timer shuts the TCP socket (captured through the httpx `trace` extension at `connect_tcp.complete`) at the deadline, aborting a blocked connect/write/read. Expiry maps to `BudgetExceeded`. Residual: DNS resolution.
- Tests: `test_f2_01_trickling_body_cannot_outlast_the_request_deadline` (the review's R2: now raises at ≤ 84 simulated s, the first chunk past 75 s), `test_f2_02_real_httpx_backend_is_cut_at_the_deadline[trickle|stall_body|stall_headers]` (real httpx against a local server, 10 s operation timeout, 1 s deadline: cut in < 2 s), `test_f2_03_real_httpx_backend_fast_response_still_works`. VERIFIED (local loopback, not live network).

F3 [minor] context cap excluded system prompt and prefix.
- Finding: with a 2,000 cap, 3,184 chars were sent; only the JSON data was measured.
- Fix: `build_messages` reserves `SYSTEM_PROMPT` + `USER_PREFIX` + wrapper first and returns the total content size; `context_chars` is now total. Minimum cap raised to 4,000 (fixed text is about 1,340 chars).
- Tests: `test_f3_01_context_cap_includes_system_prompt_and_prefix[4000|8000|20000]` (measured == sum of message contents ≤ cap), `test_f3_02_model_request_content_respects_the_configured_total` (POSTed body, cap 6,000), `test_f3_03_context_cap_below_fixed_instructions_is_rejected`. VERIFIED.

Review reservations not turned into code changes in this cycle (no finding raised them):
- Telegram link previews are not disabled by the plugin; it relies on URL neutralization. To verify on first enablement (runbook).
- The reviewer's whole-file runs of `test_scout_mail.py` stalled in asyncio executor shutdown inside the review sandbox. In this environment the file completes (89 passed in 19.4 s); the stall was not reproduced here.

## L. Review 2 (Codex, on edcd9fe): findings, fixes, tests

Review: `review-2.md`, verdict CHANGES_REQUESTED (F1 and F2 partially fixed, F3 fixed, new F4–F6). Fixes in `b22ba76472d3884e24a2954e40ec7e2b4793b040`. Review 2's assessment stands for §K: its in-memory guard (F1) and its watchdog on the pre-TLS socket (F2) were not complete; both are replaced below.

F4 [blocker] restriction lost on restart when the session write fails (completes F1).
- Finding: `_restrict` kept an unwritable restriction in `self.guarded`, emptied at every plugin start; after compression and restart the session regained every tool (review R4).
- Fix (`taint.py` `lockdown`, `locked`, `probe_writable`; `__init__.py` `_lockdown`, `_is_locked`): the in-memory set is removed. Any restriction that cannot be written, any hook evaluation fault and any tool-result evaluation fault lock the whole feature down durably: an empty `taint.lockdown` file is created beside the ledger (no data block needed); if that fails, the ledger is renamed to `taint.lockdown`. While it exists, `pre_gateway_dispatch` rewrites every Scout message to the registry refusal and `pre_tool_call` vetoes every tool, across restarts, until the operator follows runbook §8. At start-up the plugin probes the ledger directory; if no file can be created there, Scout is refused from the start.
- Tests: `test_f4_01_unwritable_restriction_survives_compression_and_restart` (review R4: write failure, compressed history, new plugin instance via the real constructor, compressed child: all blocked, messages refused), `test_f4_02_lockdown_falls_back_to_renaming_the_ledger`, `test_f4_03_unwritable_ledger_directory_keeps_scout_refused_across_restart` (directory 0500, real constructor), `test_f4_04_hook_evaluation_error_locks_down_durably`. Existing `test_f1_04` renamed `test_f1_04_unrecordable_restriction_locks_down_and_full_ledger_refuses`. VERIFIED.
- Residual: if the directory refuses both creating the lockdown file and renaming the ledger, the lockdown lives in memory; after a restart the start-up probe keeps Scout refused while the directory stays unwritable. Only a directory that refused every write and then recovered before a restart loses the lockdown. Hermes writes that turn's transcript to the same filesystem.

F5 [blocker] last ledger slot: delivered message ids lost (completes F1).
- Finding: the pre-delivery record took a slot without ids and the ids were written as a second record; with one slot left the second write raised `LedgerFull`, was logged only, and a reply to the delivered id with a short marker-free quote was accepted (review R5).
- Fix (`taint.py` `record_result` returns a record handle, `attach_ids`; `__init__.py` `command`): the result is reserved (fingerprints, one slot) before delivery; after each posted part its Telegram id is attached to that same record, which needs no new slot. If attaching fails, a posted part has no id, or the delivery is interrupted (exception or cancellation after a post), the plugin locks down durably (F4 mechanism) and re-raises a cancellation.
- Tests: `test_f5_01_last_result_slot_still_records_the_delivered_ids` (review R5 at the real default `MAX_RESULTS=20000`: id recorded, reply rewritten to the refusal, next `/courriels` refused as full), `test_f5_02_failed_id_write_after_delivery_locks_down_durably` (every write after the reservation fails: reply refused before and after restart, tools vetoed), `test_f5_03_delivery_cancelled_after_posting_locks_down`. `test_f1_03` now uses `MAX_RESULTS=1` since a delivery takes one record. VERIFIED.

F6 [major] deadline watchdog on a detached socket over HTTPS (completes F2).
- Finding: the watchdog kept the socket object from `connect_tcp.complete`; `ssl` detaches it when wrapping, so the shutdown hit a dead object and trickled headers kept the exchange alive past the deadline (review R6: 0.671 s for a 0.15 s deadline, 0 TLS-socket shutdowns).
- Fix (`transport.py` `_Watchdog`, `_abort`): the watchdog records the connection's file descriptor and its socket identity (`st_dev`, `st_ino`). The descriptor number is unchanged by the TLS wrap, so the handshake, headers and body are all covered. At the deadline it duplicates the descriptor, re-checks the identity (a number reused after close is never touched), calls `shutdown(SHUT_RDWR)` and closes only the duplicate. It is disarmed in `finally`. The per-operation timeout stays capped by the time left; the per-chunk deadline check stays.
- Tests: `test_f6_01_https_exchange_is_aborted_at_the_deadline`, 8 cases = {never-answered handshake, trickled headers, trickled body, stalled body} × {loopback TCP, socket pair with `connect_tcp` patched (no network socket, as in the reviewer's sandbox)}. Each case uses real httpx 0.28.1, httpcore 1.0.9 and Python `ssl` with a throwaway certificate verified by the client, a 1 s deadline and a 10 s operation timeout. It asserts `BudgetExceeded` in under 1.8 s and that the server sees the connection closed in under 2.5 s (connection released, no partial response returned). `test_f6_02_https_fast_response_still_works`. VERIFIED.
- Red before the fix: the two trickled-header cases (the exchange never ended; the test bounds it in a worker thread). The handshake and stalled-body cases already passed on edcd9fe, because the operation timeout was capped by the time left; they are kept as regressions over HTTPS. The trickled-body case also passed (per-chunk check).
- Residual unchanged: name resolution is outside the watchdog (system resolver).

Red/green evidence (`evidence/m7-post-review-2-tests.md`):
- edcd9fe plugin code with the new test file (scratch tree from `git archive edcd9fe hermes`; one compatibility line so the helpers also set the removed `guarded` attribute): 9 failed, 7 passed for `-k "f4_ or f5_ or f6_"`. All 9 failures are behavioral (tool allowed after restart, message not refused, delivered id not recorded, exchange outlived the deadline).
- Fixed code: 16 passed for the same selection; plugin suite 105 passed.

Review 2 limits addressed: the four loopback tests that could not create sockets in the reviewer's sandbox now have socket-pair counterparts for HTTPS. The asynchronous command tests use `asyncio.to_thread`, which stalled in the reviewer's sandbox; they pass here (plugin suite 105 passed in about 28 s).
