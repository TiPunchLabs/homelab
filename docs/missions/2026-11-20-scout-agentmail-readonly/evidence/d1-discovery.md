# D1 — Discovery (AC1)

Collected 2026-11-20 by exec-mail01 (session model Claude Opus 5.5). Read-only. Hermes source was read from the local image `nousresearch/hermes-agent:v0.22.5`, RepoDigest `sha256:9c5561579f3f…238d`. That is the digest of the image running on hermes-31 (prior state inventory, re-verified below via `hermes --version`). The source was extracted with `docker create` + `docker cp /opt/hermes` into the session scratchpad; it is not committed. Paths below are relative to `/opt/hermes` in the image.

AgentMail and OWASP primary documentation: `evidence/d1-agentmail-docs.md` (Sonnet subagent, WebFetch on 2026-11-20; context7 was not available).

## 1. Runtime version and deployed configuration (hermes-31, read-only SSH)

Commands: `ssh hermes-31 'docker exec -u 1000 hermes …'` with `sha256sum`, `grep`, and variable-name-only listing (`grep -oE '^[A-Za-z_][A-Za-z0-9_]*='`). No value of any `.env` was read, and no file was written.

| Item | Observed | Repo / expected | Status |
|---|---|---|---|
| Hermes version | `Hermes Agent v0.22.5 (2026.9.24) · upstream bf0203a7` | host_vars `hermes_image_tag: v0.22.5` | VERIFIED, equal |
| Managed `/etc/hermes/config.yaml` | fb2f043f1a02…8f73 | same as the R1 hash recorded 2026-11-14 | VERIFIED, no drift |
| Nora `/opt/data/config.yaml` | 0f3f69484959…14aa | R1/R6 | VERIFIED |
| Scout `profiles/job-search/config.yaml` | 054ec6157ead…41f0 | R1/R6 | VERIFIED |
| Kaféine `profiles/cafe-ia/config.yaml` | c4bc51133ee8…c8aa | R1/R6 | VERIFIED |
| SOUL.md Scout / Nora / Kaféine | 7dc753fe… / a3b4e2c2… / b08468d8… | `files/…/SOUL.md` | VERIFIED, equal |
| Scout `plugins:` key | absent (so `plugins.enabled` resolves to None) | — | VERIFIED |
| Scout `profiles/job-search/plugins/` | empty directory | — | VERIFIED |
| Effective model | managed: `provider: deepseek`, `default: deepseek-v4-flash`, `base_url: https://api.deepseek.com/v1` | `defaults/main.yml:44-48` | VERIFIED |
| AgentMail variables | none in `/opt/data/.env`, Scout `.env`, managed `.env` (names only) | — | VERIFIED absent |
| Profile `.env` modes | 600 (Scout, default) | env_keys.yml | VERIFIED |

These hashes are the "before" baseline for AC11.

## 2. Tool registration (global vs per request)

- `tools/registry.py:462` `ToolRegistry` is a process-global registry with overlays keyed by profile home (`hermes_cli/plugins.py:1119`, `scope_key = hermes_home_key(...)`). The effective tool set of a turn is computed per platform from the profile config (`hermes_cli/tools_config.py:578` `_get_platform_tools`). This design registers no tool and toggles none.
- MCP `readOnlyHint` is used only to decide whether `trust: untrusted` asks for approval (`tools/mcp_tool_handlers.py:53-60`, `_trust_gate_check`). It is a server-declared annotation and grants no authority here. The mail path uses no MCP.
- Plugin hooks: `pre_tool_call` can veto any tool, and veto wins over approve (`hermes_cli/plugins.py:1940-1990`). A `pre_tool_call` callback that times out fails closed (`hermes_cli/plugins.py:1835-1841`). An exception in the dispatch wrapper fails open (`agent/tool_executor.py:671-684`), so the plugin's callbacks must never raise.

## 3. Plugin mechanism (the chosen boundary)

- Discovery is per profile home. `get_plugin_manager()` caches one manager per resolved `HERMES_HOME` (`hermes_cli/plugins.py:1660-1680`). User plugins are read from `<HERMES_HOME>/plugins/` (`hermes_cli/plugins_discovery.py:209`) and load only if listed in that profile's `plugins.enabled` (`plugins_discovery.py:299`). Bundled platform plugins (Telegram) load regardless (`plugins_discovery.py:291-298`), so setting `plugins.enabled` does not disable Telegram.
- Multiplexed routing: each profile's inbound handler enters `_async_profile_runtime_scope(profile_home)` before `_handle_message` (`gateway/run_adapters.py:1710-1728`). Command lookup, hooks and `get_secret` therefore resolve in Scout's scope only.
- Slash command dispatch:
  - `_handle_message` (`gateway/run_inbound.py:1242-1284`) runs `_hm_dispatch_idle_commands`, which calls `_hm_dispatch_quick_and_plugin_commands` (`gateway/run_inbound_hooks.py:209-260`), and then `_hm_run_plugin_handler` (`run_inbound_hooks.py:262-300`).
  - The handler's return value is returned as the reply text. No agent turn is created.
  - `append_to_transcript` is called only from agent-turn code (`gateway/run_turn.py`, `gateway/run_turn_persistence.py`, `gateway/session_transcript.py`). A plugin command reply is therefore not written to Scout's session history.
