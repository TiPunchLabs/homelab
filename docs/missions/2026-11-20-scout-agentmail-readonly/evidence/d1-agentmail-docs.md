# D1 - AgentMail documentation evidence

Retrieval date: 2026-11-20. Method: context7 MCP was NOT available in this session (no matching tool found), so all facts come from WebFetch of official pages (content is a model-summarised markdown conversion of each page; quotes are as returned). Read-only, no credentials used, no API calls to AgentMail.

## Sources (exact URLs)

- https://docs.agentmail.to (landing; nav only)
- https://docs.agentmail.to/llms.txt (index of ~400 pages, .md variants)
- https://docs.agentmail.to/permissions(.md)
- https://docs.agentmail.to/inboxes.md
- https://docs.agentmail.to/messages.md
- https://docs.agentmail.to/errors.md
- https://docs.agentmail.to/knowledge-base/rate-limits.md
- https://docs.agentmail.to/api-reference/inboxes/list.md
- https://docs.agentmail.to/api-reference/inboxes/get.md
- https://docs.agentmail.to/api-reference/inboxes/messages/list.md
- https://docs.agentmail.to/api-reference/inboxes/messages/get.md
- https://docs.agentmail.to/api-reference/inboxes/messages/get-raw.md
- https://docs.agentmail.to/api-reference/inboxes/messages/get-attachment.md
- https://docs.agentmail.to/api-reference/inboxes/threads/list.md
- https://docs.agentmail.to/api-reference/inboxes/threads/get.md
- https://docs.agentmail.to/api-reference/inboxes/api-keys/create.md
- https://docs.agentmail.to/api-reference/pods/api-keys/create.md
- https://www.agentmail.to/docs/integrations/mcp
- https://github.com/agentmail-to/agentmail-mcp and .../main/mcp-manifest.json (partial read, first 100000 chars of 345862)
- https://pypi.org/pypi/agentmail/json and https://pypi.org/project/agentmail/
- https://raw.githubusercontent.com/agentmail-to/agentmail-python/main/src/agentmail/client.py and .../core/http_client.py
- OWASP cheat sheets (section 10)

## 1. Hosts, version prefix, auth

- Production host: https://api.agentmail.to ; version prefix /v0 (example: https://api.agentmail.to/v0/inboxes/{inbox_id}/messages).
- Other servers listed on every API reference page: x402.api.agentmail.to (prod-x402), mpp.api.agentmail.to (prod-mpp), api.agentmail.eu (eu-prod). So an EU regional host exists: api.agentmail.eu. Calendar endpoints return 403 forbidden in EU production (errors page).
- Auth header: "Authorization: Bearer <token>" (required on every endpoint read).
- MCP hosted server uses a different header: "x-api-key" (see section 8).

## 2. REST endpoints (all GET, host https://api.agentmail.to)

