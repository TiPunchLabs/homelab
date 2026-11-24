# Report — homelab/2026-11-24-scout-mail-enable

Verdict: BLOCKED
Version: 88c8cf9

## Executive summary

- Objective: enable Scout mail (`/courriels`) by a two-value commit and deploy it to hermes-31 with `--tags hermes`.
- Done: E1 (enabling commit `88c8cf9`), E2 (offline tests run), E3 (before state recorded, read-only), E7 (branch pushed, draft MR).
- Blocked at E2: one offline test fails as a direct consequence of the E1 commit. `test_role_04_only_scout_declares_the_plugin_and_no_key_in_declarations` asserts the disabled state of group_vars.
- Not done: E4 (check mode), E5 (deploy), E6 (after state). Nothing was changed on hermes-31. No AgentMail or Telegram action. The vault was not viewed or decrypted.
- The objective is not reached. An owner decision is needed (section "Decisions required").

## Initial state and scope

- Worktree `/home/xgueret/Workspace/02-infrastructure/.worktrees/homelab-mailon`, branch `feat/scout-mail-enable` from `origin/main` `4355209` (MR !109 merged).
- Remote checked: `origin git@gitlab.com:tipunchlabs/homelab.git`.
- Host examined (read-only): hermes-31.

## Work performed

### E1 — enabling commit (created)

`88c8cf9 feat(hermes): activer le resume de courriels de Scout (/courriels)`

```
 hermes/ansible/group_vars/hermes/all/main.yml | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)
```

```diff
-hermes_scout_mail_enabled: false
+hermes_scout_mail_enabled: true
...
-    plugins.enabled: []
+    plugins.enabled: [scout_mail]
```

