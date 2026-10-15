"""Filters for the hermes_agent role: profile payload selection, config comparison."""

from __future__ import annotations

import json
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


class FilterModule:
    """Expose the filters to Ansible."""

    def filters(self) -> dict[str, Any]:
        """Return the filter table."""
        return {
            "hermes_profile_payload": hermes_profile_payload,
            "hermes_config_equal": hermes_config_equal,
            "hermes_config_arg": hermes_config_arg,
        }
