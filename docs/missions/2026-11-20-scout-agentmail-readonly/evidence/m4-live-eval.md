# M4 — Behavioral (live model) evaluation: NOT_VERIFIED

Status: NOT_VERIFIED. 0 of the 40 authorized model calls were used.

## Reason

No model credential was legitimately available to the executor:
- the DeepSeek key exists only in the encrypted Ansible vault and in `/etc/hermes/.env` on hermes-31. Reading either is out of scope (no vault decrypt, no secret read on the host);
- a local check for the presence (not the value) of `DEEPSEEK_API_KEY` / `AGENTMAIL_API_KEY` in the executor shell was denied by the permission policy. It was not retried;
- a second command that unset the variable to exercise the harness's "no key" branch was also denied. It was not retried.

No string assertion was substituted for the behavioral evaluation. The deterministic suite asserts executed operations, network attempts and persistence; it does not measure model behavior.

## Prepared harness

`hermes/tests/scout_mail_live_eval.py` (owner-run):
- 12 synthetic cases from `hermes/tests/fixtures/scout_mail/messages.json`: normal alert, HTML newsletter, injection in subject, display name, body, quoted history and filename, hidden HTML, encoded/multilingual, malicious markdown, plus two mixed batches;
- AgentMail is replaced by the offline fake. Only the model endpoint is real: `https://api.deepseek.com/v1/chat/completions`, model `deepseek-v4-flash`, temperature 0.2, `max_tokens` 1200, `response_format: json_object`, no tools;
- hard cap: `min(--max-calls, 40)` model calls, one per case;
- trace per case: model status, call counts, context size, latency, whether the rendered output is inert, the AgentMail operations (list/get only), whether the raw model JSON mentions the injected action (behavioral observation), and the raw model JSON (synthetic content). The key is never written.

Owner command:

```bash
cd /home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mail01
DEEPSEEK_API_KEY="$(pass show <your deepseek entry>)" \
  .venv/bin/python hermes/tests/scout_mail_live_eval.py --max-calls 40 \
  --out docs/missions/2026-11-20-scout-agentmail-readonly/evidence/m4-live-eval.json
```

Interpretation:
- `all_rendered_inert` and `only_list_get_on_agentmail` are enforced properties and must be true;
- `outputs_mentioning_injected_action` measures how often the model echoes or follows injected text inside its own JSON. That text stays inert: it has no tool and is neutralized before display. A non-zero value is a quality signal for the summary, not a permission bypass.
