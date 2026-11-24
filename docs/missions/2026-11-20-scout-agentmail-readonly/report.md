# Report — homelab/2026-11-20-scout-agentmail-readonly (SCOUT-MAIL-01)

Verdict: PARTIAL
Version: a1f91a8d0d011caa4d05aee40ee655cbfa8c3bd0

The verdict is PARTIAL because three required items are not verified:
- the live behavioral evaluation (AC10: no model credential was legitimately available);
- the AgentMail read smoke test (runbook step 6), after merge and deployment at the owner's call. Q1–Q3 are answered by the owner (inbox, scoped key, vault); the key scope is the owner's statement, not executor-verified;
- the independent review: review 1 (Codex, on 78ee2ee) returned F1–F3 (§K); review 2 (on edcd9fe) found F1/F2 partial and F4–F6 (§L); review 3 (on b22ba76) found F1, F2, F4 and F5 partially fixed, F3 and F6 fixed, and new F7 [blocker] and F8 [major] (§M). The owner authorized one extra cycle for F7/F8 (2026-11-23, mission.md §7). Review 4 (on 1182fb5) found F8 fixed, F7 partially fixed, and new F9 [major] and F10 [major] (§N). The owner authorized a cycle for F9/F10 and accepted the D5 residual (2026-11-23). Review 5 (on 18af837) found F9 fixed, the F10 ordering repaired, and new F11 [major]: the Retire step's `sessions list` check missed hidden and archived sessions (§O). The owner authorized cycle 6 for F11 (2026-11-23). The Version above addresses F11; it awaits review 6.

Everything else is implemented and verified offline, including on the real Hermes v0.22.5 image. Production is unchanged.

## A. Executive summary

Objective: let the owner ask Scout, in its private Telegram chat, for a French summary of the job-search mail of exactly one AgentMail inbox. Mail content must be structurally unable to reach Scout's privileged tools (Web, Kandidat, memory, skills, session search, delegation, files, shell) on that turn or any later one.

