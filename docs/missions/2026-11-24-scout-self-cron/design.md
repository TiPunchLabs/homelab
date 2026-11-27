# Design — Scout manages its own scheduled tasks (E0)

Mission: `homelab/2026-11-24-scout-self-cron`. Step E0: read-only discovery and design. Nothing was implemented, deployed or committed. Executor model: Claude Opus 5.5 (`claude-opus-5-5`); no subagent was used in E0.

Sources:

- Hermes v0.22.5: `/opt/hermes` copied out of the local image `nousresearch/hermes-agent:v0.22.5` (id `49b70739d2e8`) into the session scratchpad. Paths below are relative to `/opt/hermes`.
- This repository at `975e302` (branch `feat/scout-self-cron`).
- hermes-31, read-only: `ls`/`test` on Scout's `cron/` directory, and a Python one-liner inside the container that printed only the keys `timezone`, `approvals`, `cron`, `command_allowlist`, `memory`, `plugins.enabled` and a boolean for `cronjob in agent.disabled_toolsets`. The environment hint, `.env` files and secrets were never read.

## 1. Findings

### 1.1 Live state on hermes-31 (2026-11-24, about 15:27 host time)

- `/opt/hermes/data/profiles/job-search/cron/`: `executions.db`, an empty `output/`, lock files, and a live `ticker_heartbeat` and `ticker_last_success` (the profile's ticker runs). No `jobs.json`, so Scout has no jobs. The `default` and `cafe-ia` profiles have no `jobs.json` either. No `ESTOP`.
- Scout's `config.yaml`: `timezone`, `approvals`, `cron`, `command_allowlist` and `memory` are all unset, so Hermes defaults apply. `plugins.enabled: [scout_mail]`. `cronjob` is in `agent.disabled_toolsets`.
- `default` (Nora): `cron.catch_up_missed: true`, `memory.write_approval: true`. `cafe-ia`: none of these keys is set.
- The managed `/etc/hermes/config.yaml` sets only `dashboard`, `model` and `providers`: no `timezone`, no `approvals`, no `cron`.

### 1.2 Corrections to the pilot's context

- `session_search` IS already in Scout's cron toolsets, together with `todo` and `clarify` (`hermes/ansible/group_vars/hermes/all/main.yml:297-304`).
- Scout has NO `memory.write_approval`. Only Nora sets it (`main.yml:441`). Scout inherits the default `False` (`hermes_cli/config_defaults.py:1332`), confirmed live (`memory: null`). So today a Scout session, a cron run included, writes `MEMORY.md`/`USER.md` without approval, and those files are injected into every Scout session. This is pre-existing. It becomes an unattended, recurring path once jobs exist (see D9).
- The model-facing tool is `cronjob_manage`, in toolset `cronjob` (`tools/cronjob_tools.py:1192`).
- The role README sections « Cron safety » (`hermes/ansible/roles/hermes_agent/README.md:249`) and « Cron drafts (M4.4, not created) » (`:1225`) describe v0.20.4 and hermes-30. The restart rules still hold on v0.22.5 (§1.8); the M4.4 procedure does not.

### 1.3 The `cronjob_manage` tool (v0.22.5)

- Actions: `create`, `list`, `update`, `pause`, `resume`, `remove`, and `run` (aliases `run_now` and `trigger`). `run` fires the job immediately in the background (`tools/cronjob_tools.py:753`, `:958`).
- Fields the model can set (`_HANDLER_FORWARDED_ARGS`, `:1170`): `job_id`, `prompt`, `schedule`, `name`, `repeat`, `deliver`, `failure_deliver`, `skill`/`skills`, `reason`, `script`, `context_from`, `continuity`, `enabled_toolsets`, `workdir`, `no_agent`, `attach_to_session`, `paused_reason`, `pinned`, plus `monitor`. The handler does not forward `model`, `provider` or `base_url`: the model cannot change which model a job runs on (`:1167-1169`).
- A job stores its own `enabled_toolsets`, `skills`, `script`, `workdir`, `context_from`, `deliver`, `origin` and optional model pin (`:642-700`).
  - A per-job `enabled_toolsets` REPLACES `platform_toolsets.cron` (`cron/scheduler.py:456`).
  - `agent.disabled_toolsets` is applied afterwards (`cron/scheduler.py:414`).
  - So a job can widen up to anything not on the denylist. For Scout that means `kandidat_confirm`, `browser` and the MCP union. `kandidat_confirm` would still be refused in cron: there is nobody to approve its calls.
- Only defence in the tool: `_scan_cron_prompt`, a short set of English regexes (`tools/cronjob_prompt_scan.py:27`). It has no size limit and no French patterns. It is not a boundary.
- `check_cronjob_requirements` (`:1151`) exposes the tool to any gateway, interactive or cron session. Platform scoping must come from config.

### 1.4 Schedules and timezone

- `parse_schedule` (`cron/jobs.py:783`) accepts:
  - intervals (`30m`, `every 2h`);
  - one-shots (`in 30m`, ISO timestamps);
  - natural phrases (`weekdays at 9am`);
  - 5-field cron expressions.
- Cron expressions and naive timestamps are read in the profile's configured timezone. `hermes_time._resolve_timezone_name` (`hermes_time.py:83`) reads `HERMES_TIMEZONE`, then the PROFILE's `config.yaml` `timezone` (managed scope included), then server time. Under the multiplexed gateway `HERMES_TIMEZONE` only speaks for `default`, so every routed profile reads its own config.
- Scout has no `timezone`, so `0 7 * * 1-5` means 07:00 UTC (03:00 in Guadeloupe). This repeats the trap recorded on hermes-30.

### 1.5 Storage and delivery

- Jobs live in `<profile home>/cron/jobs.json` (`cron/jobs.py:90`), per profile. Outputs go to `cron/output/`, runs to `cron/executions.db`.
- `deliver` (schema `:1056`):
  - omitted or `origin` means the creating chat, captured from `HERMES_SESSION_PLATFORM`/`HERMES_SESSION_CHAT_ID` (`tools/cronjob_job_args.py:59`). No origin is recorded on api_server, which has no async delivery;
  - otherwise `local`, `all`, `bot-chat[:profile]`, or an explicit `platform:chat_id[:thread]`.
- At create time only `bot-chat` targets are validated. Any `telegram:<chat>` is accepted and sent by the profile's bot when the job fires.

### 1.6 Enforcement points available

- `pre_tool_call` plugin hook (`hermes_cli/plugins.py:1941`). It receives `tool_name`, `args` and `session_id`, and fires in every session, cron runs included. Three directives are available:
  - `block` vetoes the call;
  - `modify` rewrites the arguments;
  - `approve` sends ANY tool call to the human approval gate.
  - Precedence is `block` > `approve` > none. So scout_mail's veto in a tainted session wins over an approval request (#87420).
- The approval gate, `tools.approval.request_tool_approval` (`tools/approval.py:1121`), is reached through `_resolve_block_from_details` (`hermes_cli/plugins.py:2021`).
  - It is the same gate as dangerous shell commands: it blocks the agent thread until the owner taps a button or types `/approve` or `/deny`, and times out to deny after 300 s.
  - It runs no LLM guardian on this path (`_run_approval_gate`, `tools/approval.py:968`).
  - With no human present it fails closed: cron uses `approvals.cron_mode: deny` (`hermes_cli/config_defaults.py:1695`).
  - Three bypasses exist: `/yolo` for the session, `approvals.mode: off`, or a previous `session`/`always` grant on the same `rule_key`. An `always` grant is written to the profile's `command_allowlist` (`_persist_choice`, `tools/approval.py:401`).
- The Telegram approval card shows the reason in at most 500 characters (`plugins/platforms/telegram/adapter.py:4231`), and its "command" line is a fixed label (`<cronjob_manage> (plugin approval rule)`). The card alone cannot show the full instructions.
- `ctx.post_message(text)` (`hermes_cli/plugins.py:615`) posts into the conversation bound to the current turn, a hook running in that turn included. It is refused in cron and outside a session (`hermes_cli/plugin_messages.py:5`). So code, not the model, can show the owner the exact text that will be saved.
- `ctx.current_cron_execution()` (`hermes_cli/plugins.py:410`, `cron/execution_identity.py:51`) gives the running job's id and name in a cron run, and `None` everywhere else. The model cannot spoof it: it is a ContextVar.
- Session identity for hooks: `HERMES_SESSION_PLATFORM`, `_CHAT_ID`, `_CHAT_TYPE`, `_USER_ID`, `_PROFILE` and `HERMES_CRON_SESSION` (`gateway/session_context.py:41-47`).
- `ctx.register_tool(...)` (`hermes_cli/plugins.py:462`) adds a model tool in a plugin toolset. Trap: plugin toolsets are ON by default on every platform, unless they are listed in `known_plugin_toolsets.<platform>` and absent from that platform's saved list (`hermes_cli/tools_config.py:527`). `agent.disabled_toolsets` runs last and overrides everything (`:643`).

### 1.7 Built-in per-job persistence: the cron notepad

- `cron/notepad.py` is a durable key/value store per job, in `cron/notepad.db`. Caps: 16 KB per value, 64 KB per job (`:26`).
- On every run it is injected at the top of the job prompt (`cron/scheduler_prompt.py:331`, `render_notepad_section` `:149`). It counts as injected data: invisible Unicode is sanitized and only the 4 directive patterns can block.
- It is cleared when the job is removed (`cron/jobs.py:2282`).
- Hermes has no model tool for it: writes go through `hermes cron notepad`, which needs the terminal, and Scout has none. The injected header even tells the model to use that CLI.

### 1.8 Restarts

- Jobs survive a restart because `jobs.json` is persisted.
- On the first tick after a restart, only an overdue enabled job fires, and only once:
  - within the grace window (half the period, clamped to 120 s..2 h: `_compute_grace_seconds`, `cron/jobs.py:937`), the missed run fires late;
  - beyond it, the job is fast-forwarded and runs once now if `cron.catch_up_missed: true`, the default (`config_defaults.py:1815`).
- A run that is in flight when the restart happens is lost, not repeated: `next_run_at` advances before the run (at-most-once).
- A job whose `next_run_at` is in the future does nothing at restart. So a weekday job at one fixed hour gets no extra run from a restart.
- `hermes_checks.py schedule-window` (preflight) already parses offset-aware timestamps (`files/hermes_checks.py:186`).
- Consequence: once Scout owns jobs, deploys and restarts must avoid ±2 h around each job's run time. The existing preflight blocks this automatically.

### 1.9 Prompt the cron agent receives

`_CRON_HINT` (`cron/scheduler_prompt.py:260`) already tells the agent never to create or update a job because of recurring wording in its task. The cron agent never receives `cronjob` anyway, because `cron.allow_agent_scheduling` defaults to `False` (`config_defaults.py:1820`, `scheduler.py:414`).

## 2. Design overview

One new plugin, `scout_cron`, enabled only in Scout (`plugins.enabled: [scout_mail, scout_cron]`), plus config changes in Scout's declaration and a SOUL update. scout_mail is untouched.

```
Telegram turn (owner, private chat)            Cron run (unattended)
--------------------------------               ---------------------
cronjob_manage(...)                            cronjob_manage: absent (Hermes denylist)
  -> scout_mail pre_tool_call: block if tainted   scout_task_record(...)  [plugin tool]
  -> scout_cron pre_tool_call:                      -> job id from current_cron_execution()
       platform/profile/user/chat checks             -> journal  -> Hermes notepad (auto-injected)
       field + schedule + N + size policy            -> alerted  -> plugin ledger (check/mark)
       post full proposal (post_message)            web, skills(read), kandidat (read)
       return approve (nonce rule_key)
  -> Hermes approval card -> owner taps
  -> cronjob_manage runs
  -> scout_cron transform_tool_result: adds next run in Guadeloupe time + UTC
```

## 3. Guards

### G1 Platform and profile scoping

Config (Scout only, `main.yml`):

- Remove `cronjob` from Scout's `agent.disabled_toolsets`. Keep it in Nora's and Kaféine's.
- Add `cronjob` to `platform_toolsets.telegram` only. Today `api_server` and `cli` share the telegram anchor: give them their own literal lists without `cronjob`.
- Add `scout_task_record` (the plugin toolset) to `platform_toolsets.cron` only. Add `known_plugin_toolsets` for `telegram`, `api_server` and `cli` containing `scout_task_record`, so the default-on rule does not expose it there.
- Leave `cron.allow_agent_scheduling` unset (false). Hermes then strips `cronjob` from every cron run, per-job `enabled_toolsets` included.

Plugin, defence in depth: `pre_tool_call` on `cronjob_manage` blocks unless all of these hold:

- profile is `job-search`;
- `current_cron_execution()` is `None` and `HERMES_CRON_SESSION` is empty;
- `HERMES_SESSION_PLATFORM == telegram` and `HERMES_SESSION_CHAT_TYPE` is private;
- `HERMES_SESSION_USER_ID` and `HERMES_SESSION_CHAT_ID` are in the owner allowlist (settings rendered from `hermes_telegram_allowed_users`).

The record tool's handler refuses unless `current_cron_execution()` is set and the profile is `job-search`.

Deploy check: extend `hermes_checks.py`. Per profile and platform, `cronjob_manage` must be exposed only on job-search/telegram, `scout_task_record` only on job-search/cron, `cron.allow_agent_scheduling` must not be true anywhere, and `scout_cron` must be enabled only for job-search. It reuses the existing tool-by-tool exposure check of `profile.yml`.

### G2 Owner confirmation (code-enforced)

For `create`, `update`, `remove` and `resume`, plus `feedback` (D10), the plugin:

1. Resolves the target job (`resolve_job_ref`) and validates the request (G3).
2. Posts a French proposal with `ctx.post_message`, built from the ARGUMENTS, not the model's prose:
   - action and name;
   - schedule as given, next three runs in Guadeloupe time and UTC (computed with `croniter`);
   - delivery: « conversation privée du propriétaire »;
   - the full instructions verbatim, or for an update a before/after of each changed field;
   - character count and sha256 prefix.
   It is ONE Telegram message, never split (correction 5, review 4 F9): `check_post` checks the whole post against Hermes' whole-message predicates and a size bound under Hermes' 4,096-unit chunker; a post that fails is refused before it is posted and before the card.
3. Returns `{"action": "approve", "message": <≤ 450 chars: action, name, schedule, sha256 prefix>, "rule_key": "scout_cron:<random nonce>"}`. The nonce makes `session` and `always` grants unusable for any later call.
4. Blocks instead of approving if `/yolo` or `approvals.mode: off` is active (`tools.approval._yolo_active`, `approval_context._get_approval_mode`), or if the proposal could not be posted. It fails closed.

No tap means nothing is saved: deny or timeout returns a refusal to the model.

- `list` and `pause` need no confirmation (read, or safe direction).
- `run`, `run_now` and `trigger` are blocked (D6).

Approval is answered by the Telegram button, which only allowlisted users can press. The model cannot answer it.

Prompt-only part (SOUL): before calling the tool, Scout should state in its own words what it is about to save and ask for confirmation. This is a usability layer; the gate does not depend on it.

### G3 Limits (code-enforced in `pre_tool_call`)

- At most N jobs in Scout's `jobs.json`, paused ones included, with N = 5 by default (D4). Create is refused when count ≥ N. A per-process lock plus an in-flight counter covers two creates in the same turn.
- At most one run per day per job. The schedule must parse (Hermes `parse_schedule`) to `kind == "cron"`, with the minute and hour fields single integers (no `*`, `,`, `-`, `/`). Day-of-month, month and weekday are free. Intervals and one-shots are refused (D5). The natural forms (`weekdays at 7am`) parse to cron and pass.
- Delivery: `deliver` must be omitted or equal `origin`. G1 guarantees that origin is the owner's private chat. `failure_deliver` is refused. Any explicit `telegram:...`, `all`, `local` or `bot-chat` is refused.
- Size: prompt ≤ 2,650 characters and name ≤ 80, both as displayed in Telegram (UTF-16 units, `\` and `` ` `` counted twice), schedule expression ≤ 40, so that the worst-case proposal is one message (correction 5; was 6,000, splitting removed). The owner's real request is about 3.4 k characters of conversation; Scout must condense the saved instructions. Create is refused if a job with the same name exists, so Scout must update in place.
- Refused fields on create and update: `script`, `no_agent`, `workdir`, `monitor`, `context_from`, `continuity`, `enabled_toolsets`, `skills`/`skill`, `attach_to_session`, `pinned`, `repeat`, `paused_reason`. The model cannot set `model`, `provider` or `base_url` anyway.
- Per-run cost bound (D11): in cron, the plugin counts tool calls per `execution_id` and blocks beyond a cap (proposal: 40 calls, of which at most 20 `web_search`/`web_extract`). The dedicated Tavily key's monthly limit remains the outer bound.

### G4 Mail-tainted sessions

Already true: scout_mail's `pre_tool_call` blocks every tool in a tainted session, and `block` beats `approve` in Hermes. E2 adds a test with both plugins loaded: a tainted session calls `cronjob_manage` create, the call is blocked, no proposal is posted and nothing is saved. One property is proved separately: scout_cron must not post the proposal before knowing it will not be blocked. Hermes calls every hook, so the order of plugins matters. Mitigation: scout_cron reads scout_mail's taint state through its public check, or posts only when no other hook vetoes; this is resolved in E1 and tested.

### G5 Persistent per-task record and deduplication, unattended

Plugin tool `scout_task_record`, cron only, job id taken from `current_cron_execution()`, never from the model. Actions:

- `journal_set(text)`: writes Hermes notepad key `journal` for the running job, at most 3000 characters (plugin cap, below Hermes' 16 KB). Hermes injects it at the start of every run, so it is read automatically. It goes away with the job.
- `check_alerted(urls[])` and `mark_alerted(items[{url, title}])`: a plugin-owned ledger `plugin-data/scout_cron/<job_id>.json` (0600). It stores normalized URLs (tracking parameters stripped) hashed to 16 hex characters, plus date and a short title. Entries older than 180 days are pruned and there is a hard cap. Ledger files are deleted in a `post_tool_call` hook when a `remove` succeeds.
- `journal_get` and `alerted_count`: read-only.

The tool adds no approval step, no terminal, no files and no Kandidat write.

Telegram-side read access for the owner: `scout_task_record` stays cron-only. The plugin registers `/taches-scout <name>`, a slash command run by the gateway before any agent turn, which shows a job's journal and ledger count to the owner.

### G6 No regression

- Nora's and Kaféine's declarations are unchanged.
- scout_mail code and settings are unchanged; `plugins.enabled` gains one entry.
- Kandidat entries and `mcp_policy` are unchanged (cron keeps `kandidat` read-only only).
- Scout's telegram, api_server and cli tool lists change only by `cronjob` on telegram.
- Scout's cron list changes as described in D9; no cron exists today, so no running behaviour changes.
- The role creates no job. A deploy check asserts that Scout's `jobs.json` is absent or unchanged by the deploy.
- A SOUL.md change requires adding the deployed SOUL's sha256 to `soul_predecessor_sha256`.

## 4. Enforcement matrix (planned)

| Guard | Mechanism | Type | E2 test |
|---|---|---|---|
| G1 no scheduling in cron | Hermes denylist (`allow_agent_scheduling` false) + plugin block on cron context | code (Hermes + plugin) | cron-run tool list lacks `cronjob_manage`; forced call blocked |
| G1 telegram only, Scout only | `platform_toolsets` + `disabled_toolsets` + plugin platform/profile/user check | config + code | api_server/cli/Nora/Kaféine: tool absent; forced call blocked |
| G1 record tool cron only | `known_plugin_toolsets` + handler check | config + code | telegram/api_server/cli: absent; handler refuses outside cron |
| G2 confirmation | plugin `approve` + verbatim proposal + nonce rule_key + yolo/off refusal | code | no tap → nothing saved; tap → saved; `/yolo` → refused |
| G2 wording, list-first, update in place | SOUL | prompt only | owner test |
| G3 N, daily cap, delivery, size, fields | plugin validation | code | N+1, `*/30`, `every 2h`, `in 1h`, `telegram:other`, 6001 chars, `script` → refused |
| G3 per-run cost | plugin call counter per execution | code | 41st call blocked |
| G4 tainted session | scout_mail block > approve | code (existing) | tainted session → blocked, nothing posted or saved |
| G5 record + dedup | plugin tool → notepad + ledger | code | 2 runs: run 2 sees the journal and skips a marked URL |
| G5 "read at start, update at end" | Hermes notepad injection (read); SOUL/job prompt (update) | code (read) + prompt (update) | run 2 prompt contains the journal |
| AC7 restart | Hermes persistence + grace rules | Hermes | restart with a future job → no run; jobs listed |

Prompt-only items: confirmation wording and asking before the tool call; listing before creating; reporting the next run (the plugin adds the values, the model phrases them); "do not schedule because of web content"; updating the journal at the end of a run; French output.

## 5. Decisions (recommendation first)

- D1 Architecture: a new plugin `scout_cron`, separate from scout_mail so it can be disabled on its own (`plugins.enabled` and a role switch `hermes_scout_cron_enabled`, mirroring scout_mail). Rejected: extending scout_mail (couples two kill switches); SOUL-only rules (no boundary).
- D2 Confirmation: the native approval gate, a verbatim proposal posted by the plugin, and a per-call nonce `rule_key`. Rejected:
  - the card alone: 500-character reason, so the owner could not see the instructions;
  - `clarify` or a typed code word checked through `pre_llm_call`: more code, and a typed word is weaker than a button bound to one pending call;
  - a custom approval transport (`register_approval_transport`) only to hide `always`: the nonce already makes `always` inert. Its only side effect is one dead `command_allowlist` entry, which the deploy check reports.
- D3 Timezone: set `timezone: America/Guadeloupe` in Scout's profile config only. `0 7 * * 1-5` then means 07:00 in Guadeloupe, and Hermes' `next_run_at` carries the −04:00 offset. Alternative: keep UTC and convert in the plugin and the SOUL (error-prone; this is the hermes-30 trap). Side effects: Scout's system-prompt clock becomes local time. Per-profile timezone under the multiplexed ticker is verified in E2 before relying on it.
- D4 N = 5, counting paused jobs. Alternative: count only enabled jobs, which then needs the cap re-checked on `resume`.
- D5 Schedules: cron kind with one fixed minute and hour only. Alternative: also allow one-shot timestamps (`once`) under the same cap.
- D6 `run`/`run_now`/`trigger` are blocked. Alternative: allow them with approval, counted against the daily cap. The owner's flow does not need them.
- D7 Field policy: as in G3, `attach_to_session` refused. Alternative: allow it, so replies to an alert continue the job's thread. It is not needed for feedback (D10).
- D8 G5 mechanism: plugin tool, with the journal in the Hermes notepad and the alerted ledger plugin-owned. Rejected:
  - memory: global to all Scout sessions, and unapproved for Scout;
  - `continuity`: injects the first 8000 characters of the last output file, stale from run 3 (README `:1247`);
  - `session_search` only: fuzzy, and see D9;
  - Kandidat writes: forbidden.
- D9 Narrow Scout's cron toolsets to `web`, `skills`, `kandidat` and `scout_task_record`, removing `memory`, `session_search`, `todo` and `clarify`:
  - `memory`: unapproved writes would carry text from untrusted pages into every Telegram session;
  - `session_search`: it reads private conversations and mail-tainted transcripts. Tainted text reaching a cron run makes scout_mail taint that run and block all its tools;
  - `clarify`: Hermes already denies it in cron;
  - `todo`: harmless, but unused.
  Alternative: keep the current list. Owner decision, because it changes Scout's capability.
- D10 Owner feedback ("use my Telegram feedback to refine ranking"): `scout_task_record` gets one Telegram action, `feedback_add(job, text)`. It is under the same G2 approval with the verbatim text, capped at 1500 characters, and stored in notepad key `feedback`, which is injected into the next runs. Alternative: feedback only by updating the job's instructions (no new action, but the prompt grows). This makes the record tool exist on Telegram for that one action. G1 then reads: the record tool's write actions are telegram/`feedback_add` under approval and cron/journal+ledger.
- D11 Per-run tool-call cap in cron: 40 total, 20 web calls. Alternative: no cap; Tavily's monthly limit only.
- D12 `cron.catch_up_missed`: keep the default `true` (one late run after an outage, never several). Alternative: `false`, which drops runs missed by more than 2 h.
- D13 Runbook language: English only, the repo convention (`docs/guides/runbook-scout-mail.md`). The mission allowed either.

## 6. Residual risks (stated, not solved)

- Injection at run time: a page fetched during an approved run can still steer that run. Its effects are bounded: tools are read-only apart from the journal and the ledger; at most 40 calls; delivery only to the owner. The run can leak the private context (`agent.environment_hint`) through search queries or fetched URLs. That leak already exists in every Telegram session with web tools; scheduling makes it unattended and recurring.
- Journal persistence: a run can write steering text into its own journal, read by later runs of that job only. Bounded at 3000 characters, visible to the owner via `/taches-scout`, and deleted with the job.
- Hermes' injection scanner is English-only and has no size limit; it is not relied upon.
- The Hermes internals used depend on v0.22.5: `current_cron_execution`, `post_message`, the approve directive, `_yolo_active` and the approval mode reader. Tests pin them against the image; an upgrade must re-run E2.

## 7. Open points to verify in E2 (no assumption made)

- Whether plugin `check_fn` and tool-definition caching interact with cron context. The handler check is the boundary whatever the result.
- Whether `post_message` succeeds from a `pre_tool_call` hook in a gateway turn, ordered before the approval card.
- Whether the multiplexed ticker honours Scout's own `timezone`.
- That `pre_tool_call` fires in cron runs for plugin tools and MCP tools.
- The approval timeout behaviour, and that the gateway refuses `/approve` from a non-allowlisted user.

## 8. E1 work list (after go)

- `files/plugins/scout_cron/`: `plugin.yaml`, `__init__.py`, `policy.py` (validation), `ledger.py`, `settings.json` template (owner ids, N, caps).
- `tasks/scout_cron.yml`: deploy or remove, like `tasks/scout_mail.yml`.
- group_vars: Scout's tool lists, `disabled_toolsets`, `known_plugin_toolsets`, `timezone` (D3), `plugins.enabled`, and the switch `hermes_scout_cron_enabled`.
- SOUL.md for job-search: replace « ni tâches planifiées ... tu ne peux pas en créer » with the scheduling rules (French), and add the predecessor sha256.
- `hermes_checks.py`: a `cron-policy` mode (G1 exposure, G3 conformity of existing jobs, names and schedules only, never prompts).
- Tests (E2), runbook (E4), README M4.4 section rewrite.
