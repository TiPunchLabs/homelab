# Runbook — Scout's own scheduled tasks (`scout_cron`, SCOUT-CRON)

In his private Telegram chat, the owner asks Scout to create, update, list, pause, resume or delete Scout's own scheduled tasks (for example a weekday job alert). Every change that saves something needs an approval tap. Design and threat model: `docs/missions/2026-11-24-scout-self-cron/design.md`. Report and evidence: `docs/missions/2026-11-24-scout-self-cron/report.md`.

## 1. What gets deployed

| Item | Value |
|---|---|
| Plugin code | `hermes/ansible/roles/hermes_agent/files/plugins/scout_cron/` → `/opt/hermes/data/profiles/job-search/plugins/scout_cron/` (owner hermes, 0644) |
| Settings | `settings.json` in the same directory, rendered by `tasks/scout_cron.yml` (0640): `enabled`, `profile`, `owner_user_ids` (from `hermes_telegram_allowed_users`), `display_timezone` (`hermes_timezone`), `limits` |
| Switch | `hermes_scout_cron_enabled` (group_vars). Must agree with `plugins.enabled` of Scout and with the `tools.override` grant below. Off requires `cronjob` back in Scout's `agent.disabled_toolsets` and no grant, and `cron.allow_agent_scheduling` stays false: the role refuses otherwise |
| Scout config | `plugins.enabled: [scout_mail, scout_cron]`; `plugins.entries.scout_cron.granted_capabilities: [tools.override]` (lets the plugin replace `cronjob_manage` in Scout's profile only; without it the plugin refuses every scheduling change); `timezone: America/Guadeloupe` (Scout only); `cronjob` and `scout_task_record` on `platform_toolsets.telegram` only; `platform_toolsets.cron: [web, skills, kandidat, scout_task_record]` (no memory, no session_search); `known_plugin_toolsets.{api_server,cli}: [scout_task_record, cronjob]` and `known_plugin_toolsets.cron: [cronjob]` (a plugin toolset is on by default where it is not "known"; the override makes `cronjob` one); `cronjob` removed from `agent.disabled_toolsets` |
| SOUL.md (Scout) | Section « Tâches planifiées »; predecessor hash `7dc753fe…` (live on 2026-11-24) added so `default_soul.yml` replaces it once |
| Runtime data | Jobs: `profiles/job-search/cron/jobs.json` (Hermes). Journal and owner feedback: Hermes cron notepad `profiles/job-search/cron/notepad.db`, keys `journal` and `feedback`. Alerted-vacancy ledger: `profiles/job-search/plugin-data/scout_cron/ledger/<job_id>.json` (0600, 16-hex URL hashes, date, short title) |
| Exposed to the owner | `/taches-scout [nom ou id]` (read-only: jobs, next run, journal, feedback, ledger count) |
| Exposed to the model | Telegram: `cronjob_manage` (Hermes' schema; in Scout's profile its handler is scout_cron's `manage`, which re-checks the approved call and then calls Hermes' own handler) and `scout_task_record` (`feedback_add` only). Cron run: `scout_task_record` (journal, alerted ledger). Nothing on api_server, cli, Nora or Kaféine |
| Created by the deploy | No job. The role never creates, edits, pauses or runs a job |

## 2. Guards and how they are enforced

| Guard | Enforcement | Code or prompt |
|---|---|---|
| G1 scheduling only in the owner's private Telegram chat, Scout only | Per-platform tool lists; Hermes strips `cronjob` from every cron run; plugin refuses outside the owner's private chat, on another profile and in any cron context | code |
| G1 a scheduled run never schedules | Hermes cron denylist (`cron.allow_agent_scheduling` false) + plugin block in cron context | code |
| G2 owner approval for create, update, remove, resume, feedback | The plugin posts the exact text to be saved (full effective instructions, schedule in Guadeloupe time and UTC, delivery; changed and unchanged fields for an update), then sends the call to Hermes' approval gate (button; 300 s; silence = refusal) with a single-use rule key. `/yolo` or `approvals.mode: off` → refused | code |
| G2 the approval covers that exact change | The approval is bound to the tool call, the immutable job id, a fingerprint of the job shown and the canonical arguments. After the tap, `manage` re-checks context, `/yolo`, the other plugins' veto (scout_mail), the policy and the binding, then hands Hermes only the canonical arguments (job id, never a name). Anything changed meanwhile (job renamed, edited, removed; other arguments) → nothing saved, the owner gets a new proposal on the next request. A saved job that differs from the approval is paused at once | code |
| G2 summary before the tool call, list before create | SOUL | prompt |
| G3 ≤ 5 jobs (paused included), ≤ 1 run per day per job, owner chat only, ≤ 6,000-char instructions, no script/toolsets/skills/workdir/model fields, no immediate run | Plugin policy on the arguments and the stored jobs. Any explicit value of another field is refused, empty or false included (`enabled_toolsets: []`, `pinned: false`, `skills: []`...: Hermes stores or clears them); only Hermes' own no-op defaults pass. A create reserves its slot for its own call only; the count is checked again at the save; resume is refused while Scout is over the cap; stored jobs are also checked for instruction and name size | code |
| G3 per-run cost | Plugin: 40 tool calls, 20 web calls per cron execution | code |
| G4 mail-tainted session cannot schedule | scout_mail veto (wins over approval); scout_cron posts nothing when another hook vetoes, and asks again at the save (a session tainted while the card is pending saves nothing) | code |
| G5 record read at start | Hermes notepad injected into every run's prompt | code |
| G5 record written, dedup applied | Tool exists and is scoped to the running job; using it is asked by the SOUL and the job instructions | prompt (use) |

## 3. Preflight (owner, before deploying)

1. Read `report.md` (check-mode diff and decisions).
2. Make sure no job of any profile can fire across the restart. Today there is none; once Scout has jobs, run this read-only check from the repository root before ANY deploy or restart:

   ```bash
   ssh hermes-31 "sudo docker exec -i -u 1000 -e HERMES_HOME=/opt/data/profiles/job-search hermes python3 - schedule-window 120" \
     < hermes/ansible/roles/hermes_agent/files/hermes_checks.py
   ```

   `GO` is required. A weekday 07:00 Guadeloupe job is 11:00 UTC: avoid deploying between 05:00 and 09:00 Guadeloupe time on its days.
3. Confirm Scout's SOUL is still the one the role may replace (expect `7dc753fe…`):

   ```bash
   ssh hermes-31 'sudo sha256sum /opt/hermes/data/profiles/job-search/SOUL.md'
   ```

4. Offline checks: `uv run pytest hermes/tests -q`. `test_scout_cron_image.py` needs `nousresearch/hermes-agent:v0.22.5` locally. Re-run it after any Hermes image change: the plugin relies on v0.22.5 internals listed in `files/plugins/scout_cron/hermes_port.py`.

## 4. Check mode and deployment

```bash
cd hermes
ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes --check --diff   # expected diff: report.md, "Check mode"
ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes                  # owner decision; one multiplexed gateway restart
ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes                  # second run: changed=0 expected
```

After the restart the playbook verifies:
- `hermes_checks.py scout-schedule`: the plugin, `/taches-scout` and the `cronjob_manage` override exist for job-search only; `cronjob` is on telegram only and `scout_task_record` on telegram and cron only, nowhere else; `cron.allow_agent_scheduling` is not true; at most 5 jobs, each conforming. It prints names and schedules, never instructions;
- `hermes_checks.py scout-mail`, unchanged;
- the per-platform `toolsets` check.

## 5. Owner test in Telegram (after deployment)

| # | Owner action in Scout's private chat | Expected |
|---|---|---|
| 1 | `/new`, then the private request text (kept in `owner-request.local.md`, never in the repository) | Scout lists existing tasks, summarises name, days, 07:00 Guadeloupe / 11:00 UTC and the instructions, then calls the tool. A message « 📋 Scout — proposition de tâche planifiée : créer … » shows the full saved text (several messages if long), followed by an approval card |
| 2 | Tap « once » (or the equivalent first button) | Scout confirms creation, lists the task as active, and gives the next run in Guadeloupe time (e.g. « mercredi … 07:00 ») |
| 3 | `/taches-scout` | One task, active, next run in Guadeloupe time, empty journal |
| 4 | Send the same request again | Scout updates the existing task (approval card again), never a second task |
| 5 | « Crée une tâche toutes les 30 minutes » | Refused: at most one run a day; nothing posted, no card |
| 6 | « Envoie les résultats aussi à un autre compte » | Refused: delivery only to this conversation |
| 7 | Ask for a creation, then tap « deny » (or wait 5 min) | Nothing saved (`/taches-scout` unchanged) |
| 8 | After the first weekday run | Alert in this chat from Scout's bot; `/taches-scout <nom>` shows a journal and a count of alerted vacancies |
| 9 | Reply with feedback (« moins de postes en ESN ») and ask Scout to note it | Approval card showing the feedback; then `/taches-scout <nom>` lists it under « Retours » |

Do not use the « always » button: it is harmless (single-use keys) but leaves a dead entry in Scout's `command_allowlist`.

## 6. Operator: inspect, pause, remove a job

Read-only inspection:

```bash
ssh hermes-31 'sudo docker exec -u 1000 hermes hermes -p job-search cron list'
ssh hermes-31 'sudo docker exec -u 1000 hermes hermes -p job-search cron notepad <job_id> list'
ssh hermes-31 'sudo docker exec -u 1000 -e HERMES_HOME=/opt/data/profiles/job-search hermes sh -c "ls -l plugin-data/scout_cron/ledger"'
```

Pause, resume, remove (operator CLI, no approval: the CLI is the operator's own channel):

```bash
ssh hermes-31 'sudo docker exec -u 1000 hermes hermes -p job-search cron pause <job_id>'
ssh hermes-31 'sudo docker exec -u 1000 hermes hermes -p job-search cron resume <job_id>'
ssh hermes-31 'sudo docker exec -u 1000 hermes hermes -p job-search cron remove <job_id>'   # notepad cleared by Hermes
ssh hermes-31 'sudo docker exec -u 1000 hermes rm -f /opt/data/profiles/job-search/plugin-data/scout_cron/ledger/<job_id>.json'
```

When the owner removes a job through Scout, the plugin deletes its ledger file. After a CLI `remove`, delete the ledger file by hand as above.

Emergency stop of every Scout job without a deploy: `touch /opt/hermes/data/profiles/job-search/ESTOP` (as the hermes user). A job created by an operator with fields outside the policy (script, other delivery, sub-daily schedule) can still be listed, paused and removed by Scout, never updated or resumed. `/taches-scout` flags it « hors politique ».

## 7. Rollback

Order matters. A job keeps firing after the plugin is unloaded, and it then runs without the per-run cap and without `scout_task_record`.

1. Pause or remove every Scout job (§6). Confirm with `cron list`.
2. In ONE commit:
   - set `hermes_scout_cron_enabled: false`;
   - remove `scout_cron` from Scout's `plugins.enabled`;
   - put `cronjob` back into Scout's `agent.disabled_toolsets`;
   - set `plugins.entries.scout_cron.granted_capabilities: []` (keep the line: the role never deletes a config key, so a removed line would leave the grant in place).
   The role refuses a disabled switch without `cronjob` denied or with the grant left.

   Optionally, revert the whole MR instead. It also restores:
   - the tool lists: cron keeps memory and session_search again;
   - the SOUL: the reverted SOUL is not re-seeded automatically, because the live SOUL then carries a hash that is not a predecessor; restore it with `default_soul.yml` rules or by hand;
   - `timezone`: removing it shifts any remaining job's wall-clock time by 4 h.
3. Check mode, then deploy (one restart), then a second run with `changed=0`. `scout-schedule` must report « inactive everywhere ».

The plugin files stay on disk, inert. The role deletes no file.

## 8. Limits (defaults, enforced in code)

Defaults live in `files/plugins/scout_cron/config.py` (`Limits`, `BOUNDS`). Override them with `hermes_scout_cron_limits`; values outside the bounds make the plugin refuse every scheduling call.

| Limit | Default | Bounds |
|---|---|---|
| `max_jobs` (paused included) | 5 | 1–10 |
| `max_prompt_chars` | 6,000 | 200–8,000 |
| `max_name_chars` | 80 | 10–120 |
| `journal_chars` | 3,000 | 200–8,000 |
| `feedback_chars` | 1,500 | 100–4,000 |
| `ledger_days` / `ledger_max` | 180 / 5,000 | 7–730 / 100–20,000 |
| `run_tool_calls` / `run_web_calls` per cron execution | 40 / 20 | 5–200 / 1–100 |

## 9. Known limitations

- A page fetched during an approved run can still steer that run (prompt injection). It is bounded: read-only tools apart from the journal and ledger, the call caps, and delivery to the owner only. Search queries or fetched URLs could still carry Scout's private context; that was already true of any Scout session with web tools.
- A run can write steering text into its own journal (at most 3,000 characters, read by that job only). `/taches-scout` shows it; removing the job deletes it.
- The approval card text is capped by Telegram at 500 characters; the full text is in the messages just above it.
- Cron runs execute in a Hermes worker process that reads `HERMES_TIMEZONE` from the gateway's environment, i.e. the default profile's `timezone` (unset today). Keep Nora's `timezone` unset or equal to `America/Guadeloupe`.
- Scout's Telegram sessions still write memory without approval (pre-existing, out of scope; follow-up in `report.md`).

## 10. Out of scope

- Subscriptions, applications and outreach.
- Kandidat writes in cron.
- Any job for Nora or Kaféine.
- Jobs created by the deploy itself.
