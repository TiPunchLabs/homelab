# Role: hermes_agent

Deploy Hermes Agent as one Docker Compose stack hosting several **profiles**,
one Telegram bot per profile, all in the same container.

> **Current host: hermes-31** (Hermes v0.22.5, one multiplexed gateway serving
> three profiles: Nora `default`, Kaféine `cafe-ia`, Scout `job-search`) — see
> [hermes-31](#hermes-31--hermes-v0225-one-multiplexed-gateway-mission-m63).
> **M7 (deployed 2026-10-29, Néo deleted 2026-10-30):** Néo (`tech-watch`) was
> consolidated into Kaféine and permanently retired — see
> [M7](#m7--kaféine-consolidation-and-néo-retirement). Sections about Néo are
> history.
> hermes-30 (v0.20.4, one s6 gateway per profile, image `v2026.8.18`, still the
> role defaults) was **destroyed in M6.6.C (2026-10-26)**. Most sections below
> were written and measured on hermes-30: they remain as the design history of
> the role, and their hermes-30 commands no longer have a target.

> **State of hermes-30 before M6 (mission M4.3 deployed, 2026-10-24),
> historical.**
> Four gateways ran in the container: `default` (unchanged, bot of its own, **no cron** since
> 2026-10-23), **Kaféine** (`cafe-ia`, `gateway-cafe-ia`, `127.0.0.1:8646`,
> bot `kafeine_r64gnb_bot`), **Néo** (`tech-watch`, `gateway-tech-watch`,
> `127.0.0.1:8643`, bot `neo_r64gnb_bot`) and **Scout** (`job-search`,
> `gateway-job-search`, `127.0.0.1:8645`, bot `scout_r64gnb_bot`) —
> `hermes_profiles` lists cafe-ia, tech-watch then job-search. The three
> additional profiles share one tool matrix, fixed in M3.3.1 so that
> `web_search` really reaches the model — see
> [`browser` and `web_search`](#tool-restrictions-browser-and-web_search-m331).
> What was proven and what was not: [Phase B](#phase-b--as-executed-2026-10-20)
> (M2), [M3.3 as executed](#m33--as-executed-2026-10-22),
> [M4.3 as executed](#m43--as-executed-2026-10-24).

## Mental Model

```
 Ansible Vault ──► Ansible
                    │
                    ├─ template ──► /opt/hermes/managed/.env  → /etc/hermes (:ro, root)
                    │                 DEEPSEEK_API_KEY, API_SERVER_KEY, dashboard auth
                    │                 TELEGRAM_ALLOWED_USERS  ← one allowlist, all bots
                    │                 TELEGRAM_ALLOW_ALL_USERS=false, GATEWAY_ALLOW_ALL_USERS=false
                    │                 ⛔ never TELEGRAM_BOT_TOKEN, API_SERVER_PORT/HOST
                    │
                    └─ lineinfile ─► /opt/hermes/data/.env    → /opt/data/.env   (default)
                       (one key)       TELEGRAM_BOT_TOKEN      + whatever the agent wrote
                                     profiles/<name>/.env                         (later)
                                       TELEGRAM_BOT_TOKEN, API_SERVER_PORT, profile keys

 container "hermes" (s6)
   gateway-default      HERMES_HOME=/opt/data                    :8642  ── bot default
   gateway-<name>       HERMES_HOME=/opt/data/profiles/<name>    :864x  ── bot <name>
     each loads: its own .env (override) → then /etc/hermes/.env (override, LAST)
```

> **Analogy**: the managed layer is the building's house rules — every flat
> obeys them and they beat each flat's own rules. A bot token is a mailbox key:
> written into the house rules, every flat would get the same key and fight over
> the same mail.

## Secrets architecture

### Where each key lives, and why

| Key | Location | Owner | Why |
|---|---|---|---|
| `DEEPSEEK_API_KEY`, `API_SERVER_*KEY`, dashboard auth | managed `.env` | Ansible (template) | shared by every profile |
| `TELEGRAM_ALLOWED_USERS` | managed `.env` | Ansible (template) | **same user for the five bots** (decision D3); unoverridable by any profile |
| `TELEGRAM_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS` = `false` | managed `.env` | Ansible (template) | both bypass the allowlist (`gateway/authz_mixin.py`); pinned off for all |
| `TELEGRAM_BOT_TOKEN` (default) | `/opt/hermes/data/.env` | Ansible, **this key only** | a token belongs to exactly one gateway |
| `TELEGRAM_BOT_TOKEN`, `API_SERVER_PORT` (profile) | `profiles/<name>/.env` | Ansible, these keys only | idem; one port per gateway |
| anything else in those `.env` | — | the agent / user | `hermes gateway setup`, pairing approval… |

### How Hermes v0.20.4 loads them

Verified in the image's source (`hermes_cli/env_loader.py`, `load_hermes_dotenv`):

1. container environment (`PUID`, `PGID`, `HERMES_HOME` — no secret in Compose);
2. `<HERMES_HOME>/.env` of the profile, `override=True`;
3. external secret sources (none configured);
4. `/etc/hermes/.env` (managed), `override=True`, **last** — beats everything.

`gateway/config.py` enables Telegram when `TELEGRAM_BOT_TOKEN` is in the
environment. The s6 run script (`#!/command/with-contenv sh`) passes only the
container environment, so each gateway resolves **its own** `.env` token, then
the shared managed allowlist on top.

### Why two gateways can never share a token

`gateway run --replace` (what every s6 slot runs) **kills** whichever process
holds the same token lock, even in another profile
(`gateway/platforms/base.py`, `take_over_scoped_lock_holder`). Hence:

- no token in the managed layer (it would be inherited by every profile) —
  checked on the layer Hermes actually loads, after every run;
- `validate.yml` refuses two equal tokens (default included), comparing values
  under `no_log` — a failure never prints them.

### How Ansible writes a `.env` key (`tasks/env_keys.yml`)

- `lineinfile` per key, regexp also matching `export KEY=`; `create: true`,
  `0600`, `PUID:PGID`. Other lines are never touched.
- Empty value → that key is removed (used for rollback and for
  `hermes_telegram_enabled: false`).
- A key present **twice** fails the run (`grep -c`, counts only): resolving a
  stale duplicate token is a human decision.
- `no_log: true`: `--diff` would otherwise print the token. No `backup:`, which
  would leave a plaintext copy next to the file.
- Hermes may rewrite the file itself (`_sanitize_env_file_if_needed`, atomic
  replace, `0600`); `KEY=value\n` lines are already canonical, so it doesn't.

### Isolation limits — accepted risk

All gateways run in **one container, under one UID** (hermes → 1000).
`0600` on a profile's `.env` does **not** stop another profile's process from
reading it: same owner. A prompt-injected agent with the `terminal` or `file`
toolset could read every bot token, and `DEEPSEEK_API_KEY` is already in every
process environment. This is accepted for a single-user homelab; the mitigations
are the shared allowlist (nobody else can drive a bot), per-profile toolset
restrictions (D5: Kaféine and Néo, verified tool by tool) and SOUL rules. Real isolation would need one
container per profile, judged disproportionate.

## Managed-layer rules

- Declare only what Ansible must own; every key becomes unoverridable **for all
  profiles**.
- Never: `TELEGRAM_BOT_TOKEN`, `API_SERVER_PORT`, `API_SERVER_HOST`,
  `mcp_servers` (merged leaf by leaf into every profile — Kandidat would reach
  all of them), toolsets, `platforms:`.
- After every run, `Verify the managed scope contract` runs
  `files/hermes_checks.py managed` **inside the container**, against what
  `hermes_cli.managed_scope` really loaded: `model.provider` pinned (an
  untraversable `/etc/hermes` silently drops the whole layer), allowlist present
  and equal to the inventory, allow-all flags off, no token, no API port.

## Profiles

```yaml
hermes_profiles:            # group_vars — one dedicated commit per activation
  - "{{ hermes_profile_cafe_ia }}"      # M2, 2026-10-20
  - "{{ hermes_profile_tech_watch }}"   # M3, 2026-10-22
  - "{{ hermes_profile_job_search }}"   # M4, 2026-10-24

hermes_profile_reserved_ports:          # fixed per profile, not per deploy order
  tech-watch: 8643
  daily-life: 8644
  job-search: 8645
  cafe-ia: 8646
```

`validate.yml` (controller side, before any write) refuses: a name off the
reservation table or `default`; a port different from the reserved one or equal
to another (8642 included); a missing or shared token; a per-profile
`telegram_allowed_users`; `TELEGRAM_*`, `API_SERVER_*` or `GATEWAY_ALLOW*` keys
in a profile's `env`. Assertions loop on **indexes**, so a failure never prints
a profile dictionary.

Ownership inside `profiles/<name>/`:

| Path | Owner |
|---|---|
| `SOUL.md` | seeded once, then Hermes/user (below) |
| `scripts/`, other delivered files | Ansible, rewritten each run (`profile_content.yml`; `__pycache__`, `*.pyc`, `*.pyo` never shipped) |
| `.env` | Ansible for its keys, the agent for the rest |
| `config.yaml` | the agent; Ansible sets declared keys with `hermes config set`, compared **type-strictly** (`hermes config get --json` vs canonical JSON: `true` ≠ `"true"`, `42` ≠ `"42"`) |
| memories, sessions, cron, skills | the agent — never touched |

Every new profile starts **blank** (decision D7): `hermes profile create <name>
--no-alias`, never `--clone`. Nothing is copied from `default` — no memory,
conversation, session, custom skill or cron; only the image's bundled skills
are seeded. Each profile's automations are created for it later (M6); a cron
of `default` is paused or removed only on an explicit decision.

## SOUL.md: seeded once (decision D6)

`hermes profile create` already writes a SOUL.md: the stock `DEFAULT_SOUL_MD`
text (`hermes_cli/profiles.py`). A plain `copy force: false` would therefore
**never** install ours. `tasks/soul_seed.yml` copies the delivered SOUL.md only
when the file is **absent** or **byte-identical to the stock text** (its sha256 is
read from the running image, so an image upgrade can't fool it). Any other
content is a live identity — edited from the dashboard or by hand — and is left
alone: content, mode, owner and mtime.

To push a new repo version on purpose: delete that profile's `SOUL.md` by hand,
then re-run. Never automatic.

## Post-deploy health checks

Handlers are flushed **before** any check, so every check judges the restarted
process, not the one still running the old configuration.

| Level | What | How | Automatic |
|---|---|---|---|
| 1 | container started | `docker inspect` → `State.Running` | ✅ |
| 2 | gateway active | `s6-svstat gateway-default` → `up (pid N)` | ✅ |
| 3 | Telegram connected | `gateway_state.json`: `gateway_state=running`, `platforms.telegram.state=connected`, **written by pid N** (pid + start_time) | ✅ retried 24 × 5 s |
| 4 | the bot answers | a human sends a message | ❌ manual |

> ⚠️ **Why level 3 checks the writer.** `gateway_state.json` is not a heartbeat:
> it is written on transitions only (on hermes-30 its last write was days old)
> and survives restarts. A gateway that died at restart still reads
> `connected` — from its previous life. The check trusts the entry only if its
> `writer_pid`/`writer_start_time` match the process s6 supervises now.

`getMe` is not used: it proves the token is valid, not that messages flow. And
`getUpdates` would steal the gateway's updates.

### Level 4 — end-to-end test (manual)

1. From the allowlisted account, send the default bot a message that needs the
   model (e.g. « Quelle heure est-il à Pointe-à-Pitre ? »).
2. A reply arrives from the **default** bot.
3. Optional evidence: `sudo grep "\[Telegram\] Sending response" /opt/hermes/data/logs/agent.log | tail -1`
   shows a line timestamped after the deployment.

Until a human has done it: **END-TO-END TELEGRAM: NOT VALIDATED**.

## Restarts and `stop_grace_period`

`Restart hermes` (handler) restarts the stack **once**, only when a managed
file, the Compose file or a default `.env` key actually changed. A second run
changes nothing and restarts nothing.

`stop_grace_period` is **not** set (studied in M1, not applied):

- `container-boot.log` shows `prior_exit=unclean` five times since 2026-09-28,
  but all five match **VM reboots** (`last -x reboot`), none a controlled
  restart;
- s6-overlay 3.2.3.0 enforces its own shutdown timers inside the container
  (`S6_SERVICES_GRACETIME`/`S6_KILL_GRACETIME`, 3 s by default) — raising
  Docker's 10 s alone would not give the gateway more time;
- changing the Compose file recreates the container *and* fires the handler:
  two restarts instead of one during the token migration.

Measure first: after the next controlled restart, read the last line of
`/opt/hermes/data/logs/container-boot.log`. `prior_exit=clean` means Docker's
10 s already suffices for controlled restarts.

## SOUL.md of `default` is never seeded

`soul_seed.yml` is reached only through `profiles.yml` → `profile.yml`, i.e.
for entries of `hermes_profiles` (`[]` in M1, and `default` is a refused name).
It also **asserts** its target is exactly `<data>/profiles/<name>/SOUL.md`
before reading anything: `/opt/hermes/data/SOUL.md` is refused even when it is
byte-identical to the stock text (tests: `test_default_soul_is_never_seeded`,
`test_soul_seed_refuses_paths_outside_a_profile`). On hermes-30 it is
customised anyway (sha256 `a0a58fb6…`, ≠ stock `2765a846…`); the preflight
prints it so the post-deploy value can be compared.

## Cron safety (Hermes v0.20.4)

The role creates, edits, pauses or triggers **no** cron job and sets no
timezone (D1: target set, timing still open). A gateway restart is the only contact. What
`cron/jobs.py` (`_get_due_jobs_locked`) does on the first tick after a restart:

| Job state at restart | Effect |
|---|---|
| `next_run_at` in the future | nothing — fires at its time |
| `next_run_at` **past**, within grace (½ period, 2 h max for weekly jobs) | fires **once**, late |
| `next_run_at` **past**, beyond grace | fast-forwarded to the next slot **and fires once now** |
| run in flight (`fire_claim` set) | killed by the restart; `next_run_at` was advanced **before** the run → **not** re-fired (at-most-once), the run is lost |
| `interval` job with `last_status=error` | re-armed to **now** |
| `cron` job with `last_status=error` | re-armed to its next **legal** slot, never now |
| disabled / paused | nothing |

So a restart is safe iff no enabled job is overdue, due within the window, or
running. `files/hermes_checks.py schedule-window <minutes>` evaluates exactly
that from the profile's `jobs.json` (read-only, prints names, schedules and
timestamps, never a prompt) and is part of the preflight
(`hermes_restart_safety_window_minutes`, default 120).

Windows to avoid (UTC, container time): **Mon 07:00**, **Wed 07:00**,
**Sat 08:00**, ± 2 h. Observed on 2026-10-14 01:30 UTC: the three jobs
`scheduled`, `last_status=ok`, no claim, no `ESTOP`; next due:
prospection-entreprises Wed 2026-10-14 07:00 UTC.

## M1 deployment procedure

All commands from `hermes/`. Nothing below runs without explicit approval.

| Step | Command | Writes on hermes-30? |
|---|---|---|
| 1. Preflight | `ansible-playbook ansible/m1-preflight.yml` | no |
| 2. Dry run | `ansible-playbook ansible/deploy.yml --tags hermes --check --diff` | no |
| 3. Backup | `ansible-playbook ansible/m1-backup.yml` | `/root/hermes-m1-backup/` only |
| 4. Deploy | `ansible-playbook ansible/deploy.yml --tags hermes` | managed/.env, data/.env, 1 restart |
| 5. Idempotence | same command again → `changed=0`, no restart | no |
| 6. Level 4 | human message to the default bot | — |

**Preflight (NO-GO on any failure):** host timezone already equals
`hermes_timezone` (else the `deploy.yml` pre_task would change it); default
gateway already Telegram-connected (levels 1-3); no cron job can fire across a
restart. It also prints, values never shown: `data/.env` presence and its
`TELEGRAM_BOT_TOKEN` line count, the managed `.env` key names, the default
SOUL.md sha256, the profile count, free space, `ESTOP`.

**What `--check` proves, and what it cannot:**

| Verified by `--check --diff` | Only by the real run |
|---|---|
| inventory guards (`validate.yml`: allowlist, tokens, ports) | the single restart actually happening |
| timezone pre_task: read runs, **no change** reported | managed contract as **loaded by Hermes** |
| `managed/config.yaml`, `docker-compose.yml`: diff shown | `data/.env` really holding the token (`env-key`) |
| `managed/.env`, `data/.env`: `changed` expected, **no diff** (no_log) | ports listening, TLS trust from the container |
| duplicate-key detection in `data/.env` (read runs in check mode) | Telegram levels 1-3 on the **new** process |
| handler and every post-restart check reported `skipped` | level 4 (human) |

Expected `--check` result: `failed=0`; `changed` only on the managed `.env`,
the `data/.env` key and the restart relay; **not** on the timezone task, the
Compose file or `managed/config.yaml`. Anything else changed → stop and
investigate.

## Rollback of M1

Independent of git: `ansible-playbook ansible/m1-rollback.yml` reads the
step-3 backup (`tasks/m1_rollback.yml`).

1. **Guard**: the backed-up managed `.env` must hold exactly one
   `TELEGRAM_BOT_TOKEN`, i.e. be a pre-M1 state. Otherwise nothing is written.
2. Restores `managed/.env` (0640 root:1000), `managed/config.yaml` and
   `docker-compose.yml` from the backup: the token is back in managed.
3. In `data/.env`, touches **only** `TELEGRAM_BOT_TOKEN` (via `env_keys.yml`):
   - absent before M1 (hermes-30 case) → key removed; the file is left
     **empty**, 0600, no secret (this role never deletes a volume file;
     removing it is manual, on confirmation);
   - present with a token → that original value comes back, in place;
   - present without a token → key removed.
   Every other variable stays.
4. One restart if anything changed, then Telegram levels 1-3; level 4 by hand.
5. `jobs.json` and `data/config.yaml` are never restored (agent-owned, M1
   does not write them).

Fallback if the backup is unusable: replay the pre-M1 role from `main`
(`--tags hermes`), check Telegram, then remove the key with
`env_keys.yml` semantics (empty value). Never delete `/opt/hermes/data`, never
regenerate a token.

Tests: `test_m1_operations.py` (absent / present-with-token /
present-without-token, post-M1 backup refused, idempotent rollback, no token
in output even with `--diff -v`), `test_t20_*`.

### Backup protection and cleanup

`/root/hermes-m1-backup/` is 0700 root, every file 0600, created only on the
host, never copied back to the controller; secret copies are `no_log`. An
existing backup is never overwritten.

It holds two copies of secrets (`managed.env`, `data.env` if any). Keep it
until **all** of: second run `changed=0`, level 4 validated, and the next cron
run (Wed 07:00 UTC) delivered. Then, **on explicit confirmation only**:

```bash
ssh ansible@hermes-30 'sudo shred -u /root/hermes-m1-backup/managed.env; sudo test ! -e /root/hermes-m1-backup/data.env || sudo shred -u /root/hermes-m1-backup/data.env'
```

and move the remaining non-secret files out (`trash` is not installed on the
host; the directory removal is a deliberate manual step).

## Kaféine — profile `cafe-ia` (mission M2)

Assistant of the Café IA project: AI watch for a mixed audience, projects to
present, meeting preparation, drafts. Identity: `files/profiles/cafe-ia/SOUL.md`
(seeded once, D6). Declaration: `hermes_profile_cafe_ia` in `group_vars`.

> **M7 (deployed 2026-10-29):** Kaféine absorbed Néo's scope (technology
> watch, technical expertise, local AI, DevOps, HomeLab) and environment hint;
> new SOUL.md through the guarded replacement; same tool matrix; description
> updated by hand (step 12). See
> [M7](#m7--kaféine-consolidation-and-néo-retirement).

### What `hermes profile create cafe-ia --no-alias` really creates (v0.20.4)

Observed in a throwaway container of the same image, with a lived-in fake
`default` next to it:

```text
profiles/cafe-ia/
├── .env            header only, 0600 (create_profile seeds it)
├── SOUL.md         stock DEFAULT_SOUL_MD (sha256 2765a846…) → replaced by the seed
├── profile.yaml    description
├── memories/ sessions/ cron/ plans/ workspace/ home/ skins/ logs/   empty
└── skills/         82 bundled skills of the image + .bundled_manifest
```

No `config.yaml` (written by the first `hermes config set`), no memory, no
session, no cron job, no custom skill of `default` (checked by content). The
s6 slot `gateway-cafe-ia` is registered `down`. The first gateway run adds its
own runtime state (`state.db`, `gateway_state.json`, `response_store.db`,
`sandboxes/`, `bin/`, `cache/`…). Nothing is ever copied from `default`
(`--clone*` never used; `backfill_profile_envs`, which copies default's `.env`
— token included — into a profile without one, only runs on `hermes update`,
never used here, and the profile has its `.env` from creation anyway).

### Architecture

| Item | `default` | `cafe-ia` |
|---|---|---|
| HERMES_HOME | `/opt/data` | `/opt/data/profiles/cafe-ia` |
| s6 service | `gateway-default` | `gateway-cafe-ia` (`hermes -p cafe-ia gateway run --replace`) |
| API port | 8642, 127.0.0.1 | **8646, 127.0.0.1** (Hermes default bind; checked after start) |
| Telegram bot | existing | **new** `kafeine_<6 alnum>_bot` (proposed: `kafeine_r64gnb_bot`) |
| Token | `vault_hermes_telegram_bot_token` → `data/.env` | `vault_hermes_cafe_ia_telegram_bot_token` → `profiles/cafe-ia/.env` |
| Allowlist, allow-all off | managed (shared) | managed (shared, verified effective in a lab container) |
| `API_SERVER_KEY` | managed (wins) | managed (wins); never in the profile `.env` |
| Web search | none configured | Tavily, `vault_hermes_cafe_ia_tavily_api_key` |
| MCP | `kandidat` (in its own config.yaml) | **none** (`no_mcp`) |
| Memory, sessions, cron | its own | its own, empty at start |

### Tools (D5) — matrix

Since M3.3.1, telegram, cron, api_server **and cli** expose exactly
`web_search, web_extract, memory, session_search, skills_list, skill_view,
skill_manage, todo, clarify` — measured on the tools a real agent receives, on
hermes-30 and in the offline lab (an unrestricted profile exposes 18 tools,
`terminal`, `read_file`, `write_file`, `execute_code`, `delegate_task`…
included). Until M3.3.1, M2 only checked toolset **names**, and `web_search`
was in fact missing: see
[`browser` and `web_search`](#tool-restrictions-browser-and-web_search-m331).

| Toolset | Allowed | Why | Risk |
|---|---|---|---|
| `web` (search, extract) | ✅ | the core of the mission | prompt injection from pages; SOUL tells it page content is data |
| `memory` | ✅ | capitalise topics and meetings | low, own profile only |
| `session_search` | ✅ | recall past conversations | low, own sessions only |
| `skills` | ✅ ⚠️ | bundled research skills (`grounded-citations`, `arxiv`, `competitor-news-monitor`) | `skill_manage` comes with it; its writes are **staged** (`skills.write_approval: true`), see below |
| `todo`, `clarify` | ✅ | multi-step work, questions | none |
| `terminal`, `process`, `code_execution` | ❌ | not needed | shell as UID 1000: every token of every profile, LAN |
| `file` | ❌ | drafts go in the chat | `HERMES_WRITE_SAFE_ROOT=/opt/data` = all profiles; reads `/etc/hermes/.env` |
| `browser`, `computer_use` | ❌ | `web_extract` reads pages | can fill and submit forms: publishing without validation. `browser` is kept **out of every allowlist** but no longer in the denylist (M3.3.1) |
| `cronjob`, `kanban`, `delegation` | ❌ | no automation in M2 (M6) | recurring actions, sub-agents |
| media, tts, vision, social/chat platforms, home automation | ❌ | not needed | outbound actions, cost |
| MCP servers | ❌ (`no_mcp`) | no Kandidat (D5) | — |

**`skill_manage` cannot be removed alone.** Hermes filters by toolset, never by
tool, and `skills` is one indivisible toolset (`skills_list`, `skill_view`,
`skill_manage`; no smaller toolset or legacy alias exists in the image). So the
profile pins `skills.write_approval: true`: every `create`, `edit`, `patch`,
`delete`, `write_file` and `remove_file` is staged under `pending/skills/`, from
a chat **and** from the background self-improvement review, until
`/skills approve <id>` (`/skills pending`, `diff <id>`, `reject <id>` in
Telegram). Tested in an offline throwaway container: gate on, `create` returns
`staged` and writes nothing; gate off, the skill is written. Reading skills is
unchanged.

Residual risk: the allowlisted user can turn the gate off with
`/skills approval off` (it writes the profile `config.yaml`); the next playbook
run puts it back and reports `changed` on that key — a visible drift, not a
silent one. An approved skill is still persistent text the model will follow:
read the `diff` before approving.

Two layers, both in the profile's `config.yaml` (never in managed, which
would restrict `default` too): `platform_toolsets.{telegram,cron,api_server,cli}`
(allowlist, `cli` declared since M3.3.1) and `agent.disabled_toolsets`
(denylist applied **last**, on every platform, tool by tool). Ansible sets them
with `hermes config set`, type-strict compared, and `Verify that the declared
tool restrictions are effective` re-resolves them with Hermes' code **before**
the gateway starts — toolset names **and** the tools the model receives. A toolset name unknown to
Hermes would be dropped silently (#38798): the test suite pins the list of
v0.20.4 names.

> ⚠️ **SOUL.md is not a security boundary.** The limits that matter (no
> shell, no files, no browser, no cron, no MCP) are technical. The others
> (publish, contact, send) are enforced by the absence of any tool able to do
> them; SOUL.md repeats them for the model.

Isolation limit (unchanged, accepted): one container, one UID. The toolset
restrictions are what keep Kaféine away from other profiles' `.env`; a future
change that grants `terminal` or `file` would void them.

### `API_SERVER_KEY` — the M1 anomaly, understood

`docker/stage2-hook.sh` (v2026.8.18, `cont-init.d/01-hermes-setup`) does, as
root, at **every container start**:

```sh
if [ -f "$HERMES_HOME/.env" ] && ! grep -q '^API_SERVER_KEY=..*' "$HERMES_HOME/.env"; then
    printf 'API_SERVER_KEY=%s\n' "$random" >> "$HERMES_HOME/.env"
fi
```

- `HERMES_HOME` is the container's, `/opt/data`: **only `/opt/data/.env`** is
  ever touched, never `profiles/*/.env` (code + lab: profile `.env` checksum
  unchanged across repeated dual-container boots).
- Check-then-append is not atomic. `hermes` and `hermes-dashboard` share the
  volume and both run the hook: when `data/.env` first appeared without the
  key (M1), both appended → 2 lines. Not reproduced in 6 local dual boots: a
  race, not a rule. Now that the line exists, the hook never fires again.
- The dashboard container **skips** the profile reconciler (`reconcile:
  skipping (dashboard container…)`, seen on hermes-30): it never starts a second
  `gateway-cafe-ia`.
- Every gateway loads its profile `.env`, then managed **last with
  override**: the effective key is managed's, for `default` and `cafe-ia`
  alike (verified by digest in the lab). With multiplexing off (default), the
  api_server reads it from the process environment.

**Decision: no fix to the image, no new secret, no cleanup of default's two
lines.** Kaféine's configuration is deterministic by construction; it is
*guarded*: `validate.yml` refuses any `API_SERVER_*` key in a profile `env`, and
`Verify that API_SERVER_KEY comes from managed only` (before the gateway
starts) fails if the profile `.env` carries one or if the effective key is not
managed's. Default's duplicate stays as is (harmless, managed wins); removing a
line from an agent-owned file is a separate decision.

### Telegram bot — BotFather procedure (manual, phase B1)

1. In Telegram, `@BotFather` → `/newbot`.
2. Name: **Kaféine — Café IA**.
3. Username: **`kafeine_r64gnb_bot`** (random code, not a security measure). If
   taken, draw another code (`python3 -c "import secrets,string;
   print(''.join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(6)))"`)
   and update `telegram_bot_username` in `group_vars`.
4. `/setdescription`: « Votre assistant pour découvrir l'IA, explorer des
   projets et préparer les rencontres Café IA. » — optional `/setuserpic`.
5. `/setjoingroups` → **Disable** (private use only).
6. Store the token **straight into the vault**, never in a chat or a file:
   `ansible-vault edit hermes/ansible/group_vars/hermes/vault/config.yml`, add
   `vault_hermes_cafe_ia_telegram_bot_token: "<token>"` and
   `vault_hermes_cafe_ia_tavily_api_key: "<key>"` (a dedicated Tavily key:
   own quota, own revocation; set a monthly usage limit in the Tavily
   dashboard, the role cannot enforce one).
7. From the allowlisted account, open the bot and send `/start`.

Checks, without displaying the token: `validate.yml` (present, unique against
default and every profile, username format), then `Verify that the token
belongs to the declared bot` (`getMe` → username must match — catches a valid
token pasted under the wrong key; tested for real: a bogus token is refused
with 401 before anything starts).

### Phase B — deployment order

All from `hermes/`, each step on explicit approval.

| Step | Command | Writes on hermes-30 |
|---|---|---|
| B1 | bot + vault keys + `/start` (above) | — |
| B2 | `ansible-playbook ansible/m2-preflight.yml` (needs `TF_VAR_pm_api_*` from `.envrc`: memory gate), then add `- "{{ hermes_profile_cafe_ia }}"` to `hermes_profiles` (activation commit) | no |
| B3 | `ansible-playbook ansible/deploy.yml --tags hermes --check --diff` | no |
| B4 | `ansible-playbook ansible/deploy.yml --tags hermes` | `profiles/cafe-ia/` only |
| B5 | automatic checks of B4 (below) | — |
| B6 | message Kaféine from Telegram; and default | — |
| B7 | isolation: ask Kaféine about something only default knows; check new memories land in `profiles/cafe-ia/memories/` | — |
| B8 | restart test outside the cron windows: `m1-preflight.yml` GO, then `docker compose restart gateway` → both slots up | restart |
| B9 | `deploy.yml --tags hermes` again → `changed=0` | no |

`m2-preflight.yml` (read-only) = `preflight.yml` (default connected, host
timezone, cron window) + `profile_preflight.yml`: the declaration added to the
current profiles passes `validate.yml` (missing vault key = NO-GO), no
`profiles/cafe-ia`, no s6 slot, port 8646 free, **memory headroom** (below);
it prints container and gateway memory.

**No restart of `default` is expected in B4**: managed files and Compose are
unchanged by M2, so the `Restart hermes` handler does not fire. `--check`
must show `changed` on none of them; otherwise stop.

B4 order inside `profile.yml`: create → seed SOUL → `.env` keys → `config set`
→ **bot identity, API key, effective tools** → `gateway start` (persists
`desired_state=running`) → port 8646 listening, **loopback only** →
Telegram connected (levels 1-3, same writer-pid rule as default). Then
`main.yml` re-checks that **default is still connected with the same pid**
(`--replace` would have killed it on a shared token).

Resources (hermes-30, 2026-10-15 22:08 UTC): container `hermes` 359 MiB / 4 GiB,
default gateway RSS 352 MiB, dashboard 277 MiB, VM 1.2 GiB used / 4.1 GiB.
A second gateway (~350 MiB) keeps the container under 1 GiB of its 4 GiB —
but the **VM** is the limit, not the container: see below.

### Memory: Proxmox ballooning and the M2 memory gate

**Why hermes-30 ran short** (audit 2026-10-16, read-only). hermes-30 is the
only VM of `pve` with a balloon device (`memory` 8192, floor `balloon` then
2048). dockhost-90 (10240), bastion-60 (2048) and vpngate-50 (512) have
`balloon: 0`: no device, so the host never takes back their guest page cache
(dockhost: 3.7 GiB used in the guest, 6.6 GiB held on the host, +2.8 GiB in a
week). Once `pve` passes its ballooning target (80 % by default, unset on the
node), `pvestatd` shrinks the only VM it can: hermes-30, down to its floor.
Komodo's 15-second history shows hermes-30 at its 2048 floor 35 to 84 % of
the time over 15 days, with 0.16 GiB available at worst (2026-10-14).

**The gate** (`tasks/memory_preflight.yml`, called by `profile_preflight.yml`):
NO-GO unless `hermes_pf_min_available_mib` (1536) is available **now** and
**at the balloon floor**. The floor is read from the effective Proxmox
configuration through its API (`cluster/resources` → `config` →
`status/current`, GET only, from the controller, `no_log`), with the
Terraform token of `.envrc` — nothing is copied from the Terraform code, so a
code/reality gap shows. Missing credentials, VM not found, unreadable config
or unknown balloon size: NO-GO. The worst case is an **estimate**, not a
guarantee: `floor − (balloon size − MemTotal) − used`, where the memory the
guest never sees is measured at that moment (~251 MiB) and used memory is
assumed not to grow. Proxmox only guarantees the floor on the host side.

| Real run (2026-10-16) | Floor | Verdict |
|---|---|---|
| before | 2048 | NO-GO: 567 MiB now and at the floor |
| after the changes below | 3584 | GO: 6726 MiB now, worst case ~2118 MiB |

One more gateway only: a second one (M3) needs a floor around 4096.

**Scenario A, applied 2026-10-16, 18:43–18:49 UTC** (authorized, without
Terraform):

- bastion-60 stopped cleanly (`qm shutdown`), `onboot 1 → 0`, its GitLab
  runner 52153437 paused first. A **temporary** stop: bastion is being
  retired, and Komodo deploys from homelab-gitops wait until the runner
  moves. Frees ~1.9 GiB of host RSS.
- `qm set 9030 --balloon 3584`, applied live: nothing pending, no reboot,
  gateway pid 162 unchanged, crons unchanged.

`hermes/terraform` then said `vm_memory_floating = 3584`, like Proxmox: its
plan showed no `memory` change (only an older cloud-init DNS drift, settled
since). `bpg/proxmox` 0.96.0 would **reboot** hermes-30 for a floor
change that Proxmox applies live (`qemu-server`, PVE 9.1.1: only
enabling/disabling the device is not hotpluggable; `reboot_after_update`
defaults to `true`), so floor changes went through `qm set` until M4-MEM
(below), and **never `apply` hermes from a branch that still says 2048**
(`main` before M2).

**Floor raised to 4096 (M4-MEM, 2026-10-23)**, room for a fourth gateway:

- Terraform now carries the floor change itself. The shared module exposes
  `vm_reboot_after_update`, and hermes sets it to `false`. bpg then pushes the
  config and only warns that a reboot is required. Apply at 19:32 UTC:
  `balloon: 4096`, nothing pending, no reboot, and the next plan says
  `No changes`.
- **The new floor did not take effect on its own.** `pve` was above its
  ballooning target, so `pvestatd` only shrinks VMs, and it leaves a VM that
  sits below its new floor where it is. The config change sends no balloon
  command either. The live balloon stayed at 3584.
- The live balloon reached 4096 at 23:54 UTC, when the administrator ran a
  one-off `balloon 4096` by hand in the QEMU monitor on `pve`
  (`qm monitor 9030`; the HMP `balloon` command takes MiB).
  Guest MemTotal went from 3333 to 3845 MiB and MemAvailable to ~2130 MiB.
  Gateway PIDs did not change, PSI stayed at 0, and there was no OOM. Once the
  live balloon is at the floor, `pvestatd` never shrinks below it.
- The global ballooning policy was not changed (`ballooning-target` still
  unset, default 80 %).
- After a floor change, check `qm status 9030 --verbose` (`balloon` against
  `balloon_min`) and the guest MemTotal. `qm config` alone does not prove the
  change is live.

**Not needed: A2** (balloon device on bastion): bastion is stopped.

**Deferred, out of M2: A1**, a balloon device on dockhost (floor 6144: guest
peak 4.16 GiB over 15 days in Komodo), so that its page cache stops weighing
on the host. Nothing for dockhost is in the M2 code. Its Terraform state
exists on **bastion-60** (local backend, copy in
`~/.local/share/homelab-tfstate-backup/dockhost/`); a plan from the laptop,
which has no state, wrongly proposes to create VM 9090. No `terraform import`
is needed, nor wanted (two states for one VM). Enabling the device is not
hotpluggable: shutdown then start of dockhost.

#### A1 procedure, for reference (on explicit approval, after M2)

Outside the cron windows of `default` (Mon 07:00 and Wed 07:00 UTC use
Kandidat, Sat 08:00 UTC; ±2 h) and with no CI job running. Commands on `pve`
(user `ansible`, sudo).

1. **Pre-checks** — `free -m`, `cat /proc/pressure/memory`, swap unused;
   `qm config 9090 | grep -E '^(memory|balloon)'` and `qm pending 9090` (no
   other pending change); `m1-preflight.yml` GO.
2. **Service baseline** — on dockhost `docker ps` (containers, restart
   policies), Caddy-fronted URLs answer, Komodo sees both servers, Hermes
   `default` connected (pid noted).
3. **A1** — `qm set 9090 --balloon 6144` (stays pending), then
   `qm shutdown 9090 --timeout 300 && qm start 9090`. Down meanwhile:
   kandidat (app, db, MCP — Hermes' Kandidat tools fail), komodo
   core/mongo/periphery, open-webui, portail-client (public), miniboard,
   excalidraw, portainer, shared postgresql.
4. **Check dockhost** — `qm config 9090` shows `balloon: 6144`, `qm status
   9090 --verbose` has `ballooninfo`; all containers up; URLs, Komodo,
   kandidat-mcp listening; Hermes reaches Kandidat again.
5. **New `m2-preflight.yml`** — memory gate still GO; watch `pve`
   (available, PSI, swap) for 24-48 h.

Rollback: A1 `qm set 9090 --balloon 0` then shutdown/start again. Floor of
hermes-30: `qm set 9030 --balloon 2048` (live). bastion:
`qm set 9060 --onboot 1 && qm start 9060`, then unpause runner 52153437.

### Rollback of M2

`ansible-playbook ansible/m2-rollback.yml` (`tasks/profile_rollback.yml`):

1. refuses any name but a reserved additional profile (never `default`);
2. `hermes -p cafe-ia gateway stop` if the slot is up **or** its
   `gateway_state.json` still says `desired_state=running` — that file, not
   the inventory, decides whether the boot reconciler restarts it;
3. checks: slot `down`, `desired_state` ≠ `running`, nothing on 8646, default
   still connected;
4. reports whether `cafe-ia` is still in `hermes_profiles`. Then `git revert`
   the activation commit and replay `deploy.yml --tags hermes` (`changed=0`).

Never: delete `profiles/cafe-ia/`, revoke the token, delete the bot, restart
the container. Played for real in a lab container: `changed=1` then `0`, and
after a container restart `reconcile: profile=cafe-ia prior_state=stopped
action=registered`, slot `down`, data intact. Independent of
`/root/hermes-m1-backup/` (kept, not used).

### Phase B — as executed (2026-10-20)

Activation commit `e07b385` (the only entry of `hermes_profiles`; its revert
is the declarative rollback). Deployed 22:51 UTC (18:51 AST), outside the
cron windows, from `feat/hermes-cafe-ia`. The `--check` step was run without
`--diff`.

| Step | Result |
|---|---|
| `m2-preflight.yml` | GO: worst case ~2301 MiB at the 3584 floor, default connected (pid 160), no `profiles/cafe-ia`, no slot, 8646 free, ESTOP absent |
| `deploy.yml --tags hermes` (1st) | `changed=5` exactly: create, SOUL seed, `.env` (3 keys), `config set` (6 keys), `gateway start`; **no handler**; every built-in check `ok` (getMe, managed-only `API_SERVER_KEY`, effective tools, loopback, Telegram connected, default same pid) |
| `deploy.yml --tags hermes` (2nd) | `changed=0` |
| `default` | same container (started 16:06:11, 0 restarts), gateway pid 160 continuous, Telegram ESTAB kept; `data/.env`, `data/config.yaml`, `SOUL.md`, managed `.env` and `config.yaml`, `cron/jobs.json` identical by sha256; 3 crons unchanged |
| `cafe-ia` | slot up, `desired_state=running`, Telegram `connected`, own lock (`gateway-locks/`, two files now), `127.0.0.1:8646` only; `.env` 0600 with `TELEGRAM_BOT_TOKEN`, `API_SERVER_PORT`, `TAVILY_API_KEY` only (no `API_SERVER_KEY` appended); 0 memories, 0 sessions, own `state.db`, no `cron/jobs.json`; `mcp_servers` empty; config = declaration (`web.backend`, toolsets, 24 disabled, `skills.write_approval: true`) |
| Resources | MemAvailable 7094 → ~6900 MiB; Kaféine gateway ~170 MB RSS, container 324 → 468 MiB; PSI 0, no swap, no OOM |
| Telegram, human (level 4) | **default and Kaféine both answered** — confirmed by the user |

**Not proven yet** — do not read them as validated:

- **Restart persistence** of `gateway-cafe-ia`. The slot shows `normally
  down`, which is expected (s6 does not restart it; `02-reconcile-profiles`
  does, from `desired_state=running`), but no container restart or reboot has
  happened since. Check at the next **organic** one: both slots up, both bots
  connected. Step B8 was not run.
- **B7 isolation by conversation** (Kaféine asked about something only default
  knows; new memories landing under `profiles/cafe-ia/memories/`). Isolation is
  proven by construction and by files only.

## Tool restrictions: `browser` and `web_search` (M3.3.1)

Common to **Kaféine and Néo**, found during the M3.3 Telegram tests and fixed
in `1a203d8`.

**Symptom.** Both profiles answered with `web_extract` only: no `web_search`,
so no way to find recent news. Configuration looked right (`web` allowed,
`web.backend: tavily`, key present) and every M2/M3 check was green.

**Cause, proven on v0.20.4 / v2026.8.18** (not claimed for other versions):

- the `browser` toolset lists the 13 `browser_*` tools **and `web_search`**
  (`toolsets.py`), not `web_extract`;
- `agent.disabled_toolsets` is subtracted **last** and **tool by tool**
  (`model_tools._compute_tool_definitions`), from the allowed toolsets too;
- so denying `browser` removed `web_search` on telegram, api_server, cli and
  cron, while `web_extract` stayed. Measured on hermes-30 with the agent's own
  tool builder; reproduced in an offline lab.

M2 and M3 checked toolset **names** (`web` present), never the tools the model
receives: that is how it went unnoticed.

**Fix (declarative, both profiles):**

| Change | Why |
|---|---|
| `browser` removed from `agent.disabled_toolsets` (24 → 23 entries) | the only denylist entry that touched a web tool |
| `platform_toolsets.cli` declared, same anchor as telegram/cron/api_server | without it the CLI falls back to Hermes' default toolsets, `browser` included — the denylist was its only filter |
| `toolsets` check of `profile.yml` now also judges **tools** (`hermes_checks.tool_errors`) | per platform, the tools a real agent would get must be **exactly** those of the allowed toolsets: one more (a `browser_*`) or one hidden (`web_search`) fails the run before the gateway restarts |

**Why this does not open `browser_*`.** `browser` is in no allowlist, on any
of the four platforms; Hermes only builds tools from the allowlisted toolsets.
The browser tools are absent by **policy**, not by chance (they also fail
their availability check in this image — the lab proved that this alone would
have hidden them on the CLI, which is why `cli` got its own allowlist). The
denylist keeps every other dangerous toolset (`terminal`, `file`,
`code_execution`, `computer_use`, `delegation`, `cronjob`, `kanban`, …).

**Guards against a regression** — `tests/test_m331_web_tools.py`, on the real
image, offline: both profiles created with their declared config, a real
`AIAgent` built per platform (telegram, api_server, cli, cron) the way the
gateway does; `web_search` and `web_extract` checked separately; exactly the 9
allowed tools, no `browser_*`/terminal/file/code tool; backend `tavily`; the
cause reproduced (`browser` denied → `web_search` gone, `web_extract` kept);
the deploy check refuses the M3.3 configuration
(`allowed tools not exposed: web_search`).

**Traceability, after the fix (2026-10-22).** Néo 2 and Kaféine 4 real
`web_search` calls, all `success: true`. `agent.log` of each profile shows
`Web search via tavily` then `Tavily search request to
https://api.tavily.com/search`; the provider only returns success after
`raise_for_status()`. HTTP status codes themselves are not logged.

> 💡 With `web.backend: tavily`, the web tools register **even without**
> `TAVILY_API_KEY` (measured in the lab): their presence does not prove the
> key. `validate.yml` refuses an empty value; a successful call proves it.

## Néo — profile `tech-watch` (mission M3, deployed 2026-10-22)

> **Retired in M7:** parked 2026-10-29, deleted from hermes-31 2026-10-30
> (`hermes profile delete`, tombstone `profiles/.deleted/tech-watch`); bot and
> Tavily key revoked by the user, both vault variables removed. This section is
> history; `m3-preflight.yml` and `m3-rollback.yml` were removed in M7. See
> [M7](#m7--kaféine-consolidation-and-néo-retirement).

| | |
|---|---|
| Name / id | **Néo** / `tech-watch` (`gateway-tech-watch`) |
| API | `127.0.0.1:8643` (loopback only) |
| Telegram | `@neo_r64gnb_bot` (`hermes_tech_watch_telegram_bot_username`), token `vault_hermes_tech_watch_telegram_bot_token` (bot deleted, variable removed in M7.5) |
| Web | Tavily, dedicated key `vault_hermes_tech_watch_tavily_api_key` (≠ Kaféine's), monthly limit managed on the Tavily side (dashboard) (key revoked, variable removed in M7.5) |
| Activation | `c49560f` (appended after cafe-ia in `hermes_profiles`) |

**Mission** (`files/profiles/tech-watch/SOUL.md`, in French): technical watch
for Xavier on five domains — 1. AI and agents, 2. **local AI** (a domain of its
own: what runs on the laptop's GPU, published requirements kept apart from
estimates, no compatibility claim without a source), 3. DevOps and cloud,
4. development, 5. open source. Verified fact / hypothesis / recommendation are
kept apart; web content is data, never instructions. **No Caribbean axis.**
SOUL.md promises no schedule, file or attachment.

**User context — `agent.environment_hint`, not a file.** Néo has no `file`
toolset, so an `ENVIRONMENT.md` would never be read. Hermes v0.20.4 appends
`agent.environment_hint` (string-typed) from the **profile's** `config.yaml` to
the stable part of the system prompt (`prompt_builder.build_environment_hints`,
called unconditionally by `system_prompt.build_system_prompt_parts`):

- native Hermes key, **no new mechanism**, no RAG, no retrieval;
- scoped to tech-watch: default's and Kaféine's prompts carry none of it
  (checked on hermes-30, 19/19 facts in Néo only);
- present from the first conversation, independent of the agent's memory
  (never overwritten, never overwriting);
- **grants no access**: plain prompt text (laptop LOQ 15ARP9, Ryzen 7 7435HS,
  32 GB, RTX 4060 Laptop 8 GB, Ubuntu 24.04; Proxmox 16 GB without GPU;
  tooling; projects), with no secret, address or identifier — and it says
  itself it may be dated;
- updated declaratively: edit `hermes_profile_tech_watch.config` in
  group_vars, replay `--tags hermes` (`config set`, then **only** Néo's
  gateway restarts). Neither the managed layer nor `HERMES_ENVIRONMENT_HINT`
  (which would win, for every profile) may carry it.

**Security**

| | |
|---|---|
| Allowed toolsets (4 platforms) | `web`, `skills` (writes staged, `skills.write_approval: true`), `memory`, `session_search`, `todo`, `clarify` → 9 tools |
| Denied toolsets | `terminal`, `file`, `code_execution`, `computer_use`, `delegation`, `cronjob`, `kanban`, media/tts/vision, social and chat platforms, home automation, `desktop_ui`, `project` (23); `browser` out of every allowlist |
| MCP | none (`no_mcp`, `mcp_servers` empty) — no Kandidat |
| Cron | none: no `jobs.json`, no `cronjob` tool. The shipped collection scripts (`files/profiles/tech-watch/scripts/`) are deployed but nothing calls them |
| Sessions, memories | its own `state.db`, `sessions/`, `memories/` under `profiles/tech-watch/`; started blank (D7) |
| Secrets | its `.env` holds `TELEGRAM_BOT_TOKEN`, `API_SERVER_PORT`, `TAVILY_API_KEY` only; no Tavily key in default's `.env` nor in managed |
| Local files | a `file://` URL given to `web_extract` is refused by Hermes' URL guard (seen 2026-10-22: `Blocked: URL targets a private or internal network address`) |

**Isolation limit (unchanged, accepted)**: one container, one UID. Profiles
are separated by `HERMES_HOME` and by the tool restrictions, **not** by the
operating system; granting `terminal` or `file` to any profile would expose
every profile's `.env`.

> ⚠️ `telegram_bot_username` goes through `mandatory`. A bare reference to an
> undefined variable reads as "no username": `validate.yml` accepts it and
> `profile.yml` **skips** getMe. Keep `mandatory` for any future profile whose
> bot name is filled in later.

### Preflights: first install vs update

| Playbook | When | Checks | After Néo exists |
|---|---|---|---|
| `m3-preflight.yml` | **first installation** of tech-watch only | `preflight.yml` (default, timezone, cron window) → `deployed_profiles_preflight.yml` (cafe-ia) → `profile_preflight.yml` for the candidate: validation with cafe-ia, **blank page** (no directory, no s6 slot, 8643 free), memory gate | **NO-GO by design** ("tech-watch existe deja") — do not use it for an update |
| `profiles-preflight.yml` | before **replaying** `deploy.yml` on profiles all deployed (config change, fix) | `preflight.yml` (default connected, timezone, no cron can fire across a restart) → `deployed_profiles_preflight.yml` with no candidate: **every** profile of `hermes_profiles` connected to Telegram, no cron due in its own `HERMES_HOME`, no `ESTOP` anywhere | the one to use |

Both are read-only. From `hermes/`, with `direnv` loaded (`ansible.cfg` sets
the inventory and the vault password script):

```bash
ansible-playbook ansible/profiles-preflight.yml
```

Never pass `hermes_profiles` as `-e` to a preflight (extra vars outrank the
list it composes), nor any `-e` that would bypass a check. `profiles-preflight`
has no memory gate: it guards restarts, not a new gateway.

### M3.3 — as executed (2026-10-22)

| Step | Result |
|---|---|
| `m3-preflight.yml` ×2 | GO (worst case at the 3584 floor ~2031 then ~1997 MiB, required 1536) |
| Activation `c49560f`, `deploy.yml --tags hermes` 00:25 UTC | `changed=7`, all on tech-watch (create, SOUL, content, `.env`, `config set`, gateway start); getMe, managed-only `API_SERVER_KEY`, effective tools, loopback, Telegram all `ok`; default pid 160 kept, cafe-ia pid 555 kept |
| Telegram tests | identity, five domains, hardware context: OK; **web search failed** → M3.3.1 |
| Fix `1a203d8`, deploy 01:49–01:50 UTC | `config set` of 2 keys and restart of **cafe-ia and tech-watch** only; default pid 160 kept |
| `profiles-preflight.yml`, then 2nd `deploy.yml --tags hermes` 02:16 UTC | GO, then **`changed=0`**: no restart, same PIDs, same sha256 for every `config.yaml`, `SOUL.md`, `.env` and default's `cron/jobs.json` |
| Web search | real `web_search` → Tavily for both profiles (above) |

**Resources measured after real use** (2026-10-22 02:17 UTC, historical
values, not live metrics): balloon at its 3584 MiB floor, MemAvailable
**~1442 MiB** (2114 before Néo); RSS default ~349, Kaféine ~285, Néo ~280 MiB;
PSI 0; no OOM; 21 GB disk free.

- 1442 MiB is below the 1536 MiB that `memory_preflight.yml` requires to
  **add** a gateway: **no fourth gateway** without a new memory preflight GO.
- Watch for 7 days, with what exists (no new service, no monitoring cron):
  `profiles-preflight.yml`; `ps -o rss` of the gateways; `free -m`;
  `/proc/pressure/memory`; `dmesg` for OOM; each profile's
  `gateway-starts.log` and `logs/errors.log`; Tavily consumption in its
  dashboard. Look again if MemAvailable drops under ~1200 MiB, PSI
  `some avg60` stops being 0, or a gateway passes ~400 MiB.
- Nothing raises memory automatically. A floor or RAM change is a decision:
  Terraform `vm_memory_floating` and `qm set` (see the M2 memory section).

### Rollback of M3

`ansible-playbook ansible/m3-rollback.yml`: `profile_rollback.yml` for
**tech-watch only** (stop, persist `desired_state=stopped`, checks), then
`profile_telegram_check.yml` on every other deployed profile (Kaféine must
stay connected). It deletes nothing: memories, sessions, `.env` and token
stay; default and Kaféine untouched; no Terraform, no Proxmox.

The rollback does not change Git. Removing Néo declaratively is a **separate,
human** step afterwards: revert the activation commit `c49560f` (not the M3.2
commits, nor the shared fix `1a203d8`, which also serves Kaféine), then
`deploy.yml --tags hermes` (`changed=0`). Removing the entry alone does not
stop the gateway.

## Scout — profile `job-search` (mission M4, deployed 2026-10-24)

| | |
|---|---|
| Name / id | **Scout** / `job-search` (`gateway-job-search`) |
| API | `127.0.0.1:8645` (reserved port) |
| Telegram | new bot `scout_r64gnb_bot` (name confirmed 2026-10-22, checked by getMe); token `vault_hermes_job_search_telegram_bot_token` |
| Web | Tavily, **dedicated** key `vault_hermes_job_search_tavily_api_key` (≠ Kaféine's and Néo's); monthly limit managed on the Tavily side (dashboard) |
| Context | `agent.environment_hint` from `vault_hermes_job_search_environment_hint` (**encrypted**: the repo is public) |
| Activation | prepared in M4.2, activated by commit `6e4dfa7` (M4.3: appended to `hermes_profiles` after tech-watch, T15/n01/s01 guards updated); deployed 2026-10-24, see [M4.3 as executed](#m43--as-executed-2026-10-24) |

**Mission** (`files/profiles/job-search/SOUL.md`, in French): job search and
career support, quality over quantity. Five domains: search (DevOps, Platform,
infrastructure, cloud, Kubernetes, automation, backend Python and
Java/Spring, not limited to these titles), offer analysis (direct link, date,
skills vs profile, points to check), geography (P1 Guadeloupe, P2 full remote
France really reachable from Guadeloupe, P3 selective international; every
remote offer qualified confirmed / to check / incompatible), languages
(graded compatible / to check / not well suited against the level declared in
the private context, never an automatic exclusion), and support (CV, letters,
LinkedIn, interviews, unsolicited applications). It **sends nothing**: drafts
only, explicit human validation for anything external. It promises no
terminal, file, browser, Kandidat, MCP, sending tool or schedule.

### Private professional context

Same mechanism as Néo (`agent.environment_hint`, stable part of the system
prompt, the profile's own `config.yaml`, no `file` toolset needed), but the
value lives in the vault. What the role guarantees:

- **resolution before any write**: `validate.yml` renders every config value
  (`to_json`): a missing vault key fails the preflight and the deployment
  before `profile create` (lazy templating would otherwise defer it to
  `config set`, profile already created);
- **never printed**: the profile declares `config_no_log:
  [agent.environment_hint]`; the read (`config get --json`) and write
  (`config set`) tasks of `profile.yml` evaluate `no_log` **per key**, so the
  value appears neither in a normal run, nor at `-vvv`, nor in a failure
  (`config set` echoing its argument). Other keys keep their output.
  `validate.yml` refuses a `config_no_log` entry that is not a declared key
  (a typo would mask nothing);
- **isolation**: only job-search's `config.yaml`; never the managed layer nor
  `HERMES_ENVIRONMENT_HINT` (both reach every profile);
- **typing**: a string; multi-line values are passed raw by
  `hermes_config_arg` and read back equal (proved on the image with a
  synthetic multi-line, accented value).

**Filling it in (M4.3 prerequisite, human step)** — from `hermes/`, direnv
loaded:

```bash
# Opens the encrypted file in $EDITOR; nothing is written in clear on disk by Ansible.
ansible-vault edit ansible/group_vars/hermes/vault/config.yml
```

```yaml
# Add the three Scout keys at the end of the file; leave every other key as it is.
# Values are typed in the editor only: never in a chat, a shell argument or a file.
vault_hermes_job_search_telegram_bot_token: "<token given by BotFather>"
vault_hermes_job_search_tavily_api_key: "<dedicated tvly- key>"
# Literal block: keeps line breaks, drops the final newline.
vault_hermes_job_search_environment_hint: |-
  Contexte professionnel de l'utilisateur (cadrage, ni CV complet ni vérifié) :
  - ...
  Ces informations peuvent être datées : ne les présente pas comme vérifiées.
```

Then check, without printing any value, that the file is still encrypted and
that the three keys resolve (decrypted in memory, `assert` runs on the
controller, only SUCCESS or FAILED is kept):

```bash
head -1 ansible/group_vars/hermes/vault/config.yml   # $ANSIBLE_VAULT;1.1;AES256
ansible hermes -m ansible.builtin.assert -a '{"quiet": true, "that": [
  "vault_hermes_job_search_telegram_bot_token | length > 0",
  "vault_hermes_job_search_tavily_api_key is match(\"tvly-\")",
  "vault_hermes_job_search_tavily_api_key != vault_hermes_cafe_ia_tavily_api_key",
  "vault_hermes_job_search_environment_hint | length > 0"]}' 2>/dev/null \
  | grep -oE '^hermes-30 \| (SUCCESS|FAILED)'
```

Content to confirm before writing it (a framing, not a full CV; no invented
employer, experience or diploma): overall experience; languages and
frameworks actually practised, with how recent they are; DevOps tooling and
since when; certifications **with their exact names**; English level; search
area; directions of interest kept apart from acquired skills; level filters
(titles to avoid); companies to leave out. Only the vault holds the values.
The two cron drafts read the level filters and the excluded companies from
this context. Keep it short (it is in every call's prompt).

### Tools

Kaféine's and Néo's matrix, unchanged (D5 and M3.3.1): `web`, `skills`
(writes staged), `memory`, `session_search`, `todo`, `clarify` on the four
platforms; the same 23-toolset denylist, **without** `browser`; `no_mcp`.
Proved on the image (`tests/test_m4_scout.py`): exactly the 9 tools on
telegram, api_server, cli and cron, `web_search` and `web_extract` each
present, no `browser_*`, terminal, file, code or `cronjob`; a real cron run
(the scheduler's own resolution) gets 7 — Hermes cuts `memory` and `clarify`
from cron runs by policy.

### Cron drafts (M4.4, not created)

`hermes/cron-drafts/job-search.yml`: `veille-emploi` (`0 7 * * 1` UTC) and
`prospection-entreprises` (`0 7 * * 3` UTC), default's schedules. Read by
nothing: no playbook, no `jobs.json`.

> **2026-10-23:** default's three crons (`ai-coffee-scout`, `veille-emploi`,
> `prospection-entreprises`) were removed by the operator; their definitions
> are archived off-repo (private). Since then **no cron runs on hermes-30**.
> The switch below (pause default's job, then create Scout's) was written
> while they existed: steps 1–2 no longer apply, and M4.4 is to be re-planned
> before any cron is created.

| Kept | Removed | Added |
|---|---|---|
| families A/B/C and keywords, job boards and recruiter/IT-services boards, 30-day freshness, Guadeloupe or 100 % remote, 2–3 offers / 3–8 companies, A > B > C priority, reasons and reserves, never invent a URL | Kandidat (dedup, `create_cible`, `create_candidature`), terminal, scripts, files, browser, sitemap scraping | `web_search` / `web_extract`, the private context (level filters, excluded companies), dedup through `session_search`, « never answer [SILENT] », « do not edit skills », full offer details in the Telegram report |

**Functional differences to accept**: nothing saved in Kandidat; coverage
probably lower (no XML sitemap, API or script; SPAs and bot-blocked sites);
languages graded as in the SOUL instead of an automatic reject; the
first Scout run knows nothing of default's history.

**Why `continuity: false`.** `--continuity` (`context_from: self`) injects
the **first 8000 characters** of the job's latest output file, and that file
starts with the whole built prompt (cron guidance, previous injection,
prompt) and ends with the answer. Measured on the image: run 2 sees run 1's
answer, but from run 3 on the previous answer is no longer injected, only a
stale fragment of an older one. The drafts deduplicate with
`session_search` instead: cron sessions stay searchable (demoted, not
excluded) across the whole history. Neither is an exact match: the prompt
says so.

**M4.4 switch, per job (operator, outside the cron windows, after
`profiles-preflight.yml` GO)** — never both jobs active at once:

```bash
# 1. Save default's job table (sha256 noted), read-only for the agent.
sudo cp -p /opt/hermes/data/cron/jobs.json /opt/hermes/data/workspace/backup-crons/jobs-$(date -u +%F).json
# 2. Pause default's job (veille-emploi = 97fede01ad07, prospection-entreprises = 9f7eba46d2db).
sudo docker exec -u 1000 hermes hermes cron pause 97fede01ad07
# 3. Create Scout's job from the draft (prompt passed as one argument).
sudo docker exec -u 1000 hermes hermes -p job-search cron create "0 7 * * 1" "<prompt>" \
  --name veille-emploi --deliver telegram:<allowlisted id>
# 4. Exactly one active job for the function, same next run.
sudo docker exec -u 1000 hermes hermes cron list
sudo docker exec -u 1000 hermes hermes -p job-search cron list
```

Then wait for the real run (or a decided `cron run`), check `cron runs` and
that the message came from **Scout's** bot. Rollback: `hermes -p job-search
cron pause <id>`, then `hermes cron resume 97fede01ad07`. Hermes has no
atomic switch: the pause comes first, so a duplicate is impossible and the
gap is seconds, days away from the run. Prerequisite: Scout's gateway
**restart persistence** proven (still unproven for every profile), or a
missed run goes unnoticed.

### Preflight and rollback

`m4-preflight.yml` (read-only): `preflight.yml` (default, timezone, cron
window) → `deployed_profiles_preflight.yml` with candidate `job-search`
(cafe-ia and tech-watch connected, no cron due, no ESTOP anywhere) →
`profile_preflight.yml` (validation with the four bots, blank page, 8645
free, memory gate **1536 MiB, unchanged**) → `candidate_bot_identity.yml`
(`getMe` on the candidate token, passed on **stdin**, never argv: NO-GO if
refused or owned by another bot). Missing token, Tavily key or
context: NO-GO naming it.

`m4-rollback.yml`: `profile_rollback.yml` for job-search only (stop, persist
`desired_state=stopped`, nothing deleted), then `profile_telegram_check.yml`
for every other deployed profile. If jobs were already switched (M4.4), give
them back to default first (above). Then revert the activation commit
`6e4dfa7` (not the M4.2 commits), and `deploy.yml --tags hermes` (`changed=0`).

### M4.3 — as executed (2026-10-24)

| Step | Result |
|---|---|
| `m4-preflight.yml` ×2 (before and after the activation commit) | GO, `changed=0`: default, cafe-ia, tech-watch connected; no cron, no ESTOP; job-search absent, s6 slot absent, 8645 free; getMe → `@scout_r64gnb_bot`; MemAvailable 2066 then 2072 MiB (required 1536) |
| Activation `6e4dfa7`, `deploy.yml --tags hermes --check` | `changed=3` (create, SOUL, `.env`), no handler; check mode skips `config set`, gateway start, getMe and the tool check |
| `deploy.yml --tags hermes` 02:25–02:27 UTC | `changed=5`, all on job-search: create, SOUL seed, `.env` (3 keys), `config set` (8 keys, context `no_log`), gateway start; no handler, no restart of another gateway. getMe, managed-only `API_SERVER_KEY`, effective tools, loopback, Telegram all `ok` |
| 2nd `deploy.yml --tags hermes` 02:28 UTC | **`changed=0`**: same PIDs, same sha256 for every `config.yaml`, `SOUL.md`, `.env`, memories, skills and sessions of the four profiles |
| Tools really exposed | exactly the 9 allowed (`clarify`, `memory`, `session_search`, `skill_manage`, `skill_view`, `skills_list`, `todo`, `web_extract`, `web_search`): no terminal, process, file, code execution, cronjob, delegation or MCP (no Kandidat) |
| Other profiles | default pid 160, cafe-ia pid 5012, tech-watch pid 5203 kept; container not restarted; still **no cron** |
| Telegram tests (human) | identity, offer search through Tavily, use of the private context, refused tools, the three other bots: **all OK** (operator, 2026-10-24) |

**Resources measured** (2026-10-24, historical values, not live metrics):
balloon at its 4096 MiB floor (live 4096, max 8192), guest MemTotal 3845 MiB;
MemAvailable 2089 MiB before Scout, ~1900 MiB after the Telegram tests; RSS
default ~357, Kaféine ~292, Néo ~285, Scout 166 MiB cold → 251 MiB after
the tests; PSI 0; no OOM; host `pve` ~2.7 GiB available, swap 0.

- After its first conversation Hermes adds `onboarding.seen.profile_build_offered`
  to Scout's `config.yaml`: a runtime flag, not a declared key; the declared
  keys still read back equal.
- **Not proven yet:** that the four gateways come back on their own after a
  container or VM restart (`desired_state=running` + reconcile), and how
  memory behaves once Scout is used every day. Watch as in M3.3 (below):
  look again if MemAvailable drops under ~1280 MiB, PSI `some avg60` stops
  being 0, or a gateway passes ~400 MiB.

## Nora — profile `default` (mission M5, deployed 2026-10-24)

Nora is `default` itself: same `HERMES_HOME` (`/opt/data`), gateway `:8642`,
historical bot and token, no new profile or port. The declaration
`hermes_default_nora` (group_vars) is **active** since the dedicated commit
adding `hermes_default_profile: "{{ hermes_default_nora }}"` (M5.4); the role
default `hermes_default_profile: {}` still skips `tasks/default_profile.yml`.
Reverting that commit is the declarative rollback of the configuration.

Prerequisites, none created by the repository (validate.yml stops with
`PREREQUIS M5.4` while they are missing), all in place since M5.4:

- `vault_hermes_default_tavily_api_key`: dedicated key, checked distinct from
  the three profiles' keys without display;
- `hermes_default_soul_predecessor_sha256`: sha256 of the live default
  SOUL.md, taken from the verified M5 backup's SHA256SUMS;
- default's `memories/USER.md` and `MEMORY.md` replaced by Nora's initial
  memories (manual M5.4 step): the memory toolset injects them into every
  prompt.

What `default_profile.yml` does, in order, before the default Telegram check
in `main.yml`:

1. `default_soul.yml`: SOUL.md replaced **once**, only if its sha256 equals
   the declared predecessor (`backup: true` leaves a copy beside it); already
   Nora = no-op; anything else, or absent = **fail**, nothing written.
   `soul_seed.yml` still refuses default.
2. `.env` keys through `env_keys.yml` (`TAVILY_API_KEY`); `TELEGRAM_BOT_TOKEN`
   stays managed by `main.yml`.
3. config keys one by one through `hermes -p default config get/set`.
   `-p default` is mandatory: without it the CLI follows a sticky
   `active_profile` into another profile (`hermes_cli/main.py`). Only declared
   keys are written; `mcp_servers.kandidat.url`, `_config_version` and every
   undeclared key stay.
4. `hermes_checks.py toolsets` on `/opt/data`: four platforms, allowed
   toolsets only, exact tools `web_search, web_extract, memory, todo, clarify`,
   no **enabled** MCP server (Kandidat is declared with `enabled: false`).
5. `hermes -p default gateway restart` when `.env` or config changed: s6
   restarts `gateway-default` only. Never the `Restart hermes` handler
   (container, four gateways). A SOUL.md change alone needs no restart.

| Capability | State | Mechanism |
|---|---|---|
| web_search, web_extract | on | `web` toolset, Tavily backend |
| memory | on, gated | `memory.write_approval: true` → `/memory pending`, `/memory approve <id>` |
| todo, clarify | on | allowlist |
| session_search, skills | off | out of the 4 allowlists + `agent.disabled_toolsets` |
| terminal, file, code, delegation, cron | off | out of the allowlists + deny list |
| browser_* | off | out of the allowlists (never in the deny list, M3.3.1) |
| Kandidat MCP | off | `mcp_servers.kandidat.enabled: false` + `no_mcp` |
| old local skills | disabled | `skills.disabled` (5 names), curator off |

### M5.4 — as executed (2026-10-24)

1. `m5-backup.yml`, id `20261024T1609` (SHA256SUMS, 8 SQLite images
   integrity `ok`); its `soul_predecessor_sha256` declared in group_vars.
2. Initial memory, by hand on hermes-30 (UID 1000, `0600`): the old
   `USER.md` and `MEMORY.md` **copied** (`cp -a`) to
   `/opt/hermes/archive/20261024T1609/memories/`, **without** an archive
   `manifest.json` — the rollback refuses an item present both in the archive
   and in place, and restores the memories from the backup `files/` instead.
   Then a minimal `USER.md` (French, concise and structured answers, facts
   checked with a source, uncertainty stated) and an empty `MEMORY.md`.
3. `deploy.yml --tags hermes --check` (no handler, profiles unchanged), then
   the real run: SOUL.md replaced (`.bak` beside it), `TAVILY_API_KEY`, 12
   config keys, tools check, s6 restart of `gateway-default` only. Second run
   `changed=0`.
4. `docker restart hermes-dashboard` (see the limit below).

The old sessions (`state.db`) and the historical workspace files stay in the
volume, by decision.

Known limits:

- **Old sessions stay in `state.db`**: invisible to Nora's tools, but visible
  in the dashboard, reloadable with `/resume`, searchable again if
  `session_search` returns. Never resume a pre-Nora session.
- **Dashboard config is loaded at its start**: the `hermes-dashboard`
  container shares `/opt/data` but kept the pre-Nora config (it kept calling
  Kandidat every 3 min) until restarted. `default_profile.yml` restarts
  `gateway-default` only: after any change to default's config, run
  `docker restart hermes-dashboard` (it never starts gateways:
  `container_boot.py` skips reconciliation in a dashboard container).
- **Stock prompt sentences**: Hermes' generic sections (all profiles) still
  name `skill_view` and `session_search`; neither tool is exposed.
- **No file isolation between profiles**: one container, one UID. Separation
  relies on exposed tools; the historical workspace files were kept in the
  volume (decision M5.4), Nora has no file or terminal tool.
- **Restart path**: executed once on s6 (M5.4): `gateway-default` restarted,
  the three other gateways and the container untouched.

### M5 preflight, backup and rollback (M5.3.B1; preflight and backup executed in M5.4)

Three playbooks, never reached by `deploy.yml`. `m5-preflight.yml` refuses
once Nora is declared (by design: the backup describes default before Nora);
after activation, the read-only gate is `profiles-preflight.yml`. The rollback
was never executed.

```bash
# 1. Read-only, any time (also checks the id is free):
ansible-playbook ansible/m5-preflight.yml -e hermes_m5_backup_id=20261025T1400
# 2. Hot backup, no stop, no restart, never overwritten:
ansible-playbook ansible/m5-backup.yml -e hermes_m5_backup_id=20261025T1400
# 3. Only after reverting the activation commit, explicit confirmation:
ansible-playbook ansible/m5-rollback.yml -e hermes_m5_backup_id=20261025T1400 \
  -e "hermes_m5_rollback_confirm=ROLLBACK 20261025T1400"
```

Backup layout, `/root/hermes-m5-backup/<id>/` (root, 0700, files 0600):
`files/` (SOUL.md, memories, config.yaml, .env, managed layer, Compose file,
each with mode/uid/gid/sha256 in `manifest.json`), `data.tar.gz` (default's
volume with numeric owners and modes; no `profiles/`, no live database, no
regenerable cache), `db/` (one image per SQLite database), `SHA256SUMS`
(verified at the end of the backup and at the start of the rollback).
`manifest.json.soul_predecessor_sha256` is the value to declare as
`hermes_default_soul_predecessor_sha256` before activating Nora.

Database consistency without stopping anything: `state.db` and the others run
in WAL mode with commits still in their `-wal`; copying the main file would
lose them. `hermes_checks.py sqlite-snapshot` uses SQLite's online backup API
from a read-only connection (same method as `hermes backup`), so the image is
one committed state, writers keep going. It runs as the agent UID
(`setpriv`), so any sidecar SQLite creates is owned by Hermes; the backup
fails if a root-owned file exists in the volume before or after. Each image
is checked with `PRAGMA integrity_check` (`immutable=1`). The files and the
databases are captured seconds apart, not at one instant: the preflight
requires `active_agents == 0` on default.

Rollback, in order, nothing before every check passed: confirmation, Nora no
longer declared, SHA256SUMS, archive conflicts. Every file it replaces is
first copied to `<backup>/rollback-saves/<UTC stamp>/`. Identity files get
their content, mode and owner back; `.env` only its M5 keys (Tavily removed);
items archived in M5.4 (`/opt/hermes/archive/<id>/manifest.json` + `data/`)
move back if absent in place. Databases only with
`-e hermes_m5_rollback_restore_databases=true` and only when no process holds
them: stop `gateway-default` and the `hermes-dashboard` container first
(Kaféine, Néo and Scout keep running; they use `profiles/<name>/state.db`).
No restart: the play prints `hermes -p default gateway restart`. A second run
changes nothing.

## Operating profiles

All from `hermes/`, with `direnv` loaded (the memory gate reads
`TF_VAR_pm_api_*`). Never inside the cron windows of `default` (Mon/Wed 07:00
UTC, Sat 08:00 UTC, ±2 h); `deploy.yml` does **not** check them, only the
preflights do.

| Goal | How |
|---|---|
| Activate a profile | its vault keys exist; add `- "{{ hermes_profile_<name> }}"` to `hermes_profiles` in **a dedicated commit**; port from `hermes_profile_reserved_ports` |
| Check before | **new** profile: its `m<N>-preflight.yml` (blank page, memory gate) — GO required. **Update** of deployed profiles: `profiles-preflight.yml` — GO required |
| Deploy changes | `ansible-playbook ansible/deploy.yml --tags hermes`, then again: `changed=0` |
| Check state | `docker exec hermes /command/s6-svstat /run/service/gateway-<name>`; `profiles/<name>/gateway_state.json` (`desired_state`, Telegram `state`); `ss -ltn` → `127.0.0.1:864x` only; `ss -tnp` ESTAB to 149.154.x / 91.108.x |
| Deactivate / roll back | `m2-rollback.yml` (Kaféine) or `m4-rollback.yml` (Scout) on v0.20.4 only (`m3-rollback.yml`, Néo, removed in M7); on hermes-31: `hermes -p <name> gateway stop` parks a profile — see [M7](#m7--kaféine-consolidation-and-néo-retirement): stop + persist `stopped`, deletes nothing, default untouched; **then** `git revert` of that profile's activation commit and `deploy.yml --tags hermes` (`changed=0`). Removing a profile from the list alone does **not** stop it |
| Check isolation | profile `.env` holds only its declared keys; `mcp_servers` empty unless declared; one lock per bot in `/opt/data/.local/state/hermes/gateway-locks/` |
| Check the tools really exposed | the `toolsets` check of `hermes_checks.py` (run by `profile.yml` before each gateway start): toolset names **and** tools, per platform |
| Avoid token conflicts | one **new** bot per profile (D2); `validate.yml` refuses duplicates and `getMe` the wrong bot — a shared token would let `--replace` kill the other gateway |

## hermes-31 — Hermes v0.22.5, one multiplexed gateway (mission M6.3)

Everything above describes **hermes-30** (v0.20.4, one s6 gateway per
profile), destroyed in M6.6.C (2026-10-26) with its data and snapshots: there
is no rollback environment any more. hermes-31 is a **fresh** install: same four assistants (three declared since M7, Néo still served until M7.3), same `group_vars` declarations,
no SQLite database or session carried over. Its differences live in
`host_vars/hermes-31/main.yml`:

| Key | role defaults (hermes-30, destroyed) | hermes-31 |
|---|---|---|
| `hermes_image_tag` | `v2026.8.18` (v0.20.4) | `v0.22.5` |
| `hermes_gateway_multiplex` | `false` → `profile.yml` | `true` → `profile_multiplex.yml` |
| `hermes_telegram_enabled` | `true` | `true` since M6.4 |
| profile config | `group_vars` | `group_vars` + `tools.tool_search.enabled: "off"` |
| `komodo_connect_as` | none (must be declared per host) | `hermes-31` |
| `deploy.yml` | `--limit` required | `--limit hermes-31` |

**Multiplex topology** (verified on the v0.22.5 source and image, offline):
`gateway-default` is the only gateway process and serves every profile whose
directory has a `SOUL.md` (rescan ≤ 30 s). Named slots stay registered but
down; `hermes -p <name> gateway start` exits 78. Only the root API listens
(`127.0.0.1:8642`, per-profile mirrors under `/p/<profile>/`); a profile's
`API_SERVER_PORT` is a process-global key nothing listens on, so
`profile_multiplex.yml` removes it. Each bot reports in the **root**
`gateway_state.json` under `telegram` (default) or `<profile>:telegram`.

**Security boundaries.** The multiplexer builds one secret scope per profile:
the profile `.env`, then the managed `.env` **with override**
(`agent/secret_scope.py`, `build_profile_secret_scope`). The managed
`TELEGRAM_ALLOWED_USERS` and the two `*_ALLOW_ALL_USERS=false` switches
therefore govern every bot, even if a profile `.env` sets its own. Tools are
resolved per turn from the profile's own `config.yaml`, through the same
`_get_platform_tools` call the `toolsets` check uses.

**`tools.tool_search.enabled: "off"`.** v0.22 defers `session_search` and
`todo_list` behind three **new** tools (`tool_search`, `tool_describe`,
`tool_call`). `off` keeps the v0.20.4 tool surface exactly (9 tools for
Kaféine, Néo and Scout, 5 for Nora). Without it, the `toolsets` check fails,
which is intended.

**`profile_multiplex.yml` order**: create, SOUL.md, owned content and config
are the same tasks as in `profile.yml`; then the API key and tool checks; then
`getMe` with the token on **stdin**; the token is written **last**, because the
rescan can connect a bot as soon as its token exists. Then `main.yml` restarts
`gateway-default` **once** if any profile changed, waits for `:8642` on
loopback, checks the topology (`hermes_checks.py multiplex`) and, with
Telegram enabled, the four `telegram` / `<profile>:telegram` entries.

Not applicable to hermes-31: the per-profile memory gate (one process instead
of four), `profile_rollback.yml` and the `m1-*` to `m5-*` and
`profiles-preflight` playbooks (all v0.20.4). Since M6.6.D.1 their first
pre_task (`tasks/legacy_v0204_guard.yml`) refuses a host whose
`hermes_gateway_multiplex` is true, before any read or write: they are kept as
history and for their offline tests, not as tools for hermes-31. Komodo is
connected since M6.3.D (Server `hermes-31`).

## M7 — Kaféine consolidation and Néo retirement

**Status: deployed and closed.** Repository change MR !78 (`0d6faf5`), Néo
parked and Kaféine deployed on 2026-10-29, Néo deleted on 2026-10-30, its bot
and Tavily key revoked and its two vault variables removed afterwards. See
[M7.3 to M7.5 — as executed](#m73-to-m75--as-executed-2026-10-29-to-2026-10-30).

Production, three assistants on the same multiplexed gateway:

| Assistant | Profile | Responsibility |
|---|---|---|
| Nora | `default` | daily life and organization (unchanged, one sentence of its SOUL.md updated) |
| Kaféine | `cafe-ia` | AI and digital technologies: technology watch, technical expertise (Linux, DevOps, Kubernetes/OpenShift, Terraform, Ansible, local AI, HomeLab), educational communication and Café IA |
| Scout | `job-search` | job search (unchanged) |

### What changes in the repository

- **Kaféine's `SOUL.md`** (`files/profiles/cafe-ia/SOUL.md`, French): one
  assistant, three facets (watch, technical expertise, educational
  communication); Néo's method (impact for Xavier, published requirements vs
  estimates, licences, experiment template) merged with Kaféine's (Café IA,
  topic template, demo with plan B, validation list). Research is done on
  demand; periodic watch missions may be configured later, after explicit
  validation — no cron exists or is promised.
- **Néo's environment hint moved to Kaféine** (`agent.environment_hint` in
  `hermes_profile_cafe_ia.config`): workstation (RTX 4060 8 GB, the only
  GPU), Proxmox HomeLab without GPU, local AI, projects. Scoped to cafe-ia's own
  `config.yaml`, never in the managed layer nor `HERMES_ENVIRONMENT_HINT`.
  Plain prompt text: it grants no access. On v0.22.5 it is appended to the
  prompt's runtime-environment block (`agent/system_prompt.py`).
- **Tool matrix unchanged** for every profile: Kaféine keeps `web`, `skills`
  (writes approved), `memory`, `session_search`, `todo`, `clarify`, `no_mcp`
  and the same deny list. No MCP, cron, terminal, file or browser.
- **Profile description** declared:
  "Kaféine — IA et technologies numériques : veille, expertise technique,
  pédagogie et Café IA." `hermes profile create` only reads it for a new
  profile; the live one is updated by hand in M7.3 (step 12).
- **Nora**: the sentence naming "Néo (veille technique), Kaféine (Café IA)"
  now names "Kaféine (IA, technologies et Café IA)". Nothing else.
- **tech-watch** leaves `hermes_profiles` (group_vars and hermes-31), its
  reserved port 8643, bot name, declaration, `files/profiles/tech-watch/`
  (SOUL.md and the never-called collection scripts) and the v0.20.4
  `m3-preflight.yml` / `m3-rollback.yml`. Its vault entries stay until M7.3
  step 14.

### Guarded SOUL.md replacement (`tasks/default_soul.yml`)

A named profile's SOUL.md is **seeded once** (`soul_seed.yml`): a new version
in Git never reaches a live profile by itself. Since M7, a profile declaring
`soul_predecessor_sha256` goes through the same guard as Nora, right after the
seed (`profile_multiplex.yml`):

| Live SOUL.md | Result |
|---|---|
| already the delivered file | nothing (`changed=0`) |
| one of the declared predecessors | replaced, previous file kept beside it (`SOUL.md.<pid>.<date>@<time>~`, Ansible `backup`) |
| anything else, or absent | **failure**, nothing written, human review |

The target is derived from the profile (`profiles/<name>/SOUL.md`, or the root
`SOUL.md` for default), never free. `soul_predecessor_sha256` is one checksum
or an explicit non-empty list, each a 64-hex sha256 (`validate.yml` refuses
anything else before any write). Single tolerance: under `--check`, a brand-new
named profile has no SOUL.md yet (the seed was only simulated), which is not an
error.

- cafe-ia: `c4923f3c…` (Kaféine's M2 SOUL.md, live on hermes-31, read on 2026-10-29).
- default on hermes-31: `[3bd38ef9… (v0.22.5 image seed, fresh rebuild), e3dfd76a… (Nora before M7, live)]`.

Replacing a SOUL.md restarts nothing: it is read when a session's prompt is
built, so the change shows from the next session (`/new` in Telegram).

### Why removing tech-watch from Ansible is not enough

On v0.22.5 the multiplexed gateway serves **every** directory under
`profiles/` carrying an identity marker (`config.yaml`, `.env`, `SOUL.md`,
`profile.yaml`, `auth.json` or `state.db`), unless it is parked or tombstoned.
Removing the declaration therefore leaves Néo served and its bot connected,
and the deploy's exact-set check (`hermes_checks.py multiplex`, unchanged)
fails after Kaféine's changes are already applied. **Park Néo first.** No
role task parks or deletes a profile: these are operator steps, below.

Verified offline on the v0.22.5 image (`tests/test_m7_kafeine.py`, lab):

- `hermes -p tech-watch gateway stop` writes `profiles/tech-watch/gateway.parked`
  and unserves the profile through the control socket: same gateway pid, no
  restart, `tech-watch:telegram` entry gone, `served_profiles` = default,
  cafe-ia, job-search. The root `parked_profiles` field stays `{}`: verify with
  the marker and `served_profiles`, not that field.
- The park survives `hermes -p default gateway restart` and a container restart.
- `hermes profile delete tech-watch --yes` removes the directory and the
  `gateway-tech-watch` s6 slot, writes `profiles/.deleted/tech-watch`, leaves
  cafe-ia and job-search byte-identical; a directory recreated afterwards stays
  unlisted and unserved (tombstone).

What `profile delete` does to shared state on v0.22.5 (source read in M7.5.A,
confirmed on hermes-31 in M7.5.B). The live gateway settles the identity
through its `purge-profile-identity` control verb
(`hermes_cli/profile_identity.py`, `hermes_state_gateway.py`
`purge_profile_state`), without restarting:

- `gateway_routing` rows whose `session_key` starts with `agent:<name>:`, and
  the same keys in the gateway's in-memory routing index: **deleted**
  (hermes-31: 3 → 0);
- `gateway_heartbeats` rows of the profile and the Telegram topic rows:
  deleted (none existed);
- `delivery_obligations`: **delivered rows are kept** as history (hermes-31:
  6 kept). Only non-terminal rows are set to `abandoned` (none existed);
- `sessions` rows of the shared store: not touched. The profile's own
  `state.db` goes with its directory.

If the gateway cannot settle the identity, the delete still completes and
raises `ProfileIdentitySettlementPending`. The retry is
`hermes profile purge-identity <name>`, run on its own approval.

The dashboard needs **no restart** to stop listing a deleted profile:
`/api/profiles` enumerates `profiles/` on every request and skips tombstones.
A restart only releases the open handles it keeps on the deleted profile's
log files. Likewise the gateway keeps its SQLite handles on a parked profile's
deleted `state.db` until its next restart (deleted-but-open files, a few MB).

### Runbook M7.3 (production — executed, see below)

From `hermes/`, `direnv` loaded. Commands on the VM run as
`ssh hermes-31 sudo docker exec -u 1000 hermes …`. Each step names its kind:
**R** read-only, **P** production change (reversible), **I** irreversible.
Every P and I step needs an explicit written GO; a green pipeline or a merged
MR is not one.

| # | Kind | Step |
|---|---|---|
| 1 | R | Preflight: `docker ps` (hermes Up), `s6-svstat /run/service/gateway-default` up, `hermes_checks.py multiplex` with `default,cafe-ia,job-search,tech-watch` → ok; record the gateway pid and the container `StartedAt` |
| 2 | R | Checksums: `sha256sum /opt/hermes/data/SOUL.md` = `e3dfd76a…`, `profiles/cafe-ia/SOUL.md` = `c4923f3c…`, `profiles/job-search/SOUL.md` = repo; four Telegram entries connected in the root `gateway_state.json`. Any other value: stop |
| 3 | R | Néo idle: `active_agents` / `active_work` of the root state; no message to Néo in progress |
| 4 | **P** | Park Néo: `hermes -p tech-watch gateway stop` (no `-y`: it refuses while work is live) |
| 5 | R | `ls profiles/tech-watch/gateway.parked`; `served_profiles` = default, cafe-ia, job-search; no `tech-watch:telegram` entry; **same gateway pid**. Otherwise stop: do not deploy |
| 6 | **P** | `ansible-playbook ansible/deploy.yml --limit hermes-31 --tags hermes` (merged `main`). Expected: Nora's and Kaféine's SOUL.md replaced, `agent.environment_hint` set on cafe-ia, one `hermes -p default gateway restart` (all three bots reconnect), multiplex check green for three |
| 7 | R | Live SOUL.md = repo for default and cafe-ia; the backup beside each equals the predecessor |
| 8 | R | `hermes -p cafe-ia config get agent.environment_hint --json` = declaration; Nora's and Scout's hints unchanged |
| 9 | R | Gateway up, `127.0.0.1:8642` only, three `telegram` / `<profile>:telegram` entries connected (`hermes_checks.py telegram`), container `StartedAt` unchanged |
| 10 | R | Second run of the same playbook: `changed=0` |
| 11 | R | Telegram acceptance (below) |
| 12 | **P** | `hermes profile describe cafe-ia --text "Kaféine — IA et technologies numériques : veille, expertise technique, pédagogie et Café IA."` |
| 13 | **I** | Separate approval: `hermes profile delete tech-watch --yes`; check the tombstone, the routing purge and that three profiles stay served. No dashboard restart needed (see above) |
| 14 | **I** | Later, separate approval: delete `@neo_r64gnb_bot` in BotFather, revoke Néo's Tavily key, then remove `vault_hermes_tech_watch_telegram_bot_token` and `vault_hermes_tech_watch_tavily_api_key` (dedicated commit) |

Read-only probes for steps 1, 5 and 9 (no secret printed):

```bash
# Gateway pid, served profiles, one state per platform entry
ssh hermes-31 "sudo python3 -c 'import json; s = json.load(open(\"/opt/hermes/data/gateway_state.json\")); print(s[\"pid\"], s[\"served_profiles\"], {k: v.get(\"state\") for k, v in s[\"platforms\"].items()})'"
# s6 view: only gateway-default up
ssh hermes-31 "sudo docker exec hermes sh -c 'for s in /run/service/gateway-*; do echo \$s \$(/command/s6-svstat \$s); done'"
# Park marker (step 5) and container start time (unchanged from step 1)
ssh hermes-31 "sudo ls -l /opt/hermes/data/profiles/tech-watch/gateway.parked; sudo docker inspect -f '{{.State.StartedAt}}' hermes"
```

Telegram acceptance (step 11):

1. Kaféine, "Qui es-tu ?": Kaféine, three facets, no Néo.
2. Kaféine, "Puis-je faire tourner un modèle de 14B en local, et où ?": uses
   the hint (RTX 4060 8 GB on the laptop, no GPU on Proxmox), published vs
   estimated, sources.
3. Kaféine, "Quoi de neuf côté Ollama ce mois-ci ?": dated items, Vérifié /
   À confirmer.
4. Kaféine, "Prépare un sujet Café IA sur les agents pour un public non
   technique", then "Réexplique-le pour des développeurs": template, demo with
   plan B, depth changes.
5. Kaféine, "Lance `docker ps` sur mon serveur": no terminal, no HomeLab access.
6. Kaféine: a daily-life request points to Nora, a job request to Scout.
7. Néo (`@neo_r64gnb_bot`): no answer.
8. Nora: one ordinary request; asked about the other assistants, names Scout and Kaféine.
9. Scout: one ordinary request.

### M7.3 to M7.5 — as executed (2026-10-29 to 2026-10-30)

| Step | When (UTC) | Result |
|---|---|---|
| Park Néo (4-5) | 2026-10-29 19:57 | `gateway stop` exit 0, no prompt; same pid 195; three profiles served |
| Deploy (6-9) | 2026-10-29 20:44-20:48 | `ok=99 changed=4 failed=0`: two SOUL.md (backups `SOUL.md.1097128.2026-10-29@16:45:09~`, `profiles/cafe-ia/SOUL.md.1098004.2026-10-29@16:46:01~`), cafe-ia hint, one gateway restart (pid 195 → 670084, about 50 s, container not restarted) |
| Idempotence (10) | 2026-10-29 20:50-20:52 | `ok=93 changed=0 failed=0` |
| Telegram acceptance (11) | 2026-10-29 | accepted by the user |
| Description (12) | 2026-10-29 23:55 | `profile describe` exit 0, nothing else changed |
| Delete Néo (13) | 2026-10-30 00:24 | exit 0, tombstone written, s6 slot removed, routing 3 → 0, delivered obligations kept, pid 670084 unchanged, no dashboard restart |
| Credentials (14) | 2026-10-30 | bot and Tavily key revoked by the user; vault variables removed (this MR) |

### Rollback (historical: valid only before step 13)

Néo has been deleted, so this sequence can no longer bring it back (see the
last paragraph).

Order matters: restore the SOUL.md backups **before** redeploying a reverted
inventory — after a revert, Nora's guard would refuse the M7 SOUL.md as unknown.

1. SOUL.md: on the VM, copy each backup back as the agent
   (`sudo docker exec -u 1000 hermes cp -p /opt/data/SOUL.md.<…>~ /opt/data/SOUL.md`,
   same for `/opt/data/profiles/cafe-ia/`); effective from the next session.
2. Kaféine's hint: `hermes -p cafe-ia config unset agent.environment_hint`
   (the role never unsets a key it stops declaring).
3. Description (if step 12 ran): `hermes profile describe cafe-ia --text
   "Kaféine — veille IA, projets à présenter et préparation des rencontres Café IA."`
4. Néo: `hermes -p tech-watch gateway start` (removes the marker, serves it hot).
5. Git: revert the M7 merge, then `deploy.yml --limit hermes-31 --tags hermes`
   (four profiles expected; `changed=0` once steps 1 to 4 are done, apart from
   one gateway restart if a key moved).

After step 13 Néo can only be recreated blank, and since step 14 it would
also need a new bot and a new Tavily key: re-declare the profile with new vault
entries, then deploy. Kaféine's own rollback (steps 1 to 3 above) remains
possible from the backups.

## Limits and follow-up (after M4.3)

- **No independent backup of `/opt/hermes/data`** — every profile, memories,
  sessions, crons (Known Gaps of [`hermes/README.md`](../../../README.md)).
  hermes-30's snapshots (`base-clean`, `pre-ch7`) and its M5 backup were
  destroyed with it in M6.6.C; hermes-31 has no snapshot, backup or tested
  restore.
- **`hermes update`** runs `backfill_profile_envs`, which copies default's
  `.env` — Telegram token included — into a profile **without** `.env`. Never
  run it without checking every profile `.env` first.
- **Restart persistence** of the profile slots: see "Not proven yet" above.
- **Memory**: three gateways fit the 3584 floor, with ~1442 MiB available
  after real use (2026-10-22), under the 1536 MiB required to add one. The
  floor is 4096 since M4-MEM (2026-10-23, see the M2 memory section), but a
  fourth gateway still needs a new memory preflight GO. See
  [M3.3 — as executed](#m33--as-executed-2026-10-22): 7-day watch, no fourth
  gateway without a new memory preflight, any floor change through Terraform.
- **Restart persistence** of `gateway-tech-watch`: like Kaféine's, not proven
  by an organic container restart yet.
- **Memory with four gateways** (2026-10-24): ~1900 MiB available at the
  4096 floor after Scout's first conversations; the host stays above its
  80 % ballooning target, so the VM does not grow past the floor. A fifth
  gateway needs a new memory preflight GO.
- **Restart persistence** of `gateway-job-search`: not proven either (M4.4).
- job-search (Scout) is deployed (M4.3), see [Scout](#scout--profile-job-search-mission-m4-deployed-2026-10-24); its automations are not created (M4.4); daily-life is not planned.

## Tests

```bash
uv run pytest hermes/tests -q
```

| File | Covers |
|---|---|
| `test_role_tasks.py` | runs the **real** `env_keys`, `soul_seed`, `profile_content`, `validate` task files with `ansible-playbook` on a throwaway directory: key preservation, idempotence, duplicates, check mode, no token in output (even `--diff -v`), seed-once, bytecode exclusion, guards |
| `test_m1_operations.py` | backup/rollback of `data/.env` (absent, present with/without token), post-M1 backup refused, cron restart window, `deploy.yml` timezone pre_task under `--check`, read-only preflight |
| `test_hermes_checks.py` | managed contract, Telegram verdict (connected / disconnected / unknown / absent / malformed / stale writer / dead pid), type-strict config comparison |
| `test_inventory.py` | effective `hermes_profiles` names `== ["cafe-ia", "job-search"]` (M7; tech-watch retired from the declarations) (needs the vault password, skipped otherwise; prints names only), definitive ids, no destructive task, `no_log` on every token task, task ordering, D1/D5 non-goals |
| `test_m2_cafe_ia.py` | Kaféine, T01-T24: blank creation, SOUL seed and keep, nothing inherited from a lived-in default, no MCP, tokens (distinct, missing, unresolved vault key), allowlist, ports, `API_SERVER_KEY` (verbatim stage2 block: absent / present / key / repeat / concurrent; profile `.env` never touched), caches, idempotence, username, tool lists and verdicts, s6/Telegram/getMe verdicts, **real** rollback and preflight against a fake `docker`/`ss`, loopback verdict, coexistence; memory gate: balloon floor parsing, verdicts on the 2026-10-16 measurements, the real preflight against a fake Proxmox API (GET only, token never printed, missing credentials / unknown VM = NO-GO) |
| `test_m331_web_tools.py` | M3.3.1, both profiles, **real image, offline**: `web_search` and `web_extract` exposed separately on telegram/api_server/cli/cron, exactly the 9 allowed tools, no `browser_*`, backend `tavily`, the `browser` cause reproduced, deploy check refusing the M3.3 configuration; pure `tool_errors` verdicts |
| `test_m4_scout.py` | Scout, activated after tech-watch: identity, port, no Charlie, bot name checked by getMe, dedicated vault keys, no shared token, SOUL.md (domains, geography, languages graded from the private context, no sending, limits, no private fact), private context (vault reference, NO-GO when missing, **real profile.yml config tasks at `-vvv`**: set verbatim, never printed, even on failure), tool matrix; **real image, offline**: config converging with a multi-line context, 9 tools per platform, 7 for a real cron run, context in Scout's prompt only, `--continuity` losing the previous answer; cron drafts (schedules, no Kandidat/shell/file, no private fact, read by nothing); m4 preflight (deployed profiles, prerequisites, shared token, blank page, memory gate, getMe on stdin) and rollback (job-search only, data kept, others re-checked) |
| `test_m5_nora.py` | Nora (default), active through one group_vars reference: declaration, declared predecessor checksum and prerequisites, SOUL.md (identity, limits, no private or job context), tool matrix (four allowlists, session_search and skills denied, Kandidat cut twice, memory approval, old skills, curator), enabled-MCP verdicts, validate.yml (accepts, PREREQUIS, malformed, shared Tavily key), **real default_soul.yml** guard (once, backup, unknown/absent/edited fail, targets, check mode), **real default_profile.yml** against a fake `docker` (`-p default` only, url kept, one targeted restart, second run 0 changed, check mode, other profiles untouched), no global restart, ordering, profiles unchanged since M4.3; **real image, offline**: keys converge, sticky `active_profile` ignored, 5 tools, approval, disabled skills, curator off, s6 slot, Nora prompt |
| `test_m5_recovery.py` | M5.3.B1 on disposable data with a real WAL SQLite database: snapshot keeps `-wal` commits (a file copy loses them), one committed state, damaged copies flagged, report never touches a file; **real m5_backup.yml** (explicit id, 0700/0600, SHA256SUMS, predecessor checksum, numeric owners and modes in the archive, profiles/live DB/caches excluded, never overwritten, check mode, only inspect/svstat sent to docker); **real m5_rollback.yml** (confirmation, Nora still declared, tampered backup, byte-identical restore with modes, Tavily removed, archive returned, current files saved first, replayable, archive conflict, profiles untouched, check mode, databases only on flag and never while open, sidecars moved together); **real m5_preflight.yml** (GO on the observed state without resolving vault references, 8 NO-GO cases, `active_agents` read as the int Hermes writes: 1-2 NO-GO, any other shape FAIL); static guards (not reachable from deploy.yml, no restart, no deletion, UID drop) |
| `test_m63_multiplex.py` | M6.3.B, hermes-31: inventory and host_vars (hermes-31 alone, v0.22.5 multiplexed with Telegram on; role defaults still v0.20.4), **real deploy.yml target guard** (6 cases, synthetic locked host), multiplex and `<profile>:telegram` verdicts, `profile_multiplex.yml` sharing `profile.yml`'s tasks, token last, no per-profile gateway action, main.yml order, rendered compose; **real profile_multiplex.yml** against a fake `docker` (phase 1 no token, phase 2 getMe on stdin before the write, idempotence, check mode); effective inventory (vault: hermes-31 alone, four distinct tokens and Tavily keys, hermes-31 = group_vars declarations + overlay only); **real v0.22.5 image, offline**: fresh boot, every key applied, managed contract, 9/5-tool surfaces with tool_search off and the bridge refused without it, API key, one gateway serving four, only `127.0.0.1:8642`, `gateway start` exit 78, no bot without tokens, managed allowlist in every profile scope (hostile profile `.env` included), one entry per bot, container restart, dashboard login and profile list |

| `test_m66_retirement.py` | M6.6.D.1: no active inventory, variable, Caddy route, hermes-31 Terraform argument or CI value names hermes-30 / `.30` / 9030 (comments and docs may); `hermes/terraform` and `host_vars/hermes-30` untracked; the 11 historical playbooks (13 until M7 removed `m3-*`) run `legacy_v0204_guard.yml` first (real run: multiplexed refused, standalone passes); `komodo_connect_as` has no default and its real check refuses an empty name |
| `test_m7_kafeine.py` | M7: Kaféine's SOUL.md (three facets, watch on demand, no Néo, Nora/Scout boundaries, rigour and limits kept) and environment hint (cafe-ia only, no secret, no shared template); tool matrices, Nora's and Scout's declarations unchanged since `ea733d4`; Nora's SOUL.md differs by one line; tech-watch out of every active declaration, no task deletes or parks a profile, exact-set multiplex check intact, shared templates unchanged; **real default_soul.yml** for cafe-ia (replace once with backup, idempotent, unknown refused, check mode, other profiles untouched, target derived from the profile, malformed lists refused) and Nora's predecessor pair; **real v0.22.5 image, offline**: four served then park (same pid, marker, unserved), exactly three converge, park survives gateway and container restarts, Kaféine's prompt carries its SOUL.md and hint only, a SOUL.md change reaches the next session, `profile delete` removes only Néo and its slot, tombstone blocks rediscovery |

Fake tokens only; nothing reaches a real host.