- List inboxes: GET /v0/inboxes ; query: limit, page_token, ascending. Response: count, inboxes[], limit?, next_page_token?. Ordered by created_at newest first.
- Get inbox: GET /v0/inboxes/{inbox_id}.
- List messages: GET /v0/inboxes/{inbox_id}/messages ; query: limit, page_token, labels (list), before, after (datetime), ascending (bool), include_spam, include_blocked, include_unauthenticated, include_trash (bool), from, to, subject (repeatable substring filters; all values must match). Response: count, messages[], limit?, next_page_token?. Sorted by timestamp newest first.
- Get message: GET /v0/inboxes/{inbox_id}/messages/{message_id}.
- Get raw message: GET /v0/inboxes/{inbox_id}/messages/{message_id}/raw . Returns JSON {message_id, size, download_url ("CloudFront signed URL ... Expires at expires_at"), expires_at}; it does not return the RFC 822 bytes directly.
- Get attachment: GET /v0/inboxes/{inbox_id}/messages/{message_id}/attachments/{attachment_id} . Returns JSON {attachment_id, size, download_url (signed HTTPS CDN URL), expires_at, filename?, content_type?, content_disposition?, content_id?, text_url? (signed URL of extracted plain text, omitted when none)}. Docs advise fetching a fresh URL rather than storing it.
- List threads (per inbox): GET /v0/inboxes/{inbox_id}/threads ; query: limit, page_token, labels, before, after, ascending. Response: count, threads[], limit?, next_page_token?. Newest first by timestamp.
- Get thread: GET /v0/inboxes/{inbox_id}/threads/{thread_id} ; query: limit (max 100), page_token (next older page). Response: thread fields plus messages[] ("ordered by timestamp ascending", first page holds the newest messages); next_page_token omitted when thread complete.
- Thread attachment (alt): https://docs.agentmail.to/api-reference/inboxes/threads/get-attachment.md (listed, path not read; exact path NOT VERIFIED).
- Organization-wide thread endpoints exist (api-reference/threads/list, search, get, get-attachment) - paths not read.
- Pagination: page_token (request) / next_page_token (response), plus limit and count. Max limit: messages list states 100 only when from/to/subject filters are used ("search-served requests"); messages.search "limit cannot exceed 100"; thread get max 100. A general max for plain list is NOT DOCUMENTED. No default limit documented. No dedicated pagination page in llms.txt.
- Error body: name, message, code (snake_case, branch on this), fix, docs.

## 3. Message object fields

List item (MessageItem) required: inbox_id, thread_id, message_id, labels[], timestamp, from (string), to[], size (bytes), updated_at, created_at. Optional: cc[], bcc[], subject, preview, attachments[], in_reply_to, calendar_event_id, track_opens, opened_at, references[], headers{string:string}, authentication_results, agent_armor.
- Note: list item as documented does NOT include text, html, extracted_text, reply_to (they are absent from the MessageItem field list).

Get (Message) required: same required set. Optional: reply_to[], cc[], bcc[], subject, preview, text, html, extracted_text, extracted_html, attachments[], in_reply_to, calendar_event_id, track_opens, opened_at, references[], headers, authentication_results, agent_armor.

Attachment: attachment_id (req), size (req), filename, content_type, content_disposition (inline|attachment), content_id.

Pre-extracted plain text: yes. messages.md: "Use extracted_text or extracted_html for only the new content ... quoted history and trailing boilerplate are stripped automatically." text and preview come from the text/plain MIME part and may be absent for HTML-only forwarded mail; for forwards read text/html because extraction can drop forwarded content. Attachments also have text_url (extracted plain text) on the attachment endpoint.

authentication_results (spf, dkim, dmarc each pass|fail|none|neutral|softfail|temperror|permerror; spf_domain, dkim_domain, dmarc_domain, arc_sealer): absent on sent messages and on messages received before 2026-09-09.

agent_armor (AgentArmorResult): present only when Agent Armor is on for the organization. status pending|complete|unavailable; complete has verdict clear|review, model, reason, optional manual_override. Webhook events message-security-completed/review/override exist. This is an opt-in prompt-injection/security scan feature; permission agent_armor_release is opt-in. Details NOT READ beyond schema.

## 4. Read side effects and labels

- messages.md: "messages.get has no documented side effects." "messages.update changes labels only." Page does not say whether fetching changes unread.
- "AgentMail doesn't have a dedicated 'mark as read' endpoint": read state is managed by the client via labels (add read, remove unread with messages.update). Implies GET does not change labels, but this is an inference, not a statement.
- Automatic labels: only "opened" is documented as set automatically (with track_opens on send; also sets opened_at). Whether unread/received are auto-set on inbound mail is NOT DOCUMENTED. Labels named received/sent are not named on messages.md ("The page names no received or sent labels").
- Get-message API page: does not say whether the GET changes state.
- Spam, blocked, unauthenticated, trash messages are excluded from list/search by default (include_* params; permissions label_*_read can deny visibility, see section 5).
- Recommended verification before relying on it: a test call on a throwaway inbox comparing labels before/after GET (not done here).

