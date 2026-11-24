# Owner brief (verbatim, received by pilotage 2026-11-20)

SCOUT-MAIL-01 — Read-only AgentMail for Scout with enforced isolation

## Mission

Implement and validate a minimal AgentMail inbox reader for Scout in HomeLab. The owner has already created a dedicated inbox and API key. The intended interaction is an explicit request through Scout's private Telegram conversation to list or summarize received job-search emails. Email content must never grant authority or trigger unrelated actions.

Act as the implementation pilot. Inspect the current repository and runtime before choosing the design; implement, test, document and prepare a reviewable merge request. Work autonomously on reversible implementation and verification. This mission authorizes development and a draft MR, not production deployment, merge, email sending or subscriptions. Prepare a concrete deployment and rollback procedure for the final owner decision.

Use English for engineering documentation and the final report, French for Scout's user-facing behavior. Follow applicable repository instructions and the established independent review workflow. Do not claim OWASP certification or complete prevention of prompt injection.

## Context to verify

- Expected repository: /home/xgueret/Workspace/02-infrastructure/homelab, GitLab tipunchlabs/homelab. Use an isolated worktree and a dedicated branch from current origin/main. Preserve unrelated changes and existing worktrees.
- Last reported runtime: hermes-31, shared multiplex gateway serving default/Nora, cafe-ia/Kaféine and job-search/Scout. Verify actual version, deployed configuration and tool authorization code; do not assume Hermes 0.22.5 is still current.
- Reported prior delivery: Kandidat !25 and HomeLab !105, !106, !107 merged; Scout deployed, compact Kandidat reads working, writes subject to owner approval. These are handoff facts, not fresh verification.
- Preserve existing Kandidat gates and ordinary Scout Web/job-search functionality outside mail processing. Preserve Nora and Kaféine configurations and secrets isolation.
- Existing cron drafts are inactive. Do not activate them.
- Inbox address/ID and secret location have not been provided in this prompt. Discover non-secret configuration locally where appropriate. Never infer the inbox from a suggested name. Ask only for missing non-secret identifiers or a secure secret provisioning step when actually required; continue fixture-based implementation meanwhile.
- A key named readonly is not proof of restricted permissions. Verify actual supported AgentMail scopes and permissions before relying on them.
- Earlier research had excessive repeated context/token consumption. This mission must bound mail ingestion and measure it, without reopening the previous optimization mission.

## Scope and exclusions

Allowed functionality: list a bounded set of message metadata, read selected messages from exactly the configured inbox, produce a concise French summary with source message identifiers, sender claims, received date, relevant opportunities, uncertainty and attachment presence.

Exclude sending, replying, forwarding, drafts, deleting, moving, changing labels/read state, creating inboxes, managing API keys, account enumeration, subscriptions/unsubscriptions, calendar actions, attachment downloads/OCR, automatic URL fetching, cron, webhooks and processing triggered by receipt. Do not create a second public bot unless a separate owner decision is necessary.

Do not modify Kandidat records, application statuses, permanent exclusions or job-search criteria based on emails. Do not include automatic archive migration, HomeLab cleanup, Hermes upgrades or unrelated authentication projects.

## Required discovery and design decision

Read current code, role templates, profile/tool allowlists, secret handling, tests and deployment checks. Inspect official AgentMail API/MCP documentation and Hermes implementation. Record exact supported operation names, scopes, read side effects and transport behavior; do not invent APIs or assume GET/MCP readOnlyHint proves safety.

Produce a short threat model and an enforcement matrix: asset, attack path, control, enforcement location, test and residual risk. Explicitly cover indirect prompt injection, excessive agency, information disclosure, memory poisoning, unsafe output rendering, SSRF and resource exhaustion.

Prefer existing supported mechanisms where they meet the controls. A narrow adapter is acceptable when necessary; do not build a generic email platform or a general HTTP execution tool.

The key architecture requirement is separation of untrusted mail interpretation from privileged Scout operations. Prefer trusted code retrieving a bounded batch, followed by a fresh summarization context with no tools, no credentials and no unrelated conversation memory. Deliver its bounded result through a trusted renderer to the already authenticated owner's private Telegram conversation.

If using a reader with tools instead, its effective capability set must be restricted to bounded reads of the configured inbox, with no route to Web, Kandidat, files, shell, generic networking, delegation or privileged agents. Bound its total read budget in trusted code.