Delivered on branch `feat/scout-agentmail-readonly` (draft MR, see §F):
- a Hermes user plugin `scout_mail`, deployed and enabled in Scout's profile only, disabled by default. It provides one gateway command, `/courriels [liste|suite|aide]`, and four guard hooks, and registers no tool;
- Ansible wiring (`tasks/scout_mail.yml`, kill switch, key handling, post-restart check `hermes_checks.py scout-mail`);
- ADR-002, threat model and enforcement matrix, operator runbook;
- a standalone operator tool `scout_mail/retire.py` that retires every Scout session through the Hermes CLI (runbook §8.1, Retire);
- 151 new tests: 132 deterministic plugin tests (15 added after review 1, 16 after review 2, 8 after review 3, 12 after review 4, 7 after review 5), 8 in the real Hermes v0.22.5 image, and 11 Ansible-wiring tests (parameter cases included).

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
| New plugin tests (deterministic) | `.venv/bin/python -m pytest hermes/tests/test_scout_mail.py` | 132 passed in 31.6 s (74 before review 1, 89 before review 2, 105 before review 3, 113 before review 4, 125 before review 5) | VERIFIED |
| Real image tests (Hermes v0.22.5, `--network none`) | `hermes/tests/test_scout_mail_image.py` | 8 passed (F7 recovery and F9 short state write with Hermes' own SessionDB; F11 retirement with Hermes' own CLI) | VERIFIED |
| Ansible wiring tests (real `tasks/scout_mail.yml` on localhost, fake key) | `hermes/tests/test_scout_mail_role.py` | 11 passed | VERIFIED |
| Deploy-time check in the image (disabled / enabled / mismatch) | `hermes_checks.py scout-mail` run inside the image | "inactive everywhere" rc 0 / "active for job-search only" rc 0 / mismatch rc 1 | VERIFIED |
| Baseline, before any change (HEAD 3d7bf18) | `evidence/m3-baseline-tests.md` | 711 of 749 reported before the 25-min cap; 1 failure (`test_m5_recovery.py::test_r10_…`), not reproduced in isolation (intermittent) | PARTIAL (38 not executed) |
| Full suite after change, run 1 | `evidence/m3-post-change-tests.md` | 10 regressions from the first wiring (all reproduced), fixed (see §F) | superseded |
| Full suite after change, run 2 (code = 78ee2ee), per file | `evidence/m3-post-change-tests-2.md` | 839 collected: 809 passed, 0 failed, 30 skipped, 0 errors | superseded |
| Full suite after review 1 fixes (code = edcd9fe), per file | `evidence/m6-post-review-1-tests.md` | 854 collected: 827 passed, 0 failed, 27 skipped, 0 errors | superseded |
| Full suite after review 2 fixes (code = b22ba76) | `evidence/m7-post-review-2-tests.md`; `uv run pytest hermes/tests -q -rs -k "not (test_m7_kafeine and test_lab_)"` | 870 collected: 832 passed, 0 failed, 27 skipped, 11 deselected (hanging `test_m7_kafeine` lab, §F), 1,318 s | superseded |
| Full suite after review 3 fixes (code = 1182fb5) | `evidence/m8-post-review-3-tests.md`; same command with `ANSIBLE_LOCAL_TEMP`/`ANSIBLE_REMOTE_TEMP` in a writable scratch directory | 879 collected: 841 passed, 0 failed, 27 skipped, 11 deselected, 1,279 s, exit 0 | superseded |
| Full suite after review 4 fixes (code = 18af837) | `evidence/m9-post-review-4-tests.md`; same command and scratch temp directories | 892 collected: 854 passed, 0 failed, 27 skipped (all need image `v2026.8.18`), 11 deselected (hanging `test_m7_kafeine` lab), 1,251 s, exit 0 | superseded |
| Full suite after review 5 fixes (code = a1f91a8) | `evidence/m10-post-review-5-tests.md`; same command and scratch temp directories | 900 collected: 862 passed, 0 failed, 27 skipped (all need image `v2026.8.18`), 11 deselected (hanging `test_m7_kafeine` lab), 1,432 s, exit 0 | VERIFIED |
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
- Residual: a cancelled `/courriels` lets its worker thread finish in-flight HTTP calls. Connection (every TCP address candidate, §M F8), TLS handshake, headers and body are bounded by the 75 s deadline; name resolution is not (next item). It delivers and records nothing. A cancellation after a part was posted locks the feature down (§L).
- Residual: name resolution (`getaddrinfo`) of the two fixed hosts is a blocking libc call made before any socket exists. It is bounded by the system resolver, not by the deadline, so a hung resolver can hold the worker past 75 s. Connection attempts after it are bounded (§M F8).
- Dependency (F8): the deadline-bounded connect is installed on an httpx/httpcore internal attribute (`_pool._network_backend`), checked against httpx 0.28.1 / httpcore 1.0.9, the versions in the v0.22.5 image. If a Hermes upgrade changes that layout, every request fails closed without connecting (`test_f8_03`); re-run the plugin and image tests before any upgrade.
- Operations: the ledger grows without expiry; at capacity `/courriels` stops delivering until the operator archives it, in the order of runbook §8.1 (hold, retire every Scout session, then clear and apply). Archiving re-opens quoting of archived digests only where the marker is absent.
- Residual: the summary can be wrong or influenced by the mail. It is labeled "IA, non vérifiée" and is inert.
- Data flow: requested mail text goes to DeepSeek (Scout's existing provider). `/courriels liste` makes no model call.
- Dependency: the isolation relies on Hermes v0.22.5 plugin scoping and dispatch order. The image tests must be re-run before any Hermes upgrade.
- Busy path: a Telegram reply sent while Scout is mid-turn goes through Hermes' busy handler. That handler was not exercised end to end (no live gateway). Layer 2 (taint plus veto) covers it at unit level (`test_c5_03`).
- Not verified: the `scout_mail request …` log line landing in `profiles/job-search/logs/agent.log` (Hermes logger routing). The runbook uses it as evidence; confirm on first use.
- Availability trade-off: a corrupt or full ledger, or a lockdown (restriction or delivered id not recordable, uncertain delivery, hook fault, unwritable ledger directory), blocks Scout's tools, messages or new digests (fail closed) until the operator acts. Runbook §8 and the ordered recovery §8.1 cover it.
- Owner-accepted residual (F4/F7, D5, accepted 2026-11-23): the lockdown is written first through `taint.state`, opened and preallocated at start-up, so it holds when no file can be created or renamed and after the directory is repaired and the gateway restarted (§M F7). A state write counts only when every byte is written and read back after `fsync`; a block other than the exact armed one is restrictive and never overwritten at start-up (§N F9). If the open block cannot be written at all (I/O error, the whole volume read-only), the lockdown is held in memory only; the log line then tells the operator to retire Scout's sessions before any restart. A restart without that step lifts it, unless the failed write left the block half written. This branch is not fixed: the owner accepted it as a risk, on condition of the ordered recovery (runbook §8.1, §N F10). The plugin refuses to start when the ledger is not on the profile home's filesystem, so the transcript store would likely face the same failure; this is an argument, not a guarantee. Recovery of any lockdown requires deleting every Scout session while the protection is still in place (runbook §8.1), which loses their history unless exported.
- Recovery procedure (F10, F11): runbook §8.1 is ordered (Hold, Repair, Stage, Retire, Clear, Apply, Verify). Retire parks Scout and runs `retire.py --delete`: inventory by an unfiltered `sessions export` cross-checked with `sessions stats`, deletion by `sessions delete <id> --yes` (Hermes' guards kept), exit 0 only on an empty inventory. `test_f11_06` proves it with the pinned CLI and Hermes' own `SessionDB` on a fresh synthetic profile (hidden, archived, tool, compressed, 29 sessions, one guarded). `test_f7_05` executes §8.1 in document order with a fake CLI mirroring the pinned filters; `test_f10_01` checks the document. Not run: a live gateway, the park/unpark of Scout, production retirement. Limits of the inventory: Hermes' export reads at most 100,000 rows per call (retire.py repeats passes until empty) and may refuse a session above `sessions.max_export_messages` (default 20,000 messages); retire.py then exits 2 and the recovery stays blocked with the protection on, an owner escalation. Rows of Scout stored in another profile's store are not covered; the pinned `hermes sessions repair-profiles --json` reported no crossed rows on the synthetic lab, not checked on hermes-31. Parking (`hermes -p job-search gateway stop`) is documented from the M7 lab; unparking before the apply is an owner check on first use.
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
| Delivered code commit (Version) | `a1f91a8d0d011caa4d05aee40ee655cbfa8c3bd0` fix(hermes): retirer toutes les sessions Scout par le CLI Hermes avant la levee (F11), on top of `18af837` (review 4 fixes), `1182fb5` (review 3 fixes), `b22ba76` (review 2 fixes), `edcd9fe` (review 1 fixes) and `78ee2ee` feat(hermes): ajouter /courriels |
| Owner-input commits | `53c0f8c` chore(hermes): set the Scout mail inbox id (Q1, `test_role_04` aligned); `225fc3a` chore(hermes): provision the Scout read-only AgentMail key in the vault (Q3, encrypted file only) |
| Mission evidence commit | `1b27f9f` docs(missions): consigner la mission SCOUT-MAIL-01 et ses preuves |
| Report commits | `a9e4a81` (initial), `2a12a2a` (review 1), `97a09c4` (review 2), `e9c7a72` (review 3), `b80890a` (review 4); review 5 update follows the code commit (`a8b5347` docs(hermes) for ADR, threat model and runbook; docs(missions) for this file) |
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

Deployment readiness: ready to merge as an inert feature only after review 6 and an owner decision. Q1–Q3 are answered (2026-11-21, section I); `hermes_scout_mail_enabled` stays `false`. Enabling remains an owner decision after merge: runbook §2–§4, then the read smoke test.

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
| Review 3 fixes (F7, F8), tests, red/green comparison and full-suite run (`evidence/m8-post-review-3-tests.md`) | none (executor, Opus) |
| Review 4 fixes (F9, F10), tests, red/green comparison and full-suite run (`evidence/m9-post-review-4-tests.md`) | none (executor, Opus) |
| Review 5 fix (F11), tests, red/green comparison and full-suite run (`evidence/m10-post-review-5-tests.md`) | none (executor, Opus) |

## I. Decisions required (owner)

- D1 (Q1): ANSWERED 2026-11-21. Inbox `scout-emploi@agentmail.to`, region `api.agentmail.to` (US), confirmed by the owner's read call (HTTP 200 on `https://api.agentmail.to` for this inbox). Set as `hermes_scout_mail_inbox_id` in `hermes/ansible/group_vars/hermes/all/main.yml`, `hermes_scout_mail_enabled` kept `false`; the role host default is already `api.agentmail.to`. `test_role_04` (`hermes/tests/test_scout_mail_role.py:116`) now asserts this inbox id instead of `""`; the rest of the test is unchanged. Ansible-wiring tests rerun after the change (see owner-questions.md Q1).
- D2 (Q2): ANSWERED 2026-11-21. Dedicated key, inbox-scoped to `scout-emploi@agentmail.to`, `inbox_read` + `message_read` only, created with the owner-questions command; read call returned 200 (owner statement).
- D2b (Q3): DONE 2026-11-21. Key stored in the vault by the owner, committed encrypted (`225fc3a`).
- D3 (Q4, optional): run the live evaluation (40 calls max) before merge.
- D4: merge the draft MR after review 6; then decide on enablement (runbook §2–§4).
- D5: ACCEPTED by the owner 2026-11-23 (mission.md §7). The all-writes-fail residual (§F: lockdown held in memory until restart when even the open state block cannot be written) is an accepted risk, provided the recovery order is fixed (F10, runbook §8.1). Recorded as owner-accepted, not as fixed; unchanged by the F11 cycle.

## J. Recommended next action

Pilotage routes Codex review 6 (owner-authorized cycle 6) at the Version above. Focus: F11 (§O), `retire.py`, runbook §8.1 Retire and the inventory limits in §F. No production action is safe or authorized before merge; enabling, the live park/unpark check and the read smoke test are owner decisions after it.

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

## M. Review 3 (Codex, on b22ba76): F7 and F8, fixes, tests

Review: `review-3.md`, verdict CHANGES_REQUESTED. F3 and F6 fixed; F1, F2, F4 and F5 partially fixed, their remaining gaps being F7 and F8. Cap 3/3 reached; the owner authorized one extra cycle scoped to F7/F8 (2026-11-23, `mission.md` §7). Fixes in `1182fb53e31bb6c26268f3e7fde8bd37f874458a`. F3–F6 behaviour is kept: their tests pass unchanged except the stream injection point (below).

F7 [blocker] repaired directory plus restart lifted an unrecorded restriction (completes F1/F4).
- Finding: when both creating `taint.lockdown` and renaming the ledger failed, only `self.locked` held the refusal. After permissions were repaired and the gateway restarted, the start-up probe passed and a session whose transcript Hermes had written meanwhile (state.db in the profile home), and its compressed child, regained tools (review R7, locally and in the image).
- Fix (`taint.py` `arm`, `lockdown`, `locked`; `__init__.py` constructor and `_lockdown` log): at start-up, while the directory is proven writable, the store creates `taint.state` (one 512-byte block, written and fsynced, directory fsynced) and keeps it open for the process lifetime. Lockdown first overwrites that block with `LOCKED` through the open descriptor: no permission check on the directory or the file (checked at open time), no new name, no new block. It then also creates `taint.lockdown` when possible; the ledger rename is used only if the state block could not be written. `locked()` reads both. A restart therefore stays refused whatever was repaired in between, until the operator follows runbook §8. The plugin also refuses to start when the ledger directory is on another filesystem than the profile home, so the transcript store shares any failure the state block meets. If even the open block cannot be written, the log line says `NOT persisted: retire Scout's sessions before any restart (runbook, section 8)`.
- Recovery (runbook §8): repair, disable, delete every Scout session (`hermes -p job-search sessions delete <id> --yes`, after an optional export; affected sessions cannot be told apart), `/new`, then remove `taint.lockdown` and `taint.state`, restart, re-enable. The unwritable-directory row now requires the same session retirement before restarting.
- Tests: `test_f7_01_repaired_directory_and_restart_do_not_restore_tools` (review R7 with real 0500 permissions, a transcript row written to `state.db`, repair to 0700, real constructor, compressed history, compressed child, message refused), `test_f7_02_lockdown_holds_when_no_file_can_be_created_or_renamed`, `test_f7_03_ledger_on_another_filesystem_than_the_transcripts_is_refused`, `test_f7_04_unpersisted_lockdown_refuses_in_process_and_names_the_recovery`, `test_f7_05_operator_recovery_lifts_the_lockdown`, and in the image `test_f7_06_real_session_db_repaired_directory_keeps_tools_refused` (Hermes' own `SessionDB.append_message` while the ledger directory is 0500). VERIFIED.
- Residual: a lockdown that cannot be written even through the open block (I/O error, whole volume read-only) is held in memory; a restart before the operator retires Scout's sessions lifts it (`test_f7_04` documents the log, not a durable refusal). This is not "all fixed": it needs owner acceptance (§I D5) or a Hermes-side change.

F8 [major] TCP address candidates could outlive the deadline (completes F2).
- Finding: httpcore's default backend calls `socket.create_connection`, which tries every resolved address with the same initial timeout and no socket for the watchdog to abort; with immediate DNS, a 0.6 s remaining budget took 1.038 s over four candidates (review R8).
- Fix (`transport.py` `_deadline_backend`, `HttpxBackend.send`): the plugin installs its own httpcore network backend on the client's connection pool. It resolves once, then for each candidate: if no time is left (or the watchdog fired) it stops with `ConnectTimeout` and starts no new candidate; otherwise it creates the socket, registers it with the watchdog before `connect`, and sets its timeout to `min(operation timeout, time left)`. A connect error after the deadline maps to `BudgetExceeded`. If the httpx/httpcore internal layout is not the expected one, the request fails closed (`Unavailable`) without connecting.
- Tests: `test_f8_01_tcp_candidates_never_outlive_the_request_deadline` (review R8 shape with timeout-honouring fake sockets: under 0.75 s for 0.6 s, three attempts, the last one capped under 0.2 s, one HTTP call, zero model calls), `test_f8_02_a_refused_candidate_falls_back_to_the_next_one` (real loopback TLS, hostname verified), `test_f8_03_unknown_httpx_layout_fails_closed_without_connecting`. VERIFIED.
- Residual: name resolution itself (`getaddrinfo`) stays outside the deadline (§F). The fake sockets in `test_f8_01` honour their timeout as real sockets do; the reviewer's R8 script rerun unchanged on 1182fb5 (its fake sleeps 0.25 s whatever the timeout) gives 0.788 s for 0.6 s with 3 attempts and timeouts 0.563 / 0.312 / 0.062 s: no fourth candidate, each timeout capped by the time left; the overrun is the fake ignoring its 0.062 s timeout, which a real socket honours.

Changed existing tests: `test_f6_01` (socket-pair cases) and `test_f6_02` inject the stream by replacing `transport._deadline_backend` instead of patching httpcore's `SyncBackend.connect_tcp`; `test_f2_01`'s fake client gained the pool attribute the backend checks.

Red/green evidence (`evidence/m8-post-review-3-tests.md`):
- b22ba76 plugin code with the new tests: 5 failed, 2 passed for `-k "f7_ or f8_"`. f7_01, f7_02, f7_03: tool allowed after restart or at start; f7_04: log line only (the in-process refusal already held); f8_01: 1.04 s, 4 attempts. f7_05 and f8_02 pass on both (behaviour kept). Image: `test_f7_06` fails on b22ba76 (tool after restart None), passes on 1182fb5.
- 1182fb5: 8 passed for the same selection; plugin suite 113 passed; image tests 6 passed; full suite 841 passed, 0 failed, 27 skipped, 11 deselected.

## N. Review 4 (Codex, on 1182fb5): F9 and F10, fixes, tests

Review: `review-4.md`, verdict CHANGES_REQUESTED. F8 fixed; F7 partially fixed (original permission case repaired; all-writes-fail branch remains, now owner-accepted as D5); F1–F6 without regression. New F9 [major] and F10 [major]. The owner authorized a last cycle scoped to F9/F10 and accepted D5 (2026-11-23, `mission.md` §7). Fixes in `18af8373aca7cf18098ea55748f9f839d1b4189a`. F1–F8 behaviour is kept: all their tests pass; only `test_f7_05` was rewritten (below).

F9 [major] a short state-block write was treated as a persisted lockdown, then cleared on restart.
- Finding: `lockdown()` ignored `os.pwrite`'s byte count; a three-byte write was fsynced and reported as persisted (no `NOT persisted` warning, no rename fallback). `locked()` did not recognize the malformed block and `arm()` overwrote anything but the exact `LOCKED` block with `armed` at the next start, so after repair and restart the parent and its compressed child regained tools (review R9, locally and in the image).
- Fix (`taint.py` `_write_block`, `arm`, `_create_state`, `lockdown`, `locked`; `__init__.py` start-up log):
  - every state write goes through `_write_block`: it loops until all 512 bytes are written, treats a zero, negative or over-reported count as an I/O error, fsyncs, then reads the block back and requires it to equal what was written. Only then does the lockdown count as persisted; otherwise it falls through to `taint.lockdown`, then the ledger rename, then the `NOT persisted` log;
  - `locked()` is true for anything but the exact armed block: `LOCKED`, empty, short, malformed, longer, or unreadable state all restrict;
  - `arm()` never writes an existing block. A missing block is created in full in a temporary file, fsynced, read back and linked into place (`os.link`, which never replaces), so a crash cannot leave a half-written new block that would be read as clean;
  - the constructor logs `lockdown state present or unrecognized at start` when it starts restricted.
- Tests (plugin): `test_f9_01_short_state_writes_are_completed` (review R9 shape: every `pwrite` writes 3 bytes and says so, directory 0500, transcript row written, repair, restart, parent and compressed child refused, no `NOT persisted`), `test_f9_02_incomplete_state_write_is_not_persisted_and_stays_restrictive` (three faults: a write that stalls at 0 bytes, one that over-reports, one that fails midway; each logs `NOT persisted` and the half-written block stays restrictive after repair and restart), `test_f9_03_malformed_existing_state_restricts_and_is_kept_at_restart` (six contents: empty, `LOC`, `armed\n` unpadded, `LOCKED\n` unpadded, 512 bytes of garbage, armed block plus a trailing byte; parent and compressed child refused, message refused, file unchanged, start-up log), `test_f9_04_fresh_state_block_is_complete_and_linked_once`. Image: `test_f9_05_real_session_db_short_state_write_keeps_tools_refused` (Hermes' own `SessionDB`). VERIFIED.
- Residual: unchanged from §F (owner-accepted D5): when the block cannot be written at all and is left intact, the refusal lives in memory until restart. A write that partly lands now leaves a restrictive block instead of a clean one.

F10 [major] the recovery procedure unloaded the protection and restarted before retiring sessions.
- Finding: runbook §8 said "2. Disable (kill switch)" before "3. Retire", and §6 defines the kill switch as a replay with a gateway restart that unloads the hooks; the `NOT persisted` row pointed to the same steps. `test_f7_05` only removed marker files.
- Fix (`docs/guides/runbook-scout-mail.md`): new §8.1, strictly ordered: 1 Hold (no restart, no deployment, no replay; keep the running gateway with the plugin loaded, or park Scout with `hermes -p job-search gateway stop` if it already restarted after a `NOT persisted` log), 2 Repair, 3 Stage (commit the kill switch or revert only; nothing applied), 4 Retire (list, optional export treated as untrusted, delete every Scout session, check the list is empty), 5 Clear (markers or ledger archive), 6 Apply (the first restart: unpark if parked, then replay `--tags hermes` or restart), 7 Verify. §6 now separates staging a configuration change from the restarting apply and forbids applying before §8.1 step 4; every lockdown, `NOT persisted`, `ledger not usable`, corrupt and full-ledger row points to §8.1. ADR-002 and matrix T13 aligned.
- Tests: `test_f7_05_operator_recovery_in_runbook_order_never_hands_tools_to_an_old_session` reads §8.1's step names and executes them in document order against a synthetic `state.db`: after each step, every remaining session must be refused by a loaded plugin; Clear and Apply assert that the sessions were already retired; the Apply step models the hooks as gone. Then a fresh session gets tools. `test_f10_01_runbook_recovery_retires_sessions_before_unloading_or_restarting` checks the step order, that no step before Apply contains a replay, restart or unpark, that Retire deletes sessions and Clear removes `taint.state`, the §6 staging/applying split, and that no lockdown row still says "steps 1–3" or "Disable the feature". VERIFIED (document and synthetic execution; not run against a live gateway or Hermes' CLI).

Red/green evidence (`evidence/m9-post-review-4-tests.md`):
- 1182fb5 plugin code and f55c226 runbook with the new tests, `-k "f7_ or f8_ or f9_ or f10_"`: 12 failed, 8 passed. Failed: `test_f9_01` (block not recognized as locked), the three `test_f9_02` cases (no `NOT persisted` warning), the six `test_f9_03` cases (tools allowed after restart), `test_f7_05` and `test_f10_01` (no ordered §8.1). Passed on both: f7_01–f7_04, f8_01–f8_03, `test_f9_04` (fresh block, behaviour kept). Image: `test_f9_05` fails on 1182fb5 (`state_locked` False), 6 others pass.
- 18af837: 20 passed for the same selection; plugin suite 125 passed; image tests 7 passed; review R9 script rerun verbatim: `state_recognized_locked= True`, parent and child blocked after restart; full suite 854 passed, 0 failed, 27 skipped, 11 deselected (892 collected).

## O. Review 5 (Codex, on 18af837): F11, fix, tests

Review: `review-5.md`, verdict CHANGES_REQUESTED. F9 fixed; F10 ordering repaired; F1–F8 without regression; D5 owner-accepted, not raised. New F11 [major]. The owner authorized cycle 6 scoped to F11 (2026-11-23, `mission.md` §7). Fix in `a1f91a8d0d011caa4d05aee40ee655cbfa8c3bd0`, documentation in `a8b5347`. F1–F10 behaviour and D5 unchanged: the plugin modules are untouched; only `test_f7_05`, `test_f10_01` and the role file list changed (below).

F11 [major] the Retire step's empty-list check did not prove that every Scout session was retired.
- Finding: `hermes -p job-search sessions list` calls `list_sessions_rich` without archived or hidden rows, excludes `source=tool` rows and stops at 20. With a fully persisted lockdown, a hidden and an archived mail-derived session survived "No sessions found."; after Clear and Apply the hidden session and its compressed child had no tool veto (review R11, real CLI and SessionDB). `test_f7_05` deleted rows by SQL and could not see it.
- Fix: `hermes/ansible/roles/hermes_agent/files/plugins/scout_mail/retire.py`, a standalone operator tool deployed with the plugin and never imported by it (standard library only):
  - inventory = `hermes -p job-search sessions export - --format jsonl` without filter (every row: any source, hidden, archived, compression lineage; 100,000-row bound per call). Each line must be a JSON object with an id and an archived flag; non-archived rows must equal `sessions stats` "Total sessions" exactly, and an empty export needs "Total messages: 0". Any failed command, non-JSON line (export refused) or disagreement = not authoritative, exit 2, nothing deleted;
  - retirement = `sessions delete <id> --yes` per id, so Hermes' active-turn and compression-lock guards apply; refusals are reported and never bypassed (no `--force`, no SQL). Passes repeat on a fresh inventory until it is empty (exit 0) or a pass removes nothing (exit 2, protection kept). Inventory mode lists ids (exit 0 empty, 3 sessions remain). Only ids and counts are printed; the exported text stays in memory;
  - runbook §8.1 Retire: park Scout, then `sudo docker exec -u 1000 hermes python3 /opt/data/profiles/job-search/plugins/scout_mail/retire.py --delete`; exit 0 is the only pass to Clear and Apply. Verify uses the inventory mode. §1, §6, ADR-002 and matrix T13 aligned.
- Tests (plugin, fake CLI mirroring the pinned filters): `test_f11_01_inventory_sees_what_sessions_list_hides` (29 sessions, `sessions list` shows 20 and none of hidden/archived/tool), `test_f11_02_delete_retires_every_row_and_proves_the_store_empty` (50 sessions), `test_f11_03_guarded_session_is_refused_not_bypassed_and_protection_kept`, `test_f11_04_non_authoritative_inventory_fails_closed_before_any_delete` (export refused, export missing a row, messages without sessions), `test_f11_05_profile_without_store_is_an_empty_inventory`. Image: `test_f11_06_real_cli_retires_hidden_archived_tool_and_compressed_sessions` (pinned CLI and SessionDB; values in the evidence file). `test_f7_05` now executes the Retire step the runbook prescribes, through the CLI. VERIFIED on synthetic profiles; not run on hermes-31.

Red/green evidence (`evidence/m10-post-review-5-tests.md`):
- 18af837 code and 4b7f403 runbook with the new tests, `-k "f7_ or f8_ or f9_ or f10_ or f11_"`: 9 failed, 18 passed. With only `retire.py` added to that tree: 2 failed; `test_f7_05` runs the old list-driven Retire and fails with `step Apply: old session S-ARCHIVED would get tools`. Image: `test_f11_06` fails on 18af837 (`retire.py` missing, after showing the real `sessions list` hiding S-HIDDEN, S-ARCHIVED, S-TOOL, the compression parent and rows past 20), 7 others pass.
- a1f91a8: 27 passed for the same selection; plugin suite 132 passed; image tests 8 passed; role tests 11 passed; full suite 862 passed, 0 failed, 27 skipped, 11 deselected (900 collected).
