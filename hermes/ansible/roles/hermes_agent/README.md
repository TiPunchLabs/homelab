# Role: hermes_agent

Deploy Hermes Agent (v0.20.4, image `nousresearch/hermes-agent:v2026.8.18`) on
**hermes-30** as one Docker Compose stack, and prepare it to host several
**profiles**: one s6-supervised gateway and one Telegram bot per profile, all in
the same container.

> **Current state (mission M2, phase A).** Only the `default` profile runs.
> `hermes_profiles: []` in `group_vars`. **Kaféine** (`cafe-ia`) is fully
> prepared (`hermes_profile_cafe_ia`, below) but not activated: it enters the
> list in phase B, once its two vault keys exist.

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
restrictions (later missions, D5) and SOUL rules. Real isolation would need one
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
hermes_profiles:            # group_vars — EMPTY in M1
  - "{{ hermes_profile_tech_watch }}"   # added in M3, not before

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

Resolved with the gateway's own code (`tools_config._get_platform_tools`) in
a lab container: telegram, cron, api_server **and cli** expose exactly
`web_search, web_extract, memory, session_search, skills_list, skill_view,
skill_manage, todo, clarify` (an unrestricted profile exposes 18 tools,
`terminal`, `read_file`, `write_file`, `execute_code`, `delegate_task`… included).

| Toolset | Allowed | Why | Risk |
|---|---|---|---|
| `web` (search, extract) | ✅ | the core of the mission | prompt injection from pages; SOUL tells it page content is data |
| `memory` | ✅ | capitalise topics and meetings | low, own profile only |
| `session_search` | ✅ | recall past conversations | low, own sessions only |
| `skills` | ✅ ⚠️ | bundled research skills (`grounded-citations`, `arxiv`, `competitor-news-monitor`) | `skill_manage` comes with it; its writes are **staged** (`skills.write_approval: true`), see below |
| `todo`, `clarify` | ✅ | multi-step work, questions | none |
| `terminal`, `process`, `code_execution` | ❌ | not needed | shell as UID 1000: every token of every profile, LAN |
| `file` | ❌ | drafts go in the chat | `HERMES_WRITE_SAFE_ROOT=/opt/data` = all profiles; reads `/etc/hermes/.env` |
| `browser`, `computer_use` | ❌ | `web_extract` reads pages | can fill and submit forms: publishing without validation |
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
would restrict `default` too): `platform_toolsets.{telegram,cron,api_server}`
(allowlist) and `agent.disabled_toolsets` (denylist applied **last**, on every
platform). Ansible sets them with `hermes config set`, type-strict compared, and
`Verify that the declared tool restrictions are effective` re-resolves them
with Hermes' code **before** the gateway starts. A toolset name unknown to
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

`hermes/terraform` now says `vm_memory_floating = 3584`, like Proxmox: its
plan shows no `memory` change (only an older cloud-init DNS drift, to settle
separately). `bpg/proxmox` 0.96.0 would **reboot** hermes-30 for a floor
change that Proxmox applies live (`qemu-server`, PVE 9.1.1: only
enabling/disabling the device is not hotpluggable; `reboot_after_update`
defaults to `true`), so floor changes go through `qm set`, and **never
`apply` hermes from a branch that still says 2048** (`main` before M2).

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

### Phase B only (not provable before deployment)

Telegram really connected with the real token; a reply from DeepSeek through
Kaféine (level 4, human); `default` still answering; memories written under
`profiles/cafe-ia/`; restart persistence of both slots on hermes-30; resources
measured after; the second `changed=0` on the real host.

## Tests

```bash
uv run pytest hermes/tests -q
```

| File | Covers |
|---|---|
| `test_role_tasks.py` | runs the **real** `env_keys`, `soul_seed`, `profile_content`, `validate` task files with `ansible-playbook` on a throwaway directory: key preservation, idempotence, duplicates, check mode, no token in output (even `--diff -v`), seed-once, bytecode exclusion, guards |
| `test_m1_operations.py` | backup/rollback of `data/.env` (absent, present with/without token), post-M1 backup refused, cron restart window, `deploy.yml` timezone pre_task under `--check`, read-only preflight |
| `test_hermes_checks.py` | managed contract, Telegram verdict (connected / disconnected / unknown / absent / malformed / stale writer / dead pid), type-strict config comparison |
| `test_inventory.py` | effective `hermes_profiles == []` (needs the vault password, skipped otherwise), definitive ids, no destructive task, `no_log` on every token task, task ordering, D1/D5 non-goals |
| `test_tech_watch_collect.py` | the tech-watch collector |
| `test_m2_cafe_ia.py` | Kaféine, T01-T24: blank creation, SOUL seed and keep, nothing inherited from a lived-in default, no MCP, tokens (distinct, missing, unresolved vault key), allowlist, ports, `API_SERVER_KEY` (verbatim stage2 block: absent / present / key / repeat / concurrent; profile `.env` never touched), caches, idempotence, username, tool lists and verdicts, s6/Telegram/getMe verdicts, **real** rollback and preflight against a fake `docker`/`ss`, loopback verdict, coexistence; memory gate: balloon floor parsing, verdicts on the 2026-10-16 measurements, the real preflight against a fake Proxmox API (GET only, token never printed, missing credentials / unknown VM = NO-GO) |

Fake tokens only; nothing reaches hermes-30.