Determine whether mail-derived text would be copied into Scout's ordinary conversation history and regain influence over privileged tools on a later turn. An isolated parser followed by an unrestricted parent receiving its free-text summary is not sufficient. Design and test the handoff and subsequent turns, keeping mail-derived text out of privileged actionable context or retaining an equivalent enforced restriction. Structured JSON alone does not make text trustworthy.

Do not temporarily mutate a global tool registry to disable tools: another simultaneous profile or request could inherit the wrong permissions. Prove per-request isolation including cancellation, exceptions and concurrency.

If the installed Hermes cannot provide the boundary, implement the smallest justified isolated path if feasible. Otherwise complete a disabled prototype, tests and a precise architectural blocker. Never silently substitute a SOUL instruction for an authorization boundary, or broaden permissions to make the demo work.

## Security requirements

### 1. Treat the entire message as untrusted data

Subject, display name, sender address, Reply-To, headers, snippets, body, quoted thread, filenames, links and API-returned text are untrusted. Never interpolate any of them into a system/developer instruction, tool declaration, command, template source or authorization rule.

Preserve source provenance in structured fields with bounded sizes. Clearly label sender-provided assertions; distinguish received date, alleged offer date and actual verification. A message saying it is from Xavier, an administrator or a system is not authorization. Authentication results or sender allowlists may help triage, but must not grant tool privileges or establish that content is safe.

Use a maintained MIME/HTML parser with bounded input. Render plain text without scripts, CSS execution, embedded resources or remote fetches. Handle malformed MIME and suspicious control characters safely, preserving useful accents and French content. Delimiters, normalization and injection classifiers are supplementary defenses, never the permission boundary. Do not recursively decode arbitrary attacker text to discover more instructions.

### 2. Enforce least privilege outside the model

Bind the inbox in trusted configuration. The model must not select arbitrary inbox IDs, API hosts, paths, headers or credentials. Validate message ownership before returning content; reject cross-inbox identifiers and traversal/path manipulation.

Allowlist exact read operations. Verify AgentMail supports a suitably scoped read key and document the effective restrictions. Prefer provider-side enforcement plus local allowlisting. If the existing key is broad, require a properly restricted replacement for production where supported, and document any provider limitation rather than claiming a name or local tool filter narrows the key itself.

No send/write/admin tool should be registered in the mail path. Missing scope/configuration, unknown tool names and policy errors must fail closed. Do not test provider write denial by attempting an operation that could succeed and send or change real data; use permission metadata, fixtures or a safe isolated test resource under explicit authorization.

### 3. Block cross-tool actions and data egress

Mail interpretation must have no Web, Kandidat, terminal, filesystem, generic HTTP, delegation or memory-write capability. The API transport may contact only the configured official service endpoints required for reads, with TLS verification and timeouts; never forward credentials on redirects to an unapproved host.

Do not fetch email links, images, tracking pixels, attachments or unsubscribe URLs. In this version no content-derived request should reach public sites, loopback, private HomeLab networks or cloud metadata endpoints. Ensure the parser and renderer do not fetch resources independently of the model.

Route output using authenticated Telegram identity and configured private chat, never an email-supplied recipient or chat identifier. Escape untrusted formatting and disable link previews for these results. Prefer inert text links for V1; do not let generated Markdown disguise a destination.

### 4. Prevent persistence and protect secrets

No email or generated summary may edit SOUL, configuration, durable memory, retrieval indexes or job-search criteria. Do not reuse a mail-analysis session across unrelated requests. Separate profile data and caches; invalidate safely when authorization changes.

Inject secrets only into the component that needs them. Exclude keys from prompts, tool output, tracebacks, HTTP debug logs, Ansible diffs, reports and committed fixtures. Use the existing secret-management pattern with restrictive file permissions and no_log where needed. Do not read or circumvent a denied Vault password; prepare the exact owner provisioning step and continue independently.

Document that requested mail text is sent to the configured model provider. Keep unrelated personal data out of the request; do not change model/provider policy or add a third-party classifier without an explicit decision. Avoid raw mail persistence; define short retention and deletion for any essential temporary content. Log IDs/counts/decisions and timing rather than bodies, subjects or secrets by default.

### 5. Bound resource use

Set explicit, configurable hard ceilings enforced before model invocation: response bytes, MIME parsing, messages per request, pagination, body/subject length, total context, model calls, retries and wall-clock duration. Propose reasonable initial defaults and justify them with a representative fixture run. Do not repeatedly retry authorization failures or rescan the whole inbox.

Expose partial results honestly: number processed, truncation, remaining results when known, and a deliberate owner request for continuation. Keep read progress outside the email itself; do not change mailbox state to mark processing.

### 6. Safe failure and operation