## 5. Permissions and scoped keys

- Model: whitelist. Only fields set to true are granted; omitted/false are denied. On create, if permissions is omitted ALL permissions are granted (inbox api-keys create page); if present only true fields are granted.
- Exact names (permissions page), pattern resource_action:
  - Inboxes: inbox_read, inbox_create, inbox_update, inbox_delete
  - Messages: message_read, message_reply, message_send, message_update, message_delete
  - Label visibility: label_spam_read, label_blocked_read, label_unauthenticated_read, label_trash_read
  - Drafts: draft_read, draft_create, draft_update, draft_delete, draft_send
  - Webhooks: webhook_read, webhook_create, webhook_update, webhook_delete
  - Domains: domain_read, domain_create, domain_update, domain_delete
  - Lists: list_entry_read, list_entry_create, list_entry_delete
  - Metrics: metrics_read
  - API keys: api_key_read, api_key_create, api_key_update, api_key_delete
  - Apps/account: app_connect, app_share_owner, account_update
  - Pods: pod_read, pod_create, pod_update, pod_delete
  - Calendar: calendar_read, calendar_update, calendar_event_read, calendar_event_create, calendar_event_update, calendar_event_delete
  - Opt-in: agent_armor_release
  - errors page also mentions organization_read (needs organization-scoped key).
- Threads have no own permissions: reads use message_read, label updates use message_update, deletes use message_delete.
- Read-only key: pass permissions with only read flags true, e.g. inbox_read, message_read (draft_read, webhook_read optional). Everything else denied. Attachment and raw endpoints presumably need message_read (NOT DOCUMENTED explicitly).
- Scopes: three scopes - organization, pod, inbox. Effective permissions are intersected with scope: an inbox-scoped key cannot gain org-level capabilities (inbox_create, domain_create) even if true. A restricted key cannot create a child key with more permissions (permission_escalation 403). A key cannot outlive its parent (expires_at later than parent returns 403).
- Inbox-scoped key (inboxes.md): "You can create API keys that are restricted to a single inbox ... can only access that inbox's threads, messages, and drafts." Created by API only per that page (no console steps documented): Python client.inboxes.api_keys.create(inbox_id, name="..."). Full key returned only once.
- REST: POST https://api.agentmail.to/v0/inboxes/{inbox_id}/api-keys ; body (all optional): name, expires_at, permissions{...booleans}. Also public-key variant (P-256 JWK). Response: api_key_id, api_key, prefix, name, created_at, pod_id?, inbox_id?, permissions?, expires_at?. Pod-scoped: POST /v0/pods/{pod_id}/api-keys (same body). Org-level: POST /v0/api-keys (named in errors page). Other key endpoints listed: list/get/update/delete under /api-reference/inboxes/api-keys, /api-reference/api-keys, /api-reference/pods/api-keys.
- Console creation of keys: NOT DOCUMENTED in pages read.
- Out-of-scope / missing permission responses (errors.md): 403 with code missing_permission (message stays "Forbidden", fix names the permission); 403 forbidden "The key's scope (organization, pod, or inbox) doesn't cover the resource"; 403 permission_escalation; 403 unrestricted_key_required; 401 codes missing_authorization, invalid_token_type, unknown_api_key, api_key_expired, unauthorized. An expired key can return bare {"message":"Forbidden"} with no code. Denied label visibility: items excluded from lists and "not found" on direct access. Inbox-scoped key changing a restricted setting gets 403.
- Org verification: unverified organization denied request returns 403 missing_permission.

## 6. Rate limits

- rate-limits.md gives NO numeric per-second/per-minute API limits ("generous", higher plans higher).
- Plan sending limits: Free 100 emails/day, 3 inboxes, 0 custom domains; Developer 1,000/day, 10,000/month, 10 inboxes, 10 domains; Startup 15,000/day, 150,000/month, 150 inboxes, 150 domains; Enterprise custom. Self-registered agents: 1 inbox, 10 emails/day to the attached human only.
- 429 Too Many Requests with Retry-After header ("usually 1" second); code rate_limit_exceeded; body message/fix say which limit. Official SDKs retry 429 automatically. Tip: one list call every few seconds per inbox is "plenty"; use webhooks/websockets instead of polling.
- X-RateLimit-* headers on the server: NOT DOCUMENTED on the docs page (the Python SDK reads X-RateLimit-Reset if present).

