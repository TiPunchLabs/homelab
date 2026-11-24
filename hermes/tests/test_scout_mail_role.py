"""SCOUT-MAIL-01 — Ansible wiring: the real tasks/scout_mail.yml on localhost, and the declarations.

Every value is a fake: a sentinel AgentMail key, a synthetic inbox. Nothing reaches hermes-31.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import ROLE, RunTasks, recap

GROUP_VARS = ROLE.parents[1] / "group_vars/hermes/all/main.yml"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
SENTINEL = "am_SENTINEL_ROLE_KEY_do_not_leak_55aa"
INBOX = "lab-scout@agentmail.to"


def variables(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    enabled = bool(extra.get("hermes_scout_mail_enabled"))
    declared = extra.pop("declared", ["scout_mail"] if enabled else [])
    return {
        "hermes_install_dir": str(tmp_path / "install"),
        "hermes_data_dir": str(tmp_path / "data"),
        "hermes_telegram_allowed_users": "111, 222",
        "hermes_profiles": [{"name": "cafe-ia", "config": {}},
                            {"name": "job-search", "config": {"plugins.enabled": declared}}],
        **extra,
    }


def env_file(tmp_path: Path) -> Path:
    return tmp_path / "data/profiles/job-search/.env"


def plugin_dir(tmp_path: Path) -> Path:
    return tmp_path / "data/profiles/job-search/plugins/scout_mail"


def test_role_01_disabled_by_default_deploys_inert_code_and_disabled_settings(run_tasks: RunTasks, tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    result = run_tasks("scout_mail.yml", variables(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads((plugin_dir(tmp_path) / "settings.json").read_text())
    assert settings["enabled"] is False and settings["profile"] == "job-search"
    assert settings["owner_user_ids"] == ["111", "222"] and settings["limits"] == {}
    assert oct((plugin_dir(tmp_path) / "settings.json").stat().st_mode & 0o777) == "0o640"
    files = sorted(p.name for p in plugin_dir(tmp_path).iterdir())
    assert files == ["__init__.py", "config.py", "plugin.yaml", "render.py", "retire.py", "sanitize.py",
                     "service.py", "settings.json", "summarize.py", "taint.py", "transport.py"]
    assert (tmp_path / "install/.multiplex-restart-pending").read_text() == "pending\n"
    assert not env_file(tmp_path).exists() or "AGENTMAIL_API_KEY" not in env_file(tmp_path).read_text()
    second = run_tasks("scout_mail.yml", variables(tmp_path))
    assert recap(second)["changed"] == 0, second.stdout


def test_role_02_enabled_requires_inbox_and_key_and_never_prints_the_key(run_tasks: RunTasks, tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    missing = run_tasks("scout_mail.yml", variables(tmp_path, hermes_scout_mail_enabled=True,
                                                    vault_hermes_job_search_agentmail_api_key=SENTINEL))
    assert missing.returncode != 0 and not plugin_dir(tmp_path).exists()
    no_key = run_tasks("scout_mail.yml", variables(tmp_path, hermes_scout_mail_enabled=True,
                                                   hermes_scout_mail_inbox_id=INBOX))
    assert no_key.returncode != 0
    ok = run_tasks("scout_mail.yml", variables(tmp_path, hermes_scout_mail_enabled=True, hermes_scout_mail_inbox_id=INBOX,
                                               vault_hermes_job_search_agentmail_api_key=SENTINEL), "--diff", "-v")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    settings = json.loads((plugin_dir(tmp_path) / "settings.json").read_text())
    assert settings["enabled"] is True and settings["inbox_id"] == INBOX
    assert env_file(tmp_path).read_text() == f"AGENTMAIL_API_KEY={SENTINEL}\n"
    assert oct(env_file(tmp_path).stat().st_mode & 0o777) == "0o600"
    for out in (missing, no_key, ok):
        assert SENTINEL not in out.stdout + out.stderr
    assert SENTINEL not in "".join(p.read_text() for p in plugin_dir(tmp_path).iterdir())
    again = run_tasks("scout_mail.yml", variables(tmp_path, hermes_scout_mail_enabled=True, hermes_scout_mail_inbox_id=INBOX,
                                                  vault_hermes_job_search_agentmail_api_key=SENTINEL))
    assert recap(again)["changed"] == 0, again.stdout
    # Kill switch: the key leaves Scout's .env, settings say disabled.
    off = run_tasks("scout_mail.yml", variables(tmp_path))
    assert off.returncode == 0 and "AGENTMAIL_API_KEY" not in env_file(tmp_path).read_text()
    assert json.loads((plugin_dir(tmp_path) / "settings.json").read_text())["enabled"] is False


def test_role_02b_switch_out_of_sync_with_declaration_is_refused(run_tasks: RunTasks, tmp_path: Path) -> None:
    (tmp_path / "install").mkdir()
    on_without_decl = run_tasks("scout_mail.yml", variables(
        tmp_path, hermes_scout_mail_enabled=True, hermes_scout_mail_inbox_id=INBOX,
        vault_hermes_job_search_agentmail_api_key=SENTINEL, declared=[]))
    off_with_decl = run_tasks("scout_mail.yml", variables(tmp_path, declared=["scout_mail"]))
    extra_plugin = run_tasks("scout_mail.yml", variables(tmp_path, declared=["other"]))
    for result in (on_without_decl, off_with_decl, extra_plugin):
        assert result.returncode != 0 and SENTINEL not in result.stdout + result.stderr
    assert not plugin_dir(tmp_path).exists()


def test_role_03_plugin_settings_are_accepted_by_the_plugin(run_tasks: RunTasks, tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(ROLE / "files/plugins"))
    from scout_mail.config import load_settings

    (tmp_path / "install").mkdir()
    run_tasks("scout_mail.yml", variables(tmp_path, hermes_scout_mail_enabled=True, hermes_scout_mail_inbox_id=INBOX,
                                          vault_hermes_job_search_agentmail_api_key=SENTINEL,
                                          hermes_scout_mail_limits={"messages_per_request": 5}))
    s = load_settings(plugin_dir(tmp_path) / "settings.json")
    assert s.enabled and s.inbox_id == INBOX and s.limits.messages_per_request == 5
    assert s.owner_user_ids == frozenset({"111", "222"})


def test_role_04_only_scout_declares_the_plugin_and_no_key_in_declarations() -> None:
    gv = yaml.safe_load(GROUP_VARS.read_text())
    assert gv["hermes_scout_mail_enabled"] is False and gv["hermes_scout_mail_inbox_id"] == "scout-emploi@agentmail.to"
    scout = gv["hermes_profile_job_search"]
    assert scout["config"]["plugins.enabled"] == []  # literal, in sync with the switch (off)
    assert "AGENTMAIL_API_KEY" not in scout["env"]
    for other in (gv["hermes_profile_cafe_ia"], gv["hermes_default_nora"]):
        assert "plugins.enabled" not in other.get("config", {}) and "AGENTMAIL_API_KEY" not in other.get("env", {})
    assert "agentmail" not in json.dumps(scout["config"]["platform_toolsets.telegram"])
    assert set(scout["mcp_policy"]["platforms"]["telegram"]) == {"kandidat", "kandidat_confirm"}
    assert "AGENTMAIL" not in (ROLE / "templates/hermes.env.j2").read_text()  # never in the shared managed layer


def test_role_05_defaults_are_off() -> None:
    assert DEFAULTS["hermes_scout_mail_enabled"] is False and DEFAULTS["hermes_scout_mail_limits"] == {}
    assert DEFAULTS["hermes_scout_mail_agentmail_host"] == "api.agentmail.to"


@pytest.mark.parametrize("mode,profiles,expected", [
    (True, {"job-search": {"commands": ["courriels"], "hooks": ["pre_gateway_dispatch", "pre_llm_call", "pre_tool_call",
                                                                "transform_tool_result"], "loaded": True},
            "default": {"commands": [], "hooks": [], "loaded": False}}, []),
    (False, {"job-search": {"commands": [], "hooks": [], "loaded": False}}, []),
    (False, {"job-search": {"commands": ["courriels"], "hooks": [], "loaded": True}}, ["must not be active"]),
    (True, {"job-search": {"commands": ["courriels"], "hooks": [], "loaded": True}}, ["hooks missing"]),
    (True, {"job-search": {"commands": ["courriels"], "hooks": ["pre_gateway_dispatch", "pre_llm_call", "pre_tool_call",
                                                                "transform_tool_result"], "loaded": True},
            "cafe-ia": {"commands": ["courriels"], "hooks": [], "loaded": True}}, ["cafe-ia"]),
])
def test_role_06_post_deploy_check_verdict(mode: bool, profiles: dict, expected: list[str]) -> None:
    import sys

    sys.path.insert(0, str(ROLE / "files"))
    import hermes_checks as hc

    errors = hc.scout_mail_errors(profiles, mode, "job-search")
    assert all(any(e in err for err in errors) for e in expected) and (bool(errors) == bool(expected))
    assert hc.scout_mail_errors({**profiles, "_registry": {"toolsets_added": ["mail"]}}, mode, "job-search")
