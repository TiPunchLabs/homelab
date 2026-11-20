"""Trusted settings of the scout_mail plugin: inbox binding, endpoints and hard limits.

Settings come only from ``settings.json`` deployed by Ansible next to the plugin. Nothing here
is ever derived from a mail, a model output or a chat argument. Any invalid or missing value
fails closed (``SettingsError``): the command then answers a fixed French refusal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

AGENTMAIL_HOSTS = frozenset({"api.agentmail.to", "api.agentmail.eu"})
MODEL_HOSTS = frozenset({"api.deepseek.com"})
INBOX_ID_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63}){1,8}$")
MODEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
USER_ID_RE = re.compile(r"^[0-9]{1,20}$")


class SettingsError(ValueError):
    """Settings are missing or invalid; the plugin must refuse to act."""


@dataclass(frozen=True)
class Limits:
    """Hard ceilings, all enforced in trusted code before or around the model call."""

    messages_per_request: int = 8
    max_pages: int = 1
    list_response_max_bytes: int = 262_144
    get_response_max_bytes: int = 262_144
    html_input_max_chars: int = 200_000
    subject_max_chars: int = 160
    sender_max_chars: int = 120
    body_max_chars: int = 3_000
    attachments_listed_max: int = 5
    attachment_name_max_chars: int = 80
    model_context_max_chars: int = 20_000
    model_calls_per_request: int = 1
    model_max_output_tokens: int = 1_200
    model_response_max_bytes: int = 65_536
    http_retries: int = 1
    retry_after_max_s: float = 2.0
    http_timeout_s: float = 10.0
    model_timeout_s: float = 40.0
    wall_clock_s: float = 75.0
    reply_max_chars: int = 3_500

    _BOUNDS = {
        "messages_per_request": (1, 20),
        "max_pages": (1, 3),
        "list_response_max_bytes": (4_096, 1_048_576),
        "get_response_max_bytes": (4_096, 1_048_576),
        "html_input_max_chars": (1_000, 1_000_000),
        "subject_max_chars": (20, 500),
        "sender_max_chars": (20, 300),
        "body_max_chars": (200, 20_000),
        "attachments_listed_max": (0, 20),
        "attachment_name_max_chars": (10, 200),
        "model_context_max_chars": (2_000, 80_000),
        "model_calls_per_request": (0, 2),
        "model_max_output_tokens": (100, 4_000),
        "model_response_max_bytes": (4_096, 262_144),
        "http_retries": (0, 2),
        "retry_after_max_s": (0.0, 10.0),
        "http_timeout_s": (1.0, 30.0),
        "model_timeout_s": (5.0, 120.0),
        "wall_clock_s": (10.0, 180.0),
        "reply_max_chars": (500, 3_800),
    }

    def __post_init__(self) -> None:
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            value = getattr(self, f.name)
            lo, hi = self._BOUNDS[f.name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
                raise SettingsError(f"limit {f.name} out of bounds [{lo}, {hi}]")


@dataclass(frozen=True)
class Settings:
    """Validated plugin settings."""

    enabled: bool
    profile: str
    inbox_id: str
    owner_user_ids: frozenset[str]
    agentmail_host: str = "api.agentmail.to"
    model_host: str = "api.deepseek.com"
    model: str = "deepseek-v4-flash"
    agentmail_key_env: str = "AGENTMAIL_API_KEY"
    model_key_env: str = "DEEPSEEK_API_KEY"
    retention_days: int = 30
    limits: Limits = field(default_factory=Limits)

    @property
    def agentmail_base(self) -> str:
        """Fixed API root; the only AgentMail prefix requests are built from."""
        return f"https://{self.agentmail_host}/v0"

    @property
    def model_url(self) -> str:
        """Fixed chat-completions endpoint of the configured provider."""
        return f"https://{self.model_host}/v1/chat/completions"


_ALLOWED_KEYS = {
    "enabled", "profile", "inbox_id", "owner_user_ids", "agentmail_host", "model_host", "model",
    "retention_days", "limits",
}


def parse_settings(raw: Any) -> Settings:
    """Validate a decoded settings mapping; raise ``SettingsError`` on anything unexpected."""
    if not isinstance(raw, dict):
        raise SettingsError("settings must be a mapping")
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise SettingsError(f"unknown settings keys: {sorted(unknown)}")
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise SettingsError("enabled must be a boolean")
    profile = raw.get("profile")
    if not isinstance(profile, str) or not PROFILE_NAME_RE.fullmatch(profile):
        raise SettingsError("invalid profile")
    inbox_id = raw.get("inbox_id")
    if not isinstance(inbox_id, str) or not INBOX_ID_RE.fullmatch(inbox_id):
        raise SettingsError("invalid inbox_id")
    owners = raw.get("owner_user_ids")
    if (not isinstance(owners, list) or not owners
            or not all(isinstance(u, str) and USER_ID_RE.fullmatch(u) for u in owners)):
        raise SettingsError("owner_user_ids must be a non-empty list of numeric ids")
    agentmail_host = raw.get("agentmail_host", "api.agentmail.to")
    if agentmail_host not in AGENTMAIL_HOSTS:
        raise SettingsError("agentmail_host not allowed")
    model_host = raw.get("model_host", "api.deepseek.com")
    if model_host not in MODEL_HOSTS:
        raise SettingsError("model_host not allowed")
    model = raw.get("model", "deepseek-v4-flash")
    if not isinstance(model, str) or not MODEL_NAME_RE.fullmatch(model):
        raise SettingsError("invalid model")
    retention = raw.get("retention_days", 30)
    if isinstance(retention, bool) or not isinstance(retention, int) or not 1 <= retention <= 90:
        raise SettingsError("retention_days out of bounds [1, 90]")
    limits_raw = raw.get("limits", {})
    if not isinstance(limits_raw, dict):
        raise SettingsError("limits must be a mapping")
    known = {f.name for f in fields(Limits) if not f.name.startswith("_")}
    if set(limits_raw) - known:
        raise SettingsError(f"unknown limits: {sorted(set(limits_raw) - known)}")
    try:
        limits = Limits(**limits_raw)
    except TypeError as exc:
        raise SettingsError("invalid limits") from exc
    return Settings(
        enabled=enabled, profile=profile, inbox_id=inbox_id, owner_user_ids=frozenset(owners),
        agentmail_host=agentmail_host, model_host=model_host, model=model,
        retention_days=retention, limits=limits,
    )


def load_settings(path: Path) -> Settings:
    """Read and validate ``settings.json``; any I/O or JSON error fails closed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SettingsError("settings file unreadable") from exc
    return parse_settings(raw)