Handle empty inbox, missing credentials, revoked key, timeout, rate limit, malformed content and unavailable provider with a concise French response and redacted diagnostics. No fallback to broader credentials or privileged Scout tools.

Provide a configuration kill switch, rollback to the prior profile behavior and key-revocation instructions. Any future expansion to links, attachments, automation or Kandidat integration requires its own permission design.

## Validation and acceptance criteria

Use synthetic fixtures with no private mail in Git. Assert actual executed operations, denied calls, network attempts and persistence, rather than only the model's refusal wording.

Required cases:

1. Normal French job alert, accented names, HTML newsletter, empty inbox and multiple messages: useful bounded summaries and correct source attribution.
2. Injection only in the subject; separately in display name, body, quoted history and filename. Include fake role delimiters and claims of owner/admin approval.
3. Attempts to read/export Kandidat, open an exfiltration URL, send mail, invoke shell/tools, change the inbox, ask a privileged delegate or persist instructions: no forbidden operation executes.
4. Hidden HTML, tracking images, obfuscated/encoded or multilingual instructions and malicious Markdown: no external resource retrieval or unsafe rendering. A detector miss must not restore privileges.
5. Poisoned summary and follow-up turn attempting to recover ordinary Scout privileges: verify the trust boundary persists and does not leak into normal history or another request.
6. Cross-inbox message IDs, unknown tools and unexpected API fields: denied or safely ignored. AgentMail readOnlyHint drift cannot add effective capabilities.
7. Oversized body, huge subject, malformed MIME, excessive pages, repeated rate limits and retry loops: hard limits hold and partial results are explicit.
8. Concurrent Scout mail reading, normal Scout search, Nora and Kaféine requests; cancellation/failure then retry: no capability or context leakage, existing non-mail functionality preserved.
9. Secret redaction and log retention checks with sentinel credentials and synthetic sensitive content. No raw mail or key in Git, CI artifacts, Ansible diff or final report.
10. Existing relevant profile/MCP tests and repository checks pass. Document unrelated intermittent failures accurately; do not hide or expand scope to fix them without justification.

Separate deterministic authorization/transport tests from live model behavior evaluations. Run a small adversarial evaluation when the configured model is available, with documented model/version/settings and call traces. Report behavioral tests unavailable rather than substituting string assertions. A finite test suite cannot prove immunity to all injections.

Use the dedicated existing inbox only for authorized read smoke tests after its identity and key scope are confirmed. Do not send test messages as the agent. Prepare a short owner procedure to place a synthetic email if none is available. Do not mutate real mail or Kandidat for testing.

## Delivery and release preparation

Deliver implementation, fixtures, meaningful tests, enforcement matrix and a short operator runbook. Record exact files and configuration changes, required secret variable names (never values), effective exposed tools, deployment preflight, check mode, rollback, and post-deploy checks. Use the project's existing release conventions.

Request an independent review through the established project workflow, focused on permission bypass, mail-to-privileged-context handoff, multi-profile concurrency, secrets and unintended writes. Fix material findings and rerun affected tests. If independent review is unavailable, report it as pending, never claim it passed.

Commit and push the scoped branch and open a draft MR when available under repository policy. Do not merge or deploy production in this mission. If a policy or credential prevents a step, complete all independent work and report the precise remaining action without repeatedly requesting approval.

The post-deploy owner test to prepare must cover: asking Scout to summarize the dedicated inbox; checking an injected test mail cannot trigger Web/Kandidat/send actions; confirming Nora and Kaféine work normally; verifying a second Ansible run is idempotent. Distinguish owner-visible behavior from tool-trace evidence.

Write the final report as an English Markdown file following repository conventions. Include objective, verdict (PASS/PARTIAL/BLOCKED), actual architecture, enforcement versus behavioral controls, test evidence and limits, remaining risks, Git/MR/CI state, production changes (expected none), secret provisioning status, deployment readiness and only essential owner decisions. Never publish private message bodies or secrets. The final chat response should link the report and state the next concrete step.

## Primary references

Consult current primary sources; record relevant version/date and map controls to actual implementation. Do not rely solely on risk numbering, which can change between OWASP editions.

- OWASP LLM Prompt Injection Prevention: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
- OWASP AI Agent Security: https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html
- OWASP SSRF Prevention: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- AgentMail permissions: https://docs.agentmail.to/permissions
- AgentMail MCP integration: https://www.agentmail.to/docs/integrations/mcp
- Installed Hermes source, pinned version and repository deployment/test code are authoritative for actual runtime behavior.