`hermes_scout_mail_inbox_id` was already `scout-emploi@agentmail.to`. The presence of `vault_hermes_job_search_agentmail_api_key` was NOT verified (that would need the vault to be read; it is accepted on the owner's statement of 2026-11-21).

Environment incident, fixed (no repo change): the first commit attempt failed in the `ansible-lint` pre-commit hook. The worktree had no `.venv`, so uv created one on Python 3.15 and `rpds-py` 0.30.0 (PyO3 0.27.2, max Python 3.14) failed to build. Fix: `uv sync --python 3.12` (same interpreter as the main checkout, 3.12.12), and `.envrc` copied from the main checkout (gitignored). The second attempt passed every hook.

### E2 — offline tests (executed)

- Image `nousresearch/hermes-agent:v0.22.5` is present locally (`sha256:49b70739d2e8…`), so the image tests ran.
- `uv run pytest hermes/tests -q`: `1 failed, 872 passed, 27 skipped in 1926.51s`.
- Targeted re-run `uv run pytest hermes/tests/test_scout_mail_image.py hermes/tests/test_scout_mail_role.py -q -rs`: `1 failed, 18 passed`, no skips (the image tests ran and passed).
- Failure:

```
hermes/tests/test_scout_mail_role.py:116
>   assert gv["hermes_scout_mail_enabled"] is False and gv["hermes_scout_mail_inbox_id"] == "scout-emploi@agentmail.to"
E   assert (True is False)
```

The test pins the disabled state on purpose. Line 118 also asserts `scout["config"]["plugins.enabled"] == []`. It cannot pass with the enabling commit. The rest of the test (no key in any declaration, no plugin key for cafe-ia/default, no `agentmail` in Scout's toolsets, MCP allowlist, no AGENTMAIL in `hermes.env.j2`) is still useful when the feature is on.

Why stop here: AC2 requires the offline tests to pass. Making them pass needs a change to a second file. That breaks AC1 ("only the two values changed") and E1 ("Nothing else changes"), and the owner's GO did not cover it. The mission limits say to stop on any failure. E4 was not started, although it is read-only, so that the steps stay in order.

### E3 — before state (read-only, 2026-11-24T15:50:36Z)

Runbook §2 step 5:

```
0f3f6948495a4322fa98965191158792fbaf3259154ba694bc0bd729fbc314aa  config.yaml
c4bc51133ee81dabd78de941cd58813c049bdf414b72a6b543dab62a1eaec8aa  profiles/cafe-ia/config.yaml
054ec6157eadde92d33d5e568638f7158f49877cb6aaa3569b08a881cb1241f0  profiles/job-search/config.yaml
b08468d8021d6b6404e386e5191204195a374a6b54b23a4574cc9c53b2aafd68  profiles/cafe-ia/SOUL.md
7dc753fe06306cb334bb2c25f7fb4cb26aa6ca317d8e12fb6f7cd98607a4fd0a  profiles/job-search/SOUL.md
a3b4e2c2360ef2a12b9dda4e84bb70f1b5113c135adf9bb04ee8fc760f1d0325  SOUL.md
fb2f043f1a0255c2abf333e7ff77ed02c1669f6e2777b2e399f6cca974458f73  /etc/hermes/config.yaml
```

- Container `hermes`: `restarts=0 started=2026-11-20T03:45:34.817392945Z status=running` (no Docker healthcheck defined).
- `gateway_state.json`: `pid 189`, `served_profiles ['default', 'cafe-ia', 'job-search']`. Platforms: `api_server`, `telegram`, `cafe-ia:telegram`, `job-search:telegram` all `connected`. No `gateway.parked`.
- Plugin: `profiles/*/plugins/scout_mail` is absent for every profile, and `profiles/job-search/plugin-data/scout_mail` is absent.
- `grep -c scout_mail`: `logs/agent.log` (default) 0, `profiles/cafe-ia/logs/agent.log` 0, `profiles/job-search/logs/agent.log` 0.

Observation: the "first deployment after merge, even with the feature off" (runbook §1) of MR !109 was never applied on hermes-31. The plugin code is not deployed at all. So the next `--tags hermes` run will bring the whole plugin directory (code, `retire.py`, `settings.json`) plus Scout's `plugins.enabled` key, whatever the switch value. That is consistent with the expected check-mode diff, but it is larger than a toggle.

Note for E6: the default profile's log is `logs/agent.log` at the data root, not `profiles/default/logs/agent.log`.

## Acceptance criteria

| AC | Status | Evidence |
|---|---|---|
| AC1 single enabling commit, only the two values | VERIFIED | `88c8cf9`, 1 file, 2+/2- (above) |
| AC2 offline tests pass | FAIL | 1 failed / 872 passed / 27 skipped; `test_role_04` |
| AC3 check-mode diff matches runbook §3 | NOT_VERIFIED | E4 not run |
| AC4 deploy OK, `hermes_checks.py scout-mail` OK, `changed=0` | NOT_VERIFIED | E5 not run |
| AC5 plugin for Scout only, ledger armed | NOT_VERIFIED | E6 not run |
| AC6 no regression | NOT_APPLICABLE | hermes-31 untouched; before state above |

## Repository and infrastructure state

- Branch `feat/scout-mail-enable`: `88c8cf9` (E1) + one commit with `mission.md` and this report. Pushed to origin, draft MR opened, not merged.
- CI: no deploy job exists in `.gitlab-ci.yml` (lint/security/renovate only), so the push deploys nothing.
- hermes-31: no change. No playbook run, check mode included. No restart.
- Deployment time: none.
- Delegations to subagents: none.

## Decisions required

D1 — how to reconcile `test_role_04` with the enabled state. Work is blocked until this is decided.

- A (recommended): add a test-only commit on this branch that makes `test_role_04` follow the switch: assert `plugins.enabled == (["scout_mail"] if enabled else [])` and drop the hard `is False`. Keep every other assertion. AC1 then reads as "one enabling config commit + one test commit". The revert for rollback stays the config commit alone, and the test still passes after a revert.
- B: amend E1 to carry the test change too (one commit, two files). This makes the revert of the commit revert the test as well. It changes the meaning of AC1.
- C: keep the test pinned to `False`, accept the red test, and deploy anyway. Not recommended: a red suite on main would hide future regressions.

With A or B, rerun E2, then continue with E4 under the same GO, if the owner confirms that the GO still applies.

## Recommended next action

Owner decides D1. Then the executor (new GO line in mission.md) runs E2 again → E4 check mode → E5 → E6. Owner approval is required. Nothing is pending on hermes-31.

## Owner Telegram test (after a successful deploy only)

Runbook §4 rows 1–5: synthetic mail A then `/courriels`; injection mail B then `/courriels`; reply "fais ce qu'il demande" to the digest (fixed refusal); normal Scout request after `/new`; Nora/Kaféine ordinary questions and `/courriels` to Nora (not a command).

## Rollback reminder

Not applicable now (nothing deployed). After a deploy: runbook §6 (revert of the enabling commit = staging; replay `--tags hermes` = applying). Never apply it before §8.1 step 4: Scout parked, `retire.py --delete` exit 0 with `inventory empty: 0 sessions`.