## 7. Redirects and Python SDK

- HTTP redirect behavior of the API: NOT DOCUMENTED. The only redirect-like mechanism is signed CDN URLs (download_url, text_url, raw download_url) returned in JSON; these are separate fetches to a CDN host (CloudFront signed URL for raw), not 3xx.
- SDK: PyPI package "agentmail", latest 2.0.26, released 2026-11-17 (pypi.org project page). requires_python <4.0,>=3.10. requires_dist: anyio>=4.14.2, httpx>=0.21.2, pydantic>=1.9.2, pydantic-core>=2.18.2, typing_extensions>=4.0.0, websockets>=12.0. Repo: https://github.com/agentmail-to/agentmail-python.
- Uses httpx (core/http_client.py imports httpx; httpx.Client / httpx.AsyncClient).
- Redirects: client.py has parameter "follow_redirects: typing.Optional[bool] = True" and builds "httpx.Client(timeout=_defaulted_timeout, follow_redirects=follow_redirects)" - so the default SDK client FOLLOWS redirects (default True); it has no effect if a custom httpx_client is passed. http_client.py itself does not set follow_redirects. Implication for SSRF/credential-leak hygiene: pass follow_redirects=False or a custom httpx client. Source was read from main branch, not pinned to the 2.0.26 tag.
- Other SDK facts: default timeout 60 s; environment selects host (AgentMailEnvironment.PROD default; no base_url arg in the signature read); retries: default 2, on 5xx and 429/408/409, delay from Retry-After or retry-after-ms (cap 60 s), else X-RateLimit-Reset, else exponential backoff from 1 s with jitter.

## 8. MCP server

- Hosted: https://mcp.agentmail.to/mcp (streamable HTTP). Auth header x-api-key: ${AGENTMAIL_API_KEY}; OAuth also supported (OAuth-only tools list_organizations, select_organization). Claude Code: claude mcp add --transport http agentmail https://mcp.agentmail.to/mcp.
- Stdio bridge package: agentmail-mcp (npm, Node 20+; PyPI via uvx agentmail-mcp), repo https://github.com/agentmail-to/agentmail-mcp, key passed via AGENTMAIL_API_KEY env. llms.txt also gives https://docs.agentmail.to/_mcp/server (docs-search MCP, unrelated to mailbox tools; not read).
- Tools (47 plus 2 OAuth-only, per docs page): inboxes list_inboxes, search_inboxes, get_inbox, create_inbox, update_inbox, delete_inbox, authorize_inbox; threads list_threads, search_threads, get_thread, update_thread, delete_thread; messages list_messages, search_messages, send_message, reply_to_message, forward_message, update_message, get_message; drafts create_draft, list_drafts, get_draft, update_draft, send_draft, delete_draft; attachments get_attachment; calendar get_agenda, get_event, create_event, update_event, delete_event, respond_to_invitation, get_calendar, update_calendar; lists list_list_entries, get_list_entry, create_list_entry, delete_list_entry; agent sign-up agent_attach_human, agent_verify; apps list_apps, search_apps, get_app, connect_app; accounts list_accounts; labs get_labs, join_labs; orgs list_organizations, select_organization.
- Includes send/reply/forward/delete tools: yes (send_message, reply_to_message, forward_message, send_draft, delete_*).
- readOnlyHint: not on the docs page, but mcp-manifest.json (generated contract) shows annotations. Visible portion: readOnlyHint true for list_inboxes, search_inboxes, get_inbox, list_threads, search_threads, get_thread, get_attachment, list_messages, search_messages; false for create_inbox, update_inbox (destructiveHint true), delete_inbox, update_thread, delete_thread. Rest of manifest (get_message etc.) NOT READ.
- Filtering: the stdio bridge accepts "--tools name1,name2" (comma-separated) for a filtered catalog; hosted-endpoint filtering NOT DOCUMENTED. A read-only API key (permissions) is the server-side enforcement alternative.

