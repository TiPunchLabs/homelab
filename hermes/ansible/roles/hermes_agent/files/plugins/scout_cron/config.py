"""Settings of scout_cron, rendered by the role into ``settings.json`` next to the plugin.

Every limit has a hard bound: an out-of-range value is a settings error, and the plugin then refuses
every scheduling and record call (fail closed) instead of running with a widened limit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


class SettingsError(ValueError):
    """settings.json is missing, malformed or out of bounds."""


@dataclass(frozen=True)
class Limits:
    max_jobs: int = 5
    max_prompt_chars: int = 6000
    max_name_chars: int = 80
    journal_chars: int = 3000
    feedback_chars: int = 1500
    ledger_days: int = 180
    ledger_max: int = 5000
    run_tool_calls: int = 40
    run_web_calls: int = 20


# (minimum, maximum) accepted for each limit.
BOUNDS: dict[str, tuple[int, int]] = {
    "max_jobs": (1, 10),
    "max_prompt_chars": (200, 8000),
    "max_name_chars": (10, 120),
    "journal_chars": (200, 8000),
    "feedback_chars": (100, 4000),
    "ledger_days": (7, 730),
    "ledger_max": (100, 20000),
    "run_tool_calls": (5, 200),
    "run_web_calls": (1, 100),
}

_OWNER_ID = re.compile(r"^-?\d{1,20}$")


@dataclass(frozen=True)
class Settings:
    enabled: bool
    profile: str
    owner_user_ids: frozenset[str]
    display_timezone: str
    limits: Limits


def parse_settings(raw: Any) -> Settings:
    """Validate the decoded settings.json; raise SettingsError on anything unexpected."""
    if not isinstance(raw, dict):
        raise SettingsError("settings must be an object")
    unknown = set(raw) - {"enabled", "profile", "owner_user_ids", "display_timezone", "limits"}
    if unknown:
        raise SettingsError(f"unknown settings keys: {sorted(unknown)}")
    if not isinstance(raw.get("enabled"), bool):
        raise SettingsError("enabled must be a boolean")
    profile = raw.get("profile")
    if profile != "job-search":
        raise SettingsError("profile must be job-search")
    owners = raw.get("owner_user_ids")
    if not isinstance(owners, list) or not owners or not all(
            isinstance(o, str) and _OWNER_ID.match(o) for o in owners):
        raise SettingsError("owner_user_ids must be a non-empty list of numeric Telegram ids")
    tz = raw.get("display_timezone", "America/Guadeloupe")
    if not isinstance(tz, str) or not re.match(r"^[A-Za-z_]+(/[A-Za-z_+-]+){0,2}$", tz):
        raise SettingsError("display_timezone must be an IANA name")
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except Exception as exc:
        raise SettingsError(f"display_timezone unknown: {tz}") from exc
    limits_raw = raw.get("limits") or {}
    if not isinstance(limits_raw, dict):
        raise SettingsError("limits must be an object")
    known = {f.name for f in fields(Limits)}
    if set(limits_raw) - known:
        raise SettingsError(f"unknown limits: {sorted(set(limits_raw) - known)}")
    values: dict[str, int] = {}
    for name in known:
        value = limits_raw.get(name, getattr(Limits, name))
        low, high = BOUNDS[name]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise SettingsError(f"limit {name} must be an integer in [{low}, {high}]")
        values[name] = value
    limits = Limits(**values)
    if limits.run_web_calls > limits.run_tool_calls:
        raise SettingsError("run_web_calls cannot exceed run_tool_calls")
    return Settings(enabled=raw["enabled"], profile=profile, owner_user_ids=frozenset(owners),
                    display_timezone=tz, limits=limits)


def load_settings(path: Path) -> Settings:
    """Read and validate settings.json."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SettingsError(f"settings unreadable: {type(exc).__name__}") from exc
    return parse_settings(raw)
