"""Filters for the hermes_agent role: profile payload selection, config comparison."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from typing import Any

# Bytecode is a by-product of running the tests on the workstation: never ship
# it. Matched on every path component, so a nested __pycache__ goes too.
EXCLUDED_PATTERNS = ("__pycache__", "*.pyc", "*.pyo")

# Seeded once by soul_seed.yml, then owned by Hermes and the user.
SEEDED_FILES = ("SOUL.md",)


def hermes_profile_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the community.general.filetree items Ansible owns in a profile.

    Drops bytecode caches and the seeded files, which follow the seed-once
    rule instead of being overwritten on every run.
    """
    kept = []
    for item in items:
        parts = item["path"].split("/")
        if any(fnmatch(part, pattern) for part in parts for pattern in EXCLUDED_PATTERNS):
            continue
        if item["path"] in SEEDED_FILES:
            continue
        kept.append(item)
    return kept


def hermes_config_equal(current_json: str, desired: Any) -> bool:
    """Compare `hermes config get --json` output with the desired value.

    Both sides go through canonical JSON (sorted keys), which keeps types
    apart: true != "true", 42 != "42", 1 != 1.0, and lists stay ordered. The
    previous comparison lower-cased strings, so "True" matched true and a
    mapping compared as its repr. Unparseable output counts as different: the
    task then sets the key, and a value that never converges stays visible as
    a `changed` on every run instead of being hidden.
    """
    try:
        current = json.loads(current_json)
    except (TypeError, ValueError):
        return False
    return json.dumps(current, sort_keys=True) == json.dumps(desired, sort_keys=True)


def hermes_config_arg(value: Any) -> str:
    """Render a desired value as the argument `hermes config set` parses.

    Strings go raw: JSON-quoting them would store the quotes. Everything else
    goes as JSON, which `config set` coerces back (true/false, digits, and
    list/mapping literals through yaml.safe_load).
    """
    return value if isinstance(value, str) else json.dumps(value)


def hermes_dotenv_value(key: str, content: str) -> str:
    """Return the value of `key` in a .env text, or "" when the key is absent.

    Read like dotenv: the last assignment wins, an `export ` prefix is
    dropped, everything after the first `=` is kept verbatim apart from
    surrounding blanks (env_keys.yml refuses duplicated keys anyway). "" makes env_keys.yml remove
    the key, which is the state before M5 for a key M5 added.
    """
    pattern = re.compile(rf"^[ \t]*(?:export[ \t]+)?{re.escape(key)}[ \t]*=[ \t]*(.*?)[ \t]*$", re.MULTILINE)
    found = pattern.findall(content or "")
    return found[-1] if found else ""


MCP_PLATFORMS = ("telegram", "api_server", "cli", "cron")


def hermes_mcp_policy(profile: dict[str, Any]) -> dict[str, Any]:
    """Return the MCP policy judged by `hermes_checks.py mcp` for a profile.

    Servers come from whole-server config keys (`mcp_servers.<name>`); a
    sub-key such as Nora's `mcp_servers.kandidat.enabled` is not a server
    declaration. A profile without servers gets `{}`: no MCP server active.
    """
    cfg = profile.get("config") or {}
    servers = {key.split(".", 1)[1]: value for key, value in cfg.items()
               if key.startswith("mcp_servers.") and key.count(".") == 1}
    policy = dict(profile.get("mcp_policy") or {})
    if servers:
        policy["servers"] = servers
    return policy


def hermes_mcp_declaration_errors(profile: dict[str, Any]) -> list[str]:
    """Return what is wrong with a profile's MCP declaration, before any write.

    Rules: whole-server keys only; an explicit, non-empty `tools.include`, no
    `exclude`; utilities off; `trust` full or untrusted; a `mcp_policy` naming
    only declared servers, on known platforms; automatic writes only on a
    `full` server and only among its included tools; no secret-bearing key.
    """
    cfg = profile.get("config") or {}
    errors: list[str] = []
    for key in cfg:
        if key.startswith("mcp_servers.") and key.count(".") != 1 and profile.get("mcp_policy"):
            errors.append(f"{key}: declare whole servers only")
    policy = hermes_mcp_policy(profile)
    servers = policy.get("servers", {})
    if servers and not profile.get("mcp_policy"):
        errors.append("MCP servers declared without mcp_policy")
    if profile.get("mcp_policy") and not servers:
        errors.append("mcp_policy without any MCP server")
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            errors.append(f"{name}: not a mapping")
            continue
        if {"headers", "auth", "env", "command", "args"} & set(spec):
            errors.append(f"{name}: headers, auth, env, command or args never go through the repository")
        tools = spec.get("tools")
        include = tools.get("include") if isinstance(tools, dict) else None
        if not isinstance(include, list) or not include:
            errors.append(f"{name}: tools.include must be an explicit, non-empty list")
            include = []
        for tool in include:
            if not isinstance(tool, str) or any(char in tool for char in "*?["):
                errors.append(f"{name}: tools.include takes explicit tool names, never patterns ({tool!r})")
            elif tool.startswith("delete_"):
                errors.append(f"{name}: {tool} is a delete tool: never allowed")
        if isinstance(tools, dict) and "exclude" in tools:
            errors.append(f"{name}: tools.exclude is not allowed")
        if not isinstance(tools, dict) or tools.get("resources") is not False or tools.get("prompts") is not False:
            errors.append(f"{name}: tools.resources and tools.prompts must be false")
        if spec.get("trust") not in ("full", "untrusted"):
            errors.append(f"{name}: trust must be full or untrusted")
        if spec.get("trust") == "untrusted":
            costs = spec.get("tool_costs") if isinstance(spec.get("tool_costs"), dict) else {}
            limit = spec.get("spend_limit")
            if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
                errors.append(f"{name}: an approval-gated server needs spend_limit > 0 (0 means no limit)")
                limit = None
            for tool in include:
                cost = costs.get(tool)
                if limit is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost <= limit):
                    errors.append(f"{name}: {tool} needs a tool_costs entry above spend_limit (local per-call gate)")
        autos = (policy.get("auto_writes") or {}).get(name) or []
        if autos and spec.get("trust") != "full":
            errors.append(f"{name}: automatic writes on an approval-gated server")
        if set(autos) - set(include):
            errors.append(f"{name}: automatic writes outside tools.include")
    platforms = policy.get("platforms") or {}
    for platform in sorted(set(platforms) - set(MCP_PLATFORMS)):
        errors.append(f"mcp_policy: unknown platform {platform}")
    for platform in MCP_PLATFORMS if servers else ():
        names = set(platforms.get(platform) or [])
        if names - set(servers):
            errors.append(f"mcp_policy.{platform}: undeclared servers")
        listed = set(cfg.get(f"platform_toolsets.{platform}") or [])
        if names != listed & set(servers) or (names and "no_mcp" in listed):
            errors.append(f"mcp_policy.{platform}: differs from platform_toolsets.{platform}")
    if set(policy.get("auto_writes") or {}) - set(servers):
        errors.append("mcp_policy.auto_writes: undeclared servers")
    return errors


class FilterModule:
    """Expose the filters to Ansible."""

    def filters(self) -> dict[str, Any]:
        """Return the filter table."""
        return {
            "hermes_profile_payload": hermes_profile_payload,
            "hermes_config_equal": hermes_config_equal,
            "hermes_config_arg": hermes_config_arg,
            "hermes_mcp_policy": hermes_mcp_policy,
            "hermes_mcp_declaration_errors": hermes_mcp_declaration_errors,
            "hermes_dotenv_value": hermes_dotenv_value,
        }