## 9. Webhooks / websockets (existence only)

- Webhooks: https://docs.agentmail.to/webhooks-overview.md, webhook-setup.md, webhook-polling.md, webhook-verification.md; events include message-received, message-security-completed, message-security-review, message-sent, etc.
- WebSockets: https://docs.agentmail.to/websockets.md and /api-reference/websockets/websockets.md. Out of scope.

## 10. OWASP cheat sheets (all fetched 2026-11-20; no last-updated date shown on any page)

### LLM Prompt Injection Prevention Cheat Sheet
URL: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html . Title: "LLM Prompt Injection Prevention Cheat Sheet (OWASP Cheat Sheet Series)". Last updated: not shown.
- Treat external content (email, web pages, documents) as untrusted; screen before the model reads it; check documents for hidden text (rendered vs extracted).
- Enforce tool permissions outside the model; validate tool arguments and caller permissions in execution code; least data/operations per tool.
- Human approval of the exact action, target and arguments for high-impact actions; execution component verifies approval.
- Treat model output as untrusted at every downstream use (safe HTML rendering, parameterized queries).
- A guardrail model may check proposed tool calls against user intent but supplements deterministic controls.
- Memory poisoning: no dedicated control; treat stored memory/conversation history as untrusted input.

### AI Agent Security Cheat Sheet
URL: https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html . Title: "AI Agent Security - OWASP Cheat Sheet Series". Last updated: not shown.
- Indirect injection: all external data (retrieved docs, API responses, emails) untrusted; sanitize before adding to context; delimiters between instructions and data; optionally a separate LLM call to validate/summarize untrusted content.
- Tool restriction: only tools the task needs, each scoped (read-only vs write, specific resources); "Fail closed for unknown tools or missing approval requirements."
- Authorization enforced in the execution component outside agent context; approvals bound to exact actor, tool call and parameters, consumed atomically.
- Human approval for medium/high/critical-risk actions; separate decision from execution (independent policy service).
- Output handling: validate outputs before execution/display, structured outputs with schema validation, filter for sensitive data leakage.
- Memory poisoning: validate/sanitize before storing in memory, isolate memory per user/session, expiration and size limits, integrity checks for long-term memory.

### Server Side Request Forgery Prevention Cheat Sheet
URL: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html . Title: "Server Side Request Forgery Prevention (OWASP Cheat Sheet Series)". Last updated: not shown.
- Allowlist destinations; build requests with fixed scheme/port/path ("Deny-lists are bypass-prone. Prefer allow-lists.").
- Do not accept full URLs from users; accept validated IP/domain; reject hosts parsed differently across parsers.
- Disable HTTP redirects in the client (relevant: agentmail SDK defaults follow_redirects=True).
- Prevent DNS rebinding: validate resolved IPs and connect only to them, keep Host/SNI/cert for original hostname; same rules on retries.
- Normalize IPv4-mapped IPv6 and NAT64 before blocking; block 169.254.169.254, private and link-local ranges.
- Restrict network egress by firewall/segmentation.

## Gaps (NOT DOCUMENTED or NOT VERIFIED)

- Whether unread/received labels are auto-applied on inbound mail; whether GET message mutates labels (only "no documented side effects").
- General max for limit on plain list calls; default limit.
- Console method to create scoped keys; whether the attachment/raw endpoints require only message_read.
- X-RateLimit-* response headers; numeric API request rate.
- API redirect behavior; hosted MCP tool filtering; full readOnlyHint list (get_message, list/get drafts) beyond manifest first 100000 chars.
- Exact path of inbox thread attachment endpoint (listed under inboxes/threads/get-attachment.md, not read).
