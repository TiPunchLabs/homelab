"""Tests for files/hermes_checks.py and filter_plugins/hermes_profiles.py.

The verdict functions are fed fixtures shaped like what Hermes v0.20.4 writes
(gateway/status.py write_runtime_status) and loads (managed_scope). No real
token, no container.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Mapping
from typing import Any

import pytest
from conftest import FAKE_TOKEN, ROLE

sys.path.insert(0, str(ROLE / "files"))
sys.path.insert(0, str(ROLE / "filter_plugins"))

import hermes_checks as hc
import hermes_profiles as hp

ALLOWLIST = "8854358938"
MANAGED_OK = {
    "DEEPSEEK_API_KEY": "sk-fake",
    "API_SERVER_ENABLED": "true",
    "API_SERVER_KEY": "fake",
    "TELEGRAM_ALLOWED_USERS": ALLOWLIST,
    "TELEGRAM_ALLOW_ALL_USERS": "false",
    "GATEWAY_ALLOW_ALL_USERS": "false",
}
CONFIG_KEYS = {"model.provider", "model.default", "dashboard.public_url"}


# --- managed layer (T02, T03, T11, T12, B7, B8) -----------------------------


def test_managed_contract_ok() -> None:
    """The M1 target layout passes."""
    assert hc.managed_errors(MANAGED_OK, CONFIG_KEYS, ALLOWLIST) == []


def test_allowlist_order_and_spaces_do_not_matter() -> None:
    """Allowlists compare as sets of ids."""
    env = MANAGED_OK | {"TELEGRAM_ALLOWED_USERS": "2, 8854358938"}
    assert hc.managed_errors(env, CONFIG_KEYS, "8854358938,2") == []


def test_t02_global_token_fails() -> None:
    """T02/B7: a TELEGRAM_BOT_TOKEN left in managed is refused, without its value."""
    errors = hc.managed_errors(MANAGED_OK | {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}, CONFIG_KEYS, ALLOWLIST)
    assert errors == ["TELEGRAM_BOT_TOKEN must not be in managed .env"]
    assert FAKE_TOKEN not in str(errors)


@pytest.mark.parametrize("value", [None, "", "  "])
def test_t03_t11_missing_allowlist_fails(value: str | None) -> None:
    """T03/T11: managed without TELEGRAM_ALLOWED_USERS (or empty) is refused."""
    env = {k: v for k, v in MANAGED_OK.items() if k != "TELEGRAM_ALLOWED_USERS"}
    if value is not None:
        env["TELEGRAM_ALLOWED_USERS"] = value
    assert hc.managed_errors(env, CONFIG_KEYS, ALLOWLIST) == ["TELEGRAM_ALLOWED_USERS missing or empty in managed .env"]


def test_t03_allowlist_drift_fails() -> None:
    """T03: an allowlist that differs from the inventory is refused."""
    env = MANAGED_OK | {"TELEGRAM_ALLOWED_USERS": "8854358938,666"}
    assert hc.managed_errors(env, CONFIG_KEYS, ALLOWLIST) == [
        "TELEGRAM_ALLOWED_USERS in managed .env differs from inventory"
    ]


def test_t11_empty_expected_allowlist_fails_closed() -> None:
    """T11: the check itself refuses to pass when given no expected allowlist."""
    assert "no expected TELEGRAM_ALLOWED_USERS given" in hc.managed_errors(MANAGED_OK, CONFIG_KEYS, "")


@pytest.mark.parametrize("key", ["API_SERVER_PORT", "API_SERVER_HOST"])
def test_t12_global_api_port_fails(key: str) -> None:
    """T12/B8: API_SERVER_PORT/HOST in managed would pin every gateway to one socket."""
    assert hc.managed_errors(MANAGED_OK | {key: "8642"}, CONFIG_KEYS, ALLOWLIST) == [
        f"{key} must not be in managed .env"
    ]


@pytest.mark.parametrize("flag", hc.ALLOW_ALL_FLAGS)
@pytest.mark.parametrize("value", ["true", "1", "YES", None])
def test_allow_all_bypass_must_be_pinned_off(flag: str, value: str | None) -> None:
    """D3: the opt-ins that bypass the allowlist must be pinned to false."""
    env = dict(MANAGED_OK)
    if value is None:
        del env[flag]
    else:
        env[flag] = value
    assert len(hc.managed_errors(env, CONFIG_KEYS, ALLOWLIST)) == 1


def test_managed_not_applied_fails() -> None:
    """The historical guard: an untraversable managed dir pins nothing."""
    assert hc.managed_errors(MANAGED_OK, set(), ALLOWLIST) == ["managed config not applied (model.provider not pinned)"]


def test_t01_default_env_key_check() -> None:
    """T01: the default .env must define a non-empty TELEGRAM_BOT_TOKEN."""
    assert hc.env_key_errors({"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}, "TELEGRAM_BOT_TOKEN") == []
    for values in ({}, {"TELEGRAM_BOT_TOKEN": ""}, {"TELEGRAM_BOT_TOKEN": None}):
        errors = hc.env_key_errors(values, "TELEGRAM_BOT_TOKEN")
        assert errors == ["TELEGRAM_BOT_TOKEN missing or empty"]


# --- Telegram health (T19, B4) ----------------------------------------------

PID, START = 154, 1714
S6_UP = f"up (pid {PID} pgid {PID}) 348602 seconds"
# Shape of /opt/data/gateway_state.json on hermes-30, 2026-10-13.
STATE: dict[str, Any] = {
    "kind": "hermes-gateway",
    "pid": PID,
    "start_time": START,
    "gateway_state": "running",
    "exit_reason": None,
    "platforms": {
        "api_server": {"state": "connected", "writer_pid": PID, "writer_start_time": START},
        "telegram": {
            "state": "connected",
            "error_code": None,
            "error_message": None,
            "writer_pid": PID,
            "writer_start_time": START,
            "needs_attention": False,
        },
    },
}


def live(_: Mapping[str, Any]) -> bool:
    """Liveness stub: the recorded process is alive."""
    return True


def dead(_: Mapping[str, Any]) -> bool:
    """Liveness stub: the recorded process is gone."""
    return False


def with_telegram(**fields: Any) -> dict[str, Any]:
    """Return STATE with the telegram entry updated."""
    state = copy.deepcopy(STATE)
    state["platforms"]["telegram"].update(fields)
    return state


def test_t19_connected() -> None:
    """T19: connected, written by the live supervised process."""
    ok, message = hc.telegram_verdict(STATE, S6_UP, live)
    assert ok, message
    assert message == f"telegram connected (gateway pid {PID})"


@pytest.mark.parametrize("state", ["retrying", "fatal", "connecting", "disconnected", "paused"])
def test_t19_not_connected(state: str) -> None:
    """T19: every non-connected state Hermes writes is a failure."""
    ok, message = hc.telegram_verdict(with_telegram(state=state), S6_UP, live)
    assert not ok
    assert repr(state) in message


@pytest.mark.parametrize("state", [None, "", "CONNECTED", 1, True])
def test_t19_unknown_state(state: Any) -> None:
    """T19: an unknown or missing state value is a failure, never assumed fine."""
    assert not hc.telegram_verdict(with_telegram(state=state), S6_UP, live)[0]


@pytest.mark.parametrize("state", [None, [], "garbage", 42])
def test_t19_absent_or_malformed_file(state: Any) -> None:
    """T19: no file, or not a JSON object."""
    ok, message = hc.telegram_verdict(state, S6_UP, live)
    assert not ok
    assert "absent or malformed" in message


def test_t19_no_telegram_entry() -> None:
    """T19: the adapter never started (no token reached the gateway)."""
    state = copy.deepcopy(STATE)
    del state["platforms"]["telegram"]
    assert not hc.telegram_verdict(state, S6_UP, live)[0]
    state["platforms"] = "not a mapping"
    assert not hc.telegram_verdict(state, S6_UP, live)[0]


def test_t19_stale_entry_from_previous_process() -> None:
    """B4 trap: `connected` survives a restart; it must come from the current pid."""
    stale = with_telegram(writer_pid=99, writer_start_time=1)
    ok, message = hc.telegram_verdict(stale, S6_UP, live)
    assert not ok
    assert "previous gateway process" in message
    # Same pid number reused after a container restart, different start_time.
    assert not hc.telegram_verdict(with_telegram(writer_start_time=START - 1), S6_UP, live)[0]


def test_t19_file_written_by_another_pid_than_s6() -> None:
    """Level 3 must be about the process s6 supervises right now."""
    ok, message = hc.telegram_verdict(STATE, "up (pid 999 pgid 999) 5 seconds", live)
    assert not ok
    assert "s6 runs 999" in message


def test_t19_dead_writer() -> None:
    """The recorded process is dead: nothing it wrote counts."""
    assert not hc.telegram_verdict(STATE, S6_UP, dead)[0]


def test_t19_gateway_not_running() -> None:
    """startup_failed / degraded at gateway level is a failure."""
    state = copy.deepcopy(STATE)
    state["gateway_state"] = "startup_failed"
    assert not hc.telegram_verdict(state, S6_UP, live)[0]


@pytest.mark.parametrize("s6", ["down (exitcode 78) 3 seconds, normally up", "", "s6-svstat: fatal: unable to read"])
def test_t19_level2_gateway_down(s6: str) -> None:
    """Level 2: s6 does not report the gateway up (78 = token collision)."""
    ok, message = hc.telegram_verdict(STATE, s6, live)
    assert not ok
    assert message.startswith("level 2")


def test_main_usage_error_is_not_success() -> None:
    """A wrong invocation never exits 0."""
    assert hc.main([]) == 2
    assert hc.main(["telegram"]) == 2


# --- structured config comparison (T13, B6) ---------------------------------


@pytest.mark.parametrize(
    ("current_json", "desired"),
    [
        ("true", True),
        ("42", 42),
        ('"text"', "text"),
        ('["a", "b"]', ["a", "b"]),
        ('{"b": 1, "a": {"x": [1, 2]}}', {"a": {"x": [1, 2]}, "b": 1}),
        ("null", None),
    ],
)
def test_t13_equal_values(current_json: str, desired: Any) -> None:
    """T13: same value, same type -> equal (mapping key order ignored)."""
    assert hp.hermes_config_equal(current_json, desired)


@pytest.mark.parametrize(
    ("current_json", "desired"),
    [
        ('"true"', True),
        ("true", "true"),
        ('"42"', 42),
        ("42", "42"),
        ("1", True),
        ("1.0", 1),
        ('"True"', "true"),
        ('["b", "a"]', ["a", "b"]),
        ('{"a": 1}', {"a": "1"}),
        ('{"a": 1}', {"a": 1, "b": 2}),
        ("not json", "not json"),
        ("", ""),
    ],
)
def test_t13_different_values(current_json: str, desired: Any) -> None:
    """T13: true != "true", 42 != "42", 1 != true, lists keep order, garbage differs."""
    assert not hp.hermes_config_equal(current_json, desired)


@pytest.mark.parametrize(
    ("value", "arg"),
    [
        ("plain text", "plain text"),
        (True, "true"),
        (42, "42"),
        (["file", "web"], '["file", "web"]'),
        ({"tools": {"include": ["a"]}}, '{"tools": {"include": ["a"]}}'),
    ],
)
def test_t13_config_set_argument(value: Any, arg: str) -> None:
    """Strings go raw (no stored quotes); the rest as JSON for `config set` to coerce."""
    assert hp.hermes_config_arg(value) == arg


def test_t14_payload_filter() -> None:
    """T14: bytecode at any depth and the seeded SOUL.md are dropped."""
    items = [
        {"path": "SOUL.md", "state": "file"},
        {"path": "scripts", "state": "directory"},
        {"path": "scripts/a.py", "state": "file"},
        {"path": "scripts/__pycache__", "state": "directory"},
        {"path": "scripts/__pycache__/a.cpython-312.pyc", "state": "file"},
        {"path": "scripts/b.pyo", "state": "file"},
        {"path": "scripts/sub/__pycache__/c.pyc", "state": "file"},
        {"path": "docs/SOUL.md", "state": "file"},
    ]
    kept = [i["path"] for i in hp.hermes_profile_payload(items)]
    assert kept == ["scripts", "scripts/a.py", "docs/SOUL.md"]