- Busy session: `_hm_handle_running_session_message` (`run_inbound.py:1280`) and `run_busy.py:1285-1290` leave plugin commands to the busy path, which may queue the event. A queued command re-enters dispatch later; this is NOT exercised end-to-end (no live gateway). It is covered by layer 2 (taint), see the design note.
- `ctx.apost_message(text)` posts into the bound chat and returns a handle with `message_id` (`hermes_cli/plugin_messages.py:25-66,170`).
- Secrets: `agent.secret_scope.get_secret(name)` reads the routed profile's `.env` scope. Under multiplex with no scope it raises; it never falls back to another profile (`agent/secret_scope.py:230-260`).

## 4. Conversation history and the handoff vector found

- History is the session transcript in `state.db` (`gateway/run_turn_persistence.py:285,467-517`), reloaded each turn.
- Telegram reply context: when the owner uses Telegram "reply" on any bot message, the adapter extracts the quoted text (`plugins/platforms/telegram/adapter.py:7078-7102`). `_prepend_inbound_reply_context` then prefixes it to the user message as `[Replying to: "<text>"]` (`gateway/run_inbound.py:1555-1563`), and that prefixed message is persisted. A reply to a mail summary would therefore carry mail-derived text into a privileged Scout turn and into history. Control: layer 1 (`pre_gateway_dispatch` rewrite, `gateway/run_inbound_hooks.py:65-112`) plus layer 2 (taint), see the design.
- `pre_llm_call` receives `session_id`, `user_message`, `conversation_history` and `parent_session_id` (`agent/turn_context.py:798-820`). It is used for taint detection.

## 5. Telegram rendering

- A reply first tries the Bot API rich path from raw markdown, otherwise `format_message` converts markdown to MarkdownV2 (`adapter.py:3637-3700, 5636`). Markdown links, autolinks and bot commands in plain text would become clickable entities. Link previews are disabled only if the adapter extra `disable_link_previews` is set (`adapter.py:603, 1286-1291`); it is not set for Scout.
- Consequence: the plugin renderer must neutralize markdown, URLs, `@mentions` and `/commands` itself. It must not rely on adapter options.

## 6. LLM call options

- `agent.auxiliary_client.call_llm` (`agent/auxiliary_client.py:8016`) has a same-provider transient retry loop and a provider fallback chain (`_call_llm_impl`, line 8151+), so its retries and providers are not bounded by the plugin. Decision: the summarizer calls the DeepSeek OpenAI-compatible endpoint directly with `httpx` (available in the image venv, `httpx 0.28.1`). Settings: one attempt, no redirects, pinned host `api.deepseek.com`, `tools` absent, same model as Scout (`deepseek-v4-flash`), key `DEEPSEEK_API_KEY` from the managed `.env`.

## 7. AgentMail facts used (from d1-agentmail-docs.md)

- Host `https://api.agentmail.to/v0` (EU `api.agentmail.eu`), `Authorization: Bearer`.
- Operations used: `GET /v0/inboxes/{inbox_id}/messages` (list: metadata + preview, `limit`, `page_token`, `next_page_token`) and `GET /v0/inboxes/{inbox_id}/messages/{message_id}` (get: `extracted_text`, `text`, `html`, attachments metadata). Nothing else.
- Read side effects: "messages.get has no documented side effects"; there is no mark-read endpoint (labels change only through `messages.update`, which is never called). Absence of side effects is documented as absence, not as a guarantee.
- Scopes: organization, pod or inbox. Permissions are a whitelist. Omitting `permissions` at creation grants ALL. Read-only = `inbox_read` + `message_read`. Out of scope returns 403 `missing_permission` / `forbidden`.
- Rate limit: no numeric value documented. A 429 carries `rate_limit_exceeded` and `Retry-After`, usually 1 s.
- The official SDK follows redirects by default (`follow_redirects=True`) and retries 2 times. It is not used; a fixed `httpx` transport is used instead.
- MCP server: 47 tools including send/reply/forward/delete. Rejected (see design).

## 8. Paused state-inventory evidence (re-verified, not trusted)

`homelab-etat/.../evidence/s2-live.md` was used as a pointer only. The Hermes version and the config/SOUL hashes in §1 were re-measured in this session. Cron: no `jobs.json`; `hermes/cron-drafts/` was not touched.
